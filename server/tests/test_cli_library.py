import io
import json
import sys
import types
import urllib.error

import pytest

from filament_kit import cli, config, library


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    (tmp_path / "etc").mkdir()
    (tmp_path / "state").mkdir()
    return tmp_path


@pytest.fixture
def rebuilds(monkeypatch):
    """A stand-in for Task 6's filament_kit.profiles.builds; records request_rebuild calls."""
    calls = []
    mod = types.ModuleType("filament_kit.profiles.builds")
    mod.request_rebuild = calls.append
    monkeypatch.setitem(sys.modules, "filament_kit.profiles.builds", mod)
    return calls


def _stdin(monkeypatch, data: bytes):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


LOCAL = {"vendor": "SUNLU", "product": "PLA+ 2.0", "material": "PLA",
         "fields": {"nozzle_temperature_range_low": ["210"], "nozzle_temperature_range_high": ["230"]}}


def test_status_bundled(capsys):
    assert cli.main(["library", "status"]) == 0
    out = capsys.readouterr().out
    assert "library version 2 (bundled), 0 local additions" in out
    assert library.DEFAULT_LIBRARY_URL in out
    assert "last check: never" in out


def test_add_from_stdin(capsys, monkeypatch, rebuilds):
    _stdin(monkeypatch, json.dumps(LOCAL).encode())
    assert cli.main(["library", "add", "-"]) == 0
    out = capsys.readouterr().out
    assert "sunlu--pla-plus-2-0" in out
    assert library.load().local_count == 1
    assert len(rebuilds) == 1 and "sunlu--pla-plus-2-0" in rebuilds[0]
    assert cli.main(["library", "status"]) == 0
    assert "1 local addition" in capsys.readouterr().out


def test_add_from_file(tmp_path, capsys):
    f = tmp_path / "e.json"
    f.write_text(json.dumps(LOCAL), encoding="utf-8")
    assert cli.main(["library", "add", str(f)]) == 0      # no profiles.builds yet: the rebuild is skipped
    assert library.load().local_count == 1


def test_add_invalid_lists_problems(capsys, monkeypatch, rebuilds):
    _stdin(monkeypatch, json.dumps(dict(LOCAL, material="", fields={"temperature_vitrification": ["1"]})).encode())
    assert cli.main(["library", "add", "-"]) == 1
    err = capsys.readouterr().err
    assert "'material' must be a non-empty string" in err and "temperature_vitrification" in err
    assert rebuilds == []


def test_update_scheduled_off(capsys, monkeypatch):
    cfg = config.load()
    cfg["library"]["schedule"] = "off"
    config.save(cfg)
    monkeypatch.setattr(library, "update", lambda *a, **k: pytest.fail("must not update"))
    assert cli.main(["library", "update", "--scheduled"]) == 0
    assert "library updates are off" in capsys.readouterr().out


def test_update_scheduled_not_due(capsys, monkeypatch):
    monkeypatch.setattr(library, "due", lambda cfg, now: False)
    monkeypatch.setattr(library, "update", lambda *a, **k: pytest.fail("must not update"))
    assert cli.main(["library", "update", "--scheduled"]) == 0
    assert "not due" in capsys.readouterr().out


def test_update_error_exits_1_without_query(capsys, monkeypatch, rebuilds):
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
    real = library.update
    monkeypatch.setattr(library, "update", lambda url=None, **k: real(url, opener=opener, **k))
    cfg = config.load()
    cfg["library"]["url"] = "https://mirror.example/lib/"
    config.save(cfg)
    assert cli.main(["library", "update"]) == 1
    err = capsys.readouterr().err
    assert "404" in err and "may be private" in err and "using version 2" in err
    assert rebuilds == []


def test_update_bad_url_exits_1_without_query(capsys, rebuilds):
    cfg = config.load()
    cfg["library"]["url"] = "https://mirror.example/lib/?token=s3cret"
    config.save(cfg)
    assert cli.main(["library", "update"]) == 1
    captured = capsys.readouterr()
    assert "s3cret" not in captured.err + captured.out and "?" not in captured.err
    assert rebuilds == []


def test_update_changed_requests_rebuild(capsys, monkeypatch, rebuilds):
    monkeypatch.setattr(library, "update",
                        lambda url=None, **k: library.UpdateResult(True, 3, 1, None))
    assert cli.main(["library", "update"]) == 0
    assert "library version 3" in capsys.readouterr().out
    assert len(rebuilds) == 1


def test_update_unchanged_no_rebuild(capsys, monkeypatch, rebuilds):
    monkeypatch.setattr(library, "update",
                        lambda url=None, **k: library.UpdateResult(False, 2, 0, None))
    assert cli.main(["library", "update"]) == 0
    assert "up to date" in capsys.readouterr().out
    assert rebuilds == []


def test_rollback_nothing(capsys):
    assert cli.main(["library", "rollback"]) == 1
    assert "error" in capsys.readouterr().err


def test_rollback_ok(capsys, monkeypatch, rebuilds):
    monkeypatch.setattr(library, "rollback", lambda: 3)
    assert cli.main(["library", "rollback"]) == 0
    assert "library version 3" in capsys.readouterr().out
    assert len(rebuilds) == 1
