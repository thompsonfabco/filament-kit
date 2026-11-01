import hashlib
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.testclient import TestClient

from conftest import free_port
from filament_kit import config, pairing
from filament_kit.api import create_app
from filament_kit.bridge import camera, models
from filament_kit.bridge.registry import Printer

CODE = "13572468"
FAKE_FFMPEG = Path(__file__).parent / "fakes" / "fake_ffmpeg.py"


def wait_until(cond, timeout=10.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie still answers kill(0); it is dead for our purpose
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


class FakeSource:
    instances: list = []

    def __init__(self, printer, hub):
        self.printer, self.started, self.stopped = printer, 0, 0
        self.dir = hub.dir_for(printer.serial)
        FakeSource.instances.append(self)

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def alive(self):
        return self.started > self.stopped


@pytest.fixture
def printers():
    return {
        "H1": Printer("H1", "Office H2D", "O1D", "127.0.0.1", CODE, True),
        "P1": Printer("P1", "Garage P1S", "C12", "127.0.0.1", CODE, True),
        "U1": Printer("U1", "Unknown", "ZZZ", "127.0.0.1", CODE, True),
        "N1": Printer("N1", "New H2D", "O1D", "127.0.0.1", "", False),
    }


@pytest.fixture
def fake_hub(printers, tmp_path):
    FakeSource.instances = []
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", idle_stop=0.2, hls_window=0.1,
                     sources={"hls": FakeSource, "mjpeg": FakeSource})
    yield hub
    hub.shutdown()


# ---------------------------------------------------------------- model table

@pytest.mark.parametrize("model,kind", [
    ("3DPrinter-X1-Carbon", "hls"), ("BL-P001", "hls"), ("3DPrinter-X1", "hls"), ("C13", "hls"),
    ("O1D", "hls"), ("O1E", "hls"), ("O1S", "hls"), ("O1C", "hls"), ("O1C2", "hls"), ("N6", "hls"), ("N7", "hls"),
    ("C11", "mjpeg"), ("C12", "mjpeg"), ("N1", "mjpeg"), ("N2S", "mjpeg"), ("N9", "mjpeg"),
    ("Bambu Lab A1 mini", "mjpeg"), ("X1C", "hls"), ("h2d", "hls"), ("P1S", "mjpeg"),
    ("N8", None), ("", None), ("Prusa MK4", None),
])
def test_camera_kind(model, kind):
    assert models.camera_kind(model) == kind


# ---------------------------------------------------------------- reference counting

def test_two_viewers_one_leaves_keeps_running_both_leave_stops_after_delay(fake_hub):
    fake_hub.acquire("P1")
    fake_hub.acquire("P1")
    src = FakeSource.instances[0]
    assert len(FakeSource.instances) == 1 and src.started == 1
    fake_hub.release("P1")
    time.sleep(0.4)
    assert fake_hub.running("P1") and src.stopped == 0
    fake_hub.release("P1")
    assert fake_hub.running("P1"), "the stop waits for the idle delay"
    assert wait_until(lambda: not fake_hub.running("P1"), 2)
    assert src.stopped == 1


def test_new_viewer_during_idle_delay_cancels_the_stop(fake_hub):
    fake_hub.acquire("P1")
    fake_hub.release("P1")
    fake_hub.acquire("P1")
    time.sleep(0.4)
    assert fake_hub.running("P1") and FakeSource.instances[0].stopped == 0
    assert len(FakeSource.instances) == 1


def test_hls_fetch_counts_as_viewer_for_its_window(fake_hub):
    fake_hub.touch_hls("H1")
    fake_hub.touch_hls("H1")
    assert len(FakeSource.instances) == 1 and fake_hub.running("H1")
    for _ in range(5):  # keep fetching: stays up
        time.sleep(0.08)
        fake_hub.touch_hls("H1")
    assert fake_hub.running("H1")
    assert wait_until(lambda: not fake_hub.running("H1"), 2), "no fetch for window + idle delay stops it"


