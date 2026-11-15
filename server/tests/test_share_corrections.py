"""The Share corrections setting (label_reader.share_corrections): the save and its checks, the job that sets the
reader with the module's own config command, the status of the reader's actual state, and the off path with delete.
Nothing runs as root: the command runner is a fake that records the command lines and changes the fake reader."""
from __future__ import annotations

import json

import pytest
from fakes import local_reader_fake as lrf
from test_setup_page import Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, config, local_intake_install as lii, local_reader, setup_helper, share_corrections as sc

KEY = "label_reader.share_corrections"


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_LOCAL_INTAKE_STORE", str(tmp_path / "store"))
    monkeypatch.setattr(local_reader, "CONNECT_TIMEOUT", 0.5)


@pytest.fixture
def jobs(monkeypatch):
    seen = []
    monkeypatch.setattr(setup_helper, "_start_job", lambda name, why="", checked=False: seen.append(name))
    return seen


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper())


def install_record(tmp_path):
    (tmp_path / "store").mkdir(exist_ok=True)
    (tmp_path / "store" / "installed.json").write_text(json.dumps({"version": "0.2.0", "tier": "cpu"}))


def set_up(url=None, installed=True, tmp_path=None, on=True, saved=None):
    cfg = config.load()
    cfg["modules"] = {**cfg.get("modules", {"spoolman": True, "server": True}), "local_intake": on}
    if url:
        cfg["local_intake"] = {"url": url, "tier": "auto"}
    if saved is not None:
        cfg["label_reader"] = {"share_corrections": saved}
    config.save(cfg)
    if installed:
        install_record(tmp_path)
    return config.load()


class Run:
    """The command runner: records each command line; the module's config command changes the fake reader."""

    def __init__(self, data, rc=0, restart_rc=0):
        self.data, self.calls, self.rc, self.restart_rc, self.pending = data, [], rc, restart_rc, None

    def __call__(self, cmd, log):
        self.calls.append(cmd)
        log("output line")
        if cmd[0] == "systemctl":
            if self.restart_rc == 0 and self.pending is not None:
                self.data["opt_in"] = self.pending
                lrf.feedback_health(self.data)
            return self.restart_rc
        if self.rc == 0:
            self.pending = cmd[-1] == "true"
        return self.rc


def reader(fake_reader):
    url, data = fake_reader
    lrf.feedback_health(data)
    return url, data


def healthy(cfg):
    return local_reader.health(cfg)


# ---------------------------------------------------------------- the setting and its save

def test_the_setting_is_in_the_general_table_as_a_bool():
    check, then = setup_helper.GENERAL[KEY]
    assert check(True) is True and check(False) is False and then is None
    for bad in ("true", 1, 0, None, "on"):
        with pytest.raises(ValueError):
            check(bad)


def test_no_address_setting_exists():
    assert not [k for k in setup_helper.GENERAL if "feedback" in k or "address" in k or "endpoint" in k]


def test_turning_it_on_saves_and_starts_the_job(app, jobs, tmp_path, fake_reader):
    url, _ = reader(fake_reader)
    set_up(url, tmp_path=tmp_path)
    r = post(client(app), "settings/general", {"values": {KEY: True, "server_name": "Shop"}})
    assert r.status_code == 200, r.text
    assert r.json()["jobs"] == ["local_intake_share"] and jobs == ["local_intake_share"]
    assert config.load()["label_reader"]["share_corrections"] is True


def test_turning_it_off_saves_and_starts_the_job(app, jobs, tmp_path, fake_reader):
    url, _ = reader(fake_reader)
    set_up(url, tmp_path=tmp_path, saved=True)
    r = post(client(app), "settings/general", {"values": {KEY: False}})
    assert r.status_code == 200 and r.json()["jobs"] == ["local_intake_share"]
    assert config.load()["label_reader"]["share_corrections"] is False


def test_the_one_key_form_works_too(app, jobs, tmp_path, fake_reader):
    url, _ = reader(fake_reader)
    set_up(url, tmp_path=tmp_path)
    r = post(client(app), "settings/general", {"key": KEY, "value": True})
    assert r.status_code == 200 and r.json()["jobs"] == ["local_intake_share"]


