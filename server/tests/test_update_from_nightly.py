"""Nightly builds were dropped (2026-11-12). What stays: a kit that installed one shows it, and its next update puts
the latest signed release in its place, even an older one. Nothing offers, fetches or installs a nightly any more."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from filament_kit import cli, setup_helper, updates
from test_updates import Runner, Servers, _cfg, _state, env, key, srv  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- the version a nightly kit shows

def test_version_text_is_the_version_on_a_stable_kit(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_OPT", str(tmp_path))
    monkeypatch.setattr(updates, "current_version", lambda: "1.2.3")
    assert updates.version_text() == "1.2.3" and not updates.on_nightly()


@pytest.mark.parametrize("content,shown", [
    ("1.2.3-nightly.20261109\n", "1.2.3-nightly.20261109"),
    ("1.2.2-nightly.20261109\n", "1.2.3"),      # left by another version
    ("<script>\n", "1.2.3"),
    ("", "1.2.3"),
])
def test_version_text_on_a_nightly_kit(tmp_path, monkeypatch, content, shown):
    (tmp_path / "resources").mkdir()
    (tmp_path / "resources" / "NIGHTLY").write_text(content)
    monkeypatch.setenv("FK_OPT", str(tmp_path))
    monkeypatch.setattr(updates, "current_version", lambda: "1.2.3")
    assert updates.version_text() == shown


# ---------------------------------------------------------------- back to signed releases

def test_a_nightly_is_replaced_by_the_latest_release(env, srv, monkeypatch, capsys):
    srv.add("1.0.0")
    monkeypatch.setattr(updates, "version_text", lambda: "1.0.0-nightly.20261110")
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 0
    assert run.installed == ["filament-kit-1.0.0"]
    assert "updated filament-kit 1.0.0-nightly.20261110 -> 1.0.0" in capsys.readouterr().out


def test_a_newer_nightly_is_replaced_by_the_older_release(env, srv, monkeypatch, capsys):
    """R77 review: an unsigned nightly never stays because the newest release is older."""
    srv.add("1.0.0")
    monkeypatch.setattr(updates, "current_version", lambda: "1.1.0")
    monkeypatch.setattr(updates, "version_text", lambda: "1.1.0-nightly.20261110")
    older = []
    real = updates._install_older
    monkeypatch.setattr(updates, "_install_older", lambda cfg, v, run: older.append(v) or real(cfg, v, run))
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 0
    assert run.installed == ["filament-kit-1.0.0"] and older == ["1.0.0"]
    assert "going back to the signed release 1.0.0 (older than this nightly's 1.1.0)" in capsys.readouterr().out


def test_a_release_on_a_release_is_up_to_date(env, srv, capsys):
    srv.add("1.0.0")
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 0
    assert run.installed == [] and "up to date" in capsys.readouterr().out


def test_a_nightly_kit_sees_the_release_as_newer(env, srv, monkeypatch):
    srv.add("1.0.0")
    monkeypatch.setattr(updates, "version_text", lambda: "1.0.0-nightly.20261110")
    assert updates.check_info(_cfg(env), fetcher=srv.fetcher())["newer"] is True


# ---------------------------------------------------------------- nothing nightly is left to choose

def test_a_nightly_channel_left_in_config_is_ignored(env, srv, capsys):
    """A kit that followed nightlies keeps updates.channel in its config: it is not refused, it updates on releases."""
    srv.add("1.0.0")
    run = Runner()
    assert updates.update(_cfg(env, updates={"channel": "nightly"}), fetcher=srv.fetcher(), run=run) == 0
    assert "up to date" in capsys.readouterr().out
    assert "channel" not in updates.view(_cfg(env, updates={"channel": "nightly"}))


def test_there_is_no_channel_option_job_or_switch():
    with pytest.raises(SystemExit):
        cli.main(["update", "--channel", "nightly"])
    assert not any("channel" in j for j in setup_helper.JOBS)
    js = (ROOT / "server/filament_kit/setup_static/setup_tabs.js").read_text(encoding="utf-8")
    assert "nightly" not in js.lower()
    assert not (ROOT / ".github/workflows/nightly.yml").exists()
    assert not (ROOT / "server/filament_kit/nightly.py").exists()
    rel = (ROOT / "tools/make_release.sh").read_text(encoding="utf-8")
    assert "FK_NIGHTLY" not in rel and "NIGHTLY" not in (ROOT / "install/install.sh").read_text(encoding="utf-8")
    assert "nightly" not in (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8").lower()
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        assert "nightly" not in wf.read_text(encoding="utf-8").lower(), wf.name


def test_the_page_shows_version_text_and_still_compares_the_version():
    """r.version decides whether the page reloads for a new release: it must stay what S.version is."""
    js = (ROOT / "server/filament_kit/setup_static/setup_tabs.js").read_text(encoding="utf-8")
    jobs = (ROOT / "web-shared/components-jobs.js").read_text(encoding="utf-8")   # the job strip reloads on a new release
    assert "${r.version_text || r.version}" in js and "version: () => (S ? S.version : null)" in js
    assert "r.version !== o.version()" in jobs and "version_text" not in jobs
