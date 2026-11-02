"""The preset generator: one Bambu Studio filament preset per product line x printer model x nozzle (port of the
owner's filament-ops `gen.py` Bambu Studio part).

Each preset is flattened from its Bambu system parent (`inherits: ""`) and carries the line's own `filament_id`
(`P` + 7 hex digits), never a system id. Per preset, in this order: resolve the parent and drop its bookkeeping
keys, set the common keys, `values.apply_library` (always, so hardened materials get `required_nozzle_HRC`),
`values.apply_spoolman`, `inapp.keep_edits`, `values.report_outside`, the notes (summary, manufacturer specs,
MARK + the owner's lines, `Spoolman filament ids:` last), `check_preset`, then the files.

"nil" is never written: a parent list with "nil" items gets them filled from the list's first real value (an
all-"nil" key is dropped) before the library is applied and again after the in-app edits. The generator never sets
temperature_vitrification: it stays the parent's unless the owner edited it in the app (ruling S16: then the edit
is kept like any other; an edit that is only "nil" restores the parent's value).

In-app edits last (rulings S27, S28; see profiles.inapp): the manifest's `inapp` records, per preset, the in-app
values the build carried; the next build reads that record from the installed build's BUILD.json (or, after a
half-finished install, from the partial build's, whose values then never count as edits).

`restored` lists the presets a restore-deleted build brought back (deleted in the app before): the PC's installer
does not take their absence from Bambu Studio for a deletion made after the build.

A saved line's filament_id never changes (ruling S12). Only a line created in this run takes the filament_id of an
existing preset of the same name made in the app, or of its installed presets (lines.json was lost); for a saved
line that preset is reported and replaced.

A preset name the PC sync could not use as a file name (`safe_name`, its own rule) is skipped with a problem line:
the PC refuses a build zip holding one.

One line with odd data, or one bad preset, is skipped with a problem line; the rest of the build goes on.

Orca Slicer (Task 6): with `orca` given, `build_all` also writes the flat tree `out_dir/orca/` (see the Orca
section at the end: names `<line> @SV08 MAX 0.4` / `<line> @H2D 0.4` as filament-ops gen.py made them, presets
that inherit their system parent and write only what differs, never "nil", never G-code of their own), re-checks
every line's Orca parent against the uploaded Orca store (`lines.rechoose_orca`), and adds a `target`
("bambu_studio" | "orca") to every preset row plus `orca_inapp`, `orca_deleted`, `orca_restored`, `orca_stale`
(in-app edits, deletions and restores are kept per target: the same rules, apart). An Orca preset whose parent
is not in the uploaded Orca store is a problem line and is not written. Without `orca` the manifest is exactly
what it was before the Orca target.
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
from .orca import SYSTEM

ID_RE = re.compile(r"^P[0-9a-f]{7}$")
# the PC sync's rule for a preset file name (pc-sync zips._safe_name, for <name>.json and <name>.info): one name it
# refuses would make it refuse the whole build zip
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_FILE_NAME = 200                             # characters of <name>.json, as the PC counts them
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
    """The user filament folder the PC sync uploaded (`root/base/<name>.json` + `.info`; Orca Slicer's is flat:
    `sub=""`, `root/<name>.json`)."""
    root: Path
    user_id: str
    sub: str = "base"

    def _dir(self) -> Path:
        return Path(self.root) / self.sub if self.sub else Path(self.root)

    def preset(self, name: str) -> tuple[dict | None, dict]:
        base = self._dir()
        return _read_json(base / f"{name}.json"), _read_info(base / f"{name}.info")

    def names(self) -> set[str]:
        base = self._dir()
        if not base.is_dir():
            return set()
        return {p.stem for p in base.iterdir() if p.is_file() and p.suffix.casefold() == ".json"}


def _recorded(build_dir: Path | None, key: str = "inapp") -> dict[str, dict]:
    """The in-app edits a build carried ({preset name: {key: value}}, its BUILD.json `inapp`; `orca_inapp` for
    the Orca tree), {} when none."""
    if build_dir is None:
        return {}
    m = _read_json(Path(build_dir) / "BUILD.json")
    rec = (m or {}).get(key)
    if not isinstance(rec, dict):
        return {}
    return {n: v for n, v in rec.items() if isinstance(n, str) and isinstance(v, dict)}


def _snapshot_names(snapshot: Path | None, tree: str = "base") -> set[str]:
    base = Path(snapshot) / tree if snapshot is not None else None
    if base is None or not base.is_dir():
        return set()
    return {p.stem for p in base.iterdir() if p.is_file() and p.suffix.casefold() == ".json"}


def _snapshot_fid(snapshot: Path | None, snap_names: set[str], name: str):
    """The filament_id of the installed copy of preset `name` (matched casefolded), or None."""
    if snapshot is None:
        return None
    key = name.casefold()
    real = next((n for n in snap_names if n.casefold() == key), None)
    return (_read_json(Path(snapshot) / "base" / f"{real}.json") or {}).get("filament_id") if real else None


# ---------- checks ----------

def safe_name(name) -> bool:
    """True when `name` + ".json" / ".info" is a file name the PC sync accepts (the same rule as pc-sync
    zips._safe_name): no control or reserved characters, no leading dot or space, no trailing dot or space, not a
    reserved Windows device name, at most MAX_FILE_NAME characters with the suffix."""
    if not isinstance(name, str) or not name or len(name) + len(".json") > MAX_FILE_NAME:
        return False
    if _BAD_CHARS.search(name) or name.startswith(".") or name[0] == " " or name[-1] in " .":
        return False
    return name.split(".")[0].upper().rstrip() not in _RESERVED


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


def check_preset(cfg: dict, parent_cfg: dict, *, edited: dict | None = None) -> list[str]:
    """Why this preset must not be written ([] = good). `edited` = the owner's in-app values that were kept;
    temperature_vitrification may equal the edited value instead of the parent's."""
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
    tv = inapp.norm(cfg.get(TV))
    if tv != inapp.norm(parent_cfg.get(TV)) and not (edited and TV in edited and tv == inapp.norm(edited[TV])):
        errs.append(f"{TV} differs from the parent's")
    name = cfg.get("name")
    if not safe_name(name):
        errs.append(f"name {name!r} cannot be a file name on the PC")
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
              restore_deleted: bool, out_dir: Path, now: float,
              partial: Path | None = None, owner_edits: dict | None = None,
              orca: "OrcaTarget | None" = None) -> tuple[dict, dict[str, Line]]:
    """Build every preset into `out_dir/base`; returns (manifest, updated lines). `snapshot` = the installed
    build's folder; `partial` = a build whose install stopped part-way (its values in live are not edits);
    `owner_edits` = {inapp: {preset: {key: value}}, notes: {preset: [lines]}} saved when the sync PC changed
    (ruling S34): with no snapshot and no partial build it is the record of the owner's edits and note lines.
    `orca` (None: Bambu Studio only, the manifest exactly as before the Orca target) adds the Orca tree
    `out_dir/orca/` (see `OrcaTarget`)."""
    out_dir = Path(out_dir)
    base_out = out_dir / "base"
    base_out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    clamps: list[str] = []
    edits: list[str] = []
    carried: dict[str, dict] = {}
    recorded = _recorded(partial) if partial is not None else _recorded(snapshot)
    kept_notes: dict[str, list[str]] = {}
    if snapshot is None and isinstance(owner_edits, dict):
        if partial is None:
            rec = owner_edits.get("inapp")
            recorded = {n: v for n, v in rec.items() if isinstance(n, str) and isinstance(v, dict)} \
                if isinstance(rec, dict) else {}
        nts = owner_edits.get("notes")
        if isinstance(nts, dict):
            kept_notes = {n: [x for x in v if isinstance(x, str)] for n, v in nts.items()
                          if isinstance(n, str) and isinstance(v, list)}

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
    before = set(ls)
    groups: dict[str, list[dict]] = {}
    for f in filaments:                     # one at a time: one odd filament never breaks the build
        try:
            for lid, fs in lines_mod.group([f], ls, library=library, store=store, used_fids=used).items():
                groups.setdefault(lid, []).extend(fs)
        except Exception as e:
            fid = f.get("id") if isinstance(f, dict) else None
            problems.append(f"filament {fid}: skipped ({e.__class__.__name__}: {e})")
    new_lines = set(ls) - before
    for line in list(ls.values()):
        if line.parent_source != "user":
            try:
                lines_mod.rechoose(line, store, library=library)
            except Exception as e:
                problems.append(f"{line.line_id}: parent not re-checked ({e.__class__.__name__}: {e})")
    if orca is not None and orca.store is not None:
        # lines made by intake before the Orca store was uploaded get a store-backed Orca parent now
        for line in list(ls.values()):
            if line.orca_parent_source != "user":
                try:
                    lines_mod.rechoose_orca(line, orca.store, library=library)
                except Exception as e:
                    problems.append(f"{line.line_id}: Orca parent not re-checked ({e.__class__.__name__}: {e})")
    problems.extend(lines_mod.problems(ls))
    printers = _printers(models, problems)

    presets: list[dict] = []
    manifest_lines: dict[str, dict] = {}
    deleted: list[str] = []
    restored: list[str] = []                # brought back by restore-deleted (the PC must not see a deletion)
    generated: set[str] = set()
    planned: set[str] = set()               # casefolded names planned this run, built or not

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
                                problems=problems, clamps=clamps, edits=edits, deleted=deleted,
                                restored=restored, planned=planned, new_line=lid in new_lines, recorded=recorded,
                                partial=partial, carried=carried, kept_notes=kept_notes)
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
    # a line still in Spoolman keeps its presets even if some were skipped this run (problems say why)
    prefixes = tuple(f"{ls[lid].vendor} {ls[lid].product} @".casefold() for lid in groups if lid in ls)
    stale = sorted(n for n in snap_names if n.casefold() in live_cf and n.casefold() not in generated
                   and n.casefold() not in planned and not n.casefold().startswith(prefixes))
    manifest = {"presets": presets, "lines": manifest_lines, "problems": problems, "clamps": clamps,
                "edits": edits, "inapp": dict(sorted(carried.items())), "deleted": sorted(deleted),
                "restored": sorted(restored), "stale": stale,
                "library_version": library.version}
    if orca is not None:
        for row in presets:
            row["target"] = BAMBU_STUDIO
        manifest.update(_build_orca(orca, groups=groups, ls=ls, library=library, restore=restore_deleted,
                                    out_dir=out_dir, now=now, problems=problems, clamps=clamps, edits=edits))
        presets.extend(manifest.pop("_rows"))
    return manifest, ls


