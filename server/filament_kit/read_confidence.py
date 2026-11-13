"""How sure the Label Reader was of each field: high, medium, low or not on the label (design S2.6, N4).

The rule, one for every engine:
  - a field with no value on the item is "not_on_label";
  - a field the reader guessed (named in the item's `estimates`) is "medium";
  - the local reader's own number for the field (`field_confidence`, else the item's `confidence`) gives "high" at
    HIGH or more, "medium" at MEDIUM or more, else "low";
  - anything else (the cloud reader gives no number) is "high". The cloud reader never gives "low".
`summary` folds the levels of a record's items into the fields to check, lowest level first."""
from __future__ import annotations

HIGH, MEDIUM = 0.8, 0.5
# the fields the reader reads off a label (the product line is worked out by the Hub, so it is left out)
READ_FIELDS = ("vendor", "name", "material", "color_hex", "net", "tare", "density", "nozzle", "bed", "nozzle_range",
               "bed_range", "price_per_kg")
LEVELS = ("high", "medium", "low", "not_on_label")


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def levels(item: dict) -> dict:
    """{field: level} for one read item (READ_FIELDS only)."""
    est = {str(x) for x in item.get("estimates") or []}
    fc = item.get("field_confidence") if isinstance(item.get("field_confidence"), dict) else {}
    out = {}
    for k in READ_FIELDS:
        v = item.get(k)
        if v is None or v == "" or (k == "vendor" and str(v).lower() == "unknown"):
            out[k] = "not_on_label"
            continue
        if k in est:
            out[k] = "medium"
            continue
        c = _num(fc.get(k))
        if c is None:
            c = _num(item.get("confidence"))
        out[k] = "high" if c is None or c >= HIGH else "medium" if c >= MEDIUM else "low"
    return out


def summary(all_levels: list[dict]) -> dict | None:
    """{level, low, medium, not_on_label}: `level` is "high" when every field is high, else the lowest level
    present ("low", then "medium", then "not_on_label"); the lists name the fields at each level (the same field
    on several items once). None when there is nothing to summarise (a record added by hand)."""
    all_levels = [x for x in all_levels if isinstance(x, dict) and x]
    if not all_levels:
        return None
    out = {"low": [], "medium": [], "not_on_label": []}
    for lv in all_levels:
        for k, v in lv.items():
            if v in out and k not in out[v]:
                out[v].append(k)
    lowest = next((k for k in ("low", "medium", "not_on_label") if out[k]), "high")
    return {"level": lowest, **out}


def engine(raw: dict) -> dict:
    """{reader, model, tier}: the engine that read it ("local" or "cloud"), its model name and the local tier."""
    u = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    return {"reader": raw.get("reader"), "model": u.get("model"), "tier": raw.get("tier")}
