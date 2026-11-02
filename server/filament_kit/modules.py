"""Module registry and install modes (spec sections 2-3).

A module is a switchable part of the kit. `config.json` may carry
`"modules": {"<name>": true, ...}`; a missing key means the *server* mode,
which is exactly the kit as it was before modules existed.
"""
from __future__ import annotations

import copy
import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse


class ModuleError(Exception):
    """The module/station settings are inconsistent."""


@dataclass(frozen=True)
class Module:
    name: str
    title: str
    description: str
    units: tuple[str, ...]
    depends: tuple[str, ...]
    apt: tuple[str, ...]


def _m(name, title, description, units=(), depends=(), apt=()) -> Module:
    return Module(name, title, description, tuple(units), tuple(depends), tuple(apt))


MODULES: dict[str, Module] = {m.name: m for m in (
    _m("spoolman", "Spoolman", "Spoolman filament database, run on this machine",
       units=("spoolman.service",), apt=("unzip",)),
    # Spoolman need is checked by validate(): local module or a remote spoolman_url.
    _m("server", "Server", "App server: pairing, inventory, API, avahi announcement",
       units=("filament-kit.service",), apt=("avahi-daemon", "qrencode")),
    _m("ai_intake", "AI intake", "Claude label reading and the API key",
       depends=("server",)),
    _m("printers", "Printers", "Bambu bridge: discovery, usage, slot mapping, camera",
       depends=("server",), apt=("ffmpeg",)),
    _m("presets", "Presets", "Bambu Studio preset builds and PC sync",
       units=("filament-kit-build.path",), depends=("server",)),
    _m("library", "Library", "Daily spec-library update",
       units=("filament-kit-library.timer",)),
    _m("backup", "Backup", "Nightly backup of Spoolman db, settings and state",
       units=("filament-kit-backup.timer",)),
    _m("station", "Station", "USB scale and PN532 reader, read-only HTTP",
       units=("filament-kit-station.service",), apt=("alsa-utils",)),
    _m("web", "Web", "Browser UI and the MCP endpoint, on top of the server",
       units=("filament-kit-web.service",), depends=("server",)),
    _m("remote", "Remote access", "Public https name for the web UI (nginx, certbot)",
       depends=("web",), apt=("nginx", "certbot")),
    _m("orders", "Orders", "Order history file for the shop tools",
       depends=("ai_intake",)),
)}

# Switched on by hand (modules set / config menu), never by a mode: a mode is the kit as it was.
OPT_IN = frozenset({"web", "remote", "orders"})

MODES: dict[str, frozenset[str]] = {
    "server": frozenset(MODULES) - {"station"} - OPT_IN,
    "station": frozenset({"station"}),
    "all-in-one": frozenset(MODULES) - OPT_IN,
}

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def enabled(cfg: dict) -> frozenset[str]:
    """Names switched on; missing/None `modules` is the server mode."""
    mods = cfg.get("modules")
    if mods is None:
        return MODES["server"]
    return frozenset(n for n, v in mods.items() if v and n in MODULES)


def mode_of(on: frozenset[str]) -> str:
    for name, members in MODES.items():
        if on == members:
            return name
    return "custom"


def drop_local_station_link(cfg: dict) -> None:
    """Unset station.url (in place) when it is the loopback link to a local station; a remote url stays.

    Without both server and station on, that link points at a station that is stopped: status would
    FAIL and /api/station answer 503, where spec section 3 wants the url unset (409 module_off)."""
    st = cfg.get("station")
    if isinstance(st, dict) and st.get("url") and urlparse(str(st["url"])).hostname in _LOCAL_HOSTS:
        st["url"] = None


def set_mode(cfg: dict, mode: str) -> dict:
    """Copy of cfg with `mode`'s module set (and the station link for all-in-one)."""
    if mode not in MODES:
        raise ModuleError(f"unknown mode {mode!r}")
    out = copy.deepcopy(cfg)
    out["modules"] = {n: n in MODES[mode] for n in MODULES}
    if mode == "all-in-one":
        st = out.setdefault("station", {})
        st["allow"] = ["127.0.0.1"]
        st["url"] = "http://127.0.0.1:5003"
    else:
        drop_local_station_link(out)
    return out


def dependents(name: str, on: frozenset[str]) -> list[str]:
    """Enabled modules (registry order) that depend on `name`."""
    return [n for n, m in MODULES.items() if n in on and name in m.depends]


def _bad_allow(entry) -> bool:
    s = str(entry).strip()
    if not s or "/" in s or "*" in s:
        return True
    try:
        return ipaddress.ip_address(s).is_unspecified
    except ValueError:
        return False  # a host name; resolved to a single address at apply time


def validate(cfg: dict) -> None:
    """Raise ModuleError naming the first problem."""
    mods = cfg.get("modules")
    if mods:
        for n in mods:
            if n not in MODULES:
                raise ModuleError(f"unknown module {n!r}")
    on = enabled(cfg)
    for n in MODULES:
        if n in on:
            for dep in MODULES[n].depends:
                if dep not in on:
                    raise ModuleError(f"{n} needs {dep}")
    if "server" in on and "spoolman" not in on:
        url = cfg.get("spoolman_url") or ""
        host = urlparse(url).hostname or ""
        if not host or host in _LOCAL_HOSTS:
            raise ModuleError(
                "server without the spoolman module needs spoolman_url "
                f"pointing at a remote Spoolman (got {url!r})")
    if "remote" in on:
        pu = urlparse(str((cfg.get("web") or {}).get("public_url") or ""))
        if pu.scheme != "https" or not pu.hostname:
            raise ModuleError("remote needs web.public_url set to the https address people will use")
    if "orders" in on and not (cfg.get("orders") or {}).get("file"):
        raise ModuleError("orders needs orders.file (the order history file)")
    allow = (cfg.get("station") or {}).get("allow") or []
    for entry in allow:
        if _bad_allow(entry):
            raise ModuleError(
                f"station.allow entry {entry!r} must be a single address or host name")
    # A station without a local server answers the server's machine; loopback alone would answer nobody.
    if "station" in on and "server" not in on:
        if not any(str(e).strip() not in _LOCAL_HOSTS for e in allow):
            raise ModuleError(
                "station without the server module needs the server's address in station.allow; "
                "fix: pass --server <name-or-IP> (modules set station --server X)")