def _build_line(line: Line, fs: list[dict], ids: list[int], *, printers, store: Store, library: Library,
                live_preset, live_names, snap_cf, ls: LineSet, snapshot, seen_live, snap_names, deleted_before,
                restore, reset, base_out: Path, user_id: str, now: float, problems, clamps, edits,
                deleted, planned: set[str], new_line: bool, restored: list[str] | None = None,
                recorded: dict[str, dict], partial: Path | None,
                carried: dict[str, dict], kept_notes: dict[str, list[str]] | None = None) -> list[dict]:
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
    unsafe: set[str] = set()
    for printer, chamber in printers:
        sizes = store.nozzles_for(line.bambu_parent, printer)
        if not sizes:
            problems.append(f"{line.line_id}: no {line.bambu_parent!r} system preset lists {printer} "
                            f"(only a compatible_printers_condition, or none); no {printer} presets")
            continue
        for nozzle in sizes:
            if (nozzle == "0.2" and abrasive) or nozzle in bad:
                continue
            if not safe_name(preset_name(line, printer, nozzle)):
                unsafe.add(preset_name(line, printer, nozzle))
                continue
            plan.append((printer, chamber, nozzle, preset_name(line, printer, nozzle)))
            planned.add(plan[-1][3].casefold())
    for name in sorted(unsafe):                 # only these presets are skipped; the PC would refuse the whole zip
        problems.append(f"{name!r} cannot be a file name on the PC (check the vendor and line name); skipped")

    # an existing preset of the same name made in the app (not installed by us): keep its filament_id
    # (only for a line created in this run: a saved line's filament_id never changes). A line created in this run
    # whose presets were installed (lines.json was lost) takes the installed presets' filament_id.
    taken = lines_mod._taken_fids(ls)
    for _p, _c, _n, name in plan:
        if name.casefold() in snap_cf:
            if not new_line:
                continue
            fid = _snapshot_fid(snapshot, snap_names, name)
            if isinstance(fid, str) and ID_RE.fullmatch(fid) and fid != line.filament_id and fid not in taken:
                edits.append(f"{line.line_id}: filament_id {line.filament_id} -> {fid} (taken from the installed "
                             f"preset {name})")
                line.filament_id = fid
                new_line = False
            continue
        if name not in live_names:
            continue
        j, _info = live_preset(name)
        fid = (j or {}).get("filament_id")
        if fid == line.filament_id:
            continue
        if new_line and isinstance(fid, str) and ID_RE.fullmatch(fid) and fid not in taken:
            edits.append(f"{line.line_id}: filament_id {line.filament_id} -> {fid} (taken from your existing "
                         f"preset {name})")
            line.filament_id = fid
            new_line = False                # adopt once
            continue
        problems.append(f"your preset {name} has filament_id {fid}; line keeps {line.filament_id}, "
                        f"the generated preset replaces it")

    rows = []
    for printer, chamber, nozzle, name in plan:
        if inapp.deleted(name, snapshot=snap_names, live=seen_live, before=deleted_before, reset=reset,
                         restore=restore):
            deleted.append(name)
            continue
        brought_back = restore and inapp.deleted(name, snapshot=snap_names, live=seen_live, before=deleted_before,
                                                 reset=reset, restore=False)
        parent = store.parent_for(line.bambu_parent, printer, nozzle)
        if parent is None:
            problems.append(f"{name}: no system parent; skipped")
            continue
        try:
            row = _build_preset(line, name, printer, chamber, nozzle, parent, sv, material, btype, entry, ids,
                                store=store, live_preset=live_preset, snapshot=snapshot, base_out=base_out,
                                user_id=user_id, now=now, problems=problems, clamps=clamps, edits=edits,
                                recorded=recorded.get(name), partial=partial, carried=carried,
                                notes=(kept_notes or {}).get(name))
        except OSError:
            raise
        except Exception as e:
            problems.append(f"{name}: skipped ({e.__class__.__name__}: {e})")
            continue
        if row is not None:
            rows.append(row)
            if brought_back and restored is not None:
                restored.append(name)
    return rows


