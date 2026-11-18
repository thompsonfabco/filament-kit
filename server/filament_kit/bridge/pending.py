"""Pending slot assignments: an assignment for a slot that is not clearly loaded waits for the filament.

The AMS wipes a slot's setting when filament goes in, so a setting sent to an empty slot (or one whose presence is
not known) is lost. `load_or_wait` (the kit's slot load route, so the app, the web app and the MCP tools) sends at
once only when the slot reports a filament; otherwise the preset is checked with a dry run and the assignment waits
here, in memory (a restart drops it), until the slot is present and read, SETTLE s more, then it is sent. The job
then keeps watching: when the AMS wipes the slot again (type empty) it is sent again, up to MAX_SENDS in all.

Ends (one log line each: pending / applied / dropped):
- TTL (15 min) after it was made;
- a newer assignment for the same slot (loaded at once or waiting) replaces it;
- the slot is unloaded or cleared (`unload`, `clear_slot`);
- the slot loads with a spool whose own RFID identifies it (`rfid`): that is not overridden;
- after it was applied: the filament is taken out, or another setting is on the slot (the user set it);
- a refusal waiting does not change (no preset, unknown spool, write refused).
Externals have no sensor (presence follows the setting), so they are sent at once as before, and so is every slot
of a printer whose presence layout is unknown (`presence` "tray_type": `present` is never True for an empty-typed
slot, so a wait could not end). A slot whose presence is unknown on a printer with a layout waits.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from . import loading

log = logging.getLogger(__name__)

TTL = 900.0                  # seconds an assignment waits for the filament (and watches the slot after it)
SETTLE = 3.0                 # seconds the slot must stay loaded and read before the first send
POLL = 2.0                   # seconds between checks
MAX_SENDS = 5                # sends of one assignment, the first included
FINAL = (loading.NoPreset, loading.NotFound, loading.SlotWriteFailed)   # waiting does not change these
EXT_KIND = "ext"


@dataclass
class Job:
    manager: object
    sm: object
    spool_id: int
    at: float
    load_kw: dict = field(default_factory=dict)      # extra arguments of loading.load
    preset_id: str | None = None                     # the preset of the last send
    seen: float | None = None
    sends: int = 0
    applied: bool = False
    waiting: str | None = None


def slot_view(manager, serial: str, label: str) -> tuple[dict, str] | None:
    """(slot of the printer's status, its unit's kind) for `label`, None when the printer gives no status."""
    st = manager.status(serial)
    if not st:
        return None
    for u in st.get("ams") or []:
        for sl in u.get("slots") or []:
            if sl.get("label") == label:
                return sl, str(u.get("kind") or "")
    return None


def is_loaded(sl: dict, kind: str) -> bool:
    """The slot is clearly loaded and read: send. Unknown counts as not loaded; externals have no sensor."""
    if kind == EXT_KIND:
        return True
    return sl.get("present") is True and sl.get("reading") is not True


class Store:
    """The waiting assignments, keyed (printer serial, slot label); in memory only."""

    def __init__(self, clock=time.monotonic, *, start_thread: bool = True):
        self.clock = clock
        self._start_thread = start_thread
        self._jobs: dict[tuple[str, str], Job] = {}
        self._lock = threading.Lock()
        self._sends: dict[tuple[str, str], threading.Lock] = {}
        self._thread: threading.Thread | None = None

    # --- the API ---

    def add(self, manager, sm, serial: str, label: str, spool_id, **kw) -> None:
        """Wait for the filament in `label`; replaces any older assignment of that slot."""
        key = (serial, label)
        with self._send_lock(key), self._lock:
            old = self._jobs.get(key)
            self._jobs[key] = Job(manager, sm, int(spool_id), self.clock(), kw)
        log.info("pending %s %s spool %s: waiting for the filament to load%s", serial, label, spool_id,
                 f" (replaces spool {old.spool_id})" if old is not None else "")
        self._ensure_thread()

    def cancel(self, serial: str, label: str, why: str = "a newer assignment") -> bool:
        """Forget the assignment of that slot; a send of it in progress finishes first."""
        key = (serial, label)
        with self._send_lock(key), self._lock:
            job = self._jobs.pop(key, None)
        if job is not None:
            log.info("dropped %s %s spool %s: %s", serial, label, job.spool_id, why)
        return job is not None

    def jobs(self) -> dict[tuple[str, str], Job]:
        with self._lock:
            return dict(self._jobs)

    def waiting_for(self, serial: str) -> dict[str, int]:
        """label -> spool id of the assignments of that printer not yet applied."""
        with self._lock:
            return {k[1]: j.spool_id for k, j in self._jobs.items() if k[0] == serial and not j.applied}

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()

    # --- the watcher ---

    def _send_lock(self, key) -> threading.Lock:
        with self._lock:
            return self._sends.setdefault(key, threading.Lock())

    def _ensure_thread(self) -> None:
        if not self._start_thread:
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="pending-assign", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            time.sleep(POLL)
            self.tick()

    def tick(self) -> None:
        for key, job in self.jobs().items():
            try:
                self._process(key, job)
            except Exception as e:  # noqa: BLE001 - one bad job must not stop the others; it expires
                self._wait(key, job, type(e).__name__, f"{type(e).__name__}: {e}")

    def _wait(self, key, job: Job, reason: str, text: str) -> None:
        """Keep the job; log only when the reason it waits for changes (no line every POLL seconds)."""
        if job.waiting != reason:
            job.waiting = reason
            log.warning("pending %s %s spool %s waits: %s", key[0], key[1], job.spool_id, text)

    def _end(self, key, job: Job, why: str) -> None:
        with self._lock:
            if self._jobs.get(key) is not job:
                return
            self._jobs.pop(key)
        log.info("dropped %s %s spool %s: %s", key[0], key[1], job.spool_id, why)

    def _process(self, key, job: Job) -> None:
        serial, label = key
        now = self.clock()
        if now - job.at > TTL:
            return self._end(key, job, "the filament was not loaded within 15 min" if not job.applied
                             else "15 min watched, done")
        found = slot_view(job.manager, serial, label)
        if found is None:
            return                                   # no status (offline): keep waiting
        sl, kind = found
        if sl.get("present") is True and sl.get("rfid"):
            return self._end(key, job, "the loaded spool's own RFID identifies it, not overridden")
        if job.applied:
            return self._watch(key, job, sl, kind, now)
        if not is_loaded(sl, kind):
            job.seen = None
            return
        if job.seen is None:
            job.seen = now                           # just detected: let the AMS finish its own reset first
            return
        if now - job.seen < SETTLE:
            return
        self._send(key, job)

    def _watch(self, key, job: Job, sl: dict, kind: str, now: float) -> None:
        """After a send: send again when the AMS wipes the slot (present, no type); end when it is emptied or
        another setting is on it."""
        if kind != EXT_KIND and sl.get("present") is False:
            return self._end(key, job, "the filament was taken out")
        if sl.get("reading") is True or (sl.get("present") is None and kind != EXT_KIND):
            return
        if sl.get("type"):
            if sl.get("preset_id") != job.preset_id:
                return self._end(key, job, f"another setting is on the slot ({sl.get('type')} {sl.get('preset_id')})")
            return
        if job.sends >= MAX_SENDS:
            return self._end(key, job, f"the printer did not keep the setting after {MAX_SENDS} sends")
        self._send(key, job)

    def _send(self, key, job: Job) -> None:
        serial, label = key
        with self._send_lock(key):
            with self._lock:
                if self._jobs.get(key) is not job:
                    return                           # replaced or cancelled meanwhile: stale, not sent
            try:
                r = loading.load(job.manager, job.sm, serial, label, job.spool_id, False, **job.load_kw)
            except FINAL as e:
                return self._end(key, job, f"refused: {e}")
            except Exception as e:  # noqa: BLE001 - busy, offline, slot in use ...: not a send, try again
                return self._wait(key, job, type(e).__name__, f"{type(e).__name__}: {e}")
            job.waiting = None
            job.sends += 1
            p = (r or {}).get("preset") or {}
            job.preset_id = p.get("filament_id")
            if not job.applied:
                job.applied = True
                log.info("applied %s %s spool %s: %s%s", serial, label, job.spool_id, p.get("name"),
                         "" if (r or {}).get("confirmed") else " (not confirmed yet)")
            else:
                log.info("applied again %s %s spool %s (the slot was wiped)", serial, label, job.spool_id)


STORE = Store()


def load_or_wait(manager, sm, serial: str, label: str, spool_id, dry: bool, *, store: Store | None = None,
                 **kw) -> dict:
    """`loading.load`, except that a real load of a slot that is not clearly loaded waits (see the module doc):
    the reply is the dry-run plan with `pending: true`, `confirmed: null` and a `message`; nothing was sent and
    Spoolman is unchanged. A load that goes at once cancels the slot's older waiting assignment."""
    store = store or STORE
    if dry:
        return loading.load(manager, sm, serial, label, spool_id, True, **kw)
    if (manager.status(serial) or {}).get("presence") == "tray_type":
        store.cancel(serial, loading._label(serial, label))     # no presence sensor: present can never show
        return loading.load(manager, sm, serial, label, spool_id, False, **kw)    # loaded, so send at once
    lab = loading._label(serial, label)
    found = slot_view(manager, serial, lab)
    if found is not None and is_loaded(*found):
        store.cancel(serial, lab)
        return loading.load(manager, sm, serial, label, spool_id, False, **kw)
    plan = loading.load(manager, sm, serial, label, spool_id, True, **kw)     # the same refusals as a real load
    store.add(manager, sm, serial, lab, spool_id, **kw)
    return {**plan, "dry_run": False, "pending": True, "confirmed": None,
            "message": f"waiting for the spool to load in slot {lab}"}


