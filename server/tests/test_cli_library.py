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
    """Records `builds.request_rebuild` calls instead of writing the request file."""
    from filament_kit.profiles import builds
    calls = []
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None: calls.append(reason))
    return calls


def _stdin(monkeypatch, data: bytes):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


LOCAL = {"vendor": "SUNLU", "product": "PLA+ 2.0", "material": "PLA",
         "fields": {"nozzle_temperature_range_low": ["210"], "nozzle_temperature_range_high": ["230"]}}


def test_status_bundled(capsys):
    assert cli.main(["library", "status"]) == 0
    out = capsys.readouterr().out
    assert f"library version {library.load().version} (updated), 0 local additions" in out
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
    assert "404" in err and "not found" in err and f"using version {library.load().version}" in err
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


def test_rollback_nothing(capsys, no_library):
    assert cli.main(["library", "rollback"]) == 1
    assert "error" in capsys.readouterr().err


def test_rollback_ok(capsys, monkeypatch, rebuilds):
    monkeypatch.setattr(library, "rollback", lambda: 3)
    assert cli.main(["library", "rollback"]) == 0
    assert "library version 3" in capsys.readouterr().out
    assert len(rebuilds) == 1


def test_rollback_says_scheduled_updates_skip_it(capsys, monkeypatch, rebuilds):
    monkeypatch.setattr(library, "rollback", lambda: 3)
    monkeypatch.setattr(library, "rolled_back_from", lambda: 4)
    assert cli.main(["library", "rollback"]) == 0
    assert "skip version 4" in capsys.readouterr().out


def test_scheduled_update_held_after_rollback(capsys, monkeypatch, rebuilds):
    monkeypatch.setattr(library, "due", lambda cfg, now: True)
    monkeypatch.setattr(library, "update", lambda url=None, **k: library.UpdateResult(
        False, 3, 0, None, held_from=4 if k.get("scheduled") else None))
    assert cli.main(["library", "update", "--scheduled"]) == 0
    assert "rolled back" in capsys.readouterr().out
    assert rebuilds == []


# ---------- fix round 1 ----------

def _404_update(monkeypatch):
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
    real = library.update
    monkeypatch.setattr(library, "update", lambda url=None, **k: real(url, opener=opener, **k))


def test_scheduled_404_is_a_warning(capsys, monkeypatch, rebuilds):
    _404_update(monkeypatch)
    assert cli.main(["library", "update", "--scheduled"]) == 0
    err = capsys.readouterr().err
    assert err.startswith("warning: ") and "404" in err and "not found" in err
    assert rebuilds == []


def test_manual_404_fails(capsys, monkeypatch):
    _404_update(monkeypatch)
    assert cli.main(["library", "update"]) == 1
    assert "warning" not in capsys.readouterr().err


def test_scheduled_500_fails(capsys, monkeypatch):
    monkeypatch.setattr(library, "update",
                        lambda url=None, **k: library.UpdateResult(False, 2, 0, "index.json: HTTP 500", 500))
    assert cli.main(["library", "update", "--scheduled"]) == 1


def test_scheduled_404_detected_by_status_not_text(capsys, monkeypatch):
    monkeypatch.setattr(library, "update", lambda url=None, **k: library.UpdateResult(
        False, 2, 0, "x: HTTP 404; not found: check the library address and version; using version 2", None))
    assert cli.main(["library", "update", "--scheduled"]) == 1


class _Recorder:
    def __init__(self, size):
        self.size = size
        self.asked = []

    def read(self, n=-1):
        self.asked.append(n)
        return b"{" * (self.size if n < 0 else min(n, self.size))


def test_add_stdin_reads_at_most_the_limit(capsys, monkeypatch):
    buf = _Recorder(10 * 2**20)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=buf))
    assert cli.main(["library", "add", "-"]) == 1
    assert buf.asked == [library.LOCAL_LIMIT + 1]
    assert "larger than 256 KiB" in capsys.readouterr().err


def test_add_file_too_large(tmp_path, capsys):
    f = tmp_path / "big.json"
    f.write_bytes(b" " * (library.LOCAL_LIMIT + 1))
    assert cli.main(["library", "add", str(f)]) == 1
    assert "larger than 256 KiB" in capsys.readouterr().err
    assert library.load().local_count == 0


def test_status_prints_sanitized_url(capsys):
    cfg = config.load()
    cfg["library"]["url"] = "https://user:pw@mirror.example/lib/?token=s3cret#frag"
    config.save(cfg)
    assert cli.main(["library", "status"]) == 0
    out = capsys.readouterr().out
    assert "url: https://mirror.example/lib/\n" in out
    assert "s3cret" not in out and "pw@" not in out and "frag" not in out
