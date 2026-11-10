"""PATCH / DELETE /api/printers/{id}: a paired device edits and forgets printers, as the setup page's printer routes."""
import logging

import pytest
from starlette.testclient import TestClient

from filament_kit import config, pairing
from filament_kit.api import create_app
from filament_kit.bridge import family, registry

CODE = "12345678"
SERIAL = "01P00A111111111"
ON = frozenset({"server", "printers", "klipper"})


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({})


class Fam:
    """One family's connections: counts syncs and waits; state is whatever the test sets."""

    def __init__(self):
        self.synced, self.waited, self.state_of = 0, [], "connected"

    def state(self, pid):
        return self.state_of

    def summary(self, pid):
        return None

    def status(self, pid):
        return None

    def sync(self):
        self.synced += 1

    def wait_settled(self, pid, timeout):
        self.waited.append(pid)
        return self.state_of

    def verified(self, pid):
        return False

    def camera_kind(self, pid):
        return None


def _client(bambu=True, klipper=True, token=True):
    b, k = (Fam() if bambu else None), (Fam() if klipper else None)
    on = frozenset({"server"} | ({"printers"} if bambu else set()) | ({"klipper"} if klipper else set()))
    app = create_app(object(), printers=family.Printers(bambu=b, klipper=k), camera_hub=object(), mapper=object(),
                     enabled_modules=on)
    c = TestClient(app)
    if token:
        c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
    return c, b, k


def _bambu(fp="ab" * 32):
    registry.upsert(registry.Printer(SERIAL, "Shop P1S", "C12", "10.0.0.5", CODE, True, cert_fp=fp))


def _klipper(name="SV08 MAX", host="10.0.1.20"):
    return registry.add_klipper(name, host).serial


def test_both_need_a_token():
    _bambu()
    c, _, _ = _client(token=False)
    assert c.patch(f"/api/printers/{SERIAL}", json={"name": "x"}).status_code == 401
    assert c.delete(f"/api/printers/{SERIAL}").status_code == 401
    assert registry.load()[SERIAL].name == "Shop P1S"


def test_rename_answers_at_once_with_the_printer():
    _bambu()
    c, b, _ = _client()
    r = c.patch(f"/api/printers/{SERIAL}", json={"name": "  Garage  "})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["changed"] == ["name"] and j["printer"]["name"] == "Garage" and j["printer"]["id"] == SERIAL
    assert registry.load()[SERIAL].name == "Garage"
    assert b.synced == 1 and b.waited == []           # a rename alone does not wait for a connection
    assert CODE not in r.text


def test_a_taken_name_gets_a_suffix_as_the_setup_page():
    _bambu()
    registry.upsert(registry.Printer("01P00A222222222", "Garage", "C12", "10.0.0.6", CODE, True))
    c, _, _ = _client()
    assert c.patch(f"/api/printers/{SERIAL}", json={"name": "Garage"}).json()["printer"]["name"] == "Garage 2"


def test_access_code_replaces_it_clears_the_pin_and_waits():
    _bambu()
    c, b, _ = _client()
    b.state_of = "wrong_code"
    r = c.patch(f"/api/printers/{SERIAL}", json={"access_code": "87654321"})
    assert r.status_code == 200, r.text
    p = registry.load()[SERIAL]
    assert p.access_code == "87654321" and p.cert_fp == "" and p.configured
    assert r.json()["printer"]["state"] == "wrong_code" and b.waited == [SERIAL]
    assert "87654321" not in r.text


def test_unpin_and_address_together():
    _bambu()
    c, b, _ = _client()
    r = c.patch(f"/api/printers/{SERIAL}", json={"unpin": True, "address": "10.0.0.9"})
    assert r.status_code == 200, r.text
    p = registry.load()[SERIAL]
    assert p.cert_fp == "" and p.ip == "10.0.0.9" and p.access_code == CODE
    assert sorted(r.json()["changed"]) == ["address", "unpin"] and b.waited == [SERIAL]


def test_an_address_outside_the_home_networks_comes_with_its_note():
    _bambu()
    c, _, _ = _client()
    r = c.patch(f"/api/printers/{SERIAL}", json={"address": "203.0.113.7"})
    assert r.status_code == 200 and r.json().get("note"), r.text


@pytest.mark.parametrize("body, says", [
    ({}, "nothing to change"),
    ({"colour": "red"}, "unknown key: colour"),
    ({"name": ""}, "give the printer a name"),
    ({"name": "x" * 65}, "give the printer a name"),
    ({"name": 5}, "give the printer a name"),
    ({"access_code": "12 34"}, "Access Code"),
    ({"unpin": False}, "unpin must be true"),
    ({"api_key": "k"}, "api_key is for a Klipper printer"),
    ({"port": 7125}, "port is for a Klipper printer"),
    ({"address": "not a host!"}, "give an IP address or a host name"),
])
def test_a_bad_bambu_body_changes_nothing(body, says):
    _bambu()
    before = registry.load()[SERIAL]
    c, b, _ = _client()
    r = c.patch(f"/api/printers/{SERIAL}", json=body)
    assert r.status_code == 400 and r.json()["error"] == "bad_request" and says in r.json()["message"], r.text
    assert registry.load()[SERIAL] == before and b.synced == 0


