"""The kit server's /setup page (setup_page.py) and its root helper (setup_helper.py), with the helper called
in-process (as JSON, like over its socket), FK_NO_SYSTEMD=1 (no apply runs) and doc values only.

Pinned: the setup code for every write (missing / wrong -> 403, lockout -> 429), LAN only, the server's own Host
and Origin, write-only secrets (never in a reply or a log), each section's write landing in the same file as the
CLI's, one audit line per change without the value, the root helper's own checks, `setup-code` and the installer's
closing line at a terminal and without one."""
from __future__ import annotations

import io
import json
import os
import logging
import re
import socket
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from filament_kit import (api, apply, cli, config, library, modules, pairing, reader_tokens, setup_code, setup_helper,
                          setup_page)
from filament_kit.bridge import registry
from filament_kit.spoolman import Spoolman

CODE = "12345678"
HOSTNAME = "kit.local"
BASE = f"https://{HOSTNAME}:8710"
H = {"Origin": BASE}
HOME = ("192.0.2.20", 50000)
AWAY = ("203.0.113.9", 50000)
KEY = "sk-ant-EXAMPLE"
SERIAL = "0948ZZ0A0000001"
PASS = "correct horse battery staple"
STATIC = Path(__file__).resolve().parent.parent / "filament_kit" / "setup_static"


class FakeManager:
    def __init__(self):
        self.synced = 0

    def sync(self):
        self.synced += 1

    def state(self, serial):
        return "connected"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setenv("FK_SETUP_RUN", str(tmp_path / "run"))
    cfg = config.load()
    cfg["modules"] = {n: n in modules.MODES["server"] for n in modules.MODULES}
    cfg["web"] = {**cfg["web"], "lan": ["192.0.2.0/24"]}
    config.save(cfg)
    setup_code.write(CODE)
    monkeypatch.setattr(cli.shutil, "chown", lambda *a, **k: None)   # no filament-kit group on a test machine
    applied = []
    monkeypatch.setattr(setup_helper, "_start_apply", lambda checked=False: applied.append(True))
    return applied


class Helper:
    """The root helper as the server sees it: JSON in, JSON out."""

    def __init__(self):
        self.calls = []

    def __call__(self, req):
        self.calls.append(req["op"])
        return json.loads(json.dumps(setup_helper.handle(json.loads(json.dumps(req)))))

    def open_file(self, req):
        """As HelperClient.open_file: the reply, and the file the op opened."""
        self.calls.append(req["op"])
        r = setup_helper.handle(json.loads(json.dumps(req)))
        fd = r.pop("fd", None)
        return json.loads(json.dumps(r)), (os.fdopen(fd, "rb") if fd is not None else None)


@pytest.fixture
def helper():
    return Helper()


@pytest.fixture
def manager():
    return FakeManager()


def make(env, helper, manager=None, client_factory=None, add=frozenset(), drop=frozenset()):
    on = (modules.enabled(config.load()) | add) - drop
    if manager is None:
        on = on - {"printers", "klipper"}
    return api.create_app(Spoolman("http://127.0.0.1:9"), printers=manager or object(), camera_hub=object(),
                          mapper=object(), enabled_modules=on,
                          setup={"helper": helper, "hosts": lambda: {HOSTNAME}, "client_factory": client_factory})


@pytest.fixture
def app(env, helper, manager):
    return make(env, helper, manager)


def client(app, who=HOME, base=BASE):
    return TestClient(app, base_url=base, client=who)


def post(c, path, body=None, code=CODE, headers=H):
    b = dict(body or {})
    if code is not None:
        b["code"] = code
    return c.post("/setup/api/" + path, json=b, headers=headers)


# every write the page has, with a body that would succeed with the right code
WRITES = [
    ("key", {"key": KEY}), ("key/remove", {}), ("passphrase", {"passphrase": PASS}),
    ("library_token", {"token": "ghp_EXAMPLE"}), ("library_token/remove", {}),
    ("readers", {"name": "bench"}), ("readers/r1/revoke", {}), ("pair", {"kind": "phone"}),
    ("devices/abc/revoke", {}), ("modules", {"name": "ai_intake", "on": True}),
    ("settings", {"key": "station.url", "value": "http://station.example.com:5003"}), ("apply", {}),
    ("printers", {"ip": "192.0.2.40", "access_code": "12345678", "serial": SERIAL}),
    (f"printers/{SERIAL}/code", {"access_code": "87654321"}), (f"printers/{SERIAL}/forget", {}),
]


def _etc(name):
    return config.paths().etc / name


# ---------- the page and its access ----------

def test_page_is_served_with_a_strict_csp_and_no_external_assets(app):
    r = client(app).get("/setup")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe" not in csp and "http" not in csp
    assert "/setup/setup.js" in r.text and "http" not in r.text.replace(BASE, "")
    assert client(app).get("/setup/setup.js").status_code == 200


def test_page_and_api_answer_only_the_home_network(app):
    away = client(app, AWAY)
    assert away.get("/setup").status_code == 403
    assert away.get("/setup/api/state").status_code == 403
    assert post(away, "key", {"key": KEY}).status_code == 403
    assert not _etc("anthropic_key").exists()


def test_another_host_name_is_refused(app):
    other = client(app, base="https://rebind.example.com:8710")
    assert other.get("/setup").status_code == 403
    r = post(other, "key", {"key": KEY}, headers={"Origin": "https://rebind.example.com:8710"})
    assert r.status_code == 403 and not _etc("anthropic_key").exists()


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://kit.local:8710", "https://kit.local"])
def test_every_post_needs_the_pages_own_origin(app, helper, origin):
    r = post(client(app), "key", {"key": KEY}, headers={"Origin": origin} if origin else {})
    assert r.status_code == 403 and r.json()["error"] == "bad origin"
    assert not helper.calls and not _etc("anthropic_key").exists()


def test_viewing_needs_no_code(app):
    r = client(app).get("/setup/api/state")
    assert r.status_code == 200
    st = r.json()
    assert st["code_set"] is True and st["address"].endswith(":8710/setup")
    assert {m["name"] for m in st["modules"]} == set(modules.MODULES)


@pytest.mark.parametrize("path,body", WRITES)
def test_every_write_needs_the_code(app, helper, manager, path, body):
    c = client(app)
    def files():
        return sorted(p.name for p in config.paths().etc.iterdir() if not p.name.startswith("setup_lockout"))
    before = files()
    for code in (None, "", "99999999", "1234-567"):
        r = post(c, path, body, code=code)
        assert r.status_code == 403, (path, code, r.text)
    assert len(helper.calls) == 2 and manager.synced == 0      # the two typed codes, refused by the helper
    assert files() == before
    assert not registry.load()


def test_wrong_codes_lock_the_page_for_ten_minutes(app, helper):
    c = client(app)
    for _ in range(setup_code.LOCK_MAX):
        assert post(c, "key", {"key": KEY}, code="00000000").status_code == 403
    r = post(c, "key", {"key": KEY})                  # even the right code, now
    assert r.status_code == 429 and "10 minutes" in r.json()["error"]
    assert not _etc("anthropic_key").exists()


def test_a_missing_code_does_not_count_towards_the_lockout(app):
    c = client(app)
    for _ in range(setup_code.LOCK_MAX + 2):
        assert post(c, "key", {"key": KEY}, code=None).status_code == 403
    assert post(c, "key", {"key": KEY}).status_code == 200


def test_the_code_is_accepted_with_a_dash_or_spaces(app):
    c = client(app)
    assert post(c, "key", {"key": KEY}, code="1234-5678").status_code == 200
    assert post(c, "key/remove", {}, code=" 1234 5678 ").status_code == 200


# ---------- write-only secrets, the CLI's files, audit lines ----------

