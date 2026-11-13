"""The Hub's setup names beside the old words, `--hub` beside `--server`, the feature titles (design S2.11, N27)."""
from __future__ import annotations

import io
import sys

import pytest
from test_console_core import Manager  # noqa: F401
from test_setup_page import client, env, make, post, Helper  # noqa: F401

from filament_kit import apply, cli, config, modules

NAMES = {"hub": "server", "weigh-station": "station", "hub-with-weigh-station": "all-in-one"}

TITLES = {
    "spoolman": "Spoolman", "server": "Hub service", "ai_intake": "Label Reader: Cloud (Claude)",
    "local_intake": "Label Reader: On this Hub", "printers": "Bambu Lab printers", "klipper": "Klipper printers",
    "presets": "Slicer presets", "library": "Filament Catalog", "backup": "Nightly backup",
    "station": "Weigh Station", "web": "Web access", "remote": "Remote access", "orders": "Order history",
    "updates": "Automatic updates",
}


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Manager())


@pytest.fixture
def applied(tmp_path, monkeypatch):
    for k, d in (("FK_ETC", "etc"), ("FK_STATE", "state"), ("FK_BACKUPS", "bk"), ("FK_OPT", "opt")):
        monkeypatch.setenv(k, str(tmp_path / d))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    (tmp_path / "etc").mkdir()
    (tmp_path / "state").mkdir()
    s = io.StringIO("")
    s.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", s)
    monkeypatch.setattr(cli, "_require_root", lambda: True)
    calls = []
    monkeypatch.setattr(apply, "plan", lambda cfg, **kw: calls.append(cfg) or [])
    monkeypatch.setattr(apply, "execute", lambda actions, **kw: None)
    monkeypatch.setattr(apply, "finish", lambda cfg, **kw: None)
    return calls


@pytest.mark.parametrize("new,old", NAMES.items())
def test_a_new_setup_name_selects_the_old_setup(new, old):
    assert modules.canonical_mode(new) == old and modules.canonical_mode(old) == old
    assert modules.set_mode({}, new, say=None) == modules.set_mode({}, old, say=None)
    assert modules.preset(frozenset(), new) == modules.preset(frozenset(), old)
    assert modules.mode_of(modules.MODES[old]) == old            # what is stored/reported stays the old word


def test_an_unknown_setup_is_still_refused():
    with pytest.raises(modules.ModuleError):
        modules.set_mode({}, "nope", say=None)


@pytest.mark.parametrize("new,old", NAMES.items())
def test_modules_set_takes_the_new_names(new, old, applied):
    assert cli.main(["modules", "set", new, "--hub", "192.0.2.10"] if old == "station" else ["modules", "set", new]) == 0
    got = config.load()
    assert modules.mode_of(modules.enabled(got)) == old
    assert (got["station"].get("allow") == ["192.0.2.10"]) == (old == "station")


def test_hub_and_server_options_give_the_same_result(applied):
    assert cli.main(["modules", "set", "station", "--server", "192.0.2.10"]) == 0
    a = config.load()
    assert cli.main(["modules", "set", "weigh-station", "--hub", "192.0.2.10"]) == 0
    assert config.load() == a


def test_hub_option_on_enable_is_the_server_option(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_modules_toggle", lambda name, on, server=None: seen.append(server) or 0)
    assert cli.main(["modules", "enable", "station", "--hub", "h"]) == 0
    assert cli.main(["modules", "enable", "station", "--server", "h"]) == 0
    assert seen == ["h", "h"]


@pytest.mark.parametrize("new,old", NAMES.items())
def test_the_page_takes_the_new_names(new, old, app, env):  # noqa: F811
    c = client(app)
    if old == "station":
        assert post(c, "modules/mode", {"mode": new}).status_code == 409
        assert c.get(f"/setup/api/modules/preview?mode={new}").json()["refused"]
    else:
        p = c.get(f"/setup/api/modules/preview?mode={new}").json()
        assert p == c.get(f"/setup/api/modules/preview?mode={old}").json()


def test_feature_titles_are_the_names_of_the_hub_page_design():
    assert {n: m.title for n, m in modules.MODULES.items()} == TITLES
