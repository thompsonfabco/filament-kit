"""Start an ASGI app in a thread for a test, deterministically (tests only).

The socket is bound here, before uvicorn runs, and handed to it: a port picked with `free_port()` and closed again
can be taken by another xdist worker before uvicorn binds it. The wait ends when the server says it started, when
its thread has died (an error at once, not after the deadline), or at START_DEADLINE, long enough for a loaded CI box.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import uvicorn

START_DEADLINE = 60.0


# 0 = "a free one" is taken from a range of its own per xdist worker, below the system's ephemeral range: that range is
# what every client connection of every worker draws from (on some WSL setups only 1024 ports), and a bind to port 0
# fails with "address in use" once the crowd of test connections in TIME_WAIT has used it up. Workers never share a range.
RANGE_START = 20000
RANGE_SIZE = 400
_next = [0]


def _worker_index() -> int:
    name = os.environ.get("PYTEST_XDIST_WORKER", "gw0")        # "gw12"; no xdist: one process, the first range
    return int(name[2:]) % 64 if name[2:].isdigit() else 0


def bind(port: int = 0) -> socket.socket:
    """A TCP socket bound to 127.0.0.1:<port> (0 = a free one from this worker's own range), not listening yet:
    connections to it are refused until the server starts, and no other process can take the port meanwhile."""
    if port:
        sock = socket.socket()
        sock.bind(("127.0.0.1", port))
        return sock
    first = RANGE_START + _worker_index() * RANGE_SIZE
    for _ in range(RANGE_SIZE):
        offset = _next[0] % RANGE_SIZE
        _next[0] += 1
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", first + offset))
        except OSError:                                      # in use by anything else, or still in TIME_WAIT: the next
            sock.close()
            continue
        return sock
    sock = socket.socket()                                   # the range is full: the system's choice, as before
    sock.bind(("127.0.0.1", 0))
    return sock


def free_port() -> int:
    """A port nothing listens on now (a dead address for a test), from this worker's range."""
    with bind() as sock:
        return sock.getsockname()[1]


class Running:
    def __init__(self, asgi, sock: socket.socket | None = None, **config):
        self.sock = sock or bind()
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(asgi, log_level="warning", **config))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)

    def start(self) -> "Running":
        self.thread.start()
        deadline = time.monotonic() + START_DEADLINE
        while not self.server.started:
            if not self.thread.is_alive():
                self.sock.close()
                raise RuntimeError(f"fake server on port {self.port} stopped before it started")
            if time.monotonic() > deadline:
                self.stop()
                raise RuntimeError(f"fake server on port {self.port} did not start in {START_DEADLINE:.0f} s")
            time.sleep(0.02)
        return self

    def stop(self, timeout: float = 10) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=timeout)
        self.sock.close()


def start(asgi, sock: socket.socket | None = None, **config) -> Running:
    return Running(asgi, sock, **config).start()
