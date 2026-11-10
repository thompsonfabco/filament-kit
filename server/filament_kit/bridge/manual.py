"""Map by loading filament: the owner's fallback when slot mapping fails (brief 2026-11-09 13:01; API in the handoff
2026-11-09-1305-all-in-one-manual-slot-mapping-api.md, version 2: a position's id is its slot label).

One session per printer, shared by the setup page and the app. The kit names one position at a time ("Load A2 to the
nozzle, then wait."); the owner loads it on the printer; the kit watches what the printer reports as loaded
(`ams.tray_now`, and each nozzle's `snow` on a printer that has them). Once a new load has held for SETTLE seconds
the session asks whether that is the position the owner loaded. Yes writes the pair into the slot map at once as
confirmed by the owner; "No, I loaded ..." writes it for the position they name; Skip leaves the position unmapped.
A printer that reports no load at all gets the by-hand form: the owner picks the slot, recorded as unverified.

While a session is open the automatic mapping is refused for that printer (mapping.ManualRunning), and afterwards
it never replaces an owner's entry (mapping._keep_owner_entries). Nothing is sent to the printer: the owner loads.

What this proves is which slot is which (what loading a spool needs). It does not prove the printer's slot numbering
for print jobs: a map whose numbering no calibration has proven stays logging-only for filament use, and says so.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from .. import config
from . import ams, layout, loading, mapping, status

SETTLE = 3.0            # seconds a new load must hold before the session asks about it
NO_REPORT_AFTER = 60.0  # seconds without any load field in the report: the printer reports no loads
# H2D: extruder 0 is the right (main) nozzle, 1 the left. From the H2D's reports as the kit reads them; not checked
# against every dual-nozzle model.
NOZZLES = {0: "right", 1: "left"}
OFFERED = "manual-map-offered"      # in the printer's state folder: the share question was asked


class ManualError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


@dataclass
class _Session:
    id: str
    serial: str
    positions: list[dict]                 # [{id, label, ams_id, tray_id}] in the order the owner loads them
    dual: bool
    started: float = field(default_factory=lambda: time.time())
    open: bool = True
    answers: dict = field(default_factory=dict)      # label -> {status, reported_label, nozzle, at}
    step_since: float = field(default_factory=lambda: time.time())
    baseline: frozenset = frozenset()     # what was loaded when the step began
    seen: tuple | None = None             # (frozenset of loaded addresses, first seen at, nozzle)
    any_report: bool = False
    offer: bool = False


def _loaded(report: dict) -> tuple[frozenset, dict]:
    """(the (ams_id, tray_id) loaded now, address -> nozzle name where the printer says which nozzle)."""
    nozzle = {}
    for e in status._l(status._d(status._d(status._d(report).get("device")).get("extruder")).get("info")):
        v = status._int(e.get("snow"))
        if v is not None and 0 <= v < 0xFF00 and (v >> 8) != 0xFF:
            nozzle[(v >> 8, v & 0xFF)] = NOZZLES.get(status._int(e.get("id"), 0) or 0)
    return frozenset(loading._feeding(report)), nozzle


def _reports_loads(report: dict) -> bool:
    has_now = "tray_now" in status._d(status._d(report).get("ams"))
    return has_now or loading._has_snow(report)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class ManualMaps:
    def __init__(self, manager):
        self._m = manager
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}

    # ---------------------------------------------------------------- the session
    def start(self, serial: str) -> dict:
        report = self._m.wait_report(serial, lambda r: True, 0)
        if not isinstance(report, dict) or self._m.state(serial) not in ("connected", "needs_developer_mode"):
            raise ManualError(409, "printer_offline", "The printer is offline: turn it on, then start again.")
        if status._s(report.get("gcode_state")).upper() in status.ACTIVE:
            raise ManualError(409, "printer_busy", "The printer is busy: start again when it is idle.")
        with self._lock:
            s = self._sessions.get(serial)
            if s is not None and s.open:
                return self._state(s, report)       # a second device joins the session that is open
            if not mapping.manual_begin(serial):
                raise ManualError(409, "map_running", mapping.AlreadyRunning.message)
            lay = layout.build(report, ams.printer_model(serial))
            positions = [{"id": sl.label, "label": sl.label, "ams_id": u.ams_id, "tray_id": sl.tray_id}
                         for u in lay.units for sl in u.slots]
            nozzles = lay.model.nozzles if lay.model.known else loading.reported_nozzles(report)
            s = _Session(secrets.token_hex(4), serial, positions, dual=(nozzles or 1) > 1)
            s.baseline = _loaded(report)[0]
            s.any_report = _reports_loads(report)
            self._sessions[serial] = s
            return self._state(s, report)

    def view(self, serial: str) -> dict:
        with self._lock:
            s = self._sessions.get(serial)
            if s is None:
                raise ManualError(404, "none", "No manual mapping was started for this printer.")
            report = self._m.wait_report(serial, lambda r: True, 0) if s.open else None
            return self._state(s, report)

    def _session(self, serial: str, sid) -> _Session:
        s = self._sessions.get(serial)
        if s is None or not s.open:
            raise ManualError(404, "none", "No manual mapping is open for this printer.")
        if sid != s.id:
            raise ManualError(409, "stale", "This manual mapping moved on or was restarted: show it again.")
        return s

    def confirm(self, serial: str, sid, position, reported, nozzle=None, by_hand: bool = False) -> dict:
        with self._lock:
            s = self._session(serial, sid)
            pos = next((p for p in s.positions if p["id"] == position), None)
            if pos is None:
                raise ManualError(400, "bad_request", "No such position on this printer.")
            addr = self._address(s, reported, by_hand)
            if nozzle not in (None, "left", "right") or (nozzle is not None and not s.dual):
                raise ManualError(400, "bad_request", "nozzle is left, right or none, and only on a dual-nozzle printer")
            self._write(serial, pos["label"], addr, "user-unverified" if by_hand else "user", nozzle)
            s.answers[pos["label"]] = {"status": "by_hand" if by_hand else "confirmed",
                                       "reported_label": layout.label_for(*addr, ams.printer_model(serial)),
                                       "nozzle": nozzle, "at": _now_iso()}
            self._next_step(s)
            return self._state(s, self._m.wait_report(serial, lambda r: True, 0))

    def skip(self, serial: str, sid, position) -> dict:
        with self._lock:
            s = self._session(serial, sid)
            if not any(p["id"] == position for p in s.positions):
                raise ManualError(400, "bad_request", "No such position on this printer.")
            s.answers[position] = {"status": "skipped", "reported_label": None, "nozzle": None, "at": _now_iso()}
            self._next_step(s)
            return self._state(s, self._m.wait_report(serial, lambda r: True, 0))

    def stop(self, serial: str, sid) -> dict:
        with self._lock:
            s = self._session(serial, sid)
            self._close(s)
            return self._state(s, None)

    def answer_offer(self, serial: str, share: bool) -> dict:
        """The owner's answer to the one-time question: share this map in a printer report (default off)."""
        d = config.paths().state / "printers" / serial
        d.mkdir(parents=True, exist_ok=True)
        (d / OFFERED).write_text("yes\n" if share else "no\n", encoding="utf-8")
        with self._lock:
            s = self._sessions.get(serial)
            if s is not None:
                s.offer = False
        if not share:
            return {"share": False, "message": "Noted: this map is not shared."}
        return {"share": True, "message": "Noted. The kit sends nothing itself: make the report with Collect a report on "
                f"the printer's page in any of them (the setup page, the phone web app, the Android app), or on the server "
                f"run: sudo filament-kit printer report {serial}, then attach the "
                "file to an issue."}

    # ---------------------------------------------------------------- inside
    def _close(self, s: _Session) -> None:
        s.open = False
        mapping.manual_end(s.serial)
        done = [a for a in s.answers.values() if a["status"] in ("confirmed", "by_hand")]
        s.offer = bool(done) and not (config.paths().state / "printers" / s.serial / OFFERED).exists()

    def _next_step(self, s: _Session) -> None:
        s.step_since, s.seen = time.time(), None
        report = self._m.wait_report(s.serial, lambda r: True, 0)
        if isinstance(report, dict):
            s.baseline = _loaded(report)[0]
        if self._step(s) is None:
            self._close(s)

    def _step(self, s: _Session) -> dict | None:
        return next((p for p in s.positions if p["label"] not in s.answers), None) if s.open else None

    def _address(self, s: _Session, reported, by_hand: bool) -> tuple[int, int]:
        if not isinstance(reported, dict):
            raise ManualError(400, "bad_request", "reported must be what the state showed")
        a, t = status._int(reported.get("ams_id")), status._int(reported.get("tray_id"))
        if a is None or t is None or not any((p["ams_id"], p["tray_id"]) == (a, t) for p in s.positions):
            raise ManualError(400, "bad_request", "That slot is not one this printer has.")
        if not by_hand and (s.seen is None or (a, t) not in s.seen[0]):
            raise ManualError(409, "stale", "The printer no longer reports that load: show it again.")
        return a, t

    def _write(self, serial: str, label: str, addr: tuple[int, int], by: str, nozzle) -> None:
        with ams._SAVE_LOCK:
            m = ams.load_map(serial)
            model = ams.printer_model(serial)
            for other, slot in list(m.slots.items()):       # an address belongs to one label
                if other != label and (slot.get("ams_id"), slot.get("tray_id")) == addr:
                    del m.slots[other]
                    m.by_user.pop(other, None)
            m.slots[label] = {"ams_id": addr[0], "tray_id": addr[1],
                              "global_id": ams.scheme_global(addr[0], addr[1], m.scheme, model) if m.scheme
                              else ams.default_global(addr[0], addr[1], model)}
            m.by_user[label] = {"by": by, "at": _now_iso(), **({"nozzle": nozzle} if nozzle else {})}
            # which slot is which is now the owner's word; the numbering for print jobs is proven only by a scheme
            m.calibrated = bool(m.scheme)
            m.observe = not m.calibrated
            m.stale = m.suspect = False
            ams.save_map(serial, m)

    def _state(self, s: _Session, report) -> dict:
        step = self._step(s)
        seen = ask = None
        now = time.time()
        if s.open and step is not None and isinstance(report, dict):
            s.any_report = s.any_report or _reports_loads(report)
            loaded, nozzle = _loaded(report)
            new = loaded - s.baseline
            if new:
                if s.seen is None or s.seen[0] != new:
                    s.seen = (new, now, next((nozzle[a] for a in new if a in nozzle), None))
            else:
                s.seen = None
            if s.seen is not None and len(s.seen[0]) == 1:
                (a, t), = s.seen[0]
                settled = now - s.seen[1] >= SETTLE
                rlabel = layout.label_for(a, t, ams.printer_model(s.serial))
                seen = {"reported": {"ams_id": a, "tray_id": t}, "reported_label": rlabel, "nozzle": s.seen[2],
                        "nozzle_reported": s.seen[2] is not None, "settled": settled}
                if settled:
                    ask = f"The printer now reports {rlabel} loaded. Is that the {step['label']} you loaded?"
        # no load field at all, or one that has not changed for a minute while the owner loads: the by-hand form
        reports = s.any_report and not (s.seen is None and now - s.step_since >= NO_REPORT_AFTER)
        out = {"session": s.id, "open": s.open, "dual_nozzle": s.dual, "reports_loads": reports,
               "step": None if step is None else {
                   "position": {"id": step["id"], "label": step["label"]},
                   "say": f"Load {step['label']} to the nozzle, then wait." if reports else
                          f"This printer does not say what is loaded. Load {step['label']}, then pick the slot it is "
                          f"in from the list.",
                   "seen": seen, "ask": ask},
               "positions": [{"id": p["id"], "label": p["label"],
                              **({"status": "pending", "reported_label": None, "nozzle": None, "at": None}
                                 | s.answers.get(p["label"], {}))} for p in s.positions],
               "summary": self._summary(s), "offer_report": s.offer and not s.open}
        if not reports:
            out["choices"] = [{"reported": {"ams_id": p["ams_id"], "tray_id": p["tray_id"]}, "label": p["label"]}
                              for p in s.positions]
        return out

    def _summary(self, s: _Session) -> str:
        n = len(s.positions)
        conf = sum(a["status"] == "confirmed" for a in s.answers.values())
        hand = sum(a["status"] == "by_hand" for a in s.answers.values())
        skipped = [label for label, a in s.answers.items() if a["status"] == "skipped"]
        parts = [f"{conf} of {n} positions confirmed"]
        if hand:
            parts.append(f"{hand} entered by hand (not checked by the printer)")
        if skipped:
            parts.append(f"skipped: {', '.join(skipped)}")
        text = "; ".join(parts) + "."
        if not s.open:
            left = [p["label"] for p in s.positions if p["label"] not in s.answers]
            if left:
                text += f" Not mapped: {', '.join(left)}."
            if conf or hand:
                m = ams.load_map(s.serial)
                text += (" Loading spools into these slots works now." if m.scheme else
                         " Loading spools into these slots works now; filament use stays logged only until the "
                         "printer's slot numbering is proven by Map slots.")
        return text