def _build_preset(line: Line, name: str, printer: str, chamber, nozzle: str, parent: str, sv, material, btype,
                  entry, ids, *, store: Store, live_preset, snapshot, base_out: Path, user_id: str, now: float,
                  problems, clamps, edits, recorded: dict | None = None, partial: Path | None = None,
                  carried: dict[str, dict] | None = None, notes: list[str] | None = None) -> dict | None:
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
    half = _read_json(Path(partial) / "base" / f"{name}.json") if partial is not None else None
    mine = inapp.keep_edits(cfg, installed, live_cfg, edits, recorded=recorded, partial=half, notes=notes)
    taken = set(mine)
    protected |= taken
    _fill_nil(cfg, name, edits)
    edited = None
    if TV in taken:
        if TV in cfg:
            edited = {TV: cfg[TV]}
        else:                               # the in-app value was only "nil": the parent's again
            if TV in template:
                cfg[TV] = copy.deepcopy(template[TV])
            edits.append(f"{name}: {TV} was only \"nil\" in the app; the parent's value is used")
    # 6. protected values outside a published bound: reported, kept
    values.report_outside(cfg, entry, protected, clamps)
    # 8. check
    parent_view = dict(parent_cfg)          # the parent's TV after its own "nil" items were filled
    if TV in template:
        parent_view[TV] = template[TV]
    else:
        parent_view.pop(TV, None)
    errs = check_preset(cfg, parent_view, edited=edited)
    if errs:
        problems.append(f"{name}: skipped ({'; '.join(errs)})")
        return None
    # 9. files
    info = {"sync_info": "", "user_id": user_id, "setting_id": "", "base_id": "", "updated_time": int(now)}
    sid = (live_info or {}).get("setting_id")
    if sid:
        info.update(setting_id=sid, base_id=live_info.get("base_id", ""), sync_info="update")
    _write(base_out, name, cfg, info)
    if mine and carried is not None:
        carried[name] = mine
    return {"name": name, "line_id": line.line_id, "printer": printer, "nozzle": nozzle,
            "filament_id": cfg["filament_id"], "filament_type": _first(cfg["filament_type"]),
            "nozzle_temp_min": _int(cfg["nozzle_temperature_range_low"]),
            "nozzle_temp_max": _int(cfg["nozzle_temperature_range_high"]), "spoolman_ids": ids}


