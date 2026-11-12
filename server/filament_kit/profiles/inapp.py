"""What the owner changed in Bambu Studio (path-free port of filament-ops inapp.py).

The server keeps the build the PC sync last installed; a key whose live value differs from that copy was edited
in the app (calibration, temps, ...) and is carried into the next build. A generated preset that was installed but
is gone from the app was deleted there and stays deleted until restored. Note lines the owner typed are kept below
MARK.

Edits last (ruling S27): each build records, per preset, the in-app values it carried (BUILD.json `inapp`). The
next build starts from the installed build's record, overridden/extended by diff(installed preset, live): a key the
owner changed again takes the new live value; a key the owner changed to the newly generated value (set it back) is
dropped from the record. A key only in the record is never dropped because the generated value happens to match
it: a later build that generates another value still keeps the owner's. A half-finished install (ruling S28) is not the owner's doing: a live value equal
to that partial build's value is not an edit; that build's own record is used instead of the installed one's.

IGNORE, norm, diff and is_reset must stay identical to pc-sync/fksync/inapp.py (a server test compares them).
"""
from __future__ import annotations

MARK = "Your notes (kept when the profiles are regenerated):"
IDS_PREFIX = "Spoolman filament ids:"
# bookkeeping the apps or the generator own; never treated as an edit
IGNORE = {"name", "inherits", "from", "version", "filament_settings_id", "filament_id", "updated_time", "setting_id",
          "user_id", "base_id", "is_custom_defined", "instantiation", "filament_notes", "compatible_printers"}


def norm(v):
    return [str(x) for x in v] if isinstance(v, list) else str(v)


def notes_text(v) -> str:
    return "\n".join(str(x) for x in v) if isinstance(v, list) else (v or "")


def diff(installed: dict, live: dict) -> dict:
    """{key: live value} for every key the app changed or added."""
    return {k: v for k, v in live.items() if k not in IGNORE and (k not in installed or norm(v) != norm(installed[k]))}


def user_notes(installed: dict, live: dict, *, partial: dict | None = None) -> list[str]:
    """Note lines the owner wrote: everything below MARK, plus lines that were not in the installed notes (nor in
    `partial`'s, the copy a half-finished install wrote: its summary/spec lines are generated, not theirs);
    never the generated `Spoolman filament ids:` line."""
    lines = notes_text(live.get("filament_notes")).splitlines()
    kept = []
    if MARK in lines:
        kept, lines = lines[lines.index(MARK) + 1:], lines[:lines.index(MARK)]
    old = notes_text(installed.get("filament_notes")).splitlines()
    old = set(old[:old.index(MARK)] if MARK in old else old)    # the owner's lines below MARK are never "generated"
    if partial is not None:
        old |= set(notes_text(partial.get("filament_notes")).splitlines())
    out = kept + [line for line in lines if line.strip() and line not in old and line not in kept]
    return [line for line in out if not line.startswith(IDS_PREFIX)]


def carried(cfg: dict, installed: dict | None, live: dict | None, *, recorded: dict | None = None,
            partial: dict | None = None) -> tuple[dict, list[str]]:
    """(the owner's in-app values for this preset, recorded keys the owner set back to the generated value).
    `cfg` holds the generated values; `recorded` = the edits the installed (or partial) build carried;
    `partial` = the partial build's copy of this preset (its values are not edits). Only a key changed in the app
    since the install (`fresh`) is dropped when its live value equals the generated one."""
    fresh = {}
    if installed is not None and live is not None:
        for k, v in diff(installed, live).items():
            if partial is not None and k in partial and norm(partial[k]) == norm(v):
                continue                    # written by the half-finished install, not typed by the owner
            fresh[k] = v
    out = {k: v for k, v in (recorded or {}).items() if k not in IGNORE}
    out.update(fresh)
    same = [k for k, v in fresh.items() if k in cfg and norm(cfg[k]) == norm(v)]
    dropped = sorted(k for k in same if k in (recorded or {}))
    for k in same:
        del out[k]
    return out, dropped


def keep_edits(cfg: dict, installed: dict | None, live: dict | None, log: list[str], *,
               recorded: dict | None = None, partial: dict | None = None, notes: list[str] | None = None) -> dict:
    """Carry the owner's in-app values (see `carried`) into cfg (in place); returns them ({key: value}, the
    record of this build). Their note lines go below MARK, before a trailing `Spoolman filament ids:` line if cfg
    has one. With no live copy (an app reset) the lines below MARK of the installed copy are carried; lines a
    half-finished install wrote (`partial`) are never taken for theirs. With no installed copy at all (a re-paired
    PC, ruling S34) the owner's saved note lines `notes` are carried."""
    edits, dropped = carried(cfg, installed, live, recorded=recorded, partial=partial)
    for k in dropped:
        log.append(f"{cfg.get('name')}: {k} is the generated value again; no longer kept as your in-app value")
    for k, v in edits.items():
        if norm(cfg.get(k)) != norm(v):
            log.append(f"{cfg.get('name')}: {k} {cfg.get(k)} -> {v} (your in-app value, kept)")
        cfg[k] = v
    if installed is None:
        mine = [line for line in (notes or []) if isinstance(line, str) and not line.startswith(IDS_PREFIX)]
    else:
        # the live preset is gone (an app reset, a restore): the owner's lines below MARK in the installed copy count
        mine = user_notes(installed, live if live is not None else installed,
                          partial=partial if live is not None else None)
    if mine:
        lines = notes_text(cfg.get("filament_notes")).splitlines()
        tail = [lines.pop()] if lines and lines[-1].startswith(IDS_PREFIX) else []
        cfg["filament_notes"] = "\n".join(lines + [MARK] + mine + tail)
        log.append(f"{cfg.get('name')}: filament_notes, {len(mine)} line(s) you wrote (kept)")
    return edits


def is_reset(snapshot: set[str], live: set[str]) -> bool:
    """More than a quarter of the installed presets vanished at once: an app reset, not deletions."""
    snap = {n.casefold() for n in snapshot}
    have = {n.casefold() for n in live}
    return bool(snap) and len(snap - have) > len(snap) / 4


def deleted(name: str, *, snapshot: set[str], live: set[str], before: set[str], reset: bool, restore: bool) -> bool:
    """True if this generated preset was deleted in the app (port of gen.gone): it was deleted before, or it was
    installed and is gone from the app now. Never during an app reset or a restore. Names match casefolded."""
    return Deleted(snapshot=snapshot, live=live, before=before, reset=reset)(name, restore=restore)


class Deleted:
    """`deleted` with the three name sets casefolded once (FA-055); call it per preset: `gone(name, restore=...)`."""

    def __init__(self, *, snapshot: set[str], live: set[str], before: set[str], reset: bool):
        self.reset = reset
        self._snapshot = {n.casefold() for n in snapshot}
        self._live = {n.casefold() for n in live}
        self._before = {n.casefold() for n in before}

    def __call__(self, name: str, *, restore: bool) -> bool:
        if restore or self.reset:
            return False
        key = name.casefold()
        return key in self._before or (key in self._snapshot and key not in self._live)
