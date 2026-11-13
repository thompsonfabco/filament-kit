"""The one-line live summary of each navigation section (03 3.2), for `G state`'s `summaries`.

A section with nothing to say (its feature is off, nothing there yet) has no entry's text: the value is None and the page
shows no summary. The lines hold counts, versions and names of setups only, never an address, serial, code or token.
The Overview's line comes from the rows the last Overview read made (no check runs for `G state`).
"""
from __future__ import annotations

import datetime
import time

from .. import config, intake_history, modules, reader_flash, setup_helper, updates

SECTIONS = ("overview", "printers", "recent", "devices", "presets", "features", "settings", "flash", "updates", "logs")
SETUPS = {"server": "Hub", "all-in-one": "Hub with Weigh Station", "station": "Weigh Station only", "custom": "Custom"}
SETTINGS_GROUPS = 9                     # 03 10: Appearance, General, Storage locations, Label Reader, Backups and restore, ...
FLASH_NAMES = {"printer-station": "Tag Reader", "intake-panel": "Weigh Station display"}


def ago(then: float, now: float | None = None) -> str:
    s = max(0, int((time.time() if now is None else now) - then))
    if s < 60:
        return "just now"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size:
            n = s // size
            return f"{n} {unit}{'' if n == 1 else 's'} ago"
    return "just now"


def _epoch(t) -> float | None:
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return float(t)
    try:
        return datetime.datetime.fromisoformat(str(t)).timestamp()
    except ValueError:
        return None


def _overview(rows: list[dict] | None) -> str | None:
    if rows is None:
        return None
    n = sum(1 for r in rows if r["state"] == "fail")
    return f"{n} need a look" if n else "All checks OK"


def _printers(state: dict) -> str | None:
    listed = state["printers"]["list"]
    if not listed:
        return None
    on = sum(1 for p in listed if p["state"] == "connected")
    off = sum(1 for p in listed if p["configured"] and p["state"] != "connected")
    return f"{on} connected · {off} offline"


def _recent() -> str | None:
    got = intake_history.newest_spool()
    if got is None:
        return None
    sid, at = got
    when = _epoch(at)
    return f"Newest: spool {sid}, {ago(when)}" if when else f"Newest: spool {sid}"


def _presets(cfg: dict) -> str | None:
    if "presets" not in modules.enabled(cfg):
        return None
    from ..profiles import builds
    cur = builds.current()
    when = _epoch(cur.get("created")) if cur else None
    return f"Last build {ago(when)}" if when else "No build yet"


def _flash() -> str | None:
    names = [FLASH_NAMES.get(d, t) for d, t in reader_flash.DEVICES.items() if reader_flash.device_image(d)]
    return " · ".join(names) or None


def _updates() -> str:
    st = updates.summary()
    return f"{st['latest']} is available" if st["newer"] else f"{st['installed']} · up to date"


def build(state: dict, overview_rows: list[dict] | None) -> dict[str, str | None]:
    """`state` is the reply of `G state` so far; `overview_rows` the last Overview read's rows (None: none yet)."""
    cfg = config.load()
    units = setup_helper.journal_units(cfg)
    out = {
        "overview": _overview(overview_rows),
        "printers": _printers(state),
        "recent": _recent(),
        "devices": f"{len(state['devices'])} paired · {len(state['readers']['list'])} Tag Readers",
        "presets": _presets(cfg),
        "features": f"Setup: {SETUPS[state['mode']] if state['mode'] in SETUPS else SETUPS['custom']}",
        "settings": f"{SETTINGS_GROUPS} groups",
        "flash": _flash(),
        "updates": _updates(),
        "logs": f"{len(units)} services",
    }
    assert tuple(out) == SECTIONS
    return out
