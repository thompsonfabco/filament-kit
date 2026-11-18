"""The printer-side tag service (printer-pack/lasttag/lasttag.py) over HTTPS: the certificate it makes itself with the
openssl program, the listener, and the plain-HTTP fallback when none can be made (R82 section 2 point 5, section 10
point 5).

Run with the server's test environment: `server/.venv/Scripts/python -m pytest printer-pack/tests`.
"""
import hashlib
import http.client
import importlib.util
import json
import os
import shutil
import ssl
import sys
import threading
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "lasttag" / "lasttag.py"
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="the openssl program is not installed")


@pytest.fixture
def lasttag(tmp_path, monkeypatch):
    """lasttag.py loaded from a copy beside an allow file, with nfc2klipper's IPC client replaced by a stub."""
    class Client:
        def __init__(self, path):
            pass

        def send_request(self, request):
            return {"status": "ok", "nfc_id": "04:aa:bb:cc", "spool_id": None, "read_at": None}
    lib, ipc = types.ModuleType("lib"), types.ModuleType("lib.ipc")
    ipc.IPCClient = Client
    lib.ipc = ipc
    monkeypatch.setitem(sys.modules, "lib", lib)
    monkeypatch.setitem(sys.modules, "lib.ipc", ipc)
    run = tmp_path / "run"
    run.mkdir()
    shutil.copy(SCRIPT, run / "lasttag.py")
    (run / "allow").write_text("127.0.0.1\n")
    spec = importlib.util.spec_from_file_location("lasttag_under_test", run / "lasttag.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "tls_dir", lambda: str(tmp_path / "state" / "tls"))
    conf = os.environ.get("OPENSSL_CONF")
    if conf and not os.path.exists(conf):       # a dev PC whose environment names a configuration that is not there
        (tmp_path / "openssl.cnf").write_text("[req]\ndistinguished_name = dn\n[dn]\n")
        monkeypatch.setenv("OPENSSL_CONF", str(tmp_path / "openssl.cnf"))
    return mod


def _serve(mod, context):
    srv = mod.Server(("127.0.0.1", 0), mod.Handler)
    srv.context = context
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _client_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@needs_openssl
def test_the_certificate_is_made_with_openssl_and_kept(lasttag, tmp_path):
    got = lasttag.tls_context()
    assert got is not None
    ctx, fp = got
    cert, key = tmp_path / "state" / "tls" / "cert.pem", tmp_path / "state" / "tls" / "key.pem"
    assert cert.is_file() and key.is_file()
    if os.name != "nt":
        assert (key.stat().st_mode & 0o777) == 0o600
    assert fp == hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
    assert not list((tmp_path / "state" / "tls").glob("*.new"))
    assert lasttag.tls_context()[1] == fp                      # the next start keeps it: the Hub's pin stays good


@needs_openssl
def test_the_service_answers_over_https_with_that_certificate_and_not_over_plain_http(lasttag):
    ctx, fp = lasttag.tls_context()
    srv = _serve(lasttag, ctx)
    try:
        c = http.client.HTTPSConnection("127.0.0.1", srv.server_port, context=_client_context(), timeout=10)
        c.connect()
        assert hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest() == fp
        c.request("GET", "/last-tag")
        r = c.getresponse()
        assert r.status == 200 and json.loads(r.read())["nfc_id"] == "04:aa:bb:cc"
        c.close()
        c = http.client.HTTPSConnection("127.0.0.1", srv.server_port, context=_client_context(), timeout=10)
        c.request("GET", "/elsewhere")
        assert c.getresponse().status == 404
        c.close()
        plain = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
        with pytest.raises((http.client.HTTPException, OSError)):
            plain.request("GET", "/last-tag")
            plain.getresponse()
        plain.close()
    finally:
        srv.shutdown()
        srv.server_close()


@needs_openssl
def test_an_address_not_on_the_allow_file_gets_403_over_https(lasttag):
    lasttag.ALLOW.clear()
    ctx, _fp = lasttag.tls_context()
    srv = _serve(lasttag, ctx)
    try:
        c = http.client.HTTPSConnection("127.0.0.1", srv.server_port, context=_client_context(), timeout=10)
        c.request("GET", "/last-tag")
        assert c.getresponse().status == 403
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_without_openssl_it_serves_plain_http_and_says_so(lasttag, monkeypatch, capsys):
    def no_openssl(*a, **k):
        raise FileNotFoundError(2, "No such file or directory", "openssl")
    monkeypatch.setattr(lasttag.subprocess, "run", no_openssl)
    assert lasttag.tls_context() is None
    assert "serving plain HTTP" in capsys.readouterr().err
    srv = _serve(lasttag, None)
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
        c.request("GET", "/last-tag")
        assert c.getresponse().status == 200
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_port_defaults_to_5002(lasttag):
    assert lasttag.PORT == 5002
