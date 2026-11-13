"""S1.4: the setup code check that changes nothing (`POST code/check`: right, wrong with `tries_left`, too many with `retry_at`,
the lockout the same as on any gated call), the trusted computer's expiry in `GET trust`, and `field` in the error replies of
the setup page's endpoints that check input (07 section 17)."""
from __future__ import annotations

import re
import time

import pytest

from filament_kit import config, setup_code, setup_helper
from test_setup_page import CODE, SERIAL, client, env, helper, make, manager, post  # noqa: F401

KL_NAME = "printer.example.com"
LOCAL_MINUTE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d")


@pytest.fixture
def app(env, helper, manager):
    return make(env, helper, manager, add=frozenset({"klipper"}))


def _check(c, code):
    return post(c, "code/check", {} if code is None else {"code": code}, code=None)


def test_a_right_code_is_ok_and_changes_nothing(app, helper):
    c = client(app)
    before = config.load()
    r = _check(c, CODE)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert _check(c, "1234-5678").status_code == 200           # typed with its dash, as everywhere
    assert helper.calls == ["check", "check"]                  # only the helper's check ran: no change op
    assert config.load() == before
    # and it unlocks nothing: a change still needs its own code
    assert post(c, "key", {"key": "sk-ant-EXAMPLE"}, code=None).status_code == 403


def test_a_wrong_code_says_how_many_tries_are_left_and_names_its_field(app):
    c = client(app)
    left = []
    for _ in range(setup_code.LOCK_MAX):
        r = _check(c, "00000000")
        assert r.status_code == 403 and r.json()["error"] == setup_helper.WRONG and r.json()["field"] == "code"
        left.append(r.json()["tries_left"])
    assert left == [4, 3, 2, 1, 0]
    r = _check(c, "00000000")                                  # the sixth: locked, with the time it ends
    assert r.status_code == 429 and r.json()["error"] == setup_helper.LOCKED and r.json()["field"] == "code"
    assert "tries_left" not in r.json()
    assert LOCAL_MINUTE.fullmatch(r.json()["retry_at"])
    ends = time.mktime(time.strptime(r.json()["retry_at"], "%Y-%m-%dT%H:%M"))
    assert 0 < ends - time.time() <= setup_code.LOCK_WINDOW + 60      # 10 minutes, rounded up to the minute
    assert _check(c, CODE).status_code == 429                  # a right code does not get through a lockout


def test_checks_and_changes_share_one_lockout(app):
    c = client(app)
    for _ in range(setup_code.LOCK_MAX - 1):
        assert _check(c, "00000000").status_code == 403
    r = post(c, "key", {"key": "sk-ant-EXAMPLE"}, code="00000000")          # the fifth wrong code, on a change
    assert r.status_code == 403 and r.json()["tries_left"] == 0 and r.json()["field"] == "code"
    assert _check(c, CODE).status_code == 429
    assert post(c, "key", {"key": "sk-ant-EXAMPLE"}, code=CODE).status_code == 429


def test_a_right_check_costs_no_try(app):
    c = client(app)
    for _ in range(3):
        assert _check(c, CODE).status_code == 200
    assert _check(c, "00000000").json()["tries_left"] == setup_code.LOCK_MAX - 1


def test_another_address_has_its_own_tries(app):
    c, other = client(app), client(app, ("192.0.2.21", 50000))
    for _ in range(setup_code.LOCK_MAX + 1):
        _check(c, "00000000")
    assert _check(other, "00000000").json()["tries_left"] == setup_code.LOCK_MAX - 1


def test_a_missing_or_typed_trust_code_is_refused_without_a_try(app, helper):
    c = client(app)
    r = _check(c, None)
    assert r.status_code == 403 and r.json()["field"] == "code"
    r = _check(c, "trusted:" + "a" * 43)                       # a cookie's stand-in is never typed
    assert r.status_code == 400 and r.json()["field"] == "code"
    assert helper.calls == []
    assert _check(c, "00000000").json()["tries_left"] == setup_code.LOCK_MAX - 1


