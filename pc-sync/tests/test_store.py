import os
import re
import sys

import pytest

from fksync import store

TOKEN = "fk_test_" + "q" * 40  # a made-up test value, not a real token


def test_appdirs_paths(tmp_path):
    d = store.AppDirs(tmp_path / "fks")
    for attr in ("config", "token", "log_file", "backups", "installed", "state", "lock"):
        assert getattr(d, attr).parent == tmp_path / "fks", attr
    assert d.log_file.name == "sync.log"


def test_token_roundtrip_not_plaintext_on_windows(tmp_path):
    d = store.AppDirs(tmp_path / "fks")
    assert store.load_token(d) is None
    store.save_token(d, TOKEN)
    raw = d.token.read_bytes()
    assert store.load_token(d) == TOKEN
    if sys.platform == "win32":
        assert TOKEN.encode() not in raw
        assert TOKEN.encode("utf-16-le") not in raw
    else:
        assert raw.decode() == TOKEN
        assert (d.token.stat().st_mode & 0o777) == 0o600
    store.save_token(d, TOKEN + "2")
    assert store.load_token(d) == TOKEN + "2"
    assert [p.name for p in d.token.parent.iterdir() if p.name.startswith(d.token.name + ".")] == []


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_token_needs_entropy_on_windows(tmp_path):
    d = store.AppDirs(tmp_path / "fks")
    store.save_token(d, TOKEN)
    with pytest.raises(OSError):
        store._dpapi_unprotect(d.token.read_bytes(), b"other-entropy")
    d.token.write_bytes(b"garbage")
    assert store.load_token(d) is None


def test_config_roundtrip(tmp_path):
    d = store.AppDirs(tmp_path / "fks")
    assert store.load_config(d) == {}
    cfg = {"server": "filament.localdomain:8443", "variant": "BambuStudio", "user_id": "default"}
    store.save_config(d, cfg)
    assert store.load_config(d) == cfg
    d.config.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load_config(d)


def test_log_rotates(tmp_path):
    d = store.AppDirs(tmp_path / "fks")
    store.log(d, "first")
    line = d.log_file.read_text(encoding="utf-8")
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d first\n", line)
    with open(d.log_file, "a", encoding="utf-8") as f:
        f.write("x" * (1024 * 1024 + 10) + "\n")
    store.log(d, "after")
    rotated = d.log_file.with_name("sync.log.1")
    assert rotated.exists()
    assert rotated.stat().st_size > 1024 * 1024
    assert d.log_file.read_text(encoding="utf-8").endswith(" after\n")
    assert d.log_file.stat().st_size < 1024


def test_single_instance(tmp_path):
    d = store.AppDirs(tmp_path / "fks")
    with store.single_instance(d):
        with pytest.raises(store.AlreadyRunning):
            with store.single_instance(d):
                pass
    with store.single_instance(d):  # released after the first one ended
        pass
