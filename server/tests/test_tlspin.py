"""Per-printer TLS pinning: trust on first use, CN == serial, and no Access Code to a changed leaf.

Every printer here is a local TLS server (127.0.0.1) or the fake paho client; nothing touches real hardware."""
import hashlib
import io
import logging
import socket
import sys
import threading
import time

import pytest
from cryptography.hazmat.primitives.serialization import Encoding
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fakes.fake_certs import Leaf
from filament_kit import cli, config, pairing
from filament_kit.api import create_app
from filament_kit.bridge import camera, connection, registry, tlspin
from filament_kit.bridge.connection import Manager
from filament_kit.bridge.registry import Printer
from test_connection import FakeClient

CODE = "13572468"
SERIAL = "0948AB123456789"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)


def wait_until(cond, timeout=10.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class TlsPrinter:
    """A local TLS server presenting `leaf`; records the bytes each connection sent after the handshake.
    `reply(data)` may return bytes to send back (e.g. a camera frame)."""

    def __init__(self, leaf: Leaf, tmp_path, reply=None, hold=1.0):
        self.ctx = leaf.server_ctx(tmp_path / "tls")
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.received: list[bytes] = []
        self.handshakes = 0
        self.reply, self.hold = reply, hold
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        data = b""
        try:
            s = self.ctx.wrap_socket(conn, server_side=True)
            self.handshakes += 1
            s.settimeout(self.hold)
            while True:
                d = s.recv(4096)
                if not d:
                    break
                data += d
                if self.reply:
                    out = self.reply(data)
                    if out:
                        s.sendall(out)
        except OSError:
            pass
        finally:
            self.received.append(data)
            conn.close()

    def close(self):
        self.srv.close()


def printer(fp="", serial=SERIAL, ip="127.0.0.1", model="O1D"):
    return Printer(serial, "Office H2D", model, ip, CODE, True, cert_fp=fp)


# ---------------------------------------------------------------- tlspin itself

def test_leaf_fp_is_lowercase_sha256_hex_of_the_der_leaf(tmp_path):
    leaf = Leaf(SERIAL)
    srv = TlsPrinter(leaf, tmp_path)
    try:
        fp = tlspin.leaf_fp("127.0.0.1", srv.port)
    finally:
        srv.close()
    assert fp == hashlib.sha256(leaf.der).hexdigest() == leaf.fp
    assert fp == fp.lower() and ":" not in fp and len(fp) == 64
    pem = leaf.cert.public_bytes(Encoding.PEM)
    assert fp == pairing.fingerprint(pem)          # same format as the server's own fingerprint helper


def test_leaf_fp_unreachable_raises_oserror():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(OSError):
        tlspin.leaf_fp("127.0.0.1", port, timeout=2)


def test_context_does_not_verify_ca_or_hostname():
    ctx = tlspin.context()
    assert ctx.verify_mode == tlspin.ssl.CERT_NONE and ctx.check_hostname is False


def test_check_pins_on_first_use_and_refuses_a_changed_leaf(tmp_path):
    registry.upsert(printer())
    a, b = Leaf(SERIAL), Leaf(SERIAL)
    sa, sb = TlsPrinter(a, tmp_path), TlsPrinter(b, tmp_path)
    try:
        p = registry.load()[SERIAL]
        tlspin.check(p, sa.port)
        assert p.cert_fp == a.fp and registry.load()[SERIAL].cert_fp == a.fp
        tlspin.check(registry.load()[SERIAL], sa.port)            # same leaf: fine
        with pytest.raises(tlspin.CertChanged) as e:
            tlspin.check(registry.load()[SERIAL], sb.port)        # any port: Task 4 uses it for FTPS 990
        assert (e.value.expected, e.value.actual) == (a.fp, b.fp)
        assert registry.load()[SERIAL].cert_fp == a.fp            # a changed leaf never replaces the pin
    finally:
        sa.close()
        sb.close()


def test_leaf_with_another_serial_as_cn_is_refused_even_on_first_use(tmp_path):
    registry.upsert(printer())
    srv = TlsPrinter(Leaf("01P00A999999999"), tmp_path)
    try:
        with pytest.raises(tlspin.CertChanged) as e:
            tlspin.check(registry.load()[SERIAL], srv.port)
    finally:
        srv.close()
    assert e.value.expected == ""
    assert registry.load()[SERIAL].cert_fp == ""                  # nothing pinned


def test_leaf_without_cn_pins(tmp_path):
    registry.upsert(printer())
    leaf = Leaf(None)
    srv = TlsPrinter(leaf, tmp_path)
    try:
        tlspin.check(registry.load()[SERIAL], srv.port)
    finally:
        srv.close()
    assert registry.load()[SERIAL].cert_fp == leaf.fp


def test_pin_never_overwrites_and_clear_pin(tmp_path):
    registry.upsert(printer())
    assert registry.pin(SERIAL, "aa" * 32) == "aa" * 32
    assert registry.pin(SERIAL, "bb" * 32) == "aa" * 32           # the first pin wins
    assert registry.load()[SERIAL].cert_fp == "aa" * 32
    assert registry.clear_pin(SERIAL) and registry.load()[SERIAL].cert_fp == ""
    assert registry.pin("NOPE", "cc" * 32) == "cc" * 32 and "NOPE" not in registry.load()
    assert not registry.clear_pin("NOPE")


def test_rename_and_detected_keep_the_pin():
    registry.upsert(printer(fp="aa" * 32))
    registry.rename(SERIAL, "Shed")
    registry.detected(SERIAL, "10.0.0.9", "O1D", "x")
    assert registry.load()[SERIAL].cert_fp == "aa" * 32


def test_set_code_clears_the_pin():
    registry.upsert(printer(fp="aa" * 32))
    registry.set_code(SERIAL, "24681357", replace=True)
    assert registry.load()[SERIAL].cert_fp == ""


# ---------------------------------------------------------------- MQTT (fake paho client)

@pytest.fixture
def clients():
    return []


@pytest.fixture
def manager(clients):
    def factory(client_id):
        c = FakeClient(client_id)
        clients.append(c)
        return c
    m = Manager(client_factory=factory)
    yield m
    m.stop()


def test_first_connect_pins_the_leaf(manager, clients):
    leaf = Leaf(SERIAL)
    registry.upsert(printer(ip="10.0.0.5"))
    manager.sync()
    clients[0].connected(0, der=leaf.der)
    assert manager.state(SERIAL) == "connected"
    assert clients[0].password == CODE
    assert registry.load()[SERIAL].cert_fp == leaf.fp
    manager.sync()                                  # its own pin does not count as a re-add
    assert len(clients) == 1


def test_changed_leaf_is_cert_changed_and_the_code_is_never_sent(manager, clients, caplog):
    a, b = Leaf(SERIAL), Leaf(SERIAL)
    registry.upsert(printer(fp=a.fp, ip="10.0.0.5"))
    manager.sync()
    c = clients[0]
    with caplog.at_level(logging.DEBUG):
        c.connected(0, der=b.der)
    assert manager.state(SERIAL) == "cert_changed"
    assert c.password is None                       # the fake client never received the Access Code
    assert "disconnect" in c.calls                  # paho stops retrying
    c.dropped()
    assert manager.state(SERIAL) == "cert_changed"  # sticky until the printer is added again
    assert manager.wait_settled(SERIAL, 0.1) == "cert_changed"
    manager.sync()
    assert len(clients) == 1                        # no reconnect loop with the same pin
    assert b.fp in caplog.text and a.fp in caplog.text
    assert CODE not in caplog.text


def test_reconnect_to_a_changed_leaf_withdraws_the_code(manager, clients):
    a, b = Leaf(SERIAL), Leaf(SERIAL)
    registry.upsert(printer(ip="10.0.0.5"))
    manager.sync()
    c = clients[0]
    c.connected(0, der=a.der)
    assert c.password == CODE
    c.dropped()
    assert not c.socket_open(b.der)                 # paho's automatic reconnect lands on another leaf
    assert c.password is None and manager.state(SERIAL) == "cert_changed"


def test_cn_of_another_printer_is_refused_on_first_connect(manager, clients):
    registry.upsert(printer(ip="10.0.0.5"))
    manager.sync()
    clients[0].connected(0, der=Leaf("01P00A999999999").der)
    assert manager.state(SERIAL) == "cert_changed" and clients[0].password is None
    assert registry.load()[SERIAL].cert_fp == ""


def test_api_re_add_clears_the_pin_and_re_pins(monkeypatch):
    monkeypatch.setattr("filament_kit.api.FIRST_STATE_WAIT", 3.0)
    config.save({})
    pairing.make_cert("fkhost", [], config.paths().etc)
    a, b = Leaf(SERIAL), Leaf(SERIAL)
    presented = {"der": b.der}

    class Client(FakeClient):
        def connect_async(self, host, port, keepalive):
            super().connect_async(host, port, keepalive)
            threading.Timer(0.05, lambda: self.connected(0, der=presented["der"])).start()

    registry.upsert(printer(fp=a.fp, ip="10.0.0.5"))
    m = Manager(client_factory=Client)
    try:
        m.sync()
        assert m.wait_settled(SERIAL, 3) == "cert_changed"
        c = TestClient(create_app(object(), printers=m))
        c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
        r = c.get("/api/printers")
        assert r.json()["printers"][0]["state"] == "cert_changed" and CODE not in r.text
        r = c.post("/api/printers", json={"serial": SERIAL, "access_code": CODE})
        assert r.status_code == 200 and r.json()["printer"]["state"] == "connected"
        assert CODE not in r.text and b.fp not in r.text
        assert registry.load()[SERIAL].cert_fp == b.fp
    finally:
        m.stop()


def test_cli_re_add_clears_the_pin(monkeypatch):
    registry.upsert(printer(fp="aa" * 32, ip="10.0.0.5"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"5\n2\nOffice\n10.0.0.5\n{SERIAL}\n\n0\n0\n"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": CODE)
    assert cli.main(["config"]) == 0
    p = registry.load()[SERIAL]
    assert p.cert_fp == "" and p.access_code == CODE


# ---------------------------------------------------------------- MQTT (real paho, local TLS server)

def _real_manager(port):
    return Manager(client_factory=connection.paho_client, port=port)


def test_real_paho_sends_no_connect_to_a_changed_leaf(tmp_path):
    a, b = Leaf(SERIAL), Leaf(SERIAL)
    srv = TlsPrinter(b, tmp_path, hold=1.5)
    registry.upsert(printer(fp=a.fp))
    m = _real_manager(srv.port)
    try:
        m.sync()
        assert wait_until(lambda: m.state(SERIAL) == "cert_changed", 10)
        assert wait_until(lambda: srv.received, 10)
        time.sleep(3)                                  # longer than paho's first retry delay
    finally:
        m.stop()
        srv.close()
    assert srv.handshakes == 1                         # no retry loop
    for data in srv.received:
        assert CODE.encode() not in data
        assert not data.startswith(b"\x10")            # no MQTT CONNECT packet at all


def test_real_paho_sends_the_code_after_the_pin_matches(tmp_path):
    a = Leaf(SERIAL)
    srv = TlsPrinter(a, tmp_path, hold=1.0)
    registry.upsert(printer(fp=a.fp))
    m = _real_manager(srv.port)
    try:
        m.sync()
        assert wait_until(lambda: srv.received, 10)
    finally:
        m.stop()
        srv.close()
    assert srv.received[0].startswith(b"\x10") and CODE.encode() in srv.received[0]


def test_real_paho_first_connect_pins(tmp_path):
    a = Leaf(SERIAL)
    srv = TlsPrinter(a, tmp_path, hold=1.0)
    registry.upsert(printer())
    m = _real_manager(srv.port)
    try:
        m.sync()
        assert wait_until(lambda: registry.load()[SERIAL].cert_fp == a.fp, 10)
    finally:
        m.stop()
        srv.close()


# ---------------------------------------------------------------- camera (322 relay, 6000 JPEG)

def passthrough(fn):
    return fn


def test_mjpeg_source_sends_no_auth_packet_to_a_changed_leaf(tmp_path, caplog):
    a, b = Leaf(SERIAL), Leaf(SERIAL)
    srv = TlsPrinter(b, tmp_path)
    hub = camera.Hub(lookup=lambda s: None, runtime_dir=tmp_path / "run", jpeg_port=srv.port)
    src = camera.MjpegSource(printer(fp=a.fp, model="C12"), hub)
    try:
        with caplog.at_level(logging.DEBUG):
            src.start()
            assert wait_until(lambda: not src.alive(), 5)   # gives up: retrying cannot help
            src.stop()
    finally:
        srv.close()
    assert src.cert_changed
    assert all(d == b"" for d in srv.received) and srv.handshakes == 1
    assert CODE not in caplog.text


def test_rtsp_relay_sends_nothing_to_a_changed_leaf(tmp_path):
    a, b = Leaf(SERIAL), Leaf(SERIAL)
    srv = TlsPrinter(b, tmp_path)
    relay = camera.RtspRelay(printer(fp=a.fp), srv.port)
    local = relay.start()
    try:
        with socket.create_connection(("127.0.0.1", local), timeout=5) as c:
            c.sendall(b"OPTIONS rtsp://127.0.0.1/streaming/live/1 RTSP/1.0\r\nCSeq: 1\r\n\r\n")
            try:
                assert c.recv(4096) == b""                     # the relay hangs up ...
            except ConnectionResetError:                       # ... (Windows: with a reset)
                pass
        assert wait_until(lambda: srv.received, 5)
    finally:
        relay.stop()
        srv.close()
    assert relay.cert_changed
    assert srv.received == [b""]


def test_rtsp_relay_first_use_pins(tmp_path):
    a = Leaf(SERIAL)
    srv = TlsPrinter(a, tmp_path, hold=0.5)
    registry.upsert(printer())
    relay = camera.RtspRelay(registry.load()[SERIAL], srv.port)
    local = relay.start()
    try:
        with socket.create_connection(("127.0.0.1", local), timeout=5) as c:
            c.sendall(b"OPTIONS rtsp://127.0.0.1/streaming/live/1 RTSP/1.0\r\nCSeq: 1\r\n\r\n")
            assert wait_until(lambda: srv.received or registry.load()[SERIAL].cert_fp, 5)
    finally:
        relay.stop()
        srv.close()
    assert registry.load()[SERIAL].cert_fp == a.fp and not relay.cert_changed


class CertChangedSource:
    """A camera source whose upstream leaf did not match the pin."""

    def __init__(self, p, hub):
        self.printer, self.dir, self.cert_changed = p, hub.dir_for(p.serial), True

    def start(self):
        pass

    def stop(self):
        pass

    def alive(self):
        return False

    def frame(self):
        return 0, None


@pytest.mark.parametrize("path", ["/api/printers/H1/camera/index.m3u8", "/api/printers/P1/camera.mjpeg"])
def test_camera_routes_refuse_with_cert_changed_from_the_source(tmp_path, path):
    ps = {"H1": printer(serial="H1"), "P1": printer(serial="P1", model="C12")}
    hub = camera.Hub(lookup=ps.get, runtime_dir=tmp_path / "run",
                     sources={"hls": CertChangedSource, "mjpeg": CertChangedSource})
    try:
        r = TestClient(Starlette(routes=camera.routes(hub, passthrough))).get(path)
    finally:
        hub.shutdown()
    assert r.status_code == 409 and r.json()["error"] == "cert_changed"
    assert CODE not in r.text


@pytest.mark.parametrize("path", ["/api/printers/H1/camera/index.m3u8", "/api/printers/P1/camera.mjpeg"])
def test_camera_routes_refuse_when_the_manager_saw_a_changed_leaf(tmp_path, path):
    ps = {"H1": printer(serial="H1"), "P1": printer(serial="P1", model="C12")}
    started = []

    class Src(CertChangedSource):
        def __init__(self, p, hub):
            super().__init__(p, hub)
            started.append(p.serial)
    hub = camera.Hub(lookup=ps.get, runtime_dir=tmp_path / "run", sources={"hls": Src, "mjpeg": Src},
                     printer_state=lambda serial: "cert_changed")
    try:
        r = TestClient(Starlette(routes=camera.routes(hub, passthrough))).get(path)
    finally:
        hub.shutdown()
    assert r.status_code == 409 and r.json()["error"] == "cert_changed"
    assert started == []                               # nothing even tried to reach the printer


def test_camera_restarts_after_re_add_clears_the_pin(tmp_path):
    ps = {"P1": printer(serial="P1", model="C12", fp="aa" * 32)}
    made = []

    class Src(CertChangedSource):
        def __init__(self, p, hub):
            super().__init__(p, hub)
            made.append(self)
    hub = camera.Hub(lookup=ps.get, runtime_dir=tmp_path / "run", sources={"hls": Src, "mjpeg": Src})
    try:
        first = hub.acquire("P1")
        assert hub.acquire("P1") is first
        ps["P1"] = printer(serial="P1", model="C12", fp="")       # re-added: pin cleared
        assert hub.acquire("P1") is not first and len(made) == 2
    finally:
        hub.shutdown()
