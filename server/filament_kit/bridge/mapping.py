"""Slot mapping: the slot test (`slottest.run`) then the calibration job (`calib3mf.run`) as one job per printer.

`Mapper.start(serial)` runs it on a background thread (the API), `Mapper.run(serial, on_step)` in the caller's
thread (the CLI). One writer per printer: a mapping job holds the printer for the whole job and a load holds it
for its write phase (`load_guard`), each refusing at once while the other holds it (`AlreadyRunning`, or
`LoadRunning` for a mapping refused by a load), in this process (`_WRITERS`) and across processes on Linux
(`mapping.lock`: loads LOCK_SH, mapping LOCK_EX, both non-blocking). A job is refused before anything is touched
unless the printer is in the registry (`UnknownPrinter`), its leaf matches the pin (state `cert_changed` ->
`CertChanged`), connected (`PrinterOffline`) and idle (`PrinterBusy`). `in_progress(serial)` says whether a job
runs for that printer in this or another process (the API refuses loading and unloading meanwhile).

Interruptions never leave a test colour silently: `abort(serial)` (the CLI on SIGINT / SIGTERM / SIGHUP) and
`shutdown()` (the service, before its printer connections close) stop the job cooperatively, and the slot test /
calibration restore every slot before the job ends `failed`; a KeyboardInterrupt still restores first. For a
process killed outright, the slot snapshot on disk (`snapshot`, saved before the first write, deleted after a
confirmed restore) is restored at the next job's start (the job is refused unless that restore is confirmed) and
by the service at start (`recover_pending`) once the printer is connected and idle; a calibration snapshot also
gets the killed job's file deleted from the printer then (best effort). `abort` takes no lock, so a signal
handler may call it at any moment.

Outcome (a job that ends `failed` never leaves a trusted map):
  - slot test could not put every slot back -> `failed`, problems name each slot, no calibration; the saved
    slot map keeps its slots but is downgraded to `calibrated: false, observe: true` (a slot may still hold a
    test colour, so what the map says can no longer be trusted); also `failed` when no slot was confirmed
    (offline, busy, Developer Mode ...) or the job broke, again with the saved map downgraded;
  - calibration consistent -> SlotMap of the confirmed slots and the empty ones (the slot test writes nothing to an
    empty slot, `SlotTestResult.empty`: its address is the report's), global ids from the calibration's decoding (a
    slot the calibration left out, an empty one or an external holder, takes the proven scheme's number: an external
    holder its own id), `calibrated: true, observe: false`;
  - calibration inconsistent or refused -> the same slots, default global ids, `calibrated: false, observe:
    true` (filament use is only logged), the reason in problems;
  - a calibration that left something changed (`CalibResult.restored` false: a filament left loaded in the
    toolhead; the calibration writes no slot, so a slot changed meanwhile is only reported) -> `failed`, the map saved
    with `calibrated: false, observe: true` even when the decoding was consistent.
Slots the slot test did not confirm are left out of the map and listed in problems.

Progress (`view`): in memory while the job runs, and in `state/printers/<serial>/mapping.json` (state, step,
problems), so after a restart `view` shows the last finished result (slots / calibrated / observe always come
from the saved SlotMap). A status file still saying "running" whose job no process holds is reported as
`failed` (interrupted), never "running" forever."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable

from .. import __version__, config
from ..pairing import _write_atomic, make_state_dir, open_lock
from . import ams, calib3mf, hardware, layout, printer_report, registry, slottest, snapshot, status
from .connection import PrinterOffline, UnknownPrinter
from .slottest import PrinterBusy

try:
    import fcntl
except ImportError:  # Windows dev PCs: one process only (the service runs on Linux)
    fcntl = None

log = logging.getLogger(__name__)
_STARTED = time.time()     # this server process's start: a job that ended before it is an earlier run's

STATUS_FILE = "mapping.json"
LOCK_FILE = "mapping.lock"
INTERRUPTED = ("the mapping was interrupted (the server or command stopped); the slots may still hold test "
               "colours: the next run restores them first, so run it again")
OBSERVE_NOTE = "slot numbering not confirmed: filament use is only logged until mapping succeeds"
STOPPED = "mapping was stopped (the server or command is stopping); the slots were put back first"
SHUTDOWN_WAIT = 60.0      # seconds the service waits at shutdown for a stopped job's restore
RECOVER_WAIT = 60.0       # seconds the service waits at start for a printer with a pending snapshot to connect
REMAP_STEP = "Re-mapping: the printer's AMS layout changed"
REMAP_SUSPECT_STEP = "Re-mapping: prints disagreed with the slot map"
REMAP_SETTLE = 30.0       # seconds a new layout must stay unchanged before an automatic re-map
REMAP_RETRY = 600.0       # seconds between automatic re-map attempts for one layout change
REMAP_TRIES = 3           # automatic attempts per layout change; then only a manual Map slots


class AlreadyRunning(Exception):
    """A mapping job is already running for this printer (or a load is writing to it: `LoadRunning`)."""

    message = "slot mapping is in progress for this printer; try again when it has finished"


class LoadRunning(AlreadyRunning):
    """A spool is being loaded into this printer right now: no mapping job may start."""

    message = "a spool is being loaded into this printer; try again in a moment"


class CertChanged(Exception):
    """The printer's certificate changed (state `cert_changed`): nothing is sent until it is added again."""


