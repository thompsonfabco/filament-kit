"""Apply planner and executor (spec section 4): config.json -> ordered install actions -> a system.

Pure: `plan()` touches no system (name resolution goes through an injectable
callable), so tests check every mode change without root. `execute()` runs the
actions: commands go through an injectable `run`, files are written under
`root`, so tests run it against a fake and a temporary directory. Nothing here
ever deletes data.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config, modules
from .modules import MODULES, ModuleError

SPOOLMAN_INFO = "http://127.0.0.1:7912/api/v1/info"
STATION_UNIT = "filament-kit-station.service"
WEB_UNIT = "filament-kit-web.service"
DROPIN = "/etc/systemd/system/filament-kit-station.service.d/kit.conf"
UDEV_RULE = "/etc/udev/rules.d/99-filament-kit-station.rules"
UDEV_TEXT = (
    "# DYMO scale: let the station user read it without being root\n"
    'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0922", GROUP="filament-kit-station", MODE="0640"\n'
)
# A timer/path unit starts its companion service; both files must be installed.
_COMPANION = {
    "filament-kit-build.path": "filament-kit-build.service",
    "filament-kit-library.timer": "filament-kit-library.service",
    "filament-kit-backup.timer": "filament-kit-backup.service",
}


@dataclass(frozen=True)
class Action:
    kind: str
    arg: str | tuple = ""


def default_resolve(host: str) -> list[str]:
    """Addresses for `host`; literal IPs are kept as they are."""
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    out: list[str] = []
    for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
        addr = info[4][0].split("%")[0]
        if addr not in out:
            out.append(addr)
    return out


def _uniq(items) -> list[str]:
    out: list[str] = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


def _env_assign(a: str) -> str:
    """systemd splits Environment= on spaces; quote a whole assignment that has any."""
    if any(c in a for c in ' 	"'):
        return '"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return a


def station_dropin(cfg: dict, addresses: list[str]) -> str:
    """Text of the station drop-in (spec section 5); `addresses` are already resolved."""
    st = config._merge(config.DEFAULTS["station"], cfg.get("station") or {})
    allow = _uniq(["127.0.0.1", *addresses])
    env = [f"STATION_ALLOW={' '.join(allow)}",
           f"STATION_PORT={int(st['port'])}",
           f"NFC_DEVICE={st['nfc_device']}",
           f"STATION_BEEP={1 if st['beep'] else 0}"]
    if st.get("beep_device"):
        env.append(f"STATION_BEEP_DEVICE={st['beep_device']}")
    env_line = "Environment=" + " ".join(_env_assign(e) for e in env)
    ip_allow = " ".join(["localhost", *_uniq(addresses)])
    return f"[Service]\n{env_line}\nIPAddressAllow={ip_allow}\n"


def _resolve_all(cfg: dict, resolve: Callable[[str], list[str]]) -> list[str]:
    st = config._merge(config.DEFAULTS["station"], cfg.get("station") or {})
    addrs: list[str] = []
    for host in st.get("allow") or []:
        try:
            found = resolve(host)
        except (OSError, UnicodeError) as e:  # a malformed name ('a..b') fails in the idna codec
            raise ModuleError(
                f"cannot resolve station.allow host {host!r} ({e}); "
                "fix: check the name, or use the server's IP address") from e
        if not found:
            raise ModuleError(
                f"station.allow host {host!r} resolved to no address; "
                "fix: check the name, or use the server's IP address")
        addrs += found
    return _uniq(addrs)


def _unit_files(unit: str) -> list[str]:
    return [unit, *([_COMPANION[unit]] if unit in _COMPANION else [])]


def plan(cfg: dict, *, resolve: Callable[[str], list[str]] = default_resolve) -> list[Action]:
    modules.validate(cfg)
    on = modules.enabled(cfg)
    # Resolve first: a failure must stop everything before any action is returned.
    addrs = _resolve_all(cfg, resolve) if "station" in on else []

    A = Action
    acts: list[Action] = []
    for pkg in _uniq(p for n in MODULES if n in on for p in MODULES[n].apt):
        acts.append(A("apt", pkg))

    # Phase 1: users, files and unit files; nothing is enabled until daemon_reload.
    if "spoolman" in on:
        acts += [A("user", "spoolman"), A("spoolman_fetch")]
    if "server" in on:
        acts += [A("install_unit", "filament-kit.service"),
                 A("server_setup", "key" if "ai_intake" in on else "")]
    for name in ("presets", "library", "backup"):
        if name in on:
            for unit in MODULES[name].units:
                acts += [A("install_unit", u) for u in _unit_files(unit)]
    if "web" in on:
        acts.append(A("install_unit", WEB_UNIT))
    if "station" in on:
        acts += [
            A("user", ("filament-kit-station", "dialout,audio")),
            A("install_file", (UDEV_RULE, UDEV_TEXT, "0644", "root:root")),
            A("udev_reload"),
            A("remove_pkg", "brltty"),
            A("disable_ext", "ModemManager"),
            A("mask_sleep"),
            A("alsa_unmute"),
            A("install_file", (DROPIN, station_dropin(cfg, addrs), "0644", "root:root")),
            A("install_unit", STATION_UNIT),
        ]
    # An opt-in module nobody ever configured is not mentioned (the legacy plan stays as it was).
    configured = cfg.get("modules") or {}
    for name, mod in MODULES.items():
        if name not in on and (name not in modules.OPT_IN or name in configured):
            for unit in mod.units:
                acts += [A("disable", u) for u in _unit_files(unit)]
    acts.append(A("daemon_reload"))

    # Phase 2: start things, Spoolman first.
    if "spoolman" in on:
        acts += [A("enable", "spoolman.service"), A("wait_http", SPOOLMAN_INFO)]
    if "server" in on:
        acts.append(A("ensure_fields"))
        acts.append(A("enable", "filament-kit.service"))
    for name in ("presets", "library", "backup"):
        if name in on:
            acts += [A("enable", u) for u in MODULES[name].units]
    if "web" in on:
        acts.append(A("enable", WEB_UNIT))
    if "station" in on:
        acts.append(A("enable", STATION_UNIT))
    if "presets" in on:
        acts.append(A("first_build"))
    return acts


# ---------- executor ----------

WRAPPER = "/usr/local/bin/filament-kit"
AVAHI_FILE = "/etc/avahi/services/filament-kit.service"
SLEEP_TARGETS = ["sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"]
ALSA_CONTROLS = ("Master", "Headphone", "Speaker", "PCM")
_AGAIN = "run `sudo filament-kit modules apply` again"
# Wait for the dpkg lock instead of failing at once: on a fresh Ubuntu, unattended-upgrades often holds it.
APT = ["apt-get", "-o", "DPkg::Lock::Timeout=300"]

# What to try when a step fails; printed after `FAIL <step>`. <arg> is the action's argument.
_HINTS = {
    "apt": f"check the network and run `sudo apt-get update`, then {_AGAIN}",
    "user": f"see the useradd message above, then {_AGAIN}",
    "spoolman_fetch": f"see the Spoolman messages above, then {_AGAIN}",
    "install_unit": "run ./install.sh again (the unit files live in /opt/filament-kit/resources)",
    "install_file": f"check the disk is writable, then {_AGAIN}",
    "enable": "see: journalctl -u <arg>",
    "daemon_reload": "see: journalctl -b",
    "udev_reload": "see: journalctl -b -u systemd-udevd",
    "remove_pkg": "remove it by hand: sudo apt-get remove <arg>",
    "disable_ext": "disable it by hand: sudo systemctl disable --now <arg>",
    "mask_sleep": "mask them by hand: sudo systemctl mask " + " ".join(SLEEP_TARGETS),
    "wait_http": "Spoolman did not answer on port 7912; see: journalctl -u spoolman",
    "ensure_fields": "check Spoolman answers, then: sudo filament-kit ensure-fields",
}


class ApplyError(Exception):
    """A step failed; the `FAIL` and `fix:` lines are already printed."""


def run_checked(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))


def _no_systemd() -> bool:
    return os.environ.get("FK_NO_SYSTEMD") == "1"


def _tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return 200 <= r.status < 300
    except (OSError, ValueError):
        return False


def _https_local_ok(url: str) -> bool:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the kit's own self-signed certificate, on localhost (curl -k today)
    try:
        with urllib.request.urlopen(url, timeout=3, context=ctx) as r:
            return 200 <= r.status < 300
    except (OSError, ValueError):
        return False


def _under(root: Path, path: str) -> Path:
    return root / path.lstrip("/")


class _Exec:
    """Runs commands (or, with FK_NO_SYSTEMD=1, prints them) and writes files under `root`."""

    def __init__(self, run, resources: Path, root: Path):
        self.dry = _no_systemd()
        self._run = run
        self.resources = resources
        self.root = root

    def cmd(self, cmd: list[str]) -> None:
        if self.dry:
            print("would run: " + " ".join(cmd))
            return
        # stdout is block-buffered when piped to a log: our "==>" lines must come before the command's output
        sys.stdout.flush()
        self._run(cmd)

    def ok(self, cmd: list[str]) -> bool:
        """Run a command whose failure is harmless (or is the answer, for a probe)."""
        try:
            self.cmd(cmd)
            return True
        except (subprocess.CalledProcessError, OSError):
            return False

    def probe(self, cmd: list[str]) -> bool:
        if self.dry:
            return True
        return self.ok(cmd)

    def write(self, dest: str, data: bytes, mode: int, owner: str = "") -> Path:
        path = _under(self.root, dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        os.chmod(path, mode)
        if owner:
            self.cmd(["chown", owner, str(path)])
        return path


def _enable(ex: _Exec, unit: str) -> None:
    ex.cmd(["systemctl", "enable", unit])
    # restart, not start: an upgrade must run the new code, and a path unit must re-read its file
    ex.cmd(["systemctl", "start" if unit.endswith(".timer") else "restart", unit])


def _user(ex: _Exec, arg) -> None:
    name, groups = (arg, "") if isinstance(arg, str) else arg
    if not ex.dry and ex.ok(["id", "-u", name]):
        return
    cmd = ["useradd", "--system", "--user-group", "--no-create-home", "--home-dir", "/nonexistent",
           "--shell", "/usr/sbin/nologin"]
    if groups:
        cmd += ["--groups", groups]
    ex.cmd(cmd + [name])


def _alsa_unmute(ex: _Exec) -> None:
    # From filament-ops station_setup.sh: analog outputs start muted on a fresh install; unmute them at
    # 80% and keep that across reboots (the scan beep). Failures are ignored.
    try:
        cards = _under(ex.root, "/proc/asound/cards").read_text(encoding="utf-8")
    except OSError:
        cards = ""
    for card in re.findall(r"^ *([0-9]+) \[", cards, re.M):
        for ctl in ALSA_CONTROLS:
            ex.ok(["amixer", "-q", "-c", card, "sset", ctl, "80%", "unmute"])
    ex.ok(["alsactl", "store"])


def _wait_http(ex: _Exec, url: str) -> None:
    if ex.dry:
        print(f"would wait for {url}")
        return
    print(f"\n==> Waiting for {url}")
    for _ in range(90):
        if _http_ok(url):
            return
        time.sleep(2)
    raise ApplyError(f"{url} did not answer")


def _raw_config() -> dict:
    f = config.paths().etc / "config.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _ask(prompt: str) -> str:
    print(prompt, end="", flush=True)
    return (sys.stdin.readline() or "").rstrip("\r\n")


def _server_setup(ex: _Exec, arg: str) -> None:
    """install.sh steps 5-6 (Ruling F): first-run questions, key, certificate, avahi file."""
    from . import cli  # cli imports apply; import here, not at module load
    etc = config.paths().etc
    if "server_name" not in _raw_config() and not _tty():
        # nobody to ask: keep the default, so a later apply at a keyboard asks no first-run questions
        cfg = config.load()
        cfg["server_name"] = socket.gethostname()
        config.save(cfg)
    elif "server_name" not in _raw_config():
        print("\n==> First-time setup")
        default_name = socket.gethostname()
        name = _ask(f"Display name shown in the phone app (any text) [{default_name}]: ").strip()
        cfg = config.load()
        cfg["server_name"] = name or default_name
        if _ask("Use the default storage locations? [Y/n]: ").strip()[:1] in ("n", "N"):
            print("Make your changes, then 0 to go back.")
            cli._storage_menu(cfg)
        config.save(cfg)

    key_file = etc / cli.KEY_FILE
    # Asked whenever it is missing and someone is at the keyboard (also on upgrade).
    if arg == "key" and (not key_file.exists() or key_file.stat().st_size == 0) and _tty():
        key = getpass.getpass("Anthropic API key (typing is hidden, Enter to skip): ").strip()
        if key:
            cli.write_key(key)
            print("Key saved.")
        else:
            print("No key entered. Add it later with: sudo filament-kit config  (option 4)")
        del key
    for f in (etc / "config.json", key_file):
        if f.exists():
            ex.cmd(["chown", "root:filament-kit", str(f)])
            ex.cmd(["chmod", "640", str(f)])

    # certificate: created once, never replaced
    print("\n==> Server certificate")
    if cli.cmd_cert() != 0:
        raise ApplyError("certificate not created")
    cert, key_pem = etc / "cert.pem", etc / "key.pem"
    if cert.exists():
        ex.cmd(["chown", "root:filament-kit", str(cert), str(key_pem)])
        ex.cmd(["chmod", "644", str(cert)])
        ex.cmd(["chmod", "640", str(key_pem)])

    port = int(config.load()["port"])
    text = (ex.resources / "avahi" / "filament-kit.service").read_text(encoding="utf-8")
    ex.write(AVAHI_FILE, text.replace("<port>8710</port>", f"<port>{port}</port>").encode("utf-8"), 0o644)
    ex.cmd(["systemctl", "enable", "--now", "avahi-daemon"])
    if not ex.ok(["systemctl", "reload", "avahi-daemon"]):
        ex.cmd(["systemctl", "restart", "avahi-daemon"])


def _step(ex: _Exec, a: Action) -> None:
    k, arg = a.kind, a.arg
    if k == "user":
        _user(ex, arg)
    elif k == "spoolman_fetch":
        ex.cmd(["bash", str(ex.resources / "spoolman.sh")])
    elif k == "install_unit":
        ex.write(f"/etc/systemd/system/{arg}", (ex.resources / "systemd" / arg).read_bytes(), 0o644)
    elif k == "install_file":
        dest, content, mode, owner = arg
        ex.write(dest, content.encode("utf-8"), int(mode, 8), owner)
    elif k == "server_setup":
        _server_setup(ex, arg)
    elif k == "udev_reload":
        ex.cmd(["udevadm", "control", "--reload"])
        ex.cmd(["udevadm", "trigger", "--subsystem-match=hidraw"])
    elif k == "remove_pkg":
        if ex.probe(["dpkg", "-s", arg]):
            ex.cmd([*APT, "remove", "-y", "-q", arg])
    elif k == "disable_ext":
        if ex.probe(["systemctl", "is-enabled", arg]):
            ex.cmd(["systemctl", "disable", "--now", arg])
    elif k == "mask_sleep":
        ex.cmd(["systemctl", "mask", *SLEEP_TARGETS])
    elif k == "alsa_unmute":
        _alsa_unmute(ex)
    elif k == "disable":
        # A unit that was never installed needs nothing; asking systemd anyway prints
        # "Failed to disable unit ... does not exist" on every apply. Its failure stays harmless.
        if _under(ex.root, f"/etc/systemd/system/{arg}").exists():
            ex.ok(["systemctl", "disable", "--now", arg])
    elif k == "daemon_reload":
        ex.cmd(["systemctl", "daemon-reload"])
    elif k == "enable":
        _enable(ex, arg)
    elif k == "wait_http":
        _wait_http(ex, arg)
    elif k == "ensure_fields":
        ex.cmd([WRAPPER, "ensure-fields"])  # the wrapper runs it as the filament-kit user
    elif k == "first_build":
        # Before the PC sync has uploaded the Bambu Studio presets this only prints what to do next;
        # it never stops apply.
        print("\n==> Building presets")
        ex.ok([WRAPPER, "profiles", "build"])
    else:
        raise ApplyError(f"unknown action {k!r}")


def _label(a: Action) -> str:
    if isinstance(a.arg, tuple):
        return f"{a.kind} {a.arg[0]}"
    return f"{a.kind} {a.arg}".rstrip()


def _fail(a: Action, e: Exception) -> None:
    print(f"FAIL {_label(a)}")
    arg = a.arg if isinstance(a.arg, str) else ""
    print(f"     fix: {_HINTS.get(a.kind, f'see the messages above, then {_AGAIN}').replace('<arg>', arg)}")
    raise ApplyError(f"{_label(a)}: {e}") from e


def execute(actions: list[Action], *, run: Callable[[list[str]], None] = run_checked,
            resources: Path | None = None, root: Path = Path("/")) -> None:
    """Run `actions` in order; stop at the first failure with `FAIL <step>` / `fix: <hint>` (ApplyError).

    `resources` defaults to config.paths().opt / "resources" (what install.sh copies there)."""
    if resources is None:
        resources = config.paths().opt / "resources"
    ex = _Exec(run, Path(resources), Path(root))
    i = 0
    while i < len(actions):
        a = actions[i]
        if a.kind == "apt":
            # one batched install for consecutive apt actions
            pkgs = []
            while i < len(actions) and actions[i].kind == "apt":
                pkgs.append(actions[i].arg)
                i += 1
            try:
                ex.cmd([*APT, "install", "-y", "-q", *pkgs])
            except (subprocess.CalledProcessError, OSError) as e:
                _fail(Action("apt", " ".join(pkgs)), e)
            continue
        try:
            _step(ex, a)
        except (subprocess.CalledProcessError, OSError, ApplyError) as e:
            _fail(a, e)
        i += 1
    # Spec section 5: the station's system changes stay when the module is turned off; say so once.
    station_on = any(a.kind == "install_file" and a.arg[0] == UDEV_RULE for a in actions)
    if not station_on and _under(ex.root, UDEV_RULE).exists():
        print("Station is off: brltty removal, ModemManager, suspend masking and audio levels "
              "were left as they are.")


def finish(cfg: dict, *, run: Callable[[list[str]], None] = run_checked, pairing: bool = True) -> None:
    """install.sh step 8, for the modules that are on: status, pairing code, the closing line.

    `pairing=False` (modules set/enable/disable, config menu) prints the status only, no QR code."""
    ex = _Exec(run, Path("."), Path("/"))
    on = modules.enabled(cfg)
    host = socket.gethostname()
    if "server" in on:
        port = int(cfg.get("port", 8710))
        if not ex.dry:
            print("\n==> Waiting for filament-kit to start")
            for _ in range(30):
                if _https_local_ok(f"https://127.0.0.1:{port}/api/info"):
                    break
                time.sleep(1)
        print("\n==> Status")
        if not ex.ok([WRAPPER, "status"]):
            print("Some checks failed; follow the 'fix:' lines above.")
        if pairing:
            print("\n==> Pair a phone: open the filament-kit app and scan this code")
            ex.ok([WRAPPER, "pair"])
    parts = ["Done."]
    if "spoolman" in on:
        parts.append(f"Spoolman: http://{host}.local:7912")
    if "server" in on:
        parts.append("Pair another phone: sudo filament-kit pair")
    if "station" in on:
        st = config._merge(config.DEFAULTS["station"], cfg.get("station") or {})
        parts.append(f"Station: http://{host}.local:{int(st['port'])}/state")
    print("\n" + "   ".join(parts))