# ---------- the Orca Slicer target (Task 6, Rulings L and O) ----------
#
# Orca presets are not flattened: each one inherits its system parent and writes only what differs from it plus
# the preset's own keys. A configured (non-Bambu) printer (config `slicer_printers`) inherits the line's Orca
# library parent (`"<orca_parent> @System"`, from the uploaded OrcaFilamentLibrary index); a Bambu printer
# (config `presets_orca`) inherits the Orca BBL system preset of the line's Bambu parent for that printer and
# nozzle (`... @BBL H2D 0.6 nozzle`). Names match filament-ops gen.py (`<line> @SV08 MAX 0.4`, `<line> @H2D
# 0.4`), so the owner's existing Orca presets are adopted: a live preset of the same name (any letter case) keeps
# its spelling, its .info setting_id and its filament_id. Values follow the Bambu Studio policy (library on the
# parent's values, Spoolman on top, in-app edits last); "nil" is never written. G-code: none of our own; a
# carried in-app G-code value only while the live preset still holds it (the PC refuses anything else).

BAMBU_STUDIO, ORCA = "bambu_studio", "orca"
ORCA_DEFAULT_VERSION = "2.4.0.16"           # what ops wrote for library-parent presets (no parent version known)
_NOZZLE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class OrcaPrinter:
    name: str                   # the printer Orca knows: "Bambu Lab H2D", or the configured "Sovol SV08 MAX"
    label: str                  # in preset names: "<line> @<label> <nozzle>" ("H2D", "SV08 MAX")
    bambu: bool                 # parents from Orca's BBL system presets; nozzles from them, per line
    nozzles: list[str]          # a configured printer's nozzles; for a Bambu printer the allowed ones ([]: all
                                # the store lists but 0.2, as ops made them: Ruling W)
    compat: dict[str, str]      # nozzle -> compatible_printers entry (a configured printer's own preset names)
    chamber: int | None = None

    def compatible(self, nozzle: str) -> str:
        return self.compat.get(nozzle) or f"{self.name} {nozzle} nozzle"