def test_anthropic_key_lands_where_the_cli_puts_it_and_is_never_shown(app, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(app)
    r = post(c, "key", {"key": KEY})
    assert r.status_code == 200 and KEY not in r.text
    assert _etc(cli.KEY_FILE).read_text(encoding="utf-8") == KEY + "\n"
    st = c.get("/setup/api/state")
    assert st.json()["anthropic"]["set"] is True and KEY not in st.text
    post(c, "key", {"key": KEY + "2"})
    post(c, "key/remove", {})
    assert not _etc(cli.KEY_FILE).exists()
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("setup:")]
    assert lines == ["setup: anthropic key set from 192.0.2.20", "setup: anthropic key replaced from 192.0.2.20",
                     "setup: anthropic key removed from 192.0.2.20"]
    assert KEY not in caplog.text


def test_key_check_runs_the_status_check(env, helper):
    class Client:
        class models:
            @staticmethod
            def list():
                return []
    cli.write_key(KEY)
    c = client(make(env, helper, client_factory=lambda key: Client))
    r = post(c, "key/check", {}, code=None)
    assert r.json() == {"ok": True, "text": "Anthropic key accepted"}
    assert post(c, "key/check", {}, code=None).status_code == 429        # one check per few seconds


def test_a_bad_key_is_refused_without_echoing_it(app):
    r = post(client(app), "key", {"key": "sk-ant- with spaces"})
    assert r.status_code == 400 and "with spaces" not in r.text
    assert not _etc(cli.KEY_FILE).exists()


def test_web_passphrase_is_stored_as_the_cli_stores_it(app, caplog):
    pytest.importorskip("mcp")  # the web extra
    from filament_kit.web import auth
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(app)
    assert post(c, "passphrase", {"passphrase": "short"}).status_code == 400
    r = post(c, "passphrase", {"passphrase": PASS})
    assert r.status_code == 200 and PASS not in r.text
    assert auth.check_passphrase(PASS, _etc(cli.WEB_PASSPHRASE)) is True
    assert c.get("/setup/api/state").json()["passphrase"]["set"] is True
    assert "setup: web passphrase set from 192.0.2.20" in caplog.text and PASS not in caplog.text


def test_library_token_lands_where_the_library_reads_it(app, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(app)
    r = post(c, "library_token", {"token": "ghp_EXAMPLE"})
    assert r.status_code == 200 and "ghp_EXAMPLE" not in r.text
    assert library._token() == "ghp_EXAMPLE"
    assert c.get("/setup/api/state").json()["library_token"]["set"] is True
    post(c, "library_token/remove", {})
    assert library._token() is None
    assert "ghp_EXAMPLE" not in caplog.text and "setup: library token removed from 192.0.2.20" in caplog.text


def test_reader_token_is_shown_once_and_only_its_hash_is_kept(app, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(app)
    r = post(c, "readers", {"name": "bench"}).json()
    tok = r["token"]
    assert r["id"] == "r1" and len(tok) > 20
    assert reader_tokens.TokenStore().check(tok)
    assert tok.encode() not in reader_tokens.token_file().read_bytes()
    st = c.get("/setup/api/state")
    assert st.json()["readers"]["list"][0]["name"] == "bench" and tok not in st.text
    assert tok not in caplog.text and "setup: reader token r1 made from 192.0.2.20" in caplog.text
    assert post(c, "readers/r1/revoke", {}).status_code == 200
    assert not reader_tokens.TokenStore().check(tok)
    assert post(c, "readers/r1/revoke", {}).status_code == 404


def test_pairing_from_the_page_is_the_clis_pairing(app, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="filament_kit")
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    c = client(app)
    r = post(c, "pair", {"kind": "pc"}).json()
    assert r["link"].startswith("fkit://pair?") and re.fullmatch(r"[0-9]{6}", r["code"]) and r["qr_svg"] is None
    token = pairing.redeem_code(r["code"])
    dev = pairing.check(token)
    devs = c.get("/setup/api/state").json()["devices"]
    assert [d["id"] for d in devs] == [dev] and devs[0]["name"] == "pc"
    assert r["code"] not in caplog.text and "fkit://" not in caplog.text
    assert "setup: pairing started (pc) from 192.0.2.20" in caplog.text
    assert post(c, f"devices/{dev}/revoke", {}).status_code == 200
    assert pairing.check(token) is None
    assert post(c, "pair", {"kind": "laptop"}).status_code == 400


# ---------- printers ----------

def test_printer_added_by_ip_with_the_serial_from_its_certificate(app, manager, monkeypatch, caplog):
    from filament_kit import setup_page
    caplog.set_level(logging.INFO, logger="filament_kit")
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip: SERIAL)
    c = client(app)
    r = post(c, "printers", {"ip": "192.0.2.40", "access_code": "12345678", "name": "H2D"})
    assert r.status_code == 200 and r.json()["serial"] == SERIAL and "12345678" not in r.text
    p = registry.load()[SERIAL]
    assert (p.ip, p.access_code, p.configured, p.name) == ("192.0.2.40", "12345678", True, "H2D")
    assert manager.synced == 1
    st = c.get("/setup/api/state")
    assert st.json()["printers"]["list"][0]["serial"] == SERIAL and "12345678" not in st.text
    assert post(c, f"printers/{SERIAL}/code", {"access_code": "87654321"}).status_code == 200
    assert registry.load()[SERIAL].access_code == "87654321"
    assert post(c, f"printers/{SERIAL}/forget", {}).status_code == 200 and not registry.load()
    assert "12345678" not in caplog.text and "87654321" not in caplog.text
    assert f"setup: printer {SERIAL} added from 192.0.2.20" in caplog.text


def test_printer_added_under_a_taken_name_gets_a_free_one(app, manager, monkeypatch):
    from filament_kit import setup_page
    serials = iter([SERIAL, "03W00X123456789", SERIAL])
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip: next(serials))
    c = client(app)
    for ip in ("192.0.2.40", "192.0.2.41", "192.0.2.40"):   # the third is the first printer added again
        assert post(c, "printers", {"ip": ip, "access_code": "12345678", "name": "H2D"}).status_code == 200
    got = registry.load()
    assert (got[SERIAL].name, got["03W00X123456789"].name) == ("H2D", "H2D 2")


def test_printer_typed_serial_is_upper_cased_and_checked_against_the_certificate(app, monkeypatch):
    from filament_kit import setup_page

    def unreachable(ip):
        raise OSError("refused")
    monkeypatch.setattr(setup_page, "setup_serial", unreachable)
    c = client(app)
    body = {"ip": "192.0.2.40", "access_code": "12345678"}
    r = post(c, "printers", body)
    assert r.status_code == 400 and "type the serial" in r.json()["error"]
    assert post(c, "printers", {**body, "serial": SERIAL.lower()}).status_code == 200
    assert SERIAL in registry.load()
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip: "03W00X123456789")
    r = post(c, "printers", {**body, "serial": SERIAL})
    assert r.status_code == 400 and "names itself 03W00X123456789" in r.json()["error"]
    assert post(c, "printers", {**body, "ip": "not an address"}).status_code == 400
    assert post(c, "printers", {**body, "access_code": "no spaces!"}).status_code == 400


def test_printers_section_is_off_without_the_printers_module(env, helper):
    c = client(make(env, helper))
    assert c.get("/setup/api/state").json()["printers"]["on"] is False
    r = post(c, "printers", {"ip": "192.0.2.40", "access_code": "12345678", "serial": SERIAL})
    assert r.status_code == 409 and not registry.load()


# ---------- Klipper printers (review B9: listed with only the klipper module on; no Bambu code or TLS test) ----------

