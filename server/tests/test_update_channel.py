"""`filament-kit update --channel nightly|stable` and the Updates tab's "Follow nightly builds" switch: the newest
nightly prerelease (unsigned, checked against its own SHA256SUMS only, and said so), never a rollback target;
the stable channel replaces a nightly with the latest signed release."""
from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from filament_kit import cli, config, nightly, release, setup_helper, updates
from test_release import make_tarball
from test_updates import Runner, Servers, _cfg, _state, env, key, srv  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[2]


class Nightlies:
    """GitHub's release list on 127.0.0.1: nightly prereleases {date: version}, plus anything in `extra_docs`."""

    def __init__(self):
        self.docs, self.files, self.extra_docs = [], {}, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                base = f"http://127.0.0.1:{self.server.server_address[1]}"
                if self.path.endswith("/releases?per_page=30"):
                    docs = [{**d, "assets": [{"name": n, "url": f"{base}/dl/{n}"} for n in d["assets"]]}
                            for d in outer.docs + outer.extra_docs]
                    return self._send(200, json.dumps(docs).encode())
                if self.path.startswith("/dl/") and self.path[4:] in outer.files:
                    return self._send(200, outer.files[self.path[4:]])
                return self._send(404, b"{}")

            def _send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.api = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def add(self, base, date, *, tamper=False, prerelease=True):
        version = f"{base}-nightly.{date}"
        name = f"filament-kit-{version}.tar.gz"
        tar = make_tarball(version)
        sums = f"{hashlib.sha256(tar).hexdigest()}  {name}\n".encode()
        if tamper:
            tar = tar[:-1] + bytes([tar[-1] ^ 1])
        self.files[name], self.files[f"SUMS-{date}"] = tar, sums
        self.docs.append({"tag_name": f"nightly-{date}", "prerelease": prerelease, "body": f"Nightly {date}",
                          "assets": [name, "SHA256SUMS"]})
        self.files["SHA256SUMS"] = sums      # the list serves one SHA256SUMS name: the newest added wins
        return version

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def nights():
    n = Nightlies()
    yield n
    n.close()


def _fetcher(srv, nights):
    stable = srv.fetcher()

    class F(release.Fetcher):
        def release(self, repo=release.REPO, version=None):
            return stable.release(repo, version)
    return F(nights.api)


def _nightly_cfg(env, channel="nightly"):
    return _cfg(env, updates={"channel": channel})


# ---------------------------------------------------------------- choosing the nightly

def test_the_newest_nightly_prerelease_is_chosen(nights):
    nights.add("1.0.0", "20261108")
    nights.add("1.0.0", "20261110")
    nights.add("1.0.0", "20261109")
    nights.extra_docs = [{"tag_name": "v9.9.9", "prerelease": False, "assets": []},          # a release
                         {"tag_name": "nightly-20991231", "prerelease": False, "assets": []},  # not a prerelease
                         {"tag_name": "nightly-20991230", "prerelease": True, "assets": ["SHA256SUMS"]}]  # no tarball
    rel = nightly.latest_nightly(release.Fetcher(nights.api), "o/r")
    assert rel["version"] == "1.0.0-nightly.20261110" and rel["notes"] == "Nightly 20261110"


def test_no_nightly_is_an_error(nights):
    with pytest.raises(release.ReleaseError, match="no nightly prerelease"):
        nightly.latest_nightly(release.Fetcher(nights.api), "o/r")


def test_versions_order_by_number_then_date():
    k = nightly.nightly_key
    assert k("1.0.0") < k("1.0.0-nightly.20261109") < k("1.0.0-nightly.20261110") < k("1.0.1")
    assert k("1.0.1-nightly.20261101") > k("1.0.0-nightly.20261231")


# ---------------------------------------------------------------- installing one

def test_the_nightly_channel_installs_the_newest_nightly_and_says_it_is_unsigned(env, srv, nights, capsys):
    srv.add("1.0.0")
    v = nights.add("1.0.0", "20261110")
    run = Runner()
    assert updates.update(_nightly_cfg(env), fetcher=_fetcher(srv, nights), run=run, now=1000.0) == 0
    assert run.installed == [f"filament-kit-{v}"]
    out = capsys.readouterr().out
    assert "unsigned" in out and "proves nothing about who built it" in out and f"-> {v} (nightly)" in out
    st = _state(env)
    assert st["previous"] == "1.0.0" and st["failed"] is None        # the signed release stays the rollback target
    assert sorted(p.name for p in (env / "opt/releases").iterdir() if p.is_dir()) == ["1.0.0", v]


def test_a_nightly_that_does_not_match_its_checksum_is_not_installed(env, srv, nights, capsys):
    srv.add("1.0.0")
    nights.add("1.0.0", "20261110", tamper=True)
    run = Runner()
    assert updates.update(_nightly_cfg(env), fetcher=_fetcher(srv, nights), run=run) == 1
    assert run.installed == [] and "does not match its hash in the nightly's (unsigned) SHA256SUMS" in \
        capsys.readouterr().err