def test_a_save_that_does_not_change_it_starts_no_job(app, jobs, tmp_path, fake_reader):
    url, _ = reader(fake_reader)
    set_up(url, tmp_path=tmp_path, saved=True)
    r = post(client(app), "settings/general", {"values": {KEY: True, "server_name": "Shop"}})
    assert r.status_code == 200 and "jobs" not in r.json() and not jobs
    off = post(client(app), "settings/general", {"values": {"server_name": "x"}})
    assert "jobs" not in off.json() and not jobs


@pytest.mark.parametrize("value", ["true", 1, None, "on", [True]])
def test_a_value_that_is_not_a_bool_is_refused(app, jobs, tmp_path, value):
    set_up(tmp_path=tmp_path)
    before = config.load()
    r = post(client(app), "settings/general", {"values": {KEY: value}})
    assert r.status_code == 400 and KEY in r.json()["errors"]
    assert config.load() == before and not jobs


def test_cloud_only_cannot_turn_it_on(app, jobs, tmp_path):
    set_up(installed=False, tmp_path=tmp_path, on=False)
    before = config.load()
    r = post(client(app), "settings/general", {"values": {KEY: True, "server_name": "Shop"}})
    assert r.status_code == 400 and "Switch it on in Features" in r.json()["errors"][KEY]
    assert config.load() == before and not jobs
    one = post(client(app), "settings/general", {"key": KEY, "value": True})
    assert one.status_code == 400 and one.json()["field"] == "value"


def test_a_reader_that_is_not_installed_here_cannot_be_turned_on(app, jobs, tmp_path):
    set_up(installed=False, tmp_path=tmp_path, on=True)
    r = post(client(app), "settings/general", {"values": {KEY: True}})
    assert r.status_code == 400 and "installed on this Hub" in r.json()["errors"][KEY] and not jobs


def test_off_is_always_allowed(app, jobs, tmp_path):
    set_up(installed=False, tmp_path=tmp_path, on=False, saved=True)
    r = post(client(app), "settings/general", {"values": {KEY: False}})
    assert r.status_code == 200 and config.load()["label_reader"]["share_corrections"] is False


def test_the_view_reports_off_until_it_is_set(app, tmp_path):
    set_up(tmp_path=tmp_path)
    assert client(app).get("/setup/api/settings/general").json()["values"][KEY] is False


# ---------------------------------------------------------------- the job

def test_the_job_is_a_closed_one_with_no_arguments():
    assert setup_helper.JOBS["local_intake_share"] == ("local-intake", "share-corrections")
    assert "local_intake_share" in setup_helper.BUSY


@pytest.mark.parametrize("want,flag", [(True, "true"), (False, "false")])
def test_the_job_runs_the_modules_config_command_then_restarts(fake_reader, tmp_path, want, flag, capsys):
    url, data = reader(fake_reader)
    data["opt_in"] = not want
    lrf.feedback_health(data)
    cfg = set_up(url, tmp_path=tmp_path, saved=want)
    run = Run(data)
    assert cli.cmd_local_intake_share(run=run, wait=lambda c: healthy(c)) == 0
    assert run.calls == [["runuser", "-u", "filament-kit-vision", "--", "/opt/filament-kit-vision/.venv/bin/filament-kit-vision",
                          "config", "--feedback-opt-in", flag],
                         ["systemctl", "restart", "filament-kit-vision.service"]]
    out = capsys.readouterr().out
    assert [ln.split(" ")[:5] for ln in out.splitlines() if ln.startswith("==> step")] == [
        ["==>", "step", "1", "of", "4"], ["==>", "step", "2", "of", "4"], ["==>", "step", "3", "of", "4"],
        ["==>", "step", "4", "of", "4"]]
    assert data["opt_in"] is want and sc.state(cfg)["differs"] is False


def test_the_job_never_passes_an_endpoint(fake_reader, tmp_path):
    url, data = reader(fake_reader)
    data["opt_in"] = False
    lrf.feedback_health(data)
    set_up(url, tmp_path=tmp_path, saved=True)
    run = Run(data)
    sc.apply(config.load(), run=run, wait=healthy)
    flat = " ".join(" ".join(c) for c in run.calls).lower()
    assert "endpoint" not in flat and "http" not in flat and "address" not in flat
    for on in (True, False):
        assert "endpoint" not in " ".join(sc.config_command(on)).lower()