class FakeMoonraker:
    """setup_page's Moonraker client: `answer` is what /printer/info returns, or an exception to raise."""
    made: list = []
    answer = {"state": "ready", "state_message": "Printer is ready", "software_version": "v0.13.0"}

    def __init__(self, host, port=7125, api_key="", timeout=5.0):
        FakeMoonraker.made.append((host, port, api_key))

    def info(self):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def moonraker(monkeypatch):
    FakeMoonraker.made = []
    FakeMoonraker.answer = dict(FakeMoonraker.answer, state="ready")
    monkeypatch.setattr(setup_page, "Moonraker", FakeMoonraker)
    return FakeMoonraker


def _klipper(name="Workshop Printer", host="printer.example.com", port=7125, key=""):
    p = registry.add_klipper(name, host, port)
    if key:
        registry.set_api_key(p.serial, key)
    return p


def test_klipper_only_install_lists_its_klipper_printers(env, helper, manager):
    k = _klipper(key="MOONRAKER-KEY-EXAMPLE")
    registry.upsert(registry.Printer(SERIAL, "H2D", "H2D", "192.0.2.40", "12345678", True))
    c = client(make(env, helper, manager, add={"klipper"}, drop={"printers"}))
    st = c.get("/setup/api/state")
    P = st.json()["printers"]
    assert (P["on"], P["bambu"], P["klipper"]) == (True, False, True)
    assert [(p["serial"], p["family"], p["host"], p["port"]) for p in P["list"]] == \
        [(k.serial, "klipper", "printer.example.com", 7125)]          # the Bambu entry: its module is off
    assert P["list"][0]["state"] == "connected"
    assert "MOONRAKER-KEY-EXAMPLE" not in st.text and "12345678" not in st.text
    # Bambu writes stay refused: the printers module is off
    r = post(c, "printers", {"ip": "192.0.2.41", "access_code": "12345678", "serial": "0948ZZ0A0000002"})
    assert r.status_code == 409 and "0948ZZ0A0000002" not in registry.load()
    assert post(c, f"printers/{SERIAL}/code", {"access_code": "87654321"}).status_code == 409
    assert registry.load()[SERIAL].access_code == "12345678"


def test_both_printer_modules_list_both_families(env, helper, manager):
    k = _klipper()
    registry.upsert(registry.Printer(SERIAL, "H2D", "H2D", "192.0.2.40", "12345678", True))
    c = client(make(env, helper, manager, add={"klipper"}))
    P = c.get("/setup/api/state").json()["printers"]
    assert (P["on"], P["bambu"], P["klipper"]) == (True, True, True)
    assert {p["serial"]: p["family"] for p in P["list"]} == {SERIAL: "bambu", k.serial: "klipper"}


def test_a_klipper_printer_has_no_access_code_to_set(env, helper, manager):
    k = _klipper()
    c = client(make(env, helper, manager, add={"klipper"}))
    r = post(c, f"printers/{k.serial}/code", {"access_code": "87654321"})
    assert r.status_code == 400 and "Klipper" in r.json()["error"]
    p = registry.load()[k.serial]
    assert (p.access_code, p.configured, p.family) == ("", True, "klipper")


def test_klipper_test_asks_moonraker_not_a_tls_handshake(env, helper, manager, moonraker, monkeypatch):
    from filament_kit.bridge import tlspin
    from filament_kit.bridge.klipper import moonraker as mr
    monkeypatch.setattr(tlspin, "leaf_fp", lambda *a, **k: pytest.fail("a TLS handshake for a Klipper printer"))
    monkeypatch.setattr(setup_page, "CHECK_GAP", 0)
    k = _klipper(host="printer.example.com", port=7126, key="MOONRAKER-KEY-EXAMPLE")
    c = client(make(env, helper, manager, add={"klipper"}, drop={"printers"}))
    r = c.post(f"/setup/api/printers/{k.serial}/test", json={}, headers=H)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["reachable"] is True and j["state"] == "connected"
    assert "printer.example.com:7126" in j["text"] and "ready" in j["text"]
    assert moonraker.made == [("printer.example.com", 7126, "MOONRAKER-KEY-EXAMPLE")]
    assert "MOONRAKER-KEY-EXAMPLE" not in r.text
    moonraker.answer = mr.Offline("Moonraker at printer.example.com:7126 is not answering (refused)")
    j = c.post(f"/setup/api/printers/{k.serial}/test", json={}, headers=H).json()
    assert j["reachable"] is False and "no answer from Moonraker at printer.example.com:7126" in j["text"]
    moonraker.answer = mr.MoonrakerError("GET /printer/info: 500 <b>the printer's own text</b>")
    j = c.post(f"/setup/api/printers/{k.serial}/test", json={}, headers=H).json()
    assert j["reachable"] is False and j["text"] == "printer.example.com:7126 answers, but not as Moonraker"
    moonraker.answer = mr.NotFound("Not Found")
    j = c.post(f"/setup/api/printers/{k.serial}/test", json={}, headers=H).json()
    assert j["text"] == "printer.example.com:7126 answers, but not as Moonraker (HTTP 404)"
    moonraker.answer = mr.Unauthorized("Moonraker at printer.example.com wants an API key (401)")
    j = c.post(f"/setup/api/printers/{k.serial}/test", json={}, headers=H).json()
    assert j["reachable"] is True and "API key" in j["text"]


def test_forget_a_klipper_printer_with_only_the_klipper_module(env, helper, manager):
    k = _klipper()
    c = client(make(env, helper, manager, add={"klipper"}, drop={"printers"}))
    assert post(c, f"printers/{k.serial}/forget", {}).status_code == 200
    assert k.serial not in registry.load() and manager.synced == 1


def test_a_bambu_printer_is_not_reachable_through_the_klipper_module(env, helper, manager):
    registry.upsert(registry.Printer(SERIAL, "H2D", "H2D", "192.0.2.40", "12345678", True))
    c = client(make(env, helper, manager, add={"klipper"}, drop={"printers"}))
    assert c.post(f"/setup/api/printers/{SERIAL}/test", json={}, headers=H).status_code == 409
    assert post(c, f"printers/{SERIAL}/forget", {}).status_code == 409 and SERIAL in registry.load()


def test_setup_script_gives_klipper_rows_no_access_code_button():
    body = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    assert 'p.family === "klipper"' in body and "klipperRow" in body
    kr = body[body.index("function klipperRow"):]
    kr = kr[:kr.index("\n}")]
    assert '"code"' not in kr and "Access Code" not in kr and "testButton" in kr and "forgetButton" in kr
    assert "P.bambu ?" in body   # no Bambu add without it


# ---------- modules, addresses, the apply ----------

