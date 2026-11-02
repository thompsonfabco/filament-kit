"""`preset_for`: the owner's preset for a Spoolman filament on a printer model and nozzle, from the last good build.

Steps (Decision "preset_for source"): printer = `models.printer_preset_name(model)`, nozzle = f"{nozzle_mm:g}";
the line is `lines.line_id_for(vendor, lines.product_of(filament, library))` (= `library.line_id`, except for a
part whose slug is empty, matching how builds key their lines) when the build has that line, else the build's
Spoolman filament-id map; then the build's preset of that line, printer and nozzle. A preset whose filament_id is
not a generated id (`generate.ID_RE`), whose name could not be a file name, or that lacks either nozzle temperature
or its filament_type is refused (None): never a system id, never None temps. `setting_id` comes from the live
upload's `base/<name>.info`, else "".

The parsed BUILD.json is cached by the mtime of `current.json`.
"""
from __future__ import annotations

import threading

from .. import library as library_mod
from ..bridge import models as models_mod
from . import PresetRef, builds, generate, lines as lines_mod

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
    vendor = lines_mod._vendor(filament)
    if vendor:
        product = lines_mod._extra_line(filament) or lines_mod.product_of(filament, library_mod.load())
        if product:
            lid = lines_mod.line_id_for(vendor, product)
            if lid in build["lines"]:
                return lid
    fid = filament.get("id")
    if isinstance(fid, int) and not isinstance(fid, bool):
        lid = build["filaments"].get(str(fid))
        if isinstance(lid, str):
            return lid
    return None


def preset_for(filament: dict, model: str, nozzle_mm: float) -> PresetRef | None:
    """The owner's preset for this Spoolman `filament` on a printer `model` with a `nozzle_mm` nozzle, or None."""
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
    row = next((p for p in build["presets"] if isinstance(p, dict) and p.get("line_id") == lid
                and p.get("printer") == printer and p.get("nozzle") == nozzle), None)
    if row is None:
        return None
    fid, name, ftype = row.get("filament_id"), row.get("name"), row.get("filament_type")
    lo, hi = _int(row.get("nozzle_temp_min")), _int(row.get("nozzle_temp_max"))
    if not (isinstance(fid, str) and generate.ID_RE.fullmatch(fid)):
        return None
    if not (isinstance(name, str) and name.strip() and not generate.BAD_NAME.search(name)) or name in (".", ".."):
        return None
    if lo is None or hi is None or not (isinstance(ftype, str) and ftype):
        return None
    info = generate._read_info(builds._live() / "user" / "base" / f"{name}.info")
    sid = info.get("setting_id") or ""
    return PresetRef(filament_id=fid, name=name, nozzle_temp_min=lo, nozzle_temp_max=hi, filament_type=ftype,
                     setting_id=sid)