def test_unknown_or_unconfigured_printers_are_refused(fake_hub):
    with pytest.raises(camera.NoCamera):
        fake_hub.acquire("nope")
    with pytest.raises(camera.NoCamera):
        fake_hub.acquire("U1")
    with pytest.raises(camera.NotConfigured):
        fake_hub.touch_hls("N1")
    with pytest.raises(camera.NoCamera):
        fake_hub.touch_hls("P1")  # an MJPEG printer has no HLS stream
    assert FakeSource.instances == []


# ---------------------------------------------------------------- ffmpeg process

@pytest.fixture
def ffmpeg_hub(printers, tmp_path):
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", idle_stop=0.2, hls_window=0.1,
                     ffmpeg=[sys.executable, "-I", str(FAKE_FFMPEG)])
    yield hub
    hub.shutdown()


def _started(hub, serial):
    d = hub.dir_for(serial)
    assert wait_until(lambda: (d / "argv.json").exists() and (d / "index.m3u8").exists(), 15)
    return json.loads((d / "argv.json").read_text())


def test_ffmpeg_reads_the_loopback_relay_and_never_gets_the_access_code(ffmpeg_hub, tmp_path):
    ffmpeg_hub.touch_hls("H1")
    info = _started(ffmpeg_hub, "H1")
    argv = info["argv"]
    assert not any(CODE in a for a in argv)
    i = argv.index("-i")
    assert re.fullmatch(r"rtsp://127\.0\.0\.1:\d+/streaming/live/1", argv[i + 1])
    assert argv[argv.index("-rtsp_transport") + 1] == "tcp"
    assert argv[argv.index("-timeout") + 1] == "10000000" and argv.index("-timeout") < i
    assert argv[argv.index("-c") + 1] == "copy"
    assert argv[argv.index("-f") + 1] == "hls"
    assert argv[argv.index("-hls_time") + 1] == "1"
    assert argv[argv.index("-hls_list_size") + 1] == "4"
    assert argv[argv.index("-hls_flags") + 1] == "delete_segments"
    assert Path(argv[-1]) == tmp_path / "run" / "cam" / "H1" / "index.m3u8"


def test_shutdown_kills_ffmpeg_and_its_children(ffmpeg_hub):
    ffmpeg_hub.touch_hls("H1")
    info = _started(ffmpeg_hub, "H1")
    assert pid_alive(info["pid"]) and pid_alive(info["child"])
    ffmpeg_hub.shutdown()
    assert wait_until(lambda: not pid_alive(info["pid"]) and not pid_alive(info["child"]), 10)
    assert not ffmpeg_hub.running("H1")


def test_idle_stop_kills_ffmpeg(ffmpeg_hub):
    ffmpeg_hub.touch_hls("H1")
    info = _started(ffmpeg_hub, "H1")
    assert wait_until(lambda: not pid_alive(info["pid"]) and not pid_alive(info["child"]), 10)
    assert not ffmpeg_hub.dir_for("H1").exists(), "segments are removed with the stream"


# ---------------------------------------------------------------- RTSP relay (TLS + Digest)

def tls_server_ctx(tmp_path) -> ssl.SSLContext:
    pairing.make_cert("printer", ["127.0.0.1"], tmp_path / "pcert")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "pcert" / "cert.pem", tmp_path / "pcert" / "key.pem")
    return ctx


def tls_listener(tmp_path):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    return srv, tls_server_ctx(tmp_path)


def _read_msg(f) -> tuple[str, dict]:
    first = f.readline().decode().strip()
    headers = {}
    while True:
        line = f.readline().decode().strip()
        if not line:
            return first, headers
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()