def test_module_switch_uses_the_checklist_rules_and_starts_an_apply(app, env, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(app)
    pv = c.get("/setup/api/modules/preview?name=orders").json()
    assert pv["on"] is True and "ai_intake" in pv["after"] and any("ai_intake" in n for n in pv["notes"])
    assert [n["key"] for n in pv["needs"]] == ["orders.file"]
    r = post(c, "modules", {"name": "orders", "on": True})
    assert r.status_code == 400 and r.json()["needs"] == ["orders.file"] and not env
    orders = config.paths().state / "orders.json"
    orders.parent.mkdir(parents=True, exist_ok=True)
    orders.write_text("[]", encoding="utf-8")
    r = post(c, "modules", {"name": "orders", "on": True, "settings": {"orders.file": str(orders)}})
    assert r.status_code == 200 and r.json()["changed"] is True
    cfg = config.load()
    assert {"orders", "ai_intake"} <= modules.enabled(cfg) and cfg["orders"]["file"] == str(orders)
    assert env == [True]                                       # the background apply was started
    assert "setup: module orders switched on from 192.0.2.20" in caplog.text


def test_the_server_module_cannot_be_switched_off_from_its_own_page(app, env):
    c = client(app)
    assert c.get("/setup/api/modules/preview?name=server").json()["refused"]
    r = post(c, "modules", {"name": "server", "on": False})
    assert r.status_code == 409 and "server" in modules.enabled(config.load()) and not env


def test_addresses_are_checked_and_saved(app, env):
    c = client(app)
    r = post(c, "settings", {"key": "web.public_url", "value": "http://plain.example.com"})
    assert r.status_code == 400 and not env
    assert post(c, "settings", {"key": "spoolman_url", "value": "http://x"}).status_code == 400
    assert post(c, "settings", {"key": "web.public_url", "value": "https://mcp.example.com/filament"}).status_code == 200
    assert post(c, "settings", {"key": "station.url", "value": "http://station.example.com:5003/"}).status_code == 200
    assert post(c, "settings", {"key": "station.url", "value": "http://u:p@station.example.com"}).status_code == 400
    cfg = config.load()
    assert cfg["web"]["public_url"] == "https://mcp.example.com/filament"
    assert cfg["station"]["url"] == "http://station.example.com:5003"
    assert env == [True, True]
    assert post(c, "settings", {"key": "station.url", "value": ""}).status_code == 200
    assert config.load()["station"]["url"] is None


def test_apply_output_is_read_from_the_log(app, env, monkeypatch):
    c = client(app)
    assert c.get("/setup/api/apply").json()["seen"] is False
    code = setup_helper.run_job("apply", [sys.executable, "-c", "print('==> Status'); print('OK  done')"])
    assert code == 0
    r = c.get("/setup/api/apply?from=0").json()
    assert r["running"] is False and r["exit"] == 0 and "OK  done" in r["text"]
    assert c.get(f"/setup/api/apply?from={r['next']}").json()["text"] == ""
    assert post(c, "apply", {}).status_code == 200 and env == [True]


def test_one_apply_at_a_time(app, env, monkeypatch):
    monkeypatch.setattr(setup_helper, "_applying", lambda: True)
    r = post(client(app), "modules", {"name": "ai_intake", "on": True})
    assert r.status_code == 409 and "ai_intake" not in modules.enabled(config.load()) and not env


# ---------- the root helper on its own ----------

def test_helper_checks_the_code_itself_with_its_own_lockout(env):
    for _ in range(setup_code.LOCK_MAX):
        assert setup_helper.handle({"op": "key_set", "code": "00000000", "key": KEY})["status"] == 403
    r = setup_helper.handle({"op": "key_set", "code": CODE, "key": KEY})
    assert r["status"] == 429 and not _etc(cli.KEY_FILE).exists()
    assert setup_code.lockout_file().exists()


def test_helper_accepts_only_its_own_operations(env):
    for req in (None, [], {"op": "run", "code": CODE, "cmd": "id"}, {"op": "__init__", "code": CODE}):
        r = setup_helper.handle(req)
        assert r["ok"] is False and r["status"] == 400


def test_helper_reply_never_holds_the_value(env):
    r = setup_helper.handle({"op": "key_set", "code": CODE, "key": KEY})
    assert r == {"ok": True, "status": 200}


def test_helper_main_reads_one_line_and_answers_one(env, monkeypatch):
    class In:
        buffer = io.BytesIO(json.dumps({"op": "key_set", "code": CODE, "key": KEY}).encode() + b"\n")

    class Out:
        buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", In)
    monkeypatch.setattr(sys, "stdout", Out)
    assert setup_helper.main([]) == 0
    assert json.loads(Out.buffer.getvalue()) == {"ok": True, "status": 200}
    assert _etc(cli.KEY_FILE).read_text(encoding="utf-8") == KEY + "\n"


def test_helper_refuses_a_request_too_large(env, monkeypatch):
    class In:
        buffer = io.BytesIO(b"x" * (setup_helper.MAX_REQUEST + 10) + b"\n")

    class Out:
        buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", In)
    monkeypatch.setattr(sys, "stdout", Out)
    setup_helper.main([])
    assert json.loads(Out.buffer.getvalue())["status"] == 413


def test_helper_unit_files_keep_it_closed():
    systemd = Path(__file__).resolve().parents[2] / "install" / "systemd"
    sock = (systemd / "filament-kit-setup.socket").read_text(encoding="utf-8")
    assert "SocketMode=0660" in sock and "SocketGroup=filament-kit" in sock and "Accept=yes" in sock
    svc = (systemd / "filament-kit-setup@.service").read_text(encoding="utf-8")
    assert "StandardInput=socket" in svc and "ProtectSystem=strict" in svc
    assert ("ReadWritePaths=/etc/filament-kit -/var/backups/filament-kit\n" in svc
            and "-m filament_kit.setup_helper\n" in svc)
    run = (systemd / "filament-kit-setup-job@.service").read_text(encoding="utf-8")
    assert "setup_helper job-run %i" in run


# ---------- the setup code: CLI and installer ----------

def _stdin(monkeypatch, tty):
    s = io.StringIO("")
    s.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", s)


def test_setup_code_cli_prints_it_at_a_terminal_only(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(pairing, "short_hostname", lambda: "kit")
    _stdin(monkeypatch, True)
    assert cli.main(["setup-code"]) == 0
    assert capsys.readouterr().out.strip() == "Open https://kit.local:8710/setup  (setup code: 1234-5678)"
    _stdin(monkeypatch, False)
    assert cli.main(["setup-code"]) == 0
    out = capsys.readouterr().out
    assert "https://kit.local:8710/setup" in out and "1234-5678" not in out and CODE not in out


def test_setup_code_new_replaces_it(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    _stdin(monkeypatch, True)
    assert cli.main(["setup-code", "--new"]) == 0
    new = setup_code.read()
    assert new != CODE and setup_code.check(new) and not setup_code.check(CODE)
    assert setup_code.shown(new) in capsys.readouterr().out


def test_setup_code_storage(env):
    assert setup_code.hash_file().read_text(encoding="utf-8").split()[0] != CODE
    assert CODE not in setup_code.hash_file().read_text(encoding="utf-8")
    assert setup_code.read() == CODE and setup_code.ensure() == CODE
    assert setup_code.normalize("1234-5678") == CODE and setup_code.normalize("1234567") is None
    setup_code.plain_file().unlink()
    fresh = setup_code.ensure()                  # nobody could show the old one again: a new one
    assert fresh != CODE and setup_code.check(fresh)


@pytest.fixture
def finish(env, monkeypatch):
    monkeypatch.setattr(apply, "_https_local_ok", lambda url: True)
    monkeypatch.setattr(apply.pairing, "short_hostname", lambda: "kit")
    monkeypatch.setattr(cli, "_qr_text", lambda payload: f"[QR {payload}]")
    monkeypatch.delenv("FK_NO_SYSTEMD")
    return lambda cmd: print("$ " + " ".join(cmd))


def test_installer_ends_with_the_address_and_code_at_a_terminal(finish, monkeypatch, capsys):
    _stdin(monkeypatch, True)
    apply.finish(config.load(), run=finish)
    out = capsys.readouterr().out
    assert out.rstrip().endswith("Open https://kit.local:8710/setup  (setup code: 1234-5678)")


def test_installer_without_a_terminal_prints_the_address_but_no_code(finish, monkeypatch, capsys):
    _stdin(monkeypatch, False)
    apply.finish(config.load(), run=finish)
    out = capsys.readouterr().out
    assert "https://kit.local:8710/setup" in out and "1234-5678" not in out and CODE not in out
    apply.finish(config.load(), run=finish, pairing=False)          # the page's own apply: no setup line
    assert "/setup" not in capsys.readouterr().out


def test_server_setup_makes_the_code_once(env, monkeypatch):
    before = setup_code.read()
    setup_code.ensure()
    assert setup_code.read() == before
    src = (Path(apply.__file__)).read_text(encoding="utf-8")
    assert "setup_code.ensure()" in src[src.index("def _server_setup"):src.index("def _remote_install")]


def test_setup_script_never_uses_innerhtml():
    lines = (STATIC / "setup.js").read_text(encoding="utf-8").splitlines()
    src = " ".join(ln for ln in lines if not ln.lstrip().startswith("//"))
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", src)
    assert re.findall(r"fetch\(([^,)]*)", src) == ['"/setup/api/" + path']     # nothing from elsewhere


@pytest.mark.skipif(not hasattr(__import__("socket"), "AF_UNIX") or sys.platform == "win32",
                    reason="the helper socket is a Linux unix socket")
def test_helper_client_over_a_real_socket_like_systemd_accept(env, tmp_path):
    """systemd's Accept=yes hands each connection to a new helper process as its stdin/stdout: do the same."""
    import os
    import socket
    import subprocess
    import threading
    from filament_kit import setup_page
    # the test user is neither root nor filament-kit: one helper as shipped (refused by SO_PEERCRED), one that also
    # accepts this test's uid
    as_shipped = [sys.executable, "-I", "-m", "filament_kit.setup_helper"]
    this_uid = [sys.executable, "-I", "-c", "import os, sys; from filament_kit import setup_helper as h; "
                "h._allowed_uids = lambda: {0, os.getuid()}; sys.exit(h.main([]))"]

    def one(cmd, name):
        path = str(tmp_path / name)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(1)

        def serve():
            conn, _ = srv.accept()
            with conn:
                subprocess.run(cmd, stdin=conn.fileno(), stdout=conn.fileno(), env={**os.environ}, check=False,
                               timeout=60)
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        reply = setup_page.HelperClient(path)({"op": "key_set", "code": CODE, "key": KEY})
        t.join(30)
        srv.close()
        return reply
    if os.getuid() != 0:
        assert one(as_shipped, "a.sock")["status"] == 403
        assert not _etc(cli.KEY_FILE).exists()
    assert one(this_uid, "b.sock") == {"ok": True, "status": 200}
    assert _etc(cli.KEY_FILE).read_text(encoding="utf-8") == KEY + "\n"
    assert setup_page.HelperClient(str(tmp_path / "none.sock"))({"op": "apply", "code": CODE})["status"] == 503


def _leaf(cn: str) -> bytes:
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.DER)


def test_setup_serial_reads_the_cn_of_the_printers_leaf(monkeypatch):
    from filament_kit import setup_page
    from filament_kit.bridge import tlspin
    seen = []
    monkeypatch.setattr(tlspin, "_leaf_der", lambda ip, port, timeout: seen.append((ip, port)) or _leaf(SERIAL))
    assert setup_page.setup_serial("192.0.2.40") == SERIAL and seen == [("192.0.2.40", 8883)]
    monkeypatch.setattr(tlspin, "_leaf_der", lambda ip, port, timeout: _leaf("not a serial!"))
    assert setup_page.setup_serial("192.0.2.40") is None


@pytest.mark.parametrize("state,running", [("activating", True), ("active", True), ("inactive", False),
                                           ("failed", False), ("", False)])
def test_an_apply_counts_as_running_while_its_oneshot_is_activating(monkeypatch, state, running):
    import subprocess
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=state + "\n", stderr="")
    monkeypatch.setattr(setup_helper.subprocess, "run", run)
    assert setup_helper._applying() is running
    assert ["systemctl", "show", "--property=ActiveState", "--value", setup_helper.UPDATE_UNIT] in seen


# ---------- the helper's ops, the page's guards and the apply log ----------

SYSTEMD = Path(__file__).resolve().parents[2] / "install" / "systemd"


@pytest.mark.skipif(sys.platform == "win32", reason="file modes")
def test_r1_the_hash_file_is_root_only(env):
    import os
    st = os.stat(setup_code.hash_file())
    assert st.st_mode & 0o777 == 0o600


def test_r1_hash_is_written_without_a_group(monkeypatch, env):
    seen = []
    monkeypatch.setattr(setup_code, "_write", lambda dest, data, mode, group: seen.append((dest.name, mode, group)))
    setup_code.write(CODE)
    assert ("setup_code", 0o600, None) in seen and ("setup_code.plain", 0o600, None) in seen


def test_r1_the_check_op_is_the_only_code_check(app, helper, monkeypatch):
    from filament_kit import setup_page
    assert not hasattr(setup_page.SetupPage(None, helper=helper), "lockout")
    src = Path(setup_page.__file__).read_text(encoding="utf-8")
    assert "setup_code.check" not in src and "Lockout" not in src.replace("lockout (", "")  # never in the server
    c = client(app)
    assert post(c, "readers", {"name": "bench"}).status_code == 200      # a state-dir write: the helper checks
    assert helper.calls == ["check"]
    assert post(c, "key", {"key": KEY}).status_code == 200               # a helper write: checked in that request
    assert helper.calls == ["check", "key_set"]


def test_r1_check_op_answers_right_and_wrong(env):
    assert setup_helper.handle({"op": "check", "code": CODE, "client": "192.0.2.20"}) == {"ok": True, "status": 200}
    assert setup_helper.handle({"op": "check", "code": "00000000", "client": "192.0.2.20"})["status"] == 403


def test_r1_web_unit_cannot_reach_the_helper_socket():
    web = (SYSTEMD / "filament-kit-web.service").read_text(encoding="utf-8")
    assert "InaccessiblePaths=-/run/filament-kit-setup\n" in web     # the folder: a remade socket stays hidden
    sock = (SYSTEMD / "filament-kit-setup.socket").read_text(encoding="utf-8")
    assert "ListenStream=/run/filament-kit-setup/setup.sock\n" in sock


def test_r2_lockout_is_per_client(env):
    for _ in range(setup_code.LOCK_MAX):
        assert setup_helper.handle({"op": "check", "code": "00000000", "client": "192.0.2.20"})["status"] == 403
    assert setup_helper.handle({"op": "check", "code": CODE, "client": "192.0.2.20"})["status"] == 429
    assert setup_helper.handle({"op": "check", "code": CODE, "client": "192.0.2.21"})["status"] == 200


def test_r2_global_ceiling_with_doubling_backoff(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(setup_code.time, "time", lambda: now[0])
    lock = setup_code.Lockout(tmp_path / "lock")
    for i in range(setup_code.GLOBAL_MAX):
        assert lock.attempt(f"192.0.2.{i}") is not None           # one wrong code each from many addresses
    assert lock.attempt("192.0.2.200") is None                    # the ceiling: everyone waits
    now[0] += setup_code.LOCK_WINDOW + 1
    assert lock.attempt("192.0.2.200") is not None                # first backoff (one window) is over
    for i in range(setup_code.GLOBAL_MAX):
        lock.attempt(f"192.0.2.{i}")
    now[0] += setup_code.LOCK_WINDOW + 1
    assert lock.attempt("192.0.2.201") is None                    # the second backoff is twice as long
    now[0] += setup_code.LOCK_WINDOW
    assert lock.attempt("192.0.2.201") is not None


def test_r2_new_code_clears_the_lockout(env, monkeypatch, capsys):
    for _ in range(setup_code.LOCK_MAX):
        setup_helper.handle({"op": "check", "code": "00000000", "client": "192.0.2.20"})
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    _stdin(monkeypatch, True)
    assert cli.main(["setup-code", "--new"]) == 0
    new = setup_code.read()
    assert setup_helper.handle({"op": "check", "code": new, "client": "192.0.2.20"})["status"] == 200


def test_r3_helper_unit_is_hardened():
    svc = (SYSTEMD / "filament-kit-setup@.service").read_text(encoding="utf-8")
    for line in ("CapabilityBoundingSet=CAP_CHOWN CAP_FOWNER CAP_DAC_OVERRIDE CAP_DAC_READ_SEARCH",
                 "RestrictAddressFamilies=AF_UNIX", "SystemCallFilter=@system-service",
                 "SystemCallArchitectures=native", "ProtectKernelTunables=yes", "ProtectKernelModules=yes",
                 "ProtectKernelLogs=yes", "ProtectControlGroups=yes", "PrivateDevices=yes", "RestrictNamespaces=yes",
                 "RestrictSUIDSGID=yes", "LockPersonality=yes", "MemoryDenyWriteExecute=yes", "UMask=0077",
                 "IPAddressDeny=any", "NoNewPrivileges=yes", "ProtectSystem=strict",
                 "ReadWritePaths=/etc/filament-kit -/var/backups/filament-kit"):
        assert line + "\n" in svc, line


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_m_peer_must_be_root_or_the_service_user(env, monkeypatch):
    import socket
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with a, b:
        monkeypatch.setattr(setup_helper, "_allowed_uids", lambda: {12345})
        assert setup_helper._peer_ok(b.fileno()) is False
        monkeypatch.setattr(setup_helper, "_allowed_uids", lambda: {__import__("os").getuid()})
        assert setup_helper._peer_ok(b.fileno()) is True
    assert setup_helper._peer_ok(io.BytesIO().fileno() if False else -1) is None


def test_m_orders_file_must_be_a_json_file_in_the_state_folder(app, env, tmp_path):
    c = client(app)
    good = config.paths().state / "orders.json"
    good.parent.mkdir(parents=True, exist_ok=True)
    good.write_text("[]", encoding="utf-8")
    for bad in ("/etc/shadow", str(config.paths().state / "orders.txt"), str(config.paths().state / "none.json"),
                str(tmp_path / "x.json")):
        r = post(c, "modules", {"name": "orders", "on": True, "settings": {"orders.file": bad}})
        assert r.status_code == 400, bad
    r = post(c, "modules", {"name": "orders", "on": True, "settings": {"orders.file": str(good)}})
    assert r.status_code == 200


def test_m_plan_check_in_the_helper_does_not_resolve_names(env, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("no DNS in the helper"))
    cfg = config.load()
    cfg["modules"]["station"] = True
    cfg["station"] = {**cfg["station"], "allow": ["station.example.com"]}
    assert setup_helper._plan_error(cfg) is None
    cfg["station"]["allow"] = ["bad..name"]
    assert setup_helper._plan_error(cfg)


def test_m_body_size_is_capped_before_reading(app):
    from filament_kit import setup_page
    c = client(app)
    r = c.post("/setup/api/key", content=b"x" * (setup_page.MAX_BODY + 1),
               headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 413
    r = c.post("/setup/api/key", content=b"{}", headers={**H, "Content-Length": str(10 ** 9)})
    assert r.status_code == 413


def test_m_setup_code_refuses_non_root_even_without_systemd(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.main(["setup-code"]) == 1
    assert "run as root" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_m_helper_read_times_out(env, monkeypatch):
    import socket
    monkeypatch.setattr(setup_helper, "READ_TIMEOUT", 0.3)
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with a, b:
        a.sendall(b'{"op": "check"')               # no newline, never finished
        assert setup_helper._read_request(b.fileno()) is None


# ---------- the web unit as its own user ----------

def _web_cfg():
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "server", say=None)
    cfg["modules"]["web"] = True
    cfg["web"]["public_url"] = "https://mcp.example.com/filament"
    return cfg


def test_r2b_web_unit_runs_as_its_own_user_with_only_its_paths():
    web = (SYSTEMD / "filament-kit-web.service").read_text(encoding="utf-8")
    for line in ("User=filament-kit-web", "Group=filament-kit-web", "WorkingDirectory=/var/lib/filament-kit-web",
                 "PrivatePIDs=yes", "InaccessiblePaths=-/run/filament-kit-setup", "NoNewPrivileges=yes",
                 "ReadWritePaths=/var/lib/filament-kit-web"):
        assert line + "\n" in web, line
    assert "User=filament-kit\n" not in web and "Group=filament-kit\n" not in web
    assert "SupplementaryGroups" not in web and "ReadWritePaths=/var/lib/filament-kit\n" not in web


def test_r2b_apply_makes_the_web_user_without_the_kit_group_before_its_state():
    kinds = [(a.kind, a.arg) for a in apply.plan(_web_cfg())]
    assert ("user", "filament-kit-web") in kinds          # a plain str: no extra groups (apply._user)
    i_user, i_state = kinds.index(("user", "filament-kit-web")), kinds.index(("web_state", ""))
    i_setup = [k for k, _ in kinds].index("server_setup")
    assert i_setup < i_user < i_state < kinds.index(("enable", "filament-kit-web.service"))


def test_r2b_tmpfiles_makes_the_run_folder_from_boot():
    acts = apply.plan(_web_cfg())
    files = [a.arg for a in acts if a.kind == "install_file"]
    assert ("/etc/tmpfiles.d/filament-kit-setup.conf", "d /run/filament-kit-setup 0750 root filament-kit -\n",
            "0644", "root:root") in files
    assert ("tmpfiles", "/etc/tmpfiles.d/filament-kit-setup.conf") in [(a.kind, a.arg) for a in acts]


def test_r2b_web_state_lives_in_its_own_folder(env):
    pytest.importorskip("mcp")  # the web extra
    from filament_kit.web import app as web_app, push, slots
    w = config.paths().web
    assert w != config.paths().state and w.name.endswith("-web")
    assert web_app.oauth_file() == w / "oauth.json"
    assert push.state_dir() == w and slots.KitApi()._token_file() == w / "kit_token"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="root runs this on Linux (descriptors, /proc)")
def test_r2b_migration_copies_the_web_files_and_keeps_reader_tokens(env):
    import os
    from filament_kit import web_access
    old = config.paths().state / "web"
    old.mkdir(parents=True, exist_ok=True)
    (old / "oauth.json").write_text('{"clients": {"c1": {}}}', encoding="utf-8")
    (old / "kit_token").write_text("tok-EXAMPLE\n", encoding="utf-8")
    (old / "vapid.pem").write_text("pem", encoding="utf-8")
    (old / "reader_tokens").write_text("<reader-tokens/>", encoding="utf-8")
    chowned = []
    moved = web_access.migrate(5001, 5001, chown=lambda fd, u, g: chowned.append((os.readlink(f"/proc/self/fd/{fd}")
                                                                                  .rsplit("/", 1)[-1], u, g)))
    w = config.paths().web
    assert moved == ["kit_token", "oauth.json", "vapid.pem"]
    assert (w / "oauth.json").read_text(encoding="utf-8") == '{"clients": {"c1": {}}}'   # the connector stays
    assert (w / "kit_token").read_text(encoding="utf-8") == "tok-EXAMPLE\n"               # the kit pairing too
    assert (old / "reader_tokens").exists() and (old / "oauth.json").exists()       # copied: 0.3.0 keeps it
    assert (w.name, 5001, 5001) in chowned and ("oauth.json", 5001, 5001) in chowned
    (old / "oauth.json").write_text("stale", encoding="utf-8")
    assert web_access.migrate(5001, 5001, chown=lambda *a: None) == []                      # never over a moved one
    assert (w / "oauth.json").read_text(encoding="utf-8") != "stale"


@pytest.mark.skipif(sys.platform == "win32", reason="file modes")
def test_r2b_migration_modes(env):
    import os
    from filament_kit import web_access
    old = config.paths().state / "web"
    old.mkdir(parents=True, exist_ok=True)
    (old / "reader_tokens").write_text("<reader-tokens/>", encoding="utf-8")
    os.chmod(old / "reader_tokens", 0o600)
    web_access.migrate(os.getuid(), os.getgid())
    assert os.stat(config.paths().web).st_mode & 0o777 == 0o750
    assert os.stat(old / "reader_tokens").st_mode & 0o777 == 0o644


@pytest.mark.skipif(sys.platform == "win32", reason="root runs this on Linux (folder descriptors)")
def test_r2b_web_pairs_once_as_root_and_keeps_an_existing_token(env):
    from filament_kit import web_access
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    config.paths().web.mkdir(parents=True, exist_ok=True)
    assert web_access.pair(5001, 5001, chown=lambda *a: None) is True
    tok = (config.paths().web / "kit_token").read_text(encoding="utf-8").strip()
    assert pairing.check(tok) is not None
    web_access.pair(5001, 5001, chown=lambda *a: pytest.fail("not paired again"))
    assert (config.paths().web / "kit_token").read_text(encoding="utf-8").strip() == tok


def test_r2b_web_without_a_token_and_without_pairing_rights_says_how(env, monkeypatch):
    from filament_kit.web import slots

    def denied(*a, **k):
        raise PermissionError("devices.json")
    monkeypatch.setattr(slots.pairing, "issue", denied)
    with pytest.raises(slots.SlotError) as e:
        slots.KitApi("https://127.0.0.1:1")._token()
    assert "sudo filament-kit modules apply" in str(e.value)


@pytest.mark.skipif(sys.platform == "win32", reason="root runs this on Linux (folder descriptors)")
def test_r2b_shared_lock_files_exist(env):
    from filament_kit import web_access
    web_access.shared_files(1000, 1000, chown=lambda *a: None)
    st = config.paths().state
    for name in web_access.LOCK_FILES:
        assert (st / name).is_file(), name


def _acls_or_skip(path):
    from filament_kit import acl
    if not acl.supported():
        pytest.skip("no xattrs here")
    try:
        acl.grant(path, {54321: acl.R})
    except OSError:
        pytest.skip("no ACLs on this file system")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX ACLs")
def test_r2b_grants_give_the_web_user_exactly_its_paths(env, tmp_path):
    import os
    from filament_kit import acl, web_access
    _acls_or_skip(tmp_path)
    st, etc = config.paths().state, config.paths().etc
    for d in ("web", "profiles", "library", "library-local"):
        (st / d).mkdir(parents=True, exist_ok=True)
    (st / "profiles" / "lines.lock").write_text("", encoding="utf-8")
    (st / "printers.json").write_text("{}", encoding="utf-8")
    (etc / "anthropic_key").write_text("sk-ant-EXAMPLE\n", encoding="utf-8")
    (etc / "key.pem").write_text("k", encoding="utf-8")
    web_access.shared_files(os.getuid(), os.getgid(), chown=lambda *a: None)
    WEB, KIT = 54321, os.getuid()
    web_access.grant(WEB, KIT, {"orders": {"file": None}})
    R, W, X = acl.R, acl.W, acl.X
    assert acl.users_of(etc) == {WEB: X} and acl.users_of(st) == {WEB: X}
    assert acl.users_of(etc / "config.json") == {WEB: R} and acl.users_of(etc / "anthropic_key") == {WEB: R}
    assert acl.users_of(etc / "key.pem") == {} and acl.users_of(st / "printers.json") == {}
    assert acl.users_of(etc / "setup_code") == {} and acl.users_of(etc / "setup_code.plain") == {}
    assert acl.users_of(st / "inventory.lock") == {WEB: R}
    assert acl.users_of(st / "profiles" / "lines.lock") == {WEB: R}
    assert acl.users_of(st / "profiles", acl.DEFAULT) == {WEB: R | X}
    assert acl.users_of(st / "profiles") == {WEB: R | X}
    assert acl.users_of(st / "library") == {WEB: R | X} and acl.users_of(st / "web") == {WEB: R | X}
    new = st / "profiles" / "made-later.json"
    new.write_text("{}", encoding="utf-8")               # what the kit makes later is readable by the web user
    assert acl.users_of(new)[WEB] & (R | W) == R


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX ACLs")
def test_r2b_acl_round_trip_keeps_the_mode_and_other_entries(tmp_path):
    import os
    from filament_kit import acl
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, 0o640)
    _acls_or_skip(f)
    acl.grant(f, {54322: acl.R | acl.W})
    assert acl.users_of(f) == {54321: acl.R, 54322: acl.R | acl.W}
    assert os.stat(f).st_mode & 0o707 == 0o600            # owner and other bits stay; group shows the mask


def test_r2b_acl_encoding():
    from filament_kit import acl
    data = acl.encode([(acl.OTHER, 0, acl.UNDEFINED), (acl.USER, 4, 1001), (acl.USER_OBJ, 6, acl.UNDEFINED)])
    assert acl.decode(data) == [(acl.USER_OBJ, 6, acl.UNDEFINED), (acl.USER, 4, 1001), (acl.OTHER, 0, acl.UNDEFINED)]
    with pytest.raises(ValueError):
        acl.decode(b"\x01\x00\x00\x00")


def test_r2b_root_writers_keep_the_web_users_read(env, monkeypatch):
    pytest.importorskip("mcp")  # the web extra
    seen = []
    monkeypatch.setattr(config, "grant_web_read", lambda path: seen.append(Path(path).name))
    config.save(config.load())
    cli.write_key(KEY)
    cli.write_passphrase(PASS)
    assert any(n.startswith("config.json") for n in seen) and any(n.startswith("anthropic_key") for n in seen)
    assert any(n.startswith("web_passphrase") for n in seen)


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_r2b_the_web_users_uid_is_refused_by_the_helper(env, monkeypatch):
    """The web unit's uid is neither root nor filament-kit: SO_PEERCRED refuses it."""
    import os
    import socket
    monkeypatch.setattr(setup_helper, "_allowed_uids", lambda: {0, os.getuid() + 1})   # filament-kit is someone else
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with a, b:
        assert setup_helper._peer_ok(b.fileno()) is False


def test_r2b_allowed_uids_are_root_and_the_kit_never_the_web_user(monkeypatch):
    import types
    users = {"filament-kit": 990, "filament-kit-web": 991}
    fake = types.SimpleNamespace(getpwnam=lambda n: types.SimpleNamespace(pw_uid=users[n]))
    monkeypatch.setitem(sys.modules, "pwd", fake)
    assert setup_helper._allowed_uids() == {0, 990}


def test_r2b_locked_message_names_the_recovery_command():
    assert "sudo filament-kit setup-code --new" in setup_helper.LOCKED


def test_r2b_global_backoff_decays_after_quiet_hours(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(setup_code.time, "time", lambda: now[0])
    lock = setup_code.Lockout(tmp_path / "lock")

    def burst():
        for i in range(setup_code.GLOBAL_MAX):
            lock.attempt(f"192.0.2.{i}")
    burst()                                                          # level 1: 10 min
    now[0] += setup_code.LOCK_WINDOW + 1
    burst()                                                          # level 2: 20 min
    now[0] += 2 * setup_code.LOCK_WINDOW + 1 + 2 * setup_code.DECAY  # two quiet hours: two levels down
    burst()                                                          # level 1 again: 10 min, not 40
    now[0] += setup_code.LOCK_WINDOW + 1
    assert lock.attempt("192.0.2.250") is not None


def test_r2b_web_state_without_the_web_user_stops_the_apply(env, monkeypatch):
    import types
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwnam=lambda n: (_ for _ in ()).throw(KeyError(n))))
    ex = apply._Exec(lambda cmd: None, Path("."), Path("/"))
    with pytest.raises(apply.ApplyError):
        apply._web_state(ex)


