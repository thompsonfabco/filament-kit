"""Linux: is Bambu Studio / Orca Slicer running, read from a fake /proc. When unsure the answer is "running"
(a wrong "not running" could install presets under an open slicer)."""
from pathlib import Path

import pytest

from fksync import studio


def _proc(tmp_path, procs: dict[int, tuple[str, list[str]]]) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    (proc / "self").mkdir(exist_ok=True)       # non-numeric entries are skipped
    (proc / "meminfo").write_text("x")
    for pid, (comm, argv) in procs.items():
        d = proc / str(pid)
        d.mkdir()
        (d / "comm").write_text(comm + "\n")
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + (b"\0" if argv else b""))
    return proc


def _both(proc):
    return studio.running(proc=proc), studio.orca_running(proc=proc)


def test_nothing_running(tmp_path):
    proc = _proc(tmp_path, {1: ("systemd", ["/sbin/init"]), 77: ("bash", ["-bash"]),
                            78: ("vim", ["vim", "/home/u/.config/BambuStudio/BambuStudio.conf"]),
                            79: ("filament-kit-sy", ["/home/u/.local/bin/filament-kit-sync", "run", "--quiet"])})
    assert _both(proc) == (False, False)


@pytest.mark.parametrize("comm, argv, want", [
    ("bambu-studio", ["/usr/bin/bambu-studio"], (True, False)),                       # native / FHS
    ("bambu-studio", ["/app/bin/bambu-studio", "--some-arg"], (True, False)),         # inside the Flatpak sandbox
    ("BambuStudio_ub", ["/home/u/Apps/BambuStudio_ubu24-v02.09.01.70.AppImage"], (True, False)),  # AppImage runtime
    ("orca-slicer", ["/app/bin/orca-slicer"], (False, True)),
    ("OrcaSlicer_Linu", ["/home/u/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"], (False, True)),
    ("OrcaSlicer", ["./OrcaSlicer"], (False, True)),
    ("flatpak", ["flatpak", "run", "com.bambulab.BambuStudio"], (True, False)),
    ("flatpak", ["/usr/bin/flatpak", "run", "--branch=stable", "io.github.softfever.OrcaSlicer"], (False, True)),
    ("flatpak", ["flatpak", "run", "com.orcaslicer.OrcaSlicer//stable"], (False, True)),
])
def test_found(tmp_path, comm, argv, want):
    assert _both(_proc(tmp_path, {4242: (comm, argv)})) == want


def test_appimage_apprun_told_apart_by_its_mount(tmp_path):
    """Both AppImage scripts rename the app to AppRun and put <app key>.png next to it."""
    orca_mount = tmp_path / "tmp" / ".mount_OrcaSlAbCdEf"
    orca_mount.mkdir(parents=True)
    (orca_mount / "OrcaSlicer.png").write_bytes(b"")
    other = tmp_path / "tmp" / ".mount_CuraXyZ123"
    other.mkdir()
    (other / "cura.png").write_bytes(b"")
    proc = _proc(tmp_path, {10: ("AppRun", [str(orca_mount / "AppRun")]), 11: ("AppRun", [str(other / "AppRun")])})
    assert _both(proc) == (False, True)
    bambu_mount = tmp_path / "tmp" / ".mount_BambuSXyZ"
    bambu_mount.mkdir()
    (bambu_mount / "BambuStudio.png").write_bytes(b"")
    (proc / "12").mkdir()
    (proc / "12" / "comm").write_text("AppRun\n")
    (proc / "12" / "cmdline").write_bytes(str(bambu_mount / "AppRun").encode() + b"\0")
    assert _both(proc) == (True, True)


def test_apprun_whose_mount_cannot_be_read_counts_as_running(tmp_path):
    proc = _proc(tmp_path, {10: ("AppRun", [str(tmp_path / "gone" / ".mount_OrcaSl1" / "AppRun")])})
    assert _both(proc) == (True, True)


def test_unsure_is_running(tmp_path):
    assert _both(tmp_path / "no-proc") == (True, True)          # no /proc at all
    proc = _proc(tmp_path, {})
    assert _both(proc) == (False, False)
    (proc / "55").mkdir()                                        # a process that vanished mid-read: skipped
    assert _both(proc) == (False, False)


def test_unsure_is_running_for_a_present_process_that_cannot_be_read(tmp_path, monkeypatch):
    proc = _proc(tmp_path, {7: ("bash", ["-bash"])})
    assert _both(proc) == (False, False)
    real = Path.read_bytes

    def denied(self):
        if self.name == "cmdline":
            raise PermissionError(13, "Permission denied")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", denied)
    assert _both(proc) == (True, True)


def test_platform_choice(monkeypatch, tmp_path):
    proc = _proc(tmp_path, {9: ("bambu-studio", ["bambu-studio"])})
    monkeypatch.setattr(studio, "PROC", proc)
    monkeypatch.setattr(studio.sys, "platform", "linux")
    assert studio.running() is True and studio.orca_running() is False
    monkeypatch.setattr(studio.sys, "platform", "darwin")         # not supported: never claims running
    assert studio.running() is False
    # a tasklist given (the Windows tests) is still read on any platform
    assert studio.running(lambda: '"bambu-studio.exe","1"') is True


def test_other_users_processes_are_skipped(tmp_path, monkeypatch):
    """M2: another user's slicer writes only their own folders; only this user's processes count."""
    proc = _proc(tmp_path, {4242: ("orca-slicer", ["/usr/bin/orca-slicer"])})
    owner = (proc / "4242").stat().st_uid
    monkeypatch.setattr(studio.os, "getuid", lambda: owner, raising=False)
    assert studio.orca_running(proc=proc) is True
    monkeypatch.setattr(studio.os, "getuid", lambda: owner + 1, raising=False)
    assert studio.orca_running(proc=proc) is False
