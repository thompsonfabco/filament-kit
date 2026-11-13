"""`pair` never breaks a working pairing before the new one is proven; `status` says what the last run really did; what
the server hears of a failure is a class, never the detail."""
from __future__ import annotations

import json
import socket
import sys

import pytest
from test_cli import LINK_TOKEN, _dirs, _link, _main, _respond, _studio_closed, paths, srv  # noqa: F401

from fksync import client, store, studio, sync
from tls_helper import TlsServer, make_cert

NEW_TOKEN = "NewToken-Secret-aaaaaaaaaaaaaaaa"


def respond_with(state=None, status=200):
    def respond(m, p, b):
        if p == "/api/sync/state" and status != 200:
            return status, "application/json", {"error": "unauthorized", "message": "no such token"}
        if p == "/api/sync/state" and state is not None:
            return 200, "application/json", state
        return _respond(m, p, b)
    return respond


@pytest.fixture
def other(tmp_path):
    """A second server, for the new link."""
    made = []

    def start(respond):
        cert, key, fp = make_cert(tmp_path / f"cert{len(made)}")
        s = TlsServer(cert, key, respond=respond)
        s.__enter__()
        s.fp = fp
        made.append(s)
        return s
    yield start
    for s in made:
        s.__exit__(None, None, None)


def paired(srv, paths):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    dirs = _dirs(paths)
    return dirs, dirs.token.read_bytes(), store.load_config(dirs)


def test_a_dead_link_leaves_the_working_pairing_exactly_as_it_was(srv, paths, other, capsys):  # noqa: F811
    dirs, tok, cfg = paired(srv, paths)
    bad = other(respond_with(status=401))
    capsys.readouterr()
    assert _main(paths, "pair", stdin=_link(bad) + "\n") == 1
    out = capsys.readouterr().out
    assert "your previous pairing is unchanged" in out and "expired" in out
    assert dirs.token.read_bytes() == tok and store.load_config(dirs) == cfg
    assert not dirs.pair_aside.exists() and LINK_TOKEN not in out


def test_another_certificate_leaves_it_too(srv, paths, other, monkeypatch, capsys):  # noqa: F811
    dirs, tok, cfg = paired(srv, paths)
    bad = other(respond_with())

    def info(self):
        raise client.CertChanged("a" * 64, "b" * 64)
    monkeypatch.setattr(client.Client, "info", info)
    assert _main(paths, "pair", stdin=_link(bad) + "\n") == 1
    assert "your previous pairing is unchanged" in capsys.readouterr().out
    assert dirs.token.read_bytes() == tok and store.load_config(dirs) == cfg


def test_a_first_pairing_that_is_refused_leaves_nothing(paths, other, capsys):  # noqa: F811
    bad = other(respond_with(status=401))
    assert _main(paths, "pair", stdin=_link(bad) + "\n") == 1
    dirs = _dirs(paths)
    assert not dirs.token.exists() and not dirs.config.exists() and not dirs.pair_aside.exists()
    assert "Not paired" in capsys.readouterr().out


def _on_trial(srv, paths, monkeypatch, capsys, new):  # noqa: F811
    """A working pairing, then a new link while the server can't be reached. `new`: the link's server."""
    dirs, tok, cfg = paired(srv, paths)

    def down(self):
        raise client.Offline("no answer")
    real = client.Client.info
    with monkeypatch.context() as m:
        m.setattr(client.Client, "info", down)
        capsys.readouterr()
        assert _main(paths, "pair", stdin=_link(new) + "\n") == 1
    assert client.Client.info is real
    return dirs, tok, cfg


def test_not_reached_keeps_the_new_one_on_trial_and_the_old_one_aside(srv, paths, monkeypatch, capsys):  # noqa: F811
    dirs, tok, _cfg = _on_trial(srv, paths, monkeypatch, capsys, srv)
    out = capsys.readouterr().out
    assert "not confirmed yet" in out and "previous pairing comes back" in out
    assert store.load_token(dirs) == LINK_TOKEN and store.pair_waiting(dirs)


def test_a_first_pairing_not_reached_has_nothing_to_keep(srv, paths, monkeypatch, capsys):  # noqa: F811
    def down(self):
        raise client.Offline("no answer")
    monkeypatch.setattr(client.Client, "info", down)
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 1
    dirs = _dirs(paths)
    assert "previous pairing" not in capsys.readouterr().out
    assert store.load_token(dirs) == LINK_TOKEN and not dirs.pair_aside.exists()


def test_the_next_run_proves_it_and_the_old_one_goes(srv, paths, monkeypatch, capsys):  # noqa: F811
    dirs, _tok, _cfg = _on_trial(srv, paths, monkeypatch, capsys, srv)
    assert _main(paths, "run", "--quiet") == 0
    assert store.load_token(dirs) == LINK_TOKEN and not dirs.pair_aside.exists()
    assert store.load_config(dirs).get("device")