@dataclass
class OrcaTarget:
    """What an Orca build needs. `store` = the uploaded Orca system presets (None: no Orca presets, one problem);
    `live` = Orca's uploaded user filament folder (`Live(..., sub="")`); `snapshot`/`partial` = the installed /
    half-installed build folders (their `orca/` tree and BUILD.json `orca_inapp`); `deleted_before` = Orca preset
    names deleted in the app; `owner_edits` = {inapp, notes} of the Orca tree kept across a PC change (S34)."""
    store: object | None
    printers: list[OrcaPrinter]
    problems: list[str]
    live: Live | None = None
    snapshot: Path | None = None
    partial: Path | None = None
    deleted_before: set[str] | None = None
    owner_edits: dict | None = None
    user_id: str = ""           # Orca's user id as the PC sync reported it (the .info user_id without a live folder)


def _label(name: str) -> str:
    if name.startswith("Bambu Lab "):
        return name[len("Bambu Lab "):]
    return name.split(" ", 1)[1] if " " in name.strip() else name


def orca_printers(models: list[str], slicer_printers: list,
                  bambu_nozzles: list | None = None) -> tuple[list[OrcaPrinter], list[str]]:
    """(the Orca printers, problems): the Bambu `models` (pass the registry's when `presets_orca` is on, else
    []), then each valid `slicer_printers` entry {"name", "slicer": "orca", "nozzles": [...], optional "label",
    optional "compatible_printers": {nozzle: printer preset name}}. A bad entry is a problem line.
    `bambu_nozzles` (config `presets_orca_nozzles`) limits the Bambu printers' Orca nozzles; None: every nozzle
    the Orca store lists except 0.2 (Ruling W: ops made Orca H2D presets for 0.4/0.6/0.8 only)."""
    out: list[OrcaPrinter] = []
    problems: list[str] = []
    seen: set[str] = set()
    allowed: list[str] = []
    if bambu_nozzles is not None:
        if isinstance(bambu_nozzles, list) and all(isinstance(n, str) and _NOZZLE.fullmatch(n)
                                                   for n in bambu_nozzles):
            allowed = list(dict.fromkeys(bambu_nozzles))
        else:
            problems.append("config presets_orca_nozzles must be a list of sizes such as 0.4; the default "
                            "(all but 0.2) is used")
    for m in models:
        name = models_mod.printer_preset_name(m)
        if name is None:
            problems.append(f"printer model {m!r} is unknown; no Orca Slicer presets for it")
            continue
        if name not in seen:
            seen.add(name)
            out.append(OrcaPrinter(name, _label(name), True, list(allowed), {}, models_mod.chamber_max(m)))
    for i, e in enumerate(slicer_printers or []):
        where = f"config slicer_printers[{i}]"
        if not isinstance(e, dict):
            problems.append(f"{where}: not an object; ignored")
            continue
        name, slicer, nozzles = e.get("name"), e.get("slicer", ORCA), e.get("nozzles")
        compat, label = e.get("compatible_printers", {}), e.get("label")
        if not (isinstance(name, str) and name.strip()):
            problems.append(f"{where}: no name; ignored")
            continue
        if slicer != ORCA:
            problems.append(f"{where} {name!r}: slicer {slicer!r} is not supported (only orca); ignored")
            continue
        if not (isinstance(nozzles, list) and nozzles and all(isinstance(n, str) and _NOZZLE.fullmatch(n)
                                                                for n in nozzles)):
            problems.append(f"{where} {name!r}: nozzles must be a list of sizes such as 0.4; ignored")
            continue
        if not (isinstance(compat, dict) and all(isinstance(k, str) and isinstance(v, str) and v.strip()
                                                 for k, v in compat.items())):
            problems.append(f"{where} {name!r}: compatible_printers must map a nozzle to a printer name; ignored")
            continue
        if label is not None and not (isinstance(label, str) and label.strip()):
            problems.append(f"{where} {name!r}: label must be text; ignored")
            continue
        name = name.strip()
        if name in seen:
            problems.append(f"{where}: printer {name!r} is listed twice; ignored")
            continue
        seen.add(name)
        out.append(OrcaPrinter(name, label.strip() if label else _label(name), False, list(dict.fromkeys(nozzles)),
                               {k: v.strip() for k, v in compat.items()}))
    return out, problems


