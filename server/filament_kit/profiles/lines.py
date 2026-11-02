"""Product lines and the Bambu parent each line's presets are flattened from.

A line is (vendor, product); `line_id = line_id_for(vendor, product)` (= `library.line_id`, except that a part
whose slug is empty becomes `x` + sha1(text)[:6]). Every line owns one generated `filament_id` (`P` + 7 hex digits)
that all its presets share; it never changes once given out. The Bambu parent is only ever the template a preset
is flattened from, never a slot's preset.

Parent steps (the Decision, rulings S9/S10): (1) the library's `bambu_parent` (a local entry's wins) if the
uploaded system store has it; (2) brand: an instantiable system preset of the vendor and the line's Bambu type
whose base name minus its first word equals the product (casefold, "+" read as "plus", alphanumerics only), else
the only such preset if there is exactly one; (3) material: the store's own Generic preset for the type (vendor
"Generic"; "for AMS" first, then plain `Generic <type>`, then name order). With no store uploaded yet, the hint is
taken as is, else the static `Generic <type>`; `rechoose` re-runs the steps at build time for every line whose
parent the owner did not set. A system preset gated only by `compatible_printers_condition` (empty
`compatible_printers`) never yields a build parent, so it is not chosen; a line left with no parent keeps
`parent_source "none"` and shows in `problems`.

Line stability (ruling S12): each line records its member Spoolman filament ids. `group` keeps a filament in its
recorded line unless its `extra.line` is set and names another line (the move is reported). Lines are never
deleted, members or not.

State: `state/profiles/lines.json` = `{"version": 1, "lines": [Line, ...]}` (atomic, state-owned). A missing file
is an empty set; an unreadable or invalid file is renamed to `lines.json.corrupt-<ts>` and `LineStoreError` is
raised (never an empty set that the next save would write over every filament_id). A row that fails validation
is kept as it is, saved back unchanged, and reported in `problems`.

Concurrency: every load -> change -> save must run inside `locked()` (or `transaction()`, which loads and saves
in it); `ensure_saved`, `set_parent_saved` and `group_saved` do. The pure `ensure`/`set_parent`/`group` work on
a set the caller loaded under the lock.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import secrets
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows dev PC
    fcntl = None

from .. import config
from .. import library as library_mod
from ..library import Library
from ..pairing import _write_atomic, make_state_dir, open_lock
from . import errors
from .bbl import Store, _first

# ports of filament-ops lines.py BS_TYPE and gen.py BS_VALID
BS_TYPE = {"PA12-CF": "PA-CF", "PA6-GF": "PA-GF", "PAHT-CF": "PA-CF", "PAHT-GF": "PPA-GF", "PC-CF": "PC",
           "PC-ABS": "PC", "POM": "PP", "TPU-GF": "TPU-AMS", "PPS-GF": "PPS", "ABS-CF": "ABS", "PETG-GF": "PETG"}
BS_VALID = {"ABS", "ABS-GF", "ASA", "ASA-AERO", "ASA-CF", "BVOH", "EVA", "HIPS", "PA", "PA-CF", "PA-GF", "PA6-CF",
            "PC", "PCTG", "PE", "PE-CF", "PET-CF", "PETG", "PETG-CF", "PHA", "PLA", "PLA-AERO", "PLA-CF", "PP",
            "PP-CF", "PP-GF", "PPA-CF", "PPA-GF", "PPS", "PPS-CF", "PVA", "TPU", "TPU-AMS"}
# Bambu type -> the store filament_types its Generic preset may carry ("Generic TPU for AMS" is "TPU-AMS")
GENERIC_TYPES = {"TPU": ("TPU", "TPU-AMS"), "TPU-AMS": ("TPU-AMS", "TPU")}

SOURCES = ("library", "brand", "material", "user", "none")
FID = re.compile(r"P[0-9a-f]{7}")
FILE_VERSION = 1


class LineStoreError(errors.ProfileError):
    """lines.json is unreadable or invalid; it was moved aside so nothing overwrites it."""

    def __init__(self, message: str, **extra):
        super().__init__(500, "lines_corrupt", message, **extra)


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
    filaments: list[int] = field(default_factory=list)   # member Spoolman filament ids, ascending


class LineSet(dict):
    """line_id -> Line, plus the raw rows that failed validation (kept and saved back) and this run's notes."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.invalid: list = []
        self.notes: list[str] = []