def test_the_next_run_brings_the_old_one_back_when_the_link_has_died(srv, paths, other, monkeypatch, capsys):  # noqa: F811
    dead = other(respond_with(status=401))
    dirs, tok, cfg = _on_trial(srv, paths, monkeypatch, capsys, dead)
    assert store.load_config(dirs).get("host") != cfg["host"] or store.load_config(dirs).get("fp") != cfg["fp"]
    n = len(srv.requests)
    assert _main(paths, "run", "--quiet") == 0
    assert dirs.token.read_bytes() == tok and store.load_config(dirs) == cfg and not dirs.pair_aside.exists()
    assert "the earlier pairing is back" in dirs.log_file.read_text(encoding="utf-8")
    assert len(srv.requests) > n                       # and the same run went on, with the old one


def test_still_away_it_stays_on_trial_and_the_run_is_a_warning(srv, paths, monkeypatch, capsys):  # noqa: F811
    dirs, tok, _cfg = _on_trial(srv, paths, monkeypatch, capsys, srv)

    def down(self):
        raise client.Offline("no answer")
    monkeypatch.setattr(client.Client, "info", down)
    assert _main(paths, "run", "--quiet") == 0
    assert store.pair_waiting(dirs) and store.load_token(dirs) == LINK_TOKEN


def test_status_leaves_a_pairing_on_trial_alone_and_says_so(srv, paths, monkeypatch, capsys):  # noqa: F811
    dirs, _tok, _cfg = _on_trial(srv, paths, monkeypatch, capsys, srv)
    capsys.readouterr()
    assert _main(paths, "status") == 0
    assert "not confirmed yet" in capsys.readouterr().out
    assert store.pair_waiting(dirs) and store.load_token(dirs) == LINK_TOKEN


def test_a_second_link_on_trial_keeps_the_last_proven_pairing_aside(srv, paths, other, monkeypatch, capsys):  # noqa: F811
    dirs, tok, cfg = _on_trial(srv, paths, monkeypatch, capsys, srv)
    bad = other(respond_with(status=401))
    capsys.readouterr()
    assert _main(paths, "pair", stdin=_link(bad) + "\n") == 1
    assert "your previous pairing is unchanged" in capsys.readouterr().out
    assert dirs.token.read_bytes() == tok and store.load_config(dirs) == cfg and not dirs.pair_aside.exists()


def test_unpair_drops_what_was_aside(srv, paths, monkeypatch, capsys):  # noqa: F811
    dirs, _tok, _cfg = _on_trial(srv, paths, monkeypatch, capsys, srv)
    assert _main(paths, "unpair") == 0
    assert not dirs.pair_aside.exists() and not dirs.token.exists()


@pytest.mark.parametrize("status,back", [(404, True), (403, True), (500, False), (503, False)])
def test_a_4xx_restores_and_a_5xx_waits(srv, paths, other, capsys, status, back):  # noqa: F811
    dirs, tok, cfg = paired(srv, paths)
    bad = other(lambda m, p, b: (status, "application/json", {"error": "x", "message": "no"}))
    assert _main(paths, "pair", stdin=_link(bad) + "\n") == 1
    if back:
        assert dirs.token.read_bytes() == tok and store.load_config(dirs) == cfg and not dirs.pair_aside.exists()
    else:
        assert store.load_token(dirs) == LINK_TOKEN and store.pair_waiting(dirs)


def test_a_full_disk_does_not_turn_a_failure_into_a_traceback(srv, paths, monkeypatch, capsys):  # noqa: F811
    from fksync import __main__ as cli
    dirs, _tok, _cfg = paired(srv, paths)

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(sync, "_save_state", full)
    cli._remember_error(dirs, "crash", "x")            # no exception


def test_a_crash_between_the_saves_brings_the_old_one_back_at_the_next_run(srv, paths, monkeypatch):  # noqa: F811
    dirs, tok, cfg = paired(srv, paths)
    store.set_pair_aside(dirs)
    store.save_config(dirs, {"host": "half.example.org", "port": 1, "fp": "0" * 64, "ips": []})
    store.save_token(dirs, NEW_TOKEN)                  # the process died here
    assert _main(paths, "run", "--quiet") == 0
    assert dirs.token.read_bytes() == tok and store.load_config(dirs).get("host") == cfg["host"]
    assert not dirs.pair_aside.exists()
    assert "interrupted" in dirs.log_file.read_text(encoding="utf-8")


def test_status_recovers_it_too(srv, paths):  # noqa: F811
    dirs, tok, _cfg = paired(srv, paths)
    store.set_pair_aside(dirs)
    store.save_token(dirs, NEW_TOKEN)
    assert _main(paths, "status") == 0
    assert dirs.token.read_bytes() == tok


