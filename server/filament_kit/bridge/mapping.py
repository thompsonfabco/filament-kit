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
  - calibration consistent -> SlotMap of the confirmed slots, global ids from the calibration's decoding (a
    confirmed slot the calibration skipped, i.e. an empty one, keeps `ams.default_global`, which the decoding
    just proved for the loaded ones), `calibrated: true, observe: false`;
  - calibration inconsistent or refused -> the same slots, default global ids, `calibrated: false, observe:
    true` (filament use is only logged), the reason in problems;
  - a calibration that could not restore a slot (`CalibResult.restored` false) -> `failed`, the map saved
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

from .. import config
from ..pairing import _write_atomic, make_state_dir, open_lock
from . import ams, calib3mf, registry, slottest, snapshot
from .connection import PrinterOffline, UnknownPrinter
from .slottest import PrinterBusy

try:
    import fcntl
except ImportError:  # Windows dev PCs: one process only (the service runs on Linux)
    fcntl = None

log = logging.getLogger(__name__)

STATUS_FILE = "mapping.json"
LOCK_FILE = "mapping.lock"
INTERRUPTED = ("the mapping was interrupted (the server or command stopped); the slots may still hold test "
               "colours: the next run restores them first, so run it again")
OBSERVE_NOTE = "slot numbering not confirmed: filament use is only logged until mapping succeeds"
STOPPED = "mapping was stopped (the server or command is stopping); the slots were put back first"
SHUTDOWN_WAIT = 60.0      # seconds the service waits at shutdown for a stopped job's restore
RECOVER_WAIT = 60.0       # seconds the service waits at start for a printer with a pending snapshot to connect


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
    started: float = field(default_factory=time.time)
    finished: float | None = None
    abort: _Flag = field(default_factory=_Flag)


def _dir(serial: str):
    return config.paths().state / "printers" / serial


def _save_status(serial: str, job: _Job) -> None:
    try:
        d = _dir(serial)
        make_state_dir(d)
        data = {"job_id": job.id, "state": job.state, "step": job.step, "problems": job.problems,
                "started": job.started, "finished": job.finished}
        _write_atomic(d / STATUS_FILE, json.dumps(data, indent=2).encode("utf-8"), 0o600, state_owned=True)
    except OSError:
        log.exception("mapping %s: cannot write the status file", serial)


def _load_status(serial: str) -> dict | None:
    try:
        d = json.loads((_dir(serial) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("state") not in ("running", "done", "failed"):
        return None
    probs = d.get("problems")
    return {"job_id": str(d.get("job_id") or ""), "state": d["state"], "step": str(d.get("step") or ""),
            "problems": [str(p) for p in probs] if isinstance(probs, list) else []}


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
    def _begin(self, serial: str) -> tuple[_Job, _ProcessLock]:
        if registry.load().get(serial) is None:
            raise UnknownPrinter(serial)
        with self._lock:
            j = self._jobs.get(serial)
            if j is not None and j.state == "running":
                raise AlreadyRunning(serial)
            plock = _take_for_mapping(serial)
            try:
                check_ready(self._m, serial)
            except BaseException:
                _give_back(serial, plock)
                raise
            job = _Job(uuid.uuid4().hex)
            self._jobs[serial] = job        # registered first: an abort from now on reaches it directly
            if self._closing.is_set() or serial in self._abort_pending:
                self._abort_pending.discard(serial)
                job.abort.set()
        _save_status(serial, job)
        log.info("mapping %s: job %s started", serial, job.id)
        return job, plock

    def start(self, serial: str) -> str:
        """Start the job on a background thread; returns its id."""
        job, plock = self._begin(serial)
        t = threading.Thread(target=self._run, args=(serial, job, plock, None), name=f"mapping-{serial}",
                             daemon=True)
        try:
            t.start()
        except BaseException as e:            # no thread: the job never ran, and must not hold the printer
            job.state, job.finished = "failed", time.time()
            job.problems.append(f"error: the mapping job could not start ({type(e).__name__}: {e})")
            _save_status(serial, job)
            _give_back(serial, plock)
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
                _give_back(serial, plock)
            log.info("mapping %s: job %s %s; problems %s", serial, job.id, job.state, job.problems)

    def _map(self, serial: str, job: _Job, step) -> None:
        def fail(problems: list[str]) -> None:
            job.problems = list(problems)
            job.state = "failed"
            _distrust(serial)

        if job.abort.is_set():
            return fail([STOPPED.split(";")[0] + "; nothing was changed"])
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

        smap = ams.SlotMap(slots={lab: {"ams_id": a["ams_id"], "tray_id": a["tray_id"],
                                        "global_id": ams.default_global(a["ams_id"], a["tray_id"])}
                                  for lab, a in st.confirmed.items()})
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
            smap.calibrated, smap.observe = True, False
        else:
            smap.calibrated, smap.observe = False, True
            if not cr.restored:
                problems.append("the calibration could not confirm that every slot was put back")
            elif not cr.problems:
                problems.append("the calibration job did not confirm the slot numbering")
            problems.append(OBSERVE_NOTE)
        step("Saving the slot map")
        ams.save_map(serial, smap)
        job.problems = problems
        job.state = "done" if cr.restored else "failed"

    # ---------------------------------------------------------------- progress
    def view(self, serial: str) -> dict:
        """`{state, step, slots: [{label, ams_id, tray_id, global}], calibrated, observe, problems}`."""
        with self._lock:
            j = self._jobs.get(serial)
            mine = None if j is None else {"job_id": j.id, "state": j.state, "step": j.step,
                                           "problems": list(j.problems)}
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
        return {"state": st["state"], "step": st["step"], "slots": slots, "calibrated": m.calibrated,
                "observe": m.observe, "problems": st["problems"]}
