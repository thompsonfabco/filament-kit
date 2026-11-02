"""Where a preset's values come from, and the manufacturer-spec rules (ports of filament-ops gen.py and spec.py).

Priority, highest first: Spoolman data for the line's filaments, the owner's local library additions, the spec
library, the Bambu system parent; in-app edits go on top of all four (profiles.inapp).

Rules (spec section 6): published ranges are bounds. Only values that came from the Bambu parent are clamped;
values from Spoolman or from in-app edits are never changed, only reported when outside a bound. Midpoints are
never invented, temperature_vitrification is never set (Bambu uses it as a heat-creep threshold, not Tg) and
"nil" is never written. Fan OFF only for the exact published text "0", "0%" or "0 (off)". Hardened material ->
required_nozzle_HRC ["40"]. Chamber only on printers that have one, capped at that printer's maximum. The
library's filament_max_volumetric_speed is a 0.4 mm figure and caps 0.4 mm presets only.
"""
from __future__ import annotations

import collections
import copy
import json
import math
import re
import statistics
from dataclasses import dataclass

from ..library import Lookup

STD = "Direct Drive Standard"
HF = "Direct Drive High Flow"
NOZZLE_TEMPS = ["nozzle_temperature", "nozzle_temperature_initial_layer"]
PLATE_GROUPS = {"bed_all_plates": ["hot_plate_temp", "textured_plate_temp", "eng_plate_temp"],
                "hot_plate_temp": ["hot_plate_temp"], "textured_plate_temp": ["textured_plate_temp"],
                "cool_plate_temp": ["cool_plate_temp"]}
SET_FIELDS = ["nozzle_temperature_range_low", "nozzle_temperature_range_high", "filament_density",
              "filament_diameter", "filament_soluble", "filament_is_support", "filament_shrink"]
BED_KEYS = ["hot_plate_temp", "hot_plate_temp_initial_layer", "textured_plate_temp",
            "textured_plate_temp_initial_layer"]
ABRASIVE = re.compile(r"-(CF|GF)\b|CF\d|GF\d")
FAN_OFF = {"0", "0%", "0 (off)"}
MERGE_DICTS = ("fields", "published_ranges")
MERGE_VALUES = ("bambu_parent", "orca_parent", "material")
_COLOR_WORDS = r"^.*?(PLA\+? 2\.0|PETG|PLA\+?|TPU|ABS|ASA|PC|PA|CF|GF|72D|HS|Silk|Matte|Wood|Glow|Metal|Marble|Meta)\s*"
_RANGE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*")
NOTE_LABELS = (("bed_all_plates", "bed"), ("hot_plate_temp", "smooth PEI"), ("textured_plate_temp", "textured PEI"),
               ("cool_plate_temp", "cool plate"), ("chamber_temperatures", "chamber"), ("_nozzle_by_speed", "by speed"),
               ("filament_shrink", "shrink"), ("filament_retraction_length", "retraction mm"),
               ("filament_retraction_speed", "retraction mm/s"), ("fan_max_speed", "fan max"),
               ("fan_min_speed/fan_max_speed", "fan %"), ("overhang_fan_threshold", "overhang fan"),
               ("_print_speed", "speed"), ("_max_print_speed", "max speed"), ("_drying", "drying"),
               ("_annealing", "annealing"), ("_vitrification", "Tg"), ("_vicat", "Vicat"), ("_hdt", "HDT"),
               ("_hdt_0.45MPa", "HDT 0.45 MPa"), ("_hdt_1.8MPa", "HDT 1.8 MPa"), ("_nozzle_sizes", "nozzles"),
               ("_nozzle_sizes_supported", "nozzles"), ("_not_supported", "NOT supported"), ("_ams", "AMS"),
               ("_enclosure", "enclosure"), ("_chamber", "chamber"), ("_fan", "fan"), ("_plates", "plates"),
               ("_min_nozzle", "min nozzle"), ("_hardened_nozzle_required", "hardened nozzle"),
               ("_hardness", "hardness"), ("_diameter_tolerance", "diameter"), ("_fiber_content", "fibre"),
               ("_notes", "notes"))


