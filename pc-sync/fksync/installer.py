"""Installs a downloaded build into the live Bambu Studio user folder (port of install.py).

Order (each check runs before anything is written):
  1. the staged names come from build_dir/base;
  2. untrusted G-code: every value of a key containing "gcode" must equal a value from this PC's
     system filament presets, or the live preset's current value (the builder never writes G-code
     of its own);
  3. a preset edited or deleted in Bambu Studio after the build was made refuses the install
     (unless more than a quarter of the installed presets vanished at once: an app reset);
  4. Bambu Studio must not be running; this is checked again right before the first write, and
     if it runs then nothing is written, not even the backup;
  5. the user filament folder is backed up to dirs.backups/<stamp> (the 5 newest are kept);
  6. each staged .json is copied in and its .info written, keeping a live cloud setting_id;
  7. nothing is ever deleted: presets no longer built but still live are returned as `stale`
     (they are deleted in the app, never on disk);
  8. dirs.installed is replaced with a copy of the build (temp dir + rename).
"""
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import inapp
from .store import AppDirs
from .studio import StudioFolders

KEEP_BACKUPS = 5
STUDIO_RUNNING = "Bambu Studio is running"


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


def read_info(path: Path) -> dict:
    d = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def write_info(path: Path, d: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"{k} = {v}\n" for k, v in d.items()))


def _key(v) -> str:
    return json.dumps(v, sort_keys=True)


def _names(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.iterdir() if p.suffix == ".json" and p.is_file())


def _load_or_none(path: Path) -> dict | None:
    """The preset at path, None when missing; Refused when present but unreadable."""
    if not path.exists():
        return None
    try:
        return inapp.load(path)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Refused(f"could not read {path}: {e}") from None


def trusted_gcode(system_filament: Path) -> set[str]:
    """Every G-code value in this PC's Bambu Studio system filament presets."""
    ok = set()
    if not system_filament.is_dir():
        return ok
    for f in system_filament.iterdir():
        if f.suffix == ".json" and f.is_file():
            try:
                d = inapp.load(f)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            ok.update(_key(v) for k, v in d.items() if "gcode" in k.lower())
    return ok


def untrusted_gcode(new: dict, live: dict | None, trusted: set[str]) -> list[str]:
    """G-code keys of a staged preset whose value is neither a system preset's nor the live copy's."""
    keys = [k for k, v in new.items() if "gcode" in k.lower() and _key(v) not in trusted]
    if keys and live is not None:
        keys = [k for k in keys if _key(live.get(k)) != _key(new[k])]
    return keys


def _backup(user_filament: Path, backups: Path, stamp: str) -> Path:
    backups.mkdir(parents=True, exist_ok=True)
    dest, n = backups / stamp, 1
    while dest.exists():
        n += 1
        dest = backups / f"{stamp}-{n}"
    shutil.copytree(user_filament, dest)
    for old in sorted(p for p in backups.iterdir() if p.is_dir())[:-KEEP_BACKUPS]:
        shutil.rmtree(old)
    return dest


def _replace_installed(build_dir: Path, dirs: AppDirs) -> None:
    dirs.ensure()
    work = Path(tempfile.mkdtemp(prefix=".installed.", suffix=".tmp", dir=dirs.base))
    try:
        new = work / "installed"
        shutil.copytree(build_dir, new)
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


def install(build_dir: Path, folders: StudioFolders, dirs: AppDirs, *,
            running: Callable[[], bool], stamp_now: str) -> InstallResult:
    build_dir = Path(build_dir)
    if running():
        raise Refused(STUDIO_RUNNING, "studio_running")

    stage = build_dir / "base"
    live = folders.user_filament / "base"
    snap = dirs.installed / "base"

    # 1. staged names
    staged = _names(stage)
    if not staged:
        raise Refused(f"build {build_dir} has no presets")
    new = {}
    for name in staged:
        try:
            new[name] = inapp.load(stage / f"{name}.json")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise Refused(f"build preset {name} is not valid JSON: {e}") from None

    before = _names(snap)
    live_names = _names(live)
    reset = inapp.is_reset(set(before), set(live_names))

    # 2. untrusted G-code, 3. edited / deleted after the build
    trusted = trusted_gcode(folders.system_filament)
    unsafe, stop = [], []
    for name in staged:
        now = _load_or_none(live / f"{name}.json")
        unsafe += [f"{name}: {k}" for k in untrusted_gcode(new[name], now, trusted)]
        old = _load_or_none(snap / f"{name}.json")
        if old is None:
            continue
        if now is None:
            if not reset:
                stop.append(f"{name}: deleted in Bambu Studio after the build was made")
            continue
        late = [k for k, v in inapp.diff(old, now).items() if inapp.norm(new[name].get(k)) != inapp.norm(v)]
        if late:
            stop.append(f"{name}: edited in Bambu Studio after the build was made ({', '.join(late)})")
    if unsafe:
        raise Refused(f"{len(unsafe)} presets carry G-code that is neither from a Bambu Studio system preset nor "
                      "already in your live copy (the build may have been tampered with): " + "; ".join(unsafe[:20]),
                      "untrusted_gcode")
    if stop:
        raise Refused("the build is older than your latest Bambu Studio changes; it will be rebuilt: "
                      + "; ".join(stop[:20]), "stale_build")

    staged_cf = {n.casefold() for n in staged}
    live_cf = {n.casefold() for n in live_names}
    stale = [n for n in before if n.casefold() not in staged_cf and n.casefold() in live_cf]

    # 4. right before the first write
    if running():
        raise Refused(STUDIO_RUNNING, "studio_running")

    # 5. backup
    backup = _backup(folders.user_filament, dirs.backups, stamp_now)

    # 6. copy presets, merging .info so a live cloud setting_id is kept
    live.mkdir(parents=True, exist_ok=True)
    for name in staged:
        shutil.copy2(stage / f"{name}.json", live / f"{name}.json")
        info, old_info = read_info(stage / f"{name}.info"), read_info(live / f"{name}.info")
        if old_info.get("setting_id") and not info.get("setting_id"):  # synced to the cloud since the build
            info.update(setting_id=old_info["setting_id"], base_id=old_info.get("base_id", ""), sync_info="update")
        write_info(live / f"{name}.info", info)

    # 7. nothing deleted; 8. snapshot
    _replace_installed(build_dir, dirs)
    return InstallResult(installed=staged, stale=stale, backup=backup)


__all__ = ["Refused", "InstallResult", "install", "KEEP_BACKUPS", "STUDIO_RUNNING"]
