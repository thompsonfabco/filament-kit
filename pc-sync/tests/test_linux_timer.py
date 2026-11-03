"""Linux: the token file, the sync's own data folder and the systemd user timer."""
import stat
import sys
from pathlib import Path

import pytest

from fksync import __main__ as cli
from fksync import store, timer

TOKEN = "fk_test_" + "z" * 40  # a made-up test value, not a real token


def test_linux_data_dir():
    assert store.linux_data_dir({"HOME": "/home/u"}) == Path("/home/u/.local/share/filament-kit-sync")
    assert store.linux_data_dir({"HOME": "/home/u", "XDG_DATA_HOME": "/d"}) == Path("/d/filament-kit-sync")
    assert store.linux_data_dir({"HOME": "/home/u", "XDG_DATA_HOME": ""}) == Path(
        "/home/u/.local/share/filament-kit-sync")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_token_file_and_folder_modes(tmp_path):
    d = store.AppDirs(tmp_path / "share" / "filament-kit-sync")
    d.ensure()
    assert stat.S_IMODE(d.base.stat().st_mode) == 0o700
    store.save_token(d, TOKEN)
    assert stat.S_IMODE(d.token.stat().st_mode) == 0o600
    assert store.load_token(d) == TOKEN
    d.base.chmod(0o755)                     # an older or hand-made folder is tightened
    d.ensure()
    assert stat.S_IMODE(d.base.stat().st_mode) == 0o700


def test_unit_text():
    svc = timer.service_text(Path("/home/u/.local/opt/filament-kit-sync/filament-kit-sync"))
    assert "[Service]\nType=oneshot\n" in svc
    assert 'ExecStart="/home/u/.local/opt/filament-kit-sync/filament-kit-sync" run --quiet\n' in svc
    assert "[Install]" not in svc               # started by the timer only
    t = timer.timer_text()
    for line in ("[Timer]", "OnBootSec=2min", "OnUnitActiveSec=10min", "Persistent=true",
                 "Unit=filament-kit-sync.service", "[Install]", "WantedBy=timers.target"):
        assert line + "\n" in t, line
    # systemd specifiers and quotes in the path are escaped
    assert 'ExecStart="/home/a%%b/x\\"y/filament-kit-sync" run' in timer.service_text(Path('/home/a%b/x"y/filament-kit-sync'))


def test_stamp_file():
    assert timer.stamp_file({"HOME": "/h"}) == Path("/h/.local/share/systemd/timers/stamp-filament-kit-sync.timer")
    assert timer.stamp_file({"HOME": "/h", "XDG_DATA_HOME": "/d"}) == Path(
        "/d/systemd/timers/stamp-filament-kit-sync.timer")


def test_units_dir():
    assert timer.units_dir({"HOME": "/home/u"}) == Path("/home/u/.config/systemd/user")
    assert timer.units_dir({"HOME": "/home/u", "XDG_CONFIG_HOME": "/c"}) == Path("/c/systemd/user")


def test_install_and_uninstall_timer(tmp_path):
    calls = []

    def systemctl(*args):
        calls.append(args)
        return 0, ""

    units = tmp_path / "units"
    exe = tmp_path / "opt" / "filament-kit-sync"
    out = []
    assert timer.install(units, exe, systemctl=systemctl, echo=out.append) == 0
    assert (units / "filament-kit-sync.service").read_text() == timer.service_text(exe)
    assert (units / "filament-kit-sync.timer").read_text() == timer.timer_text()
    assert calls == [("daemon-reload",), ("enable", "--now", "filament-kit-sync.timer")]
    text = "\n".join(out)
    assert "loginctl enable-linger" in text and "not turned on" in text
    calls.clear()
    stamp = tmp_path / "share" / "systemd" / "timers" / "stamp-filament-kit-sync.timer"
    stamp.parent.mkdir(parents=True)
    stamp.write_bytes(b"")
    assert timer.uninstall(units, stamp=stamp, systemctl=systemctl, echo=out.append) == 0
    assert not stamp.exists()
    assert calls == [("disable", "--now", "filament-kit-sync.timer"), ("daemon-reload",)]
    assert not (units / "filament-kit-sync.service").exists() and not (units / "filament-kit-sync.timer").exists()
    assert timer.uninstall(units, systemctl=systemctl, echo=out.append) == 0          # twice is fine


def test_install_timer_without_user_bus(tmp_path):
    def systemctl(*args):
        return 1, "Failed to connect to bus: No medium found"
    out = []
    assert timer.install(tmp_path / "units", tmp_path / "exe", systemctl=systemctl, echo=out.append) == 1
    assert (tmp_path / "units" / "filament-kit-sync.timer").exists()   # the units stay, for a later session
    assert "Failed to connect to bus" in "\n".join(out)


