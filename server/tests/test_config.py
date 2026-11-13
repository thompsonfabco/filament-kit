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
    assert stat.S_IMODE((etc / "config.json").stat().st_mode) == 0o640


def test_save_leaves_no_tmp_and_roundtrips(etc):
    config.save({"port": 1234})
    assert not list(etc.glob("*.tmp"))
    assert config.load()["port"] == 1234


def test_two_saves_at_once_each_write_their_own_temp_file(etc, monkeypatch):
    real = config.grant_web_read
    nested = []

    def grant(path):
        if not nested:      # the first save is between its write and its rename: a second one runs whole
            nested.append(1)
            config.save({"port": 2222})
        real(path)
    monkeypatch.setattr(config, "grant_web_read", grant)
    config.save({"port": 1111})
    assert not list(etc.glob("*.tmp"))
    assert json.loads((etc / "config.json").read_text(encoding="utf-8"))["port"] == 1111


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


def test_a_failed_write_keeps_the_old_file_and_leaves_no_tmp(etc, monkeypatch):
    config.save({"port": 1234})

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(config.os, "replace", boom)
    with pytest.raises(OSError):
        config.save({"port": 9999})
    monkeypatch.undo()
    assert not list(etc.glob("*.tmp"))
    assert json.loads((etc / "config.json").read_text())["port"] == 1234


def test_a_corrupt_config_file_is_an_error_not_silently_the_defaults(etc):
    (etc / "config.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        config.load()


def test_paths_web_follows_the_state_folder_unless_told(monkeypatch, tmp_path):
    monkeypatch.delenv("FK_WEB_STATE", raising=False)
    monkeypatch.delenv("FK_STATE", raising=False)
    assert str(config.paths().web).replace("\\", "/") == "/var/lib/filament-kit-web"
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    assert config.paths().web == tmp_path / "state-web"
    monkeypatch.setenv("FK_WEB_STATE", str(tmp_path / "elsewhere"))
    assert config.paths().web == tmp_path / "elsewhere"