def test_nothing_runs_when_the_reader_is_already_set_that_way(fake_reader, tmp_path, capsys):
    url, data = reader(fake_reader)
    set_up(url, tmp_path=tmp_path, saved=True)               # the fake's opt-in is on
    run = Run(data)
    assert cli.cmd_local_intake_share(run=run) == 0
    assert run.calls == [] and "already has sharing of corrections on" in capsys.readouterr().out


def test_the_job_sets_a_reader_that_does_not_answer(tmp_path, capsys):
    set_up("http://127.0.0.1:9", tmp_path=tmp_path, saved=True)
    run = Run(lrf.new_data())
    got = sc.apply(config.load(), run=run, wait=lambda c: {"ok": True, "capabilities": {}})
    assert got == {"want": True, "changed": True} and len(run.calls) == 2


def test_a_failed_config_command_restarts_nothing(fake_reader, tmp_path, capsys):
    url, data = reader(fake_reader)
    data["opt_in"] = False
    lrf.feedback_health(data)
    set_up(url, tmp_path=tmp_path, saved=True)
    run = Run(data, rc=3)
    assert cli.cmd_local_intake_share(run=run) == 1
    assert len(run.calls) == 1 and "config command failed (exit 3)" in capsys.readouterr().err


def test_a_failed_restart_is_reported(fake_reader, tmp_path, capsys):
    url, data = reader(fake_reader)
    data["opt_in"] = False
    lrf.feedback_health(data)
    set_up(url, tmp_path=tmp_path, saved=True)
    assert cli.cmd_local_intake_share(run=Run(data, restart_rc=1)) == 1
    assert "did not restart" in capsys.readouterr().err


def test_a_reader_that_still_says_the_old_value_is_reported(fake_reader, tmp_path, capsys):
    url, data = reader(fake_reader)
    data["opt_in"] = False
    lrf.feedback_health(data)
    set_up(url, tmp_path=tmp_path, saved=True)

    class Stuck(Run):
        def __call__(self, cmd, log):
            self.calls.append(cmd)
            return 0
    assert cli.cmd_local_intake_share(run=Stuck(data), wait=healthy) == 1
    assert "still has sharing of corrections off" in capsys.readouterr().err


def test_the_job_refuses_without_the_installed_reader(tmp_path, capsys):
    set_up(installed=False, tmp_path=tmp_path, saved=True)
    run = Run({})
    assert cli.cmd_local_intake_share(run=run) == 1 and run.calls == []
    assert "installed on this Hub" in capsys.readouterr().err


def test_the_job_refuses_a_reader_too_old_for_it(fake_reader, tmp_path, capsys):
    url, data = fake_reader                                  # API 1.0, no capabilities
    set_up(url, tmp_path=tmp_path, saved=True)
    run = Run(data)
    assert cli.cmd_local_intake_share(run=run) == 1 and run.calls == []
    assert "too old" in capsys.readouterr().err


def test_the_command_needs_root(monkeypatch, capsys):
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    run = Run({})
    assert cli.cmd_local_intake_share(run=run) == 1 and run.calls == []


