import json
import os
import socket
import stat

import pytest

from filament_kit import config


@pytest.fixture
def etc(tmp_path, monkeypatch):
    d = tmp_path / "etc"
    d.mkdir()
    monkeypatch.setenv("FK_ETC", str(d))
    return d


def test_defaults_when_no_file(etc):
    expected = dict(config.DEFAULTS)
    expected["server_name"] = socket.gethostname()
    assert config.load() == expected
    assert config.DEFAULTS["port"] == 8710
    assert config.DEFAULTS["model"] == "claude-opus-5-5"


def test_file_overrides_and_nested_merge(etc):
    (etc / "config.json").write_text(json.dumps({"placement": {"box_count": 12}, "port": 9000}))
    cfg = config.load()
    assert cfg["port"] == 9000
    assert cfg["placement"]["box_count"] == 12
    assert cfg["placement"]["pla_location"] == "Rack 1"
    assert cfg["placement"]["box_prefix"] == "Storage box "


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_save_is_atomic_and_640(etc):
    config.save({"port": 1234})
    assert not list(etc.glob("*.tmp"))
    assert stat.S_IMODE((etc / "config.json").stat().st_mode) == 0o640
    assert config.load()["port"] == 1234


def test_save_leaves_no_tmp_and_roundtrips(etc):
    config.save({"port": 1234})
    assert not list(etc.glob("*.tmp"))
    assert config.load()["port"] == 1234


def test_unknown_keys_kept(etc):
    config.save({"future_key": {"a": 1}})
    assert config.load()["future_key"] == {"a": 1}


def test_paths_env_and_defaults(monkeypatch):
    for v in ("FK_ETC", "FK_STATE", "FK_BACKUPS", "FK_OPT"):
        monkeypatch.delenv(v, raising=False)
    p = config.paths()
    assert (str(p.etc).replace("\\", "/"), str(p.state).replace("\\", "/"), str(p.backups).replace("\\", "/"), str(p.opt).replace("\\", "/")) == (
        "/etc/filament-kit", "/var/lib/filament-kit", "/var/backups/filament-kit", "/opt/filament-kit")
    monkeypatch.setenv("FK_STATE", "/x")
    assert str(config.paths().state).replace("\\", "/") == "/x"
