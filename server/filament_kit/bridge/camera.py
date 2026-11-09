"""Printer camera relay, started on demand by the first viewer and stopped 45 s after the last.

RTSP printers (X1, H2, X2, P2S; see `models.camera_kind`): RTSPS on port 322 with Digest auth. A loopback relay
(`RtspRelay`) does the TLS and the auth, so ffmpeg only ever sees `rtsp://127.0.0.1:<relay>/...` and remuxes the
H.264 to HLS without re-encoding into `$RUNTIME_DIRECTORY/cam/<serial>/` (tmpfs under systemd). A viewer is an
HLS fetch within the last 10 s.

P1/A1 printers: TLS on port 6000, an 80-byte auth packet, then frames of a 16-byte header (u32 LE payload size +
12 bytes) and a JPEG. Served as `multipart/x-mixed-replace` at no more than 5 frames a second. A viewer is an
open MJPEG response.

Both upstreams are TLS with the printer's pinned leaf (`tlspin`): the Access Code (Digest response, auth packet)
only goes over a socket whose leaf passed the pin; a changed leaf stops the source and the routes answer
`409 cert_changed` (also as soon as the MQTT connection has seen it, via `printer_state`).

Ported from the owner's H2D remote (`remote.py`, proven on hardware). The Access Code is never on a command
line, never logged and never part of a repr.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import os
import re
import select
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import anyio

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .. import hostaddr
from . import models, registry, tlspin

log = logging.getLogger(__name__)

USER = "bblp"
RTSP_PORT = 322
JPEG_PORT = 6000
CAM_PATH = "/streaming/live/1"
IDLE_STOP = 45.0            # seconds the source keeps running after the last viewer
HLS_WINDOW = 10.0           # an HLS fetch counts as a viewer for this long
HLS_START_WAIT = 12.0       # seconds a playlist request waits for ffmpeg's first playlist
RESTART_AFTER = 5.0         # a dead ffmpeg is restarted by a fetch at most this often
MJPEG_MIN_INTERVAL = 0.2    # ≤ 5 fps to the phone
MAX_FRAME = 8 * 1024 * 1024
MAX_QUEUED = 1024 * 1024        # the relay stops reading a side once this much waits for the other
PUMP_CHUNK = 16384              # at most one write's worth, one TLS record
PUMP_TICK = 1.0                 # seconds; the pump looks at the clock at least this often
FLUSH_TIMEOUT = 5.0             # seconds either side gets to take what is queued once the other has ended
BACKOFF = (1.0, 30.0)
MAX_RTSP_HEADERS = 64 * 1024
MAX_RTSP_BODY = 1024 * 1024
UPSTREAM_TIMEOUT = 20.0     # a printer silent this long drops the relay; ffmpeg exits, the next fetch restarts it
FFMPEG_IO_TIMEOUT_US = 10_000_000  # ffmpeg RTSP `-timeout` in µs (ffmpeg >= 5; Ubuntu 24.04 ships 6.1)
SEGMENT = re.compile(r"[A-Za-z0-9_-]{1,64}\.(ts|m3u8)")
SERIAL = registry.SERIAL


class CameraError(Exception):
    status, code = 500, "internal"


class NoCamera(CameraError):
    status, code = 404, "not_found"


class NotConfigured(CameraError):
    status, code = 409, "not_configured"


class Unavailable(CameraError):
    status, code = 503, "camera_unavailable"


class CertChangedError(CameraError):
    status, code = 409, "cert_changed"


CERT_CHANGED = ("The printer's certificate changed. If you reset the printer or its mainboard was replaced, add it "
                "again with its Access Code. If not, something else may be answering at the printer's address — "
                "check the printer's IP before re-adding.")


# ---------------------------------------------------------------- RTSPS relay (X1 / H2 / X2 / P2S)

def _parse_rtsp(buf: bytes) -> tuple[bytes, bytes] | None:
    """One whole RTSP text message (headers + Content-Length body) off the front of `buf` -> (msg, rest); None: not all
    here yet."""
    if b"\r\n\r\n" not in buf:
        if len(buf) > MAX_RTSP_HEADERS:
            raise ConnectionError("RTSP headers too long")
        return None
    head, rest = buf.split(b"\r\n\r\n", 1)
    m = re.search(rb"(?im)^content-length:\s*(\d+)", head)
    n = int(m.group(1)) if m else 0
    if len(head) > MAX_RTSP_HEADERS or n > MAX_RTSP_BODY:
        raise ConnectionError("RTSP message too large")
    if len(rest) < n:
        return None
    return head + b"\r\n\r\n" + rest[:n], rest[n:]


def _read_rtsp(sock, buf: bytes) -> tuple[bytes, bytes]:
    """Read one RTSP text message -> (msg bytes, rest)."""
    while (got := _parse_rtsp(buf)) is None:
        d = sock.recv(65536)
        if not d:
            raise ConnectionError("closed")
        buf += d
    return got


def _for_printer(buf: bytes, rewrite: Callable[[bytes], bytes]) -> tuple[bytes, bytes]:
    """What ffmpeg's bytes so far send on to the printer -> (bytes to send, what waits for the rest of its message):
    interleaved RTCP frames as they are, text messages through `rewrite`."""
    out = bytearray()
    while buf:
        if buf[:1] == b"$":             # interleaved RTCP from ffmpeg
            if len(buf) < 4:
                break
            n = 4 + struct.unpack(">H", buf[2:4])[0]
            if len(buf) < n:
                break
            out += buf[:n]
            buf = buf[n:]
            continue
        got = _parse_rtsp(buf)
        if got is None:
            break
        msg, buf = got
        out += rewrite(msg)
    return bytes(out), buf


def _pump(cli: socket.socket, up, rewrite: Callable[[bytes], bytes], idle: float) -> None:
    """Relay between ffmpeg (`cli`) and the printer's TLS socket (`up`) until either ends. One thread both ways: an
    SSLSocket's one TLS session must not be read and written at the same time from two threads. Non-blocking, so a TLS
    read that needs a write (or the reverse) waits on what it asked for. Printer silent for `idle` seconds: TimeoutError."""
    cli.setblocking(False)
    up.setblocking(False)
    to_up, to_cli = bytearray(), bytearray()
    from_cli = b""
    recv_waits, send_waits = "r", "w"       # what `up` last asked its read and its write to wait for
    last_up = time.monotonic()

    def cli_ended() -> None:
        """However ffmpeg's side ended, what it sent first still reaches the printer: stopped while video flows, it has
        unread bytes, so its close is a reset, with its TEARDOWN still waiting here to be read."""
        nonlocal from_cli, to_up
        try:
            while d := cli.recv(65536):
                out, from_cli = _for_printer(from_cli + d, rewrite)
                to_up += out
        except (OSError, ValueError):       # all read (a would-block or a reset), or a bad last message
            pass
        try:
            up.settimeout(FLUSH_TIMEOUT)
            up.sendall(to_up)
        except OSError:
            pass

    while True:
        room_down = len(to_cli) < MAX_QUEUED
        readable = [s for s, on in ((cli, len(to_up) < MAX_QUEUED),
                                    (up, (room_down and recv_waits == "r") or (to_up and send_waits == "r"))) if on]
        writable = [s for s, on in ((cli, to_cli),
                                    (up, (room_down and recv_waits == "w") or (to_up and send_waits == "w"))) if on]
        left = last_up + idle - time.monotonic()
        if left <= 0:
            raise TimeoutError("the camera went silent")
        # up.pending(): TLS has bytes of a record it already read, and select would not say so
        wait = 0 if room_down and up.pending() else min(left, PUMP_TICK)
        can_read, can_write, _ = select.select(readable, writable, [], wait)

        if cli in can_read:
            try:
                d = cli.recv(65536)
            except BlockingIOError:
                d = None
            except OSError:
                d = b""
            if d == b"":
                cli_ended()
                return
            if d:
                out, from_cli = _for_printer(from_cli + d, rewrite)
                to_up += out
        up_ready = up in can_read or up in can_write
        if room_down and (up_ready or up.pending()):
            recv_waits = "r"
            try:
                d = up.recv(65536)
                if not d:
                    cli.settimeout(FLUSH_TIMEOUT)   # what the printer sent before it ended still reaches ffmpeg
                    cli.sendall(to_cli)
                    return
                to_cli += d
                last_up = time.monotonic()
            except (ssl.SSLWantReadError, BlockingIOError):
                pass
            except ssl.SSLWantWriteError:
                recv_waits = "w"
            except OSError:         # the printer hung up, or stop() shut it down
                cli.settimeout(FLUSH_TIMEOUT)
                cli.sendall(to_cli)
                return
        if to_up and up_ready:
            send_waits = "w"
            try:
                # a retried TLS write sends this same prefix: to_up only ever grows at its end
                del to_up[:up.send(bytes(to_up[:PUMP_CHUNK]))]
            except ssl.SSLWantReadError:
                send_waits = "r"
            except (ssl.SSLWantWriteError, BlockingIOError):
                pass
        if to_cli and cli in can_write:
            try:
                del to_cli[:cli.send(bytes(to_cli[:PUMP_CHUNK]))]
            except BlockingIOError:
                pass
            except OSError:
                cli_ended()
                return


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


class RtspRelay:
    """Loopback RTSP server; each connection is forwarded to the printer over TLS with Digest auth added."""

    def __init__(self, printer: registry.Printer, port: int = RTSP_PORT):
        self.printer, self.ip, self.port = printer, printer.ip, port
        self._code = printer.access_code
        self.cert_changed = False       # the upstream leaf did not match the pin
        self._srv: socket.socket | None = None
        self._conns: set[socket.socket] = set()
        self._lock = threading.Lock()
        self.local_port = 0

    def __repr__(self) -> str:
        return f"RtspRelay({self.ip}:{self.port})"

    def start(self) -> int:
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        self._srv = srv
        self.local_port = srv.getsockname()[1]
        threading.Thread(target=self._accept, args=(srv,), daemon=True, name="cam-relay").start()
        return self.local_port

    def stop(self) -> None:
        """Wakes every thread of the relay; each closes what it owns. A socket closed while another thread waits on it
        leaves that thread reading the file number, whichever connection has it by then."""
        srv, self._srv = self._srv, None
        if srv:
            _wake(srv)
            srv.close()
        with self._lock:
            conns, self._conns = list(self._conns), set()
        for s in conns:
            _wake(s)

    def _accept(self, srv: socket.socket) -> None:
        while True:
            try:
                c, a = srv.accept()
            except OSError:
                return
            if a[0] != "127.0.0.1":
                c.close()
                continue
            threading.Thread(target=self._conn, args=(c,), daemon=True, name="cam-relay-conn").start()

    def _track(self, *socks) -> bool:
        with self._lock:
            if self._srv is None:
                return False
            self._conns.update(s for s in socks if s is not None)
            return True

    def _conn(self, cli: socket.socket) -> None:
        up = None
        try:
            if not self._track(cli):
                return
            try:
                up = tlspin.connect(self.printer, self.port, timeout=10)   # pin checked before any Digest
            except tlspin.CertChanged:  # logged by tlspin (fingerprints only)
                self.cert_changed = True
                return
            if not self._track(up):
                return
            real = f"rtsps://{hostaddr.url_host(self.ip)}:{self.port}"
            up.sendall(f"DESCRIBE {real}{CAM_PATH} RTSP/1.0\r\nCSeq: 0\r\n\r\n".encode())
            resp, _ = _read_rtsp(up, b"")
            m = re.search(rb'Digest realm="([^"]+)".*?nonce="([^"]+)"', resp)
            if not m:
                raise ConnectionError("no digest challenge from the camera (is LAN mode liveview on?)")
            realm, nonce = m.group(1).decode(), m.group(2).decode()
            ha1 = _md5(f"{USER}:{realm}:{self._code}")
            local = f"rtsp://127.0.0.1:{self.local_port}".encode()

            def signed(msg: bytes) -> bytes:
                head, body = msg.split(b"\r\n\r\n", 1)
                lines = head.split(b"\r\n")
                method, uri, ver = lines[0].split(b" ", 2)
                uri = uri.replace(local, real.encode())
                u = uri.decode()
                digest = _md5(f"{ha1}:{nonce}:{_md5(f'{method.decode()}:{u}')}")
                auth = (f'Authorization: Digest username="{USER}", realm="{realm}", nonce="{nonce}", '
                        f'uri="{u}", response="{digest}"').encode()
                keep = [line for line in lines[1:] if not line.lower().startswith(b"authorization:")]
                return b"\r\n".join([b" ".join([method, uri, ver])] + keep + [auth]) + b"\r\n\r\n" + body

            _pump(cli, up, signed, UPSTREAM_TIMEOUT)
        except (OSError, ValueError, ConnectionError) as e:
            log.info("camera relay to %s: %s", self.ip, type(e).__name__ if not str(e) else e)
        finally:
            with self._lock:
                self._conns.difference_update({cli, up})
            _close(cli)
            _close(up)


def _wake(s) -> None:
    """On Linux, where the server runs, a thread waiting on `s` returns now. Only that wakes it: close() in another thread doesn't."""
    try:
        s.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _close(s) -> None:
    if s is None:
        return
    try:
        s.close()
    except OSError:
        pass