def test_the_old_tokens_bytes_come_back_untouched_so_its_protection_is_kept(paths):  # noqa: F811
    dirs = _dirs(paths)
    dirs.ensure()
    blob = bytes(range(256))                           # as DPAPI would leave it: nothing here can decrypt it
    dirs.token.write_bytes(blob)
    store.set_pair_aside(dirs)
    dirs.token.write_bytes(b"other")
    assert store.restore_pair_aside(dirs) is True and dirs.token.read_bytes() == blob


def test_a_damaged_aside_changes_nothing(paths):  # noqa: F811
    dirs = _dirs(paths)
    dirs.ensure()
    dirs.token.write_bytes(b"keep")
    dirs.pair_aside.write_text("{nope", encoding="utf-8")
    assert store.restore_pair_aside(dirs) is False
    assert dirs.token.read_bytes() == b"keep" and not dirs.pair_aside.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_the_aside_is_as_private_as_the_token(srv, paths):  # noqa: F811
    dirs, _tok, _cfg = paired(srv, paths)
    store.set_pair_aside(dirs)
    assert dirs.pair_aside.stat().st_mode & 0o077 == 0


def test_a_run_in_progress_means_nothing_is_spent_or_changed(srv, paths, capsys):  # noqa: F811
    dirs, tok, _cfg = paired(srv, paths)
    n = len(srv.requests)
    with store.single_instance(dirs):
        assert _main(paths, "pair", stdin=_link(srv) + "\n") == 1
    assert "try again" in capsys.readouterr().out and dirs.token.read_bytes() == tok and len(srv.requests) == n


def test_pairing_says_when_another_pairing_owns_the_sync(paths, other, capsys):  # noqa: F811
    s = other(respond_with(state={"owner": "dev7", "you": "dev42"}))
    assert _main(paths, "pair", stdin=_link(s) + "\n") == 0
    assert "sudo filament-kit unpair dev7" in capsys.readouterr().out


def test_pairing_says_nothing_when_it_owns_the_sync_itself(paths, other, capsys):  # noqa: F811
    s = other(respond_with(state={"owner": "dev42", "you": "dev42"}))
    assert _main(paths, "pair", stdin=_link(s) + "\n") == 0
    assert "unpair" not in capsys.readouterr().out


def test_pairing_names_the_studio_folder_or_says_it_found_none(srv, paths, monkeypatch, capsys):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    assert "Bambu Studio folder:" in capsys.readouterr().out

    def none(*a, **k):
        raise studio.NotFound("Bambu Studio not found: open Bambu Studio once")
    monkeypatch.setattr(studio, "primary", none)
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    assert "open Bambu Studio once" in capsys.readouterr().out


# ---------- status ----------

def _down_for(monkeypatch, exc):
    def fail(*a, **k):
        raise exc
    monkeypatch.setattr(sync, "run_once", fail)


@pytest.mark.parametrize("exc,word,rc", [
    (client.ApiError(401, "unauthorized", "no"), "no longer accepts", 1),
    (client.CertChanged("a" * 64, "b" * 64), "FAILED", 1),
    (RuntimeError("boom"), "RuntimeError: boom", 1),
    (studio.NotFound("Bambu Studio not found"), "Bambu Studio not found", 1),
])
def test_status_says_the_last_run_failed_ahead_of_the_last_good_one(srv, paths, monkeypatch, capsys, exc, word, rc):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    assert _main(paths, "run", "--quiet") == 0
    _down_for(monkeypatch, exc)
    assert _main(paths, "run", "--quiet") == rc
    capsys.readouterr()
    assert _main(paths, "status") == 0
    out = capsys.readouterr().out
    assert "Last run:        FAILED at" in out and word in out
    assert "Last run:        uploaded" in out
    assert out.index("FAILED at") < out.index("Last run:        uploaded")


def test_a_run_that_gets_to_its_end_clears_the_failure(srv, paths, monkeypatch, capsys):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    with monkeypatch.context() as m:
        _down_for(m, RuntimeError("boom"))
        _main(paths, "run", "--quiet")
    assert sync.load_state(_dirs(paths)).get("last_error")
    assert _main(paths, "run", "--quiet") == 0
    assert "last_error" not in sync.load_state(_dirs(paths))
    capsys.readouterr()
    _main(paths, "status")
    assert "FAILED" not in capsys.readouterr().out


def test_offline_is_said_as_a_try_and_stays_exit_0(srv, paths, capsys):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    dirs = _dirs(paths)
    cfg = store.load_config(dirs)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    cfg.update(host="127.0.0.1", ips=[], port=s.getsockname()[1])
    store.save_config(dirs, cfg)
    try:                                            # bound, never listening: refused, and no other worker can take the port
        assert _main(paths, "run", "--quiet") == 0
    finally:
        s.close()
    capsys.readouterr()
    _main(paths, "status")
    out = capsys.readouterr().out
    assert "could not reach the server" in out and "FAILED" not in out