def test_on_a_nightly_an_older_or_same_nightly_is_up_to_date(env, srv, nights, monkeypatch, capsys):
    srv.add("1.0.0")
    nights.add("1.0.0", "20261110")
    monkeypatch.setattr(updates, "version_text", lambda: "1.0.0-nightly.20261110")
    run = Runner()
    assert updates.update(_nightly_cfg(env), fetcher=_fetcher(srv, nights), run=run, scheduled=False) == 0
    assert run.installed == [] and "up to date with the nightly channel" in capsys.readouterr().out


def test_a_nightly_after_a_nightly_keeps_the_signed_release_as_the_rollback(env, srv, nights, monkeypatch):
    srv.add("1.0.0")
    run = Runner()
    nights.add("1.0.0", "20261109")
    assert updates.update(_nightly_cfg(env), fetcher=_fetcher(srv, nights), run=run) == 0
    monkeypatch.setattr(updates, "version_text", lambda: "1.0.0-nightly.20261109")
    v2 = nights.add("1.0.0", "20261110")
    assert updates.update(_nightly_cfg(env), fetcher=_fetcher(srv, nights), run=run) == 0
    assert run.installed[-1] == f"filament-kit-{v2}"
    st = _state(env)
    assert st["previous"] == "1.0.0"                                 # never a nightly
    assert sorted(p.name for p in (env / "opt/releases").iterdir() if p.is_dir()) == ["1.0.0", v2]


# ---------------------------------------------------------------- back to stable

def test_the_stable_channel_replaces_a_nightly_with_the_latest_release(env, srv, nights, monkeypatch, capsys):
    srv.add("1.0.0")
    monkeypatch.setattr(updates, "version_text", lambda: "1.0.0-nightly.20261110")
    run = Runner()
    assert updates.update(_nightly_cfg(env, "stable"), fetcher=_fetcher(srv, nights), run=run) == 0
    assert run.installed == ["filament-kit-1.0.0"]
    assert "updated filament-kit 1.0.0-nightly.20261110 -> 1.0.0" in capsys.readouterr().out


def test_the_stable_channel_on_a_release_is_as_before(env, srv, nights, capsys):
    srv.add("1.0.0")
    run = Runner()
    assert updates.update(_nightly_cfg(env, "stable"), fetcher=_fetcher(srv, nights), run=run) == 0
    assert run.installed == [] and "up to date" in capsys.readouterr().out


def test_set_channel_saves_it_says_so_and_updates(env, srv, nights, monkeypatch, capsys):
    srv.add("1.0.0")
    nights.add("1.0.0", "20261110")
    monkeypatch.setattr(updates, "_require_root", lambda: True)
    calls = []
    monkeypatch.setattr(updates, "update", lambda cfg, **kw: calls.append(cfg["updates"]["channel"]) or 0)
    assert updates.set_channel(_cfg(env), "nightly") == 0
    assert config.load()["updates"]["channel"] == "nightly" and calls == ["nightly"]
    out = capsys.readouterr().out
    assert "update channel: stable -> nightly" in out and "unsigned" in out
    assert updates.set_channel(config.load(), "stable") == 0 and config.load()["updates"]["channel"] == "stable"


def test_set_channel_needs_root(env, monkeypatch):
    monkeypatch.setattr(updates, "_require_root", lambda: False)
    assert updates.set_channel(_cfg(env), "nightly") == 1
    assert (config.load().get("updates") or {}).get("channel") in (None, "stable")


def test_a_bad_channel_in_config_is_refused(env):
    with pytest.raises(release.ReleaseError, match="updates.channel"):
        updates.settings({"updates": {"channel": "beta"}})


# ---------------------------------------------------------------- the CLI and the setup page

def test_the_cli_routes_channel(monkeypatch):
    got = []
    monkeypatch.setattr(updates, "set_channel", lambda cfg, ch: got.append(ch) or 0)
    assert cli.main(["update", "--channel", "nightly"]) == 0 and got == ["nightly"]
    with pytest.raises(SystemExit):
        cli.main(["update", "--channel", "nightly", "--rollback"])


def test_the_switch_is_two_jobs_and_says_unsigned_before_it_runs():
    assert setup_helper.JOBS["channel_nightly"] == ("update", "--channel", "nightly")
    assert setup_helper.JOBS["channel_stable"] == ("update", "--channel", "stable")
    js = (ROOT / "server/filament_kit/setup_static/setup_tabs.js").read_text(encoding="utf-8")
    card = js.split("function nightlyCard(", 1)[1].split("\nfunction ", 1)[0]
    assert "Follow nightly builds" in card and '"channel_nightly"' in card and "NIGHTLY_ASK" in card
    assert "untested and unsigned" in js.split("const NIGHTLY_ASK", 1)[1].split(";", 1)[0]


def test_the_view_says_the_channel(env):
    v = updates.view(_cfg(env))
    assert v["channel"] == "stable" and v["installed_text"] == "1.0.0"