def test_one_bad_key_refuses_the_good_ones_too():
    _bambu()
    c, _, _ = _client()
    r = c.patch(f"/api/printers/{SERIAL}", json={"name": "Garage", "access_code": "no spaces allowed"})
    assert r.status_code == 400
    assert registry.load()[SERIAL].name == "Shop P1S"


def test_klipper_address_port_and_key():
    pid = _klipper()
    c, _, k = _client()
    r = c.patch(f"/api/printers/{pid}", json={"address": "10.0.1.21", "port": 7130, "api_key": "abcDEF123"})
    assert r.status_code == 200, r.text
    p = registry.load()[pid]
    assert (p.host, p.port, p.api_key) == ("10.0.1.21", 7130, "abcDEF123")
    assert sorted(r.json()["changed"]) == ["address", "api_key", "port"] and k.waited == [pid]
    assert "abcDEF123" not in r.text
    assert c.patch(f"/api/printers/{pid}", json={"api_key": ""}).status_code == 200
    assert registry.load()[pid].api_key == ""


def test_klipper_port_alone_keeps_the_host():
    pid = _klipper()
    c, _, _ = _client()
    assert c.patch(f"/api/printers/{pid}", json={"port": 7200}).status_code == 200
    p = registry.load()[pid]
    assert (p.host, p.port) == ("10.0.1.20", 7200)


@pytest.mark.parametrize("body, says", [
    ({"access_code": CODE}, "a Klipper printer has no Access Code"),
    ({"unpin": True}, "unpin is for a Bambu printer"),
    ({"port": 0}, "the port must be a number from 1 to 65535"),
    ({"port": True}, "the port must be a number from 1 to 65535"),
    ({"api_key": "has space"}, "API key"),
])
def test_a_bad_klipper_body_changes_nothing(body, says):
    pid = _klipper()
    before = registry.load()[pid]
    c, _, _ = _client()
    r = c.patch(f"/api/printers/{pid}", json=body)
    assert r.status_code == 400 and says in r.json()["message"], r.text
    assert registry.load()[pid] == before


def test_klipper_address_taken_by_another_is_409_exists():
    a = _klipper("A", "10.0.1.20")
    _klipper("B", "10.0.1.30")
    c, _, _ = _client()
    r = c.patch(f"/api/printers/{a}", json={"address": "10.0.1.30"})
    assert r.status_code == 409 and r.json()["error"] == "exists" and "already at 10.0.1.30" in r.json()["message"]
    assert registry.load()[a].host == "10.0.1.20"


def test_unknown_printer_is_404_for_both():
    c, _, _ = _client()
    for r in (c.patch("/api/printers/NOPE", json={"name": "x"}), c.delete("/api/printers/NOPE")):
        assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_delete_forgets_the_printer_and_logs_it(caplog):
    _bambu()
    c, b, _ = _client()
    with caplog.at_level(logging.INFO, logger="filament_kit.api"):
        r = c.delete(f"/api/printers/{SERIAL}")
    assert r.status_code == 200 and r.json() == {"ok": True, "id": SERIAL}
    assert SERIAL not in registry.load() and b.synced == 1
    assert any("printer forget" in m and SERIAL in m for m in caplog.messages)
    assert c.delete(f"/api/printers/{SERIAL}").status_code == 404


def test_edit_log_names_keys_never_values(caplog):
    _bambu()
    c, _, _ = _client()
    with caplog.at_level(logging.INFO, logger="filament_kit.api"):
        c.patch(f"/api/printers/{SERIAL}", json={"access_code": "87654321"})
    line = next(m for m in caplog.messages if "printer edit" in m)
    assert "access_code" in line and "87654321" not in line


def test_a_family_whose_module_is_off_is_409_module_off():
    pid = _klipper()
    _bambu()
    c, _, _ = _client(klipper=False)
    for r in (c.patch(f"/api/printers/{pid}", json={"name": "x"}), c.delete(f"/api/printers/{pid}")):
        assert r.status_code == 409 and r.json()["error"] == "module_off" and r.json()["module"] == "klipper"
    assert pid in registry.load()
    c, _, _ = _client(bambu=False)
    r = c.delete(f"/api/printers/{SERIAL}")
    assert r.status_code == 409 and r.json()["module"] == "printers"
    assert SERIAL in registry.load()


def test_the_web_unit_may_add_edit_and_forget_for_the_phone_web_app():
    """Parity gap 3: the phone web app's Manage printers calls these with its own (web) token."""
    from filament_kit.api import WEB_ROUTES
    for route in (("POST", "/api/printers"), ("PATCH", "/api/printers/{id}"), ("DELETE", "/api/printers/{id}")):
        assert route in WEB_ROUTES
