"""The setup console, stage 1: the job unit and its API, Overview, the mode presets, Updates, and what each new route
shows without the setup code. The page's older routes are in test_setup_page.py; the CLI's words in
test_console_cli_snapshots.py."""
from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from test_setup_page import (CODE, H, HOME, SERIAL, STATIC, Helper, client, env, make, post)  # noqa: F401

from filament_kit import config, modules, redact, release, setup_helper, status, updates
from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer
from filament_kit.setup_console import jobs

PRINTER_IP = "192.0.2.41"
STATION = "http://192.0.2.30:5003"
SPOOLMAN = "http://192.0.2.31:7912"
PUBLIC = "https://printer.example.com/filament"
PLANTED = (SERIAL, PRINTER_IP, "192.0.2.30", "192.0.2.31", "printer.example.com")
ROOT = Path(__file__).resolve().parents[2]
SYSTEMD = ROOT / "install" / "systemd"


class Manager:
    def sync(self):
        pass

    def state(self, serial):
        return "connected"


@pytest.fixture
def helper():
    return Helper()


@pytest.fixture
def app(env, helper):  # noqa: F811
    return make(env, helper, Manager())


@pytest.fixture
def owned(env, monkeypatch):  # noqa: F811
    """A server that knows its owner's addresses, with Spoolman and the station answering in words that name them."""
    from filament_kit import cli
    registry.upsert(Printer(SERIAL, "Bench", "O1D", PRINTER_IP, "12345678", True))
    c = config.load()
    c["spoolman_url"] = SPOOLMAN
    c["station"] = {**c["station"], "url": STATION}
    c["web"] = {**c["web"], "public_url": PUBLIC}
    c["modules"]["web"] = True
    config.save(c)
    monkeypatch.setattr(cli.Spoolman, "ping", lambda self: "1.2.3")
    monkeypatch.setattr(cli.Spoolman, "missing_fields", lambda self: [])

    class Station:
        def __init__(self, url, backoff=0):
            pass

        def state(self):
            raise cli.StationUnreachable("no")
    monkeypatch.setattr(cli, "StationClient", Station)
    monkeypatch.setattr(cli, "_web_health", lambda port: (True, "ok"))


def write_log(text: str) -> None:
    p = setup_helper.job_log()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


# ---------- the jobs ----------

@pytest.mark.parametrize("name,args", [("apply", ["modules", "apply", "--no-pair"]), ("update", ["update"]),
                                       ("rollback", ["update", "--rollback"]), ("check", ["update", "--check"])])
def test_each_job_runs_the_clis_own_command_with_no_terminal(env, monkeypatch, name, args):  # noqa: F811
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, stdin=kw["stdin"])
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(setup_helper.subprocess, "run", run)
    assert setup_helper.run_job(name) == 0
    assert seen == {"cmd": [setup_helper.WRAPPER, *args], "stdin": subprocess.DEVNULL}
    assert jobs.view(0)["name"] == name


