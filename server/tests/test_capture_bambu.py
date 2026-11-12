"""tools/capture_bambu.py: the owner's read-only printer capture (spec P §6, plan P7). No network: a fake client."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "capture_bambu.py"
SERIAL = "0948ZZ0A0000999"
CODE = "Ab12Cd34"
IP = "198.51.100.109"     # synthetic (RFC 5737)
LEAF = b"synthetic-der-leaf"


@pytest.fixture(scope="module")
def cap():
    spec = importlib.util.spec_from_file_location("capture_bambu", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, json.dumps(payload).encode()


class FakeClient:
    """paho's Client as the script uses it: connect -> on_connect at loop_start; replies to publishes."""

    def __init__(self, client_id, *, accept=True, replies=None):
        self.client_id, self.accept = client_id, accept
        self.published, self.subscribed, self.calls = [], [], []
        self.replies = replies if replies is not None else REPLIES
        self.on_connect = self.on_message = self.on_socket_open = None
        self.leaf = LEAF                 # the DER leaf its socket presents

    def username_pw_set(self, user, password):
        self.user, self.password = user, password

    def tls_set_context(self, ctx):
        self.tls = ctx

    def connect(self, host, port, keepalive):
        self.host, self.port = host, port
        if self.on_socket_open:          # paho: after the TLS handshake, before CONNECT
            leaf = self.leaf
            self.on_socket_open(self, None, type("Sock", (), {"getpeercert": lambda s, binary_form=False: leaf})())

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos=0):
        body = json.loads(payload)
        self.published.append((topic, body))
        cmd = next(iter(body.values()))["command"]
        for p in self.replies.get(cmd, []):
            self.on_message(self, None, Msg(f"device/{SERIAL}/report", p))

    def loop_start(self):
        self.calls.append("loop_start")
        self.on_connect(self, None, {}, 0 if self.accept else 5, None)

    def loop_stop(self):
        self.calls.append("loop_stop")

    def disconnect(self):
        self.calls.append("disconnect")


REPLIES = {
    "pushall": [{"print": {"command": "push_status", "sn": SERIAL, "ipcam": {"rtsp_url": f"rtsps://{IP}/streaming"},
                           "net": {"info": [{"ip": IP, "mask": "255.255.255.0"}]},
                           "ams": {"ams": [{"id": "0", "tray": [{"id": "0"}]}], "tray_exist_bits": "f"},
                           "vir_slot": [{"id": "254"}, {"id": "255"}],
                           "upload": {"message": f"/sdcard/{SERIAL}/x and code {CODE}"},
                           f"x_{SERIAL}": 1}},
                {"print": {"command": "push_status", "mc_percent": 5}}],
    "get_version": [{"info": {"command": "get_version", "sequence_id": "0",
                              "module": [{"name": "n3f/0", "sn": SERIAL, "product_name": "AMS 2 PRO"},
                                         {"name": "ota", "sn": SERIAL}]}}],
}


def env_file(tmp_path, body=None):
    p = tmp_path / "env"
    p.write_text(body if body is not None else
                 f"# scanner env\nSPOOLMAN_URL=http://localhost:7912\nPRINTER_IP={IP}\n"
                 f"export PRINTER_SERIAL=\"{SERIAL}\"\nPRINTER_CODE='{CODE}'\nAUTH_TOKEN=secret-token\n",
                 encoding="utf-8")
    return p


def run(cap, tmp_path, *extra, factory=None, probe=lambda host: LEAF):
    made = []

    def f(cid):
        c = (factory or FakeClient)(cid)
        made.append(c)
        return c
    out = tmp_path / "out" / "h2d.json"
    rc = cap.main(["--env", str(env_file(tmp_path)), "--out", str(out), *extra], client_factory=f,
                  sleep=lambda s: None, probe=probe)
    return rc, out, made


def test_sends_only_pushall_and_get_version(cap, tmp_path):
    rc, out, (c,) = run(cap, tmp_path)
    assert rc == 0
    assert c.published == [(f"device/{SERIAL}/request", cap.PUSHALL), (f"device/{SERIAL}/request", cap.GET_VERSION)]
    assert {json.dumps(b, sort_keys=True) for _, b in c.published} == \
        {json.dumps(p, sort_keys=True) for p in ({"pushing": {"sequence_id": "0", "command": "pushall"}},
                                                 {"info": {"sequence_id": "0", "command": "get_version"}})}
    assert c.subscribed == [f"device/{SERIAL}/report"]
    assert (c.host, c.port, c.user, c.password) == (IP, 8883, "bblp", CODE)
    assert c.calls[-2:] == ["loop_stop", "disconnect"]


