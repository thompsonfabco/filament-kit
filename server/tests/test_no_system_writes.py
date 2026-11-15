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


ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.mark.real_system_paths("the guard's own test of the opt-out")
@pytest.mark.skipif(not ROOT, reason="the opt-out is for root tests")
def test_a_marked_root_test_may_write_its_real_path(system_writes):
    folder = Path(f"/etc/fk-guard-optout-{os.getpid()}")
    folder.mkdir()
    try:
        (folder / "x").write_bytes(b"x")
    finally:
        (folder / "x").unlink()
        folder.rmdir()
    assert system_writes == []


@pytest.mark.skipif(ROOT, reason="as root the marker is honoured")
def test_the_marker_fails_a_test_that_is_not_root(tmp_path):
    import subprocess
    import sys
    tests_dir = Path(__file__).resolve().parent
    (tmp_path / "test_marked.py").write_text(
        "import pytest\n\n@pytest.mark.real_system_paths('x')\ndef test_it():\n    pass\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "-q", "--rootdir",
                        str(tmp_path), str(tmp_path / "test_marked.py")], cwd=tmp_path, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(tests_dir) + os.pathsep + str(tests_dir.parent)})
    assert r.returncode != 0 and "real_system_paths is for tests that run as root" in r.stdout + r.stderr, r.stdout