def test_a_global_backoff_gives_its_end_as_retry_at(env, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(setup_code.time, "time", lambda: now[0])
    lock = setup_code.Lockout(config.paths().etc / "lock")
    for i in range(setup_code.GLOBAL_MAX):
        lock.attempt(f"192.0.2.{i}")
    left, until = lock.standing("192.0.2.200")
    assert left == 0 and until == now[0] + setup_code.LOCK_WINDOW
    now[0] += setup_code.LOCK_WINDOW + 1
    assert lock.standing("192.0.2.200") == (setup_code.LOCK_MAX, None)


def test_the_local_minute_rounds_up():
    t = time.mktime((2030, 5, 6, 7, 8, 1, 0, 0, -1))
    assert setup_code.local_minute(t) == "2030-05-06T07:09"
    assert setup_code.local_minute(t - 1) == "2030-05-06T07:08"


# ---------- field ----------

def _field(r, name, status=400):
    assert r.status_code == status, r.text
    assert r.json()["field"] == name, r.json()
    assert r.json()["error"]


def test_printer_add_errors_name_their_field(app):
    c = client(app)
    body = {"ip": "192.0.2.40", "access_code": "12345678", "serial": SERIAL}
    _field(post(c, "printers", {**body, "ip": "not an address"}), "address")
    _field(post(c, "printers", {**body, "access_code": "no spaces!"}), "access_code")
    _field(post(c, "printers", {**body, "name": 5}), "name")


def test_printer_code_error_names_its_field(app):
    _field(post(client(app), f"printers/{SERIAL}/code", {"access_code": "no spaces!"}), "access_code")


def test_klipper_errors_name_their_field(app, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.77", 0))])
    c = client(app)
    _field(post(c, "printers/klipper", {"host": "not an address"}), "host")
    _field(post(c, "printers/klipper", {"host": KL_NAME, "port": 70000}), "port")
    _field(post(c, "printers/klipper", {"host": KL_NAME, "api_key": "has spaces"}), "api_key")
    sid = post(c, "printers/klipper", {"host": KL_NAME, "name": "Workshop"}).json()["serial"]
    _field(post(c, "printers/klipper", {"host": KL_NAME}), "host", 409)
    _field(post(c, f"printers/{sid}/rename", {"name": "  "}), "name")
    _field(post(c, f"printers/{sid}/address", {"address": "not an address"}), "address")
    _field(post(c, f"printers/{sid}/address", {"address": KL_NAME, "port": "x"}), "port")
    _field(post(c, f"printers/{sid}/api_key", {"api_key": "has spaces"}), "api_key")
    assert "field" not in post(c, f"printers/{sid}/lane_data", {"mode": "nope"}).json()      # about no one field of the list


def test_helper_endpoint_errors_name_their_field(app, helper):
    c = client(app)
    _field(post(c, "key", {"key": 5}), "key")
    _field(post(c, "passphrase", {"passphrase": 5}), "passphrase")
    _field(post(c, "passphrase", {"passphrase": "short"}), "passphrase")
    _field(post(c, "settings", {"key": "nope", "value": "x"}), "key")
    _field(post(c, "settings", {"key": "station.url", "value": "ftp://x"}), "value")
    _field(post(c, "settings/general", {"key": "nope", "value": "x"}), "key")
    _field(post(c, "settings/general", {"key": "reads_per_day", "value": 100001}), "value")
    _field(post(c, "settings/spoolman", {"url": ""}), "url")
    _field(post(c, "settings/spoolman", {"url": "not a url"}), "url")
    _field(post(c, "backups/keep", {"days": 0}), "days")
    _field(post(c, "readers", {"name": 5}), "name")
    # a missing code names the code field (the page locks again on it)
    assert post(c, "key", {"key": "sk-ant-EXAMPLE"}, code=None).json()["field"] == "code"   # refused for the code (S1.5 locks on it)


def test_a_gated_change_refused_for_its_code_names_the_code_field(app):
    """The page locks again only on replies with field "code" (S1.5): no code, a wrong code and a lockout on an ordinary
    change all carry it; an error about the change's own input does not."""
    c = client(app)
    r = post(c, "key", {"key": "sk-ant-EXAMPLE"}, code=None)
    assert r.status_code == 403 and r.json()["field"] == "code"
    for _ in range(setup_code.LOCK_MAX):
        r = post(c, "key", {"key": "sk-ant-EXAMPLE"}, code="00000000")
        assert r.status_code in (403, 429) and r.json()["field"] == "code"
    r = post(c, "key", {"key": "sk-ant-EXAMPLE"}, code="00000000")
    assert r.status_code == 429 and r.json()["field"] == "code"
