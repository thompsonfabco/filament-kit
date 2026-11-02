"""Installs a downloaded build into the live Bambu Studio user folder, and its Orca Slicer tree into the live
Orca Slicer user folder (port of install.py).

A build holds `base/` (Bambu Studio, installed into <user filament>/base) and may hold `orca/` (Orca Slicer,
installed flat into Orca's user filament folder). The Orca tree is installed only when this PC has Orca
Slicer (`orca` given); otherwise it is left out, also from the snapshot. Each target gets the same checks.

Order (each check runs before anything is written):
  1. the staged names come from build_dir/base and build_dir/orca;
  2. untrusted G-code: for Bambu Studio every value of a key containing "gcode" must equal a value from this
     PC's system filament presets, a value of the installed snapshot (dirs.installed: this PC accepted it
     once, e.g. the owner's G-code edit carried after an app reset), or the live preset's current value; for
     Orca Slicer (whose presets inherit their G-code from `@System`) a "gcode" key is only allowed with the
     live preset's current value (the builder never writes G-code of its own);
  3. a preset edited or deleted in the app after the build was made refuses the install
     (unless more than a quarter of the installed presets vanished at once: an app reset); a live
     value equal to the copy in dirs.partial (a build whose install stopped part-way, ruling S28) was
     written by that install, not typed in the app, so it is not an edit (the server agrees); nor is
     a live value equal to the build's own record of the in-app values it carried (BUILD.json
     `inapp`, `orca_inapp` for Orca: the build saw it, e.g. a "nil" it filled in); a preset the build
     brought back on `profiles restore-deleted` (BUILD.json `restored`, `orca_restored`) is not a deletion;
  4. Bambu Studio (and Orca Slicer, when its tree is installed) must not be running; this is checked again
     right before the first write, and if one runs then nothing is written, not even the backup;
  5. the user filament folders (which must exist) are backed up to dirs.backups/<stamp> and
     dirs.orca_backups/<same name> (the 5 newest of each are kept); a backup that fails part-way is removed
     and the install refused;
  6. each staged .json is copied in and its .info written, keeping a live cloud setting_id; every
     file goes to a sibling `.<name>.fktmp` first and is renamed over the target, so a crash never
     leaves a half-written preset (leftover temp files are removed at the start of this phase);
  7. nothing is ever deleted: presets no longer built but still live are returned as `stale` /
     `stale_orca` (they are deleted in the app, never on disk);
  8. dirs.installed is replaced with a copy of the build (temp dir + rename).
"""
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import inapp, studio
from .store import AppDirs
from .studio import OrcaFolders, StudioFolders

KEEP_BACKUPS = 5
STUDIO_RUNNING = "Bambu Studio is running"
ORCA_RUNNING = "Orca Slicer is running"
TMP_SUFFIX = ".fktmp"
BAMBU, ORCA = "Bambu Studio", "Orca Slicer"


