"""Product lines and the Bambu parent each line's presets are flattened from.

A line is (vendor, product); `line_id = library.line_id(vendor, product)`. Every line owns one generated
`filament_id` (`P` + 7 hex digits) that all its presets share; it never changes once given out. The Bambu parent
is only ever the template a preset is flattened from, never a slot's preset.

Parent steps (the Decision): (1) the library's `bambu_parent` (a local entry's wins) if the uploaded system store
has it; (2) brand: an instantiable system preset of the vendor and the line's Bambu type whose base name minus its
first word equals the product (casefold, alphanumerics only), else the only such preset if there is exactly one;
(3) material: `Generic <type>`. With no store uploaded yet, the hint is taken as is, else the static
`Generic <type>`, and the build re-checks it. A system preset gated only by `compatible_printers_condition` (empty
`compatible_printers`) never yields a build parent, so it is not chosen; a line left with no parent keeps
`parent_source "none"` and shows in `problems`.

State: `state/profiles/lines.json` = `{"version": 1, "lines": [Line, ...]}` (atomic, state-owned).
"""
from __future__ import annotations

import datetime
import json
import re
import secrets
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .. import config
from .. import library as library_mod
from ..library import Library
from ..pairing import _write_atomic, make_state_dir
from .bbl import Store

# ports of filament-ops lines.py BS_TYPE and gen.py BS_VALID
BS_TYPE = {"PA12-CF": "PA-CF", "PA6-GF": "PA-GF", "PAHT-CF": "PA-CF", "PAHT-GF": "PPA-GF", "PC-CF": "PC",
           "PC-ABS": "PC", "POM": "PP", "TPU-GF": "TPU-AMS", "PPS-GF": "PPS", "ABS-CF": "ABS", "PETG-GF": "PETG"}
BS_VALID = {"ABS", "ABS-GF", "ASA", "ASA-AERO", "ASA-CF", "BVOH", "EVA", "HIPS", "PA", "PA-CF", "PA-GF", "PA6-CF",
            "PC", "PCTG", "PE", "PE-CF", "PET-CF", "PETG", "PETG-CF", "PHA", "PLA", "PLA-AERO", "PLA-CF", "PP",
            "PP-CF", "PP-GF", "PPA-CF", "PPA-GF", "PPS", "PPS-CF", "PVA", "TPU", "TPU-AMS"}

SOURCES = ("library", "brand", "material", "user", "none")
FID = re.compile(r"P[0-9a-f]{7}")
FILE_VERSION = 1


@dataclass
class Line:
    line_id: str
    vendor: str
    product: str
    material: str
    bambu_parent: str | None
    parent_source: str          # one of SOURCES
    filament_id: str
    created: str


def bs_type(material: str) -> str:
    """The Bambu Studio filament_type for a Spoolman material: mapped, else upper-cased (even if not in BS_VALID)."""
    m = (material or "").strip().upper()
    return BS_TYPE.get(m, m)


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (text or "").casefold())


# ---------- parent choice ----------

def _usable(store: Store, base: str) -> bool:
    """`base` names an instantiable system preset that lists at least one compatible printer."""
    return any(store._compatible(cfg) for _n, cfg in store._with_base(base))


def _hint(vendor: str, product: str, library: Library) -> str | None:
    look = library.lookup(vendor, product)
    for entry in (look.local, look.library):
        p = (entry or {}).get("bambu_parent")
        if isinstance(p, str) and p.strip():
            return p.strip()
    return None


def _brand(vendor: str, product: str, btype: str, store: Store) -> str | None:
    cands = [b for b in store.vendor_bases(vendor, btype) if _usable(store, b)]
    want = _norm(product)
    named = [b for b in cands if _norm(b.split(" ", 1)[1] if " " in b else "") == want]
    if len(named) == 1:
        return named[0]
    if not named and len(cands) == 1:
        return cands[0]
    return None


def choose_parent(vendor: str, product: str, material: str, *, library: Library,
                  store: Store | None) -> tuple[str | None, str]:
    btype = bs_type(material)
    hint = _hint(vendor, product, library)
    if store is None:
        if hint is not None:
            return hint, "library"
        return (f"Generic {btype}", "material") if btype else (None, "none")
    if hint is not None and _usable(store, hint):
        return hint, "library"
    if not btype:
        return None, "none"
    brand = _brand(vendor, product, btype, store)
    if brand is not None:
        return brand, "brand"
    generic = f"Generic {btype}"
    if _usable(store, generic):
        return generic, "material"
    return None, "none"


# ---------- lines ----------

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_filament_id(used: set[str]) -> str:
    while True:
        fid = "P" + secrets.token_hex(4)[:7]
        if fid not in used:
            return fid


def propose(vendor: str, product: str, material: str, *, library: Library, store: Store | None,
            lines: dict[str, Line]) -> dict:
    vendor, product = (vendor or "").strip(), (product or "").strip()
    lid = library_mod.line_id(vendor, product)
    have = lines.get(lid)
    if have is not None:
        return {"line_id": lid, "line": have.product, "bambu_parent": have.bambu_parent,
                "parent_source": have.parent_source, "exists": True}
    parent, source = choose_parent(vendor, product, material, library=library, store=store)
    return {"line_id": lid, "line": product, "bambu_parent": parent, "parent_source": source, "exists": False}


