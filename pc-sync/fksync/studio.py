"""Finds this PC's Bambu Studio data folders and tells whether Bambu Studio is running.

Folder choice (Decision "Bambu Studio folder choice"): from %APPDATA%\\BambuStudio and
%APPDATA%\\BambuStudioBeta take the root whose BambuStudio.conf is newest (a root without a conf
is ranked by its newest user/*/filament dir); within it, the user/<id> whose filament dir is
newest. A pin from the sync config (`variant`, `user_id`) wins over both choices.

The caller passes `appdata`; only fksync.__main__ reads the real environment.
"""
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
    conf = _mtime(root / CONF)
    if conf is not None:
        return conf
    dirs = _user_filament_dirs(root)
    return max(d[0] for d in dirs) if dirs else None


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


def _tasklist() -> str:
    return subprocess.run(
        ["tasklist", "/fo", "csv", "/nh", "/fi", "IMAGENAME eq bambu-studio.exe"],
        capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


def running(tasklist: Callable[[], str] | None = None) -> bool:
    """True when bambu-studio.exe is running. Always False off Windows unless a tasklist is given."""
    if tasklist is None:
        if sys.platform != "win32":
            return False
        tasklist = _tasklist
    return "bambu-studio.exe" in (tasklist() or "").lower()
