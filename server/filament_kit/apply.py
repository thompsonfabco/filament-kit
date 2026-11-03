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

from . import config, modules, remote
from .modules import MODULES, ModuleError

SPOOLMAN_INFO = "http://127.0.0.1:7912/api/v1/info"
STATION_UNIT = "filament-kit-station.service"
WEB_UNIT = "filament-kit-web.service"
DROPIN = "/etc/systemd/system/filament-kit-station.service.d/kit.conf"
# udev applies rules in file-name order and the last GROUP= wins: the name sorts after the ops station's
# 99-intake-station.rules (C-I1). OLD_UDEV_RULE is the kit's name before that; apply removes it.
UDEV_RULE = "/etc/udev/rules.d/99-zz-filament-kit-station.rules"
OLD_UDEV_RULE = "/etc/udev/rules.d/99-filament-kit-station.rules"
UDEV_TEXT = (
    "# DYMO scale: let the station user read it without being root\n"
    'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0922", GROUP="filament-kit-station", MODE="0640"\n'
)
# A timer/path unit starts its companion service; both files must be installed.
_COMPANION = {
    "filament-kit-build.path": "filament-kit-build.service",
    "filament-kit-library.timer": "filament-kit-library.service",
    "filament-kit-backup.timer": "filament-kit-backup.service",
    "filament-kit-update.timer": "filament-kit-update.service",
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
    if "\n" in a or "\r" in a:
        raise ModuleError(f"a line break in a station setting ({a.split('=')[0]}); fix: put the value on one line")
    a = a.replace("%", "%%")  # systemd expands %-specifiers in Environment=
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
           f"STATION_BEEP={1 if st['beep'] else 0}",
           f"STATION_SPEECH={1 if st['speech'] else 0}",
           f"STATION_CAMERA={st['camera']}",
           f"STATION_PANEL_FW={config.paths().opt.as_posix()}/resources/panel/intake-panel.bin",
           f"STATION_PANEL_FLASH={1 if st['panel_flash'] else 0}"]
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
    full = _uniq(p for n in MODULES if n in on for p in MODULES[n].apt)
    acts += [A("apt", pkg) for pkg in full]
    # --no-install-recommends packages; one another module installs in full is left to that install
    acts += [A("apt_lean", pkg) for pkg in _uniq(p for n in MODULES if n in on for p in MODULES[n].apt_lean)
             if pkg not in full]

    # Phase 1: users, files and unit files; nothing is enabled until daemon_reload.
    if "spoolman" in on:
        acts += [A("user", "spoolman"), A("spoolman_fetch")]
    if "server" in on:
        acts += [A("install_unit", "filament-kit.service"),
                 A("server_setup", "key" if "ai_intake" in on else "")]
    for name in ("presets", "library", "backup", "updates"):
        if name in on:
            for unit in MODULES[name].units:
                acts += [A("install_unit", u) for u in _unit_files(unit)]
    if "web" in on:
        acts.append(A("install_unit", WEB_UNIT))
    rs = remote.settings(cfg) if "remote" in on else None
    if rs:
        acts.append(A("remote_install", rs["hostname"]))
        if rs["window"]:
            acts.append(A("install_file", (remote.TIMER_DROPIN, remote.timer_dropin(rs["window"]),
                                           "0644", "root:root")))
        else:
            acts.append(A("remote_unpin"))  # a window set earlier is removed with the setting
    if "station" in on:
        acts += [
            A("user", ("filament-kit-station", "dialout,audio,video")),
            A("remove_file", OLD_UDEV_RULE),
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
    # Remote off: remove the router route this kit made; nginx, certbot and other routes stay.
    if "remote" not in on and "remote" in configured:
        acts.append(A("remote_off", remote.route_name(cfg)))
    acts.append(A("daemon_reload"))

    # Phase 2: start things, Spoolman first.
    if "spoolman" in on:
        acts += [A("enable", "spoolman.service"), A("wait_http", SPOOLMAN_INFO)]
    if "server" in on:
        acts.append(A("ensure_fields"))
        acts.append(A("enable", "filament-kit.service"))
    for name in ("presets", "library", "backup", "updates"):
        if name in on:
            acts += [A("enable", u) for u in MODULES[name].units]
    if "web" in on:
        acts.append(A("enable", WEB_UNIT))
    if rs:
        acts.append(A("enable", "nginx.service"))
        if rs["window"]:
            acts.append(A("enable", "certbot.timer"))
        acts.append(A("remote_route", (rs["route"], rs["port"])))
    if "station" in on:
        acts.append(A("enable", STATION_UNIT))
    if rs:  # last, so the rules are the final thing on screen before the closing line
        acts.append(A("remote_print", (rs["hostname"], rs["route"], rs["window"] or "", tuple(rs["lan"]))))
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
    "apt_lean": f"check the network and run `sudo apt-get update`, then {_AGAIN}",
    "user": f"see the useradd message above, then {_AGAIN}",
    "spoolman_fetch": f"see the Spoolman messages above, then {_AGAIN}",
    "install_unit": "run ./install.sh again (the unit files live in /opt/filament-kit/resources)",
    "install_file": f"check the disk is writable, then {_AGAIN}",
    "remove_file": "remove it by hand: sudo rm <arg>",
    "enable": "see: journalctl -u <arg>",
    "daemon_reload": "see: journalctl -b",
    "udev_reload": "see: journalctl -b -u systemd-udevd",
    "remove_pkg": "remove it by hand: sudo apt-get remove <arg>",
    "disable_ext": "disable it by hand: sudo systemctl disable --now <arg>",
    "mask_sleep": "mask them by hand: sudo systemctl mask " + " ".join(SLEEP_TARGETS),
    "wait_http": "Spoolman did not answer on port 7912; see: journalctl -u spoolman",
    "remote_install": f"see the messages above (nginx -t shows config errors), then {_AGAIN}",
    "remote_route": "see: nginx -t and journalctl -u nginx; list routes with: sudo /usr/local/sbin/mcp-route ls",
    "remote_unpin": "remove it by hand: sudo rm /etc/systemd/system/certbot.timer.d/acme-window.conf",
    "remote_off": ("remove the kit's files by hand: sudo /usr/local/sbin/mcp-route rm <arg>; sudo rm "
                   "/etc/nginx/conf.d/filament-kit-router.conf /etc/letsencrypt/renewal-hooks/deploy/filament-kit"),
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


def _remote_install(ex: _Exec, host: str) -> None:
    """Router files, certbot hooks and a placeholder certificate so nginx starts before certbot has run. When
    `nginx -t` fails, the router conf and proxy conf go back to what they were (or away), so a bad conf never
    stops every later nginx start (C-I4); the step then fails."""
    before = {}
    for dest in (remote.ROUTER_CONF, remote.PROXY_CONF):
        f = _under(ex.root, dest)
        before[dest] = f.read_bytes() if f.exists() else None
    conf = remote.read_resource(ex.resources, "mcp-router.conf").replace("@HOST@", host)
    ex.write(remote.ROUTER_CONF, conf.encode("utf-8"), 0o644)
    for name, dest, mode in (("mcp-proxy.conf", remote.PROXY_CONF, 0o644),
                             ("route.template", f"{remote.ROUTER_DIR}/route.template", 0o644),
                             ("mcp-route", remote.MCP_ROUTE, 0o755),
                             ("acme-hooks.sh", remote.HOOK, 0o755)):
        ex.write(dest, remote.read_resource(ex.resources, name).encode("utf-8"), mode)
    ex.write(f"{remote.ROUTER_DIR}/host", f"{host}\n".encode("utf-8"), 0o644)
    # The deploy hook deliberately runs from two places: the lineage's renewal conf (set by `remote issue`) and
    # this renewal-hooks/deploy file. A later `certbot --expand` rewrites the renewal conf and drops its hook
    # (known from the ops install); this file keeps the cert reaching nginx. The hook acts only on our lineage.
    ex.write(remote.DEPLOY_HOOK_FILE, f"#!/bin/sh\nexec {remote.HOOK} deploy\n".encode("utf-8"), 0o755)
    for d, mode in ((remote.ROUTE_DIR, 0o755), (remote.TLS_DIR, 0o750)):
        _under(ex.root, d).mkdir(parents=True, exist_ok=True)
        os.chmod(_under(ex.root, d), mode)
    cert = _under(ex.root, f"{remote.TLS_DIR}/fullchain.pem")
    key = _under(ex.root, f"{remote.TLS_DIR}/privkey.pem")
    if not cert.exists():  # never replaces a real certificate
        print(f"\n==> Placeholder certificate for {host} (replaced when certbot succeeds)")
        ex.cmd(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                "-subj", f"/CN={host}", "-addext", f"subjectAltName=DNS:{host}",
                "-keyout", str(key), "-out", str(cert)])
        ex.cmd(["chmod", "600", str(key)])
    try:
        ex.cmd(["nginx", "-t"])
    except (subprocess.CalledProcessError, OSError):
        back, gone = [], []
        for dest, old in before.items():
            f = _under(ex.root, dest)
            if old is None:
                f.unlink(missing_ok=True)
                gone.append(dest)
            else:
                f.write_bytes(old)
                back.append(dest)
        print("nginx -t failed: " + "; ".join(([f"put back the previous {', '.join(back)}"] if back else [])
                                               + ([f"removed {', '.join(gone)} again"] if gone else [])))
        raise