class Refused(Exception):
    """The install was not done; nothing was written. `.reason` says why, `.code` is a short tag."""

    def __init__(self, reason: str, code: str = "refused"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass
class InstallResult:
    installed: list[str]
    stale: list[str]
    backup: Path
    installed_orca: list[str] = field(default_factory=list)
    stale_orca: list[str] = field(default_factory=list)
    backup_orca: Path | None = None


def read_info(path: Path) -> dict:
    d = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def _key(v) -> str:
    return json.dumps(v, sort_keys=True)


def _names(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.iterdir() if p.suffix.casefold() == ".json" and p.is_file())


def _load_or_none(path: Path) -> dict | None:
    """The preset at path, None when missing; Refused when present but unreadable."""
    if not path.exists():
        return None
    try:
        return inapp.load(path)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Refused(f"could not read {path}: {e}") from None


def trusted_gcode(system_filament: Path, *more: Path) -> set[str]:
    """Every G-code value in this PC's Bambu Studio system filament presets (and in the `more` folders, e.g. the
    installed snapshot's base/)."""
    ok = set()
    for folder in (system_filament, *more):
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if f.suffix.casefold() == ".json" and f.is_file():
                try:
                    d = inapp.load(f)
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                ok.update(_key(v) for k, v in d.items() if "gcode" in k.lower())
    return ok


def _build_meta(build_dir: Path, prefix: str = "") -> tuple[dict[str, dict], set[str]]:
    """(BUILD.json `<prefix>inapp`: {preset: {key: value}}, casefolded `<prefix>restored` names); empty when absent."""
    try:
        m = json.loads((build_dir / "BUILD.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}, set()
    if not isinstance(m, dict):
        return {}, set()
    rec = m.get(f"{prefix}inapp")
    rec = {n: v for n, v in rec.items() if isinstance(n, str) and isinstance(v, dict)} if isinstance(rec, dict) else {}
    restored = m.get(f"{prefix}restored")
    restored = {n.casefold() for n in restored if isinstance(n, str)} if isinstance(restored, list) else set()
    return rec, restored


def untrusted_gcode(new: dict, live: dict | None, trusted: set[str]) -> list[str]:
    """G-code keys of a staged preset whose value is neither a trusted one nor the live copy's."""
    keys = [k for k, v in new.items() if "gcode" in k.lower() and _key(v) not in trusted]
    if keys and live is not None:
        keys = [k for k in keys if _key(live.get(k)) != _key(new[k])]
    return keys


def _backup(user_filament: Path, backups: Path, stamp: str, prune: bool = True) -> Path:
    """Copy user_filament to backups/<stamp>[-n]; `prune` then keeps the KEEP_BACKUPS newest."""
    backups.mkdir(parents=True, exist_ok=True)
    dest, n = backups / stamp, 1
    while dest.exists():
        n += 1
        dest = backups / f"{stamp}-{n}"
    try:
        shutil.copytree(user_filament, dest)
    except OSError as e:
        shutil.rmtree(dest, ignore_errors=True)  # a partial backup must not count as one of the 5
        raise Refused(f"could not back up {user_filament} to {dest} ({e}); nothing was installed") from None
    if prune:
        _prune(backups)
    return dest


def _prune(backups: Path) -> None:
    for old in sorted(p for p in backups.iterdir() if p.is_dir())[:-KEEP_BACKUPS]:
        shutil.rmtree(old)


def _write_live(target: Path, data: bytes) -> None:
    """Write target via a sibling temp file + os.replace, so a live preset is never half-written."""
    tmp = target.with_name(f".{target.name}{TMP_SUFFIX}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _info_bytes(d: dict) -> bytes:
    return "".join(f"{k} = {v}\n" for k, v in d.items()).encode("utf-8")


def _remove_leftover_tmp(live: Path) -> None:
    """Temp files a crashed earlier run left behind (only ours: dot-prefixed, .fktmp)."""
    for p in live.iterdir():
        if p.name.startswith(".") and p.name.endswith(TMP_SUFFIX) and p.is_file():
            p.unlink()


def _replace_installed(build_dir: Path, dirs: AppDirs, skip: tuple[str, ...] = ()) -> None:
    dirs.ensure()
    work = Path(tempfile.mkdtemp(prefix=".installed.", suffix=".tmp", dir=dirs.base))
    try:
        new = work / "installed"
        top = Path(build_dir)
        shutil.copytree(build_dir, new, ignore=lambda d, names: [n for n in names if Path(d) == top and n in skip])
        old = work / "old"
        if dirs.installed.exists():
            dirs.installed.rename(old)
        try:
            new.rename(dirs.installed)
        except OSError:
            if old.exists() and not dirs.installed.exists():
                old.rename(dirs.installed)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


@dataclass
class _Target:
    app: str                    # BAMBU or ORCA
    tree: str                   # "base" or "orca": the build's and the snapshot's folder
    stage: Path
    live: Path                  # where the presets go
    snap: Path
    half: Path
    staged: list[str] = field(default_factory=list)
    new: dict = field(default_factory=dict)
    stale: list[str] = field(default_factory=list)


def _check(t: _Target, trusted: set[str], record: dict, restored: set[str], unsafe: list, stop: list) -> None:
    """Steps 1-3 for one target: load the staged presets, collect untrusted G-code and late app changes."""
    for name in t.staged:
        try:
            t.new[name] = inapp.load(t.stage / f"{name}.json")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise Refused(f"build preset {name} is not valid JSON: {e}") from None
    before = _names(t.snap)
    live_names = _names(t.live)
    reset = inapp.is_reset(set(before), set(live_names))
    label = "" if t.app == BAMBU else f"{ORCA} "
    for name in t.staged:
        now = _load_or_none(t.live / f"{name}.json")
        unsafe += [f"{label}{name}: {k}" for k in untrusted_gcode(t.new[name], now, trusted)]
        old = _load_or_none(t.snap / f"{name}.json")
        if old is None:
            continue
        if now is None:
            if not reset and name.casefold() not in restored:
                stop.append(f"{name}: deleted in {t.app} after the build was made")
            continue
        part = _load_or_none(t.half / f"{name}.json") if t.half.is_dir() else None
        seen = record.get(name, {})
        late = [k for k, v in inapp.diff(old, now).items() if inapp.norm(t.new[name].get(k)) != inapp.norm(v)
                and not (part is not None and k in part and inapp.norm(part[k]) == inapp.norm(v))
                and not (k in seen and inapp.norm(seen[k]) == inapp.norm(v))]
        if late:
            stop.append(f"{name}: edited in {t.app} after the build was made ({', '.join(late)})")
    staged_cf = {n.casefold() for n in t.staged}
    live_cf = {n.casefold() for n in live_names}
    t.stale = [n for n in before if n.casefold() not in staged_cf and n.casefold() in live_cf]


def _copy_in(t: _Target) -> None:
    """Step 6 for one target: copy presets, merging .info so a live cloud setting_id is kept
    (each file is written to a temp file next to it, then renamed over it)."""
    t.live.mkdir(parents=True, exist_ok=True)
    _remove_leftover_tmp(t.live)
    for name in t.staged:
        _write_live(t.live / f"{name}.json", (t.stage / f"{name}.json").read_bytes())
        info, old_info = read_info(t.stage / f"{name}.info"), read_info(t.live / f"{name}.info")
        if old_info.get("setting_id") and not info.get("setting_id"):  # synced to the cloud since the build
            info.update(setting_id=old_info["setting_id"], base_id=old_info.get("base_id", ""), sync_info="update")
        _write_live(t.live / f"{name}.info", _info_bytes(info))


def install(build_dir: Path, folders: StudioFolders, dirs: AppDirs, *,
            running: Callable[[], bool], stamp_now: str,
            before_write: Callable[[Path], None] | None = None,
            orca: OrcaFolders | None = None, orca_running: Callable[[], bool] | None = None) -> InstallResult:
    """before_write(backup_dir) runs after the backups and before the first live write (the sync
    records it so an interrupted install can be told apart from later in-app edits). `orca`: this PC's
    Orca Slicer folders (None: the build's orca/ tree is not installed)."""
    build_dir = Path(build_dir)
    orca_running = orca_running or studio.orca_running
    if running():
        raise Refused(STUDIO_RUNNING, "studio_running")

    bambu = _Target(BAMBU, "base", build_dir / "base", folders.user_filament / "base", dirs.installed / "base",
                    dirs.partial / "base", staged=_names(build_dir / "base"))
    targets = [bambu]
    o = None
    if orca is not None and (build_dir / "orca").is_dir():
        o = _Target(ORCA, "orca", build_dir / "orca", orca.user_filament, dirs.installed / "orca",
                    dirs.partial / "orca", staged=_names(build_dir / "orca"))
        targets.append(o)
        if orca_running():
            raise Refused(ORCA_RUNNING, "studio_running")

    # 1. staged names
    if not any(t.staged for t in targets):
        raise Refused(f"build {build_dir} has no presets")

    # 2. untrusted G-code, 3. edited / deleted after the build
    unsafe, stop = [], []
    _check(bambu, trusted_gcode(folders.system_filament, bambu.snap), *_build_meta(build_dir), unsafe, stop)
    if o is not None:
        _check(o, set(), *_build_meta(build_dir, "orca_"), unsafe, stop)   # Orca: only the live copy's G-code
    if unsafe:
        raise Refused(f"{len(unsafe)} presets carry G-code that is neither from a Bambu Studio system preset nor "
                      "already in your live copy (Orca Slicer presets: only the live copy's) (the build may have "
                      "been tampered with): " + "; ".join(unsafe[:20]), "untrusted_gcode")
    if stop:
        apps = " / ".join(t.app for t in targets)
        raise Refused(f"the build is older than your latest {apps} changes; a rebuild is asked for: "
                      + "; ".join(stop[:20]), "stale_build")

    if not folders.user_filament.is_dir():
        raise Refused(f"the Bambu Studio user filament folder {folders.user_filament} does not exist; open Bambu "
                      "Studio once (and sign in, if you use an account), then run the sync again")
    if o is not None and not orca.user_filament.is_dir():
        raise Refused(f"the Orca Slicer user filament folder {orca.user_filament} does not exist; open Orca "
                      "Slicer once, then run the sync again")

    # 4. right before the first write
    if running():
        raise Refused(STUDIO_RUNNING, "studio_running")
    if o is not None and orca_running():
        raise Refused(ORCA_RUNNING, "studio_running")

    # 5. backups (the Orca one under the same name, so a marker naming one finds both)
    #    old backups are pruned only once both exist, so a failed Orca backup costs no Bambu one
    backup = _backup(folders.user_filament, dirs.backups, stamp_now, prune=False)
    backup_orca = None
    if o is not None:
        shutil.rmtree(dirs.orca_backups / backup.name, ignore_errors=True)  # ours, from an attempt in the same second
        try:
            backup_orca = _backup(orca.user_filament, dirs.orca_backups, backup.name, prune=False)
        except Refused:
            shutil.rmtree(backup, ignore_errors=True)
            raise
        _prune(dirs.orca_backups)
    _prune(dirs.backups)
    if before_write is not None:
        before_write(backup)

    # 6. copy presets
    for t in targets:
        _copy_in(t)

    # 7. nothing deleted; 8. snapshot (without an orca/ tree that was not installed here)
    _replace_installed(build_dir, dirs, skip=() if o is not None else ("orca",))
    return InstallResult(installed=bambu.staged, stale=bambu.stale, backup=backup,
                         installed_orca=o.staged if o else [], stale_orca=o.stale if o else [],
                         backup_orca=backup_orca)


__all__ = ["Refused", "InstallResult", "install", "KEEP_BACKUPS", "STUDIO_RUNNING", "ORCA_RUNNING"]