def _note(lines: dict, text: str) -> None:
    notes = getattr(lines, "notes", None)
    if notes is not None and text not in notes:
        notes.append(text)


def bs_type(material: str) -> str:
    """The Bambu Studio filament_type for a Spoolman material: mapped, else upper-cased (even if not in BS_VALID)."""
    m = (material or "").strip().upper()
    return BS_TYPE.get(m, m)


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (text or "").casefold().replace("+", "plus"))


def _part(text: str) -> str:
    s = library_mod.slug(text or "")
    return s or "x" + hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:6]


def line_id_for(vendor: str, product: str) -> str:
    """`library.line_id`, except an empty slug part becomes `x` + sha1(text)[:6] (e.g. a product named "++")."""
    return _part((vendor or "").strip()) + "--" + _part((product or "").strip())


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


def _generic(btype: str, store: Store) -> str | None:
    types = GENERIC_TYPES.get(btype, (btype,))
    plain = {f"Generic {t}" for t in types}
    cands = []
    for base in store.bases():
        for _n, cfg in store._with_base(base):
            if store._compatible(cfg) and (_first(cfg.get("filament_vendor")) or "").casefold() == "generic" \
                    and _first(cfg.get("filament_type")) in types:
                cands.append(base)
                break
    if not cands:
        return None
    return min(cands, key=lambda b: (0 if "for ams" in b.casefold() else 1 if b in plain else 2, b))


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
    generic = _generic(btype, store)
    if generic is not None:
        return generic, "material"
    return None, "none"


def rechoose(line: Line, store: Store | None, *, library: Library | None = None) -> Line:
    """Re-run the parent steps for a line whose parent the owner did not set (any source but "user", "none"
    included), e.g. at build time once a system store is uploaded."""
    if line.parent_source != "user":
        lib = library if library is not None else library_mod.load()
        line.bambu_parent, line.parent_source = choose_parent(line.vendor, line.product, line.material,
                                                              library=lib, store=store)
    return line


# ---------- lines ----------

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_filament_id(used: set[str]) -> str:
    while True:
        fid = "P" + secrets.token_hex(4)[:7]
        if fid not in used:
            return fid


def _taken_fids(lines: dict) -> set[str]:
    out = {l.filament_id for l in lines.values()}
    for r in getattr(lines, "invalid", []):
        if isinstance(r, dict) and isinstance(r.get("filament_id"), str):
            out.add(r["filament_id"])
    return out


def propose(vendor: str, product: str, material: str, *, library: Library, store: Store | None,
            lines: dict[str, Line]) -> dict:
    vendor, product = (vendor or "").strip(), (product or "").strip()
    lid = line_id_for(vendor, product)
    have = lines.get(lid)
    if have is not None:
        return {"line_id": lid, "line": have.product, "bambu_parent": have.bambu_parent,
                "parent_source": have.parent_source, "exists": True}
    parent, source = choose_parent(vendor, product, material, library=library, store=store)
    return {"line_id": lid, "line": product, "bambu_parent": parent, "parent_source": source, "exists": False}


def ensure(lines: dict[str, Line], vendor: str, product: str, material: str, *, bambu_parent: str | None,
           library: Library, store: Store | None, used_fids: set[str]) -> Line:
    """The line for (vendor, product), created if missing. A given `bambu_parent` that differs from the line's
    (or, for a new line, from the chosen one) is set with source "user". Run under `locked()` when the set is
    saved afterwards."""
    vendor, product = (vendor or "").strip(), (product or "").strip()
    lid = line_id_for(vendor, product)
    line = lines.get(lid)
    if line is None:
        parent, source = choose_parent(vendor, product, material, library=library, store=store)
        fid = new_filament_id(used_fids | _taken_fids(lines))
        used_fids.add(fid)
        line = Line(lid, vendor, product, (material or "").strip(), parent, source, fid, _now())
        lines[lid] = line
    elif (_norm(vendor), _norm(product)) != (_norm(line.vendor), _norm(line.product)):
        _note(lines, f"two names share line {lid}: {line.vendor} {line.product!s} and {vendor} {product}")
    if bambu_parent is not None and bambu_parent.strip() and bambu_parent.strip() != line.bambu_parent:
        line.bambu_parent, line.parent_source = bambu_parent.strip(), "user"
    return line