class _Flag:
    """A stop flag a signal handler may set: `threading.Event.set` takes a lock (its Condition), which would
    deadlock if the signal landed while the main thread held it. Setting a bool is atomic and takes none."""
    __slots__ = ("_on",)

    def __init__(self):
        self._on = False

    def set(self) -> None:
        self._on = True

    def is_set(self) -> bool:
        return self._on


@dataclass
class _Job:
    id: str
    state: str = "running"          # running | done | failed
    step: str = "Starting"
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)      # not problems: what a good result does not settle yet
    scheme_unsettled: bool = False                      # several numbering schemes fit; the model's first was taken
    report_wanted: str | None = None                    # printer_report.WANTED: why a report would help
    trail: list = field(default_factory=list)           # calib3mf.CalibResult.trail, for a report made later
    started: float = field(default_factory=time.time)
    finished: float | None = None
    abort: _Flag = field(default_factory=_Flag)
    auto: bool = False              # started by LayoutWatch (the printer's layout changed): the app shows re-mapping
    # set once the job has given the printer back; it shows done/failed a moment earlier
    released: threading.Event = field(default_factory=threading.Event)


def _dir(serial: str):
    return config.paths().state / "printers" / serial


def _save_status(serial: str, job: _Job) -> None:
    try:
        d = _dir(serial)
        make_state_dir(d)
        data = {"kit": __version__, "job_id": job.id, "state": job.state, "step": job.step, "problems": job.problems,
                "notes": job.notes, "scheme_unsettled": job.scheme_unsettled,
                "report_wanted": job.report_wanted, "trail": job.trail, "started": job.started, "finished": job.finished}
        _write_atomic(d / STATUS_FILE, json.dumps(data, indent=2).encode("utf-8"), 0o600, state_owned=True)
    except OSError:
        log.exception("mapping %s: cannot write the status file", serial)


def job_held_elsewhere(serial: str) -> bool:
    """A mapping job for `serial` holds the printer in another process (always False on Windows dev PCs)."""
    return _ProcessLock.held_elsewhere(serial)


def record_seeded(serial: str, step: str, problems: list[str] | None = None) -> None:
    """Record a slot map that came from elsewhere (`migrate_scanner`: the scanner's calibration) as the last
    finished mapping, so `view` (the app's mapping status) says where the map came from until a job maps again."""
    _save_status(serial, _Job(id=uuid.uuid4().hex, state="done", step=step, problems=list(problems or []),
                              finished=time.time()))


