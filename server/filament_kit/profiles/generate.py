"""The preset generator: one Bambu Studio filament preset per product line x printer model x nozzle (port of the
owner's filament-ops `gen.py` Bambu Studio part).

Each preset is flattened from its Bambu system parent (`inherits: ""`) and carries the line's own `filament_id`
(`P` + 7 hex digits), never a system id. Per preset, in this order: resolve the parent and drop its bookkeeping
keys, set the common keys, `values.apply_library` (always, so hardened materials get `required_nozzle_HRC`),
`values.apply_spoolman`, `inapp.keep_edits`, `values.report_outside`, the notes (summary, manufacturer specs,
MARK + the owner's lines, `Spoolman filament ids:` last), `check_preset`, then the files.

"nil" is never written: a parent list with "nil" items gets them filled from the list's first real value (an
all-"nil" key is dropped) before the library is applied and again after the in-app edits. temperature_vitrification
always stays the parent's (an in-app change to it is reported, not kept).

One line with odd data, or one bad preset, is skipped with a problem line; the rest of the build goes on.
"""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from ..bridge import models as models_mod
from ..library import Library
from . import inapp, lines as lines_mod, values
from .bbl import Store, _first
from .lines import BS_VALID, Line, LineSet

ID_RE = re.compile(r"^P[0-9a-f]{7}$")
BAD_NAME = re.compile(r'[\\/:*?"<>|]')
POP = ("type", "instantiation", "setting_id", "description", "renamed_from", "is_custom_defined", "inherits",
       "filament_id", "compatible_printers")
TV = "temperature_vitrification"
DEFAULT_VERSION = "2.0.0.0"


# ---------- the live upload ----------