def _kill_tree(p: subprocess.Popen) -> None:
    """Stop the process and everything it started (it leads its own process group / job)."""
    if p.poll() is not None and os.name == "nt":
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        pass
    try:  # anything left in the group (or a stuck ffmpeg)
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        log.error("camera: ffmpeg pid %s did not exit", p.pid)


class HlsSource:
    """Relay + ffmpeg HLS remux for one printer."""

    def __init__(self, printer: registry.Printer, hub: "Hub"):
        self.serial, self.dir = printer.serial, hub.dir_for(printer.serial)
        self._relay = RtspRelay(printer, hub.rtsp_port)
        self._ffmpeg = list(hub.ffmpeg)
        self._proc: subprocess.Popen | None = None
        self.started_at = 0.0

    def command(self, relay_port: int) -> list[str]:
        return [*self._ffmpeg, "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
                "-timeout", str(FFMPEG_IO_TIMEOUT_US), "-i", f"rtsp://127.0.0.1:{relay_port}{CAM_PATH}", "-an", "-c", "copy",
                "-f", "hls", "-hls_time", "1", "-hls_list_size", "4", "-hls_flags", "delete_segments",
                "-hls_segment_filename", str(self.dir / "seg%05d.ts"), str(self.dir / "index.m3u8")]

    def start(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        port = self._relay.start()
        kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
              else {"start_new_session": True})
        self.started_at = time.monotonic()
        try:
            self._proc = subprocess.Popen(self.command(port), stdin=subprocess.DEVNULL, **kw)
        except OSError:
            self._relay.stop()
            raise
        log.info("camera %s: started", self.serial)

    def stop(self) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            _kill_tree(p)
        self._relay.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
        log.info("camera %s: stopped", self.serial)

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def cert_changed(self) -> bool:
        return self._relay.cert_changed


