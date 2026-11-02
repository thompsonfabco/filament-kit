"""Apply planner (spec section 4): config.json -> ordered install actions.

Pure: `plan()` touches no system (name resolution goes through an injectable
callable), so tests check every mode change without root. The executor that
runs these actions is a separate step. Nothing here ever deletes data.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Callable

from . import config, modules
from .modules import MODULES, ModuleError

SPOOLMAN_INFO = "http://127.0.0.1:7912/api/v1/info"
STATION_UNIT = "filament-kit-station.service"
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
    for host in st["allow"]:
        try:
            found = resolve(host)
        except OSError as e:
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
    for name, mod in MODULES.items():
        if name not in on:
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
    if "station" in on:
        acts.append(A("enable", STATION_UNIT))
    if "presets" in on:
        acts.append(A("first_build"))
    return acts
