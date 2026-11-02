"""The in-app edit rules the PC sync needs, copied from the server's profiles.inapp (port of inapp.py).

Keep IGNORE, norm, diff and is_reset identical to the server's copy: the installer's
"edited / deleted in the app after the build" check must agree with what the builder carried over.
"""
import json
from pathlib import Path

# bookkeeping the apps or the generator own; never treated as an edit
IGNORE = {"name", "inherits", "from", "version", "filament_settings_id", "filament_id", "updated_time", "setting_id",
          "user_id", "base_id", "is_custom_defined", "instantiation", "filament_notes", "compatible_printers"}


def load(path: Path) -> dict:
    """A preset JSON object; ValueError when the file is not a JSON object."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def norm(v):
    return [str(x) for x in v] if isinstance(v, list) else str(v)


def diff(installed: dict, live: dict) -> dict:
    """{key: live value} for every key the app changed or added."""
    return {k: v for k, v in live.items() if k not in IGNORE and (k not in installed or norm(v) != norm(installed[k]))}


def is_reset(snapshot: set[str], live: set[str]) -> bool:
    """More than a quarter of the installed presets vanished at once: an app reset, not deletions."""
    snap = {n.casefold() for n in snapshot}
    have = {n.casefold() for n in live}
    return bool(snap) and len(snap - have) > len(snap) / 4