# ---------------------------------------------------------------- port-6000 JPEG stream (P1 / A1)

def auth_packet(access_code: str) -> bytes:
    """u32 LE 0x40, 0x3000, 0, 0; then user and Access Code, each NUL-padded to 32 bytes."""
    if not access_code.isascii() or len(access_code) > 32:
        raise ValueError("the Access Code must be at most 32 ASCII characters")
    user, code = USER.encode("ascii"), access_code.encode("ascii")
    return struct.pack("<4I", 0x40, 0x3000, 0, 0) + user.ljust(32, b"\0") + code.ljust(32, b"\0")


def _recv_exact(s, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        d = s.recv(min(n - len(buf), 65536))
        if not d:
            raise ConnectionError("closed")
        buf += d
    return bytes(buf)


class MjpegSource:
    """Reads the printer's JPEG stream in a thread and keeps the latest frame; reconnects with backoff."""

    def __init__(self, printer: registry.Printer, hub: "Hub"):
        self.serial, self.ip, self.port = printer.serial, printer.ip, hub.jpeg_port
        self.printer = printer
        self._code = printer.access_code
        self.cert_changed = False       # the leaf did not match the pin; the source gave up
        self._stop = threading.Event()
        self._sock = None
        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self.seq = 0
        self._thread: threading.Thread | None = None

    def __repr__(self) -> str:
        return f"MjpegSource({self.serial} {self.ip}:{self.port})"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"cam-jpeg-{self.serial}")
        self._thread.start()
        log.info("camera %s: started", self.serial)

    def stop(self) -> None:
        self._stop.set()
        s = self._sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            _close(s)
        if self._thread is not None:
            self._thread.join(5)
        log.info("camera %s: stopped", self.serial)

    def alive(self) -> bool:
        return not self._stop.is_set()

    def frame(self) -> tuple[int, bytes | None]:
        with self._lock:
            return self.seq, self._frame

    def _run(self) -> None:
        delay = BACKOFF[0]
        while not self._stop.is_set():
            try:
                s = tlspin.connect(self.printer, self.port, timeout=10)   # pin checked before the auth packet
                self._sock = s
                if self._stop.is_set():
                    break
                s.sendall(auth_packet(self._code))
                while not self._stop.is_set():
                    size = struct.unpack_from("<I", _recv_exact(s, 16))[0]
                    if not 0 < size <= MAX_FRAME:
                        raise ConnectionError(f"bad frame size {size}")
                    img = _recv_exact(s, size)
                    if img[:2] != b"\xff\xd8" or img[-2:] != b"\xff\xd9":
                        log.debug("camera %s: dropped a frame that is not a whole JPEG", self.serial)
                        continue
                    with self._lock:
                        self._frame, self.seq = img, self.seq + 1
                    delay = BACKOFF[0]
            except tlspin.CertChanged:  # logged by tlspin (fingerprints only); retrying cannot help
                self.cert_changed = True
                self._stop.set()
                break
            except ValueError as e:  # an unusable Access Code: log the type only, retrying cannot help
                log.warning("camera %s: %s; not retrying", self.serial, type(e).__name__)
                self._stop.set()
                break
            except (OSError, ConnectionError) as e:
                if not self._stop.is_set():
                    log.info("camera %s: %s; retry in %.0f s", self.serial, e or type(e).__name__, delay)
            finally:
                _close(self._sock)
                self._sock = None
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, BACKOFF[1])