def test_publish_guard_refuses_anything_else(cap):
    for p in (cap.PUSHALL, cap.GET_VERSION):
        cap.check_read_only(p)
    for bad in ({"print": {"command": "stop", "sequence_id": "0", "param": ""}},
                {"print": {"command": "ams_filament_setting", "sequence_id": "0"}},
                {"pushing": {"sequence_id": "0", "command": "pushall"}, "print": {"command": "stop"}},
                {"info": {"sequence_id": "0", "command": "get_version", "extra": 1}},
                {"system": {"command": "ledctrl", "sequence_id": "0"}}):
        with pytest.raises(cap.CaptureError):
            cap.check_read_only(bad)


def test_fixture_is_scrubbed(cap, tmp_path, capsys):
    rc, out, _ = run(cap, tmp_path)
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert SERIAL not in text and CODE not in text and IP not in text and "secret-token" not in text
    printed = capsys.readouterr()
    assert CODE not in printed.out + printed.err and SERIAL not in printed.out + printed.err
    data = json.loads(text)
    p = data["report"]["print"]
    assert p["sn"] == "SERIAL0000000000" and "x_SERIAL0000000000" in p
    assert p["net"]["info"][0]["ip"] == "192.0.2.1" and p["net"]["info"][0]["mask"] == "192.0.2.1"
    assert p["ipcam"]["rtsp_url"] == "rtsps://192.0.2.1/streaming"
    assert p["upload"]["message"] == "/sdcard/SERIAL0000000000/x and code REDACTED"
    assert p["mc_percent"] == 5 and p["ams"]["tray_exist_bits"] == "f"        # merged in order
    assert data["version"]["module"][0]["name"] == "n3f/0"
    assert data["version"]["module"][0]["sn"] == "SERIAL0000000000"
    assert all(m["topic"] == "device/SERIAL0000000000/report" for m in data["messages"])
    assert len(data["messages"]) == 3


def test_scrub_rules(cap):
    got = cap.scrub({"a": [f"{SERIAL}", {"10.0.0.7:8883": "v1.2.3.4"}], 7: 1.5}, SERIAL, CODE)
    assert got == {"a": ["SERIAL0000000000", {"192.0.2.1:8883": "v1.2.3.4"}], 7: 1.5}
    assert cap.scrub("01.08.02.00 and 1.2.3.4", "S") == "01.08.02.00 and 192.0.2.1"
    assert cap.scrub({"ota_ver": "01.02.03.04", "ip": "0.0.0.0"}, "S") == {"ota_ver": "01.02.03.04",
                                                                          "ip": "192.0.2.1"}


def test_out_inside_tests_dir_needs_force(cap, tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "TESTS", tmp_path / "out")
    rc, out, made = run(cap, tmp_path)
    assert rc == 2 and not out.exists() and not made            # refused before connecting
    rc, out, _ = run(cap, tmp_path, "--force")
    assert rc == 0 and out.exists()


def test_env_problems_never_show_the_code(cap, tmp_path, capsys):
    p = env_file(tmp_path, f"PRINTER_IP={IP}\nPRINTER_CODE={CODE}\n")
    rc = cap.main(["--env", str(p), "--out", str(tmp_path / "x.json")], client_factory=FakeClient,
                  sleep=lambda s: None)
    err = capsys.readouterr().err
    assert rc == 1 and "PRINTER_SERIAL" in err and CODE not in err


def test_rejected_connection_writes_nothing(cap, tmp_path, capsys):
    rc, out, _ = run(cap, tmp_path, factory=lambda cid: FakeClient(cid, accept=False))
    err = capsys.readouterr().err
    assert rc == 1 and not out.exists() and CODE not in err and "access code" in err


def test_the_code_goes_only_to_the_pinned_leaf(cap, tmp_path, capsys):
    """FA-100: the leaf is read and printed first; a different leaf at connect time never gets the access code."""
    rc, out, (c,) = run(cap, tmp_path)
    assert rc == 0 and c.password == CODE
    assert hashlib.sha256(LEAF).hexdigest() in capsys.readouterr().out

    seen = []

    class Spy(FakeClient):
        def username_pw_set(self, user, password):
            seen.append(password)
            super().username_pw_set(user, password)
    def swapped(cid):
        c = Spy(cid)
        c.leaf = b"another-leaf"
        return c
    out.unlink()
    rc, out, _ = run(cap, tmp_path, factory=swapped)
    err = capsys.readouterr().err
    assert rc == 1 and not out.exists() and CODE not in err and "not the one read at the start" in err
    assert CODE not in seen                                    # the code was never handed to the client