def test_cli_timer_commands_are_linux_only(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    with pytest.raises(SystemExit):
        cli.main(["install-timer"])
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "{pair,run,status,unpair}" in out and "timer" not in out     # the Windows help is as it was
    monkeypatch.setattr(cli.sys, "platform", "linux")
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "install-timer" in capsys.readouterr().out


def test_cli_status_reads_the_linux_folders(tmp_path, monkeypatch, capsys):
    """Without --appdata on Linux: $HOME/.config (or Flatpak) for the slicers, ~/.local/share for the sync."""
    import orca_fixture
    import studio_fixture
    home = tmp_path / "home"
    studio_fixture.make(home / ".var/app/com.bambulab.BambuStudio/config", variant="BambuStudio", user_id="555")
    orca_fixture.make(home / ".config")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(cli.sys, "platform", "linux")
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Bambu Studio:    Flatpak BambuStudio, user 555" in out
    assert f"Orca folder:     {home / '.config' / 'OrcaSlicer' / 'user' / orca_fixture.USER_ID / 'filament'}" in out
    assert f"Log:             {home / '.local' / 'share' / 'filament-kit-sync' / 'sync.log'}" in out
    assert "Orca install:    not found" in out          # M7: the guard keeps the real /usr/share, /opt out of reach


# --- fix round 1 ---------------------------------------------------------------------------------

def test_exec_start_escapes_dollar():
    """M3: systemd expands $VAR in ExecStart; a literal $ is $$."""
    assert 'ExecStart="/home/a$$b/filament-kit-sync" run' in timer.service_text(Path("/home/a$b/filament-kit-sync"))


def test_service_carries_the_installing_shells_xdg_folders():
    """M1: the user manager may not have the shell's XDG_* : the service gets them, so run reads the token pair wrote."""
    exe = Path("/o/filament-kit-sync")
    plain = timer.service_text(exe, {"HOME": "/h"})
    assert "Environment=" not in plain
    assert timer.service_text(exe, {"XDG_DATA_HOME": "", "XDG_CONFIG_HOME": ""}) == plain    # empty = unset
    svc = timer.service_text(exe, {"HOME": "/h", "XDG_DATA_HOME": "/d a%t", "XDG_CONFIG_HOME": r'/c"x\y'})
    assert 'Environment="XDG_DATA_HOME=/d a%%t"\n' in svc
    assert r'Environment="XDG_CONFIG_HOME=/c\"x\\y"' + "\n" in svc
    assert svc.index("Environment=") < svc.index("ExecStart=")


def test_manager_env_parses_show_environment():
    def sc(*args):
        assert args == ("show-environment",)
        return 0, "HOME=/h\nXDG_DATA_HOME=/m/data\nPATH=/usr/bin\n"
    assert timer.manager_env(sc) == {"HOME": "/h", "XDG_DATA_HOME": "/m/data", "PATH": "/usr/bin"}
    assert timer.manager_env(lambda *a: (1, "Failed to connect to bus")) is None


def test_cli_install_timer_uses_the_managers_folders(tmp_path, monkeypatch, capsys):
    """M1: units go where the user manager looks ($XDG_CONFIG_HOME of the manager, not the shell); the service
    gets the shell's XDG_DATA_HOME; uninstall removes the stamp from the manager's data folder."""
    home = tmp_path / "home"
    calls = []

    def sc(*args):
        calls.append(args)
        if args == ("show-environment",):
            return 0, f"HOME={home}\n"                        # the manager has no XDG_* set
        return 0, ""
    monkeypatch.setattr(timer, "systemctl_user", sc)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", (tmp_path / "shell-data").as_posix())
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "shell-config"))
    monkeypatch.setattr(cli.sys, "platform", "linux")
    assert cli.main(["install-timer"]) == 0
    svc = (home / ".config" / "systemd" / "user" / "filament-kit-sync.service").read_text()
    assert f'Environment="XDG_DATA_HOME={(tmp_path / "shell-data").as_posix()}"' in svc
    assert not (tmp_path / "shell-config" / "systemd").exists()
    stamp = home / ".local" / "share" / "systemd" / "timers" / "stamp-filament-kit-sync.timer"
    stamp.parent.mkdir(parents=True)
    stamp.write_bytes(b"")
    assert cli.main(["uninstall-timer"]) == 0
    assert not stamp.exists()
    assert not (home / ".config" / "systemd" / "user" / "filament-kit-sync.service").exists()