def orca_preset_name(line: Line, printer: OrcaPrinter, nozzle: str) -> str:
    return f"{line.vendor} {line.product} @{printer.label} {nozzle}"


def _orca_recorded(t: OrcaTarget) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """(the Orca in-app record to start from, the owner's saved Orca note lines): the partial build's record,
    else the installed build's, else (a new sync PC, S34) the owner's kept record and note lines."""
    if t.partial is not None:
        return _recorded(t.partial, "orca_inapp"), {}
    if t.snapshot is not None:
        return _recorded(t.snapshot, "orca_inapp"), {}
    oe = t.owner_edits if isinstance(t.owner_edits, dict) else {}
    rec, nts = oe.get("inapp"), oe.get("notes")
    rec = {n: v for n, v in rec.items() if isinstance(n, str) and isinstance(v, dict)} if isinstance(rec, dict) else {}
    nts = {n: [x for x in v if isinstance(x, str)] for n, v in nts.items()
           if isinstance(n, str) and isinstance(v, list)} if isinstance(nts, dict) else {}
    return rec, nts


def _build_orca(t: OrcaTarget, *, groups: dict[str, list[dict]], ls: LineSet, library: Library, restore: bool,
                out_dir: Path, now: float, problems: list[str], clamps: list[str], edits: list[str]) -> dict:
    """The Orca tree `out_dir/orca/` for every grouped line; returns the manifest's Orca keys (+ `_rows`)."""
    problems.extend(t.problems)
    rows: list[dict] = []
    carried: dict[str, dict] = {}
    deleted: list[str] = []
    restored: list[str] = []
    active = bool(t.printers) and t.store is not None
    if t.printers and t.store is None:
        problems.append("no Orca Slicer system presets yet (the PC sync uploads them once Orca Slicer is set up); "
                        "no Orca Slicer presets")
    live_names = t.live.names() if t.live is not None else set()
    live_by_cf = {n.casefold(): n for n in sorted(live_names)}
    snap_names = _snapshot_names(t.snapshot, ORCA)
    seen_live = live_names if t.live is not None else snap_names
    reset = t.live is not None and inapp.is_reset(snap_names, live_names)
    if reset and active:
        gone = len({n.casefold() for n in snap_names} - set(live_by_cf))
        problems.append(f"{gone} of {len(snap_names)} installed Orca Slicer presets are gone from Orca Slicer at "
                        f"once; treated as an app reset, all rebuilt")
    recorded, kept_notes = _orca_recorded(t)
    generated: set[str] = set()
    planned: set[str] = set()
    cache: dict[str, tuple[dict | None, dict]] = {}

    def live_preset(name: str) -> tuple[dict | None, dict]:
        if t.live is None or name not in live_names:
            return None, {}
        if name not in cache:
            cache[name] = t.live.preset(name)
        return cache[name]

    if active:
        out_tree = Path(out_dir) / ORCA
        out_tree.mkdir(parents=True, exist_ok=True)
        for lid in sorted(groups):
            if lid not in ls:
                continue
            fs = groups[lid]
            ids = sorted({f["id"] for f in fs if isinstance(f.get("id"), int) and not isinstance(f["id"], bool)})
            try:
                built = _build_orca_line(ls[lid], fs, ids, t=t, library=library, restore=restore, reset=reset,
                                         out_tree=out_tree, now=now, live_preset=live_preset, live_by_cf=live_by_cf,
                                         snap_names=snap_names, seen_live=seen_live, recorded=recorded,
                                         kept_notes=kept_notes, problems=problems, clamps=clamps, edits=edits,
                                         carried=carried, deleted=deleted, restored=restored, planned=planned)
            except OSError:
                raise
            except Exception as e:  # one odd line never breaks the build
                problems.append(f"{lid}: no Orca Slicer presets ({e.__class__.__name__}: {e})")
                continue
            for row in built:
                generated.add(row["name"].casefold())
            rows.extend(built)
    prefixes = tuple(f"{ls[lid].vendor} {ls[lid].product} @".casefold() for lid in groups if lid in ls)
    stale = sorted(n for n in snap_names if n.casefold() in live_by_cf and n.casefold() not in generated
                   and n.casefold() not in planned and not n.casefold().startswith(prefixes))
    return {"_rows": rows, "orca_inapp": dict(sorted(carried.items())), "orca_deleted": sorted(deleted),
            "orca_restored": sorted(restored), "orca_stale": stale}