def test_fingerprint_option_and_off_switch(cap, tmp_path, capsys):
    good = hashlib.sha256(LEAF).hexdigest()
    rc, out, _ = run(cap, tmp_path, "--fingerprint", good.upper())
    assert rc == 0
    rc, out, made = run(cap, tmp_path, "--fingerprint", "00" * 32)
    assert rc == 1 and not made and CODE not in capsys.readouterr().err         # refused before connecting
    # --no-pin: no probe at all, the code is set as before
    def no_probe(host):
        raise AssertionError("probed")
    rc, out, (c,) = run(cap, tmp_path, "--no-pin", probe=no_probe)
    assert rc == 0 and c.password == CODE


def test_read_env_format(cap, tmp_path):
    env = cap.read_env(env_file(tmp_path))
    assert env == {"PRINTER_IP": IP, "PRINTER_SERIAL": SERIAL, "PRINTER_CODE": CODE}   # nothing else kept


# ---------- fix round 1 ----------

import socket   # noqa: E402
import struct   # noqa: E402


def packed(ip, order="<"):
    return struct.unpack(order + "I", socket.inet_aton(ip))[0]


def test_int_ips_are_replaced(cap, tmp_path):
    """Bambu firmware sends net.info[].ip / mask / gw as packed uint32 (little-endian, ha-bambulab)."""
    replies = {"pushall": [{"print": {"command": "push_status", "net": {"info": [
        {"ip": packed(IP), "mask": packed("255.255.255.0"), "gw": packed("192.168.1.1")},
        {"ip": 0, "mask": 0}, {"ip": 12345, "mask": 777}]},
        "other": [packed(IP, ">"), packed(IP)], "uptime": 42}}],
        "get_version": []}
    rc, out, _ = run(cap, tmp_path, factory=lambda cid: FakeClient(cid, replies=replies))
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    p = data["report"]["print"]
    doc = packed("192.0.2.1")
    assert p["net"]["info"][0] == {"ip": doc, "mask": packed("255.255.255.0"), "gw": doc}    # plain netmask kept
    assert p["net"]["info"][1] == {"ip": doc, "mask": 0}
    assert p["net"]["info"][2] == {"ip": doc, "mask": doc}                                    # not a netmask
    assert p["other"] == [doc, doc] and p["uptime"] == 42
    for n in (packed(IP), packed(IP, ">"), packed("192.168.1.1")):
        assert str(n) not in out.read_text(encoding="utf-8")


def test_final_check_refuses_a_leftover_host_ip(cap, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cap, "scrub", lambda obj, *a, **k: obj)      # a scrub that missed something
    rc, out, _ = run(cap, tmp_path)
    assert rc == 1 and not out.exists()
    assert CODE not in capsys.readouterr().err


def test_final_check_sees_a_packed_host_ip(cap):
    assert cap.leftovers('{"x": %d}' % packed(IP, ">"), "S", "C", IP)
    assert cap.leftovers('{"x": "%s"}' % IP, "S", "C", IP)
    assert not cap.leftovers('{"x": %d1}' % packed(IP), "S", "C", IP)


def test_module_serials_are_redacted_consistently(cap, tmp_path):
    replies = {"pushall": [{"print": {"command": "push_status",
                                      "ams": {"ams": [{"id": "0", "sn": "19C06A111"}]}}}],
               "get_version": [{"info": {"command": "get_version", "module": [
                   {"name": "n3f/0", "sn": "19C06A111"}, {"name": "n3s/128", "sn": "22E08B222"},
                   {"name": "ahb", "sn": "33X"}, {"name": "ota", "sn": SERIAL}]}},
                   {"info": {"command": "get_version", "module": [{"name": "n3s/128", "sn": "22E08B222"}]}}]}
    rc, out, _ = run(cap, tmp_path, factory=lambda cid: FakeClient(cid, replies=replies))
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    for sn in ("19C06A111", "22E08B222", "33X", SERIAL):
        assert sn not in text
    data = json.loads(text)
    mods = {m["name"]: m["sn"] for m in data["version"]["module"]}
    first = [m for m in data["messages"] if "info" in m["payload"]][0]["payload"]["info"]["module"]
    names = {m["name"]: m["sn"] for m in first}
    assert names == {"n3f/0": "SN-redacted-1", "n3s/128": "SN-redacted-2", "ahb": "SN-redacted-3",
                     "ota": "SERIAL0000000000"}
    assert mods == {"n3s/128": "SN-redacted-2"}
    assert data["report"]["print"]["ams"]["ams"][0]["sn"] == "SN-redacted-1"