# ---------- the client address cannot be forged from loopback ----------

def test_kit_server_takes_no_proxy_headers():
    from filament_kit import __main__ as kit_main
    opts = kit_main.serve_options({"port": 8710}, Path("/etc/filament-kit"))
    assert opts["proxy_headers"] is False and opts["forwarded_allow_ips"] == ""


def test_x_forwarded_for_from_loopback_does_not_change_the_client(tmp_path):
    """Through uvicorn's own app wrapping, with the kit server's options: the client stays the socket's."""
    import asyncio
    import uvicorn
    from filament_kit import __main__ as kit_main
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["client"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})
    opts = {k: v for k, v in kit_main.serve_options({"port": 8710}, tmp_path).items() if not k.startswith("ssl_")}
    cfg = uvicorn.Config(app, **opts)
    cfg.load()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https",
             "path": "/setup/api/key", "raw_path": b"/setup/api/key", "query_string": b"", "root_path": "",
             "headers": [(b"host", b"localhost"), (b"x-forwarded-for", b"192.0.2.77")],
             "client": ("127.0.0.1", 40000), "server": ("127.0.0.1", 8710)}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_):
        pass
    asyncio.run(cfg.loaded_app(scope, receive, send))
    assert seen == [("127.0.0.1", 40000)]


def test_every_loopback_caller_is_one_lockout_client(env, helper):
    import types
    key = setup_page.SetupPage._client_key
    req = lambda host: types.SimpleNamespace(client=types.SimpleNamespace(host=host))   # noqa: E731
    assert key(req("127.0.0.1")) == key(req("127.0.0.53")) == key(req("::1")) == key(req("::ffff:127.0.0.1")) \
        == "loopback"
    assert key(req("192.0.2.4")) == "192.0.2.4"
    sent = []
    app = make(env, lambda r: sent.append(r.get("client")) or helper(r))
    c = TestClient(app, base_url=BASE, client=("127.0.0.1", 50000))
    cfg = config.load()
    cfg["web"] = {**cfg["web"], "lan": ["192.0.2.0/24", "127.0.0.0/8"]}
    config.save(cfg)
    for fwd in ("192.0.2.31", "192.0.2.32"):
        post(c, "key", {"key": KEY}, code="00000000", headers={**H, "X-Forwarded-For": fwd})
    assert sent and set(sent) == {"loopback"}


