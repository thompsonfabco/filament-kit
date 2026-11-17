"""Storage locations: the ordered list a new spool is put away by (ruling R79, docs/design 03 section 10.4).

The list lives in `storage.xml` beside the Hub's config file (atomic write, owner and mode as the config file). A Hub
that has none builds it once from the old config keys (`migrate`) and writes it; those keys then stay in config.json
untouched and are no longer read. The placement rule itself is in placement.py; the rename of the spools stored under
a renamed location is `inventory.rename_locations`.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import config

log = logging.getLogger("filament_kit.storage")

BULK, CONTAINERS = "bulk", "containers"
NONE, ANY, MATERIALS = "none", "any", "materials"
NOTICE = "Storage locations were converted. Check them."
VERSION = "1"
NAME_MAX = 100
_ID = re.compile(r"^loc-([1-9][0-9]*)$")


@dataclass(frozen=True)
class Problem:
    """One thing wrong in the list: the row (0-based position, None for the list), the field, and the two lines."""
    row: int | None
    field: str
    error: str
    fix: str


class StorageError(ValueError):
    """The list or its file is not usable. `problems` holds one Problem per cause; str() is the Error and Fix lines."""

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        first = problems[0]
        super().__init__(f"Error: {first.error}\nFix: {first.fix}")


@dataclass
class Location:
    name: str
    type: str = BULK
    id: str | None = None                  # loc-<n>, given by the Hub; None for a row not saved yet
    limit: int | None = None               # bulk: spools; None = no limit
    count: int | None = None               # containers: how many
    prefix: str | None = None              # containers: the exact text before the number
    fill: str = NONE
    materials: list[str] = field(default_factory=list)
    overflow: bool = False
    default_overflow: bool = False
    sealed: bool = False

    def container_prefix(self) -> str:
        return self.prefix if self.prefix is not None else self.name + " "

    def container_name(self, n: int) -> str:
        return f"{self.container_prefix()}{n:02d}"       # at least two digits: 01 ... 99, 100


@dataclass
class Storage:
    locations: list[Location] = field(default_factory=list)
    next_id: int = 1                       # the high-water mark: an id once given is never given again
    converted: bool = False                # the migration kept two roles apart: the group shows NOTICE
    rename_pending: bool = False           # a rename job (inventory.rename_locations) is not finished

    # ---- lookups
    def by_name(self, name: str) -> Location | None:
        low = name.casefold()
        return next((x for x in self.locations if x.name.casefold() == low), None)

    def default_overflow(self) -> Location:
        return next(x for x in self.locations if x.default_overflow)

    def sealed_location(self) -> Location:
        return next(x for x in self.locations if x.sealed)

    def new_id(self) -> str:
        used = {int(m.group(1)) for x in self.locations if x.id and (m := _ID.match(x.id))}
        self.next_id = max(self.next_id, max(used, default=0) + 1)
        out = f"loc-{self.next_id}"
        self.next_id += 1
        return out

    # ---- how full (taken: spool location text -> number of spools, or a set of the texts as today's "taken")
    def used(self, loc: Location, taken) -> int:
        counts = counts_of(taken)
        if loc.type == BULK:
            return counts.get(loc.name, 0)
        return sum(1 for n in range(1, (loc.count or 0) + 1) if counts.get(loc.container_name(n), 0) > 0)

    def free(self, loc: Location, taken) -> int | None:
        """Free containers, or spools left under the limit; None = no limit."""
        if loc.type == CONTAINERS:
            return (loc.count or 0) - self.used(loc, taken)
        return None if loc.limit is None else max(loc.limit - self.used(loc, taken), 0)

    def lowest_free(self, loc: Location, taken) -> str | None:
        """The lowest free container's name of an Individual containers location, else None."""
        counts = counts_of(taken)
        return next((loc.container_name(n) for n in range(1, (loc.count or 0) + 1)
                     if counts.get(loc.container_name(n), 0) == 0), None)

    def containers(self, loc: Location, taken) -> list[dict] | None:
        """The whole set in number order, [{name, number, taken}] (the `containers` field SL2 adds to the contract);
        None for Bulk storage. The `prefix` field is `loc.container_prefix()`."""
        if loc.type != CONTAINERS:
            return None
        counts = counts_of(taken)
        return [{"name": loc.container_name(n), "number": n, "taken": counts.get(loc.container_name(n), 0) > 0}
                for n in range(1, (loc.count or 0) + 1)]

    def describe(self, taken) -> list[dict]:
        """One dict per location in fill order, the fields of the `GET api/storage` rows (R79 section 4).
        (R457 C4: no field is added; the web app's "Automatic" line comes from the preview.)"""
        return [{"id": x.id, "name": x.name, "type": x.type, "limit": x.limit, "count": x.count,
                 "used": self.used(x, taken), "free": self.free(x, taken), "fill": x.fill,
                 "materials": list(x.materials), "overflow": x.overflow, "default_overflow": x.default_overflow,
                 "sealed": x.sealed, "position": i + 1} for i, x in enumerate(self.locations)]


