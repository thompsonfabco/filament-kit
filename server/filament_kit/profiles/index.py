"""`preset_for`: the owner's preset for a Spoolman filament on a printer model and nozzle, from the last good build.

Steps (Decision "preset_for source"): printer = `models.printer_preset_name(model)`, nozzle = f"{nozzle_mm:g}";
only Bambu Studio preset rows (`target` "bambu_studio", or none) count; the line is the filament's explicit
`extra.line` when the build has it (a new colour of a built line, or a filament the owner moved), else the
build's Spoolman filament-id map (where the build really put it, ruling S12), else
`lines.line_id_for(vendor, lines.product_of(filament, library))` (= `library.line_id`, except for a part whose slug
is empty, matching how builds key their lines); then the build's preset of that line, printer and nozzle. A preset whose filament_id is
not a generated id (`generate.ID_RE`), whose name could not be a file name, or that lacks either nozzle temperature
or its filament_type is refused (None): never a system id, never None temps. `setting_id` comes from the live
upload's `base/<name>.info` when it matches
`[A-Za-z0-9_-]{1,32}`, else "". A broken library falls back to the build's filament-id map.

The parsed BUILD.json is cached by the mtime of `current.json`.
"""
from __future__ import annotations

import logging
import re
import threading

from .. import library as library_mod
from ..bridge import models as models_mod
from . import PresetRef, builds, generate, lines as lines_mod

log = logging.getLogger(__name__)
BAMBU_STUDIO = generate.BAMBU_STUDIO
SETTING_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
_cache: dict = {}
_cache_lock = threading.Lock()


def _read_build(stamp: str) -> dict | None:
    m = builds.manifest(stamp)
    if m is None or not isinstance(m.get("presets"), list) or not isinstance(m.get("lines"), dict):
        return None
    if not isinstance(m.get("filaments"), dict):
        m["filaments"] = {}
    return m


def _build() -> dict | None:
    path = builds._dir() / "current.json"
    try:
        key = path.stat().st_mtime_ns
    except OSError:
        return None
    with _cache_lock:
        if _cache.get("key") == key and _cache.get("path") == str(path):
            return _cache["build"]
    cur = builds.current()
    b = _read_build(cur["stamp"]) if cur else None
    with _cache_lock:
        _cache.update(key=key, path=str(path), build=b)
    return b


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _line_of(filament: dict, build: dict) -> str | None:
    """The build's line of this filament: its explicit `extra.line` when the build has that line (a new colour, or a
    filament the owner moved); else the build's filament-id map (the build keeps a filament in its recorded line,
    ruling S12, even after a library update adds a longer product prefix); else vendor + `product_of`."""
    vendor = lines_mod._vendor(filament)
    explicit = lines_mod._extra_line(filament) if vendor else ""
    if explicit:
        lid = lines_mod.line_id_for(vendor, explicit)
        if lid in build["lines"]:
            return lid
    fid = filament.get("id")
    if isinstance(fid, int) and not isinstance(fid, bool):
        lid = build["filaments"].get(str(fid))
        if isinstance(lid, str):
            return lid
    if vendor and not explicit:
        try:
            product = lines_mod.product_of(filament, library_mod.load())
        except Exception:               # a broken library: only the build's filament-id map is left
            log.warning("preset_for: library unavailable; using the build's filament-id map", exc_info=True)
            product = ""
        if product:
            lid = lines_mod.line_id_for(vendor, product)
            if lid in build["lines"]:
                return lid
    return None


def _same_nozzle(a, b) -> bool:
    """Nozzle sizes as numbers: klipper_hardware.xml says "1.0", a build row or config may say "1" or 1.0."""
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


