"""Finds this PC's Bambu Studio data folders and tells whether Bambu Studio is running.

Folder choice (Decision "Bambu Studio folder choice"): from %APPDATA%\\BambuStudio and
%APPDATA%\\BambuStudioBeta take the root whose BambuStudio.conf is newest (a root without a conf
is ranked by its newest user/*/filament dir; a root with no user filament dir is skipped); within it, the user/<id> whose filament dir is
newest. A pin from the sync config (`variant`, `user_id`) wins over both choices.

Orca Slicer (locate_orca; None when %APPDATA%\\OrcaSlicer has no user/<id>/filament dir, and the sync is then
Bambu Studio only): the user folder is the config pin `orca_user_id`, else OrcaSlicer.conf's
`app.preset_folder` when that folder exists, else the newest user/<id>/filament dir. Orca's user filament
folder is flat (no base/). The install dir (only needed for OrcaFilamentLibrary.opc) is the config pin
`orca_install`, else the uninstall registry entry (HKLM/HKCU, DisplayName "OrcaSlicer...": InstallLocation,
else the folder of DisplayIcon / UninstallString), else the newest `<Program Files>\\OrcaSlicer*` holding
orca-slicer.exe; it may be missing. The packed library is `<install>\\resources\\profiles\\OrcaFilamentLibrary.opc`,
else `%APPDATA%\\OrcaSlicer\\system\\OrcaFilamentLibrary.opc` (Ruling L).

The caller passes `appdata` (and the Program Files folders); only fksync.__main__ reads the real environment.
"""
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

VARIANTS = ("BambuStudio", "BambuStudioBeta")
CONF = "BambuStudio.conf"
_USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # same rule as PUT /api/sync/live?user_id=


class NotFound(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class StudioFolders:
    root: Path
    variant: str
    user_id: str
    user_filament: Path
    system_filament: Path


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _user_filament_dirs(root: Path) -> list[tuple[float, str, Path]]:
    """(mtime, user_id, filament dir) for every user/<id>/filament dir with a valid id."""
    out = []
    try:
        users = list((root / "user").iterdir())
    except OSError:
        return out
    for user in users:
        fil = user / "filament"
        if _USER_ID.match(user.name) and fil.is_dir():
            m = _mtime(fil)
            if m is not None:
                out.append((m, user.name, fil))
    return out


def _root_rank(root: Path) -> float | None:
    """The root's rank, or None when it has no user/*/filament dir (a root it could never use)."""
    dirs = _user_filament_dirs(root)
    if not dirs:
        return None
    conf = _mtime(root / CONF)
    return conf if conf is not None else max(d[0] for d in dirs)


def locate(appdata: Path, pin: dict | None = None) -> StudioFolders:
    appdata = Path(appdata)
    pin = pin or {}
    variant, user_id = pin.get("variant"), pin.get("user_id")

    if variant:
        if variant not in VARIANTS:
            raise NotFound(f"Bambu Studio variant {variant!r} in the sync config is not one of {', '.join(VARIANTS)}.")
        root = appdata / variant
        if not root.is_dir():
            raise NotFound(f"Bambu Studio folder {root} (pinned variant {variant}) does not exist.")
    else:
        ranked = [(r, v) for v in VARIANTS if (appdata / v).is_dir() and (r := _root_rank(appdata / v)) is not None]
        if not ranked:
            raise NotFound(f"Bambu Studio not found: neither {appdata / VARIANTS[0]} nor {appdata / VARIANTS[1]} "
                           "has a user filament folder. Open Bambu Studio once (and sign in, if you use an "
                           "account), then run the sync again.")
        variant = max(ranked)[1]
        root = appdata / variant

    if user_id:
        if not _USER_ID.match(str(user_id)):
            raise NotFound(f"Bambu Studio user id {user_id!r} in the sync config is not valid.")
        user_filament = root / "user" / user_id / "filament"
        if not user_filament.is_dir():
            raise NotFound(f"Bambu Studio user folder {user_filament} (pinned user_id {user_id}) does not exist.")
    else:
        dirs = _user_filament_dirs(root)
        if not dirs:
            raise NotFound(f"Bambu Studio folder {root} has no user filament folder. Open Bambu Studio once "
                           "(and sign in, if you use an account), then run the sync again.")
        _, user_id, user_filament = max(dirs)

    return StudioFolders(root=root, variant=variant, user_id=user_id, user_filament=user_filament,
                         system_filament=root / "system" / "BBL" / "filament")


def _tasklist(image: str = "bambu-studio.exe") -> str:
    return subprocess.run(
        ["tasklist", "/fo", "csv", "/nh", "/fi", f"IMAGENAME eq {image}"],
        capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


def _running(image: str, tasklist: Callable[[], str] | None) -> bool:
    if tasklist is None:
        if sys.platform != "win32":
            return False
        return image in (_tasklist(image) or "").lower()
    return image in (tasklist() or "").lower()


def running(tasklist: Callable[[], str] | None = None) -> bool:
    """True when bambu-studio.exe is running. Always False off Windows unless a tasklist is given."""
    return _running("bambu-studio.exe", tasklist)


def orca_running(tasklist: Callable[[], str] | None = None) -> bool:
    """True when orca-slicer.exe is running. Always False off Windows unless a tasklist is given."""
    return _running("orca-slicer.exe", tasklist)


# --- Orca Slicer -------------------------------------------------------------------------------

ORCA = "OrcaSlicer"
ORCA_CONF = "OrcaSlicer.conf"
ORCA_EXE = "orca-slicer.exe"
LIBRARY_OPC = "OrcaFilamentLibrary.opc"
_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_UNINSTALL_WOW = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass(frozen=True)
class OrcaFolders:
    root: Path                  # %APPDATA%\OrcaSlicer
    user_id: str
    user_filament: Path         # flat: <name>.json + <name>.info
    system_bbl: Path            # Orca's unpacked BBL system presets (system\BBL\filament)
    install: Path | None
    library_opc: Path | None


def _conf_preset_folder(root: Path) -> str | None:
    """app.preset_folder from OrcaSlicer.conf (JSON, then Orca's '# MD5 checksum' line); None if unreadable.
    Nothing else of the conf is read (it also holds printer access codes)."""
    try:
        text = (root / ORCA_CONF).read_text(encoding="utf-8")
        conf = json.loads(text[:text.rindex("}") + 1])
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    app = conf.get("app") if isinstance(conf, dict) else None
    folder = app.get("preset_folder") if isinstance(app, dict) else None
    return folder if isinstance(folder, str) and _USER_ID.match(folder) else None


def _registry_entries() -> list[dict]:
    """Uninstall entries (HKLM, HKLM WOW6432Node, HKCU) whose DisplayName starts with OrcaSlicer."""
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, _UNINSTALL), (winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_WOW),
                       (winreg.HKEY_CURRENT_USER, _UNINSTALL)):
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                entry = {}
                try:
                    with winreg.OpenKey(root, sub) as k:
                        for name in ("DisplayName", "InstallLocation", "DisplayIcon", "UninstallString"):
                            try:
                                entry[name] = str(winreg.QueryValueEx(k, name)[0])
                            except OSError:
                                pass
                except OSError:
                    continue
                if entry.get("DisplayName", "").startswith(ORCA):
                    out.append(entry)
    return out


