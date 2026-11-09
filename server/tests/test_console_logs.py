"""The setup console's Logs tab and the helper's journal op: a closed list of units, an argument list, the code first."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_setup_page import CODE, Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, config, setup_helper

STATIC = Path(cli.__file__).parent / "setup_static"


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Mgr())


@pytest.fixture
def journal(env, monkeypatch):  # noqa: F811
    """journalctl stands in: records its arguments, and setup_helper thinks systemd is here."""
    monkeypatch.delenv("FK_NO_SYSTEMD")
    calls = []
    out = {"stdout": "line one\nline two\n", "rc": 0}

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, out["rc"], stdout=out["stdout"].encode(), stderr=b"oops")
    monkeypatch.setattr(setup_helper.subprocess, "run", run)
    return calls, out


def test_the_units_are_the_services_of_the_modules_that_are_on(app):
    units = client(app).get("/setup/api/logs/units").json()["units"]
    assert "filament-kit.service" in units and "spoolman.service" in units
    assert all(u.endswith(".service") and "@" not in u for u in units)
    cfg = config.load()
    cfg["modules"]["spoolman"] = False
    config.save(cfg)
    assert "spoolman.service" not in setup_helper.journal_units(config.load())


def test_reading_needs_the_code(app, journal):
    calls, _ = journal
    body = {"unit": "filament-kit.service"}
    assert post(client(app), "logs", body, code=None).status_code in (401, 403)
    assert post(client(app), "logs", body, code="0000-0000").status_code == 403
    assert calls == []


def test_it_runs_journalctl_with_an_argument_list(app, journal):
    calls, _ = journal
    r = post(client(app), "logs", {"unit": "filament-kit.service", "lines": 50})
    assert r.status_code == 200
    assert r.json() == {"unit": "filament-kit.service", "text": "line one\nline two\n", "truncated": False}
    cmd, kw = calls[0]
    assert cmd == ["journalctl", "-u", "filament-kit.service", "-n", "50", "-o", "short-iso", "--no-pager"]
    assert not kw.get("shell") and kw["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("unit", ["ssh.service", "filament-kit.service; rm -rf /", "../x", "-f", "", 5, None,
                                  "filament-kit-setup@.service"])
def test_any_other_unit_is_refused(app, journal, unit):
    calls, _ = journal
    assert post(client(app), "logs", {"unit": unit}).status_code == 400
    assert calls == []


def test_a_unit_of_a_module_that_is_off_is_refused(app, journal):
    calls, _ = journal
    cfg = config.load()
    cfg["modules"]["spoolman"] = False
    config.save(cfg)
    assert post(client(app), "logs", {"unit": "spoolman.service"}).status_code == 400
    assert calls == []


@pytest.mark.parametrize("lines", [0, -1, 201, "50", 1.5, True, None])
def test_lines_is_a_number_up_to_200(app, journal, lines):
    calls, _ = journal
    assert post(client(app), "logs", {"unit": "filament-kit.service", "lines": lines}).status_code == 400
    assert calls == []


def test_long_output_keeps_its_end_on_a_whole_line(app, journal):
    _, out = journal
    out["stdout"] = "".join(f"line {i:06d}\n" for i in range(20000))     # 240 KB
    r = post(client(app), "logs", {"unit": "filament-kit.service"}).json()
    assert r["truncated"] is True and len(r["text"]) <= setup_helper.JOURNAL_MAX
    assert r["text"].startswith("line ") and r["text"].endswith("line 019999\n")


def test_a_failed_read_says_so_with_no_journal_text(app, journal):
    _, out = journal
    out.update(stdout="", rc=1)
    r = post(client(app), "logs", {"unit": "filament-kit.service"})
    assert r.status_code == 500 and "oops" not in r.text


def test_bad_bytes_do_not_break_the_reply(app, journal, monkeypatch):
    monkeypatch.setattr(setup_helper.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=b"ok \xff\xfe end\n", stderr=b""))
    assert "ok" in post(client(app), "logs", {"unit": "filament-kit.service"}).json()["text"]


def test_with_no_systemd_there_is_nothing_to_read(app):
    r = post(client(app), "logs", {"unit": "filament-kit.service"})
    assert r.status_code == 200 and r.json()["text"] == ""


def test_the_page_has_the_tab():
    assert 'logs: ["Logs", () => logsTab()]' in (STATIC / "setup.js").read_text(encoding="utf-8")
    src = (STATIC / "setup_logs.js").read_text(encoding="utf-8")
    assert 'api("logs/units")' in src and "code: codeIn.value" in src and "innerHTML" not in src
    assert CODE
