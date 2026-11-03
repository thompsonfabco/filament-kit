# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.11.1, onedir: two executables that share one folder (one COLLECT).
#   filament-kit-sync.exe       console: pair / status / run / unpair
#   filament-kit-sync-task.exe  windowed: `run --quiet`, started by Task Scheduler (no console window)
# On Linux only the first is built (filament-kit-sync; the systemd user timer runs `run --quiet` itself);
# pc-sync/linux/build.sh packs it with install.sh / uninstall.sh.
# Build:  pyinstaller --noconfirm pc-sync/fksync.spec   ->  dist/filament-kit-sync/
# pc-sync runtime is stdlib only; UPX is off (packed exes trip antivirus heuristics).
import os
import sys

HERE = SPECPATH  # noqa: F821 - defined by PyInstaller
PKG = os.path.join(HERE, "fksync")
EXCLUDES = ["tkinter", "unittest", "pydoc", "test", "pytest", "cryptography"]


def _analysis(script):
    return Analysis(  # noqa: F821
        [os.path.join(PKG, script)],
        pathex=[HERE],
        binaries=[],
        datas=[],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
        optimize=0,
    )


def _exe(a, name, console):
    return EXE(  # noqa: F821
        PYZ(a.pure),  # noqa: F821
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=True,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


cli = _analysis("__main__.py")
cli_exe = _exe(cli, "filament-kit-sync", console=True)
parts = [cli_exe, cli.binaries, cli.datas]
if sys.platform == "win32":
    task = _analysis("task_entry.py")
    task_exe = _exe(task, "filament-kit-sync-task", console=False)
    parts += [task_exe, task.binaries, task.datas]

coll = COLLECT(  # noqa: F821
    *parts,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="filament-kit-sync",
)
