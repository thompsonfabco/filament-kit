"""The watcher: writes the events of both printer families' listeners, and the Hub's 5-minute loop (R80 sections 2, 6, 7).

Printer events (`Watcher`): it listens to the Bambu `Manager` (report listener) and the `KlipperFamily` (`status`
and `job_ended` events) through their existing hooks and writes print.started / paused / runout / resumed /
finished / failed, printer.error and printer.offline / online with their conditions. The first sight of a printer
after the Hub starts writes nothing (it only learns the state; a condition left raised by an earlier run is cleared
as `reconciled` if it is no longer true), and neither do the kit's own slot-mapping (calibration) jobs.

How runout is told from another pause (R80 assumption 3): Bambu, the stage "Paused: filament runout"; Klipper, a
filament switch or motion sensor reporting no filament, or the filament system's active slot reporting none, at the
pause. A pause is decided when the answer is clear or `PAUSE_SETTLE` seconds after it began (Moonraker and Bambu may
send the state and the stage or sensor in separate messages); where the Hub cannot tell, the event is print.paused
with reason `unknown`, so the person is still alerted.

The loop (`Loop`, every 5 minutes): the disk (storage.low / storage.ok), low spools (spool.low / spool.ok), the Weigh
Station (device.down / device.up), the Checks rows (check.failed / check.ok), the reconciliation of raised conditions
and, once a day, the deletion of old month files (`events.keep_days`). No texts are built here (EA3).
"""
from __future__ import annotations

import logging
import threading
import time

from . import alerts, config, event_sink
from .bridge import registry, status
from .bridge.usage import CALIB_PREFIXES

log = logging.getLogger("filament_kit.watch")

PAUSE_SETTLE = 2.0          # seconds to wait for the stage or the sensor that says why a print paused
POLL = 5.0                  # seconds between looks at whether each printer answers
OFFLINE_GRACE = 30.0        # seconds a printer must stay offline before printer.offline (a reconnect is not news)
BAMBU_ONLINE = ("connected", "needs_developer_mode")
KLIPPER_ONLINE = ("connected", "unknown_model")
ACTIVE = ("RUNNING", "PAUSE")
HUB = {"type": "hub"}
RUNOUT_STAGE = 6            # status.STAGES[6] = "Paused: filament runout"
USER_STAGE = 16             # "Paused by user"


def _subject(pid: str) -> dict:
    p = registry.load().get(pid)
    return {"type": "printer", "id": pid, "name": registry.display_name(p) if p else pid}


class _Printer:
    def __init__(self):
        self.state: str | None = None        # RUNNING / PAUSE / FINISH / FAILED / IDLE / OTHER; None = not seen yet
        self.job = ""
        self.started_at: float | None = None
        self.pending = False                 # a pause is waiting for its reason
        self.timer: threading.Timer | None = None
        self.errors: set[str] = set()        # printer error codes already told
        self.online: bool | None = None      # None = not known; False = known offline (told or first sight)
        self.offline_told = False
        self.offline_since: float | None = None