# ---------- the lockout file is XML, written by a temp file and a rename ----------

def test_lockout_state_is_kept_as_xml(tmp_path):
    import defusedxml.ElementTree as DET
    lock = setup_code.Lockout(tmp_path / "setup_lockout.xml")
    t = lock.attempt("192.0.2.20")
    root = DET.fromstring((tmp_path / "setup_lockout.xml").read_bytes())
    assert root.tag == "setup-lockout"
    fails = root.findall("fail")
    assert [(f.get("client"), f.get("ticket")) for f in fails] == [("192.0.2.20", t)]
    lock.release(t)
    assert DET.fromstring((tmp_path / "setup_lockout.xml").read_bytes()).findall("fail") == []


def test_lockout_file_name_is_xml_and_the_old_json_one_is_ignored(env):
    assert setup_code.lockout_file().name == "setup_lockout.xml"
    old = config.paths().etc / "setup_lockout"
    old.write_text('{"until": 99999999999, "level": 9}', encoding="utf-8")   # a dev install's: never shipped
    assert setup_helper.handle({"op": "check", "code": CODE, "client": "192.0.2.20"})["status"] == 200


@pytest.mark.skipif(sys.platform == "win32", reason="file modes")
def test_lockout_is_written_by_rename_never_through_a_link(tmp_path):
    import os
    f = tmp_path / "setup_lockout.xml"
    victim = tmp_path / "victim"
    victim.write_text("root's\n", encoding="utf-8")
    os.chmod(victim, 0o644)
    os.symlink(victim, f)
    lock = setup_code.Lockout(f)
    lock.attempt("192.0.2.20")
    assert victim.read_text(encoding="utf-8") == "root's\n" and os.stat(victim).st_mode & 0o777 == 0o644
    assert not f.is_symlink() and os.stat(f).st_mode & 0o777 == 0o600
    ino = os.stat(f).st_ino
    lock.attempt("192.0.2.21")
    assert os.stat(f).st_ino != ino                                  # a new file renamed in each time