def is_container_name(loc: Location, text: str) -> bool:
    """`text` is the set's prefix followed only by digits (a container's name, whatever the set's count)."""
    pre = loc.container_prefix()
    return loc.type == CONTAINERS and text.startswith(pre) and text[len(pre):].isdigit()


def counts_of(taken) -> Counter:
    """A Counter of spools per location text from a Counter or dict (counts) or from a set or list of texts, each one
    spool: today's "taken" set is the same thing with every count 1."""
    if isinstance(taken, dict):
        return Counter({k: int(v) for k, v in taken.items() if v})
    return Counter(taken)


# ---------------------------------------------------------------- validation

def _line(v) -> bool:
    return isinstance(v, str) and v.isprintable()          # one line: no newline or other control character


def clashes(locations: list[Location]) -> set[tuple[str, str]]:
    """The (name, prefix) pairs where a location's name is a container name of a set (R79 22:06 and 22:30)."""
    return {(x.name.casefold(), st_.container_prefix()) for i, x in enumerate(locations)
            for j, st_ in enumerate(locations)
            if i != j and st_.type == CONTAINERS and isinstance(x.name, str) and is_container_name(st_, x.name)}


def validate(locations: list[Location], before: list[Location] | None = None, *,
             check_clashes: bool = True) -> list[Problem]:
    """What is wrong in the list. A name that is a container name of a set is refused only when it is NEW: a clash
    already in `before` (the saved list) survives edits of other fields; `check_clashes=False` (reading the file,
    the migration) never refuses one, so an upgraded Hub can always place spools (R79 22:30)."""
    known = clashes(before) if before else set()
    out: list[Problem] = []
    seen: dict[str, int] = {}
    ids: set[str] = set()
    for i, x in enumerate(locations):
        def bad(fld, error, fix):
            out.append(Problem(i, fld, error, fix))
        name = x.name.strip() if isinstance(x.name, str) else ""
        if not name or not _line(x.name):
            bad("name", "Enter a name for the location.", "Type the name of a shelf, rack, drawer or box.")
        elif len(name) > NAME_MAX:
            bad("name", f"The name is longer than {NAME_MAX} characters.", f"Use at most {NAME_MAX} characters.")
        elif name.casefold() in seen:
            bad("name", f"There is already a location called {name}.", "Give each location its own name.")
        else:
            seen[name.casefold()] = i
        if x.id is not None:
            if not _ID.match(x.id) or x.id in ids:
                bad("id", f"The id {x.id!r} is not valid or is used twice.", "Leave the id empty for a new location.")
            ids.add(x.id)
        if x.type not in (BULK, CONTAINERS):
            bad("type", "The type is neither Bulk storage nor Individual containers.", "Choose one of the two.")
        elif x.type == BULK:
            if x.limit is not None and not (isinstance(x.limit, int) and not isinstance(x.limit, bool)
                                            and 1 <= x.limit <= 9999):
                bad("limit", "Enter a whole number, 1 or more.", "Use 1 to 9999, or leave the limit empty.")
        else:
            if not (isinstance(x.count, int) and not isinstance(x.count, bool) and 1 <= x.count <= 999):
                bad("count", "Enter a whole number, 1 or more.", "Use 1 to 999 containers.")
            if x.overflow or x.default_overflow:
                bad("overflow", "Individual containers cannot be overflow.", "Use Bulk storage for overflow.")
            if x.sealed:
                bad("sealed", "Individual containers cannot hold the sealed spools.", "Use Bulk storage.")
        if x.fill not in (NONE, ANY, MATERIALS):
            bad("fill", "The fill is not one of nothing, any material or these materials.", "Choose one.")
        elif x.fill == MATERIALS:
            if not x.materials:
                bad("materials", "Enter at least one material, e.g. PLA.", "Separate several with commas.")
            elif not all(_line(m) and m.strip() and len(m) <= NAME_MAX for m in x.materials):
                bad("materials", "A material name must be one line of 1 to 100 characters.", "Check the names.")
        if x.overflow and x.fill == ANY:
            bad("fill", "An overflow location cannot take any material automatically.",
                "Use Nothing, only when you choose it, or name the materials.")
        if x.default_overflow and not x.overflow:
            bad("overflow", "The default overflow must be an overflow location.", "Switch overflow on.")
    for i, x in enumerate(locations):          # a name that is a container's name, refused both ways (R79, 22:06)
        for j, st_ in enumerate(locations):
            if (check_clashes and i != j and st_.type == CONTAINERS and isinstance(x.name, str)
                    and is_container_name(st_, x.name)
                    and (x.name.casefold(), st_.container_prefix()) not in known):
                text = f"{x.name} is the name of a container in {st_.name}. Choose another name."
                fix = "Use a name that is not the set's prefix followed by a number."
                out.append(Problem(i, "name", text, fix))
                out.append(Problem(j, "name", text, fix))
    defaults = [i for i, x in enumerate(locations) if x.default_overflow]
    if len(defaults) != 1:
        out.append(Problem(None, "default_overflow", "There must be exactly one default overflow location.",
                           "Make one overflow location the default overflow."))
    sealed = [i for i, x in enumerate(locations) if x.sealed]
    if len(sealed) != 1:
        out.append(Problem(None, "sealed", "Exactly one location must take the sealed spools.",
                           "Choose one Bulk storage location for sealed spools."))
    return out


