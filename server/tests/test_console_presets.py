"""The setup console's Presets tab: `filament-kit profiles` on the page, with the same add-or-accept-only rule."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_setup_page import CODE, H, Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, config, modules
from filament_kit.profiles import builds
from filament_kit.profiles import lines as lines_mod

STATIC = Path(cli.__file__).parent / "setup_static"


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Mgr())


LINE = lines_mod.line_id_for("V", "P")
CHOSEN = [{"line_id": "l1", "target": "bambu", "name": "P @BBL", "file": "C:/Users/someone/p.json", "keys": ["a", "b"]},
          {"line_id": "l2", "target": "orca", "name": "Q", "keys": ["c"]}]


def _line():
    return lines_mod.Line(LINE, "V", "P", "PLA", None, "none", "P0000001", "2026-11-09T00:00:00Z")


def test_the_view_says_when_the_module_is_off(app):
    cfg = config.load()
    cfg["modules"]["presets"] = False
    config.save(cfg)
    r = client(app).get("/setup/api/presets")
    assert r.status_code == 200 and r.json() == {"on": False}
    assert post(client(app), "presets/build").status_code == 409


def test_the_view_needs_no_code_and_shows_no_device_id_or_file_names(app, monkeypatch):
    real = builds.status

    def status():
        st = real()
        st["pc"] = {"device_id": "secretdevice", "last_upload": None}
        return st
    monkeypatch.setattr(builds, "status", status)
    r = client(app).get("/setup/api/presets")
    assert r.status_code == 200
    body = r.json()
    assert body["on"] is True and "secretdevice" not in r.text and body["lines"] == []
    assert set(body["updates"]) == {"count", "lines", "accepted", "yours"}


def test_the_view_redacts_a_failed_builds_error(app, monkeypatch):
    real = builds.status
    raw = "FileNotFoundError: '/var/lib/filament-kit/profiles/user/1234567890/live.zip' from 192.0.2.77"

    def status():
        return {**real(), "last_attempt": {"at": 1000.0, "ok": False, "error": raw}}
    monkeypatch.setattr(builds, "status", status)
    r = client(app).get("/setup/api/presets")
    assert r.status_code == 200
    assert "1234567890" not in r.text and "192.0.2.77" not in r.text
    assert r.json()["last_attempt"]["error"].startswith("FileNotFoundError")


@pytest.mark.parametrize("path,body", [("presets/build", {}), ("presets/restore_deleted", {}),
                                       (f"presets/lines/{LINE}/parent", {"parent": "x"}),
                                       ("presets/updates", {"all": True})])
def test_every_change_needs_the_code(app, path, body):
    assert post(client(app), path, body, code=None).status_code in (401, 403)
    assert post(client(app), path, body, code="0000-0000").status_code in (401, 403)


def test_build_asks_for_a_build(app, monkeypatch):
    asked = []
    monkeypatch.setattr(builds, "request_rebuild", lambda reason: asked.append(reason))
    assert post(client(app), "presets/build").json() == {"ok": True}
    assert len(asked) == 1


def test_restore_deleted_sets_the_flag_and_asks_for_a_build(app, monkeypatch):
    seen = []
    monkeypatch.setattr(builds, "restore_deleted_next", lambda: seen.append("flag"))
    monkeypatch.setattr(builds, "request_rebuild", lambda reason: seen.append("build"))
    assert post(client(app), "presets/restore_deleted").status_code == 200
    assert seen == ["flag", "build"]


def test_a_dry_run_changes_nothing_and_lists_the_files(app, monkeypatch):
    calls = []

    def apply_updates(**kw):
        calls.append(kw)
        return {"stamp": "s1", "chosen": CHOSEN}
    monkeypatch.setattr(builds, "apply_updates", apply_updates)
    r = post(client(app), "presets/updates", {"all": True}).json()     # no dry_run named: still a dry run
    assert calls == [{"line_id": None, "all_": True, "dry_run": True}]
    assert r["dry_run"] is True and r["chosen"][0]["file"] == CHOSEN[0]["file"] and r["chosen"][1]["file"] is None


def test_accept_takes_a_plain_false_and_exactly_what_was_shown(app, monkeypatch):
    calls = []
    monkeypatch.setattr(builds, "apply_updates", lambda **k: calls.append(k) or {"stamp": "s", "chosen": CHOSEN[:1]})
    r = post(client(app), "presets/updates", {"all": True, "dry_run": False, "stamp": "s", "names": ["P @BBL"]})
    assert r.json()["dry_run"] is False
    assert calls == [{"line_id": None, "all_": True, "dry_run": False, "only": {"P @BBL"}, "expect_stamp": "s"}]


@pytest.mark.parametrize("extra", [{}, {"stamp": "s"}, {"names": ["a"]}, {"stamp": "s", "names": []},
                                   {"stamp": 5, "names": ["a"]}, {"stamp": "s", "names": [5]}, {"stamp": "s", "names": "a"}])
def test_accept_with_no_named_list_is_refused(app, monkeypatch, extra):
    monkeypatch.setattr(builds, "apply_updates", lambda **k: pytest.fail("must not run"))
    assert post(client(app), "presets/updates", {"all": True, "dry_run": False, **extra}).status_code == 400


def _pending(monkeypatch, tmp_path, stamp, names):
    """The real apply_updates over a build with these updates pending."""
    (tmp_path / "accepted").mkdir(exist_ok=True)
    items = [{"name": n, "line_id": "l1", "target": "bambu", "keys": ["a"], "accepted": False} for n in names]
    monkeypatch.setattr(builds, "_update_items", lambda: (stamp, items, []))
    saved = []
    monkeypatch.setattr(builds.updates_mod, "accepted", lambda d: {})
    monkeypatch.setattr(builds.updates_mod, "preset_hash", lambda p: "hash-of-" + p.stem)
    monkeypatch.setattr(builds.updates_mod, "save_accepted", lambda d, acc, w: saved.append(acc))
    return saved


def test_a_build_after_the_list_accepts_nothing(app, monkeypatch, tmp_path):
    saved = _pending(monkeypatch, tmp_path, "newer", ["A", "B", "UNSEEN"])
    r = post(client(app), "presets/updates", {"all": True, "dry_run": False, "stamp": "older", "names": ["A", "B"]})
    assert r.status_code == 409 and "show them again" in r.json()["error"]
    assert saved == []


def test_an_update_nobody_was_shown_is_not_accepted(app, monkeypatch, tmp_path):
    saved = _pending(monkeypatch, tmp_path, "same", ["A", "UNSEEN"])
    r = post(client(app), "presets/updates", {"all": True, "dry_run": False, "stamp": "same", "names": ["A"]})
    assert [u["name"] for u in r.json()["chosen"]] == ["A"]
    assert len(saved) == 1 and "UNSEEN" not in str(saved[0]) and "A" in str(saved[0])


@pytest.mark.parametrize("body", [{}, {"line": "l1", "all": True}, {"line": 5}, {"line": "../x"}, {"all": "yes"}])
def test_updates_takes_one_line_or_all(app, monkeypatch, body):
    monkeypatch.setattr(builds, "apply_updates", lambda **k: pytest.fail("must not run"))
    assert post(client(app), "presets/updates", body).status_code == 400


def test_an_odd_dry_run_value_is_a_dry_run(app, monkeypatch):
    calls = []
    monkeypatch.setattr(builds, "apply_updates", lambda **k: calls.append(k) or {"stamp": "s", "chosen": []})
    post(client(app), "presets/updates", {"all": True, "dry_run": 0})
    assert calls[0]["dry_run"] is True


def test_set_parent_saves_through_the_commands_own_checks(app, monkeypatch):
    with lines_mod.transaction() as ls:
        ls[LINE] = _line()
    asked = []
    monkeypatch.setattr(builds, "request_rebuild", lambda reason: asked.append(reason))
    r = post(client(app), f"presets/lines/{LINE}/parent", {"parent": "Generic PLA", "target": "bambu"})
    assert r.status_code == 200 and r.json()["parent"] == "Generic PLA"
    assert lines_mod.load()[LINE].bambu_parent == "Generic PLA" and asked
    assert client(app).get("/setup/api/presets").json()["lines"][0]["bambu_parent"] == "Generic PLA"


@pytest.mark.parametrize("path,body,status", [("presets/lines/nope/parent", {"parent": "x"}, 404),
                                              (f"presets/lines/{LINE}/parent", {"parent": ""}, 400),
                                              (f"presets/lines/{LINE}/parent", {"parent": 5}, 400),
                                              (f"presets/lines/{LINE}/parent", {"parent": "x", "target": "other"}, 400)])
def test_set_parent_refuses(app, path, body, status):
    with lines_mod.transaction() as ls:
        ls[LINE] = _line()
    assert post(client(app), path, body).status_code == status


def test_parents_with_no_sync_yet(app):
    assert client(app).get("/setup/api/presets/parents?material=PLA").json() == {"parents": [], "synced": False}
    assert client(app).get("/setup/api/presets/parents?material=PLA&target=orca").json() == {"parents": [], "synced": False}
    assert client(app).get("/setup/api/presets/parents?target=other").status_code == 400


def test_the_page_loads_the_tab_and_writes_no_html():
    assert modules.MODULES["presets"]
    src = (STATIC / "setup_presets.js").read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|fetch\(", src)
    assert 'presets: ["nav_slicer_presets", "presets", () => [presetsTab]]' in (STATIC / "setup.js").read_text(encoding="utf-8")
    # a null in replaceChildren prints the word: this file uses fill for anything that may be null
    assert "replaceChildren(null" not in src


def test_the_page_serves_the_script(app):
    c = client(app)
    assert "/setup/setup_presets.js" in c.get("/setup").text
    assert c.get("/setup/setup_presets.js").status_code == 200
    assert CODE and H
