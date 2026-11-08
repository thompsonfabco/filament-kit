import json
import socket

import pytest

from fksync import client
from tls_helper import TlsServer, make_cert

FP = "ab" * 32


def test_parse_link_two_ips():
    link = (f"fkit://pair?h=fk-server.local&p=8710&t=tok%2Fen_1&fp={FP.upper()}"
            "&ip=192.168.1.20&ip=10.0.0.5")
    got = client.parse_link(link)
    assert got == client.PairLink(host="fk-server.local", port=8710, token="tok/en_1", fp=FP,
                                  ips=["192.168.1.20", "10.0.0.5"])
    assert client.parse_link("  " + link + "\n").ips == ["192.168.1.20", "10.0.0.5"]


@pytest.mark.parametrize("bad", [
    "https://fk-server.local:8710/",
    "fkit://other?h=a&p=1&t=x&fp=" + FP,
    "fkit://pair?h=a&p=1&t=x",                       # no fp
    "fkit://pair?h=a&p=0&t=x&fp=" + FP,              # bad port
    "fkit://pair?h=a&p=1&t=x&fp=1234",               # short fp
    "fkit://pair?h=a&h=b&p=1&t=x&fp=" + FP,          # two hosts
    "fkit://pair?h=a&p=1&fp=" + FP,                  # no token
    "fk-server.local",
])
def test_parse_link_rejects(bad):
    with pytest.raises(ValueError):
        client.parse_link(bad)


@pytest.fixture
def certs(tmp_path):
    return make_cert(tmp_path / "a", "a"), make_cert(tmp_path / "b", "b")


def _cfg(server, fp, host=None, ips=()):
    return {"host": host or server.host, "port": server.port, "fp": fp, "ips": list(ips)}


def test_fetch_fingerprint(certs):
    (cert, key, fp), _ = certs
    with TlsServer(cert, key) as srv:
        assert client.fetch_fingerprint("127.0.0.1", srv.port, timeout=5) == fp
        assert client.fetch_peer("localhost", srv.port, timeout=5) == (fp, "127.0.0.1")
        assert srv.requests == []


def test_fetch_fingerprint_offline():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(client.Offline):
        client.fetch_fingerprint("127.0.0.1", port, timeout=2)


def test_matching_fp_works_and_sends_token(certs):
    (cert, key, fp), _ = certs

    def respond(m, p, b):
        if p == "/api/sync/state":
            return 200, "application/json", {"owner": None, "you": "dev1", "build": None}
        if p.startswith("/api/sync/build"):
            return 200, "application/zip", b"PK-zipbytes"
        if p.startswith("/api/sync/live"):
            return 200, "application/json", {"live_hash": "h"}
        return 200, "application/json", {"name": "fk", "api": 1}

    with TlsServer(cert, key, respond=respond) as srv:
        c = client.Client(_cfg(srv, fp), "secret-token", timeout=5)
        assert c.info()["name"] == "fk"
        assert c.state()["you"] == "dev1"
        assert c.build("20261102-010203") == b"PK-zipbytes"
        assert c.upload("live", b"zip", user_id="123") == {"live_hash": "h"}
        reqs = srv.requests
        assert [r["path"] for r in reqs] == ["/api/info", "/api/sync/state", "/api/sync/build?stamp=20261102-010203",
                                             "/api/sync/live?user_id=123"]
        assert reqs[1]["auth"] == "Bearer secret-token"
        assert reqs[3]["method"] == "PUT" and reqs[3]["type"] == "application/zip" and reqs[3]["body"] == b"zip"
        # ruling S28: the stamp of a half-finished install rides along as `partial`
        assert c.upload("live", b"zip", user_id="123", partial="20261102-010203") == {"live_hash": "h"}
        assert srv.requests[-1]["path"] == "/api/sync/live?user_id=123&partial=20261102-010203"


def test_wrong_fp_cert_changed_and_no_bytes_sent(certs):
    (cert, key, fp), (_, _, other_fp) = certs
    with TlsServer(cert, key) as srv:
        c = client.Client(_cfg(srv, other_fp), "secret-token", timeout=5)
        with pytest.raises(client.CertChanged) as ei:
            c.state()
        assert ei.value.actual == fp and ei.value.expected == other_fp
        assert srv.requests == []
        assert srv.wait_received() and all(r == b"" for r in srv.received)


