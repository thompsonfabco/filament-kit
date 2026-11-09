"""Storage placement rules for new spools."""


def place(items: list[dict], used: set[str], rules: dict) -> list[dict]:
    """Each item with a location: its own, else the rules' choice, with `placed_by` saying which rule chose it
    (sealed | pla | box | overflow | no_boxes), so the result can tell the owner where a spool went and why."""
    taken = set(used)
    out: list[dict] = []
    for item in items:
        if item.get("location"):
            out.append(dict(item))
        elif item.get("sealed") is not False:
            out.append({**item, "location": rules["sealed_location"], "placed_by": "sealed"})
        elif str(item.get("material", "")).upper().startswith("PLA"):
            out.append({**item, "location": rules["pla_location"], "placed_by": "pla"})
        else:
            for _ in range(int(item.get("count", 1))):
                loc = _free_box(taken, rules)
                taken.add(loc)
                why = "box" if loc != rules["overflow"] else "overflow" if int(rules["box_count"]) > 0 else "no_boxes"
                out.append({**item, "count": 1, "location": loc, "placed_by": why})
    return out


def _free_box(taken: set[str], rules: dict) -> str:
    for n in range(1, int(rules["box_count"]) + 1):
        name = f"{rules['box_prefix']}{n:02d}"
        if name not in taken:
            return name
    return rules["overflow"]