# ---------- small helpers ----------

def s(v) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def fmt(v: float, pct: bool = False) -> str:
    out = f"{v:.2f}".rstrip("0").rstrip(".")
    return out + "%" if pct else out


def _num(v) -> float | None:
    """A usable Spoolman number: ints, floats and numeric strings; None, 0, bools and other text are not."""
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x and x == x and abs(x) != float("inf") else None


def _value(v) -> float | None:
    """A preset value as a number ("97%" -> 97), or None for "nil", "" and other text."""
    try:
        x = float(str(v).strip().rstrip("%"))
    except ValueError:
        return None
    return x if math.isfinite(x) else None   # "nan" / "inf" are not values


def _mode(xs):
    xs = [x for x in xs if x is not None]
    return collections.Counter(xs).most_common(1)[0][0] if xs else None


def variant_names(cfg: dict | None, n: int) -> list[str]:
    v = (cfg or {}).get("filament_extruder_variant")
    if isinstance(v, list) and len(v) == n:
        return v
    return {1: [STD], 2: [STD, HF], 3: [STD, HF, "Direct Drive E3D High Flow"],
            6: [STD, HF, "Direct Drive Extra High Flow", "Bowden Standard", "Bowden High Flow",
                "Bowden Extra High Flow"]}.get(n, [STD] * n)


# ---------- Spoolman ----------

@dataclass
class SpoolmanValues:
    material: str | None
    density: float | None
    cost: float
    nozzle: int | None
    bed: int | None
    nozzle_range: tuple[int, int] | None
    colors: str


def _nozzle_range(f: dict) -> tuple[int, int] | None:
    raw = (f.get("extra") or {}).get("nozzle_range") if isinstance(f.get("extra"), dict) else None
    if not isinstance(raw, str):
        return None
    try:
        text = json.loads(raw)
    except ValueError:
        return None
    m = _RANGE.fullmatch(text) if isinstance(text, str) else None
    if not m:
        return None
    lo, hi = round(float(m.group(1))), round(float(m.group(2)))
    return (lo, hi) if lo <= hi else None


def spoolman_values(filaments: list[dict]) -> SpoolmanValues:
    """What the line's Spoolman filaments say (port of gen.spoolman_values): the most common material, nozzle and bed
    temperature, the mean density and the median price per kg (0 = no price). None, 0 and non-numbers are skipped."""
    fs = [f for f in filaments if isinstance(f, dict)]
    dens = [x for x in (_num(f.get("density")) for f in fs) if x is not None]
    prices = []
    for f in fs:
        price, weight = _num(f.get("price")), _num(f.get("weight"))
        if price is not None and weight is not None and price > 0 and weight > 0:
            prices.append(price / weight * 1000)
    nozzle = _mode(_num(f.get("settings_extruder_temp")) for f in fs)
    bed = _mode(_num(f.get("settings_bed_temp")) for f in fs)
    names = {re.sub(_COLOR_WORDS, "", f["name"]) or f["name"] for f in fs if isinstance(f.get("name"), str)}
    return SpoolmanValues(
        material=_mode(f.get("material") for f in fs if isinstance(f.get("material"), str) and f["material"].strip()),
        density=round(statistics.mean(dens), 3) if dens else None,
        cost=round(statistics.median(prices), 2) if prices else 0,
        nozzle=round(nozzle) if nozzle is not None else None,
        bed=round(bed) if bed is not None else None,
        nozzle_range=_mode(_nozzle_range(f) for f in fs),
        colors=", ".join(sorted(names)))


def temps_for_variants(key: str, variants: list[str], template: dict | None, sv_nozzle) -> dict:
    """Per-variant nozzle temps from the Spoolman temperature: the standard variant gets it, the others the same
    plus the template's offset for that variant (port of gen.temps_for_variants without user presets)."""
    out = {var: None for var in variants}
    if not sv_nozzle:
        return out
    std = s(sv_nozzle)
    out[STD] = std
    t = template.get(key) if template else None
    tnames = variant_names(template, len(t)) if isinstance(t, list) and t else []
    for var in variants:
        if out[var] is None and var in tnames and STD in tnames:
            a, b = _value(t[tnames.index(var)]), _value(t[tnames.index(STD)])
            if a is not None and b is not None:
                out[var] = s(float(std) + a - b)
    return out


