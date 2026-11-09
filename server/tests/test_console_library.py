"""The filament library on the setup console's Settings tab."""
from __future__ import annotations

from pathlib import Path

import pytest
from test_setup_page import Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, library, setup_helper
from filament_kit.profiles import builds
from filament_kit.setup_console import library_tab

STATIC = Path(cli.__file__).parent / "setup_static"


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Mgr())


def _status(monkeypatch, **over):
    base = {"version": 4, "source": "update", "local": 2, "url": "https://example.org/library.tar.gz",
            "last_check": {"at": 1000.0, "ok": True, "error": None}, "skipped": None}
    monkeypatch.setattr(library, "status", lambda: {**base, **over})


def test_the_view_needs_no_code(app, monkeypatch):
    _status(monkeypatch)
    r = client(app).get("/setup/api/library").json()
    assert r["version"] == 4 and r["local"] == 2 and r["last_check"]["ok"] is True and r["last_check"]["at"]


def test_a_failed_checks_error_is_redacted(app, monkeypatch):
    _status(monkeypatch, last_check={"at": 1000.0, "ok": False,
                                     "error": "cannot read /var/lib/filament-kit/profiles/user/1234567890/x from 192.0.2.77"})
    r = client(app).get("/setup/api/library")
    assert "1234567890" not in r.text and "192.0.2.77" not in r.text
    assert r.json()["last_check"]["ok"] is False


def test_no_check_yet(app, monkeypatch):
    _status(monkeypatch, last_check=None)
    assert client(app).get("/setup/api/library").json()["last_check"] is None


@pytest.mark.parametrize("name,args", [("library_update", ["library", "update"]), ("library_rollback", ["library", "rollback"])])
def test_the_jobs_run_the_commands(name, args):
    assert list(setup_helper.JOBS[name]) == args and name in setup_helper.BUSY


def test_adding_needs_the_code(app, monkeypatch):
    monkeypatch.setattr(library, "add_local", lambda data: pytest.fail("must not run"))
    assert post(client(app), "library/add", {"entry": "{}"}, code=None).status_code in (401, 403)
    assert post(client(app), "library/add", {"entry": "{}"}, code="0000-0000").status_code in (401, 403)


def test_adding_goes_through_the_commands_check_and_asks_for_a_build(app, monkeypatch):
    seen, asked = [], []
    monkeypatch.setattr(library, "add_local", lambda data: seen.append(data) or ({"vendor": "V", "product": "P"}, "v--p"))
    monkeypatch.setattr(builds, "request_rebuild", lambda reason: asked.append(reason))
    r = post(client(app), "library/add", {"entry": '{"vendor": "V"}'})
    assert r.json() == {"ok": True, "vendor": "V", "product": "P", "line": "v--p"}
    assert seen == [b'{"vendor": "V"}'] and len(asked) == 1


def test_a_bad_entry_is_refused_with_its_reason_and_no_build(app, monkeypatch):
    def bad(data):
        raise ValueError("no vendor")
    monkeypatch.setattr(library, "add_local", bad)
    monkeypatch.setattr(builds, "request_rebuild", lambda reason: pytest.fail("no build"))
    r = post(client(app), "library/add", {"entry": "{}"})
    assert r.status_code == 400 and "no vendor" in r.json()["error"]


@pytest.mark.parametrize("entry", [None, 5, "", "   "])
def test_an_empty_entry_is_refused(app, monkeypatch, entry):
    monkeypatch.setattr(library, "add_local", lambda data: pytest.fail("must not run"))
    assert post(client(app), "library/add", {"entry": entry}).status_code == 400


def test_the_settings_tab_has_the_card():
    src = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert "libraryCard()" in src
    tabs = (STATIC / "setup_tabs.js").read_text(encoding="utf-8")
    assert "function libraryCard(" in tabs and '"library_update"' in tabs and '"library_rollback"' in tabs
    assert library_tab.routes