def check(locations: list[Location], before: list[Location] | None = None) -> None:
    problems = validate(locations, before)
    if problems:
        raise StorageError(problems)


# ---------------------------------------------------------------- XML

def _file() -> Path:
    return config.paths().etc / "storage.xml"


def to_xml(st: Storage) -> str:
    root = ET.Element("storage", {"version": VERSION})
    if st.converted:
        root.set("converted", "yes")
    if st.rename_pending:
        root.set("rename-pending", "yes")
    root.set("next-id", str(max(st.next_id, 1)))
    for x in st.locations:
        a = {"id": x.id or "", "name": x.name, "type": x.type}
        if x.type == BULK and x.limit is not None:
            a["limit"] = str(x.limit)
        if x.type == CONTAINERS:
            a["count"] = str(x.count)
            a["prefix"] = x.container_prefix()
        a["fill"] = x.fill
        for key, on in (("sealed", x.sealed), ("overflow", x.overflow), ("default-overflow", x.default_overflow)):
            if on:
                a[key] = "yes"
        el = ET.SubElement(root, "location", a)
        if x.fill == MATERIALS:
            for m in x.materials:
                ET.SubElement(el, "material").text = m
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def from_xml(text: str) -> Storage:
    def unreadable(why: str) -> StorageError:
        return StorageError([Problem(None, "file", f"The storage locations file cannot be read: {why}.",
                                     f"Restore {_file()} from a backup, or move it away to build the list again "
                                     f"from the old settings.")])
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise unreadable(str(e)) from None
    if root.tag != "storage" or root.get("version") != VERSION:
        raise unreadable("it is not a storage file of this version")
    locs: list[Location] = []
    for el in root:
        if el.tag != "location":
            raise unreadable(f"unexpected element {el.tag}")
        try:
            limit, count = el.get("limit"), el.get("count")
            locs.append(Location(
                name=el.get("name", ""), type=el.get("type", ""), id=el.get("id") or None,
                limit=int(limit) if limit is not None else None, count=int(count) if count is not None else None,
                prefix=el.get("prefix"), fill=el.get("fill", NONE),
                materials=[(m.text or "") for m in el.findall("material")],
                overflow=el.get("overflow") == "yes" or el.get("default-overflow") == "yes",
                default_overflow=el.get("default-overflow") == "yes", sealed=el.get("sealed") == "yes"))
        except ValueError:
            raise unreadable("a number is not a number") from None
    try:
        nxt = int(root.get("next-id", "1"))
    except ValueError:
        raise unreadable("next-id is not a number") from None
    problems = validate(locs, check_clashes=False)
    if problems:
        raise StorageError(problems)
    st = Storage(locs, nxt, root.get("converted") == "yes", root.get("rename-pending") == "yes")
    st.next_id = max(st.next_id, max((int(_ID.match(x.id).group(1)) for x in locs if x.id), default=0) + 1)
    return st