def _build_orca_line(line: Line, fs: list[dict], ids: list[int], *, t: OrcaTarget, library: Library, restore,
                     reset, out_tree: Path, now: float, live_preset, live_by_cf, snap_names, seen_live, recorded,
                     kept_notes, problems, clamps, edits, carried, deleted, restored, planned) -> list[dict]:
    store = t.store
    sv = values.spoolman_values(fs)
    material = sv.material or line.material
    entry = values.merged_entry(library.lookup(line.vendor, line.product))
    abrasive = bool(values.ABRASIVE.search(material or "")) \
        or bool(values.ABRASIVE.search(str((entry or {}).get("material") or "")))
    bad = values.unsupported_nozzles(entry)

    plan = []
    for p in t.printers:
        if p.bambu:
            if line.bambu_parent is None:
                continue                                # reported by lines.problems
            sizes = [n for n in store.bbl.nozzles_for(line.bambu_parent, p.name)
                     if (n in p.nozzles if p.nozzles else n != "0.2")]
            if not sizes:
                problems.append(f"{line.line_id}: no Orca Slicer {line.bambu_parent!r} system preset lists "
                                f"{p.name}; no Orca Slicer {p.label} presets")
                continue
        else:
            sizes = p.nozzles
        for nozzle in sizes:
            if (nozzle == "0.2" and abrasive) or nozzle in bad:
                continue
            name = orca_preset_name(line, p, nozzle)
            name = live_by_cf.get(name.casefold(), name)     # the owner's spelling: never a case twin
            if not safe_name(name):
                problems.append(f"{name!r} cannot be a file name on the PC (check the vendor and line name); skipped")
                continue
            plan.append((p, nozzle, name))
            planned.add(name.casefold())

    rows = []
    before = t.deleted_before or set()
    for p, nozzle, name in plan:
        if inapp.deleted(name, snapshot=snap_names, live=seen_live, before=before, reset=reset, restore=restore):
            deleted.append(name)
            continue
        brought_back = restore and inapp.deleted(name, snapshot=snap_names, live=seen_live, before=before,
                                                 reset=reset, restore=False)
        if p.bambu:
            parent = store.system_parent_for(p.name, nozzle, line.bambu_parent)
            template = store.parent(parent) if parent is not None else None
            if template is None:
                problems.append(f"{name}: no Orca Slicer {line.bambu_parent!r} system preset for {p.name} "
                                f"{nozzle} (or it does not resolve); skipped")
                continue
            base_id = template.get("setting_id")
        else:
            parent = f"{line.orca_parent}{SYSTEM}" if line.orca_parent else None
            lib_row = store.library.get(parent) if parent is not None else None
            if lib_row is None:
                why = (f"Orca parent {parent!r} is not in the uploaded Orca Slicer system presets" if parent
                       else "no Orca parent")
                problems.append(f"{name}: {why}; skipped (set one: filament-kit profiles set-parent "
                                f"{line.line_id} <parent> --orca)")
                continue
            template, base_id = {}, lib_row.get("setting_id")
        try:
            row = _build_orca_preset(line, name, p, nozzle, parent, template, base_id, sv, material, entry, ids,
                                     t=t, live_preset=live_preset, out_tree=out_tree, now=now, problems=problems,
                                     clamps=clamps, edits=edits, recorded=recorded.get(name), carried=carried,
                                     notes=kept_notes.get(name))
        except OSError:
            raise
        except Exception as e:
            problems.append(f"{name}: skipped ({e.__class__.__name__}: {e})")
            continue
        if row is not None:
            rows.append(row)
            if brought_back:
                restored.append(name)
    return rows


def check_orca_preset(cfg: dict) -> list[str]:
    """Why this Orca preset must not be written ([] = good)."""
    errs = []
    if _has_nil(cfg):
        errs.append('a value is "nil"')
    if not (isinstance(cfg.get("inherits"), str) and cfg["inherits"]):
        errs.append("inherits is empty")
    cp = cfg.get("compatible_printers")
    if not (isinstance(cp, list) and len(cp) == 1 and isinstance(cp[0], str)):
        errs.append("compatible_printers is not a single printer")
    v = cfg.get("filament_extruder_variant")
    if not (isinstance(v, list) and v):
        errs.append("filament_extruder_variant is empty")
    notes = inapp.notes_text(cfg.get("filament_notes")).splitlines()
    if not notes or not notes[-1].startswith(inapp.IDS_PREFIX + " "):
        errs.append("notes do not end with the Spoolman filament ids")
    if not safe_name(cfg.get("name")):
        errs.append(f"name {cfg.get('name')!r} cannot be a file name on the PC")
    return errs