class Watcher:
    """Turns what the printers report into events. `sink` (default: the sink in force) takes them; `mapping_busy(id)`
    says the kit's own slot mapping runs on a printer (its jobs write no event)."""

    def __init__(self, sink=None, *, mapping_busy=None, settle: float = PAUSE_SETTLE, grace: float = OFFLINE_GRACE,
                 clock=time.monotonic):
        self._sink = sink
        self._busy = mapping_busy or (lambda pid: False)
        self.settle, self.grace, self._clock = settle, grace, clock
        self._lock = threading.RLock()
        self._p: dict[str, _Printer] = {}
        self._bambu = None
        self._klipper = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- wiring
    @property
    def sink(self):
        return self._sink if self._sink is not None else event_sink.sink()

    def attach(self, bambu=None, klipper=None) -> "Watcher":
        """Listen to the Bambu Manager and the KlipperFamily (either may be None)."""
        self._bambu, self._klipper = bambu, klipper
        if bambu is not None:
            bambu.add_listener(self.on_report)
        if klipper is not None:
            klipper.add_listener(self.on_klipper)
        return self

    def start(self) -> None:
        """Look at whether each printer answers every POLL seconds, on a thread of its own."""
        self._stop.clear()

        def run():
            while not self._stop.wait(POLL):
                try:
                    self.poll()
                except Exception:  # noqa: BLE001 - the watcher must outlive an odd printer
                    log.exception("watcher: poll failed")
        self._thread = threading.Thread(target=run, name="event-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for p in self._p.values():
                if p.timer is not None:
                    p.timer.cancel()
        if self._thread is not None:
            self._thread.join(2)
            self._thread = None

    def flush(self) -> None:
        """Decide every waiting pause now (tests, shutdown)."""
        for pid in [k for k, p in list(self._p.items()) if p.pending]:
            self._decide(pid, final=True)

    # ---- writing
    def _write(self, kind: str, pid: str, data: dict | None = None, **kw):
        return self.sink.write(kind, _subject(pid), HUB, data, **kw)

    def _run(self, pid: str, job: str = "") -> str:
        run = event_sink.runs.current(pid)
        return run or event_sink.runs.begin(pid, job)

    def _clear(self, pid: str, key: str, reason: str = "reconciled") -> None:
        self.sink.write("condition.cleared", _subject(pid), HUB, {"key": key, "reason": reason})

    # ---- Bambu
    @staticmethod
    def bambu_view(report: dict) -> dict:
        """The report as the watcher reads it: state, job, percent, stage number and text, print error, HMS codes."""
        p = status._d(report)
        gs = status._s(p.get("gcode_state")) or "UNKNOWN"
        stg = status._int(p.get("stg_cur"), -1)
        active = gs in ("RUNNING", "PAUSE", "PREPARE", "SLICING")
        return {"state": {"PREPARE": "RUNNING", "SLICING": "RUNNING"}.get(gs, gs) if active
                else gs if gs in ("FINISH", "FAILED", "IDLE") else "OTHER",
                "job": status._s(p.get("subtask_name")) or "", "percent": status._int(p.get("mc_percent"), 0) or 0,
                "stage_no": stg if active else -1,
                "stage": status.STAGES.get(stg, f"Stage {stg}") if active and 0 <= stg < 255 else "",
                "error": status._print_error(p),
                "hms": {status.hms_code(e): status.hms_text(status.hms_code(e)) for e in status._l(p.get("hms"))}}

    def on_report(self, serial: str, report: dict, first: bool) -> None:
        """The Bambu Manager's report listener (the MQTT thread of that printer)."""
        if not isinstance(report.get("gcode_state"), str):
            return
        try:
            self._step(serial, self.bambu_view(report), first,
                       lambda: self.bambu_view(self._bambu.wait_report(serial, lambda r: True, 0) or report),
                       bambu=True)
        except Exception:  # noqa: BLE001 - never break the printer's report thread
            log.exception("watcher: report of %s", serial)

    # ---- Klipper
    @staticmethod
    def klipper_view(v: dict) -> dict:
        """`KlipperFamily.live()` as the watcher reads it. A sensor or the active slot saying no filament is runout
        evidence; sensors or a slot all saying filament is present is evidence the pause is not a runout."""
        ps = v.get("print")
        state = {"printing": "RUNNING", "paused": "PAUSE", "complete": "FINISH", "cancelled": "FAILED",
                 "error": "FAILED", "standby": "IDLE"}.get(ps, "OTHER")
        evidence = list(v.get("sensors", {}).values()) + ([v["slot"]["present"]] if v.get("slot") else [])
        return {"state": state, "job": v.get("job") or "", "percent": v.get("percent") or 0,
                "fail": ps if ps in ("cancelled", "error") else None, "error": v.get("message") or "",
                "runout": (False in evidence) if evidence else None, "slot": (v.get("slot") or {}).get("label", ""),
                "hms": {}}

    def on_klipper(self, pid: str, event: str, data) -> None:
        """The KlipperFamily's listener: `status` (a delta arrived) and `job_ended` matter."""
        if event not in ("status", "job_ended") or self._klipper is None:
            return
        try:
            v = self._klipper.live(pid, slot=False)
            if v is None:
                return
            if v["print"] == "paused":                  # the filament system is read only for a pause
                v = self._klipper.live(pid) or v
            if event == "job_ended":
                self._ended_without_state(pid)
            elif v["state"] in KLIPPER_ONLINE:
                self._step(pid, self.klipper_view(v), False,
                           lambda: self.klipper_view(self._klipper.live(pid) or v))
        except Exception:  # noqa: BLE001
            log.exception("watcher: klipper %s", pid)

    def _ended_without_state(self, pid: str) -> None:
        """Klipper shut down in the middle of a job: no end state arrives, the job just ended (an error)."""
        with self._lock:
            p = self._p.get(pid)
            if p is None or p.state not in ACTIVE or self._skip(pid, p.job):
                return
            self._finish(pid, p, "FAILED", {"percent": 0, "job": p.job, "fail": "error", "error": "klippy_shutdown"})

    # ---- the one state machine
    def _skip(self, pid: str, job: str) -> bool:
        return self._busy(pid) or bool(job) and job.startswith(CALIB_PREFIXES)

    def _step(self, pid: str, obs: dict, first: bool, reader, bambu: bool = False) -> None:
        with self._lock:
            p = self._p.setdefault(pid, _Printer())
            prev, new = p.state, obs["state"]
            p.state = new
            if obs["job"]:
                p.job = obs["job"]
            if prev is None or first:                         # first sight: learn, write nothing
                p.errors = (set(obs["hms"]) | ({obs["error"]} if obs["error"] else set())) if bambu else set()
                if new != "PAUSE" and self.sink.is_raised(f"print-paused:{pid}"):
                    self._clear(pid, f"print-paused:{pid}")
                if new in ACTIVE:
                    p.started_at = None
                return
            if not self._skip(pid, obs["job"]):
                if p.pending and prev == new == "PAUSE":          # the stage or sensor that says why may just have come
                    self._decide(pid, final=False, obs=obs)
                self._transition(pid, p, prev, new, obs, reader)
                if bambu:
                    self._errors(pid, p, obs)
            if new not in ACTIVE and p.pending:
                self._cancel_pause(p)

    def _transition(self, pid, p, prev, new, obs, reader) -> None:
        was = prev in ACTIVE
        if new == "RUNNING":
            if prev == "PAUSE":
                self._cancel_pause(p)               # paused and running again before its reason came: no news
                if self.sink.is_raised(f"print-paused:{pid}"):
                    self._write("print.resumed", pid, {"job": p.job, "run": self._run(pid, p.job)})
            elif not was:
                run = event_sink.runs.begin(pid, p.job)
                p.started_at = time.time()
                self._write("print.started", pid, {"job": p.job, "printer": pid, "run": run})
        elif new == "PAUSE" and prev == "RUNNING":
            p.pending = True
            if not self._decide(pid, final=False, obs=obs):
                p.timer = threading.Timer(self.settle, self._decide, (pid, True, None, reader))
                p.timer.daemon = True
                p.timer.start()
        elif new in ("FINISH", "FAILED") and was:
            self._finish(pid, p, new, obs)
        elif new in ("IDLE", "OTHER") and was and self.sink.is_raised(f"print-paused:{pid}"):
            self._clear(pid, f"print-paused:{pid}")            # the print is gone without an end state
            event_sink.runs.end(pid)

    def _finish(self, pid: str, p: _Printer, new: str, obs: dict) -> None:
        self._cancel_pause(p)
        run = self._run(pid, p.job)
        if new == "FINISH":
            mins = round((time.time() - p.started_at) / 60) if p.started_at else None
            self._write("print.finished", pid, {"job": p.job, "minutes": mins, "run": run})
        else:
            reason = obs.get("fail") or ("error" if obs.get("error") else "unknown")   # Bambu: see the module doc
            self._write("print.failed", pid, {"job": p.job, "percent": obs["percent"], "reason": reason,
                                              "error": obs.get("error") or None, "run": run})
        p.state = new
        event_sink.runs.end(pid)

    def _cancel_pause(self, p: _Printer) -> None:
        p.pending = False
        if p.timer is not None:
            p.timer.cancel()
            p.timer = None

    def _decide(self, pid: str, final: bool, obs: dict | None = None, reader=None) -> bool:
        """Write the pause's event when its reason is clear (or `final`). True when written."""
        with self._lock:
            p = self._p.get(pid)
            if p is None or not p.pending or p.state != "PAUSE":
                return False
            if obs is None:
                try:
                    obs = reader() if reader else None
                except Exception:  # noqa: BLE001
                    log.exception("watcher: reading %s for its pause", pid)
                    obs = None
                if obs is None:
                    obs = {"state": "PAUSE", "job": p.job, "percent": 0, "hms": {}}
                if obs["state"] != "PAUSE":
                    return False
            kind, data = self._reason(obs, final)
            if kind is None:
                return False
            p.pending = False
            p.timer = None
            data.update(job=obs["job"] or p.job, percent=obs["percent"], run=self._run(pid, p.job))
            self._write(kind, pid, data)
            return True

    @staticmethod
    def _reason(obs: dict, final: bool) -> tuple[str | None, dict]:
        """(event kind, its values) for a pause, or (None, {}) while the reason may still arrive."""
        if "stage_no" in obs:                                   # Bambu
            n = obs["stage_no"]
            if n == RUNOUT_STAGE:
                return "print.runout", {}
            if obs["error"] or (obs["stage"].startswith("Paused:")):
                return "print.paused", {"reason": "error", "stage": obs["stage"] or None}
            if n == USER_STAGE:
                return "print.paused", {"reason": "user", "stage": obs["stage"]}
            return ("print.paused", {"reason": "unknown", "stage": obs["stage"] or None}) if final else (None, {})
        if obs.get("runout"):                                   # Klipper: a sensor or the slot says no filament
            return "print.runout", ({"slot": obs["slot"]} if obs.get("slot") else {})
        if not final:
            return None, {}
        if obs.get("error"):
            return "print.paused", {"reason": "error", "stage": obs["error"]}
        if obs.get("runout") is False:                          # the sensors say filament is there: not a runout
            return "print.paused", {"reason": "user"}
        return "print.paused", {"reason": "unknown"}            # no sensor to ask (R80 fallback)

    def _errors(self, pid: str, p: _Printer, obs: dict) -> None:
        """printer.error for each error code that was not there before (HMS codes and the print error)."""
        now = {**obs["hms"], **({obs["error"]: obs.get("stage") or ""} if obs["error"] else {})}
        for code, text in now.items():
            if code not in p.errors:
                self._write("printer.error", pid, {"code": code, "text": text})
        p.errors = set(now)

    # ---- do the printers answer
    def _online(self, pid: str, family: str) -> bool | None:
        """True answering, False offline, None not decided (connecting, wrong code ...)."""
        if family == "klipper":
            st = self._klipper.state(pid) if self._klipper is not None else None
            return True if st in KLIPPER_ONLINE else False if st == "offline" else None
        st = self._bambu.state(pid) if self._bambu is not None else None
        return True if st in BAMBU_ONLINE else False if st == "offline" else None

    def poll(self) -> None:
        """Write printer.offline / printer.online, and clear what a removed printer left raised."""
        printers = {s: p for s, p in registry.load().items() if p.configured}
        now = self._clock()
        with self._lock:
            for pid, pr in printers.items():
                on = self._online(pid, pr.family)
                if on is None:
                    continue
                p = self._p.setdefault(pid, _Printer())
                key = f"printer-offline:{pid}"
                if on:
                    p.offline_since = None
                    if p.online is not True and self.sink.is_raised(key):
                        if p.online is False and p.offline_told:
                            self._write("printer.online", pid)
                        else:
                            self._clear(pid, key)
                    p.online, p.offline_told = True, False
                elif p.online is None:
                    p.online = False                               # first sight: learn, write nothing
                elif p.online:
                    p.offline_since = p.offline_since if p.offline_since is not None else now
                    if now - p.offline_since >= self.grace:
                        self._write("printer.offline", pid)
                        p.online, p.offline_told = False, True
            self._forget_removed(printers)

    def _forget_removed(self, printers: dict) -> None:
        """A removed printer: its raised conditions are cleared at once (`subject_removed`), its state forgotten."""
        for ev in self.sink.conditions():
            key = ev["condition"]["key"]
            base, _, pid = key.partition(":")
            if base in ("print-paused", "printer-offline") and pid and pid not in printers:
                self._clear(pid, key, "subject_removed")
        for pid in [k for k in self._p if k not in printers]:
            if self._p[pid].timer is not None:
                self._p[pid].timer.cancel()
            del self._p[pid]
            event_sink.runs.forget(pid)

    def reconcile(self) -> None:
        """Clear a print-paused condition whose printer is known and not paused (the loop's every-5-minutes check)."""
        with self._lock:
            for ev in self.sink.conditions():
                base, _, pid = ev["condition"]["key"].partition(":")
                p = self._p.get(pid)
                if base == "print-paused" and p is not None and p.state not in (None, "PAUSE") and not p.pending:
                    self._clear(pid, ev["condition"]["key"])


# ---------------------------------------------------------------- the 5-minute loop

EVERY = 300.0               # seconds between rounds (R80 section 6)
PRUNE_EVERY = 86400.0       # old month files are deleted once a day
FIRST_AFTER = 30.0          # seconds after the Hub starts until the first round (services are still starting)


def _raised(sink, base: str) -> dict:
    """{suffix: the event that raised it} of the raised conditions whose key starts with `base:`."""
    out = {}
    for ev in sink.conditions():
        b, _, rest = ev["condition"]["key"].partition(":")
        if b == base:
            out[rest] = ev
    return out


def check_disk(sink, settings: dict | None = None) -> None:
    """storage.low / storage.ok from the disk in the worst state (R80 section 6): one event per limit passed; the
    disk falling from bad back to warn writes storage.low again, severity warn, `direction` down (never an alert)."""
    s = settings or alerts.load()
    fs = alerts.worst(alerts.filesystems(s))
    if fs is None:
        return
    raised = next((e for e in sink.conditions() if e["condition"]["key"] == "storage-low"), None)
    data = {"free": fs["free"], "total": fs["total"], "percent": fs["percent_used"]}
    subject = {"type": "hub"}
    if fs["state"] == "ok":
        if raised is not None:
            sink.write("storage.ok", subject, HUB, {"free": fs["free"], "total": fs["total"]})
    elif raised is None or (raised["severity"] == "warn" and fs["state"] == "bad"):
        sink.write("storage.low", subject, HUB, data, severity=fs["state"])
    elif raised["severity"] == "bad" and fs["state"] == "warn":
        sink.write("storage.low", subject, HUB, {**data, "direction": "down"}, severity="warn")


def check_low(sm, sink=None, settings: dict | None = None) -> None:
    """spool.low for each opened spool that is at or under the threshold and not raised yet; spool.ok (or
    condition.cleared when the spool is gone) for each raised one that is not low any more. Nothing when Spoolman
    cannot be read."""
    from .spoolman import SpoolmanError
    sink = sink if sink is not None else event_sink.sink()
    s = settings or alerts.load()
    try:
        spools = sm.get("spool") or []
    except SpoolmanError as e:
        log.info("spools are not checked for running low: %s", e)
        return
    low = {r["id"]: r for r in alerts.running_low(spools, s)["spools"]}
    raised = _raised(sink, "spool-low")
    by_id = {sp.get("id"): sp for sp in spools}
    for sid, r in low.items():
        if str(sid) not in raised:
            sink.write("spool.low", event_sink.spool_subject(by_id[sid]), HUB,
                       {"spool": sid, "filament": r["filament"], "material": r["material"], "grams": r["remaining_g"],
                        "in_stock": r["in_stock"]})
    for key, ev in raised.items():
        if key.isdigit() and int(key) in low:
            continue
        subject = ev["subject"]
        if key.isdigit() and int(key) in by_id:               # above the threshold again, sealed or emptied
            sink.write("spool.ok", subject, HUB, {"spool": key})
            continue
        try:
            sm.get(f"spool/{key}")
        except SpoolmanError as e:
            if e.status == 404:
                sink.write("condition.cleared", subject, HUB, {"key": f"spool-low:{key}", "reason": "subject_removed"})
            continue
        sink.write("spool.ok", subject, HUB, {"spool": key})  # archived: emptied


def check_devices(sink, station_url: str | None, devices: list[dict]) -> None:
    """device.down / device.up for the Weigh Station, when the Hub can ask it (its address is set and exactly one
    station is paired: the known limit of 0.6.2). Tag Readers are not covered (R80 E3)."""
    from .station_client import station_reach
    reach = station_reach(devices, station_url)
    by_id = {d["id"]: d for d in devices}
    for key, ev in _raised(sink, "device-down").items():
        if key not in by_id:
            sink.write("condition.cleared", ev["subject"], HUB, {"key": f"device-down:{key}",
                                                                 "reason": "subject_removed"})
        elif key not in reach:                               # the address is gone or two stations are paired
            sink.write("condition.cleared", ev["subject"], HUB, {"key": f"device-down:{key}", "reason": "reconciled"})
    for did, up in reach.items():
        d = by_id[did]
        subject = {"type": "device", "id": did, "name": d.get("name") or ""}
        down = f"device-down:{did}"
        if not up and not sink.is_raised(down):
            sink.write("device.down", subject, HUB)
        elif up and sink.is_raised(down):
            sink.write("device.up", subject, HUB)


def row_key(row) -> str:
    """The key of a Checks row: its own `key` when it has one (EA3 may give Row one), else the group and the
    first two words of its text without digits (the text of a row changes with its numbers, its key must not)."""
    k = getattr(row, "key", "")
    if k:
        return k
    words = "".join(c if c.isalpha() or c in " -" else " " for c in str(row.text)).lower().split()[:2]
    return f"{(getattr(row, 'group', '') or 'hub').lower()}.{'-'.join(words)}"


def check_rows(sink, rows) -> None:
    """check.failed when a Checks row needs a look and none is raised for it; check.ok when a raised one is fine
    again; condition.cleared (feature_off) for a raised one whose row no longer exists. Rows that are notes or
    detail lines are not checks."""
    seen = {}
    for r in rows:
        if r.state in ("ok", "fail"):
            seen[row_key(r)] = r
    raised = _raised(sink, "check")
    hub = {"type": "hub"}
    for key, r in seen.items():
        if r.state == "fail" and key not in raised:
            sink.write("check.failed", hub, HUB, {"text": r.text}, key=key)
        elif r.state == "ok" and key in raised:
            sink.write("check.ok", hub, HUB, {"text": r.text}, key=key)
    for key, ev in raised.items():
        if key not in seen:
            sink.write("condition.cleared", hub, HUB, {"key": f"check:{key}", "reason": "feature_off"})


class Loop:
    """Every 5 minutes: the disk, low spools, the Weigh Station, the Checks rows, the printers' raised conditions
    against the present state, and once a day the deletion of old month files. A step that fails is logged and the
    others still run. `rows()` gives the Checks rows (status.collect in the Hub), `devices()` the paired devices."""

    def __init__(self, sink=None, *, spoolman=None, watcher: Watcher | None = None, rows=None, devices=None,
                 every: float = EVERY, first: float = FIRST_AFTER, clock=time.monotonic):
        self._sink = sink
        self.sm, self.watcher, self._rows, self._devices = spoolman, watcher, rows, devices
        self.every, self.first, self._clock = every, first, clock
        self._last_prune: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def sink(self):
        return self._sink if self._sink is not None else event_sink.sink()

    def start(self) -> None:
        self._stop.clear()

        def run():
            if self._stop.wait(self.first):          # let the services start before the first look at the Checks
                return
            self.tick()
            while not self._stop.wait(self.every):
                self.tick()
        self._thread = threading.Thread(target=run, name="event-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None

    def tick(self) -> None:
        steps = [("printers", lambda: self.watcher.reconcile() if self.watcher else None),
                 ("disk", lambda: check_disk(self.sink)),
                 ("spools", lambda: check_low(self.sm, self.sink) if self.sm is not None else None),
                 ("devices", self._check_devices),
                 ("checks", lambda: check_rows(self.sink, self._rows()) if self._rows else None),
                 ("prune", self._prune)]
        for name, step in steps:
            try:
                step()
            except Exception:  # noqa: BLE001 - one step must not stop the rest
                log.exception("the 5-minute round: %s failed", name)

    def _check_devices(self) -> None:
        from . import pairing
        devs = self._devices() if self._devices else pairing.devices()
        check_devices(self.sink, (config.load().get("station") or {}).get("url"), devs)

    def _prune(self) -> None:
        """Delete month files older than `events.keep_days` once a day (the only caller of the store's prune)."""
        from . import events
        now = self._clock()
        if self._last_prune is not None and now - self._last_prune < PRUNE_EVERY:
            return
        self._last_prune = now
        events.prune(config.keep_days(config.load()))
