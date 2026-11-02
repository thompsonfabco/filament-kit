"""Slot mapping: the slot test (`slottest.run`) then the calibration job (`calib3mf.run`) as one job per printer.

`Mapper.start(serial)` runs it on a background thread (the API), `Mapper.run(serial, on_step)` in the caller's
thread (the CLI). One job per printer at a time (`AlreadyRunning`, also across processes on Linux through a lock
file), refused before anything is touched unless the printer is in the registry (`UnknownPrinter`), its leaf
matches the pin (state `cert_changed` -> `CertChanged`), connected (`PrinterOffline`) and idle (`PrinterBusy`).

Outcome:
  - slot test could not put every slot back -> `failed`, problems name each slot; nothing saved, the slot map
    stays as it was; also `failed` when no slot was confirmed (offline, busy, Developer Mode ...);
  - calibration consistent -> SlotMap of the confirmed slots, global ids from the calibration's decoding (a
    confirmed slot the calibration skipped, i.e. an empty one, keeps `ams.default_global`, which the decoding
    just proved for the loaded ones), `calibrated: true, observe: false`;
  - calibration inconsistent or refused -> the same slots, default global ids, `calibrated: false, observe:
    true` (filament use is only logged), the reason in problems;
  - a calibration that could not restore a slot -> the map is saved as above, but the job is `failed`.
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
from dataclasses import dataclass, field
from typing import Callable

from .. import config
from ..pairing import _write_atomic, make_state_dir, open_lock
from . import ams, calib3mf, registry, slottest
from .connection import PrinterOffline, UnknownPrinter
from .slottest import PrinterBusy

try:
    import fcntl
except ImportError:  # Windows dev PCs: one process only (the service runs on Linux)
    fcntl = None

log = logging.getLogger(__name__)

STATUS_FILE = "mapping.json"
LOCK_FILE = "mapping.lock"
INTERRUPTED = "the mapping was interrupted (the server or command stopped); run it again"
OBSERVE_NOTE = "slot numbering not confirmed: filament use is only logged until mapping succeeds"


class AlreadyRunning(Exception):
    """A mapping job is already running for this printer."""


class CertChanged(Exception):
    """The printer's certificate changed (state `cert_changed`): nothing is sent until it is added again."""


@dataclass
class _Job:
    id: str
    state: str = "running"          # running | done | failed
    step: str = "Starting"
    problems: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    finished: float | None = None


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


class _ProcessLock:
    """The per-printer lock file, held for the whole job (flock, so a crashed process releases it)."""

    def __init__(self, serial: str):
        self.fh = None
        if fcntl is None:
            return
        d = _dir(serial)
        make_state_dir(d)
        fh = open_lock(d / LOCK_FILE)
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
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
        if fcntl is None:
            return False
        f = _dir(serial) / LOCK_FILE
        if not f.exists():
            return False
        try:
            with open(f, "a") as fh:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return True
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            return False
        return False


def check_ready(manager, serial: str) -> None:
    """Raise UnknownPrinter / CertChanged / PrinterOffline / PrinterBusy unless mapping may start now."""
    if registry.load().get(serial) is None:
        raise UnknownPrinter(serial)
    if manager.state(serial) == "cert_changed":
        raise CertChanged(serial)
    slottest.check_idle(manager, serial)


def _restore_failed(problems: list[str]) -> bool:
    """calib3mf reports slots it could not put back as sentences that all mention "restore"."""
    return any("restore" in p for p in problems)


class Mapper:
    def __init__(self, manager):
        self._m = manager
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}

    # ---------------------------------------------------------------- start / run
    def _begin(self, serial: str) -> tuple[_Job, _ProcessLock]:
        if registry.load().get(serial) is None:
            raise UnknownPrinter(serial)
        with self._lock:
            j = self._jobs.get(serial)
            if j is not None and j.state == "running":
                raise AlreadyRunning(serial)
            plock = _ProcessLock(serial)
            try:
                check_ready(self._m, serial)
            except BaseException:
                plock.release()
                raise
            job = _Job(uuid.uuid4().hex)
            self._jobs[serial] = job
        _save_status(serial, job)
        log.info("mapping %s: job %s started", serial, job.id)
        return job, plock

    def start(self, serial: str) -> str:
        """Start the job on a background thread; returns its id."""
        job, plock = self._begin(serial)
        t = threading.Thread(target=self._run, args=(serial, job, plock, None), name=f"mapping-{serial}",
                             daemon=True)
        t.start()
        return job.id

    def run(self, serial: str, on_step: Callable[[str], None] | None = None) -> dict:
        """Run the job here, telling `on_step(text)` each step; returns `view(serial)`."""
        job, plock = self._begin(serial)
        self._run(serial, job, plock, on_step)
        return self.view(serial)

    def running(self, serial: str) -> bool:
        with self._lock:
            j = self._jobs.get(serial)
            return j is not None and j.state == "running"

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
        except Exception as e:
            log.exception("mapping %s: job failed", serial)
            job.state = "failed"
            job.problems.append(f"error: mapping failed ({type(e).__name__}: {e})")
        finally:
            if job.state == "running":   # defensive: never leave a finished job "running"
                job.state = "failed"
            job.finished = time.time()
            final = ("Mapping finished" if job.state == "done" else "Mapping failed")
            try:
                step(final)
            finally:
                plock.release()
            log.info("mapping %s: job %s %s; problems %s", serial, job.id, job.state, job.problems)

    def _map(self, serial: str, job: _Job, step) -> None:
        def fail(problems: list[str]) -> None:
            job.problems = list(problems)
            job.state = "failed"

        try:
            st = slottest.run(self._m, serial, step)
        except PrinterBusy as e:
            return fail([f"printer_busy: the printer started a job ({e}); nothing was changed"])
        except (PrinterOffline, UnknownPrinter):
            return fail(["printer_offline: the printer went offline; nothing was changed"])
        if not st.restored:
            step("The slot test could not put every slot back")
            return fail(st.problems or ["the slot test could not confirm that every slot was put back"])
        if not st.confirmed:
            return fail(st.problems or ["no slot was confirmed by the slot test"])

        smap = ams.SlotMap(slots={lab: {"ams_id": a["ams_id"], "tray_id": a["tray_id"],
                                        "global_id": ams.default_global(a["ams_id"], a["tray_id"])}
                                  for lab, a in st.confirmed.items()})
        step("Running the calibration job (no heating, no motion)")
        cr = calib3mf.run(self._m, serial, smap)
        problems = list(st.problems) + list(cr.problems)
        if cr.consistent:
            for lab, s in smap.slots.items():
                if lab in cr.decoding:
                    s["global_id"] = cr.decoding[lab]
            smap.calibrated, smap.observe = True, False
        else:
            smap.calibrated, smap.observe = False, True
            if not cr.problems:
                problems.append("the calibration job did not confirm the slot numbering")
            problems.append(OBSERVE_NOTE)
        step("Saving the slot map")
        ams.save_map(serial, smap)
        job.problems = problems
        job.state = "failed" if _restore_failed(cr.problems) else "done"

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
