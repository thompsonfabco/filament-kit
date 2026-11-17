"""Storage placement rules for new spools (ruling R79 section 2): one rule over the storage location list."""
from collections import Counter

from . import storage
from .storage import ANY, BULK, MATERIALS, Location, Storage


def as_storage(rules) -> Storage:
    """`rules` is the Storage list; the old `placement` dict (a caller or test that still holds one) is migrated
    in memory with the same rule, so there is one placement code path."""
    if isinstance(rules, Storage):
        return rules
    return storage.migrate({"locations": rules.get("locations") or [], "placement": rules})


def sealed_name(rules) -> str:
    return as_storage(rules).sealed_location().name


def place(items: list[dict], used, rules) -> list[dict]:
    """Each item with a location: its own, else the rule's choice, with `placed_by` saying which step chose it
    (sealed | material | any | overflow | overflow_none), so the result can tell the owner where a spool went and why.
    `used`: spools per location text (a Counter) or the set of location texts that are taken, one spool each.
    A count is placed spool by spool: one item may come back as several parts."""
    st = as_storage(rules)
    counts = storage.counts_of(used)
    out: list[dict] = []
    for item in items:
        n = int(item.get("count", 1))
        if item.get("location"):
            out.append(dict(item))
            counts[item["location"]] += n
        elif item.get("sealed") is not False:
            name = st.sealed_location().name                      # its limit is not applied to sealed spools
            counts[name] += n
            out.append({**item, "location": name, "placed_by": "sealed"})
        else:
            parts: list[dict] = []
            for _ in range(n):
                name, why = _choose(st, str(item.get("material", "")), counts)
                counts[name] += 1
                if parts and parts[-1]["location"] == name and parts[-1]["placed_by"] == why:
                    parts[-1]["count"] += 1                       # a bulk place takes the spools of one add together
                else:
                    parts.append({**item, "count": 1, "location": name, "placed_by": why})
            out.extend(parts)
    return out


def _room(st: Storage, loc: Location, counts: Counter) -> str | None:
    """The name a spool would get at `loc` (the location's name; a container's own), None when it has no room."""
    if loc.type == BULK:
        return loc.name if loc.limit is None or counts[loc.name] < loc.limit else None
    return st.lowest_free(loc, counts)


def _match(loc: Location, material: str) -> int:
    """Length of the longest of the location's material names the spool's material starts with (case ignored), else 0."""
    low = material.casefold()
    return max((len(m.strip()) for m in loc.materials if m.strip() and low.startswith(m.strip().casefold())),
               default=0)


def _choose(st: Storage, material: str, counts: Counter) -> tuple[str, str]:
    own = [(x, _match(x, material)) for x in st.locations if x.fill == MATERIALS]     # overflow places included
    best = max((n for _, n in own), default=0)
    candidate = bool(best)                                                          # a place that could take it
    if best:                                                                        # 3: only the longest names count
        for x in (x for x, n in own if n == best):
            if (name := _room(st, x, counts)):
                return name, "material"
    else:                                                                           # 4: no place names the material
        anys = [x for x in st.locations if not x.overflow and x.fill == ANY]
        candidate = bool(anys)
        for x in anys:
            if (name := _room(st, x, counts)):
                return name, "any"
    default = st.default_overflow()                                                 # 5: the default's limit counts
    why = "overflow" if candidate else "overflow_none"      # none: no place takes the material automatically
    for x in [default, *(x for x in st.locations if x.overflow and x is not default)]:
        if (name := _room(st, x, counts)):
            return name, why
    return default.name, why                    # all at their limit: the default takes the spool over it
