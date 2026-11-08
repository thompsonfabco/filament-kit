"""fk_spool_check.py: only safe characters reach gcode, cancel goes through Moonraker with checked replies (review
2026-11-08 A2/A3). The macro side is run on real Klipper by tools/e2e/klipper.sh."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fk_spool_check.py"


@pytest.fixture
def sc(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("fk_spool_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOG", str(tmp_path / "fk_spool_check.log"))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def _spool(vendor, material, name):
    return {"filament": {"material": material, "name": name, "vendor": {"name": vendor}}}


def _fake_get(sc, monkeypatch, spool):
    def get_json(url):
        if url.endswith("/server/spoolman/spool_id"):
            return {"result": {"spool_id": 7}}
        if url.endswith("/server/config"):
            return {"result": {"config": {"spoolman": {"server": "http://sm:7912"}}}}
        assert url == "http://sm:7912/api/v1/spool/7", url
        return spool
    monkeypatch.setattr(sc, "get_json", get_json)


@pytest.mark.parametrize("raw", ['Silk #2 "x"; M112', "a\nM112", "Jayo's {x} *5", "$(reboot) `id`"])
def test_safe_never_lets_gcode_syntax_through(sc, raw):
    out = sc.safe(raw)
    assert not set(out) & set('"\'#;*{}\n\r$`')
    assert len(sc.safe("x" * 1000)) == 200


def test_cancel_mode_starts_the_detached_cancel_with_a_safe_message(sc, monkeypatch, capsys):
    _fake_get(sc, monkeypatch, _spool('Silk #2 "Co"', "PETG", "Red;\nM112"))
    started, real_start = [], sc.start_cancel
    monkeypatch.setattr(sc, "start_cancel", lambda msg: started.append(msg))
    assert sc.main(["cancel", "PLA", "Jayo_s"]) == 0
    out = capsys.readouterr().out
    assert "Spool mismatch" in out and "Cancelling" in out
    assert started and "M112" in started[0]          # the text may mention it ...
    popen = []
    monkeypatch.setattr(sc.subprocess, "Popen", lambda args, **kw: popen.append(args))
    real_start(started[0])
    assert popen[0][-2] == "--cancel" and not set(popen[0][-1]) & set('"#;\n')   # ... but never as gcode


def test_warn_mode_never_cancels(sc, monkeypatch):
    _fake_get(sc, monkeypatch, _spool("SUNLU", "PETG", "Grey"))
    monkeypatch.setattr(sc, "start_cancel", lambda msg: pytest.fail("warn mode cancelled"))
    assert sc.main(["warn", "PLA", "_"]) == 0


def test_matching_spool_is_ok(sc, monkeypatch, capsys):
    _fake_get(sc, monkeypatch, _spool("SUNLU", "PLA", "PLA+ Grey"))
    monkeypatch.setattr(sc, "start_cancel", lambda msg: pytest.fail("cancelled a match"))
    assert sc.main(["cancel", "PLA", "SUNLU"]) == 0
    assert "Spool check OK" in capsys.readouterr().out


def test_cancel_posts_message_then_cancel_and_checks_the_reply(sc, monkeypatch):
    calls = []

    def post_json(path, body, timeout=120):
        calls.append((path, body))
        return {"result": "ok"}
    monkeypatch.setattr(sc, "post_json", post_json)
    assert sc.cancel('bad "name"; M112\nG28') == 0
    assert [c[0] for c in calls] == ["/printer/gcode/script", "/printer/print/cancel"]
    script = calls[0][1]["script"]
    assert script.startswith('_FK_SPOOL_MISMATCH MSG="') and script.count('"') == 2 and "\n" not in script
    assert ";" not in script


def test_a_failed_cancel_is_retried_and_logged(sc, monkeypatch):
    tries = []

    def post_json(path, body, timeout=120):
        if path == "/printer/print/cancel":
            tries.append(1)
            raise OSError("HTTP 400: no print")
        return {"result": "ok"}
    monkeypatch.setattr(sc, "post_json", post_json)
    assert sc.cancel("x", tries=3) == 1 and len(tries) == 3
    assert "cancel failed (try 3)" in Path(sc.LOG).read_text()


def test_main_cancel_entry(sc, monkeypatch):
    got = []
    monkeypatch.setattr(sc, "cancel", lambda msg: got.append(msg) or 0)
    assert sc.main(["--cancel", "Spool mismatch (type PLA vs PETG)"]) == 0 and got


def test_log_goes_to_printer_data_logs(tmp_path):
    dest = tmp_path / "printer_data" / "config" / "filament-kit" / "scripts"
    dest.mkdir(parents=True)
    (dest / SCRIPT.name).write_bytes(SCRIPT.read_bytes())
    spec = importlib.util.spec_from_file_location("fk_spool_check_installed", dest / SCRIPT.name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert Path(mod.LOG) == tmp_path / "printer_data" / "logs" / "fk_spool_check.log"