def test_cli_parses_the_command(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_local_intake_share", lambda *a, **k: seen.append((a, k)) or 0)
    assert cli.main(["local-intake", "share-corrections"]) == 0 and seen == [((), {})]


# ---------------------------------------------------------------- the status

def test_status_mapping_on_off_and_a_mismatch(fake_reader, tmp_path):
    url, data = reader(fake_reader)
    cfg = set_up(url, tmp_path=tmp_path, saved=True)
    st = sc.state(cfg)
    assert st == {"saved": True, "actual": True, "differs": False, "count": 0, "reason": None}
    data["opt_in"] = False
    lrf.feedback_health(data)
    assert sc.state(cfg) == {"saved": True, "actual": False, "differs": True, "count": 0, "reason": None}
    assert sc.state(set_up(url, tmp_path=tmp_path, saved=False))["differs"] is False


def test_status_reads_the_state_from_the_list_when_health_does_not_say(fake_reader, tmp_path):
    url, data = fake_reader
    lrf.feedback_health(data, with_capabilities=False)       # 1.1 without `capabilities`: opt_in unknown there
    data["opt_in"] = False
    cfg = set_up(url, tmp_path=tmp_path, saved=False)
    assert sc.state(cfg)["actual"] is False
    data["opt_in"] = True
    assert sc.state(cfg) == {"saved": False, "actual": True, "differs": True, "count": None, "reason": None}


def test_status_reasons(fake_reader, tmp_path):
    url, data = fake_reader
    assert sc.state(set_up(url, installed=False, tmp_path=tmp_path, on=False))["reason"] == "off"
    assert sc.state(set_up(url, installed=False, tmp_path=tmp_path, on=True))["reason"] == "not_installed"
    cfg = set_up(url, tmp_path=tmp_path)
    assert sc.state(cfg)["reason"] == "too_old"             # API 1.0
    assert sc.state(set_up("http://127.0.0.1:9", tmp_path=tmp_path))["reason"] == "no_answer"
    lrf.feedback_health(data)
    assert sc.state(cfg)["reason"] is None


def test_the_reader_status_route_carries_the_state(app, fake_reader, tmp_path):
    url, data = reader(fake_reader)
    set_up(url, tmp_path=tmp_path, saved=False)
    got = client(app).get("/setup/api/settings/local-intake").json()
    assert got["ok"] and got["share_corrections"] == {"saved": False, "actual": True, "differs": True, "count": 0,
                                                       "reason": None}


# ---------------------------------------------------------------- the off path with delete

def queue(data, n):
    for i in range(n):
        data["queue"].append({"id": f"fb-{i}", "created_at": "t", "predicted": {}, "corrected": {}, "note": "",
                              "photos": 1, "jpegs": [b"x"], "thumbnail_b64": ""})


def test_delete_waiting_deletes_each_entry(fake_reader, tmp_path):
    url, data = reader(fake_reader)
    queue(data, 3)
    assert sc.delete_waiting(set_up(url, tmp_path=tmp_path)) == 3 and data["queue"] == []


def test_off_with_delete_waiting_deletes_then_saves(app, jobs, fake_reader, tmp_path):
    url, data = reader(fake_reader)
    queue(data, 2)
    set_up(url, tmp_path=tmp_path, saved=True)
    r = post(client(app), "settings/general", {"values": {KEY: False}, "delete_waiting": True})
    assert r.status_code == 200 and r.json()["deleted"] == 2 and r.json()["jobs"] == ["local_intake_share"]
    assert data["queue"] == [] and config.load()["label_reader"]["share_corrections"] is False


def test_off_without_the_option_keeps_what_is_waiting(app, jobs, fake_reader, tmp_path):
    url, data = reader(fake_reader)
    queue(data, 2)
    set_up(url, tmp_path=tmp_path, saved=True)
    r = post(client(app), "settings/general", {"values": {KEY: False}})
    assert r.status_code == 200 and "deleted" not in r.json() and len(data["queue"]) == 2


def test_the_option_is_ignored_when_turning_on(app, jobs, fake_reader, tmp_path):
    url, data = reader(fake_reader)
    queue(data, 2)
    set_up(url, tmp_path=tmp_path, saved=False)
    r = post(client(app), "settings/general", {"values": {KEY: True}, "delete_waiting": True})
    assert r.status_code == 200 and "deleted" not in r.json() and len(data["queue"]) == 2


def test_the_option_needs_the_code_and_deletes_nothing_without_it(app, jobs, fake_reader, tmp_path):
    url, data = reader(fake_reader)
    queue(data, 2)
    set_up(url, tmp_path=tmp_path, saved=True)
    r = post(client(app), "settings/general", {"values": {KEY: False}, "delete_waiting": True}, code="0000-0000")
    assert r.status_code == 403 and len(data["queue"]) == 2 and not jobs
    assert config.load()["label_reader"]["share_corrections"] is True


def test_a_reader_that_cannot_delete_changes_nothing(app, jobs, fake_reader, tmp_path):
    url, data = reader(fake_reader)
    queue(data, 2)
    data["token"] = "secret-token"                          # the Hub has no token: the reader refuses
    set_up(url, tmp_path=tmp_path, saved=True)
    r = post(client(app), "settings/general", {"values": {KEY: False}, "delete_waiting": True})
    assert r.status_code == 502 and "nothing was changed" in r.json()["error"]
    assert config.load()["label_reader"]["share_corrections"] is True and not jobs
