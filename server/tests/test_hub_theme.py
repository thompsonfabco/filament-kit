"""S6.1: the Hub's default theme (`appearance.theme`) reaches both page shells (`data-look`, the two `theme-color` metas,
the two manifests) and `look` in GET api/info; the group save writes it and refuses an unknown name."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from starlette.applications import Starlette  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from test_setup_page import Helper, client, env, make, post  # noqa: E402, F401

from filament_kit import config  # noqa: E402
from filament_kit.web import mcp_tools  # noqa: E402
from filament_kit.web.intake_app import IntakeApp  # noqa: E402

LOOKS = ["console", "workbench", "palette", "panes"]
HOME = ("192.168.1.20", 50000)


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


def _tokens(look):
    p = Path(__file__).resolve().parents[2] / "tokens" / "tokens.json"
    return json.loads(p.read_text(encoding="utf-8"))["themes"][look]


def _metas(text):
    return re.findall(r"<meta name=theme-color content='([^']*)' media='([^']*)'>", text)


def _surfaces(look):
    t = _tokens(look)
    return t["light"]["surface"], t["dark"].get("surface", t["light"]["surface"])


def _set_look(look):
    cfg = config.load()
    cfg["appearance"] = {"theme": look}
    config.save(cfg)


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Mgr())


def _web_client():
    tools = mcp_tools.Tools(None, kit_api=object(), kit_writes=True)
    routes = IntakeApp(tools, public_url=None, lan_cidrs=["192.168.1.0/24"], push=False, host_ok=lambda r: True).routes()
    return TestClient(Starlette(routes=routes), base_url="https://hub.local:8710", client=HOME)


def test_default_is_console_everywhere(app):
    assert config.load()["appearance"]["theme"] == "console"
    assert client(app).get("/api/info").json()["look"] == "console"


@pytest.mark.parametrize("look", LOOKS)
def test_api_info_carries_look(app, look):
    _set_look(look)
    assert client(app).get("/api/info").json()["look"] == look


def test_unknown_stored_theme_is_console(app):
    _set_look("neon")
    assert client(app).get("/api/info").json()["look"] == "console"
    assert 'data-look=console>' in client(app).get("/setup").text


@pytest.mark.parametrize("look", LOOKS)
def test_hub_page_shell(app, look):
    _set_look(look)
    text = client(app).get("/setup").text
    assert text.startswith(f"<!doctype html><html lang=en data-look={look}>")
    light, dark = _surfaces(look)
    assert _metas(text) == [(light, "(prefers-color-scheme: light)"), (dark, "(prefers-color-scheme: dark)")]


@pytest.mark.parametrize("look", LOOKS)
def test_web_app_shell_and_manifests(look):
    _set_look(look)
    with _web_client() as c:
        text = c.get("/intake").text
        assert text.startswith(f"<!doctype html><html lang=en data-look={look}>")
        light, dark = _surfaces(look)
        assert _metas(text) == [(light, "(prefers-color-scheme: light)"), (dark, "(prefers-color-scheme: dark)")]
        t = _tokens(look)
        for appearance, got in (("light", light), ("dark", dark)):
            j = c.get(f"/intake/manifest-{appearance}.webmanifest").json()
            assert j["theme_color"] == got
            assert j["background_color"] == t[appearance].get("bg", t["light"]["bg"])
        assert c.get("/intake/manifest.webmanifest").json() == c.get("/intake/manifest-light.webmanifest").json()


def test_a_change_shows_on_the_next_page_without_a_restart(app):
    c = client(app)
    assert "data-look=console>" in c.get("/setup").text
    _set_look("palette")
    assert "data-look=palette>" in c.get("/setup").text


@pytest.mark.parametrize("look", LOOKS)
def test_group_save_writes_and_state_reads_it(app, look):
    r = post(client(app), "settings/general", {"values": {"appearance.theme": look}})
    assert r.status_code == 200, r.text
    assert config.load()["appearance"]["theme"] == look
    assert client(app).get("/setup/api/settings/general").json()["values"]["appearance.theme"] == look
    assert client(app).get("/api/info").json()["look"] == look


@pytest.mark.parametrize("bad", ["", "Console", "neon", 5, None, True, ["panes"]])
def test_group_save_refuses_an_unknown_theme(app, bad):
    before = config.load()
    r = post(client(app), "settings/general", {"values": {"appearance.theme": bad}})
    assert r.status_code == 400, r.text
    assert config.load() == before


def test_single_key_save_and_state_read(app):
    assert post(client(app), "settings/general", {"key": "appearance.theme", "value": "panes"}).status_code == 200
    assert config.load()["appearance"]["theme"] == "panes"
    assert client(app).get("/setup/api/settings/general").json()["values"]["appearance.theme"] == "panes"


def test_state_reads_console_before_any_save(app):
    assert client(app).get("/setup/api/settings/general").json()["values"]["appearance.theme"] == "console"


# ---- rework (refuter-03) ----

@pytest.mark.parametrize("look", LOOKS)
def test_state_carries_the_theme(app, look):
    _set_look(look)
    assert client(app).get("/setup/api/state").json()["appearance"] == {"theme": look}


def test_state_and_general_read_console_for_an_unknown_stored_theme(app):
    _set_look("neon")
    c = client(app)
    assert c.get("/setup/api/state").json()["appearance"]["theme"] == "console"
    assert c.get("/setup/api/settings/general").json()["values"]["appearance.theme"] == "console"
    assert c.get("/api/info").json()["look"] == "console" and "data-look=console>" in c.get("/setup").text


def test_state_follows_a_save(app):
    assert post(client(app), "settings/general", {"values": {"appearance.theme": "workbench"}}).status_code == 200
    assert client(app).get("/setup/api/state").json()["appearance"]["theme"] == "workbench"


@pytest.mark.parametrize("stored", ["neon", "", 5, ["panes"]])
def test_web_app_falls_back_to_console_for_an_unknown_stored_theme(stored):
    cfg = config.load()
    cfg["appearance"] = {"theme": stored}
    config.save(cfg)
    light, dark = _surfaces("console")
    with _web_client() as c:
        text = c.get("/intake").text
        assert text.startswith("<!doctype html><html lang=en data-look=console>")
        assert _metas(text) == [(light, "(prefers-color-scheme: light)"), (dark, "(prefers-color-scheme: dark)")]
        assert c.get("/intake/manifest-light.webmanifest").json()["theme_color"] == light
        assert c.get("/intake/manifest-dark.webmanifest").json()["theme_color"] == dark


def test_a_device_that_has_chosen_keeps_its_choice():
    """Static: the head script (not driven in a browser) reads `spoolwarden.look` from localStorage and sets `data-look`
    from it, so it wins over the Hub's default in the served `<html>`; both shells load it before any stylesheet."""
    root = Path(__file__).resolve().parents[1] / "filament_kit"
    js = (root / "shared_static" / "theme-init.js").read_text(encoding="utf-8")
    assert 'getItem("spoolwarden.look")' in js and 'r.setAttribute("data-look", l)' in js
    assert js.index("setAttribute(\"data-look\"") > js.index("indexOf(l) >= 0")      # only a known look is applied
    for path in ("setup_page.py", "web/intake_app.py"):
        src = (root / path).read_text(encoding="utf-8")
        assert src.index("theme-init.js") < src.index("/tokens.css")


def test_a_chosen_look_reaches_the_page_only_through_the_script(app):
    _set_look("panes")
    text = client(app).get("/setup").text
    assert "data-look=panes>" in text and text.index("theme-init.js") < text.index("tokens.css")