def test_mismatch_moves_to_next_address_without_sending(certs):
    (cert_a, key_a, fp_a), (cert_b, key_b, fp_b) = certs
    with TlsServer(cert_b, key_b, host="127.0.0.1") as good:
        try:
            bad = TlsServer(cert_a, key_a, host="127.0.0.3", port=good.port)
        except OSError:
            pytest.skip("cannot bind 127.0.0.3 here")
        with bad:
            logged = []
            c = client.Client({"host": "127.0.0.3", "port": good.port, "fp": fp_b, "ips": ["127.0.0.1"]},
                              "secret-token", timeout=5, log=logged.append)
            assert c.info()["name"] == "fk"
            assert logged == ["certificate mismatch on 127.0.0.3, using 127.0.0.1"]
            assert bad.wait_received() and all(r == b"" for r in bad.received)
            assert bad.requests == []
            assert len(good.requests) == 1


def test_unreachable_host_then_ip(certs):
    (cert, key, fp), _ = certs
    with TlsServer(cert, key) as srv:
        c = client.Client({"host": "127.0.0.2", "port": srv.port, "fp": fp, "ips": ["127.0.0.1"]}, None, timeout=5)
        try:
            assert c.info()["name"] == "fk"
        except client.Offline:
            pytest.skip("127.0.0.2 reaches the 127.0.0.1 listener on this OS")
        assert srv.requests[0]["auth"] is None


def test_all_offline():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    c = client.Client({"host": "127.0.0.1", "port": port, "fp": FP, "ips": []}, "t", timeout=2)
    with pytest.raises(client.Offline):
        c.info()


def test_api_error_and_pair(certs):
    (cert, key, fp), _ = certs

    def respond(m, p, b):
        if p == "/api/pair":
            if json.loads(b)["code"] == "123456":
                return 200, "application/json", {"token": "new-token"}
            return 401, "application/json", {"error": "unauthorized", "message": "invalid code"}
        if p == "/api/sync/rebuild":
            return 409, "application/json", {"error": "other_pc", "message": "another PC syncs"}
        return 200, "application/json", {}

    with TlsServer(cert, key, respond=respond) as srv:
        c = client.Client(_cfg(srv, fp), None, timeout=5)
        assert c.pair("123456") == "new-token"
        with pytest.raises(client.ApiError) as ei:
            c.pair("000000")
        assert (ei.value.status, ei.value.code) == (401, "unauthorized")
        c2 = client.Client(_cfg(srv, fp), "t", timeout=5)
        with pytest.raises(client.ApiError) as ei:
            c2.rebuild("h")
        assert (ei.value.status, ei.value.code, ei.value.message) == (409, "other_pc", "another PC syncs")
        assert json.loads(srv.requests[-1]["body"]) == {"live_hash": "h"}


def test_heartbeat_and_fresh_upload(certs):
    """The heartbeat is a tiny JSON body (outcome, waiting_since, app), nothing else; a folder's first
    live upload carries fresh=1."""
    (cert, key, fp), _ = certs

    def respond(m, p, b):
        if p == "/api/sync/heartbeat":
            return 200, "application/json", {"ok": True}
        return 200, "application/json", {"live_hash": "h", "fresh": True}

    with TlsServer(cert, key, respond=respond) as srv:
        c = client.Client(_cfg(srv, fp), "secret-token", timeout=5)
        assert c.heartbeat("studio_running", 1_800_000_000.0, "Bambu Studio") == {"ok": True}
        r = srv.requests[-1]
        assert r["method"] == "POST" and r["type"] == "application/json" and r["auth"] == "Bearer secret-token"
        assert json.loads(r["body"]) == {"outcome": "studio_running", "waiting_since": 1_800_000_000.0,
                                         "app": "Bambu Studio"}
        assert len(r["body"]) < 1024
        c.heartbeat("up_to_date")
        assert json.loads(srv.requests[-1]["body"]) == {"outcome": "up_to_date", "waiting_since": None, "app": None}
        assert c.upload("live", b"zip", user_id="123", fresh=True)["fresh"] is True
        assert srv.requests[-1]["path"] == "/api/sync/live?user_id=123&fresh=1"
