"""Map by loading filament, for Klipper printers (brief 2026-11-09 13:01; API version 2 in the handoff
2026-11-09-1330-all-in-one-manual-slot-mapping-api-v2.md, the same routes and state as bridge/manual.py for Bambu).

A Klipper printer's slots come from the printer and the kit's data file: a toolchanger's tool n is "extruder<n>" under
the label klipper_hardware.xml gives it, AFC lanes and Happy Hare gates under the printer's own names. Those names can
differ from what the owner calls a position (the Sovol M1D's labels are placeholders until the printer is captured),
so the owner makes one position at a time active and confirms what the printer reports as active: the toolhead's
extruder, AFC's `tool_loaded`, Happy Hare's gate. A printer with no such report (one extruder; lane_data only) gets
the by-hand form.

The owner's answers are a relabelling: owner label -> the printer's label for that position. It is kept a permutation
(a confirm swaps the two labels involved), so every slot keeps one label, and saved in the printer's state folder as
slot-map.xml. `relabel` and `printer_label` apply it wherever the kit reads slots or sends a slot's gcode. A map that no
longer fits the printer's slots (a lane gone) is ignored as a whole and logged, never half applied.

Nothing is sent to the printer: the owner loads or picks the tool.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import xmlfile
from ..manual import NO_REPORT_AFTER, SETTLE, ManualError

log = logging.getLogger(__name__)
MAP_FILE = "slot-map.xml"
REPORTS = ("toolchanger", "afc", "happyhare")       # adapters whose read() says which slot is active
BUSY = ("printing", "paused")


# --------------------------------------------------------------------------------------------------- the saved map
def _path(pid: str) -> Path:
    from .manager import printer_dir
    return printer_dir(pid) / MAP_FILE


def load_map(pid: str) -> dict[str, dict]:
    """owner label -> {"printer": label, "by": "user" | "user-unverified" | None, "at": str | None}. {} when none."""
    try:
        from defusedxml.ElementTree import fromstring
        root = fromstring(_path(pid).read_bytes(), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001 - a broken file: no map, said in the log
        log.warning("klipper %s: %s is unreadable; slots keep the printer's names", pid, MAP_FILE)
        return {}
    out = {}
    for el in root.findall("slot") if root.tag == "slot-map" else ():
        label, printer = el.get("label", ""), el.get("printer", "")
        if label and printer:
            by = el.get("by")
            out[label] = {"printer": printer, "by": by if by in ("user", "user-unverified") else None,
                          "at": el.get("at")}
    return out


def save_map(pid: str, entries: dict[str, dict]) -> None:
    root = ET.Element("slot-map", version="1")
    for label, e in entries.items():
        attrs = {"label": xmlfile.clean(label), "printer": xmlfile.clean(e["printer"])}
        if e.get("by"):
            attrs["by"] = e["by"]
            attrs["at"] = xmlfile.clean(e.get("at") or "")
        ET.SubElement(root, "slot", attrs)
    path = _path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    tmp.replace(path)


def mapping(entries: dict[str, dict], labels) -> dict[str, str]:
    """owner label -> printer label over `labels` (the printer's own), identity where the map says nothing. Identity
    everywhere when the map doesn't fit: a label it names is gone, or its moves don't close into a permutation."""
    labels = list(labels)
    moved = {k: v["printer"] for k, v in entries.items() if v["printer"] != k}
    if moved and (set(moved) != set(moved.values()) or not set(moved) <= set(labels)):
        return {x: x for x in labels}
    return {x: moved.get(x, x) for x in labels}


def relabel(units, entries: dict[str, dict]):
    """The adapter's units with each slot under the owner's label."""
    if not entries:
        return units
    labels = [s.label for u in units for s in u.slots]
    to_owner = {p: o for o, p in mapping(entries, labels).items()}
    if all(o == p for p, o in to_owner.items()):
        return units
    return [replace(u, slots=[replace(s, label=to_owner.get(s.label, s.label)) for s in u.slots]) for u in units]


def printer_label(entries: dict[str, dict], label: str, labels) -> str:
    """The printer's label for the slot the owner calls `label`."""
    return mapping(entries, labels).get(label, label) if entries else label


# --------------------------------------------------------------------------------------------------- the session
@dataclass
class _Session:
    id: str
    pid: str
    positions: list[str]                  # owner labels, in the order the owner loads them
    kind: str                             # the adapter's name
    started: float = field(default_factory=lambda: time.time())
    open: bool = True
    answers: dict = field(default_factory=dict)      # owner label -> {status, reported_label, nozzle, at}
    step_since: float = field(default_factory=lambda: time.time())
    baseline: str | None = None           # the printer's active slot when the step began
    moved: bool = False                   # the active slot changed during this step
    seen: tuple | None = None             # (printer label, first seen at)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class KlipperManualMaps:
    """The Bambu session's interface (bridge/manual.ManualMaps) over a KlipperFamily."""

    def __init__(self, fam):
        self._f = fam
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}

    # what the family tells it -------------------------------------------------------------------------------------
    def _look(self, pid: str) -> tuple[list[str], str | None, str, str | None]:
        """(the printer's slot labels, the active one or None, the adapter's name, print_stats state); ManualError
        when offline."""
        c = self._f._conn(pid)
        if c is None or c.state not in ("connected", "unknown_model") or not (c.sub and c.sub.connected):
            raise ManualError(409, "printer_offline", "The printer is offline: turn it on, then start again.")
        units, kind, job = self._f.raw_slots(pid)
        labels = [s.label for u in units for s in u.slots]
        active = [s.label for u in units for s in u.slots if s.active]
        return labels, (active[0] if len(active) == 1 and kind in REPORTS else None), kind, job

    def start(self, pid: str) -> dict:
        labels, active, kind, job = self._look(pid)
        if job in BUSY:
            raise ManualError(409, "printer_busy", "The printer is busy: start again when it is idle.")
        with self._lock:
            s = self._sessions.get(pid)
            if s is not None and s.open:
                return self._state(s, labels, active)       # a second device joins the session that is open
            owner = {p: o for o, p in mapping(load_map(pid), labels).items()}
            s = _Session(secrets.token_hex(4), pid, [owner[x] for x in labels], kind)
            s.baseline = active
            self._sessions[pid] = s
            return self._state(s, labels, active)

    def view(self, pid: str) -> dict:
        with self._lock:
            s = self._sessions.get(pid)
            if s is None:
                raise ManualError(404, "none", "No manual mapping was started for this printer.")
            if not s.open:
                return self._state(s, None, None)
        labels, active, _kind, _job = self._look(pid)
        with self._lock:
            return self._state(s, labels, active)

    def _session(self, pid: str, sid) -> _Session:
        s = self._sessions.get(pid)
        if s is None or not s.open:
            raise ManualError(404, "none", "No manual mapping is open for this printer.")
        if sid != s.id:
            raise ManualError(409, "stale", "This manual mapping moved on or was restarted: show it again.")
        return s

    def confirm(self, pid: str, sid, position, reported, nozzle=None, by_hand: bool = False) -> dict:
        labels, active, _kind, _job = self._look(pid)
        with self._lock:
            s = self._session(pid, sid)
            if position not in s.positions:
                raise ManualError(400, "bad_request", "No such position on this printer.")
            if nozzle is not None:
                raise ManualError(400, "bad_request", "nozzle is only for a dual-nozzle printer")
            target = reported.get("label") if isinstance(reported, dict) else None
            if target not in labels:
                raise ManualError(400, "bad_request", "That slot is not one this printer has.")
            if not by_hand and (s.seen is None or s.seen[0] != target or active != target):
                raise ManualError(409, "stale", "The printer no longer reports that slot active: show it again.")
            self._write(pid, labels, position, target, "user-unverified" if by_hand else "user")
            s.answers[position] = {"status": "by_hand" if by_hand else "confirmed", "reported_label": target,
                                   "nozzle": None, "at": _now_iso()}
            self._next_step(s, active)
            return self._state(s, labels, active)

    def skip(self, pid: str, sid, position) -> dict:
        labels, active, _kind, _job = self._look(pid)
        with self._lock:
            s = self._session(pid, sid)
            if position not in s.positions:
                raise ManualError(400, "bad_request", "No such position on this printer.")
            s.answers[position] = {"status": "skipped", "reported_label": None, "nozzle": None, "at": _now_iso()}
            self._next_step(s, active)
            return self._state(s, labels, active)

    def stop(self, pid: str, sid) -> dict:
        with self._lock:
            s = self._session(pid, sid)
            s.open = False
            return self._state(s, None, None)

    def answer_offer(self, pid: str, share: bool) -> dict:
        """Klipper maps are the owner's own wiring and names: there is no printer report to share them in yet."""
        return {"share": False}

    # inside ----------------------------------------------------------------------------------------------------------
    def _next_step(self, s: _Session, active) -> None:
        s.step_since, s.seen, s.baseline, s.moved = time.time(), None, active, False
        if self._step(s) is None:
            s.open = False

    def _step(self, s: _Session) -> str | None:
        return next((p for p in s.positions if p not in s.answers), None) if s.open else None

    def _write(self, pid: str, labels, owner: str, target: str, by: str) -> None:
        """owner -> target, swapping with the label that had target, so the map stays a permutation."""
        entries = load_map(pid)
        cur = mapping(entries, labels)
        other = next(o for o, p in cur.items() if p == target)
        cur[other], cur[owner] = cur[owner], target
        meta = {o: e for o, e in entries.items() if e.get("by") and o not in (owner, other)}
        out = {}
        for o in labels:
            if cur[o] != o or o in meta or o == owner:
                out[o] = {"printer": cur[o], **({"by": meta[o]["by"], "at": meta[o]["at"]} if o in meta else {})}
        out[owner].update(by=by, at=_now_iso())
        save_map(pid, out)
        self._f.forget_slot_map(pid)

    def _state(self, s: _Session, labels, active) -> dict:
        step = self._step(s)
        seen = ask = None
        now = time.time()
        reports = s.kind in REPORTS
        if s.open and step is not None and labels is not None:
            if active != s.baseline:
                s.moved = True
            if s.moved and active is not None:
                if s.seen is None or s.seen[0] != active:
                    s.seen = (active, now)
            else:
                s.seen = None
            if s.seen is not None:
                settled = now - s.seen[1] >= SETTLE
                seen = {"reported": {"label": s.seen[0]}, "reported_label": s.seen[0], "nozzle": None,
                        "nozzle_reported": False, "settled": settled}
                if settled:
                    ask = f"The printer now reports {s.seen[0]} active. Is that the {step} you loaded?"
            reports = reports and not (s.seen is None and now - s.step_since >= NO_REPORT_AFTER)
        out = {"session": s.id, "open": s.open, "dual_nozzle": False, "reports_loads": reports,
               "step": None if step is None else {
                   "position": {"id": step, "label": step}, "say": self._say(s, step, reports), "seen": seen,
                   "ask": ask},
               "positions": [{"id": p, "label": p,
                              **({"status": "pending", "reported_label": None, "nozzle": None, "at": None}
                                 | s.answers.get(p, {}))} for p in s.positions],
               "summary": self._summary(s), "offer_report": False}
        if not reports and labels is not None:
            out["choices"] = [{"reported": {"label": x}, "label": x} for x in labels]
        return out

    def _say(self, s: _Session, step: str, reports: bool) -> str:
        if not reports:
            return (f"This printer does not say which slot is active. Load {step}, then pick the printer's name for "
                    "that slot from the list.")
        what = (f"Make {step} the active tool on the printer" if s.kind == "toolchanger"
                else f"Load {step} to the toolhead")
        text = f"{what}, then wait."
        if s.baseline is not None and not s.moved:
            text += (f" The printer has {s.baseline} active now: to confirm that one, make another slot active first, "
                     "then this one.")
        return text

    def _summary(self, s: _Session) -> str:
        n = len(s.positions)
        conf = sum(a["status"] == "confirmed" for a in s.answers.values())
        hand = sum(a["status"] == "by_hand" for a in s.answers.values())
        skipped = [p for p, a in s.answers.items() if a["status"] == "skipped"]
        parts = [f"{conf} of {n} positions confirmed"]
        if hand:
            parts.append(f"{hand} entered by hand (not checked by the printer)")
        if skipped:
            parts.append(f"skipped: {', '.join(skipped)}")
        text = "; ".join(parts) + "."
        if not s.open:
            left = [p for p in s.positions if p not in s.answers]
            if left:
                text += f" Not mapped: {', '.join(left)}."
            if conf or hand:
                text += " Loading spools into these slots uses your names now."
        return text
