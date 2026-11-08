"""The updater (module `updates`, `filament-kit update`) against a local fake release server."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from filament_kit import apply, cli, config, modules, release, updates
from test_release import FakeRelease

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def key(monkeypatch):
    priv = ed25519.Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(release, "PUBKEY", base64.b64encode(raw).decode())
    return priv


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(updates, "current_version", lambda: "1.0.0")
    return tmp_path


class Servers:
    """Fake releases by version; `latest` picks which one /releases/latest answers."""

    def __init__(self, key):
        self.key, self.by_ver, self.latest = key, {}, None

    def add(self, version, **kw):
        self.by_ver[version] = FakeRelease(self.key, version, **kw)
        self.latest = version
        return self.by_ver[version]

    def fetcher(self):
        outer = self

        class F(release.Fetcher):
            def release(self, repo=release.REPO, version=None):
                fr = outer.by_ver.get(version or outer.latest)
                if fr is None:
                    raise release.ReleaseError("HTTP 404: no such release")
                return release.Fetcher(fr.api).release("o/r", version)

            def get(self, url, limit, accept="application/octet-stream"):
                return release.Fetcher("http://127.0.0.1").get(url, limit, accept)

            def save(self, url, dest, limit):
                return release.Fetcher("http://127.0.0.1").save(url, dest, limit)
        return F("http://127.0.0.1")

    def close(self):
        for fr in self.by_ver.values():
            fr.close()


@pytest.fixture
def srv(key):
    s = Servers(key)
    yield s
    s.close()


def _cfg(env, on=("spoolman", "server", "updates"), **extra):
    cfg = config.load()
    cfg["modules"] = {n: n in on for n in modules.MODULES}
    cfg.update(extra)
    config.save(cfg)
    return config.load()


class Runner:
    """Records commands. `rc`: install.sh's exit code, or {version folder: exit code or an exception to raise
    or a callable to call}."""

    def __init__(self, rc=0):
        self.cmds, self.rc = [], rc
        self.installed = []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        if cmd[0] == "bash":
            assert Path(cmd[1]).name == "install.sh" and Path(cmd[1]).is_file()
            folder = Path(cmd[1]).parent.name
            self.installed.append(folder)
            out = self.rc.get(folder, 0) if isinstance(self.rc, dict) else self.rc
            if isinstance(out, BaseException):
                raise out
            if callable(out):
                return out()
            return out
        return 0


def _state(env) -> dict:
    return json.loads((env / "opt" / "releases" / "state.json").read_text())


# ---------------------------------------------------------------- registration

def test_updates_module_is_opt_in_with_its_timer():
    m = modules.MODULES["updates"]
    assert m.units == ("filament-kit-update.timer",) and m.depends == ()
    assert "updates" in modules.OPT_IN
    assert all("updates" not in members for members in modules.MODES.values())


def test_plan_installs_and_enables_the_timer_only_when_on():
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "server")
    acts = apply.plan(cfg)
    assert ("disable", "filament-kit-update.timer") in [(a.kind, a.arg) for a in acts]
    cfg["modules"]["updates"] = True
    acts = apply.plan(cfg)
    pairs = [(a.kind, a.arg) for a in acts]
    assert ("install_unit", "filament-kit-update.timer") in pairs
    assert ("install_unit", "filament-kit-update.service") in pairs
    assert ("enable", "filament-kit-update.timer") in pairs


def test_unit_files_ship():
    svc = (ROOT / "install/systemd/filament-kit-update.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/filament-kit/venv/bin/filament-kit update --scheduled" in svc
    assert "User=" not in svc            # root: it runs install.sh
    timer = (ROOT / "install/systemd/filament-kit-update.timer").read_text(encoding="utf-8")
    assert "OnCalendar=daily" in timer


def test_release_workflow_signs_sums_with_the_secret():
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "FK_RELEASE_KEY: ${{ secrets.FK_RELEASE_KEY }}" in text
    assert "python tools/sign_release.py sign dist/SHA256SUMS" in text
    for f in ("dist/get.sh", "dist/SHA256SUMS", "dist/SHA256SUMS.sig"):
        assert f in text
    assert "echo \"$FK_RELEASE_KEY" not in text and "set -x" not in text


# ---------------------------------------------------------------- check

def test_check_says_newer(env, srv, key, capsys):
    srv.add("1.1.0")
    assert updates.check(_cfg(env), fetcher=srv.fetcher()) == 0
    assert "1.1.0 is available" in capsys.readouterr().out


def test_check_up_to_date(env, srv, key, capsys):
    srv.add("1.0.0")
    assert updates.check(_cfg(env), fetcher=srv.fetcher()) == 0
    assert "up to date" in capsys.readouterr().out


# ---------------------------------------------------------------- update

def test_update_installs_and_keeps_the_previous(env, srv, key, capsys):
    srv.add("1.0.0")
    srv.add("1.1.0")
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run, now=1000.0) == 0
    assert run.installed == ["filament-kit-1.1.0"]
    st = _state(env)
    assert st["previous"] == "1.0.0" and st["held"] is None and st["last_ok_at"] == 1000.0
    kept = sorted(p.name for p in (env / "opt/releases").iterdir() if p.is_dir())
    assert kept == ["1.0.0", "1.1.0"]
    assert "updated filament-kit 1.0.0 -> 1.1.0" in capsys.readouterr().out


def test_update_stops_the_services_when_systemd(env, srv, key, monkeypatch):
    srv.add("1.0.0")
    srv.add("1.1.0")
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(updates, "_require_root", lambda: True)
    run = Runner()
    assert updates.update(_cfg(env, on=("spoolman", "server", "web", "updates")), fetcher=srv.fetcher(),
                          run=run) == 0
    # timers and the setup page's helper socket first (M6: nothing starts an apply mid-update)
    assert run.cmds[0] == ["systemctl", "stop", "filament-kit-setup.socket", "filament-kit-update.timer"]
    assert run.cmds[1] == ["systemctl", "stop", "spoolman.service", "filament-kit.service",
                           "filament-kit-web.service"]
    assert run.cmds[2][0] == "bash" and len(run.cmds) == 3   # install.sh's modules apply starts them again


START = [["systemctl", "start", "spoolman.service", "filament-kit.service"],
         ["systemctl", "start", "filament-kit-setup.socket", "filament-kit-build.path",
          "filament-kit-update.timer"]]


@pytest.fixture
def systemd(monkeypatch):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(updates, "_require_root", lambda: True)


def _on():
    return ("spoolman", "server", "presets", "updates")


def test_failed_install_without_a_kept_copy_starts_the_units_again(env, srv, key, systemd, capsys):
    srv.add("1.1.0")
    run = Runner(rc=3)
    assert updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run) == 1
    assert run.cmds[-2:] == START
    assert "previous" not in updates._read_state() and updates._read_state()["failed"] == "1.1.0"
    assert "--version 1.0.0" in capsys.readouterr().err


def test_install_failing_halfway_reinstalls_the_running_version(env, srv, key, systemd, capsys):
    srv.add("1.0.0")
    srv.add("1.1.0")
    updates._write_state(previous="0.9.0")
    run = Runner(rc={"filament-kit-1.1.0": 7})
    assert updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run, now=50.0) == 1
    assert run.installed == ["filament-kit-1.1.0", "filament-kit-1.0.0"]
    # the failed attempt started the units again before the reinstall stopped them once more
    i = run.cmds.index(["bash", run.cmds[2][1]])
    assert run.cmds[i + 1:i + 3] == START
    st = updates._read_state()
    assert st["failed"] == "1.1.0" and st["previous"] == "0.9.0"      # 1.0.0 runs again: previous as it was
    assert "1.0.0 is back in place" in capsys.readouterr().err


def test_previous_is_recorded_before_the_install(env, srv, key):
    srv.add("1.0.0")
    srv.add("1.1.0")
    seen = []
    run = Runner(rc={"filament-kit-1.1.0": lambda: seen.append(updates._read_state().get("previous")) or 0})
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 0
    assert seen == ["1.0.0"]


def test_both_failing_keeps_previous_and_says_how_to_roll_back(env, srv, key, systemd, monkeypatch, capsys):
    srv.add("1.0.0")
    srv.add("1.1.0")
    cfg = _cfg(env, on=_on())
    run = Runner(rc=9)
    assert updates.update(cfg, fetcher=srv.fetcher(), run=run) == 1
    assert run.installed == ["filament-kit-1.1.0", "filament-kit-1.0.0"]
    assert run.cmds[-2:] == START
    assert updates._read_state()["previous"] == "1.0.0"
    assert "sudo filament-kit update --rollback" in capsys.readouterr().err
    # the rollback afterwards works (this process may still report the old version after a half-done install)
    run = Runner()
    assert updates.rollback(cfg, run=run) == 0
    assert run.installed == ["filament-kit-1.0.0"]


def test_failed_version_is_not_retried_daily(env, srv, key):
    srv.add("1.0.0")
    srv.add("1.1.0")
    cfg = _cfg(env)
    run = Runner(rc={"filament-kit-1.1.0": 1})
    assert updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=0.0) == 1
    run = Runner()
    for day in (1, 2, 3):
        assert updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=day * 86400.0) == 0
    assert run.cmds == []
    # a newer release is tried, and clears the mark
    srv.add("1.2.0")
    assert updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=4 * 86400.0) == 0
    assert run.installed == ["filament-kit-1.2.0"] and updates._read_state()["failed"] is None


def test_manual_update_retries_a_failed_version(env, srv, key):
    srv.add("1.0.0")
    srv.add("1.1.0")
    cfg = _cfg(env)
    assert updates.update(cfg, fetcher=srv.fetcher(), run=Runner(rc={"filament-kit-1.1.0": 1})) == 1
    run = Runner()
    assert updates.update(cfg, fetcher=srv.fetcher(), run=run) == 0
    assert run.installed == ["filament-kit-1.1.0"] and updates._read_state()["failed"] is None


def test_run_raising_oserror_starts_the_units_again(env, srv, key, systemd):
    srv.add("1.1.0")
    run = Runner(rc=OSError("bash missing"))
    assert updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run) == 1
    assert run.cmds[-2:] == START


def test_unexpected_exception_still_starts_the_units_again(env, srv, key, systemd):
    srv.add("1.1.0")
    run = Runner(rc=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run)
    assert run.cmds[-2:] == START


def test_sigterm_during_install_starts_the_units_again(env, srv, key, systemd):
    import signal
    srv.add("1.1.0")
    before = signal.getsignal(signal.SIGTERM)

    def term():                         # what the kernel does: call the handler the updater installed
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler) and handler is not before
        handler(signal.SIGTERM, None)
        return 0
    run = Runner(rc=term)
    with pytest.raises(SystemExit) as e:
        updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run)
    assert e.value.code == 128 + signal.SIGTERM
    assert run.cmds[-2:] == START
    assert signal.getsignal(signal.SIGTERM) is before       # handler restored
    assert not (env / "opt/releases/.work").exists()


@pytest.mark.skipif(os.name != "posix", reason="a real SIGTERM to this process")
def test_real_sigterm_during_install(env, srv, key, systemd):
    import signal
    srv.add("1.1.0")
    run = Runner(rc=lambda: os.kill(os.getpid(), signal.SIGTERM) or 0)
    with pytest.raises(SystemExit):
        updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run)
    assert run.cmds[-2:] == START


def test_update_unit_starts_the_kit_when_the_run_did_not_succeed():
    svc = (ROOT / "install/systemd/filament-kit-update.service").read_text(encoding="utf-8")
    line = next(ln for ln in svc.splitlines() if ln.startswith("ExecStopPost="))
    assert '"$$SERVICE_RESULT" != success' in line and "--state=enabled" in line
    assert "systemctl start --no-block \"$$unit\"" in line and "/opt/filament-kit/venv" not in line


@pytest.mark.skipif(not hasattr(__import__("signal"), "SIGHUP"), reason="no SIGHUP on Windows")
def test_sighup_during_install_starts_the_units_again(env, srv, key, systemd):
    import signal
    srv.add("1.1.0")
    before = signal.getsignal(signal.SIGHUP)
    run = Runner(rc=lambda: os.kill(os.getpid(), signal.SIGHUP) or 0)
    with pytest.raises(SystemExit) as e:
        updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run)
    assert e.value.code == 128 + signal.SIGHUP
    assert run.cmds[-2:] == START and signal.getsignal(signal.SIGHUP) is before


def _term():
    import signal
    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
    return 0


@pytest.mark.parametrize("kill", ["sigterm", "exception"])
def test_killed_install_is_marked_failed_and_not_retried_by_the_timer(env, srv, key, kill):
    srv.add("1.0.0")
    srv.add("1.1.0")
    cfg = _cfg(env)
    run = Runner(rc={"filament-kit-1.1.0": _term if kill == "sigterm" else RuntimeError("boom")})
    with pytest.raises(SystemExit if kill == "sigterm" else RuntimeError):
        updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=100.0)
    st = updates._read_state()
    assert st["failed"] == "1.1.0" and st["last_ok_at"] == 100.0 and st["previous"] == "1.0.0"
    run = Runner()
    assert updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=100.0 + 86400) == 0
    assert run.cmds == []
    assert updates.rollback(cfg, run=run) == 0 and run.installed == ["filament-kit-1.0.0"]


def test_refused_unpack_keeps_previous_as_it_was(env, srv, key, systemd, monkeypatch, capsys):
    srv.add("1.0.0")
    srv.add("1.1.0")
    updates._write_state(previous="0.9.0")

    def refuse(tarball, version, dest):
        raise release.ReleaseError("the tarball holds an unexpected entry 'x'; nothing was installed")
    monkeypatch.setattr(release, "extract", refuse)
    run = Runner()
    assert updates.update(_cfg(env, on=_on()), fetcher=srv.fetcher(), run=run) == 1
    assert run.cmds == []                                   # nothing stopped, nothing run
    assert updates._read_state()["previous"] == "0.9.0"
    assert "unexpected entry" in capsys.readouterr().err


def test_up_to_date_does_nothing(env, srv, key):
    srv.add("1.0.0")
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run, now=5.0) == 0
    assert run.cmds == [] and _state(env)["last_ok_at"] == 5.0


@pytest.mark.parametrize("tamper", ["tamper_sig", "tamper_tar"])
def test_tampered_release_installs_nothing(env, srv, key, tamper, capsys):
    srv.add("1.1.0", **{tamper: True})
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 1
    assert run.cmds == []
    assert not (env / "opt/releases/1.1.0").exists()
    assert "nothing was installed" in capsys.readouterr().err


def test_no_rollback_copy_still_updates_with_a_warning(env, srv, key, capsys):
    srv.add("1.1.0")                     # the installed 1.0.0 is not on the server
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 0
    out, err = capsys.readouterr()
    assert "no verified copy of the installed 1.0.0" in err and "(no rollback copy)" in out
    assert _state(env)["previous"] is None


def test_scheduled_needs_the_module_and_a_due_check(env, srv, key, capsys):
    srv.add("1.1.0")
    run = Runner()
    assert updates.update(_cfg(env, on=("spoolman", "server")), scheduled=True, fetcher=srv.fetcher(),
                          run=run) == 0
    assert "module is off" in capsys.readouterr().out and run.cmds == []
    updates._write_state(last_ok_at=1000.0)
    cfg = _cfg(env)
    assert updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=1000.0 + 3600) == 0
    assert "not due" in capsys.readouterr().out and run.cmds == []
    assert updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=1000.0 + 21 * 3600) == 0
    assert run.installed == ["filament-kit-1.1.0"]


def test_weekly_schedule(env, srv, key):
    updates._write_state(last_ok_at=0.0)
    cfg = _cfg(env, updates={"schedule": "weekly"})
    assert not updates.due(cfg, 2 * 86400) and updates.due(cfg, 7 * 86400)
    with pytest.raises(release.ReleaseError):
        updates.settings({"updates": {"schedule": "hourly"}})


def test_not_installed_refuses(env, srv, key, capsys):
    assert updates.update(config.load(), fetcher=srv.fetcher(), run=Runner()) == 1
    assert "not installed" in capsys.readouterr().err


@pytest.mark.skipif(updates.fcntl is None, reason="flock: Linux only")
def test_busy_printer_skips(env, srv, key, capsys):
    import fcntl
    srv.add("1.1.0")
    d = env / "state" / "printers" / "SERIAL1"
    d.mkdir(parents=True)
    with open(d / "mapping.lock", "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH)         # a load's write phase
        run = Runner()
        assert updates.update(_cfg(env), scheduled=True, fetcher=srv.fetcher(), run=run) == 0
        assert run.cmds == [] and "SERIAL1 is mapping or loading" in capsys.readouterr().out
        assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 1
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 0


def test_busy_printer_refuses_via_the_guard(env, srv, key, monkeypatch, capsys):
    """Platform-independent: whatever printers_idle raises Busy for stops the install."""
    srv.add("1.1.0")

    def busy():
        raise updates.Busy("SERIAL2")
    monkeypatch.setattr(updates, "printers_idle", busy)
    run = Runner()
    assert updates.update(_cfg(env), fetcher=srv.fetcher(), run=run) == 1
    assert run.cmds == [] and "SERIAL2" in capsys.readouterr().err


# ---------------------------------------------------------------- rollback

def test_rollback_reinstalls_the_previous_and_holds_the_newer(env, srv, key, monkeypatch, capsys):
    srv.add("1.0.0")
    srv.add("1.1.0")
    cfg = _cfg(env)
    assert updates.update(cfg, fetcher=srv.fetcher(), run=Runner()) == 0
    monkeypatch.setattr(updates, "current_version", lambda: "1.1.0")
    run = Runner()
    assert updates.rollback(cfg, run=run) == 0
    assert run.installed == ["filament-kit-1.0.0"]
    assert _state(env)["held"] == "1.1.0" and _state(env)["previous"] is None
    # the timer leaves the rolled-back version alone; by hand it installs
    monkeypatch.setattr(updates, "current_version", lambda: "1.0.0")
    updates._write_state(last_ok_at=0.0)
    run = Runner()
    assert updates.update(cfg, scheduled=True, fetcher=srv.fetcher(), run=run, now=10 ** 6) == 0
    assert run.cmds == [] and "rolled back" in capsys.readouterr().out
    assert updates.update(cfg, fetcher=srv.fetcher(), run=run) == 0
    assert run.installed == ["filament-kit-1.1.0"] and _state(env)["held"] is None


def test_rollback_without_a_kept_version(env, key, capsys):
    assert updates.rollback(_cfg(env), run=Runner()) == 1
    assert "nothing to roll back to" in capsys.readouterr().err


def test_rollback_refuses_a_changed_copy(env, srv, key, monkeypatch, capsys):
    srv.add("1.0.0")
    srv.add("1.1.0")
    cfg = _cfg(env)
    assert updates.update(cfg, fetcher=srv.fetcher(), run=Runner()) == 0
    tar = env / "opt/releases/1.0.0/filament-kit-1.0.0.tar.gz"
    tar.write_bytes(tar.read_bytes() + b"x")
    monkeypatch.setattr(updates, "current_version", lambda: "1.1.0")
    run = Runner()
    assert updates.rollback(cfg, run=run) == 1 and run.cmds == []


# ---------------------------------------------------------------- cli

def test_cli_update_check(env, srv, key, monkeypatch, capsys):
    srv.add("1.2.0")
    _cfg(env)
    monkeypatch.setattr(updates, "default_fetcher", lambda cfg: srv.fetcher())
    assert cli.main(["update", "--check"]) == 0
    assert "1.2.0 is available" in capsys.readouterr().out


def test_cli_update_flags_are_exclusive(capsys):
    with pytest.raises(SystemExit):
        cli.main(["update", "--check", "--rollback"])


@pytest.mark.skipif(os.name != "posix", reason="runs the release's install.sh with bash")
def test_update_runs_the_real_install_sh(env, srv, key, capsys):
    srv.add("1.0.0")
    srv.add("1.1.0")
    assert updates.update(_cfg(env), fetcher=srv.fetcher()) == 0      # default_run: bash install.sh
    out = capsys.readouterr().out
    assert "installed" in out or "updated filament-kit 1.0.0 -> 1.1.0" in out
    assert not (env / "opt/releases/.work").exists()