def _remote_route(ex: _Exec, name: str, port: int) -> None:
    """Route the web unit; drop routes this kit added earlier under another name (public_url changed)."""
    book = _under(ex.root, remote.KIT_ROUTES)
    old = book.read_text(encoding="utf-8").split() if book.exists() else []
    for n in old:
        if n != name and re.fullmatch(r"[a-z][a-z0-9-]{1,30}", n):
            ex.cmd([remote.MCP_ROUTE, "rm", n])  # mcp-route rm leaves files it did not write
    ex.cmd([remote.MCP_ROUTE, "add", name, str(port)])
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(name + "\n", encoding="utf-8")


def _other_routes(ex: _Exec, name: str) -> list[str]:
    """Route files in mcp.d this kit did not add (not `name`, not in kit-routes): e.g. the owner's amazon and h2d
    routes, which only the kit's router conf serves once the ops router is gone (C-I2)."""
    book = _under(ex.root, remote.KIT_ROUTES)
    ours = {name, *(book.read_text(encoding="utf-8").split() if book.exists() else [])}
    d = _under(ex.root, remote.ROUTE_DIR)
    return sorted(f.stem for f in d.glob("*.conf") if f.stem not in ours) if d.is_dir() else []


def _remote_off(ex: _Exec, name: str) -> None:
    """Remove the kit's own remote files: the route file mcp-route made for this kit, the kit's router conf (a
    default_server on 443 that would keep any other router from loading) and its certbot deploy hook (Ruling
    AF). nginx, certbot, the certificate, mcp-route and other routes stay. While mcp.d holds routes the kit did
    not add, the router conf stays too: it is what serves them (C-I2)."""
    gone = []
    f = _under(ex.root, f"{remote.ROUTE_DIR}/{name}.conf")
    if f.exists():
        if remote.MARK not in f.read_text(encoding="utf-8", errors="replace"):
            print(f"Remote is off; {f} was not written by the kit, so it was left in place.")
        else:
            f.unlink()
            gone.append(f"the {name} route")
    others = _other_routes(ex, name)
    files = [(remote.DEPLOY_HOOK_FILE, "the kit's certbot deploy hook")]
    if not others:
        files.insert(0, (remote.ROUTER_CONF, "the kit's router conf"))
    elif _under(ex.root, remote.ROUTER_CONF).exists():
        print(f"Remote is off; kept the kit's router conf {remote.ROUTER_CONF}: it serves the other routes in "
              f"{remote.ROUTE_DIR} ({', '.join(others)}). Remove it by hand once nothing needs them.")
    for path, what in files:
        p = _under(ex.root, path)
        if p.exists():
            p.unlink()
            gone.append(what)
    if not gone:
        return
    print(f"Remote is off: removed {', '.join(gone)} (nginx, certbot, the certificate and other routes were left).")
    if ex.ok(["nginx", "-t"]):
        ex.ok(["systemctl", "reload", "nginx"])  # a stopped nginx needs nothing