# ---------------------------------------------------------------- hub

SOI, EOI = b"\xff\xd8", b"\xff\xd9"     # JPEG start / end of image


class HttpMjpegSource:
    """A Klipper printer's webcam: reads Moonraker's MJPEG stream URL (multipart/x-mixed-replace, e.g. crowsnest /
    ustreamer at /webcam/?action=stream) in a thread and keeps the latest whole JPEG; reconnects with backoff. Same
    interface as MjpegSource (`start`, `stop`, `alive`, `frame`)."""

    cert_changed = False

    def __init__(self, printer: registry.Printer, hub, url: str):
        self.serial, self.url, self.printer = printer.serial, url, printer
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self.seq = 0
        self._resp = None
        self._thread: threading.Thread | None = None

    def __repr__(self) -> str:
        return f"HttpMjpegSource({self.serial})"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"cam-http-{self.serial}")
        self._thread.start()
        log.info("camera %s: started", self.serial)

    def stop(self) -> None:
        self._stop.set()
        r = self._resp
        if r is not None:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(5)
        log.info("camera %s: stopped", self.serial)

    def alive(self) -> bool:
        return not self._stop.is_set()

    def frame(self) -> tuple[int, bytes | None]:
        with self._lock:
            return self.seq, self._frame

    def _run(self) -> None:
        import urllib.request
        delay = BACKOFF[0]
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(self.url, headers={"User-Agent": "filament-kit"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    self._resp = r
                    buf = b""
                    while not self._stop.is_set():
                        chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                        if not chunk:
                            break
                        buf += chunk
                        while True:
                            a = buf.find(SOI)
                            if a < 0:
                                buf = buf[-1:]
                                break
                            b = buf.find(EOI, a + 2)
                            if b < 0:
                                buf = buf[a:]
                                if len(buf) > MAX_FRAME:
                                    buf = b""      # no end marker within a frame's size: drop and resync
                                break
                            img, buf = buf[a:b + 2], buf[b + 2:]
                            with self._lock:
                                self._frame, self.seq = img, self.seq + 1
                            delay = BACKOFF[0]
            except (OSError, ValueError) as e:
                if not self._stop.is_set():
                    log.info("camera %s: %s; retry in %.0f s", self.serial, e or type(e).__name__, delay)
            finally:
                self._resp = None
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, BACKOFF[1])


def _runtime_root() -> Path:
    rd = os.environ.get("RUNTIME_DIRECTORY", "").split(":")[0]
    return Path(rd) if rd else Path(tempfile.gettempdir()) / "filament-kit"


class Hub:
    """One camera source per printer, reference-counted: the first viewer starts it, the last `release()`
    stops it `idle_stop` seconds later unless a new viewer arrives first.

    Locking: `_lock` guards the dictionaries only and is never held while a source starts or stops. Starting
    and stopping one printer's source holds that printer's own lock, so a printer that is slow to stop delays
    only its own next viewer (who waits for the stop to finish), never another printer's."""

    def __init__(self, lookup: Callable[[str], registry.Printer | None] | None = None,
                 runtime_dir: Path | None = None, idle_stop: float = IDLE_STOP, hls_window: float = HLS_WINDOW,
                 sources: dict | None = None, ffmpeg=("ffmpeg",), rtsp_port: int = RTSP_PORT,
                 jpeg_port: int = JPEG_PORT, printer_state: Callable[[str], str] | None = None,
                 klipper_url: Callable[[str], str | None] | None = None):
        self._lookup = lookup or (lambda serial: registry.load().get(serial))
        self._klipper_url = klipper_url       # KlipperFamily.camera_url: a Klipper printer's webcam stream URL
        self._printer_state = printer_state   # the MQTT Manager's state(): its `cert_changed` refuses the camera too
        self.root = Path(runtime_dir) if runtime_dir else _runtime_root()
        self.idle_stop, self.hls_window = idle_stop, hls_window
        self._sources = {"hls": HlsSource, "mjpeg": MjpegSource, **(sources or {})}
        self.ffmpeg, self.rtsp_port, self.jpeg_port = tuple(ffmpeg), rtsp_port, jpeg_port
        self.stopping = threading.Event()   # set when the server is shutting down: streams end, no new ones
        self._lock = threading.Lock()
        self._serial_locks: dict[str, threading.RLock] = {}
        self._running: dict[str, object] = {}
        # the printer each running source was started with; a first-use pin updates its cert_fp in place
        self._targets: dict[str, registry.Printer] = {}
        self._refs: dict[str, int] = {}
        self._stop_timers: dict[str, threading.Timer] = {}
        self._hls_last: dict[str, float] = {}
        self._hls_timers: dict[str, threading.Timer] = {}

    def dir_for(self, serial: str) -> Path:
        if not SERIAL.fullmatch(serial or ""):
            raise NoCamera("no such printer")
        return self.root / "cam" / serial

    def check(self, serial: str, kind: str | None = None) -> tuple[registry.Printer, str]:
        """The printer and its camera kind; raises NoCamera / NotConfigured / Unavailable."""
        if self.stopping.is_set():
            raise Unavailable("the server is shutting down")
        if not SERIAL.fullmatch(serial or ""):
            raise NoCamera("no such printer")
        p = self._lookup(serial)
        if p is not None and p.family == "klipper":
            url = self._klipper_url(serial) if self._klipper_url else None
            if url is None or (kind and kind != "mjpeg"):
                raise NoCamera("this printer has no camera of that kind")
            return p, "mjpeg"
        k = models.camera_kind(p.model) if p else None
        if p is None or k is None or (kind and k != kind):
            raise NoCamera("this printer has no camera of that kind" if p else "no such printer")
        if not p.configured or not p.access_code or not p.ip:
            raise NotConfigured("add this printer's Access Code first")
        if self._printer_state is not None and self._printer_state(serial) == "cert_changed":
            raise CertChangedError(CERT_CHANGED)
        return p, k

    def running(self, serial: str) -> bool:
        with self._lock:
            return serial in self._running

    def _serial_lock(self, serial: str) -> threading.RLock:
        with self._lock:
            return self._serial_locks.setdefault(serial, threading.RLock())

    def acquire(self, serial: str, kind: str | None = None, checked: tuple | None = None):
        """Count a viewer in; start the source if needed. Returns the source. `checked` = a `check()` result
        the caller already has (saves a registry read)."""
        p, k = checked or self.check(serial, kind)
        with self._serial_lock(serial):
            with self._lock:
                t = self._stop_timers.pop(serial, None)
                if t:
                    t.cancel()
                src = self._running.get(serial)
                self._refs[serial] = self._refs.get(serial, 0) + 1
            try:
                if src is None:
                    src = self._start(serial, p, k)
                else:
                    src = self._retarget(serial, p, k, src)
            except BaseException:
                with self._lock:
                    self._refs[serial] -= 1
                    if not self._refs[serial]:
                        del self._refs[serial]
                raise
            return src

    def _start(self, serial: str, p: registry.Printer, kind: str):
        """Start a new source for `p` and record it as running. Caller holds the printer's lock."""
        if p.family == "klipper":
            src = HttpMjpegSource(p, self, self._klipper_url(serial) if self._klipper_url else "")
        else:
            src = self._sources[kind](p, self)
        src.start()
        with self._lock:
            self._running[serial] = src
            self._targets[serial] = p
        return src

    @staticmethod
    def _target(p: registry.Printer) -> tuple:
        return p.ip, p.access_code, p.cert_fp, p.family, p.host, p.port

    def _retarget(self, serial: str, p: registry.Printer, kind: str, src):
        """The running source if it still points at the printer's (ip, Access Code, pin); otherwise it is stopped
        and a new one started (the printer moved, was re-keyed or added again). Caller holds the printer's lock."""
        with self._lock:
            t = self._targets.get(serial)
            same = t is not None and self._target(t) == self._target(p)
        if same:
            return src
        log.info("camera %s: the printer's address, Access Code or pin changed; restarting", serial)
        with self._lock:
            if self._running.get(serial) is src:
                del self._running[serial]
                self._targets.pop(serial, None)
        _stop(src)
        return self._start(serial, p, kind)

    def release(self, serial: str) -> None:
        """Count a viewer out. Never waits for a source to stop."""
        with self._lock:
            n = self._refs.get(serial, 0) - 1
            if n > 0:
                self._refs[serial] = n
                return
            self._refs.pop(serial, None)
            if serial in self._running and serial not in self._stop_timers:
                t = threading.Timer(self.idle_stop, self._idle, args=(serial,))
                t.daemon = True
                self._stop_timers[serial] = t
                t.start()

    def _idle(self, serial: str) -> None:
        # the printer's own lock: its next viewer waits until the old source has stopped and cleaned its dir
        with self._serial_lock(serial):
            with self._lock:
                if self._stop_timers.pop(serial, None) is None or self._refs.get(serial):
                    return
                src = self._running.pop(serial, None)
                self._targets.pop(serial, None)
            if src is not None:
                _stop(src)

    def touch_hls(self, serial: str):
        """An HLS fetch: holds one viewer reference until `hls_window` passes without a fetch. A source whose
        ffmpeg died is restarted (at most every RESTART_AFTER seconds). One registry read per fetch."""
        checked = self.check(serial, "hls")
        with self._serial_lock(serial):
            with self._lock:
                self._hls_last[serial] = time.monotonic()
                src = self._running.get(serial) if serial in self._hls_timers else None
            if src is None:
                src = self.acquire(serial, "hls", checked)
                with self._lock:
                    if serial not in self._hls_timers:
                        self._arm_hls(serial, self.hls_window)
                    else:  # lease held but its source was gone: keep one reference for the lease
                        self._refs[serial] -= 1
            else:
                src = self._retarget(serial, *checked, src)
            if not src.alive() and time.monotonic() - getattr(src, "started_at", 0) > RESTART_AFTER:
                src.stop()
                src.start()
            return src

    def _arm_hls(self, serial: str, delay: float) -> None:  # caller holds _lock
        t = threading.Timer(delay, self._hls_check, args=(serial,))
        t.daemon = True
        self._hls_timers[serial] = t
        t.start()

    def _hls_check(self, serial: str) -> None:
        with self._lock:
            if serial not in self._hls_timers:
                return
            left = self._hls_last.get(serial, 0) + self.hls_window - time.monotonic()
            if left > 0:
                self._arm_hls(serial, left)
                return
            del self._hls_timers[serial]
            self._hls_last.pop(serial, None)
        self.release(serial)

    def begin_stop(self) -> None:
        """The server is going down: open MJPEG streams end at their next check, new viewers are refused."""
        self.stopping.set()

    def shutdown(self) -> None:
        """Stop every source now (no orphan ffmpeg)."""
        self.stopping.set()
        with self._lock:
            for t in [*self._stop_timers.values(), *self._hls_timers.values()]:
                t.cancel()
            self._stop_timers.clear()
            self._hls_timers.clear()
            self._hls_last.clear()
            self._refs.clear()
            sources, self._running = list(self._running.items()), {}
            self._targets.clear()
        for serial, src in sources:
            with self._serial_lock(serial):
                _stop(src)


def _stop(src) -> None:
    try:
        src.stop()
    except Exception:  # noqa: BLE001 - a failed stop must not break the hub
        log.exception("camera: stopping a source failed")


# ---------------------------------------------------------------- routes

def _err(e: CameraError | int, code: str = "", message: str = "") -> JSONResponse:
    if isinstance(e, CameraError):
        return JSONResponse({"error": e.code, "message": str(e)}, status_code=e.status)
    return JSONResponse({"error": code, "message": message}, status_code=e)


def _guard(fn):
    """CameraError -> its JSON error; anything unexpected (ffmpeg missing, ...) -> 500 `internal`."""
    @functools.wraps(fn)
    async def wrapper(request: Request):
        try:
            return await fn(request)
        except CameraError as e:
            return _err(e)
        except Exception as e:  # noqa: BLE001
            log.error("camera: internal error (%s)", type(e).__name__, exc_info=e)
            return _err(500, "internal", "internal error")
    return wrapper


_TYPES = {"m3u8": "application/vnd.apple.mpegurl", "ts": "video/mp2t"}


def routes(hub: Hub, auth_wrapper: Callable) -> list[Route]:
    """`GET /api/printers/{id}/camera/<index.m3u8|segment.ts>` and `GET /api/printers/{id}/camera.mjpeg`;
    `auth_wrapper` adds the Bearer check."""

    async def hls(request: Request):
        serial, name = request.path_params["id"], request.path_params["name"]
        if not SEGMENT.fullmatch(name):
            return _err(400, "bad_request", "only index.m3u8 and .ts segments are served here")
        src = await run_in_threadpool(hub.touch_hls, serial)
        if getattr(src, "cert_changed", False):
            raise CertChangedError(CERT_CHANGED)
        path = src.dir / name
        if name.endswith(".m3u8"):
            end = time.monotonic() + HLS_START_WAIT
            while not await run_in_threadpool(path.exists):
                if getattr(src, "cert_changed", False):
                    raise CertChangedError(CERT_CHANGED)
                if time.monotonic() >= end or hub.stopping.is_set():
                    return _err(503, "camera_unavailable",
                                "the camera stream did not start; check that the printer is on and "
                                "LAN mode liveview is enabled")
                await asyncio.sleep(0.2)
        try:
            data = await run_in_threadpool(path.read_bytes)
        except OSError:
            return _err(404, "not_found", "that segment is gone; reload the playlist")
        return Response(data, media_type=_TYPES[name.rsplit(".", 1)[1]], headers={"Cache-Control": "no-cache"})

    async def mjpeg(request: Request):
        """The viewer is counted in here and the first frame awaited before any header goes out, so a camera that
        sends nothing within HLS_START_WAIT gets a 503 rather than an empty 200 stream."""
        serial = request.path_params["id"]
        src = await run_in_threadpool(hub.acquire, serial, "mjpeg")
        try:
            end = time.monotonic() + HLS_START_WAIT
            while src.frame()[1] is None:
                if getattr(src, "cert_changed", False):
                    raise CertChangedError(CERT_CHANGED)
                if time.monotonic() >= end or not src.alive() or hub.stopping.is_set():
                    raise Unavailable("the camera sent no picture; check that the printer is on and "
                                      "LAN mode liveview is enabled")
                await asyncio.sleep(0.05)
        except BaseException:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(hub.release, serial)
            raise
        return _ViewerStream(_frames(hub, src), functools.partial(hub.release, serial),
                             media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-cache"})

    return [
        Route("/api/printers/{id}/camera/{name:path}", auth_wrapper(_guard(hls))),
        Route("/api/printers/{id}/camera.mjpeg", auth_wrapper(_guard(mjpeg))),
    ]


class _ViewerStream(StreamingResponse):
    """A streaming response that counts its viewer out when it ends, however it ends (client gone, source
    dead, server stopping, or a body that was never iterated)."""

    def __init__(self, content, on_close: Callable[[], None], **kw):
        super().__init__(content, **kw)
        self._on_close = on_close

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):  # also runs when the client's disconnect cancels the body
                await run_in_threadpool(self._on_close)


async def _frames(hub: Hub, src):
    """The multipart body; ends when the source dies or the server is stopping."""
    seq, last = 0, 0.0
    while src.alive() and not hub.stopping.is_set():
        s, img = src.frame()
        if s == seq or img is None:
            await asyncio.sleep(0.05)
            continue
        wait = MJPEG_MIN_INTERVAL - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
            s, img = src.frame()  # the newest frame after the wait
        seq, last = s, time.monotonic()
        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(img) + img + b"\r\n"