def test_job_run_takes_the_request_once(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(setup_helper, "run_job", lambda n: {"update": 7}[n])
    setup_helper.job_request().parent.mkdir(parents=True)
    setup_helper.job_request().write_text('{"name": "update"}', encoding="utf-8")
    assert setup_helper.main(["job-run"]) == 7
    assert not setup_helper.job_request().exists()
    assert setup_helper.main(["job-run"]) == 2


def test_job_run_refuses_a_name_off_the_list(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(setup_helper, "run_job", lambda n: pytest.fail("ran"))
    setup_helper.job_request().parent.mkdir(parents=True)
    setup_helper.job_request().write_text('{"name": "rm -rf /"}', encoding="utf-8")
    assert setup_helper.job_run() == 2


def test_the_old_units_entry_still_runs_the_apply(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(setup_helper, "run_job", lambda n, cmd=None: {"apply": 5}[n])
    assert setup_helper.main(["apply-run"]) == 5


def test_a_job_removes_the_log_a_rollback_would_misread(env):  # noqa: F811
    setup_helper.apply_log().parent.mkdir(parents=True)
    setup_helper.apply_log().write_text("==> filament-kit modules apply\nhalf done\n", encoding="utf-8")
    assert setup_helper.run_apply([sys.executable, "-c", "print('hello')"]) == 0
    assert not setup_helper.apply_log().exists()
    assert "hello" in jobs.view(0)["text"]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM to a child")
def test_sigterm_waits_for_the_command_and_its_exit_lands_in_the_log(env):  # noqa: F811
    """As an update stopped by systemd: its own handler starts the kit again, so it must not be killed from here."""
    import os
    import threading
    code = ("import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, lambda *a: (print('putting the kit back', flush=True), sys.exit(143)))\n"
            "print('ready', flush=True)\ntime.sleep(20)\n")

    def term():
        for _ in range(100):
            if setup_helper.job_log().exists() and "ready" in setup_helper.job_log().read_text(encoding="utf-8"):
                break
            threading.Event().wait(0.05)
        os.kill(os.getpid(), signal.SIGTERM)
        out = subprocess.run(["pgrep", "-f", "putting the kit back"], capture_output=True, text=True).stdout.split()
        for pid in out:
            if int(pid) != os.getpid():
                os.kill(int(pid), signal.SIGTERM)
    threading.Thread(target=term, daemon=True).start()
    assert setup_helper.run_job("update", [sys.executable, "-c", code]) == 143
    v = jobs.view(0)
    assert v["exit"] == 143 and "putting the kit back" in v["text"]


def test_starting_a_job_writes_only_its_name_and_starts_the_new_unit(env, monkeypatch):  # noqa: F811
    monkeypatch.delenv("FK_NO_SYSTEMD")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="inactive\n", stderr="")
    monkeypatch.setattr(setup_helper.subprocess, "run", run)
    setup_helper._start_job("update")
    assert ["systemctl", "start", "--no-block", setup_helper.JOB_UNIT] in calls
    assert json.loads(setup_helper.job_request().read_text(encoding="utf-8")) == {"name": "update"}


def test_a_job_that_will_not_start_leaves_no_request(env, monkeypatch):  # noqa: F811
    monkeypatch.delenv("FK_NO_SYSTEMD")

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1 if "start" in cmd else 0, stdout="inactive\n", stderr="nope")
    monkeypatch.setattr(setup_helper.subprocess, "run", run)
    with pytest.raises(setup_helper.Refused) as e:
        setup_helper._start_job("rollback")
    assert e.value.status == 500 and "update --rollback" in e.value.message
    assert not setup_helper.job_request().exists()


@pytest.mark.parametrize("unit", [setup_helper.JOB_UNIT, setup_helper.APPLY_UNIT])
def test_either_unit_running_means_a_job_is_running(env, monkeypatch, unit):  # noqa: F811
    monkeypatch.delenv("FK_NO_SYSTEMD")

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="activating\n" if cmd[-1] == unit else "inactive\n")
    monkeypatch.setattr(setup_helper.subprocess, "run", run)
    assert setup_helper._applying() is True


def test_a_request_not_picked_up_yet_counts_as_running(env, monkeypatch):  # noqa: F811
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(setup_helper.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="inactive\n", stderr=""))
    setup_helper._start_job("update")
    with pytest.raises(setup_helper.Refused) as e:
        setup_helper._start_job("rollback")
    assert e.value.status == 409


def test_the_refusal_names_the_job_that_runs(app, env, monkeypatch):  # noqa: F811
    write_log(setup_helper.header("update") + "\nworking\n")
    monkeypatch.setattr(setup_helper, "_applying", lambda: True)
    r = post(client(app), "job", {"name": "check"})
    assert r.status_code == 409 and r.json()["error"] == setup_helper.BUSY["update"]
    r = post(client(app), "modules", {"name": "ai_intake", "on": True})
    assert r.status_code == 409 and r.json()["error"] == setup_helper.BUSY["update"]


def test_a_job_needs_the_code(app, helper):
    c = client(app)
    assert post(c, "job", {"name": "update"}, code=None).status_code == 403
    assert post(c, "job", {"name": "update"}, code="00000000").status_code == 403
    assert post(c, "job", {"name": "update"}, code=CODE, headers={}).status_code == 403     # no Origin


