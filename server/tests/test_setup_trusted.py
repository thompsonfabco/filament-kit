"""Trusted computers (trusted.py): set, used, run out, revoked, turned off; the cookie's attributes; no token in a reply's body or a
log; the setup-code path the same without a cookie; only the root helper checks it; the second question stays in the page."""
from __future__ import annotations

import logging
import stat
import sys

import pytest

from filament_kit import config, setup_helper, trusted
from test_setup_page import BASE, CODE, H, HOME, STATIC, client, env, helper, make, manager, post  # noqa: F401

SET_COOKIE = "set-cookie"
AGENT = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0"}


@pytest.fixture
def app(env, helper, manager):
    return make(env, helper, manager)


def _trust(c, code=CODE, **body):
    return c.post("/setup/api/trust", json={"code": code, **body}, headers={**H, **AGENT})


def _change(c, code=""):
    """A change the server makes itself, with no code typed."""
    return c.post("/setup/api/readers", json={"code": code, "name": "bench"}, headers=H)


def _helper_change(c):
    """A change the root helper makes."""
    return c.post("/setup/api/key", json={"key": "sk-ant-EXAMPLE"}, headers=H)


def test_trust_needs_the_typed_code_and_the_body_never_holds_the_token(app, caplog):
    caplog.set_level(logging.DEBUG)
    c = client(app)
    assert _trust(c, code="").status_code == 403
    assert _trust(c, code="00000000").status_code == 403
    r = _trust(c)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Edge on Windows"
    token = c.cookies[trusted.COOKIE]
    assert trusted.TOKEN.fullmatch(token) and token not in r.text and token not in caplog.text
    assert f"computer {r.json()['id']} trusted from 192.0.2.20" in caplog.text


def test_cookie_attributes(app):
    r = _trust(client(app))
    cookie = r.headers[SET_COOKIE].lower()
    for part in ("httponly", "secure", "samesite=strict", "path=/setup", f"max-age={trusted.LIFETIME}"):
        assert part in cookie, part


def test_a_trusted_computer_changes_things_without_the_code(app, helper):
    c = client(app)
    _trust(c)
    r = _change(c)
    assert r.status_code == 200, r.text
    assert _helper_change(c).status_code == 200
    assert trusted.COOKIE in r.headers[SET_COOKIE]     # its time is renewed with each use
    assert c.get("/setup/api/trust").json()["trusted"] is True


def test_without_a_cookie_the_code_path_is_the_same(app, helper):
    c = client(app)
    assert _change(c).status_code == 403
    assert _helper_change(c).status_code == 403
    r = _change(c, CODE)
    assert r.status_code == 200 and SET_COOKIE not in r.headers
    assert c.get("/setup/api/trust").json() == {"ok": True, "status": 200, "enabled": True, "trusted": False, "id": None, "name": None,
                                                         "expires": None}


def test_get_trust_reports_this_computers_expiry_without_the_code(app):
    import time
    c = client(app)
    r = _trust(c)
    got = c.get("/setup/api/trust").json()
    listed = {d["id"]: d for d in c.post("/setup/api/trust/list", json={"code": CODE}, headers=H).json()["devices"]}
    assert got["trusted"] is True and got["expires"] == listed[r.json()["id"]]["expires"]       # the list's own value
    assert abs(got["expires"] - (time.time() + trusted.LIFETIME)) < 60


def test_a_typed_code_wins_over_the_cookie(app):
    c = client(app)
    _trust(c)
    assert _change(c, "00000000").status_code == 403


def test_another_browser_is_not_trusted(app):
    _trust(client(app))
    assert _change(client(app)).status_code == 403


