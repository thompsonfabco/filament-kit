"""Start an ASGI app in a thread for a test, deterministically (tests only).

The socket is bound here, before uvicorn runs, and handed to it: a port picked with `free_port()` and closed again
can be taken by another xdist worker before uvicorn binds it. The wait ends when the server says it started, when
its thread has died (an error at once, not after the deadline), or at START_DEADLINE, long enough for a loaded CI box.
"""
from __future__ import annotations

import socket
import threading
import time

import uvicorn

START_DEADLINE = 60.0


def bind(port: int = 0) -> socket.socket:
    """A TCP socket bound to 127.0.0.1:<port> (0 = a free one), not listening yet: connections to it are refused
    until the server starts, and no other process can take the port meanwhile."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    return sock


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