@pytest.mark.parametrize("name", ["uninstall", "", None, 3, "update; reboot", "../x"])
def test_a_job_off_the_list_is_refused_before_the_helper(app, helper, name):
    r = post(client(app), "job", {"name": name})
    assert r.status_code == 400 and helper.calls == []
    assert setup_helper.handle({"op": "job", "code": CODE, "name": name})["status"] == 400


def test_a_job_that_starts_writes_one_audit_line_without_the_code(app, monkeypatch, caplog):
    started = []
    monkeypatch.setattr(setup_helper, "_start_job", lambda n, why="": started.append(n))
    caplog.set_level("INFO", logger="filament_kit")
    assert post(client(app), "job", {"name": "check"}).json() == {"ok": True, "name": "check"}
    assert started == ["check"]
    assert "setup: job check started from 192.0.2.20" in caplog.text and CODE not in caplog.text


def test_update_refused_while_a_printer_is_busy_in_the_printers_words_without_its_serial(app, monkeypatch):
    monkeypatch.setattr(updates, "printers_idle", _busy)
    monkeypatch.setattr(setup_helper, "_start_job", lambda n, why="": pytest.fail("started"))
    r = post(client(app), "job", {"name": "update"})
    assert r.status_code == 409 and r.json()["error"] == updates.BUSY_TEXT and SERIAL not in r.text


def _busy():
    class Held:
        def __enter__(self):
            raise updates.Busy(SERIAL)

        def __exit__(self, *a):
            return False
    return Held()


@pytest.mark.skipif(sys.platform == "win32", reason="flock")
def test_the_look_at_the_locks_works_where_the_helper_may_not_write(env, monkeypatch):  # noqa: F811
    """The root helper's filesystem is read-only outside its own folders: a lock must open read-only to be seen."""
    import fcntl
    d = config.paths().state / "printers" / SERIAL
    d.mkdir(parents=True)
    lock = d / "mapping.lock"
    lock.touch()
    lock.chmod(0o444)
    held = open(lock)
    fcntl.flock(held.fileno(), fcntl.LOCK_EX)
    assert updates.idle_problem() == updates.BUSY_TEXT
    held.close()
    assert updates.idle_problem() is None


def test_rollback_refused_with_nothing_kept_and_with_a_module_the_target_lacks(app, monkeypatch):
    monkeypatch.setattr(setup_helper, "_start_job", lambda n, why="": pytest.fail("started"))
    r = post(client(app), "job", {"name": "rollback"})
    assert r.status_code == 409 and "nothing to roll back to" in r.json()["error"]
    updates._write_state(previous="0.3.0")
    cfg = config.load()
    cfg["modules"]["klipper"] = True
    config.save(cfg)
    r = post(client(app), "job", {"name": "rollback"})
    assert r.status_code == 409
    assert r.json()["error"] == ("filament-kit 0.3.0 has no klipper module; run "
                                 "`sudo filament-kit modules disable klipper` first")


def test_job_view_before_any_job(app):
    r = client(app).get("/setup/api/job").json()
    assert r["seen"] is False and r["running"] is False and r["name"] is None and r["version"]


def test_job_view_follows_a_log_from_an_offset(app):
    c = client(app)
    write_log(setup_helper.header("check") + "\nfirst\nhalf a li")
    r = c.get("/setup/api/job?from=0").json()
    assert r["running"] is True and r["name"] == "check" and r["text"].endswith("first\n")       # whole lines only
    write_log(setup_helper.header("check") + "\nfirst\nhalf a line\n\n==> finished (exit 3)\n")
    r2 = c.get(f"/setup/api/job?from={r['next']}").json()
    assert r2["text"].startswith("half a line") and r2["running"] is False and r2["exit"] == 3
    assert c.get(f"/setup/api/job?from={r2['next']}").json()["text"] == ""
    assert c.get("/setup/api/job?from=x").status_code == 400