def test_a_made_up_or_malformed_cookie_is_nothing_and_counts_against_no_lockout(app):
    c = client(app)
    c.cookies.set(trusted.COOKIE, "x" * 43, domain="kit.local", path="/setup")
    for _ in range(8):
        r = _change(c)
        assert r.status_code == 403 and r.json().get("trust_gone") is True
        c.cookies.set(trusted.COOKIE, "x" * 43, domain="kit.local", path="/setup")
    assert _change(c, CODE).status_code == 200
    c.cookies.set(trusted.COOKIE, "short", domain="kit.local", path="/setup")
    r = _change(c)
    assert r.status_code == 403 and "trust_gone" not in r.json()


def test_it_runs_out_and_use_renews_it(env, monkeypatch):
    now = 1_000_000.0
    did, token = trusted.add("A", "192.0.2.20", now)
    assert trusted.use(token, "192.0.2.20", now + trusted.LIFETIME - 1)["id"] == did
    assert trusted.use(token, "192.0.2.20", now + trusted.LIFETIME + 100)["id"] == did      # renewed by the use before
    assert trusted.use(token, "192.0.2.20", now + 3 * trusted.LIFETIME) is None
    assert trusted.listing(now + 3 * trusted.LIFETIME) == []


def test_a_cookie_past_its_time_is_refused_and_cleared(app, monkeypatch):
    c = client(app)
    _trust(c)
    st = trusted._load()
    st["devices"][0]["expires"] = 1000.0        # the server's own clock: a browser drops its copy of the cookie by itself
    trusted._save(st)
    r = _change(c)
    assert r.status_code == 403 and r.json()["trust_gone"] is True and trusted.COOKIE not in c.cookies


def test_revoking_is_immediate(app):
    other, mine = client(app), client(app)
    oid = _trust(other).json()["id"]
    _trust(mine)
    assert _change(other).status_code == 200
    r = mine.post(f"/setup/api/trust/{oid}/revoke", json={}, headers=H)
    assert r.status_code == 200 and r.json()["self"] is False and trusted.COOKIE in mine.cookies
    r = _change(other)
    assert r.status_code == 403 and r.json()["trust_gone"] is True and trusted.COOKIE not in other.cookies
    assert _change(mine).status_code == 200


def test_revoking_this_computer_clears_its_cookie(app):
    c = client(app)
    did = _trust(c).json()["id"]
    r = c.post(f"/setup/api/trust/{did}/revoke", json={}, headers=H)
    assert r.json()["self"] is True and trusted.COOKIE not in c.cookies
    assert _change(c).status_code == 403


def test_revoke_all(app):
    a, b = client(app), client(app)
    _trust(a), _trust(b)
    assert post(client(app), "trust/revoke_all", {}).json()["count"] == 2
    assert _change(a).status_code == 403 and _change(b).status_code == 403


def test_the_list_names_this_computer_and_holds_no_secret(app):
    c = client(app)
    did = _trust(c).json()["id"]
    assert post(client(app), "trust/list", {}, code="").status_code == 403
    r = c.post("/setup/api/trust/list", json={}, headers=H)
    j = r.json()
    assert j["this"] == did and j["enabled"] is True and j["devices"][0]["name"] == "Edge on Windows"
    assert j["devices"][0]["last_address"] == "192.0.2.20"
    assert set(j["devices"][0]) == {"id", "name", "created", "last_seen", "last_address", "expires"}
    assert c.cookies[trusted.COOKIE] not in r.text


def test_rename(app):
    c = client(app)
    did = _trust(c).json()["id"]
    assert c.post(f"/setup/api/trust/{did}/rename", json={"name": "Bench PC"}, headers=H).status_code == 200
    assert trusted.listing()[0]["name"] == "Bench PC"
    assert c.post("/setup/api/trust/abc/rename", json={"name": "x"}, headers=H).status_code == 404
    assert c.post("/setup/api/trust/abcdefabcdef/revoke", json={}, headers=H).status_code == 404