def test_status_shows_a_refused_upload_and_a_stopped_install(srv, paths, capsys):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    dirs = _dirs(paths)
    st = sync.load_state(dirs)
    st["rejected"] = {"live": {"kind": "live", "hash": "x", "at": 1.0, "error": "too many presets"}}
    st["partial"] = {"stamp": "20261108-120000", "at": 1.0}
    sync._save_state(dirs, st)
    capsys.readouterr()
    _main(paths, "status")
    out = capsys.readouterr().out
    assert "too many presets" in out and "20261108-120000" in out


def test_other_pc_is_a_failure_exit_and_refused_is_not(srv, paths, monkeypatch):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    monkeypatch.setattr(sync, "run_once", lambda *a, **k: "other_pc")
    assert _main(paths, "run", "--quiet") == 1
    monkeypatch.setattr(sync, "run_once", lambda *a, **k: "refused")
    assert _main(paths, "run", "--quiet") == 0


# ---------- what the server hears ----------

def _beats(srv):  # noqa: F811
    return [r for r in srv.requests if "/api/sync/heartbeat" in str(r)]


def test_the_server_hears_a_class_and_never_the_detail(srv, paths, monkeypatch):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    secret = r"C:\Users\alex\AppData\Roaming\BambuStudio\user\1234567\filament is broken"
    _down_for(monkeypatch, RuntimeError(secret))
    sent = []
    monkeypatch.setattr(client.Client, "heartbeat", lambda self, outcome, *a: sent.append((outcome, a)) or {})
    assert _main(paths, "run", "--quiet") == 1
    assert sent == [("error_crash", ())]
    assert "1234567" in sync.load_state(_dirs(paths))["last_error"]["detail"]     # kept here, on the PC


def test_it_hears_once_an_hour_and_when_it_is_over(srv, paths, monkeypatch):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    sent = []
    monkeypatch.setattr(client.Client, "heartbeat", lambda self, outcome, *a: sent.append(outcome) or {})
    with monkeypatch.context() as m:
        _down_for(m, RuntimeError("boom"))
        _main(paths, "run", "--quiet")
        _main(paths, "run", "--quiet")
    assert sent == ["error_crash"]
    assert _main(paths, "run", "--quiet") == 0
    assert sent[-1] != "error_crash" and len(sent) == 2


@pytest.mark.parametrize("exc", [client.ApiError(401, "unauthorized", "no"), client.CertChanged("a" * 64, "b" * 64)])
def test_a_failure_that_means_it_cant_be_told_is_not_sent(srv, paths, monkeypatch, exc):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    _down_for(monkeypatch, exc)
    monkeypatch.setattr(client.Client, "heartbeat", lambda *a, **k: pytest.fail("told"))
    assert _main(paths, "run", "--quiet") == 1


def test_a_heartbeat_that_fails_changes_nothing(srv, paths, monkeypatch):  # noqa: F811
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    _down_for(monkeypatch, RuntimeError("boom"))

    def down(self, *a):
        raise client.Offline("no")
    monkeypatch.setattr(client.Client, "heartbeat", down)
    assert _main(paths, "run", "--quiet") == 1
    assert json.dumps(sync.load_state(_dirs(paths))["last_error"]["class"]) == '"crash"'



def test_status_says_when_the_scheduled_task_is_missing(paths, monkeypatch, capsys):  # noqa: F811
    from fksync import __main__ as cli
    monkeypatch.setattr(cli, "_task_registered", lambda: False)
    assert _main(paths, "status") == 0
    assert "Scheduled task:  'filament-kit sync' is not registered" in capsys.readouterr().out
    for known in (True, None):
        monkeypatch.setattr(cli, "_task_registered", lambda known=known: known)
        assert _main(paths, "status") == 0
        assert "Scheduled task" not in capsys.readouterr().out


def test_task_registered_reads_the_schtasks_exit_code(monkeypatch):
    import subprocess

    from fksync import __main__ as cli
    monkeypatch.setattr(cli.sys, "platform", "win32")
    for code, want in ((0, True), (1, False)):
        monkeypatch.setattr(cli.subprocess, "run",
                            lambda *a, code=code, **k: subprocess.CompletedProcess(a, code))
        assert cli._task_registered() is want

    def missing(*a, **k):
        raise FileNotFoundError("schtasks")
    monkeypatch.setattr(cli.subprocess, "run", missing)
    assert cli._task_registered() is None
    monkeypatch.setattr(cli.sys, "platform", "linux")
    assert cli._task_registered() is None