def _exe_dir(value: str) -> Path | None:
    """The folder of a registry path value: '"G:\\x\\Uninstall.exe"' or 'G:\\x\\orca-slicer.exe,0'."""
    v = (value or "").strip()
    v = v[1:].partition('"')[0] if v.startswith('"') else v.partition(",")[0]
    return Path(v).parent if v else None


def _is_install(path: Path | None) -> bool:
    return path is not None and (path / ORCA_EXE).is_file()


def _orca_install(pin: str | None, program_files: Iterable[Path], registry: Callable[[], list[dict]]) -> Path | None:
    if pin:
        p = Path(pin)
        if not _is_install(p):
            raise NotFound(f"Orca Slicer install folder {p} (orca_install in the sync config) has no {ORCA_EXE}.")
        return p
    try:
        entries = registry() or []
    except OSError:
        entries = []
    for e in entries:
        if not str(e.get("DisplayName", "")).startswith(ORCA):
            continue
        for cand in (Path(e["InstallLocation"]) if e.get("InstallLocation") else None,
                     _exe_dir(e.get("DisplayIcon", "")), _exe_dir(e.get("UninstallString", ""))):
            if _is_install(cand):
                return cand
    found = []
    for pf in program_files:
        try:
            dirs = [d for d in Path(pf).glob(f"{ORCA}*") if _is_install(d)]
        except OSError:
            continue
        found += [(m, str(d), d) for d in dirs if (m := _mtime(d / ORCA_EXE)) is not None]
    return max(found)[2] if found else None


def locate_orca(appdata: Path, pin: dict | None = None, *, program_files: Iterable[Path] = (),
                registry: Callable[[], list[dict]] = _registry_entries) -> OrcaFolders | None:
    """This PC's Orca Slicer folders, or None when Orca Slicer has no user filament folder here."""
    root = Path(appdata) / ORCA
    pin = pin or {}
    user_id = pin.get("orca_user_id")
    if user_id:
        if not _USER_ID.match(str(user_id)):
            raise NotFound(f"Orca Slicer user id {user_id!r} in the sync config is not valid.")
        user_filament = root / "user" / user_id / "filament"
        if not user_filament.is_dir():
            raise NotFound(f"Orca Slicer user folder {user_filament} (pinned orca_user_id {user_id}) does not exist.")
    else:
        dirs = _user_filament_dirs(root)
        if not dirs:
            return None
        folder = _conf_preset_folder(root)
        chosen = [d for d in dirs if d[1] == folder]
        _, user_id, user_filament = chosen[0] if chosen else max(dirs)
    install = _orca_install(pin.get("orca_install"), program_files, registry)
    opc = None
    for cand in ((install / "resources" / "profiles" / LIBRARY_OPC) if install else None,
                 root / "system" / LIBRARY_OPC):
        if cand is not None and cand.is_file():
            opc = cand
            break
    return OrcaFolders(root=root, user_id=user_id, user_filament=user_filament,
                       system_bbl=root / "system" / "BBL" / "filament", install=install, library_opc=opc)
