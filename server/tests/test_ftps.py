"""FTPS client against a fake printer (implicit TLS, NLST only, data-channel session reuse required)."""
import logging
import ssl

import pytest

from fakes.fake_certs import Leaf
from fakes.fake_ftps import FakeFtps
from filament_kit.bridge import ftps, registry, tlspin
from filament_kit.bridge.registry import Printer

CODE = "13572468"
SERIAL = "0948AB123456789"


@pytest.fixture
def leaf():
    return Leaf(SERIAL)


@pytest.fixture
def printer():
    p = Printer(serial=SERIAL, name="H2D", model="H2D", ip="127.0.0.1", access_code=CODE, configured=True)
    registry.upsert(p)
    return p


@pytest.fixture
def fake(leaf, tmp_path, monkeypatch):
    f = FakeFtps(leaf, tmp_path / "sd", CODE)
    monkeypatch.setattr(ftps, "PORT", f.port)
    yield f
    f.close()


def test_upload_nlst_download_delete(fake, printer, leaf):
    data = bytes(range(256)) * 300
    with ftps.Client(printer) as c:
        c.upload("/cache/fk-calib-x.gcode.3mf", data)
        assert "fk-calib-x.gcode.3mf" in [n.rsplit("/", 1)[-1] for n in c.nlst("/cache")]
        assert c.download("/cache/fk-calib-x.gcode.3mf") == data
        c.delete("/cache/fk-calib-x.gcode.3mf")
        assert c.nlst("/cache") == []
    assert (fake.root / "cache").exists() and not (fake.root / "cache" / "fk-calib-x.gcode.3mf").exists()
    # every data channel resumed the session. Three carry data; the empty listing's can end before the server's handshake
    # does (test_failed_data_channel_shutdown_is_not_a_failed_transfer), so it isn't always counted.
    assert fake.data_conns >= 3 and fake.refused_data == 0
    assert "MLSD" not in fake.commands
    assert registry.load()[SERIAL].cert_fp == leaf.fp                 # pinned on first use


def test_failed_data_channel_shutdown_is_not_a_failed_transfer(fake, printer, leaf, monkeypatch):
    # the printer closing an empty listing's channel can make the TLS shutdown fail; the 226 decides
    def broken(self):
        raise ssl.SSLError("[SSL: SHUTDOWN_WHILE_IN_INIT] shutdown while in init")
    monkeypatch.setattr(ssl.SSLSocket, "unwrap", broken)
    with ftps.Client(printer) as c:
        assert c.nlst("/cache") == []
        assert c.nlst("/") == ["cache"]


def test_pinned_leaf_accepted(fake, printer, leaf):
    registry.pin(SERIAL, leaf.fp)
    printer.cert_fp = leaf.fp
    with ftps.Client(printer) as c:
        assert c.nlst("/") == ["cache"]


def test_changed_leaf_no_login(fake, printer, caplog):
    registry.pin(SERIAL, "ab" * 32)
    printer.cert_fp = "ab" * 32
    caplog.set_level(logging.DEBUG)
    with pytest.raises(tlspin.CertChanged):
        with ftps.Client(printer):
            pass
    assert fake.connections == 1
    assert "USER" not in fake.commands and "PASS" not in fake.commands   # the Access Code was never sent
    assert CODE not in caplog.text


def test_other_printers_leaf_refused_on_first_use(tmp_path, printer, monkeypatch):
    f = FakeFtps(Leaf("0948AB999999999"), tmp_path / "sd2", CODE)
    monkeypatch.setattr(ftps, "PORT", f.port)
    try:
        with pytest.raises(tlspin.CertChanged):
            ftps.Client(printer).__enter__()
        assert "PASS" not in f.commands
    finally:
        f.close()


def test_errors_are_ftps_errors(fake, printer):
    with ftps.Client(printer) as c:
        with pytest.raises(ftps.FtpsError):
            c.download("/cache/missing.3mf")
        with pytest.raises(ftps.FtpsError):
            c.delete("/cache/missing.3mf")


def test_wrong_code(fake, printer):
    printer.access_code = "00000000"
    with pytest.raises(ftps.FtpsError):
        with ftps.Client(printer):
            pass


def test_unreachable(printer, monkeypatch):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setattr(ftps, "PORT", port)
    with pytest.raises(ftps.FtpsError):
        with ftps.Client(printer, timeout=2):
            pass


def test_repr_has_no_code(printer):
    assert CODE not in repr(ftps.Client(printer))