def load() -> Storage | None:
    """The saved list, None when there is no storage.xml. A file that cannot be read raises StorageError."""
    f = _file()
    try:
        text = f.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise StorageError([Problem(None, "file", f"The storage locations file cannot be read: {e}.",
                                    f"Check the owner and mode of {f} (as config.json), or restore it from a "
                                    f"backup.")]) from None
    return from_xml(text)


def save(st: Storage, before: Storage | None = None) -> None:
    """Validate, give every row without an id one, and write storage.xml atomically (mode and owner as config.json).
    A clash of names that the saved file (or `before`) already has is not refused again, a new one is."""
    if before is None:
        try:
            before = load()
        except StorageError:
            before = None
    check(st.locations, before.locations if before else None)
    for x in st.locations:
        if x.id is None:
            x.id = st.new_id()
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=f.name + ".", suffix=".tmp")
    tmp = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(to_xml(st))
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o640)
        config.grant_web_read(tmp)
        os.replace(tmp, f)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise


_warned = False


def current() -> Storage:
    """The list in force: storage.xml; when there is none (first start of this version, or a fresh install) it is
    built from the config file's old keys and written. A file that cannot be read raises, never defaults.

    The first start can be either unit: the Hub service (which can write the root-owned etc dir; the file gets the
    owner, mode 0640 and the web unit's read ACL of config.json) or the web unit (which cannot). A reader that cannot
    write uses the list migrated from the config file in memory (ids and names are the same the file will get, the
    migration is deterministic) and says so once in the log; it never writes a file the other unit could not read."""
    global _warned
    st = load()
    if st is None:
        st = migrate(config.load())
        try:
            save(st, before=st)                  # the migration never fails on a clash it carries over
        except PermissionError as e:
            if not _warned:
                _warned = True
                log.warning("storage.xml could not be written (%s); using the list migrated from config.json "
                            "until the Hub service writes it", e)
            return st
        if st.converted:
            log.warning(NOTICE)
    return st


def mark_rename_pending(flag: bool) -> None:
    """Set or clear `rename-pending` in storage.xml (no file: nothing to mark)."""
    st = load()
    if st is not None and st.rename_pending != flag:
        st.rename_pending = flag
        save(st)


def migrate_at_start() -> None:
    """Called when the Hub service starts: write storage.xml on the first start of this version. A file that cannot
    be read is logged (every use then raises the Error/Fix lines); it does not stop the service."""
    try:
        current()
    except StorageError as e:
        log.error("%s", e)


# ---------------------------------------------------------------- migration (R79 section 6)

def _clean(v) -> str:
    text = "".join(c if c.isprintable() else " " for c in v) if isinstance(v, str) else ""
    return text.strip()[:NAME_MAX].strip()