def test_an_address_cut_by_the_chunk_size_is_not_shown(app, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_LOG", 64)
    head = setup_helper.header("apply") + "\n"
    line = "x" * (64 - len(head) - 4) + " 192.0.2.77 end\n"
    write_log(head + line)
    c = client(app)
    r = c.get("/setup/api/job").json()
    assert r["text"] == head and "192" not in r["text"]


def test_a_job_with_no_last_line_is_given_up_on_after_the_units_timeout(app, monkeypatch):
    write_log(setup_helper.header("update") + "\nworking\n")
    monkeypatch.setattr(jobs, "STALE_AFTER", -1)
    r = client(app).get("/setup/api/job").json()
    assert r["running"] is False and r["lost"] is True and r["exit"] is None


def test_the_log_hides_addresses_and_comes_whole_with_the_code(app, owned):
    write_log(setup_helper.header("apply") + f"\nOK   Spoolman reachable at {SPOOLMAN}\n{SERIAL} at {PRINTER_IP}\n"
              "Open https://kit.local:8710/setup\n\n==> finished (exit 0)\n")
    c = client(app)
    free = c.get("/setup/api/job")
    apply_old_name = c.get("/setup/api/apply")
    for r in (free, apply_old_name):
        assert r.status_code == 200 and r.json()["redacted"] is True
        for v in (*PLANTED, "kit.local"):
            assert v not in r.text
    assert post(c, "job/log", {"from": 0}, code=None).status_code == 403
    assert post(c, "job/log", {"from": 0}, code="00000000").status_code == 403
    whole = post(c, "job/log", {"from": 0}).json()
    assert whole["redacted"] is False and SERIAL in whole["text"] and SPOOLMAN in whole["text"]


# ---------- what the new routes show without the code ----------

def test_no_new_route_shows_an_owners_address_or_serial_without_the_code(app, owned):
    write_log(setup_helper.header("apply") + f"\n{SERIAL} {PRINTER_IP} {STATION} {PUBLIC}\n\n==> finished (exit 0)\n")
    updates._write_state(latest={"version": "9.9.9", "notes": "New things.", "going_back": "", "at": 1.0})
    c = client(app)
    for route in ("overview", "job", "job?from=0", "apply", "updates", "modules/preview?mode=server",
                  "modules/preview?mode=all-in-one", "modules/preview?mode=station"):
        r = c.get("/setup/api/" + route)
        assert r.status_code == 200, route
        for v in PLANTED:
            assert v not in r.text, (route, v)


# ---------- Overview ----------

def test_overview_shows_the_status_rows_without_addresses(app, owned):
    r = client(app).get("/setup/api/overview").json()
    assert r["redacted"] is True and r["version"] and r["update"]["installed"] == r["version"]
    texts = [x["text"] for x in r["rows"]]
    assert f"Spoolman reachable at {redact.HIDDEN} (v1.2.3)" in texts
    assert f"station not answering at {redact.HIDDEN}" in texts
    assert f"public URL {redact.HIDDEN}" in texts
    bad = next(x for x in r["rows"] if x["text"].startswith("station not"))
    assert bad["state"] == "fail" and "192.0.2.30" not in bad["fix"] and "systemctl status" in bad["fix"]


def test_overview_with_the_code_is_whole_and_a_wrong_code_counts(app, owned, helper):
    c = client(app)
    r = post(c, "overview", {}).json()
    assert r["redacted"] is False
    assert f"Spoolman reachable at {SPOOLMAN} (v1.2.3)" in [x["text"] for x in r["rows"]]
    assert helper.calls == ["check"]
    assert post(c, "overview", {}, code="00000000").status_code == 403
    assert post(c, "overview", {}, code=None).status_code == 403


def test_overview_never_tries_the_anthropic_key(app, owned, monkeypatch):
    from filament_kit import cli
    cfg = config.load()
    cfg["modules"]["ai_intake"] = True
    config.save(cfg)
    monkeypatch.setattr(cli, "check_key", lambda f=None: pytest.fail("spent a call"))
    rows = client(app).get("/setup/api/overview").json()["rows"]
    assert any(x["text"] == "Anthropic key missing" and x["state"] == "fail" for x in rows)
    (config.paths().etc / cli.KEY_FILE).write_text("sk-ant-EXAMPLE", encoding="utf-8")
    assert status.collect(config.load())[0]    # the row is read fresh below, past the page's short memory
    assert not any("sk-ant" in x.text for x in status.collect(config.load()))
    assert any(x.text.startswith("Anthropic key set") for x in status.collect(config.load()))


def test_overview_is_remembered_briefly(app, owned, monkeypatch):
    n = []
    real = status.collect
    monkeypatch.setattr(status, "collect", lambda *a, **k: n.append(1) or real(*a, **k))
    c = client(app)
    c.get("/setup/api/overview")
    c.get("/setup/api/overview")
    assert len(n) == 1


def test_missing_fields_offer_the_fix_and_the_fix_needs_the_code(app, owned, monkeypatch, caplog):
    from filament_kit import cli
    monkeypatch.setattr(cli.Spoolman, "missing_fields", lambda self: ["nfc_id"])
    made = []
    monkeypatch.setattr(cli.Spoolman, "ensure_fields", lambda self: made.append(1) or ["nfc_id"])
    caplog.set_level("INFO", logger="filament_kit")
    c = client(app)
    row = next(x for x in c.get("/setup/api/overview").json()["rows"] if x["action"])
    assert row["action"] == "ensure_fields" and "nfc_id" in row["text"]
    assert post(c, "fields", {}, code=None).status_code == 403 and not made
    assert post(c, "fields", {}).json() == {"ok": True, "made": ["nfc_id"]} and made == [1]
    assert "setup: Spoolman fields made from 192.0.2.20" in caplog.text


def test_cli_status_has_no_console_rows(env, monkeypatch, capsys):  # noqa: F811
    from filament_kit import cli
    monkeypatch.setattr(cli.Spoolman, "ping", lambda self: "1.2.3")
    monkeypatch.setattr(cli.Spoolman, "missing_fields", lambda self: pytest.fail("the CLI's status does not ask"))
    cli.main(["status"])
    assert "extra fields" not in capsys.readouterr().out


# ---------- the redaction ----------

@pytest.mark.parametrize("text", ["see 192.0.2.5 now", "at 192.0.2.5:8883", "net 198.51.100.0/24", "https://x.example.com/a",
                                  "http://10.0.0.2:7912", "kit.local:8710", "printer.internal", "fe80::1", "::1",
                                  "2001:db8:1:2:3:4:5:6", SERIAL, "serial 03W00X123456789."])
def test_redaction_hides(text):
    out = redact.text(text, [])
    assert redact.HIDDEN in out
    for part in ("192.", "198.", "10.0", "example.com", "kit.local", "printer.internal", "fe80", SERIAL, "03W00X"):
        assert part not in out


@pytest.mark.parametrize("text", ["filament-kit 0.4.0", "14:03:22 started", "ERROR Something", "exit 143",
                                  "the updates module is off", "2026-11-08 14:00", "filament-kit.service active",
                                  "print_error 0x0500C010", "sudo filament-kit modules disable klipper"])
def test_redaction_leaves_ordinary_words(text):
    assert redact.text(text, []) == text


def test_redaction_uses_the_values_this_server_knows(owned):
    known = redact.known_values()
    assert SERIAL in known and PRINTER_IP in known and "printer.example.com" in known
    registry.upsert(Printer("plainname", "Bench", "O1D", "printer-in-shed", "12345678", True))
    assert "printer-in-shed" in redact.known_values()
    assert "printer-in-shed" not in redact.text("cannot reach printer-in-shed")


def test_known_values_survive_a_broken_config(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: 1 / 0)
    assert isinstance(redact.known_values(), list)


# ---------- the mode presets ----------

def test_a_mode_needs_the_code_and_applies_like_modules_set(app, env):  # noqa: F811
    c = client(app)
    assert post(c, "modules/mode", {"mode": "all-in-one"}, code=None).status_code == 403
    assert post(c, "modules/mode", {"mode": "all-in-one"}, code="00000000").status_code == 403
    assert not env
    r = post(c, "modules/mode", {"mode": "all-in-one"}).json()
    assert r["changed"] is True and env == [True]
    cfg = config.load()
    assert modules.mode_of(modules.enabled(cfg)) == "all-in-one" and cfg["station"]["url"] == "http://127.0.0.1:5003"


def test_a_mode_as_it_is_changes_nothing(app, env):  # noqa: F811
    r = post(client(app), "modules/mode", {"mode": "server"}).json()
    assert r["changed"] is False and not env


def test_the_page_will_not_set_a_mode_without_the_server(app, env):  # noqa: F811
    c = client(app)
    r = post(c, "modules/mode", {"mode": "station"})
    assert r.status_code == 409 and "modules set station" in r.json()["error"]
    assert "server" in modules.enabled(config.load()) and not env
    p = c.get("/setup/api/modules/preview?mode=station").json()
    assert p["refused"] and "modules set station" in p["refused"]


@pytest.mark.parametrize("mode", ["", "nope", None, 3])
def test_an_unknown_mode_is_refused(app, mode):
    assert post(client(app), "modules/mode", {"mode": mode}).status_code == 400


def test_one_job_at_a_time_holds_for_a_mode(app, env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(setup_helper, "_applying", lambda: True)
    assert post(client(app), "modules/mode", {"mode": "all-in-one"}).status_code == 409
    assert modules.mode_of(modules.enabled(config.load())) == "server" and not env


def test_mode_preview_says_what_goes_and_comes_and_changes_nothing(app):
    c = client(app)
    before = (config.paths().etc / "config.json").read_bytes()
    p = c.get("/setup/api/modules/preview?mode=all-in-one").json()
    assert p["refused"] is None and "station" in p["after"] and "Turns on: station" in p["notes"]
    assert (config.paths().etc / "config.json").read_bytes() == before
    assert c.get("/setup/api/modules/preview?mode=nope").status_code == 400


def test_a_mode_keeps_a_module_switched_on_by_hand_and_asks_for_what_it_needs(app):
    c = client(app)
    cfg = config.load()
    cfg["modules"]["web"] = True
    cfg["web"] = {**cfg["web"], "public_url": None}
    config.save(cfg)
    r = post(c, "modules/mode", {"mode": "all-in-one"})
    assert r.status_code == 400 and r.json()["needs"] == ["web.public_url"]
    p = c.get("/setup/api/modules/preview?mode=all-in-one").json()
    assert [n["key"] for n in p["needs"]] == ["web.public_url"]
    r = post(c, "modules/mode", {"mode": "all-in-one", "settings": {"web.public_url": PUBLIC}})
    assert r.status_code == 200, r.text
    assert config.load()["web"]["public_url"] == PUBLIC and "web" in modules.enabled(config.load())


def test_state_lists_the_modes_and_which_this_page_can_set(app):
    st = client(app).get("/setup/api/state").json()
    assert {m["name"]: m["here"] for m in st["modes"]} == {"server": True, "station": False, "all-in-one": True}
    assert st["version"]


# ---------- Updates ----------

class Fetcher:
    def __init__(self, latest="0.6.0", notes="New things.", mine="## Going back\nDrop the thing.\n## Other\nx"):
        self.latest, self.notes, self.mine, self.asked = latest, notes, mine, []

    def release(self, repo, version=None):
        self.asked.append(version)
        if version is None:
            return {"version": self.latest, "assets": {}, "notes": self.notes}
        if self.mine is None:
            raise updates.ReleaseError("no such release")
        return {"version": version, "assets": {}, "notes": self.mine}


def test_check_info_returns_what_the_cli_prints_and_saves_it_for_the_page(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(updates, "current_version", lambda: "0.5.0")
    info = updates.check_info(config.load(), fetcher=Fetcher(), now=100.0)
    assert info == {"installed": "0.5.0", "latest": "0.6.0", "newer": True, "held": None, "notes": "New things.",
                    "going_back": "## Going back\nDrop the thing."}
    v = updates.view(config.load())
    assert (v["installed"], v["latest"], v["newer"], v["checked_at"]) == ("0.5.0", "0.6.0", True, 100.0)
    assert v["notes"] == "New things." and v["going_back"].endswith("Drop the thing.")


def test_a_release_without_its_own_notes_still_checks(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(updates, "current_version", lambda: "0.5.0")
    assert updates.check_info(config.load(), fetcher=Fetcher(mine=None))["going_back"] == ""


def test_check_as_a_plain_user_still_answers(env, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr(updates, "current_version", lambda: "0.5.0")

    def denied(**k):
        raise PermissionError("no")
    monkeypatch.setattr(updates, "_write_state", denied)
    assert updates.check(config.load(), fetcher=Fetcher()) == 0
    assert "0.6.0 is available" in capsys.readouterr().out


@pytest.mark.parametrize("notes,want", [
    ("intro\n\n**Going back to 0.3.0.** Do this.\nand that\n\n## Next\nno", "**Going back to 0.3.0.** Do this.\nand that"),
    ("# Going back\nx\n# After\ny", "# Going back\nx"), ("nothing here", ""), ("", "")])
def test_going_back_section(notes, want):
    assert updates.going_back(notes) == want


def test_updates_route_reads_no_network_and_says_what_would_be_refused(app, monkeypatch):
    monkeypatch.setattr(updates, "default_fetcher", lambda cfg: pytest.fail("reached for the network"))
    monkeypatch.setattr(updates, "printers_idle", _busy)
    r = client(app).get("/setup/api/updates")
    assert r.status_code == 200 and SERIAL not in r.text
    v = r.json()
    assert v["latest"] is None and v["newer"] is False and v["update_refused"] == updates.BUSY_TEXT


def test_a_kept_version_is_offered_and_one_that_fails_its_check_is_not(app, monkeypatch):
    updates._write_state(previous="0.3.0")
    monkeypatch.setattr(updates, "_kept", lambda v: True)
    v = client(app).get("/setup/api/updates").json()
    assert v["previous"] == "0.3.0" and v["rollback_refused"] is None
    monkeypatch.setattr(updates, "_kept", lambda v: False)
    v = updates.view(config.load())
    assert v["previous"] is None


def test_the_page_sees_a_finished_check_at_once(app, monkeypatch):
    c = client(app)
    assert c.get("/setup/api/updates").json()["latest"] is None
    updates._write_state(latest={"version": "9.9.9", "notes": "", "going_back": "", "at": 1.0})
    write_log(setup_helper.header("check") + "\n\n==> finished (exit 0)\n")
    assert c.get("/setup/api/updates").json()["latest"] == "9.9.9"


def test_fetcher_release_carries_the_notes():
    doc = {"tag_name": "v1.2.3", "assets": [], "body": "Notes."}

    class Resp:
        def read(self, n):
            return json.dumps(doc).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, req, timeout=None):
            return Resp()
    assert release.Fetcher(opener=Opener()).release()["notes"] == "Notes."
    doc["body"] = None
    assert release.Fetcher(opener=Opener()).release()["notes"] == ""


def test_a_missing_release_points_at_the_version_not_a_token():
    import io
    import urllib.error

    class Opener:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO())
    with pytest.raises(release.ReleaseError) as e:
        release.Fetcher(opener=Opener()).release(version="9.9.9")
    assert "check the version number" in str(e.value) and "token" not in str(e.value)
    assert "private repo needs" not in (ROOT / "get.sh").read_text(encoding="utf-8")


# ---------- the units and the page's files ----------

def test_the_job_unit_is_nothing_an_update_stops():
    cfg = {"modules": {n: True for n in modules.MODULES}}
    services, others = updates._units(cfg)
    assert setup_helper.JOB_UNIT not in services + others and setup_helper.APPLY_UNIT not in services + others
    assert setup_helper.JOB_UNIT not in [u for m in modules.MODULES.values() for u in m.units]


def test_the_job_unit_as_shipped():
    run = (SYSTEMD / setup_helper.JOB_UNIT).read_text(encoding="utf-8")
    assert "setup_helper job-run" in run and "Type=oneshot" in run and "PartOf" not in run
    timeout = int(re.search(r"TimeoutStartSec=(\d+)min", run).group(1)) * 60
    assert jobs.STALE_AFTER > timeout
    assert setup_helper.JOB_UNIT in (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")


def test_the_helper_may_write_only_the_jobs_folder_beyond_etc():
    svc = (SYSTEMD / "filament-kit-setup@.service").read_text(encoding="utf-8")
    assert re.findall(r"^ReadWritePaths=(.*)$", svc, re.M) == ["/etc/filament-kit", "-/run/filament-kit-setup"]


def test_the_server_unit_was_not_widened():
    """Check now is a job because the server may not reach GitHub: this must not change to make it easier."""
    svc = (SYSTEMD / "filament-kit.service").read_text(encoding="utf-8")
    assert "IPAddressAllow=localhost 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 160.79.104.0/21 2607:6bc0::/48" in svc


def test_the_page_loads_both_scripts_under_its_csp(app):
    c = client(app)
    page = c.get("/setup")
    assert "/setup/setup.js" in page.text and "/setup/setup_tabs.js" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    r = c.get("/setup/setup_tabs.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert client(app, who=("203.0.113.9", 50000)).get("/setup/setup_tabs.js").status_code == 403


def test_the_tab_script_never_uses_innerhtml_or_talks_elsewhere():
    lines = (STATIC / "setup_tabs.js").read_text(encoding="utf-8").splitlines()
    src = " ".join(ln for ln in lines if not ln.lstrip().startswith("//"))
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|fetch\(", src)
    assert "localStorage" not in src and "sessionStorage" not in src


def test_the_scripts_never_hand_a_null_to_replacechildren():
    """It prints "null" on the page. `fill` and h() skip it."""
    for name in ("setup.js", "setup_tabs.js"):
        src = (STATIC / name).read_text(encoding="utf-8")
        for m in re.finditer(r"\.replaceChildren\(", src):
            depth, i = 1, m.end()
            while depth and i < len(src):
                depth += {"(": 1, ")": -1}.get(src[i], 0)
                i += 1
            top, before = src[m.end():i - 1], None
            while top != before:        # what is inside an h(...) call is h()'s to skip
                top, before = re.sub(r"\([^()]*\)|\{[^{}]*\}", "", top), top
            assert ": null" not in top, (name, src[m.start():m.start() + 80])


def test_every_tab_the_shell_lists_has_its_view():
    src = (STATIC / "setup.js").read_text(encoding="utf-8")
    tabs = (STATIC / "setup_tabs.js").read_text(encoding="utf-8")
    block = src[src.index("const TABS = {"):src.index("const tabNow")]
    assert re.findall(r"^  (\w+): \[", block, re.M) == ["overview", "modules", "printers", "devices", "settings", "updates"]
    for fn in re.findall(r"(\w+(?:Card|Tab))\(\)", block):
        assert f"function {fn}(" in src + tabs, fn


def test_the_klipper_hint_no_longer_promises_an_app_screen():
    assert "or in the app" not in (STATIC / "setup.js").read_text(encoding="utf-8")


def test_a_rollback_target_older_than_the_job_unit_finds_what_it_needs():
    """0.4.0's own install puts back the unit it uses; ours stays on disk unused, and the name it knew still works."""
    assert (SYSTEMD / setup_helper.APPLY_UNIT).exists()
    assert "setup_helper apply-run" in (SYSTEMD / setup_helper.APPLY_UNIT).read_text(encoding="utf-8")


def test_helper_ops_are_the_closed_list():
    assert set(setup_helper.OPS) == {"check", "key_set", "key_remove", "passphrase_set", "library_token_set",
                                     "library_token_remove", "module", "setting", "apply", "mode", "job"}
    assert set(setup_helper.JOBS) == {"apply", "update", "rollback", "check"}
    assert HOME and H     # the shared fixtures' constants are the ones in use
