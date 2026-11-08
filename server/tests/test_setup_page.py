"""The kit server's /setup page (setup_page.py) and its root helper (setup_helper.py), with the helper called
in-process (as JSON, like over its socket), FK_NO_SYSTEMD=1 (no apply runs) and doc values only.

Pinned: the setup code for every write (missing / wrong -> 403, lockout -> 429), LAN only, the server's own Host
and Origin, write-only secrets (never in a reply or a log), each section's write landing in the same file as the
CLI's, one audit line per change without the value, the root helper's own checks, `setup-code` and the installer's
closing line at a terminal and without one."""
from __future__ import annotations

import io
import json
import logging
import re
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from filament_kit import api, apply, cli, config, library, modules, pairing, reader_tokens, setup_code, setup_helper
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
    monkeypatch.setattr(setup_helper, "_start_apply", lambda: applied.append(True))
    return applied


class Helper:
    """The root helper as the server sees it: JSON in, JSON out."""

    def __init__(self):
        self.calls = []

    def __call__(self, req):
        self.calls.append(req["op"])
        return json.loads(json.dumps(setup_helper.handle(json.loads(json.dumps(req)))))


@pytest.fixture
def helper():
    return Helper()


@pytest.fixture
def manager():
    return FakeManager()


def make(env, helper, manager=None, client_factory=None):
    on = modules.enabled(config.load())
    if manager is None:
        on = on - {"printers"}
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
    before = sorted(p.name for p in config.paths().etc.iterdir())
    for code in (None, "", "99999999", "1234-567"):
        r = post(c, path, body, code=code)
        assert r.status_code == 403, (path, code, r.text)
    assert not helper.calls and manager.synced == 0
    assert sorted(p.name for p in config.paths().etc.iterdir()) == before
    assert not registry.load()


def test_wrong_codes_lock_the_page_for_ten_minutes(app, helper):
    c = client(app)
    for _ in range(setup_code.LOCK_MAX):
        assert post(c, "key", {"key": KEY}, code="00000000").status_code == 403
    r = post(c, "key", {"key": KEY})                  # even the right code, now
    assert r.status_code == 429 and "10 minutes" in r.json()["error"]
    assert not _etc("anthropic_key").exists() and not helper.calls


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
    assert post(c, "printers", {**body, "ip": "not-an-ip"}).status_code == 400
    assert post(c, "printers", {**body, "access_code": "no spaces!"}).status_code == 400


def test_printers_section_is_off_without_the_printers_module(env, helper):
    c = client(make(env, helper))
    assert c.get("/setup/api/state").json()["printers"]["on"] is False
    r = post(c, "printers", {"ip": "192.0.2.40", "access_code": "12345678", "serial": SERIAL})
    assert r.status_code == 409 and not registry.load()


# ---------- modules, addresses, the apply ----------

def test_module_switch_uses_the_checklist_rules_and_starts_an_apply(app, env, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(app)
    pv = c.get("/setup/api/modules/preview?name=orders").json()
    assert pv["on"] is True and "ai_intake" in pv["after"] and any("ai_intake" in n for n in pv["notes"])
    assert [n["key"] for n in pv["needs"]] == ["orders.file"]
    r = post(c, "modules", {"name": "orders", "on": True})
    assert r.status_code == 400 and r.json()["needs"] == ["orders.file"] and not env
    r = post(c, "modules", {"name": "orders", "on": True, "settings": {"orders.file": "/srv/orders.json"}})
    assert r.status_code == 200 and r.json()["changed"] is True
    cfg = config.load()
    assert {"orders", "ai_intake"} <= modules.enabled(cfg) and cfg["orders"]["file"] == "/srv/orders.json"
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
    code = setup_helper.run_apply([sys.executable, "-c", "print('==> Status'); print('OK  done')"])
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
    assert "ReadWritePaths=/etc/filament-kit\n" in svc and "-m filament_kit.setup_helper\n" in svc
    run = (systemd / "filament-kit-setup-apply.service").read_text(encoding="utf-8")
    assert "setup_helper apply-run" in run


# ---------- the setup code: CLI and installer ----------

def _stdin(monkeypatch, tty):
    s = io.StringIO("")
    s.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", s)


def test_setup_code_cli_prints_it_at_a_terminal_only(env, monkeypatch, capsys):
    monkeypatch.setattr(pairing, "short_hostname", lambda: "kit")
    _stdin(monkeypatch, True)
    assert cli.main(["setup-code"]) == 0
    assert capsys.readouterr().out.strip() == "Open https://kit.local:8710/setup  (setup code: 1234-5678)"
    _stdin(monkeypatch, False)
    assert cli.main(["setup-code"]) == 0
    out = capsys.readouterr().out
    assert "https://kit.local:8710/setup" in out and "1234-5678" not in out and CODE not in out


def test_setup_code_new_replaces_it(env, monkeypatch, capsys):
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
    path = str(tmp_path / "setup.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        with conn:
            subprocess.run([sys.executable, "-I", "-m", "filament_kit.setup_helper"], stdin=conn.fileno(),
                           stdout=conn.fileno(), env={**os.environ}, check=False, timeout=60)
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    reply = setup_page.HelperClient(path)({"op": "key_set", "code": CODE, "key": KEY})
    t.join(30)
    srv.close()
    assert reply == {"ok": True, "status": 200}
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
    assert seen == [["systemctl", "show", "--property=ActiveState", "--value", setup_helper.APPLY_UNIT]]