def _build_orca_preset(line: Line, name: str, p: OrcaPrinter, nozzle: str, parent: str, template: dict, base_id,
                       sv, material, entry, ids, *, t: OrcaTarget, live_preset, out_tree: Path, now: float,
                       problems, clamps, edits, recorded: dict | None, carried: dict[str, dict],
                       notes: list[str] | None) -> dict | None:
    # 1. the parent's values (only to compare against: the preset inherits them)
    tmpl = copy.deepcopy(template)
    for k in POP:
        tmpl.pop(k, None)
    _fill_nil(tmpl, name, None)
    variants = _variants(tmpl) if p.bambu else t.store.printer_variants(p.name)
    # 2. library on the parent's values, Spoolman on top (the Bambu Studio policy)
    full = copy.deepcopy(tmpl)
    values.apply_library(full, entry, template=tmpl, printer=p.name, nozzle=nozzle, chamber_max=p.chamber,
                         log=clamps, material=material)
    protected = values.apply_spoolman(full, sv, variants=variants, template=tmpl)
    # 3. only what differs from the parent, never G-code, plus the preset's own keys
    cfg = {k: v for k, v in full.items() if (k not in tmpl or inapp.norm(v) != inapp.norm(tmpl[k]))
           and "gcode" not in k.lower()}
    ftype = lines_mod.orca_type(material) or _first(tmpl.get("filament_type")) or "PLA"
    version = tmpl.get("version") if p.bambu else None
    live_cfg, live_info = live_preset(name)
    cfg.update({"name": name, "from": "User", "filament_settings_id": [name], "filament_vendor": [line.vendor],
                "filament_type": [ftype], "inherits": parent, "compatible_printers": [p.compatible(nozzle)],
                "filament_extruder_variant": list(variants),
                "version": version if isinstance(version, str) and version else ORCA_DEFAULT_VERSION})
    fid = (live_cfg or {}).get("filament_id")
    if isinstance(fid, str) and fid:
        cfg["filament_id"] = fid                    # the owner's preset keeps its filament id (adoption)
    summary = f"One profile for every {line.vendor} {line.product} colour in Spoolman ({sv.colors})."
    spec = values.spec_notes(entry)
    cfg["filament_notes"] = "\n".join([summary] + ([spec] if spec else [])
                                      + [f"{inapp.IDS_PREFIX} {', '.join(str(i) for i in ids)}"])
    # 4. in-app edits
    installed = _read_json(Path(t.snapshot) / ORCA / f"{name}.json") if t.snapshot is not None else None
    half = _read_json(Path(t.partial) / ORCA / f"{name}.json") if t.partial is not None else None
    mine = inapp.keep_edits(cfg, installed, live_cfg, edits, recorded=recorded, partial=half, notes=notes)
    _fill_nil(cfg, name, edits)
    for k in [k for k in cfg if "gcode" in k.lower()]:
        if live_cfg is None or inapp.norm(live_cfg.get(k)) != inapp.norm(cfg[k]):
            del cfg[k]
            mine.pop(k, None)
            problems.append(f"{name}: {k} not written (an in-app G-code value is only kept while Orca Slicer "
                            f"still holds it)")
    # 5. protected values outside a published bound: reported, kept
    values.report_outside(cfg, entry, protected | set(mine), clamps)
    errs = check_orca_preset(cfg)
    if errs:
        problems.append(f"{name}: skipped ({'; '.join(errs)})")
        return None
    # 6. files
    info = {"sync_info": "", "user_id": (t.live.user_id if t.live is not None else "") or t.user_id,
            "setting_id": "",
            "base_id": base_id if isinstance(base_id, str) else "", "updated_time": int(now)}
    sid = (live_info or {}).get("setting_id")
    if sid:
        info.update(setting_id=sid, sync_info="update")
    _write(out_tree, name, cfg, info)
    if mine:
        carried[name] = mine
    view = {**tmpl, **cfg}
    return {"target": ORCA, "name": name, "line_id": line.line_id, "printer": p.name, "nozzle": nozzle,
            "parent": parent, "filament_id": cfg.get("filament_id"), "filament_type": ftype,
            "nozzle_temp_min": _int(view.get("nozzle_temperature_range_low")),
            "nozzle_temp_max": _int(view.get("nozzle_temperature_range_high")), "spoolman_ids": ids}