def test_a_broken_lockout_file_starts_clean(tmp_path):
    f = tmp_path / "setup_lockout.xml"
    f.write_text("<not-closed", encoding="utf-8")
    assert setup_code.Lockout(f).attempt("192.0.2.20") is not None


# ---------------------------------------------------------------- names of the owner's DNS (the live bug, 2026-11-09)

def _resolve(monkeypatch, table):
    """getaddrinfo as the owner's DNS answers it: name -> address; this server's own address is 192.0.2.10."""
    monkeypatch.setattr(pairing, "local_ips", lambda: ["192.0.2.10"])
    monkeypatch.setattr(setup_page, "_RESOLVED", {})

    def gai(name, port, *a, **kw):
        if name not in table:
            raise socket.gaierror("no such name")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[name], 0))]
    monkeypatch.setattr(setup_page.socket, "getaddrinfo", gai)


def test_a_local_dns_alias_of_this_server_is_accepted(app, monkeypatch, tmp_path):
    _resolve(monkeypatch, {"workshop.lan": "192.0.2.10", "kit": "192.0.2.10", "kit.home.example": "192.0.2.10"})
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 192.0.2.1\nsearch home.example\n")
    monkeypatch.setattr(setup_page, "RESOLV_CONF", str(resolv))       # the router's domain, as DHCP hands it out
    for base in ("https://workshop.lan:8710", "https://kit:8710", "https://kit.home.example:8710"):
        assert client(app, base=base).get("/setup").status_code == 200, base