def test_a_new_address_is_kept_and_logged_and_still_accepted(app, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(app)
    did = _trust(c).json()["id"]
    token = c.cookies[trusted.COOKIE]
    moved = client(app, who=("192.0.2.33", 50000))
    moved.cookies.set(trusted.COOKIE, token, domain="kit.local", path="/setup")
    assert _change(moved).status_code == 200
    assert trusted.listing()[0]["last_address"] == "192.0.2.33"
    assert f"trusted computer {did} seen at a new address: 192.0.2.33" in caplog.text and token not in caplog.text


def test_the_off_switch_forgets_them_all_and_on_trusts_nobody(app):
    c = client(app)
    _trust(c)
    r = c.post("/setup/api/trust/enabled", json={"enabled": False}, headers=H)
    assert r.status_code == 200 and r.json()["forgotten"] == 1 and trusted.COOKIE not in c.cookies
    assert c.get("/setup/api/trust").json()["enabled"] is False
    r = _trust(c)
    assert r.status_code == 409 and "turned off" in r.json()["error"]
    assert _change(c, CODE).status_code == 200      # the code goes on as ever
    assert post(c, "trust/enabled", {"enabled": True}).json()["enabled"] is True
    assert trusted.listing() == [] and _trust(c).status_code == 200


def test_on_by_default_with_no_file(env):
    assert trusted.enabled() is True and trusted.status(None)["enabled"] is True


def test_a_trusted_browser_can_not_trust_another(app):
    c = client(app)
    _trust(c)
    r = c.post("/setup/api/trust", json={}, headers=H)
    assert r.status_code == 403 and "type the setup code" in r.json()["error"]


def test_the_helper_itself_refuses_a_token_for_trust_add(env):
    _, token = trusted.add("A", "192.0.2.20")
    r = setup_helper.handle({"op": "trust_add", "code": trusted.PREFIX + token, "client": "192.0.2.20", "name": "B"})
    assert r["status"] == 403 and len(trusted.listing()) == 1


def test_the_helper_is_where_the_token_is_checked(env):
    _, token = trusted.add("A", "192.0.2.20")
    assert setup_helper.handle({"op": "check", "code": trusted.PREFIX + token, "client": "192.0.2.20"}) == {"ok": True, "status": 200}
    r = setup_helper.handle({"op": "check", "code": trusted.PREFIX + "y" * 43, "client": "192.0.2.20"})
    assert r["status"] == 403 and r["trust_gone"] is True
    assert setup_helper.handle({"op": "trust_list", "client": "192.0.2.20"})["status"] == 403
    r = setup_helper.handle({"op": "trust_status", "token": token, "client": "192.0.2.20"})
    assert r["trusted"] is True


def test_a_wrong_code_still_counts_and_the_code_path_locks_as_ever(env):
    for _ in range(5):
        assert setup_helper.handle({"op": "check", "code": "00000000", "client": "192.0.2.20"})["status"] == 403
    assert setup_helper.handle({"op": "check", "code": CODE, "client": "192.0.2.20"})["status"] == 429


def test_only_the_hash_is_on_disk_root_only(env):
    _, token = trusted.add("Bench", "192.0.2.20")
    path = config.paths().etc / trusted.FILE
    data = path.read_bytes()
    assert token.encode() not in data and trusted._hash(token).encode() in data
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert data.startswith(b"<trusted") and b"Bench" in data


def test_a_bad_file_trusts_nobody_and_the_code_still_works(env):
    _, token = trusted.add("A", "192.0.2.20")
    (config.paths().etc / trusted.FILE).write_bytes(b"not xml")
    assert trusted.use(token, "192.0.2.20") is None and trusted.status(token)["trusted"] is False
    assert setup_helper.handle({"op": "check", "code": CODE, "client": "192.0.2.20"})["status"] == 200


def test_a_name_with_markup_or_control_characters_stays_data(env):
    did, _ = trusted.add('<x a="b">\x07&', "192.0.2.20")
    assert trusted.listing()[0]["name"] == '<x a="b">&' and trusted.listing()[0]["id"] == did


def test_the_list_keeps_a_ceiling(env):
    now = 1000.0
    for i in range(trusted.MAX_DEVICES + 5):
        trusted.add(f"pc{i}", "192.0.2.20", now + i)
    names = [d["name"] for d in trusted.listing(now)]
    assert len(names) == trusted.MAX_DEVICES and "pc0" not in names


@pytest.mark.parametrize("agent, name", [
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/130 Safari/537", "Chrome on Windows"), ("Mozilla/5.0 (X11; Linux x86_64; rv:130) Firefox/130", "Firefox on Linux"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14) Safari/605", "Safari on Mac"), (None, "A computer"), ("curl/8", "A computer")])
def test_the_first_name_comes_from_the_browser(agent, name):
    assert trusted.name_from_agent(agent) == name