def _list_number(values, i: int):
    """values[i] when it is a valid finite number, else None."""
    if isinstance(values, list) and i < len(values) and _value(values[i]) is not None:
        return values[i]
    return None


def apply_spoolman(cfg: dict, sv: SpoolmanValues, *, variants: list[str], template: dict) -> set[str]:
    """Set what Spoolman says on cfg (in place); returns the keys set, which are protected from clamping."""
    keys = set()
    for key in NOZZLE_TEMPS:
        vals = temps_for_variants(key, variants, template, sv.nozzle)
        if any(vals.values()):
            out = []
            for i, var in enumerate(variants):
                # no Spoolman value for this variant: the (already clamped) cfg value, then the parent's,
                # then the Spoolman standard value; the first two lie inside any published bound, so only
                # Spoolman-derived values can ever be reported by report_outside
                v = (vals.get(var) or _list_number(cfg.get(key), i) or _list_number((template or {}).get(key), i)
                     or vals.get(STD))
                out.append(str(v))
            cfg[key] = out
            keys.add(key)
    if sv.bed:
        for key in BED_KEYS:
            t = (template or {}).get(key)
            cfg[key] = [s(sv.bed)] * (len(t) if isinstance(t, list) and t else 1)
            keys.add(key)
    if sv.nozzle_range:
        cfg["nozzle_temperature_range_low"] = [s(sv.nozzle_range[0])]
        cfg["nozzle_temperature_range_high"] = [s(sv.nozzle_range[1])]
        keys |= {"nozzle_temperature_range_low", "nozzle_temperature_range_high"}
    if sv.density:
        cfg["filament_density"] = [s(sv.density)]
        keys.add("filament_density")
    if sv.cost and sv.cost > 0:
        cfg["filament_cost"] = [s(sv.cost)]
        keys.add("filament_cost")
    return keys


# ---------- the library entry ----------

def merged_entry(lookup: Lookup) -> dict | None:
    """The library entry with the owner's local entry on top: fields and published_ranges key by key,
    bambu_parent, orca_parent and material replaced. None when neither exists."""
    lib, loc = lookup.library, lookup.local
    if lib is None and loc is None:
        return None
    if lib is None:
        return copy.deepcopy(loc)
    out = copy.deepcopy(lib)
    if loc is None:
        return out
    for k in MERGE_DICTS:
        if isinstance(loc.get(k), dict):
            base = out.get(k) if isinstance(out.get(k), dict) else {}
            out[k] = {**base, **copy.deepcopy(loc[k])}
    for k in MERGE_VALUES:
        if k in loc:
            out[k] = copy.deepcopy(loc[k])
    return out


def _fields(entry: dict | None) -> dict:
    f = (entry or {}).get("fields")
    return f if isinstance(f, dict) else {}


def _ranges(entry: dict | None) -> dict:
    pr = (entry or {}).get("published_ranges")
    return pr if isinstance(pr, dict) else {}


def rng(text) -> tuple[float, float] | None:
    """'35-65', '50-70 (glue)', '99.7%-99.9% ...', '70-100 (min 60 highly recommended)' -> (lo, hi) or None."""
    if not isinstance(text, str) or "room" in text:
        return None
    m = re.match(r"\s*([\d.]+)%?\s*-\s*([\d.]+)%?", text)
    try:
        if not m:
            m1 = re.match(r"\s*([\d.]+)", text)
            return (float(m1.group(1)),) * 2 if m1 else None
        lo, hi = float(m.group(1)), float(m.group(2))
        low_min = re.search(r"min\s+([\d.]+)", text)
        return (float(low_min.group(1)) if low_min else lo, hi)
    except ValueError:   # "1.2.3"
        return None


def _is_range(text) -> bool:
    return isinstance(text, str) and re.match(r"\s*[\d.]+%?\s*-\s*[\d.]+", text) is not None