def _load_status(serial: str) -> dict | None:
    try:
        d = json.loads((_dir(serial) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("state") not in ("running", "done", "failed"):
        return None
    probs, notes = d.get("problems"), d.get("notes")
    finished = d.get("finished")
    kit = d.get("kit")
    return {"kit": kit if isinstance(kit, str) else None,
            "job_id": str(d.get("job_id") or ""), "state": d["state"], "step": str(d.get("step") or ""),
            "problems": [str(p) for p in probs] if isinstance(probs, list) else [],
            "notes": [str(n) for n in notes] if isinstance(notes, list) else [],
            "scheme_unsettled": d.get("scheme_unsettled") is True,
            "report_wanted": d.get("report_wanted") if d.get("report_wanted") in printer_report.WANTED else None,
            "trail": d.get("trail") if isinstance(d.get("trail"), list) else [],
            "finished": finished if isinstance(finished, (int, float)) and not isinstance(finished, bool) else None}


def _unrecognised(report: dict, model) -> str | None:
    """What the kit has no data for, though a mapping may work without it."""
    if not hardware.load().model(model).known:
        return "unknown_model"
    # a module code the file has no type for. Not `known`: that is also false for a first-gen AMS, which the file names
    # but hasn't verified, and for any unit before the printer has said its module code
    if any(u.kind == "generic" and u.module for u in layout.build(report, model).units):
        return "unknown_ams"
    return None


# ---------------------------------------------------------------- one writer per printer
# In this process: `_WRITERS[serial]` counts the loads writing to the printer and says whether a mapping job (or
# the start-up restore) holds it; both sides take it without waiting and refuse when the other holds it. Across
# processes the same rule rides on `mapping.lock`: a load's write phase holds LOCK_SH, a mapping job LOCK_EX, both
# LOCK_NB (flock, so a crashed process releases it; Windows dev PCs have no fcntl and only the in-process part).

_WRITERS: dict[str, dict] = {}
_WRITERS_GUARD = threading.Lock()


def _writer(serial: str) -> dict:
    return _WRITERS.setdefault(serial, {"map": False, "loads": 0})


class _ProcessLock:
    """The per-printer lock file: LOCK_EX for a mapping job (whole job), LOCK_SH for a load's write phase."""

    def __init__(self, serial: str, shared: bool = False):
        self.fh = None
        if fcntl is None:
            return
        d = _dir(serial)
        make_state_dir(d)
        fh = open_lock(d / LOCK_FILE)
        try:
            fcntl.flock(fh.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise AlreadyRunning(serial) from None
        self.fh = fh

    def release(self) -> None:
        if self.fh is not None:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None

    @staticmethod
    def held_elsewhere(serial: str) -> bool:
        """A mapping job (LOCK_EX) holds the lock file in another process; loads (LOCK_SH) do not count."""
        if fcntl is None:
            return False
        f = _dir(serial) / LOCK_FILE
        if not f.exists():
            return False
        try:
            with open(f, "a") as fh:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except OSError:
                    return True
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            return False
        return False


@contextmanager
def load_guard(serial: str):
    """Hold the printer for a load's (or unload's) write phase. Raises AlreadyRunning at once while a mapping job
    holds it, in this process or another one; loads do not exclude each other."""
    with _WRITERS_GUARD:
        w = _writer(serial)
        if w["map"]:
            raise AlreadyRunning(serial)
        w["loads"] += 1
    plock = None
    try:
        plock = _ProcessLock(serial, shared=True)
        yield
    finally:
        if plock is not None:
            plock.release()
        with _WRITERS_GUARD:
            w["loads"] -= 1


def _take_for_mapping(serial: str) -> _ProcessLock:
    """Hold the printer for a mapping job (or the start-up restore); raises AlreadyRunning / LoadRunning."""
    with _WRITERS_GUARD:
        w = _writer(serial)
        if w["map"]:
            raise AlreadyRunning(serial)
        if w["loads"]:
            raise LoadRunning(serial)
        w["map"] = True
    try:
        return _ProcessLock(serial)
    except BaseException:
        _give_back(serial, None)
        raise


def _give_back(serial: str, plock: _ProcessLock | None) -> None:
    try:
        if plock is not None:
            plock.release()
    finally:
        with _WRITERS_GUARD:
            _writer(serial)["map"] = False


def check_ready(manager, serial: str) -> None:
    """Raise UnknownPrinter / CertChanged / PrinterOffline / PrinterBusy unless mapping may start now."""
    if registry.load().get(serial) is None:
        raise UnknownPrinter(serial)
    if manager.state(serial) == "cert_changed":
        raise CertChanged(serial)
    slottest.check_idle(manager, serial)


def _delete_leftover_job(serial: str) -> None:
    """A pending calibration snapshot means a calibration was killed mid-job: its file may still be on the
    printer (`/cache/fk-calib-<serial>.gcode.3mf`). Delete it, best effort (logged, never fatal); read before the
    restore, which deletes the snapshot."""
    snap = snapshot.load(serial)
    if snap is None or snap.get("kind") != "calibration":
        return
    problems = calib3mf.delete_leftover(serial)
    if problems:
        log.warning("mapping %s: the killed calibration's file was not deleted: %s", serial, problems)
    else:
        log.info("mapping %s: deleted the file a killed calibration left on the printer", serial)


def _distrust(serial: str) -> None:
    """After a failed restore: keep the saved map's slots, but never as a trusted (calibrated) map."""
    m = ams.load_map(serial)
    if m.calibrated or not m.observe:
        m.calibrated, m.observe = False, True
        ams.save_map(serial, m)


class Mapper:
    def __init__(self, manager):
        self._m = manager
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}
        self._threads: list[threading.Thread] = []
        self._closing = threading.Event()
        self._abort_pending: set[str] = set()

    # ---------------------------------------------------------------- start / run
    def _begin(self, serial: str, auto: bool = False) -> tuple[_Job, _ProcessLock]:
        if registry.load().get(serial) is None:
            raise UnknownPrinter(serial)
        with self._lock:
            j = self._jobs.get(serial)
            if j is not None and (j.state == "running" or not j.released.wait(5)):
                raise AlreadyRunning(serial)    # a finished job is still giving the printer back: wait for that
            plock = _take_for_mapping(serial)
            try:
                check_ready(self._m, serial)
            except BaseException:
                _give_back(serial, plock)
                raise
            job = _Job(uuid.uuid4().hex, auto=auto)
            if auto:
                saved = ams.load_map(serial)
                job.step = REMAP_SUSPECT_STEP if saved.suspect and not saved.stale else REMAP_STEP
            self._jobs[serial] = job        # registered first: an abort from now on reaches it directly
            if self._closing.is_set() or serial in self._abort_pending:
                self._abort_pending.discard(serial)
                job.abort.set()
        _save_status(serial, job)
        log.info("mapping %s: job %s started", serial, job.id)
        return job, plock

    def start(self, serial: str, auto: bool = False) -> str:
        """Start the job on a background thread; returns its id. `auto`: started because the printer's layout
        changed (`LayoutWatch`)."""
        job, plock = self._begin(serial, auto)
        t = threading.Thread(target=self._run, args=(serial, job, plock, None), name=f"mapping-{serial}",
                             daemon=True)
        try:
            t.start()
        except BaseException as e:            # no thread: the job never ran, and must not hold the printer
            job.state, job.finished = "failed", time.time()
            job.problems.append(f"error: the mapping job could not start ({type(e).__name__}: {e})")
            _save_status(serial, job)
            _give_back(serial, plock)
            job.released.set()
            raise
        with self._lock:
            self._threads = [x for x in self._threads if x.is_alive()] + [t]
        return job.id

    def run(self, serial: str, on_step: Callable[[str], None] | None = None) -> dict:
        """Run the job here, telling `on_step(text)` each step; returns `view(serial)`."""
        job, plock = self._begin(serial)
        self._run(serial, job, plock, on_step)
        return self.view(serial)

    def abort(self, serial: str) -> None:
        """Stop the printer's job as soon as it can: the slots are put back first (CLI signals, shutdown).

        Called from signal handlers, so it takes no lock (the main thread may hold `_lock` in `_begin` or `view`):
        only atomic set / dict operations and `_Flag.set`. The request is left pending for a job not registered
        yet (`_begin` registers the job, then takes up a pending request) and dropped once it reached a running
        job; either order of the two ends with the job aborted."""
        self._abort_pending.add(serial)
        j = self._jobs.get(serial)
        if j is not None and j.state == "running":
            j.abort.set()
            self._abort_pending.discard(serial)

    def shutdown(self, timeout: float = SHUTDOWN_WAIT) -> None:
        """Service stop, BEFORE the printer connections close: stop every job (and the start-up restore) and wait
        up to `timeout` s for their restores."""
        self._closing.set()
        with self._lock:
            for j in self._jobs.values():
                if j.state == "running":
                    j.abort.set()
            threads = list(self._threads)
        deadline = time.monotonic() + timeout
        for t in threads:
            t.join(max(0.0, deadline - time.monotonic()))
            if t.is_alive():
                log.warning("mapping: %s still running at shutdown; its slots may keep test colours until the "
                            "next run", t.name)

    def running(self, serial: str) -> bool:
        """A job runs for `serial` in this process."""
        with self._lock:
            j = self._jobs.get(serial)
            return j is not None and j.state == "running"

    def in_progress(self, serial: str) -> bool:
        """A job runs for `serial` in this process or another one (`filament-kit printer map`)."""
        return self.running(serial) or _ProcessLock.held_elsewhere(serial)

    # ---------------------------------------------------------------- start-up restore
    def recover_pending(self, wait: float = RECOVER_WAIT) -> None:
        """Service start: for each printer with a pending slot snapshot (a job was killed), restore the slots from
        it once the printer is connected and idle (on a thread each; logged). Otherwise the next job does it."""
        for serial in snapshot.pending_serials():
            t = threading.Thread(target=self._recover, args=(serial, wait), name=f"mapping-recover-{serial}",
                                 daemon=True)
            t.start()
            with self._lock:
                self._threads.append(t)

    def _recover(self, serial: str, wait: float) -> None:
        deadline = time.monotonic() + wait
        while not self._closing.is_set():
            if self._m.state(serial) in slottest.ONLINE and \
                    self._m.wait_report(serial, lambda r: "gcode_state" in r, 0.5) is not None:
                break
            if time.monotonic() >= deadline:
                log.warning("mapping %s: a slot snapshot is pending but the printer did not connect; the next "
                            "mapping run restores it", serial)
                return
            self._closing.wait(0.5)
        if self._closing.is_set():
            return
        try:
            plock = _take_for_mapping(serial)
        except AlreadyRunning:
            log.info("mapping %s: busy; the pending slot snapshot is restored by the job", serial)
            return
        try:
            try:
                slottest.check_idle(self._m, serial)
            except (PrinterBusy, PrinterOffline) as e:
                log.warning("mapping %s: a slot snapshot is pending but the printer is not idle (%s); the next "
                            "mapping run restores it", serial, type(e).__name__)
                return
            log.info("mapping %s: restoring the slots a stopped mapping left (slot snapshot)", serial)
            _delete_leftover_job(serial)
            problems = snapshot.restore(self._m, serial)
            if problems:
                log.warning("mapping %s: restore from the slot snapshot not confirmed: %s", serial, problems)
                _distrust(serial)
            else:
                log.info("mapping %s: slots restored from the slot snapshot", serial)
        except Exception:
            log.exception("mapping %s: restore from the slot snapshot failed", serial)
        finally:
            _give_back(serial, plock)

    # ---------------------------------------------------------------- the job
    def _run(self, serial: str, job: _Job, plock: _ProcessLock, on_step) -> None:
        def step(text: str) -> None:
            job.step = text
            _save_status(serial, job)
            if on_step is not None:
                try:
                    on_step(text)
                except Exception:
                    log.exception("mapping %s: progress callback failed", serial)
        try:
            self._map(serial, job, step)
        except BaseException as e:            # a bug, or Ctrl-C / SystemExit: failed, never a trusted map
            log.exception("mapping %s: job failed", serial)
            job.state = "failed"
            job.problems.append(f"error: mapping failed ({type(e).__name__}: {e})")
            try:
                _distrust(serial)
            except Exception:
                log.exception("mapping %s: cannot downgrade the slot map", serial)
            if not isinstance(e, Exception):
                raise
        finally:
            if job.state == "running":   # defensive: never leave a finished job "running"
                job.state = "failed"
            job.finished = time.time()
            final = ("Mapping finished" if job.state == "done" else "Mapping failed")
            try:
                step(final)
            finally:
                try:
                    _give_back(serial, plock)
                finally:
                    job.released.set()
            log.info("mapping %s: job %s %s; problems %s", serial, job.id, job.state, job.problems)

    def _map(self, serial: str, job: _Job, step) -> None:
        def fail(problems: list[str]) -> None:
            job.problems = list(problems)
            job.state = "failed"
            _distrust(serial)

        if job.abort.is_set():
            return fail([STOPPED.split(";")[0] + "; nothing was changed"])
        fp = _fingerprint_now(self._m, serial)
        if snapshot.pending(serial):
            _delete_leftover_job(serial)
            probs = snapshot.restore(self._m, serial, step)
            if probs:
                return fail(["the slots an interrupted mapping changed could not all be restored, so nothing else "
                             "was done; check the slots on the printer and run the mapping again"] + probs)
        try:
            st = slottest.run(self._m, serial, step, should_stop=job.abort.is_set)
        except PrinterBusy as e:
            return fail([f"printer_busy: the printer started a job ({e}); nothing was changed"])
        except (PrinterOffline, UnknownPrinter):
            return fail(["printer_offline: the printer went offline; nothing was changed"])
        if not st.restored:
            step("The slot test could not put every slot back")
            return fail(st.problems or ["the slot test could not confirm that every slot was put back"])
        if job.abort.is_set():
            return fail([STOPPED] + list(st.problems))
        if not st.confirmed:
            return fail(st.problems or ["no slot was confirmed by the slot test"])

        model = ams.printer_model(serial)
        smap = ams.SlotMap(slots={lab: {"ams_id": a["ams_id"], "tray_id": a["tray_id"],
                                        "global_id": ams.default_global(a["ams_id"], a["tray_id"], model)}
                                  for lab, a in {**st.confirmed, **st.empty}.items()})
        step("Running the calibration job (no heating, no motion)")
        cr = calib3mf.run(self._m, serial, smap, should_stop=job.abort.is_set)
        problems = list(st.problems) + list(cr.problems)
        if job.abort.is_set():
            if not cr.restored:
                problems.append("the calibration could not confirm that every slot was put back")
            return fail([STOPPED] + problems)
        if cr.consistent and cr.restored:
            for lab, s in smap.slots.items():
                if lab in cr.decoding:
                    s["global_id"] = cr.decoding[lab]
                elif lab in cr.external:    # a holder keeps its own id, with or without a proven scheme
                    s["global_id"] = s["ams_id"]
                elif cr.scheme:     # a slot the job skipped (empty): the proven scheme's number
                    s["global_id"] = ams.scheme_global(s["ams_id"], s["tray_id"], cr.scheme, model)
                else:               # no scheme: a guess could be another slot's number, so none yet
                    s["global_id"] = None
            smap.calibrated, smap.observe, smap.scheme = True, False, cr.scheme
        else:
            smap.calibrated, smap.observe = False, True
            if not cr.restored:
                problems.append("the calibration could not confirm that every slot was put back")
            elif not cr.problems:
                problems.append("the calibration job did not confirm the slot numbering")
            problems.append(OBSERVE_NOTE)
        step("Saving the slot map")
        smap.fingerprint, smap.stale = fp, False
        ams.save_map(serial, smap)
        job.problems = problems
        job.notes = list(cr.notes)
        job.scheme_unsettled = cr.scheme_unsettled
        job.trail = list(cr.trail)
        report = self._m.wait_report(serial, lambda r: True, 0) or {}
        job.report_wanted = cr.report_wanted or _unrecognised(report, model)
        if job.report_wanted in printer_report.LOUD or not cr.consistent:     # kept here; the owner decides to share it
            self._save_report(serial, report, model, job)
        job.state = "done" if cr.restored else "failed"

    # ---------------------------------------------------------------- the printer report
    def _save_report(self, serial: str, report: dict, model, job: _Job) -> None:
        try:
            printer_report.save(serial, printer_report.build(report, model, trail=job.trail, wanted=job.report_wanted),
                                model)
        except OSError:
            log.exception("mapping %s: cannot save the printer report", serial)

    def report(self, serial: str) -> dict:
        """A report from the printer as it is now and the last mapping's attempts: {name, xml, path}. Raises
        PrinterOffline when there is no report to read."""
        snap = self._m.wait_report(serial, lambda r: True, 0)
        if snap is None:
            raise PrinterOffline(serial)
        model = ams.printer_model(serial)
        saved = _load_status(serial) or {}
        wanted = saved.get("report_wanted") or _unrecognised(snap, model)
        data = printer_report.build(snap, model, trail=saved.get("trail"), wanted=wanted)
        path = printer_report.save(serial, data, model)
        return {"name": path.name, "xml": data.decode("utf-8"), "path": str(path)}

    # ---------------------------------------------------------------- progress
    def view(self, serial: str) -> dict:
        """`{state, step, slots: [{label, ams_id, tray_id, global}], calibrated, observe, problems, notes,
        problems_old, finished, stale, remapping, scheme, suspect}`: `stale` = the printer's layout changed since the
        map was made; `remapping` = this process runs a re-map that `LayoutWatch` started (layout change or suspect
        map); `scheme` = the numbering scheme calibration proved (None: none yet); `suspect` = two prints in a row
        disagreed with the map (logging only until the re-map); `notes` = what a good result does not settle yet
        (not problems); `scheme_unsettled` = several numbering schemes fit and the model's first was taken, the reason
        to map again after loading a second unit (a client keys on this, never on a note's text); `report_wanted` =
        why a printer report would help (printer_report.WANTED), None when it wouldn't; `report_why` = that as a sentence;
        `kit` = the kit version that ran that job (None: a kit too old to say, or no job yet);
        `problems_old` = the problems are from a job an earlier server run finished, so an update or
        a fix since may have dealt with them: they say what happened then, not what is wrong now, and they never
        stop a new mapping; `finished` = when that job ended (epoch seconds, None: not known or still running)."""
        with self._lock:
            j = self._jobs.get(serial)
            mine = None if j is None else {"kit": __version__, "job_id": j.id, "state": j.state, "step": j.step,
                                           "problems": list(j.problems), "notes": list(j.notes),
                                           "scheme_unsettled": j.scheme_unsettled,
                                           "report_wanted": j.report_wanted, "trail": j.trail,
                                           "finished": j.finished}
        saved = _load_status(serial)
        # this process's own job is the truth unless the file holds a later job (run by another process); the
        # file can lag behind it (a status write that failed, or one not made yet)
        if mine is not None and (mine["state"] == "running" or saved is None or saved["job_id"] == mine["job_id"]):
            st = mine
        else:
            st = saved
            if st is not None and st["state"] == "running" and not _ProcessLock.held_elsewhere(serial):
                st = {**st, "state": "failed", "problems": st["problems"] + [INTERRUPTED]}
        m = ams.load_map(serial)
        slots = []
        for label, s in m.slots.items():
            if isinstance(s, dict):
                slots.append({"label": label, "ams_id": s.get("ams_id"), "tray_id": s.get("tray_id"),
                              "global": s.get("global_id")})
        st = st or {"state": "none", "step": "", "problems": []}
        remapping = bool(j is not None and j.auto and st is mine and st["state"] == "running")
        # finished before this server started (a `printer map` at the CLI just now is not old)
        ended = st.get("finished")
        old = (st is not mine and bool(st["problems"]) and (ended is None or ended < _STARTED)
               and not (st["state"] == "running" and _ProcessLock.held_elsewhere(serial)))
        return {"state": st["state"], "step": st["step"], "slots": slots, "calibrated": m.calibrated,
                "observe": m.observe, "problems": st["problems"], "notes": st.get("notes", []),
                "scheme_unsettled": st.get("scheme_unsettled", False),
                "report_wanted": st.get("report_wanted"), "report_why": printer_report.why(st.get("report_wanted")),
                "problems_old": old,
                "finished": st.get("finished"), "kit": st.get("kit"), "stale": m.stale, "remapping": remapping,
                "scheme": m.scheme, "suspect": m.suspect}


# ---------------------------------------------------------------- layout fingerprint: stale map, auto re-map

def _fingerprint_now(manager, serial: str) -> list | None:
    """The layout fingerprint of the printer's current report (None when there is none to read)."""
    try:
        r = manager.wait_report(serial, lambda r: True, 0)
    except Exception:  # noqa: BLE001 - a fake or a dropped printer: no fingerprint, never a failed job
        return None
    if not isinstance(r, dict) or not isinstance(status._d(r.get('ams')).get('ams'), list):
        return None
    return layout.build(r, ams.printer_model(serial)).fingerprint


_REMAP_REQUESTS: set[str] = set()
_REMAP_GUARD = threading.Lock()


def request_remap(serial: str) -> None:
    """Ask `LayoutWatch` to look at the printer's slot map again at its next report (`usage` marked it suspect):
    a stale or suspect map is re-mapped once the printer is idle. Cheap and safe from any thread."""
    with _REMAP_GUARD:
        _REMAP_REQUESTS.add(serial)


def _take_request(serial: str) -> bool:
    with _REMAP_GUARD:
        if serial in _REMAP_REQUESTS:
            _REMAP_REQUESTS.discard(serial)
            return True
        return False


def _merge_fp(old: list, new: list) -> list:
    """`new`, keeping a unit type `old` knew (from a module code) where `new` has none (same layout)."""
    return [[n[0], n[1] if n[1] is not None else o[1], n[2]] for o, n in zip(old, new)]


@dataclass
class _Seen:
    fp: list | None = None
    labels: frozenset | None = None
    since: float = 0.0
    pending: bool = False          # the saved map is stale: an automatic re-map may be due
    last_try: float | None = None
    tries: int = 0


class LayoutWatch:
    """A report listener (`Manager.add_listener`): keeps each printer's slot map in step with its hardware.

    On a layout change (`layout.same_layout` of the fingerprints: unit ids, slot counts, module-code types) the
    fingerprint saved in the slot map decides: a map made for other hardware is marked `stale` (`calibrated` and
    the slots stay: units that did not move keep their numbers), a map that matches again is un-marked, and an
    old map without a fingerprint adopts the current one. While stale, and with config `auto_remap` (default
    on), the mapper re-runs (`Mapper.start(serial, auto=True)`; the app shows re-mapping) once the printer is
    connected and idle, no job maps it already, and the new layout held for REMAP_SETTLE s; at most REMAP_TRIES
    attempts, REMAP_RETRY s apart, per layout change. A printer that was never mapped is left alone. A map `usage`
    marked `suspect` (two prints in a row disagreed with it; `request_remap`) is re-mapped the same way, with no
    layout change needed (and found at start from the saved map). Runs on the MQTT thread: the slot map is only
    read when the layout changes, a re-map was requested or one is due, and the job starts on a thread of its own
    (`sync=True`: in the caller's thread, for tests)."""

    def __init__(self, manager, mapper, *, clock=time.monotonic, settle: float = REMAP_SETTLE,
                 retry: float = REMAP_RETRY, sync: bool = False):
        self._m, self._mapper, self._clock = manager, mapper, clock
        self._settle, self._retry, self._sync = settle, retry, sync
        self._seen: dict[str, _Seen] = {}
        self._lock = threading.Lock()

    def _model(self, serial: str):
        fn = getattr(self._m, 'model', None)
        return fn(serial) if callable(fn) else ams.printer_model(serial)

    def __call__(self, serial: str, report: dict, first: bool) -> None:
        if not isinstance(status._d(status._d(report).get('ams')).get('ams'), list):
            return
        lay = layout.build(report, self._model(serial))
        fp = lay.fingerprint
        labels = frozenset(s.label for u in lay.units for s in u.slots)
        now = self._clock()
        with self._lock:
            seen = self._seen.setdefault(serial, _Seen())
            if seen.fp is not None and layout.same_layout(seen.fp, fp) and labels == seen.labels:
                merged = _merge_fp(seen.fp, fp)
                learned = merged != seen.fp            # a module code told a unit's type: remember it
                seen.fp, changed = merged, False
            else:
                seen.fp, seen.labels, changed, learned = fp, labels, True, False
                seen.since, seen.tries, seen.last_try = now, 0, None
            asked = _take_request(serial)
            if asked and not (changed or learned):
                seen.tries, seen.last_try = 0, None    # a new reason to re-map: a fresh set of attempts
            if changed or learned or asked:
                if self._mapper.in_progress(serial):
                    seen.fp = None             # look again once the job is over
                    if asked:
                        request_remap(serial)
                    return
                seen.pending = self._check_map(serial, seen.fp, labels)
            if seen.pending and self._due(serial, seen, report, now):
                seen.last_try, seen.tries = now, seen.tries + 1
                self._start(serial)

    def _check_map(self, serial: str, fp: list, labels=None) -> bool:
        """Compare with the saved map, marking it stale or not; True = a re-map is due (stale, or suspect). Stale:
        the map was made for other hardware (fingerprint), or one of its labels is not a slot of the current layout
        (a renamed label; keys under an older external label were already renamed by `ams.load_map`)."""
        m = ams.load_map(serial)
        if not m.slots:
            return False
        same = m.fingerprint is None or layout.same_layout(m.fingerprint, fp)
        missing = sorted(k for k in m.slots if labels is not None and k not in labels)
        stale = not same or bool(missing)
        if m.fingerprint is None:
            new_fp = fp
            log.info("mapping %s: the slot map adopted the printer's current layout", serial)
        else:
            new_fp = _merge_fp(m.fingerprint, fp) if same else m.fingerprint
        if new_fp == m.fingerprint and stale == m.stale:
            return stale or m.suspect
        if stale and not m.stale:
            log.warning("mapping %s: the slot map is stale (%s)", serial,
                        "the printer's AMS layout changed" if not same else f"no slot {', '.join(missing)} now")
        m.fingerprint, m.stale = new_fp, stale
        try:
            ams.save_map(serial, m)
        except OSError:
            log.exception("mapping %s: cannot save the slot map", serial)
        return m.stale or m.suspect

    def _due(self, serial: str, seen: _Seen, report: dict, now: float) -> bool:
        if seen.tries >= REMAP_TRIES or now - seen.since < self._settle:
            return False
        if seen.last_try is not None and now - seen.last_try < self._retry:
            return False
        gs = status._s(status._d(report).get('gcode_state'))
        if not gs or gs == 'UNKNOWN' or gs in status.ACTIVE:
            return False
        if self._m.state(serial) not in slottest.ONLINE or self._mapper.in_progress(serial):
            return False
        if not config.load().get('auto_remap', True):
            seen.last_try = now                  # off: look at the config again a retry interval later
            return False
        m = ams.load_map(serial)
        if not (m.stale or m.suspect):           # a job (manual or ours) already made a fresh map
            seen.pending = False
            return False
        return True

    def _start(self, serial: str) -> None:
        def go():
            try:
                self._mapper.start(serial, auto=True)
                log.info("mapping %s: re-mapping, the AMS layout changed", serial)
            except Exception as e:  # noqa: BLE001 - busy, offline, a load running: tried again later
                log.warning("mapping %s: automatic re-map not started (%s: %s)", serial, type(e).__name__, e)
        if self._sync:
            go()
        else:
            threading.Thread(target=go, name=f"remap-{serial}", daemon=True).start()
