"""The guard in conftest.py: a test writes nothing outside its temp dirs."""
import os
from pathlib import Path

import pytest

from filament_kit import apply


def test_a_planted_write_to_a_system_path_is_refused_and_recorded(system_writes):
    target = Path("/etc/filament-kit-guard-test/planted.conf")
    with pytest.raises(PermissionError):
        target.write_bytes(b"x")
    with pytest.raises(PermissionError):
        open("/etc/filament-kit-guard-test/planted2.conf", "w")
    with pytest.raises(PermissionError):
        os.mkdir("/var/lib/filament-kit-guard-test")
    with pytest.raises(PermissionError):
        os.replace(__file__, "/usr/local/filament-kit-guard-test")
    assert len(system_writes) == 4
    assert not target.parent.exists()
    system_writes.clear()           # planted on purpose: the guard's own check at the end must pass


def test_reading_a_system_path_is_not_a_write(system_writes):
    Path("/etc/filament-kit-no-such-file").exists()
    with pytest.raises(OSError):
        open("/etc/filament-kit-no-such-file")
    assert system_writes == []


def test_apply_defaults_to_a_temp_root(tmp_path):
    assert apply.execute.__kwdefaults__["root"] != Path("/")
    assert apply.refresh_station.__kwdefaults__["root"] != Path("/")
    text = "[Service]\nIPAddressAllow=localhost 10.0.0.0/8\n"
    apply.execute([apply.Action("spoolman_allow", text)], run=lambda cmd: None)
    root = apply.execute.__kwdefaults__["root"]
    assert (root / "etc/systemd/system/spoolman.service.d/kit.conf").read_text() == text
