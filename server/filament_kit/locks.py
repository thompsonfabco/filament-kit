"""Locks shared by threads and processes (merge-ops: the `server` and `web` processes write the same inventory).

`ProcessLock` = a `threading.RLock` (threads of one process) plus `fcntl.flock` on a file in the state directory
(other processes). It is re-entrant within a thread, like the RLock it replaces: the file is locked by the
outermost acquire only, since a second flock on a new descriptor in the same process would wait on itself.
Where fcntl is missing (Windows dev PCs) only the in-process part works, as `profiles.builds._locked` does.
"""
from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Callable

try:
    import fcntl
except ImportError:  # Windows: tests only
    fcntl = None

from .pairing import make_state_dir, open_lock

_POLL = 0.05


class ProcessLock:
    """`path` is a Path or a callable giving one (so FK_STATE is read at lock time, not import time)."""

    def __init__(self, path: Path | Callable[[], Path]):
        self._path = path
        self._rlock = threading.RLock()
        self._depth = 0          # guarded by _rlock: only the holding thread touches it
        self._fh = None

    def path(self) -> Path:
        return Path(self._path() if callable(self._path) else self._path)

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        deadline = None if not blocking or timeout is None or timeout < 0 else time.monotonic() + timeout
        if not (self._rlock.acquire(blocking, timeout) if blocking else self._rlock.acquire(False)):
            return False
        if self._depth == 0 and fcntl is not None:
            try:
                if not self._lock_file(blocking, deadline):
                    self._rlock.release()
                    return False
            except BaseException:
                self._rlock.release()
                raise
        self._depth += 1
        return True

    def _lock_file(self, blocking: bool, deadline: float | None) -> bool:
        path = self.path()
        make_state_dir(path.parent)
        fh = open_lock(path)
        try:
            if blocking and deadline is None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            else:
                while True:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if not blocking or time.monotonic() >= deadline:
                            fh.close()
                            return False
                        time.sleep(_POLL)
        except BaseException:
            fh.close()
            raise
        self._fh = fh
        return True

    def release(self) -> None:
        if self._depth <= 0:
            raise RuntimeError("release of an unheld ProcessLock")
        self._depth -= 1
        if self._depth == 0 and self._fh is not None:
            fh, self._fh = self._fh, None
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()
        self._rlock.release()

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