def _end_for(serial: str, label: str, dry: bool, why: str, store: Store) -> bool:
    """End the slot's assignment (a dry run: leave it); True when one was still waiting for its filament. An
    applied one that is only watched the slot ends too, but is not "waiting"."""
    waiting = label in store.waiting_for(serial)
    if not dry:
        store.cancel(serial, label, why)
    return waiting


def unload(manager, sm, serial: str, label: str, dry: bool, *, store: Store | None = None, **kw) -> dict:
    """`loading.unload`, which also ends the slot's waiting assignment: the result gains `waiting_ended` (on a dry
    run: the assignment would end)."""
    store = store or STORE
    lab = loading._label(serial, label)
    r = loading.unload(manager, sm, serial, label, dry, **kw)
    ended = _end_for(serial, lab, dry, "the slot was unloaded", store)
    return {**r, "waiting_ended": ended}


def clear_slot(manager, sm, serial: str, label: str, dry: bool, *, store: Store | None = None, **kw) -> dict:
    """Clear slot `label` (`loading.clear`): a waiting assignment for it ends, then the recorded spool goes back
    where it was. The answer of the kit route (`loading.clear_view`). A refused clear (slot in use) ends nothing."""
    store = store or STORE
    lab = loading._label(serial, label)
    r = loading.clear(manager, sm, serial, label, dry, **kw)
    ended = _end_for(serial, lab, dry, "the slot was cleared", store)
    return loading.clear_view(r, ended)


def annotate(serial: str, st: dict | None, store: Store | None = None) -> dict | None:
    """Add `pending` {spool_id, text} to the slots of a printer status that wait for their filament."""
    waiting = (store or STORE).waiting_for(serial)
    if not st or not waiting:
        return st
    for u in st.get("ams") or []:
        for sl in u.get("slots") or []:
            if sl.get("label") in waiting:
                sl["pending"] = {"spool_id": waiting[sl["label"]],
                                 "text": f"waiting for the spool to load in slot {sl['label']}"}
    return st