def ensure(lines: dict[str, Line], vendor: str, product: str, material: str, *, bambu_parent: str | None,
           library: Library, store: Store | None, used_fids: set[str]) -> Line:
    """The line for (vendor, product), created if missing. A given `bambu_parent` that differs from the line's
    (or, for a new line, from the chosen one) is set with source "user"."""
    vendor, product = (vendor or "").strip(), (product or "").strip()
    lid = library_mod.line_id(vendor, product)
    line = lines.get(lid)
    if line is None:
        parent, source = choose_parent(vendor, product, material, library=library, store=store)
        fid = new_filament_id(used_fids | {l.filament_id for l in lines.values()})
        used_fids.add(fid)
        line = Line(lid, vendor, product, (material or "").strip(), parent, source, fid, _now())
        lines[lid] = line
    if bambu_parent is not None and bambu_parent.strip() and bambu_parent.strip() != line.bambu_parent:
        line.bambu_parent, line.parent_source = bambu_parent.strip(), "user"
    return line


def set_parent(lines: dict[str, Line], line_id: str, parent: str) -> Line:
    line = lines[line_id]                       # KeyError when unknown
    line.bambu_parent, line.parent_source = parent, "user"
    return line


def problems(lines: dict[str, Line]) -> list[str]:
    """One line per product line that has no Bambu parent (it gets no presets until one is set)."""
    return [f"{l.line_id}: no Bambu parent (no usable library hint, brand or Generic {bs_type(l.material) or '?'} "
            f"system preset with compatible printers); set one for this line"
            for l in sorted(lines.values(), key=lambda l: l.line_id) if l.bambu_parent is None]


# ---------- Spoolman filaments ----------

def _extra_line(filament: dict) -> str:
    raw = (filament.get("extra") or {}).get("line")
    if not isinstance(raw, str):
        return ""
    try:
        val = json.loads(raw)
    except ValueError:
        val = raw
    return (val if isinstance(val, str) else raw).strip()


def _vendor(filament: dict) -> str:
    v = filament.get("vendor")
    name = v.get("name") if isinstance(v, dict) else None
    return name.strip() if isinstance(name, str) else ""


def _boundary(name: str, n: int) -> bool:
    return n == len(name) or not (name[n].isalnum() or name[n] in "+.")


def product_of(filament: dict, library: Library) -> str:
    """The filament's product line: `extra.line`, else the longest library product of the vendor that prefixes its
    name at a word boundary, else its name."""
    line = _extra_line(filament)
    if line:
        return line
    name = (filament.get("name") or "").strip()
    folded = name.casefold()
    best = ""
    for e in library.vendor_entries(_vendor(filament)):
        p = (e.get("product") or "").strip()
        if p and len(p) > len(best) and folded.startswith(p.casefold()) and _boundary(name, len(p)):
            best = p
    return best or name


def group(filaments: list[dict], lines: dict[str, Line], *, library: Library, store: Store | None,
          used_fids: set[str]) -> dict[str, list[dict]]:
    """line_id -> the line's filaments (Spoolman order); missing lines are created. Archived filaments and those
    without a vendor are skipped; a filament with no name and no line takes its material as the product."""
    out: dict[str, list[dict]] = {}
    for f in filaments:
        if f.get("archived"):
            continue
        vendor = _vendor(f)
        if not vendor:
            continue
        material = (f.get("material") or "").strip()
        product = product_of(f, library) or material
        if not product:
            continue
        line = ensure(lines, vendor, product, material, bambu_parent=None, library=library, store=store,
                      used_fids=used_fids)
        out.setdefault(line.line_id, []).append(f)
    return out


# ---------- persistence ----------

def _path() -> Path:
    return config.paths().state / "profiles" / "lines.json"


def _row(r) -> Line | None:
    if not isinstance(r, dict):
        return None
    try:
        line = Line(**{f.name: r[f.name] for f in fields(Line)})
    except KeyError:
        return None
    text = (line.line_id, line.vendor, line.product, line.material, line.filament_id, line.created)
    if not all(isinstance(t, str) for t in text) or not line.line_id:
        return None
    if not (line.bambu_parent is None or isinstance(line.bambu_parent, str)):
        return None
    if line.parent_source not in SOURCES or not FID.fullmatch(line.filament_id):
        return None
    return line


def load() -> dict[str, Line]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("lines") if isinstance(data, dict) else None
    out: dict[str, Line] = {}
    for r in rows if isinstance(rows, list) else []:
        line = _row(r)
        if line is not None and line.line_id not in out:
            out[line.line_id] = line
    return out


def save(lines: dict[str, Line]) -> None:
    path = _path()
    make_state_dir(path.parent)
    data = {"version": FILE_VERSION, "lines": [asdict(lines[k]) for k in sorted(lines)]}
    _write_atomic(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), 0o644,
                  state_owned=True)