def set_parent(lines: dict[str, Line], line_id: str, parent: str) -> Line:
    line = lines[line_id]                       # KeyError when unknown
    line.bambu_parent, line.parent_source = parent, "user"
    return line


def problems(lines: dict[str, Line]) -> list[str]:
    """Lines with no Bambu parent (they get no presets until one is set), rows of lines.json that failed
    validation, and this run's notes (filament moves, line_id collisions)."""
    out = [f"{l.line_id}: no Bambu parent (no usable library hint, brand or Generic {bs_type(l.material) or '?'} "
           f"system preset with compatible printers); set one for this line"
           for l in sorted(lines.values(), key=lambda l: l.line_id) if l.bambu_parent is None]
    for r in getattr(lines, "invalid", []):
        lid = r.get("line_id") if isinstance(r, dict) else None
        out.append(f"lines.json: invalid row kept as is ({lid if isinstance(lid, str) else 'no line_id'})")
    return out + list(getattr(lines, "notes", []))


# ---------- Spoolman filaments ----------

def _extra_line(filament: dict) -> str:
    """`extra.line` JSON-decoded; text that is not JSON is taken as is; other JSON values (null, numbers) are
    ignored."""
    raw = (filament.get("extra") or {}).get("line")
    if not isinstance(raw, str):
        return ""
    try:
        val = json.loads(raw)
    except ValueError:
        return raw.strip()
    return val.strip() if isinstance(val, str) else ""


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


def _add_member(line: Line, fid) -> None:
    if isinstance(fid, int) and not isinstance(fid, bool) and fid not in line.filaments:
        line.filaments = sorted(line.filaments + [fid])


def group(filaments: list[dict], lines: dict[str, Line], *, library: Library, store: Store | None,
          used_fids: set[str]) -> dict[str, list[dict]]:
    """line_id -> the line's filaments (Spoolman order); missing lines are created. A filament stays in the line
    that records it unless its `extra.line` is set and names another line (then it moves, with a note).
    Archived filaments and those without a vendor are skipped (their membership is kept); a filament with no
    name and no line takes its material as the product. Run under `locked()` when the set is saved afterwards."""
    recorded: dict[int, str] = {}
    for l in sorted(lines.values(), key=lambda l: l.line_id):
        for i in l.filaments:
            recorded.setdefault(i, l.line_id)
    out: dict[str, list[dict]] = {}
    for f in filaments:
        if f.get("archived"):
            continue
        vendor = _vendor(f)
        if not vendor:
            continue
        material = (f.get("material") or "").strip()
        fid = f.get("id")
        rec = recorded.get(fid) if isinstance(fid, int) else None
        if rec is not None and rec in lines:
            explicit = _extra_line(f)
            if explicit and line_id_for(vendor, explicit) != rec:
                new = ensure(lines, vendor, explicit, material, bambu_parent=None, library=library, store=store,
                             used_fids=used_fids)
                old = lines[rec]
                old.filaments = [i for i in old.filaments if i != fid]
                _add_member(new, fid)
                recorded[fid] = new.line_id
                _note(lines, f"filament {fid} moved from line {rec} to {new.line_id} (extra.line)")
                rec = new.line_id
            out.setdefault(rec, []).append(f)
            continue
        product = product_of(f, library) or material
        if not product:
            continue
        line = ensure(lines, vendor, product, material, bambu_parent=None, library=library, store=store,
                      used_fids=used_fids)
        _add_member(line, fid)
        if isinstance(fid, int):
            recorded[fid] = line.line_id
        out.setdefault(line.line_id, []).append(f)
    return out