def _read_info(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass
class Live:
    """The user filament folder the PC sync uploaded (`root/base/<name>.json` + `.info`)."""
    root: Path
    user_id: str

    def preset(self, name: str) -> tuple[dict | None, dict]:
        base = Path(self.root) / "base"
        return _read_json(base / f"{name}.json"), _read_info(base / f"{name}.info")

    def names(self) -> set[str]:
        base = Path(self.root) / "base"
        if not base.is_dir():
            return set()
        return {p.stem for p in base.iterdir() if p.is_file() and p.suffix.casefold() == ".json"}


def _snapshot_names(snapshot: Path | None) -> set[str]:
    base = Path(snapshot) / "base" if snapshot is not None else None
    if base is None or not base.is_dir():
        return set()
    return {p.stem for p in base.iterdir() if p.is_file() and p.suffix.casefold() == ".json"}


# ---------- checks ----------

def preset_name(line: Line, printer: str, nozzle: str) -> str:
    return f"{line.vendor} {line.product} @{printer} {nozzle} nozzle"


def _has_nil(v) -> bool:
    if isinstance(v, str):
        return v == "nil"
    if isinstance(v, list):
        return any(_has_nil(x) for x in v)
    if isinstance(v, dict):
        return any(_has_nil(x) for x in v.values())
    return False


def _int(v) -> int | None:
    """The first value of a preset list as an int ("205", "205.0"), or None."""
    x = v[0] if isinstance(v, list) and v else v
    if isinstance(x, bool) or x is None or isinstance(x, (list, dict)):
        return None
    try:
        f = float(str(x).strip())
    except ValueError:
        return None
    return round(f) if math.isfinite(f) else None


def check_preset(cfg: dict, parent_cfg: dict) -> list[str]:
    """Why this preset must not be written ([] = good)."""
    errs = []
    if _has_nil(cfg):
        errs.append('a value is "nil"')
    if not (isinstance(cfg.get("filament_id"), str) and ID_RE.fullmatch(cfg["filament_id"])):
        errs.append(f"filament_id {cfg.get('filament_id')!r} is not a generated id")
    for k in ("nozzle_temperature_range_low", "nozzle_temperature_range_high"):
        if _int(cfg.get(k)) is None:
            errs.append(f"{k} missing or not a number")
    notes = inapp.notes_text(cfg.get("filament_notes")).splitlines()
    if not notes or not notes[-1].startswith(inapp.IDS_PREFIX + " "):
        errs.append("notes do not end with the Spoolman filament ids")
    if cfg.get("inherits") != "":
        errs.append("inherits is not empty")
    cp = cfg.get("compatible_printers")
    if not (isinstance(cp, list) and len(cp) == 1 and isinstance(cp[0], str)):
        errs.append("compatible_printers is not a single printer")
    if inapp.norm(cfg.get(TV)) != inapp.norm(parent_cfg.get(TV)):
        errs.append(f"{TV} differs from the parent's")
    name = cfg.get("name")
    if not isinstance(name, str) or not name.strip() or BAD_NAME.search(name):
        errs.append(f"name {name!r} has characters a file name cannot hold")
    return errs


# ---------- steps ----------

def _fill_nil(cfg: dict, where: str, log: list[str] | None) -> None:
    """Fill "nil" list items from the list's first real value; drop keys that hold nothing but "nil".
    Logged only when `log` is given (in-app values; the parent's own "nil" items are routine)."""
    log = log if log is not None else []
    for k in list(cfg):
        v = cfg[k]
        if v == "nil":
            del cfg[k]
            log.append(f"{where}: {k} dropped (\"nil\")")
        elif isinstance(v, list) and "nil" in v:
            real = [x for x in v if x != "nil"]
            if not real:
                del cfg[k]
                log.append(f"{where}: {k} dropped (only \"nil\")")
            else:
                cfg[k] = [real[0] if x == "nil" else x for x in v]
                log.append(f"{where}: {k} \"nil\" -> {real[0]} (no value for that variant)")


def _variants(cfg: dict) -> list[str]:
    v = cfg.get("filament_extruder_variant")
    if isinstance(v, list) and v:
        return [str(x) for x in v]
    t = cfg.get("nozzle_temperature")
    return values.variant_names(cfg, len(t) if isinstance(t, list) and t else 1)


def _ftype(line_type: str, parent_cfg: dict) -> str:
    t_type = _first(parent_cfg.get("filament_type")) or "PLA"
    if t_type == "TPU-AMS" or line_type not in BS_VALID:
        return t_type
    return line_type


def _write(base: Path, name: str, cfg: dict, info: dict) -> None:
    base.mkdir(parents=True, exist_ok=True)
    with open(base / f"{name}.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict(sorted(cfg.items())), fh, indent=4, ensure_ascii=False)
    with open(base / f"{name}.info", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(f"{k} = {v}\n" for k, v in info.items()))


def _copy_lines(src: dict[str, Line]) -> LineSet:
    out = LineSet({k: copy.deepcopy(v) for k, v in src.items()})
    out.invalid = copy.deepcopy(list(getattr(src, "invalid", [])))
    out.notes = list(getattr(src, "notes", []))
    return out


def _printers(models: list[str], problems: list[str]) -> list[tuple[str, int | None]]:
    out, seen = [], set()
    for m in models:
        name = models_mod.printer_preset_name(m)
        if name is None:
            problems.append(f"printer model {m!r} is unknown; no presets for it")
            continue
        if name not in seen:
            seen.add(name)
            out.append((name, models_mod.chamber_max(m)))
    return out


def build_all(*, filaments: list[dict], models: list[str], store: Store, library: Library,
              lines: dict[str, Line], live: Live | None, snapshot: Path | None, deleted_before: set[str],
              restore_deleted: bool, out_dir: Path, now: float) -> tuple[dict, dict[str, Line]]:
    """Build every preset into `out_dir/base`; returns (manifest, updated lines)."""
    out_dir = Path(out_dir)
    base_out = out_dir / "base"
    base_out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    clamps: list[str] = []
    edits: list[str] = []

    live_names = live.names() if live is not None else set()
    snap_names = _snapshot_names(snapshot)
    snap_cf = {n.casefold() for n in snap_names}
    # with no live upload nothing can be seen as deleted in the app now (only what was deleted before)
    seen_live = live_names if live is not None else snap_names
    reset = live is not None and inapp.is_reset(snap_names, live_names)
    if reset:
        problems.append(f"{len(snap_cf - {n.casefold() for n in live_names})} of {len(snap_names)} installed "
                        f"presets are gone from Bambu Studio at once; treated as an app reset, all rebuilt")
    live_cache: dict[str, tuple[dict | None, dict]] = {}

    def live_preset(name: str) -> tuple[dict | None, dict]:
        if live is None or name not in live_names:
            return None, {}
        if name not in live_cache:
            live_cache[name] = live.preset(name)
        return live_cache[name]

    used = set()
    for n in live_names:
        j, _info = live_preset(n)
        if j and isinstance(j.get("filament_id"), str):
            used.add(j["filament_id"])

    ls = _copy_lines(lines)
    groups = lines_mod.group(filaments, ls, library=library, store=store, used_fids=used)
    for line in ls.values():
        if line.parent_source != "user":
            lines_mod.rechoose(line, store, library=library)
    problems.extend(lines_mod.problems(ls))
    printers = _printers(models, problems)

    presets: list[dict] = []
    manifest_lines: dict[str, dict] = {}
    deleted: list[str] = []
    generated: set[str] = set()

    for lid in sorted(groups):
        line = ls[lid]
        fs = groups[lid]
        ids = sorted({f["id"] for f in fs if isinstance(f.get("id"), int) and not isinstance(f["id"], bool)})
        try:
            built = _build_line(line, fs, ids, printers=printers, store=store, library=library,
                                live_preset=live_preset, live_names=live_names, snap_cf=snap_cf, ls=ls,
                                snapshot=snapshot, seen_live=seen_live, snap_names=snap_names,
                                deleted_before=deleted_before, restore=restore_deleted, reset=reset,
                                base_out=base_out, user_id=live.user_id if live is not None else "", now=now,
                                problems=problems, clamps=clamps, edits=edits, deleted=deleted)
        except OSError:
            raise
        except Exception as e:  # one odd line never breaks the build
            problems.append(f"{lid}: skipped ({e.__class__.__name__}: {e})")
            continue
        for row in built:
            generated.add(row["name"].casefold())
        presets.extend(built)
        manifest_lines[lid] = {"filament_id": line.filament_id, "spoolman_ids": ids, "vendor": line.vendor,
                               "product": line.product}

    live_cf = {n.casefold() for n in live_names}
    stale = sorted(n for n in snap_names if n.casefold() not in generated and n.casefold() in live_cf)
    manifest = {"presets": presets, "lines": manifest_lines, "problems": problems, "clamps": clamps,
                "edits": edits, "deleted": sorted(deleted), "stale": stale, "library_version": library.version}
    return manifest, ls


def _build_line(line: Line, fs: list[dict], ids: list[int], *, printers, store: Store, library: Library,
                live_preset, live_names, snap_cf, ls: LineSet, snapshot, seen_live, snap_names, deleted_before,
                restore, reset, base_out: Path, user_id: str, now: float, problems, clamps, edits,
                deleted) -> list[dict]:
    if line.bambu_parent is None:
        return []                                   # reported by lines.problems
    sv = values.spoolman_values(fs)
    material = sv.material or line.material
    entry = values.merged_entry(library.lookup(line.vendor, line.product))
    abrasive = bool(values.ABRASIVE.search(material or "")) \
        or bool(values.ABRASIVE.search(str((entry or {}).get("material") or "")))
    bad = values.unsupported_nozzles(entry)
    btype = lines_mod.bs_type(material)

    plan = []
    for printer, chamber in printers:
        sizes = store.nozzles_for(line.bambu_parent, printer)
        if not sizes:
            problems.append(f"{line.line_id}: no {line.bambu_parent!r} system preset lists {printer} "
                            f"(only a compatible_printers_condition, or none); no {printer} presets")
            continue
        for nozzle in sizes:
            if (nozzle == "0.2" and abrasive) or nozzle in bad:
                continue
            plan.append((printer, chamber, nozzle, preset_name(line, printer, nozzle)))

    # an existing preset of the same name made in the app (not installed by us): keep its filament_id
    taken = {l.filament_id for k, l in ls.items() if k != line.line_id}
    for _p, _c, _n, name in plan:
        if name not in live_names or name.casefold() in snap_cf:
            continue
        j, _info = live_preset(name)
        fid = (j or {}).get("filament_id")
        if isinstance(fid, str) and fid != line.filament_id and ID_RE.fullmatch(fid) and fid not in taken:
            edits.append(f"{line.line_id}: filament_id {line.filament_id} -> {fid} (taken from your existing "
                         f"preset {name})")
            line.filament_id = fid
            break

    rows = []
    for printer, chamber, nozzle, name in plan:
        if inapp.deleted(name, snapshot=snap_names, live=seen_live, before=deleted_before, reset=reset,
                         restore=restore):
            deleted.append(name)
            continue
        parent = store.parent_for(line.bambu_parent, printer, nozzle)
        if parent is None:
            problems.append(f"{name}: no system parent; skipped")
            continue
        try:
            row = _build_preset(line, name, printer, chamber, nozzle, parent, sv, material, btype, entry, ids,
                                store=store, live_preset=live_preset, snapshot=snapshot, base_out=base_out,
                                user_id=user_id, now=now, problems=problems, clamps=clamps, edits=edits)
        except OSError:
            raise
        except Exception as e:
            problems.append(f"{name}: skipped ({e.__class__.__name__}: {e})")
            continue
        if row is not None:
            rows.append(row)
    return rows


def _build_preset(line: Line, name: str, printer: str, chamber, nozzle: str, parent: str, sv, material, btype,
                  entry, ids, *, store: Store, live_preset, snapshot, base_out: Path, user_id: str, now: float,
                  problems, clamps, edits) -> dict | None:
    # 1. the flattened parent
    parent_cfg = store.resolve(parent)
    cfg = copy.deepcopy(parent_cfg)
    for k in POP:
        cfg.pop(k, None)
    _fill_nil(cfg, name, None)
    template = copy.deepcopy(cfg)
    variants = _variants(cfg)
    # 2. common keys
    version = parent_cfg.get("version")
    cfg.update({"name": name, "from": "User", "filament_settings_id": [name], "filament_vendor": [line.vendor],
                "filament_type": [_ftype(btype, parent_cfg)], "inherits": "", "filament_id": line.filament_id,
                "compatible_printers": [f"{printer} {nozzle} nozzle"], "compatible_printers_condition": "",
                "compatible_prints": [], "compatible_prints_condition": "",
                "version": version if isinstance(version, str) and version else DEFAULT_VERSION})
    # 3. library (always: hardened material), 4. Spoolman
    values.apply_library(cfg, entry, template=template, printer=printer, nozzle=nozzle, chamber_max=chamber,
                         log=clamps, material=material)
    protected = values.apply_spoolman(cfg, sv, variants=variants, template=template)
    # 7 (before 5, so the owner's note lines go above the ids line). Notes in the Decision's order.
    summary = f"One profile for every {line.vendor} {line.product} colour in Spoolman ({sv.colors})."
    spec = values.spec_notes(entry)
    cfg["filament_notes"] = "\n".join([summary] + ([spec] if spec else [])
                                      + [f"{inapp.IDS_PREFIX} {', '.join(str(i) for i in ids)}"])
    # 5. in-app edits
    installed = _read_json(Path(snapshot) / "base" / f"{name}.json") if snapshot is not None else None
    live_cfg, live_info = live_preset(name)
    if installed is not None and live_cfg is not None:
        live_cfg = dict(live_cfg)
        if inapp.norm(live_cfg.get(TV)) != inapp.norm(installed.get(TV)):
            edits.append(f"{name}: {TV} {live_cfg.get(TV)} not kept (the generator never sets it)")
            if TV in installed:
                live_cfg[TV] = installed[TV]
            else:
                live_cfg.pop(TV, None)
    protected |= inapp.keep_edits(cfg, installed, live_cfg, edits)
    _fill_nil(cfg, name, edits)
    # 6. protected values outside a published bound: reported, kept
    values.report_outside(cfg, entry, protected, clamps)
    # 8. check
    errs = check_preset(cfg, parent_cfg)
    if errs:
        problems.append(f"{name}: skipped ({'; '.join(errs)})")
        return None
    # 9. files
    info = {"sync_info": "", "user_id": user_id, "setting_id": "", "base_id": "", "updated_time": int(now)}
    sid = (live_info or {}).get("setting_id")
    if sid:
        info.update(setting_id=sid, base_id=live_info.get("base_id", ""), sync_info="update")
    _write(base_out, name, cfg, info)
    return {"name": name, "line_id": line.line_id, "printer": printer, "nozzle": nozzle,
            "filament_id": cfg["filament_id"], "filament_type": _first(cfg["filament_type"]),
            "nozzle_temp_min": _int(cfg["nozzle_temperature_range_low"]),
            "nozzle_temp_max": _int(cfg["nozzle_temperature_range_high"]), "spoolman_ids": ids}
