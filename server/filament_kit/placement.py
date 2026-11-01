"""Storage placement rules for new spools."""


def place(items: list[dict], used: set[str], rules: dict) -> list[dict]:
    taken = set(used)
    out: list[dict] = []
    for item in items:
        if item.get("location"):
            out.append(dict(item))
        elif item.get("sealed") is not False:
            out.append({**item, "location": rules["sealed_location"]})
        elif str(item.get("material", "")).upper().startswith("PLA"):
            out.append({**item, "location": rules["pla_location"]})
        else:
            for _ in range(int(item.get("count", 1))):
                loc = _free_box(taken, rules)
                taken.add(loc)
                out.append({**item, "count": 1, "location": loc})
    return out


def _free_box(taken: set[str], rules: dict) -> str:
    for n in range(1, int(rules["box_count"]) + 1):
        name = f"{rules['box_prefix']}{n:02d}"
        if name not in taken:
            return name
    return rules["overflow"]
