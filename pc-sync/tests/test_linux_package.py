"""Linux package files, checked as text (they run on Linux and on GitHub; the WSL run is in the LINUX report).
Repo files are found from this test file, never from the installed package."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / "pc-sync" / "linux"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_scripts_are_strict_bash():
    for name in ("build.sh", "install.sh", "uninstall.sh"):
        text = (LINUX / name).read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash\n"), name
        assert "set -euo pipefail" in text, name
        assert "\r" not in text, name


def test_install_is_per_user_with_the_timer():
    text = (LINUX / "install.sh").read_text(encoding="utf-8")
    assert 'opt="$HOME/.local/opt/filament-kit-sync"' in text
    assert 'ln -sfn "$opt/filament-kit-sync" "$bin/filament-kit-sync"' in text
    assert '"$opt/filament-kit-sync" install-timer' in text
    assert "sudo " not in text.replace("'sudo filament-kit pair --pc'", "")
    assert 'die "run this as your own user, not as root' in text


def test_uninstall_keeps_the_token_unless_purge():
    text = (LINUX / "uninstall.sh").read_text(encoding="utf-8")
    assert "systemctl --user disable --now filament-kit-sync.timer" in text
    assert 'data="${XDG_DATA_HOME:-$HOME/.local/share}/filament-kit-sync"' in text
    purge = text[text.index('if [ "$PURGE" -eq 1 ]; then'):]
    assert 'rm -rf "$data"' in purge
    assert text.count('rm -rf "$data"') == 1             # only with --purge
    assert 'rm -rf "$opt" "$opt.old"' in text
    assert '"$state/systemd/timers/stamp-filament-kit-sync.timer"' in text      # Persistent=true's stamp


def _bash_runs() -> bool:
    bash = shutil.which("bash")
    if not bash:
        return False
    try:        # on Windows a plain `bash` can be WSL's, which cannot read these paths
        return subprocess.run([bash, str(LINUX / "uninstall.sh"), "--bogus"], capture_output=True, timeout=30).returncode == 2
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _bash_runs(), reason="needs a bash that can run uninstall.sh")
def test_uninstall_run_keeps_the_data_unless_purge(tmp_path):
    """The text checks above cannot see where `rm -rf "$data"` sits; run the script against a temp HOME."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
    home = tmp_path / "home"
    env["HOME"] = str(home)
    data = home / ".local" / "share" / "filament-kit-sync"
    opt = home / ".local" / "opt" / "filament-kit-sync"

    def run(*args):
        data.mkdir(parents=True, exist_ok=True)
        (data / "token").write_text("secret", encoding="utf-8")
        opt.mkdir(parents=True, exist_ok=True)
        return subprocess.run([shutil.which("bash"), str(LINUX / "uninstall.sh"), *args], env=env, capture_output=True,
                              text=True, timeout=60)

    kept = run()
    assert kept.returncode == 0, kept.stderr
    assert (data / "token").read_text(encoding="utf-8") == "secret" and not opt.exists()
    purged = run("--purge")
    assert purged.returncode == 0, purged.stderr
    assert not data.exists() and not opt.exists()


def test_build_names_the_tarball():
    text = (LINUX / "build.sh").read_text(encoding="utf-8")
    assert 'name="filament-kit-sync-linux-x86_64-$version"' in text
    assert 'tar -C "$stage" --owner=0 --group=0 --numeric-owner -czf "dist/$name.tar.gz" "$name"' in text
    assert "pyinstaller --noconfirm pc-sync/fksync.spec" in text


def test_spec_builds_the_task_exe_on_windows_only():
    text = _read("pc-sync/fksync.spec")
    assert 'if sys.platform == "win32":\n    task = _analysis("task_entry.py")' in text


def test_pc_sync_workflow_runs_on_both():
    text = _read(".github/workflows/pc-sync.yml")
    assert "os: [windows-2022, ubuntu-24.04]" in text
    assert "shellcheck pc-sync/linux/*.sh" in text
    assert "bash pc-sync/linux/build.sh" in text
    assert "pyinstaller==6.11.1" in text


def test_release_builds_signs_and_publishes_the_tarball():
    text = _read(".github/workflows/release.yml")
    job = text[text.index("  sync-linux:"):text.index("  publish:")]
    assert "runs-on: ubuntu-24.04" in job and "bash pc-sync/linux/build.sh" in job
    assert "pytest -n auto -rfEs pc-sync/tests" in job
    assert "secrets." not in job
    assert "needs: [version, server, sync, sync-linux]" in text
    assert re.search(r'assets="[^"]*filament-kit-sync-linux-x86_64-\$VERSION\.tar\.gz', text)


# --- fix round 1 ---------------------------------------------------------------------------------

def test_install_cleans_a_failed_copy_and_stops_a_running_sync():
    """M4: no $opt.new.* folder is left when the copy fails; a sync run is stopped before the swap."""
    text = (LINUX / "install.sh").read_text(encoding="utf-8")
    assert "trap 'rm -rf \"$new\"' ERR" in text
    i_new, i_swap = text.index('new=$(mktemp -d "$opt.new.XXXXXX")'), text.index('mv "$new" "$opt"')
    assert i_new < text.index("trap 'rm -rf \"$new\"' ERR") < i_swap
    stop = "systemctl --user stop filament-kit-sync.service"
    assert stop in text and text.index(stop) < text.index('mv "$opt" "$opt.old"')
    assert "trap - ERR" in text[i_swap:]


def test_uninstall_removes_leftover_copies_and_both_xdg_places():
    """M4 + M1: leftover $opt.new.* go; units and stamp are removed from the shell's XDG folders and the defaults
    (the user manager may not see the shell's XDG_* values)."""
    text = (LINUX / "uninstall.sh").read_text(encoding="utf-8")
    assert 'rm -rf "$opt" "$opt.old" "$opt".new.*' in text
    assert 'for units in "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user" "$HOME/.config/systemd/user"; do' in text
    assert 'for state in "${XDG_DATA_HOME:-$HOME/.local/share}" "$HOME/.local/share"; do' in text