# ---------- persistence ----------

_lock = threading.RLock()
_held = threading.local()


def _path() -> Path:
    return config.paths().state / "profiles" / "lines.json"


@contextmanager
def locked():
    """Serialize lines.json changes between threads and with the CLI/builder in another process (flock on
    `state/profiles/lines.lock`; thread lock only where fcntl is missing). Re-entrant within a thread."""
    with _lock:
        depth = getattr(_held, "depth", 0)
        if fcntl is None or depth:
            _held.depth = depth + 1
            try:
                yield
            finally:
                _held.depth = depth
            return
        folder = _path().parent
        make_state_dir(folder)
        with open_lock(folder / "lines.lock") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            _held.depth = 1
            try:
                yield
            finally:
                _held.depth = 0
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _row(r) -> Line | None:
    if not isinstance(r, dict):
        return None
    try:
        line = Line(**{f.name: r[f.name] for f in fields(Line) if f.name != "filaments"},
                    filaments=r.get("filaments", []))
    except KeyError:
        return None
    text = (line.line_id, line.vendor, line.product, line.material, line.filament_id, line.created)
    if not all(isinstance(t, str) for t in text) or not line.line_id:
        return None
    if not (line.bambu_parent is None or isinstance(line.bambu_parent, str)):
        return None
    if line.parent_source not in SOURCES or not FID.fullmatch(line.filament_id):
        return None
    if not (isinstance(line.filaments, list)
            and all(isinstance(i, int) and not isinstance(i, bool) for i in line.filaments)):
        return None
    line.filaments = sorted(set(line.filaments))
    return line


def _corrupt(path: Path, why: str):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    aside = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        path.replace(aside)
        moved = aside.name
    except OSError:
        moved = None
    raise LineStoreError(f"lines.json is unusable ({why}); "
                         + (f"moved aside to {moved}" if moved else "it could not be moved aside"), moved=moved)


def load() -> LineSet:
    """The saved lines; an empty set when lines.json is missing. Raises LineStoreError (after moving the file
    aside) when it is unreadable or not a lines file."""
    path = _path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return LineSet()
    except OSError as e:
        _corrupt(path, f"unreadable: {e.__class__.__name__}")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        _corrupt(path, f"not JSON: {e.__class__.__name__}")
    rows = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        _corrupt(path, "no lines list")
    out = LineSet()
    for r in rows:
        line = _row(r)
        if line is None or line.line_id in out:
            out.invalid.append(r)
        else:
            out[line.line_id] = line
    return out


def save(lines: dict[str, Line]) -> None:
    """Write the set (valid lines sorted by line_id, then the invalid rows unchanged). Call under `locked()`."""
    path = _path()
    make_state_dir(path.parent)
    rows = [asdict(lines[k]) for k in sorted(lines)] + list(getattr(lines, "invalid", []))
    data = {"version": FILE_VERSION, "lines": rows}
    _write_atomic(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), 0o644,
                  state_owned=True)


@contextmanager
def transaction():
    """`with transaction() as ls:` loads under `locked()`, yields the set, and saves it if the block succeeds."""
    with locked():
        ls = load()
        yield ls
        save(ls)


def ensure_saved(vendor: str, product: str, material: str, *, bambu_parent: str | None, library: Library,
                 store: Store | None) -> Line:
    with transaction() as ls:
        return ensure(ls, vendor, product, material, bambu_parent=bambu_parent, library=library, store=store,
                      used_fids=set())


def set_parent_saved(line_id: str, parent: str) -> Line:
    with transaction() as ls:
        return set_parent(ls, line_id, parent)


def group_saved(filaments: list[dict], *, library: Library,
                store: Store | None) -> tuple[dict[str, list[dict]], LineSet]:
    """`group` on the saved set, saved back; returns the groups and the set (its `problems` include the moves)."""
    with transaction() as ls:
        return group(filaments, ls, library=library, store=store, used_fids=set()), ls
