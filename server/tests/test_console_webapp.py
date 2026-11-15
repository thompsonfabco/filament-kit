"""The iPhone's entry on the setup console's Devices tab."""
from __future__ import annotations

from pathlib import Path

import pytest
from test_setup_page import Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, config, pairing, setup_page

STATIC = Path(cli.__file__).parent / "setup_static"


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Mgr())


def _web(on=True, public=None):
    cfg = config.load()
    cfg["modules"]["web"] = on
    cfg["web"] = {**cfg["web"], "public_url": public}
    config.save(cfg)


def test_with_the_web_module_off_it_is_the_servers_own_address(app, monkeypatch):
    """The user's decision 2026-11-09: the phone page is part of the main software, no module needed."""
    _web(on=False, public="https://fk.example.org/filament")
    monkeypatch.setattr(pairing, "short_hostname", lambda: "kit")
    monkeypatch.setattr(setup_page, "qr_svg", lambda url: f"<svg>{url}</svg>")
    assert client(app).get("/setup/api/webapp").json() == {
        "url": "https://kit.local:8710/intake", "qr_svg": "<svg>https://kit.local:8710/intake</svg>",
        "public_url": None, "public_qr_svg": None, "public_hidden": False}


def test_with_the_web_module_on_the_public_address_is_offered_with_the_code(app, monkeypatch):
    _web(public="https://fk.example.org/filament/")
    monkeypatch.setattr(pairing, "short_hostname", lambda: "kit")
    monkeypatch.setattr(setup_page, "qr_svg", lambda url: f"<svg>{url}</svg>")
    r = post(client(app), "webapp").json()
    assert r["url"] == "https://kit.local:8710/intake"
    assert r["public_url"] == "https://fk.example.org/filament/intake"
    assert r["public_qr_svg"] == "<svg>https://fk.example.org/filament/intake</svg>"
    assert r["public_hidden"] is False


def test_without_the_code_the_public_address_stays_hidden(app, monkeypatch):
    """FA-017: the public host is one of the values `redact` hides, so what answers without the code leaves it out."""
    _web(public="https://fk.example.org/filament/")
    monkeypatch.setattr(pairing, "short_hostname", lambda: "kit")
    monkeypatch.setattr(setup_page, "qr_svg", lambda url: f"<svg>{url}</svg>")
    r = client(app).get("/setup/api/webapp")
    assert r.json()["public_url"] is None and r.json()["public_qr_svg"] is None and r.json()["public_hidden"] is True
    assert "fk.example.org" not in r.text
    assert post(client(app), "webapp", code="00000000").status_code == 403
    assert post(client(app), "webapp", code=None).status_code == 403


def test_an_address_that_does_not_fit_a_code_is_given_alone(app, monkeypatch):
    _web(public="https://fk.example.org/filament")
    monkeypatch.setattr(setup_page, "qr_svg", lambda url: None)
    r = post(client(app), "webapp").json()
    assert r["qr_svg"] is None and r["public_url"] == "https://fk.example.org/filament/intake"         and r["public_qr_svg"] is None


def test_the_address_is_a_page_the_web_app_serves():
    """Held to the web app's own routes: its base address answers 404, so a card pointing there is a dead end."""
    from filament_kit.web import intake_app
    src = Path(intake_app.__file__).read_text(encoding="utf-8")
    assert '("/intake", self.page, ["GET"])' in src and '+ "/intake"' in src


def test_the_state_without_the_code_leaves_the_public_address_out(app):
    """FA-017 (review MED): GET /setup/api/state answers without the code too, and fills the Settings box."""
    _web(public="https://fk.example.org/filament")
    r = client(app).get("/setup/api/state")
    assert r.status_code == 200 and "fk.example.org" not in r.text
    assert "public_url" not in r.json()["web"] and r.json()["web"]["public_set"] is True
    _web(public=None)
    assert client(app).get("/setup/api/state").json()["web"]["public_set"] is False


def test_the_page_copes_with_the_missing_address_and_a_wrong_code_keeps_the_card():
    src = "".join((STATIC / n).read_text(encoding="utf-8") for n in ("setup_devices.js", "setup_settings.js"))
    assert "S.web.public_url" not in src and "S.web.public_set" in src
    # the public address is a hidden value: read with the code once the page is open, its note beside the card (S1.5)
    assert "whenOpen(body, load)" in src and 'lockNote("lock_hidden_note")' in src
    assert "Show the public address" not in src


def test_the_devices_tab_has_the_card():
    src = (STATIC / "setup_devices.js").read_text(encoding="utf-8")
    assert "webAppCard()" in src and "function webAppCard(" in src and "Add to Home Screen" in src
