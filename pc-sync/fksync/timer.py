"""Linux: the systemd *user* timer that runs `filament-kit-sync run --quiet` every 10 minutes (Windows: the
scheduled task the installer registers).

filament-kit-sync.timer starts filament-kit-sync.service 2 minutes after boot (at once when the user's session
starts later than that) and then 10 minutes after each run; Persistent=true. The service is Type=oneshot. Both
units live in $XDG_CONFIG_HOME/systemd/user (else ~/.config/systemd/user) and are handled with `systemctl --user`,
so no root is needed; Persistent=true makes systemd keep a stamp file in $XDG_DATA_HOME/systemd/timers, which
uninstall removes too. The user manager runs only while the user is logged in; lingering (runs while logged
out) is never turned on here, only explained.
"""
import subprocess
from pathlib import Path
from typing import Callable, Mapping

NAME = "filament-kit-sync"
SERVICE = f"{NAME}.service"
TIMER = f"{NAME}.timer"
LINGER_NOTE = ("The sync runs while you are logged in. To have it run while you are logged out too, run "
               "'loginctl enable-linger' once (not turned on by this install).")


def units_dir(env: Mapping[str, str]) -> Path:
    xdg = env.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path(env.get("HOME") or Path.home()) / ".config") / "systemd" / "user"


def stamp_file(env: Mapping[str, str]) -> Path:
    """Where systemd keeps the Persistent=true stamp of the user timer."""
    data = env.get("XDG_DATA_HOME")
    base = Path(data) if data else Path(env.get("HOME") or Path.home()) / ".local" / "share"
    return base / "systemd" / "timers" / f"stamp-{TIMER}"


def _quote(path: Path) -> str:
    """A systemd command line word: double-quoted, with % (specifiers), \\ and " escaped."""
    s = Path(path).as_posix().replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{s}"'


def service_text(exe: Path) -> str:
    return ("[Unit]\n"
            "Description=filament-kit sync: Bambu Studio and Orca Slicer filament presets\n"
            "\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={_quote(exe)} run --quiet\n")


def timer_text() -> str:
    return ("[Unit]\n"
            "Description=Run the filament-kit sync every 10 minutes\n"
            "\n"
            "[Timer]\n"
            "OnBootSec=2min\n"
            "OnUnitActiveSec=10min\n"
            "Persistent=true\n"
            f"Unit={SERVICE}\n"
            "\n"
            "[Install]\n"
            "WantedBy=timers.target\n")


def systemctl_user(*args: str) -> tuple[int, str]:
    """`systemctl --user <args>`: (exit code, stderr + stdout)."""
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stderr + r.stdout).strip()


def install(units: Path, exe: Path, *, systemctl: Callable[..., tuple[int, str]] = systemctl_user,
            echo: Callable[[str], None] = print) -> int:
    """Write both units and enable + start the timer. The units stay written when systemctl fails."""
    units.mkdir(parents=True, exist_ok=True)
    (units / SERVICE).write_text(service_text(exe), encoding="utf-8", newline="\n")
    (units / TIMER).write_text(timer_text(), encoding="utf-8", newline="\n")
    for args in (("daemon-reload",), ("enable", "--now", TIMER)):
        rc, out = systemctl(*args)
        if rc != 0:
            echo(f"Wrote {units / TIMER}, but 'systemctl --user {' '.join(args)}' failed: {out}")
            echo(f"Run '{NAME} install-timer' again from a desktop or SSH session of this user.")
            return 1
    echo(f"The sync timer is on: {TIMER} runs '{exe} run --quiet' every 10 minutes.")
    echo(LINGER_NOTE)
    return 0


def uninstall(units: Path, *, stamp: Path | None = None, systemctl: Callable[..., tuple[int, str]] = systemctl_user,
              echo: Callable[[str], None] = print) -> int:
    """Stop and disable the timer, remove both units (and the timer's stamp file). Nothing there is fine."""
    rc, out = systemctl("disable", "--now", TIMER)
    if rc != 0 and (units / TIMER).exists():
        echo(f"warning: 'systemctl --user disable --now {TIMER}' failed: {out}")
    for unit in (TIMER, SERVICE):
        (units / unit).unlink(missing_ok=True)
    if stamp is not None:
        stamp.unlink(missing_ok=True)
    systemctl("daemon-reload")
    echo(f"The sync timer is off and its units are removed from {units}.")
    return 0