def _orca_printers(model: str, nozzle: str, printer_name: str | None) -> set[str]:
    """Orca printer names a Klipper printer's rows can carry: the klipper_hardware.xml model's `<orca>` name for
    this nozzle, and every config `slicer_printers` entry that is that printer (by its name or label) or lists that
    Orca name among its compatible printers (a row's `printer` is the entry's name)."""
    from .. import config
    from ..bridge.klipper import hardware as kh
    xml = {o.printer for o in kh.load().model(model).orca if _same_nozzle(o.nozzle, nozzle)}
    names = set(xml)
    for e in (config.load().get("slicer_printers") or []):
        if not isinstance(e, dict) or not isinstance(e.get("name"), str):
            continue
        compat = e.get("compatible_printers") if isinstance(e.get("compatible_printers"), dict) else {}
        if (printer_name and printer_name in (e.get("name"), e.get("label"))) or \
                any(_same_nozzle(k, nozzle) and v in xml for k, v in compat.items()):
            names.add(e["name"])
    return names


def _orca_preset(filament: dict, model: str, nozzle: str, printer_name: str | None) -> PresetRef | None:
    """Klipper printers: the build's Orca preset row (target "orca"). Nothing of it is sent to the printer, so the
    filament_id need not be a generated id; the name and both temperatures must still be usable."""
    printers = _orca_printers(model, nozzle, printer_name)
    build = _build()
    if not printers or build is None:
        return None
    lid = _line_of(filament, build)
    if lid is None:
        return None
    row = next((p for p in build["presets"] if isinstance(p, dict) and p.get("target") == generate.ORCA
                and p.get("line_id") == lid and p.get("printer") in printers
                and _same_nozzle(p.get("nozzle"), nozzle)), None)
    if row is None:
        return None
    name, ftype, fid = row.get("name"), row.get("filament_type"), row.get("filament_id")
    lo, hi = _int(row.get("nozzle_temp_min")), _int(row.get("nozzle_temp_max"))
    if not generate.safe_name(name) or lo is None or hi is None or not (isinstance(ftype, str) and ftype):
        return None
    return PresetRef(filament_id=fid if isinstance(fid, str) else "", name=name, nozzle_temp_min=lo,
                     nozzle_temp_max=hi, filament_type=ftype, setting_id="")


def preset_for(filament: dict, model: str, nozzle_mm: float, *, family: str = "bambu",
               printer_name: str | None = None) -> PresetRef | None:
    """The owner's preset for this Spoolman `filament` on a printer `model` with a `nozzle_mm` nozzle, or None.
    `family="klipper"`: `model` is the klipper_hardware.xml model key and the preset is the build's Orca row
    (`_orca_preset`); `printer_name` is the printer's registry name (matches a config `slicer_printers` entry)."""
    if family == "klipper":
        if not isinstance(filament, dict):
            return None
        try:
            return _orca_preset(filament, model, f"{float(nozzle_mm):g}", printer_name)
        except (TypeError, ValueError):
            return None
    printer = models_mod.printer_preset_name(model)
    if printer is None or not isinstance(filament, dict):
        return None
    try:
        nozzle = f"{float(nozzle_mm):g}"
    except (TypeError, ValueError):
        return None
    build = _build()
    if build is None:
        return None
    lid = _line_of(filament, build)
    if lid is None:
        return None
    # only Bambu Studio presets reach the AMS (a row without a target predates the Orca target, Task 6)
    row = next((p for p in build["presets"] if isinstance(p, dict) and p.get("line_id") == lid
                and p.get("target", BAMBU_STUDIO) == BAMBU_STUDIO
                and p.get("printer") == printer and p.get("nozzle") == nozzle), None)
    if row is None:
        return None
    fid, name, ftype = row.get("filament_id"), row.get("name"), row.get("filament_type")
    lo, hi = _int(row.get("nozzle_temp_min")), _int(row.get("nozzle_temp_max"))
    if not (isinstance(fid, str) and generate.ID_RE.fullmatch(fid)):
        return None
    if not generate.safe_name(name):
        return None
    if lo is None or hi is None or not (isinstance(ftype, str) and ftype):
        return None
    info = generate._read_info(builds._live() / "user" / "base" / f"{name}.info")
    sid = info.get("setting_id") or ""
    if not SETTING_ID.fullmatch(sid):
        sid = ""                        # sent to the printer: only a plain Bambu setting id
    return PresetRef(filament_id=fid, name=name, nozzle_temp_min=lo, nozzle_temp_max=hi, filament_type=ftype,
                     setting_id=sid)