def nozzle_bounds(fields: dict) -> tuple:
    """(low, high) of the published nozzle range; either may be None (e.g. only 'as low as 220C' is published)."""
    def first(key):
        v = fields.get(key) if isinstance(fields, dict) else None
        return _value(v[0]) if isinstance(v, list) and v else None
    return first("nozzle_temperature_range_low"), first("nozzle_temperature_range_high")


def nozzle_text(fields: dict) -> str | None:
    lo, hi = nozzle_bounds(fields)
    if lo is None and hi is None:
        return None
    return f"{lo:g}-{hi:g}" if lo is not None and hi is not None else f"{lo:g}+" if lo is not None else f"up to {hi:g}"


def unsupported_nozzles(entry: dict | None) -> set[str]:
    ns = _ranges(entry).get("_not_supported", "")
    return set(re.findall(r"0\.\d", ns)) if isinstance(ns, str) else set()


def hardened(entry: dict | None, material: str | None) -> bool:
    """Abrasive material (-CF/-GF, CF15, GF30, ...) or a hardened-nozzle note that does not start with 'No'."""
    if isinstance(material, str) and ABRASIVE.search(material):
        return True
    text = _ranges(entry).get("_hardened_nozzle_required")
    return isinstance(text, str) and bool(text.strip()) and not text.strip().casefold().startswith("no")


def fan_off(entry: dict | None) -> bool:
    text = _ranges(entry).get("fan_max_speed")
    return isinstance(text, str) and text.strip().casefold() in FAN_OFF


def _mvs_cap(entry: dict | None) -> float | None:
    v = _fields(entry).get("filament_max_volumetric_speed")
    return _value(v[0]) if isinstance(v, list) and v else None


def _bounds(entry: dict | None) -> list:
    """[(keys, lo, hi, pct, skip_zero)] for every published bound of the entry (chamber uncapped: report only)."""
    f, pr = _fields(entry), _ranges(entry)
    out = []
    lo, hi = nozzle_bounds(f)
    if lo is not None or hi is not None:
        out.append((NOZZLE_TEMPS, lo if lo is not None else 0, hi if hi is not None else 999, False, False))
    for rk, keys in PLATE_GROUPS.items():
        r = rng(pr.get(rk))
        if r:
            out.append(([k for key in keys for k in (key, key + "_initial_layer")], r[0], r[1], False, True))
    r = rng(pr.get("chamber_temperatures"))
    if r:
        out.append((["chamber_temperatures", "chamber_temperature"], r[0], r[1], False, True))
    r = rng(pr.get("filament_shrink"))
    if r:
        out.append((["filament_shrink"], r[0], r[1], True, False))
    r = rng(pr.get("fan_min_speed/fan_max_speed"))
    if r:
        out.append((["fan_min_speed", "fan_max_speed"], r[0], r[1], False, False))
    if not fan_off(entry) and _is_range(pr.get("fan_max_speed")):
        r = rng(pr.get("fan_max_speed"))
        if r:
            out.append((["fan_max_speed"], r[0], r[1], False, False))
    return out


# ---------- applying the entry ----------

