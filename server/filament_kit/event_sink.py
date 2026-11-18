"""The event sink: where the code that changes things reports what happened (R80 E1).

`inventory.py`, the loading code, the usage code and the watcher never call the event store themselves: they call
`emit(...)`, which hands the event to the sink in force. In the Hub the sink is the store (`StoreSink`), in the
command line as root also the store, and in the web unit the hand-over to the Hub (EA4 gives it with `set_sink`).
Until a sink is given nothing is written (`NullSink`): code that runs in a short-lived process or a test needs no
event store. A sink never raises into the code that reports to it: an event that cannot be written is logged and
dropped (a spool change must not fail because its history could not be kept).

Who did it (`actor`) and which request it was part of (`batch`) are set by whoever handles the request, once, with
`with acting({"type": "page"}): ...`; spool events written inside carry that actor and one `batch` value (R80 E5).
Without it the actor is the Hub itself. `runs` keeps the `run` value of each printer's print run (R80 E5).
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import secrets
import threading

from . import events

log = logging.getLogger("filament_kit.event_sink")

HUB = {"type": "hub"}
_actor: contextvars.ContextVar = contextvars.ContextVar("event_actor", default=None)
_batch: contextvars.ContextVar = contextvars.ContextVar("event_batch", default=None)


class NullSink:
    """Writes nothing."""

    def write(self, kind, subject, actor=None, data=None, **kw):
        return None

    def next_id(self) -> int:
        return 0

    def is_raised(self, key: str) -> bool:
        return False

    def conditions(self) -> list:
        return []


class StoreSink(NullSink):
    """The event store itself (the Hub, and the command line as root): errors are logged, never raised."""

    def __init__(self, store=None):
        self.store = store if store is not None else events.store()

    def write(self, kind, subject, actor=None, data=None, **kw):
        try:
            return self.store.write(kind, subject, actor or current_actor(), data, **kw)
        except (events.EventError, OSError) as e:
            log.warning("event %s not written: %s", kind, e)
            return None

    def next_id(self) -> int:
        try:
            return self.store.last_id() + 1
        except (events.EventError, OSError):
            return 0

    def is_raised(self, key: str) -> bool:
        try:
            return self.store.is_raised(key)
        except (events.EventError, OSError):
            return False

    def conditions(self) -> list:
        try:
            return self.store.conditions()
        except (events.EventError, OSError):
            return []


_sink = NullSink()


def set_sink(sink) -> None:
    """Give the sink in force (None: nothing is written)."""
    global _sink
    _sink = sink if sink is not None else NullSink()


def sink():
    return _sink


_held: contextvars.ContextVar = contextvars.ContextVar("event_held", default=None)


@contextlib.contextmanager
def held():
    """Events emitted inside this block are kept and written, in order, when the OUTERMOST block ends: the code that
    reports from under a lock (inventory's `_LOCK`) takes the lock INSIDE this block, so the store's write (it costs
    O(month)) never lengthens the time the lock is held (R475 LOW 4). Actor and batch are taken when `emit` is called."""
    if _held.get() is not None:
        yield
        return
    queue: list = []
    token = _held.set(queue)
    try:
        yield
    finally:
        _held.reset(token)
        for kind, subject, actor, data, kw in queue:
            _write(kind, subject, actor, data, kw)


def _write(kind, subject, actor, data, kw):
    try:
        return _sink.write(kind, subject, actor, data, **kw)
    except Exception:  # noqa: BLE001
        log.exception("event %s not written", kind)
        return None


_weight_hook = None


def set_weight_hook(fn) -> None:
    """The Hub gives a function that checks spools for running low; `weight_changed` calls it with Spoolman."""
    global _weight_hook
    _weight_hook = fn


def weight_changed(sm) -> None:
    """A spool's weight was changed by the Hub: check running low right away (R80 section 7). Never raises."""
    if _weight_hook is not None:
        try:
            _weight_hook(sm)
        except Exception:  # noqa: BLE001 - a spool change must not fail because the check did
            log.exception("running-low check after a weight change failed")


def current_actor() -> dict:
    return _actor.get() or HUB


def new_batch() -> str:
    return "b-" + secrets.token_hex(4)


@contextlib.contextmanager
def acting(actor: dict | str | None = None, batch: str | None = None):
    """Events written inside this block (in this thread or task) have `actor`, and the spool events of one request
    share `batch` (a given id, else a new one)."""
    a = _actor.set({"type": actor} if isinstance(actor, str) else actor)
    b = _batch.set(batch or _batch.get() or new_batch())
    try:
        yield
    finally:
        _batch.reset(b)
        _actor.reset(a)


@contextlib.contextmanager
def batch_scope():
    """One batch for what happens inside: the request's own when `acting` set one, else a new one for this call."""
    if _batch.get():
        yield _batch.get()
        return
    b = _batch.set(new_batch())
    try:
        yield _batch.get()
    finally:
        _batch.reset(b)


def current_batch() -> str:
    return _batch.get() or ""


def emit(kind: str, subject, data: dict | None = None, *, actor=None, **kw):
    """Report an event to the sink in force; returns the event or None. `actor` defaults to the one `acting` set.
    Never raises: whatever the sink does, the change that reported goes on."""
    actor = actor or current_actor()
    if _held.get() is not None:                         # under a lock: written when the lock is released (`held`)
        _held.get().append((kind, subject, actor, data, kw))
        return None
    return _write(kind, subject, actor, data, kw)


def spool_subject(spool: dict | None, spool_id=None) -> dict:
    """The subject of a spool event: id and its name at that time ("<brand> <filament>")."""
    spool = spool or {}
    f = spool.get("filament") or {}
    name = " ".join(x for x in ((f.get("vendor") or {}).get("name"), f.get("name")) if x)
    sid = spool.get("id") if spool.get("id") is not None else spool_id
    return {"type": "spool", "id": "" if sid is None else str(sid), "name": name}


def emit_spool(kind: str, spool: dict | None, spool_id=None, **values) -> None:
    """A spool event (`spool.moved` ...): the values are `spool`, `before_*` and `after_*` (None ones are left out),
    and the request's `batch`."""
    s = spool_subject(spool, spool_id)
    data = {"spool": s["id"], **{k: v for k, v in values.items() if v is not None}}
    if current_batch():
        data["batch"] = current_batch()
    emit(kind, s, data)


class RunBook:
    """The `run` value of each printer's print run (R80 E5): made when the first event of the run is written
    (`r-<id the first event gets>`; the guess is the next id, which is the id unless another writer was first by a
    hair, and every event of the run carries the same value either way). The run stays known after it ends, for the
    `usage.recorded` that settles later."""

    def __init__(self):
        self._lock = threading.Lock()
        self._runs: dict[str, dict] = {}

    def begin(self, printer: str, job: str = "") -> str:
        run = f"r-{_sink.next_id() or secrets.token_hex(3)}"
        with self._lock:
            self._runs[printer] = {"run": run, "job": job, "open": True}
        return run

    def current(self, printer: str) -> str:
        with self._lock:
            r = self._runs.get(printer)
            return r["run"] if r and r["open"] else ""

    def end(self, printer: str) -> None:
        with self._lock:
            if printer in self._runs:
                self._runs[printer]["open"] = False

    def last(self, printer: str, job: str | None = None) -> str:
        """The latest run of the printer, open or ended; with `job`, only when it is that job's."""
        with self._lock:
            r = self._runs.get(printer)
            return r["run"] if r and (job is None or r["job"] == job) else ""

    def forget(self, printer: str) -> None:
        with self._lock:
            self._runs.pop(printer, None)


runs = RunBook()
