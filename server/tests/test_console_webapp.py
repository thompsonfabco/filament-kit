"""The iPhone's entry on the setup console's Devices tab."""
from __future__ import annotations

from pathlib import Path

import pytest
from test_setup_page import Helper, client, env, make  # noqa: F401

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


def test_off_says_so_and_nothing_else(app):
    _web(on=False, public="https://fk.example.org/filament")
    assert client(app).get("/setup/api/webapp").json() == {"on": False}


def test_the_public_address_wins(app, monkeypatch):
    _web(public="https://fk.example.org/filament")
    monkeypatch.setattr(setup_page, "qr_svg", lambda url: f"<svg>{url}</svg>")
    r = client(app).get("/setup/api/webapp").json()
    assert r == {"on": True, "url": "https://fk.example.org/filament", "set_address": True,
                 "qr_svg": "<svg>https://fk.example.org/filament</svg>"}


def test_with_no_public_address_it_is_the_home_address(app, monkeypatch):
    _web()
    monkeypatch.setattr(pairing, "short_hostname", lambda: "kit")
    monkeypatch.setattr(setup_page, "qr_svg", lambda url: None)      # no qrencode: the address alone
    r = client(app).get("/setup/api/webapp").json()
    assert r["url"] == "https://kit.local/filament" and r["set_address"] is False and r["qr_svg"] is None


def test_the_devices_tab_has_the_card():
    src = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert "webAppCard()" in src and "function webAppCard(" in src and "Add to Home Screen" in src