def _remote_print(ex: _Exec, arg: tuple) -> None:
    host, route, window, lan = arg
    s = {"hostname": host, "route": route, "window": window or None, "lan": list(lan)}
    print(remote.firewall_text(s, ex.resources))


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
    elif k == "remove_file":
        f = _under(ex.root, arg)
        if f.exists():
            f.unlink()
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
    elif k == "remote_install":
        _remote_install(ex, arg)
    elif k == "remote_unpin":
        f = _under(ex.root, remote.TIMER_DROPIN)
        if f.exists():
            f.unlink()
            print("remote.acme_window is unset: removed the certbot timer drop-in.")
    elif k == "remote_route":
        _remote_route(ex, arg[0], arg[1])
    elif k == "remote_off":
        _remote_off(ex, arg)
    elif k == "remote_print":
        _remote_print(ex, arg)
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
        if a.kind in ("apt", "apt_lean"):
            # one batched install for consecutive apt actions of the same kind; apt_lean skips recommended packages
            # (espeak-ng would otherwise pull in a whole audio stack)
            pkgs = []
            while i < len(actions) and actions[i].kind == a.kind:
                pkgs.append(actions[i].arg)
                i += 1
            flags = ["--no-install-recommends"] if a.kind == "apt_lean" else []
            try:
                ex.cmd([*APT, "install", "-y", "-q", *flags, *pkgs])
            except (subprocess.CalledProcessError, OSError) as e:
                _fail(Action(a.kind, " ".join(pkgs)), e)
            continue
        try:
            _step(ex, a)
        except (subprocess.CalledProcessError, OSError, ApplyError) as e:
            _fail(a, e)
        i += 1
    # Spec section 5: the station's system changes stay when the module is turned off; say so once.
    station_on = any(a.kind == "install_file" and a.arg[0] == UDEV_RULE for a in actions)
    if not station_on and (_under(ex.root, UDEV_RULE).exists() or _under(ex.root, OLD_UDEV_RULE).exists()):
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