def apply_library(cfg: dict, entry: dict | None, *, template: dict, printer: str, nozzle: str,
                  chamber_max: int | None, log: list[str], material: str | None = None) -> None:
    """Apply the merged library entry to cfg (in place; port of spec.apply).

    Order: call this FIRST, before apply_spoolman and inapp.keep_edits. It clamps every value cfg or the template
    holds, assuming they all came from the Bambu parent; Spoolman and in-app values set later are never clamped.
    `material` is the line's material (from Spoolman or the line); Task 5 must always pass it. Hardened material
    sets required_nozzle_HRC ["40"] even when `entry` is None (a line known only from Spoolman).
    `printer` names the printer in log lines when cfg has no name yet."""
    if hardened(entry, material) or hardened(None, (entry or {}).get("material")):
        cfg["required_nozzle_HRC"] = ["40"]
    if not entry:
        return
    f, pr = _fields(entry), _ranges(entry)
    name = cfg.get("name") or printer

    def current(key):
        v = cfg.get(key)
        if v is None and template is not None:
            v = template.get(key)
        return list(v) if isinstance(v, list) else None

    def clamp(key, lo, hi, pct=False, skip_zero=False):
        vals = current(key)
        if vals is None:
            return
        new, changed = [], False
        for v in vals:
            x = _value(v)
            if x is None or (skip_zero and x == 0) or lo <= x <= hi:
                new.append(v)
                continue
            y = min(max(x, lo), hi)
            new.append(fmt(y, pct))
            changed = True
            log.append(f"{name}: {key} {v} -> {fmt(y, pct)} (published {fmt(lo, pct)}-{fmt(hi, pct)})")
        if changed:
            cfg[key] = new

    for key in SET_FIELDS:
        if isinstance(f.get(key), list) and f[key]:
            cfg[key] = list(f[key])
    lo, hi = nozzle_bounds(f)
    if lo is not None or hi is not None:
        for key in NOZZLE_TEMPS:
            clamp(key, lo if lo is not None else 0, hi if hi is not None else 999)
    for rk, keys in PLATE_GROUPS.items():
        r = rng(pr.get(rk))
        if r:
            for key in keys:
                clamp(key, *r, skip_zero=True)
                clamp(key + "_initial_layer", *r, skip_zero=True)
    r = rng(pr.get("chamber_temperatures"))
    if r and chamber_max is not None:
        key = "chamber_temperatures" if "chamber_temperatures" in (template or cfg) else "chamber_temperature"
        top = min(r[1], chamber_max)
        clamp(key, min(r[0], top), top, skip_zero=True)  # 0 = no chamber control; above the printer max -> max
    r = rng(pr.get("filament_shrink"))
    if r:
        clamp("filament_shrink", r[0], r[1], pct=True)
    if fan_off(entry):
        cfg["fan_min_speed"], cfg["fan_max_speed"] = ["0"], ["0"]
    elif _is_range(pr.get("fan_max_speed")):
        r = rng(pr["fan_max_speed"])
        if r:
            clamp("fan_max_speed", *r)
    r = rng(pr.get("fan_min_speed/fan_max_speed"))
    if r:
        clamp("fan_min_speed", *r)
        clamp("fan_max_speed", *r)
    cap = _mvs_cap(entry)
    if cap is not None and nozzle == "0.4":
        clamp("filament_max_volumetric_speed", 0, cap)


def report_outside(cfg: dict, entry: dict | None, keys: set[str], log: list[str]) -> None:
    """For protected keys (Spoolman, in-app) outside a published bound: report, never change."""
    if not entry or not keys:
        return
    for bkeys, lo, hi, pct, skip_zero in _bounds(entry):
        for key in bkeys:
            if key not in keys or not isinstance(cfg.get(key), list):
                continue
            for v in cfg[key]:
                x = _value(v)
                if x is None or (skip_zero and x == 0) or lo <= x <= hi:
                    continue
                log.append(f"{cfg.get('name')}: your {key} {v} is outside the published "
                           f"{fmt(lo, pct)}-{fmt(hi, pct)}; kept")


def spec_notes(entry: dict | None) -> str | None:
    """The manufacturer-spec block for filament_notes (port of spec.notes for the library schema)."""
    if not entry:
        return None
    f, pr = _fields(entry), _ranges(entry)
    parts = []
    if nozzle_text(f):
        parts.append(f"nozzle {nozzle_text(f)} C")
    for k, label in NOTE_LABELS:
        if isinstance(pr.get(k), str) and pr[k].strip():
            parts.append(f"{label} {pr[k]}")
    cap = f.get("filament_max_volumetric_speed")
    if isinstance(cap, list) and cap:
        parts.append(f"max flow {cap[0]} mm3/s")
    text = "Manufacturer specs: " + "; ".join(parts) + "."
    if entry.get("conflicts"):
        text += "\nSource conflicts: " + "; ".join(str(c) for c in entry["conflicts"]) + "."
    quality = f" ({entry['source_quality']})" if entry.get("source_quality") else ""
    sources = entry.get("sources") if isinstance(entry.get("sources"), list) else []
    if sources:
        text += f"\nSources{quality}: " + " ".join(str(x) for x in sources)
    return text