def test_relay_answers_digest_challenge_with_rewritten_uri(tmp_path):
    srv, ctx = tls_listener(tmp_path)
    port = srv.getsockname()[1]
    seen = {}

    def printer():
        conn, _ = srv.accept()
        with ctx.wrap_socket(conn, server_side=True) as s:
            f = s.makefile("rb")
            seen["first"] = _read_msg(f)
            s.sendall(b'RTSP/1.0 401 Unauthorized\r\nCSeq: 0\r\n'
                      b'WWW-Authenticate: Digest realm="LIVE555 Streaming Media", nonce="abc123"\r\n\r\n')
            seen["second"] = _read_msg(f)
            s.sendall(b"RTSP/1.0 200 OK\r\nCSeq: 1\r\nPublic: DESCRIBE\r\n\r\n")
            time.sleep(0.5)
    t = threading.Thread(target=printer, daemon=True)
    t.start()

    relay = camera.RtspRelay("127.0.0.1", CODE, port)
    local = relay.start()
    try:
        with socket.create_connection(("127.0.0.1", local), timeout=5) as c:
            c.sendall(f"OPTIONS rtsp://127.0.0.1:{local}/streaming/live/1 RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
            reply = c.recv(4096)
    finally:
        relay.stop()
        srv.close()
    assert reply.startswith(b"RTSP/1.0 200 OK")
    assert seen["first"][0] == f"DESCRIBE rtsps://127.0.0.1:{port}/streaming/live/1 RTSP/1.0"
    line, headers = seen["second"]
    uri = f"rtsps://127.0.0.1:{port}/streaming/live/1"
    assert line == f"OPTIONS {uri} RTSP/1.0"
    md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731
    expect = md5(f"{md5(f'bblp:LIVE555 Streaming Media:{CODE}')}:abc123:{md5(f'OPTIONS:{uri}')}")
    assert f'response="{expect}"' in headers["authorization"]
    assert 'username="bblp"' in headers["authorization"]


# ---------------------------------------------------------------- port-6000 JPEG stream

def jpeg(n: int) -> bytes:
    return b"\xff\xd8\xff\xe0" + bytes([n]) * 200 + b"\xff\xd9"


def test_auth_packet_layout():
    p = camera.auth_packet(CODE)
    assert len(p) == 80
    assert struct.unpack("<4I", p[:16]) == (0x40, 0x3000, 0, 0)
    assert p[16:48] == b"bblp" + b"\0" * 28
    assert p[48:80] == CODE.encode() + b"\0" * (32 - len(CODE))


@pytest.fixture
def jpeg_printer(tmp_path):
    """Fake P1/A1 camera on TLS: checks the auth packet, sends 3 frames 0.3 s apart, then holds the line."""
    srv, ctx = tls_listener(tmp_path)
    state = {"auth": [], "conns": 0}

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            state["conns"] += 1
            try:
                s = ctx.wrap_socket(conn, server_side=True)
                buf = b""
                while len(buf) < 80:
                    d = s.recv(80 - len(buf))
                    if not d:
                        raise ConnectionError
                    buf += d
                state["auth"].append(buf)
                if buf != camera.auth_packet(CODE):
                    s.close()
                    continue
                for n in range(1, 4):
                    body = jpeg(n)
                    s.sendall(struct.pack("<I", len(body)) + b"\0" * 12 + body)
                    time.sleep(0.3)
                time.sleep(30)
            except (OSError, ConnectionError):
                pass
    threading.Thread(target=serve, daemon=True).start()
    yield srv.getsockname()[1], state
    srv.close()


def serve_app(app):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    assert wait_until(lambda: server.started, 10)
    return server, t, f"http://127.0.0.1:{port}"


def passthrough(fn):
    return fn


def parts(stream, count):
    buf, out = b"", []
    for chunk in stream.iter_bytes():
        buf += chunk
        while True:
            m = re.match(rb"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: (\d+)\r\n\r\n", buf)
            if not m:
                break
            n = int(m.group(1))
            if len(buf) < m.end() + n + 2:
                break
            out.append(buf[m.end():m.end() + n])
            buf = buf[m.end() + n + 2:]
        if len(out) >= count:
            return out
    return out


def test_mjpeg_route_streams_frames_and_releases_on_disconnect(printers, tmp_path, jpeg_printer):
    port, state = jpeg_printer
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", idle_stop=0.2, jpeg_port=port)
    server, t, base = serve_app(Starlette(routes=camera.routes(hub, passthrough)))
    try:
        with httpx.stream("GET", f"{base}/api/printers/P1/camera.mjpeg", timeout=10) as r:
            assert r.status_code == 200
            assert r.headers["content-type"] == "multipart/x-mixed-replace; boundary=frame"
            got = parts(r, 3)
        assert got == [jpeg(1), jpeg(2), jpeg(3)]
        assert state["auth"] == [camera.auth_packet(CODE)]
        assert wait_until(lambda: not hub.running("P1"), 5), "stops after the last viewer disconnects"
    finally:
        hub.shutdown()
        server.should_exit = True
        t.join(5)


def test_mjpeg_source_never_sends_faster_than_5_fps(printers, tmp_path, jpeg_printer, monkeypatch):
    port, _ = jpeg_printer
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", jpeg_port=port)
    monkeypatch.setattr(camera, "MJPEG_MIN_INTERVAL", 0.5)
    server, t, base = serve_app(Starlette(routes=camera.routes(hub, passthrough)))
    try:
        t0 = time.monotonic()
        with httpx.stream("GET", f"{base}/api/printers/P1/camera.mjpeg", timeout=10) as r:
            got = parts(r, 2)
        assert len(got) == 2 and time.monotonic() - t0 >= 0.5
    finally:
        hub.shutdown()
        server.should_exit = True
        t.join(5)


# ---------------------------------------------------------------- HLS route

def test_hls_route_serves_only_playlist_and_segments(fake_hub):
    c = TestClient(Starlette(routes=camera.routes(fake_hub, passthrough)))
    d = fake_hub.dir_for("H1")
    d.mkdir(parents=True)
    (d / "index.m3u8").write_bytes(b"#EXTM3U\n")
    (d / "seg00001.ts").write_bytes(b"\x47" * 188)
    (d / "argv.json").write_text("{}")

    r = c.get("/api/printers/H1/camera/index.m3u8")
    assert r.status_code == 200 and r.text == "#EXTM3U\n"
    assert r.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    r = c.get("/api/printers/H1/camera/seg00001.ts")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp2t"
    assert c.get("/api/printers/H1/camera/seg99999.ts").status_code == 404
    for bad in ("argv.json", "%2E%2E%2F%2E%2E%2Fsecret.ts", "..%2Findex.m3u8", "sub%2Fseg1.ts", "x.ts.txt"):
        r = c.get(f"/api/printers/H1/camera/{bad}")
        assert (r.status_code, r.json()["error"]) == (400, "bad_request"), bad
    assert c.get("/api/printers/P1/camera/index.m3u8").status_code == 404  # MJPEG printer
    assert c.get("/api/printers/zz/camera/index.m3u8").json()["error"] == "not_found"
    assert c.get("/api/printers/N1/camera/index.m3u8").json()["error"] == "not_configured"
    assert c.get("/api/printers/H1/camera.mjpeg").status_code == 404  # HLS printer


def test_hls_playlist_not_ready_gives_503(fake_hub, monkeypatch):
    monkeypatch.setattr(camera, "HLS_START_WAIT", 0.3)
    c = TestClient(Starlette(routes=camera.routes(fake_hub, passthrough)))
    r = c.get("/api/printers/H1/camera/index.m3u8")
    assert r.status_code == 503 and r.json()["error"] == "camera_unavailable"


def test_camera_routes_need_the_token(tmp_path, monkeypatch, fake_hub):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({})
    c = TestClient(create_app(sm=object(), camera_hub=fake_hub))
    assert c.get("/api/printers/H1/camera/index.m3u8").status_code == 401
    assert c.get("/api/printers/P1/camera.mjpeg").status_code == 401
    tok = pairing.redeem_code(pairing.issue().code)
    d = fake_hub.dir_for("H1")
    d.mkdir(parents=True)
    (d / "index.m3u8").write_text("#EXTM3U\n")
    r = c.get("/api/printers/H1/camera/index.m3u8", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200


# ---------------------------------------------------------------- review round 1

class SlowStopSource(FakeSource):
    stopping = threading.Event()

    def stop(self):
        SlowStopSource.stopping.set()
        time.sleep(1.5)
        super().stop()


def test_slow_stop_of_one_printer_does_not_block_another(printers, tmp_path):
    FakeSource.instances = []
    SlowStopSource.stopping = threading.Event()
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", idle_stop=0.05, hls_window=5,
                     sources={"hls": FakeSource, "mjpeg": SlowStopSource})
    try:
        hub.acquire("P1")
        hub.release("P1")
        assert SlowStopSource.stopping.wait(2)
        t0 = time.monotonic()
        hub.touch_hls("H1")
        hub.acquire("H1")
        hub.release("H1")
        hub.release("P1")  # a stray release is harmless and never waits
        assert time.monotonic() - t0 < 0.5
        # the same printer's next viewer waits for its old source to finish stopping, then gets a new one
        new = hub.acquire("P1")
        assert new is not FakeSource.instances[0] and FakeSource.instances[0].stopped == 1
    finally:
        hub.shutdown()


def test_unexpected_error_is_json_internal(printers, tmp_path):
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", ffmpeg=["no-such-ffmpeg-binary"])
    try:
        c = TestClient(Starlette(routes=camera.routes(hub, passthrough)))
        r = c.get("/api/printers/H1/camera/index.m3u8")
        assert r.status_code == 500 and r.json() == {"error": "internal", "message": "internal error"}
        assert not hub.running("H1")
    finally:
        hub.shutdown()


def test_mjpeg_stream_ends_when_server_is_stopping(printers, tmp_path, jpeg_printer):
    port, _ = jpeg_printer
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", jpeg_port=port)
    server, t, base = serve_app(Starlette(routes=camera.routes(hub, passthrough)))
    try:
        with httpx.stream("GET", f"{base}/api/printers/P1/camera.mjpeg", timeout=10) as r:
            it = r.iter_bytes()
            next(it)
            hub.begin_stop()
            t0 = time.monotonic()
            for _ in it:  # the body must end by itself
                pass
            assert time.monotonic() - t0 < 3
        assert wait_until(lambda: hub._refs.get("P1") is None, 2), "the viewer was counted out"
        r = httpx.get(f"{base}/api/printers/P1/camera.mjpeg", timeout=5)
        assert r.status_code == 503 and r.json()["error"] == "camera_unavailable"
    finally:
        hub.shutdown()
        server.should_exit = True
        t.join(5)


class FeedSock:
    def __init__(self, data: bytes):
        self.data = data

    def recv(self, n):
        d, self.data = self.data[:n], self.data[n:]
        return d


def test_rtsp_reads_are_capped():
    with pytest.raises(ConnectionError):
        camera._read_rtsp(FeedSock(b"RTSP/1.0 200 OK\r\nX: " + b"a" * 70000 + b"\r\n\r\n"), b"")
    with pytest.raises(ConnectionError):
        camera._read_rtsp(FeedSock(b"RTSP/1.0 200 OK\r\nContent-Length: 2000000\r\n\r\n" + b"b" * 10), b"")
    msg, rest = camera._read_rtsp(FeedSock(b"RTSP/1.0 200 OK\r\nContent-Length: 3\r\n\r\nabcXYZ"), b"")
    assert msg.endswith(b"\r\n\r\nabc") and rest == b"XYZ"


def test_relay_drops_a_silent_printer(tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "UPSTREAM_TIMEOUT", 0.5)
    srv, ctx = tls_listener(tmp_path)

    def printer():
        conn, _ = srv.accept()
        with ctx.wrap_socket(conn, server_side=True) as s:
            f = s.makefile("rb")
            _read_msg(f)
            s.sendall(b'RTSP/1.0 401 Unauthorized\r\nCSeq: 0\r\n'
                      b'WWW-Authenticate: Digest realm="r", nonce="n"\r\n\r\n')
            _read_msg(f)
            time.sleep(10)  # never answers
    threading.Thread(target=printer, daemon=True).start()
    relay = camera.RtspRelay("127.0.0.1", CODE, srv.getsockname()[1])
    local = relay.start()
    try:
        with socket.create_connection(("127.0.0.1", local), timeout=5) as c:
            c.sendall(f"OPTIONS rtsp://127.0.0.1:{local}/streaming/live/1 RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
            t0 = time.monotonic()
            assert c.recv(4096) == b""  # the relay hung up on us
            assert time.monotonic() - t0 < 3
    finally:
        relay.stop()
        srv.close()


def test_non_ascii_access_code_is_refused_and_never_logged(caplog):
    bad = "cødé1234"
    with pytest.raises(ValueError) as e:
        camera.auth_packet(bad)
    assert bad not in str(e.value)
    with pytest.raises(ValueError):
        camera.auth_packet("x" * 33)


def test_mjpeg_source_with_unusable_code_stops_without_retrying(tmp_path, jpeg_printer, caplog):
    port, state = jpeg_printer
    bad = "cødé1234"
    hub = camera.Hub(lookup=lambda s: None, runtime_dir=tmp_path / "run", jpeg_port=port)
    src = camera.MjpegSource(Printer("P9", "x", "C12", "127.0.0.1", bad, True), hub)
    with caplog.at_level("DEBUG"):
        src.start()
        assert wait_until(lambda: not src.alive(), 5)
        src.stop()
    assert state["auth"] == []
    assert bad not in caplog.text and "ValueError" in caplog.text


# ---------------------------------------------------------------- final review

def test_mjpeg_without_a_first_frame_is_503(printers, tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "HLS_START_WAIT", 0.5)
    hub = camera.Hub(lookup=printers.get, runtime_dir=tmp_path / "run", idle_stop=0.1, jpeg_port=free_port())
    try:
        c = TestClient(Starlette(routes=camera.routes(hub, passthrough)))
        r = c.get("/api/printers/P1/camera.mjpeg")
        assert r.status_code == 503 and r.json()["error"] == "camera_unavailable"
        assert hub._refs.get("P1") is None, "the viewer was counted out"
        assert wait_until(lambda: not hub.running("P1"), 3)
    finally:
        hub.shutdown()


def test_acquire_restarts_the_source_when_ip_or_code_changes(fake_hub, printers):
    first = fake_hub.acquire("P1")
    assert fake_hub.acquire("P1") is first                       # same target: shared
    printers["P1"] = Printer("P1", "Garage P1S", "C12", "10.0.0.9", CODE, True)
    second = fake_hub.acquire("P1")
    assert second is not first and first.stopped == 1 and second.started == 1
    printers["P1"] = Printer("P1", "Garage P1S", "C12", "10.0.0.9", "24681357", True)
    third = fake_hub.acquire("P1")
    assert third is not second and second.stopped == 1
    assert fake_hub._refs["P1"] == 4


def test_touch_hls_restarts_the_source_when_ip_or_code_changes(fake_hub, printers):
    fake_hub.hls_window = 5
    first = fake_hub.touch_hls("H1")
    assert fake_hub.touch_hls("H1") is first
    printers["H1"] = Printer("H1", "Office H2D", "O1D", "127.0.0.1", "24681357", True)
    second = fake_hub.touch_hls("H1")
    assert second is not first and first.stopped == 1 and second.alive()
    assert fake_hub.running("H1")