def migrate(cfg: dict) -> Storage:
    """The list the old keys `locations`, `placement.pla_location`, `.box_prefix`, `.box_count`, `.overflow` and
    `.sealed_location` stand for; it places every spool where the old rule did."""
    pl = cfg.get("placement") if isinstance(cfg.get("placement"), dict) else {}
    out: list[Location] = []
    converted = False

    def find(name: str) -> Location | None:
        low = name.casefold()
        return next((x for x in out if x.name.casefold() == low), None)

    for raw in cfg.get("locations") or []:                                                  # 1
        name = _clean(raw)
        if name and not find(name):
            out.append(Location(name))
    pla = _clean(pl.get("pla_location"))
    overflow_name = _clean(pl.get("overflow")) or "Overflow"
    sealed_name = _clean(pl.get("sealed_location")) or "Sealed stock"
    if pla:                                                                                 # 2
        x = find(pla)
        if not x:
            x = Location(pla)
            out.append(x)
        x.fill, x.materials = MATERIALS, ["PLA"]
    try:
        boxes = max(0, min(int(pl.get("box_count") or 0), 999))
    except (TypeError, ValueError):
        boxes = 0
    if boxes > 0:                                                                           # 3
        prefix = pl.get("box_prefix") if isinstance(pl.get("box_prefix"), str) else "Storage box "
        name = _clean(prefix.rstrip()) or "Container"
        box = Location(name, CONTAINERS, count=boxes, prefix=prefix, fill=ANY)
        roles = {pla.casefold(), overflow_name.casefold(), sealed_name.casefold()} - {""}
        where = next((i for i, x in enumerate(out) if x.name.casefold() == overflow_name.casefold()), len(out))
        if name.casefold() in roles:      # a place today's rule uses as one literal name: the bulk place keeps it
            box.name = f"{name} (containers)"[:NAME_MAX]
            while find(box.name):
                box.name = box.name[:NAME_MAX - 1] + "+"
            out.insert(where, box)
        elif (x := find(name)):           # a plain entry of that name becomes the set, in its place
            out[out.index(x)] = box
        else:
            out.insert(where, box)
        converted = box.name == "Container" or box.name.endswith(" (containers)")
        # a list entry that is a container name of this set is that container, not a location of its own
        # one that is the PLA, overflow or sealed place stays a Bulk storage location beside the set (the text is one
        # place, as today); the Hub says so with the notice
        out[:] = [x for x in out if x is box or x.name.casefold() in roles or not is_container_name(box, x.name)]
        converted = converted or any(is_container_name(box, n) for n in (pla, overflow_name, sealed_name) if n)
    x = find(overflow_name)                                                                 # 4
    if not x:
        x = Location(overflow_name)
        out.append(x)
    x.overflow = x.default_overflow = True
    x = find(sealed_name)                                                                   # 5
    if not x:
        x = Location(sealed_name)
        out.insert(0, x)
    x.sealed = True
    st = Storage(out, 1, converted)
    for x in st.locations:
        x.id = st.new_id()
    return st


# ---------------------------------------------------------------- renames (R79 section 3, "Rename")

@dataclass(frozen=True)
class Rename:
    """Spools stored under `old` move to `new`. For containers both are prefixes: "Storage box " -> "Dry box ",
    and a spool at `old` + digits goes to `new` + the same digits."""
    old: str
    new: str
    containers: bool = False

    @property
    def label(self) -> tuple[str, str]:
        return self.old.rstrip(), self.new.rstrip()


def renames(before: Storage, after: Storage) -> list[Rename]:
    """What a save changes in the names of the places spools are stored at, matched by id. A containers location
    whose prefix was its name plus a space follows the new name (the caller sets `prefix` with `follow_names`)."""
    old = {x.id: x for x in before.locations if x.id}
    out: list[Rename] = []
    for x in after.locations:
        o = old.get(x.id)
        if not o:
            continue
        if x.type == BULK and o.type == BULK and x.name != o.name:
            out.append(Rename(o.name, x.name))
        elif x.type == CONTAINERS and o.type == CONTAINERS and x.container_prefix() != o.container_prefix():
            out.append(Rename(o.container_prefix(), x.container_prefix(), True))
    return out


def follow_names(before: Storage, after: Storage) -> None:
    """A renamed Individual containers location gets the prefix of its new name plus one space (R79 C3), so its
    containers are renamed with it."""
    old = {x.id: x for x in before.locations if x.id}
    for x in after.locations:
        o = old.get(x.id)
        if o and x.type == CONTAINERS and o.type == CONTAINERS and x.name != o.name:
            x.prefix = x.name + " "


DEFAULT_OVERFLOW_NOTE = ("The default overflow has no limit, so the other overflow places are never used. "
                         "Give it a spool limit to let them fill.")


def default_overflow_starves_others(st: Storage) -> bool:
    """True when two or more overflow locations exist and the default overflow has no limit (R79 C1): the others
    are never reached. The Hub page, `spoolwarden locations` and the config menu show DEFAULT_OVERFLOW_NOTE then."""
    over = [x for x in st.locations if x.overflow]
    return len(over) >= 2 and st.default_overflow().limit is None


def rename_text(items: list[Rename], updated: int) -> str:
    pairs = ", ".join(f"{a} to {b}" for a, b in (r.label for r in items))
    return f"Renamed {pairs}. {updated} spool{'' if updated == 1 else 's'} updated."


def copy_of(st: Storage) -> Storage:
    return Storage([replace(x, materials=list(x.materials)) for x in st.locations], st.next_id, st.converted, st.rename_pending)