def test_a_public_name_is_refused_even_when_it_resolves_here(app, monkeypatch):
    """DNS rebinding: an attacker's public name answering with this server's address must not open the page."""
    _resolve(monkeypatch, {"rebind.example.com": "192.0.2.10", "other.lan": "192.0.2.99"})
    r = client(app, base="https://rebind.example.com:8710").get("/setup")
    assert r.status_code == 403 and "Settings tab" in r.text and "192.0.2.10" not in r.text
    assert "kit.local" not in r.text and "<p>Open the setup page" in r.text    # F2: no own names to a stranger
    assert client(app, base="https://other.lan:8710").get("/setup").status_code == 403      # local, but not here
    j = post(client(app, base="https://rebind.example.com:8710"), "key", {"key": KEY},
             headers={"Origin": "https://rebind.example.com:8710"})
    assert j.status_code == 403 and "Names for this page" in j.json()["error"]


def test_a_name_added_on_the_settings_tab_is_accepted(app, monkeypatch):
    _resolve(monkeypatch, {})
    cfg = config.load()
    cfg["setup"] = {"hosts": ["kit.example.net"]}
    config.save(cfg)
    assert client(app, base="https://kit.example.net:8710").get("/setup").status_code == 200


def test_local_names():
    assert all(setup_page.local_name(n) for n in ("kit", "workshop.lan", "kit.lan", "x.home.arpa", "a.local"))
    assert not any(setup_page.local_name(n) for n in ("rebind.example.com", "192.0.2.10", "", "fe80::1", "local.com"))


def test_a_name_under_the_resolvers_search_domain_is_local(tmp_path, monkeypatch):
    """The home network's own domain, as the router hands it out (resolv.conf `search` or `domain`), counts as local:
    that is how a router's default domain is reached without naming any particular one in the code."""
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 192.0.2.1\nsearch home.example corp.example\n")
    monkeypatch.setattr(setup_page, "RESOLV_CONF", str(resolv))
    assert setup_page.local_name("workshop.home.example") and setup_page.local_name("kit.corp.example")
    assert not setup_page.local_name("workshop.other.example")
    resolv.write_text("domain office.example\n")
    assert setup_page.local_name("kit.office.example")


def test_the_names_setting_takes_dns_names_only():
    assert setup_helper._hosts("Kit.Example.net, workshop.lan kit.example.net.") == \
        ["kit.example.net", "workshop.lan"]
    assert setup_helper._hosts([]) == []
    for bad in (["192.0.2.10"], ["a b"], ["-x.com"], ["x" * 64 + ".com"], [f"h{i}.lan" for i in range(21)], 5):
        with pytest.raises(ValueError):
            setup_helper._hosts(bad)
    assert setup_helper.GENERAL["setup.hosts"][1] is None          # saved without a restart: read on every request