def _root_at_a_terminal(monkeypatch):
    import io
    from filament_kit import cli
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    s = io.StringIO("")
    s.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", s)
    return cli


def test_a_new_setup_code_keeps_trusted_computers_and_says_so(app, helper, monkeypatch, capsys):
    """Review R32 ruling: security is the owner's choice. A new code keeps trusted computers (they stood in for the old
    one by the owner's own choice) and says so, with where to revoke; --revoke-trusted is the other choice."""
    cli = _root_at_a_terminal(monkeypatch)
    c = client(app)
    _trust(c)
    capsys.readouterr()
    assert cli.main(["setup-code", "--new"]) == 0
    out = capsys.readouterr().out
    assert "The old setup code no longer works." in out
    assert "Trusted computers stay trusted (1): revoke them in Devices on the setup page, or with sudo filament-kit setup-code --revoke-trusted." in out
    assert _change(c).status_code == 200 and _change(c, code=CODE).status_code == 403     # cookie yes, old code no
    assert cli.main(["setup-code", "--new", "--revoke-trusted"]) == 0
    out = capsys.readouterr().out
    assert "1 trusted computer revoked: each needs the setup code again." in out and "stay trusted" not in out
    assert _change(c).status_code == 403 and trusted.listing() == []
    assert cli.main(["setup-code", "--new"]) == 0
    assert "trusted" not in capsys.readouterr().out.lower()                                 # nobody trusted: no line
    assert cli.main(["setup-code", "--revoke-trusted"]) == 0
    assert "0 trusted computers revoked" in capsys.readouterr().out


def test_the_page_and_the_guide_say_a_new_code_keeps_trusted_computers():
    trust = (STATIC / "setup_trust.js").read_text(encoding="utf-8")
    assert "keeps trusted computers trusted" in trust and "--revoke-trusted" in trust
    from pathlib import Path
    guide = (Path(__file__).resolve().parents[2] / "docs" / "user-guide.md").read_text(encoding="utf-8")
    assert "Trust this computer" in guide and "--revoke-trusted" in guide and "every change does." not in guide


def test_the_page_offers_it_in_the_unlock_dialog_and_keeps_the_rules():
    trust = (STATIC / "setup_trust.js").read_text(encoding="utf-8")
    assert "innerHTML" not in trust and "document.cookie" not in trust
    # S1.5: no offer after an unrelated change; the unlock dialog's checkbox, there while the feature is on
    assert "offerTrust" not in trust and "SW.lock.trustOffered = !!T.enabled" in trust
    setup = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert "offerTrust" not in setup and "codeIn" not in setup and "trustCard()" in setup
    # the code is held in memory by the shared script and sent in the body, never stored by the page
    assert "const theCode = () => SW.lock.code" in setup and "code: theCode()" in setup
    every = "".join(p.read_text(encoding="utf-8") for p in STATIC.glob("setup*.js"))
    assert "sessionStorage" not in every and "localStorage" not in every


def test_the_script_is_served_and_the_second_question_stays(app):
    c = client(app)
    assert "/setup/setup_trust.js" in c.get("/setup").text
    assert c.get("/setup/setup_trust.js").status_code == 200
    tabs = (STATIC / "setup_tabs.js").read_text(encoding="utf-8")
    assert "window.confirm(question)" in tabs   # update and rollback ask, trusted or not
