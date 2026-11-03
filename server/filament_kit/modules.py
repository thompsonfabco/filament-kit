"""Module registry and install modes (spec sections 2-3).

A module is a switchable part of the kit. `config.json` may carry
`"modules": {"<name>": true, ...}`; a missing key means the *server* mode,
which is exactly the kit as it was before modules existed.
"""
from __future__ import annotations

import copy
import ipaddress
from dataclasses import dataclass
from typing import Callable
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
    apt_lean: tuple[str, ...] = ()  # installed with --no-install-recommends (apply's apt_lean action)
    needs_text: str = ""            # extra "needs:" shown in the checklist that is not another module
    optional_ai: bool = False       # marked OPTIONAL AI in the checklist


def _m(name, title, description, units=(), depends=(), apt=(), apt_lean=(),
       needs_text="", optional_ai=False) -> Module:
    return Module(name, title, description, tuple(units), tuple(depends), tuple(apt), tuple(apt_lean),
                  needs_text, optional_ai)


MODULES: dict[str, Module] = {m.name: m for m in (
    _m("spoolman", "Spoolman", "Spoolman filament database, run on this machine",
       units=("spoolman.service",), apt=("unzip",)),
    # Spoolman need is checked by validate(): local module or a remote spoolman_url.
    _m("server", "Server", "App server: pairing, inventory, API, avahi announcement",
       units=("filament-kit.service",), apt=("avahi-daemon", "qrencode"),
       needs_text="Spoolman (this machine or a remote one)"),
    _m("ai_intake", "AI intake", "Claude reads spool labels from photos (needs an Anthropic API key)",
       depends=("server",), needs_text="an Anthropic API key", optional_ai=True),
    _m("printers", "Printers", "Bambu bridge: discovery, usage, slot mapping, camera",
       depends=("server",), apt=("ffmpeg",)),
    _m("presets", "Presets", "Bambu Studio preset builds and PC sync",
       units=("filament-kit-build.path",), depends=("server",)),
    _m("library", "Library", "Filament spec library: downloaded on request, then a daily update",
       units=("filament-kit-library.timer",)),
    _m("backup", "Backup", "Nightly backup of Spoolman db, settings and state",
       units=("filament-kit-backup.timer",)),
    _m("station", "Station", "USB scale and PN532 reader, read-only HTTP",
       units=("filament-kit-station.service",), apt=("alsa-utils",), apt_lean=("espeak-ng", "ffmpeg")),
    _m("web", "Web", "Browser UI and the MCP endpoint, on top of the server",
       units=("filament-kit-web.service",), depends=("server",)),
    _m("remote", "Remote access", "Public https name for the web UI (nginx, certbot)",
       depends=("web",), apt=("nginx", "certbot")),
    _m("orders", "Orders", "Order history file for the shop tools",
       depends=("ai_intake",)),
)}

# Switched on by hand (modules set / config menu, the installer's question), never by a mode: a mode is the kit
# as it was. ai_intake (spec R 2.4): AI is optional, so a new install has it off; one that had it keeps it. The
# library is not bundled: switching it on downloads it; one without the key has none until asked.
OPT_IN = frozenset({"ai_intake", "web", "remote", "orders", "library"})

MODES: dict[str, frozenset[str]] = {
    "server": frozenset(MODULES) - {"station"} - OPT_IN,
    "station": frozenset({"station"}),
    "all-in-one": frozenset(MODULES) - OPT_IN,
}

# A config without `modules` is an install from before modules: the server mode as it was then, AI intake and the library timer on.
LEGACY = MODES["server"] | {"ai_intake", "library"}
# On in addition to a mode's set without making the mode "custom" (the legacy set is still the server mode).
ADD_ONS = frozenset({"ai_intake", "library"})

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def enabled(cfg: dict) -> frozenset[str]:
    """Names switched on; missing/None `modules` is the server mode as it was before modules (`LEGACY`)."""
    mods = cfg.get("modules")
    if mods is None:
        return LEGACY
    return frozenset(n for n, v in mods.items() if v and n in MODULES)


def mode_of(on: frozenset[str]) -> str:
    for name, members in MODES.items():
        if on == members or (on - ADD_ONS == members and "server" in members):
            return name
    return "custom"


def drop_local_station_link(cfg: dict) -> None:
    """Unset station.url (in place) when it is the loopback link to a local station; a remote url stays.

    Without both server and station on, that link points at a station that is stopped: status would
    FAIL and /api/station answer 503, where spec section 3 wants the url unset (409 module_off)."""
    st = cfg.get("station")
    if isinstance(st, dict) and st.get("url") and urlparse(str(st["url"])).hostname in _LOCAL_HOSTS:
        st["url"] = None


def set_mode(cfg: dict, mode: str, say: Callable[[str], None] | None = print) -> dict:
    """Copy of cfg with `mode`'s module set (and the station link for all-in-one). Opt-in modules switched on by
    hand stay on (C-I3: a mode never turns them on or off), except those whose dependencies the new mode removes;
    those are named through `say`."""
    if mode not in MODES:
        raise ModuleError(f"unknown mode {mode!r}")
    out = copy.deepcopy(cfg)
    # An empty cfg is a new install (nothing was on); a filled one without `modules` is a legacy install.
    legacy = cfg.get("modules") is None and bool(cfg)
    was = enabled(cfg) if cfg.get("modules") is not None or cfg else frozenset()
    if legacy and mode == "station":
        was = was - {"library"}
    on = set(MODES[mode])
    dropped = []
    for n in MODULES:                       # registry order: web before remote, so remote sees web's outcome
        if n in OPT_IN and n in was:
            if all(d in on for d in MODULES[n].depends):
                on.add(n)
            else:
                dropped.append(n)
    out["modules"] = {n: n in on for n in MODULES}
    if dropped and say is not None:
        say(f"Mode {mode}: turned off {', '.join(dropped)} (they need modules this mode does not have).")
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
    if "web" in on or "remote" in on:  # Ruling AA: the web unit is the OAuth issuer, remote or not
        pu = urlparse(str((cfg.get("web") or {}).get("public_url") or ""))
        if pu.scheme != "https" or not pu.hostname:
            who = "web" if "web" in on else "remote"
            raise ModuleError(f"{who} needs web.public_url set to the https address people will use "
                              "(e.g. https://mcp.example.com/filament)")
    if "web" in on:                             # A-M5: a bad entry would crash the web unit on every start
        lan = (cfg.get("web") or {}).get("lan")
        if not isinstance(lan, list):
            raise ModuleError("web.lan must be a list of networks such as 192.168.1.0/24")
        for entry in lan:
            try:
                ipaddress.ip_network(str(entry) if isinstance(entry, str) else "", strict=False)
            except ValueError:
                raise ModuleError(f"web.lan entry {entry!r} is not a network such as 192.168.1.0/24") from None
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


# ---------- the checklist menu (spec R section 2.3) ----------

def needs_of(name: str) -> list[str]:
    """What `name` needs, for display: its module dependencies, then its free-text needs."""
    m = MODULES[name]
    out = list(m.depends)
    if m.needs_text:
        out.append(m.needs_text)
    return out


def needs_closure(names, on=frozenset()) -> list[str]:
    """Modules (registry order) that must also be on for `names`, not counting those already in `on`/`names`."""
    chosen = set(names)
    want = set(chosen)
    todo = list(chosen)
    while todo:
        for d in MODULES[todo.pop()].depends:
            if d not in want:
                want.add(d)
                todo.append(d)
    return [n for n in MODULES if n in want and n not in on and n not in chosen]


def dependents_closure(name: str, on) -> list[str]:
    """Enabled modules (registry order) that need `name`, directly or through another module."""
    gone = {name}
    changed = True
    while changed:
        changed = False
        for n, m in MODULES.items():
            if n in on and n not in gone and gone & set(m.depends):
                gone.add(n)
                changed = True
    return [n for n in MODULES if n in gone and n != name]


def toggle(on, name: str) -> tuple[frozenset[str], list[str]]:
    """Flip `name`. On: its needs go on too; off: whatever needs it goes off. Returns (new set, messages)."""
    if name not in MODULES:
        raise ModuleError(f"unknown module {name!r}")
    on = frozenset(on)
    if name in on:
        gone = dependents_closure(name, on)
        notes = [f"Turned off {name}; that also turns off: {', '.join(gone)}."] if gone else []
        return on - set(gone) - {name}, notes
    extra = needs_closure([name], on)
    notes = []
    if extra:
        notes = [f"Turned on {name}; it needs {', '.join(extra)}, now on too."]
    return on | {name} | set(extra), notes


def preset(on, mode: str) -> tuple[frozenset[str], list[str]]:
    """The module set of install mode `mode`, keeping opt-ins already on (as set_mode does)."""
    notes: list[str] = []
    cfg = set_mode({"modules": {n: True for n in on}}, mode, say=notes.append)
    result = enabled(cfg)
    if mode == "station" and frozenset(on) == LEGACY:     # set_mode's rule for a legacy config going to station
        result = result - {"library"}
    return result, notes


def menu_lines(cfg: dict, on=None) -> list[str]:
    """The checklist, one line per module in registry order. `on` overrides the set read from cfg."""
    on = enabled(cfg) if on is None else frozenset(on)
    width = max(len(n) for n in MODULES)
    dw = max(len(m.description) for m in MODULES.values())
    lines = []
    for i, (n, m) in enumerate(MODULES.items(), 1):
        line = f" [{'x' if n in on else ' '}] {i:>2} {n:<{width}}  {m.description:<{dw}}"
        needs = needs_of(n)
        if needs:
            line += "  needs: " + ", ".join(needs)
        if m.optional_ai:
            line += "   OPTIONAL AI"
        lines.append(line.rstrip())
    return lines


PRESET_KEYS = {"a": "all-in-one", "s": "server", "t": "station"}
MENU_HELP = ("Type a number to switch a module on or off (several: 2 5 7). "
             "a = all-in-one, s = server, t = station preset. Enter applies; q cancels.")


def run_checklist(on, ask: Callable[[str], str | None], say: Callable[[str], None] = print) -> frozenset[str] | None:
    """Interactive checklist. `ask(prompt)` returns a line (None = EOF = cancel). Returns the chosen set, or
    None when cancelled."""
    on = frozenset(on)
    names = list(MODULES)
    say(MENU_HELP)
    while True:
        for line in menu_lines({}, on):
            say(line)
        raw = ask("> ")
        if raw is None or raw.strip().lower() in ("q", "quit", "0"):
            return None
        raw = raw.strip().lower()
        if not raw:
            return on
        for tok in raw.replace(",", " ").split():
            if tok in PRESET_KEYS:
                on, notes = preset(on, PRESET_KEYS[tok])
                say(f"Preset {PRESET_KEYS[tok]}.")
            elif tok.isdigit() and 1 <= int(tok) <= len(names):
                on, notes = toggle(on, names[int(tok) - 1])
            elif tok in MODULES:
                on, notes = toggle(on, tok)
            else:
                say(f"Unknown choice {tok!r}.")
                continue
            for note in notes:
                say(note)


def close_selection(names) -> tuple[frozenset[str], list[str]]:
    """A name list (e.g. --modules a,b) plus everything it needs; unknown names raise ModuleError."""
    names = [n.strip() for n in names if n.strip()]
    for n in names:
        if n not in MODULES:
            raise ModuleError(f"unknown module {n!r}")
    extra = needs_closure(names)
    notes = [f"{', '.join(extra)} also turned on (needed by the modules you chose)."] if extra else []
    return frozenset(names) | set(extra), notes


# ---------- settings a module needs before it can start (asked in the checklist) ----------

def _lookup(cfg: dict, key: str):
    cur = cfg
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def set_setting(cfg: dict, key: str, value: str) -> None:
    """Store a collected setting in cfg (in place). station.allow is a one-address list."""
    parts = key.split(".")
    cur = cfg
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = [value] if key == "station.allow" else value


def check_setting(key: str, value: str) -> str | None:
    """Error text for a bad value, or None."""
    value = value.strip()
    if key == "web.public_url":
        pu = urlparse(value)
        if pu.scheme != "https" or not pu.hostname:
            return "Give the https address people will use, e.g. https://mcp.example.com/filament"
    elif key == "orders.file":
        if not value:
            return "Give the path of the order history file."
    elif key == "station.allow":
        if _bad_allow(value):
            return "Enter a single address or host name, not a range or wildcard."
        if value in _LOCAL_HOSTS:
            return "A station without a local server needs the address of the machine the server runs on."
    return None


_SETTING_PROMPTS = {
    "web.public_url": "web needs its public https address (e.g. https://mcp.example.com/filament): ",
    "orders.file": "orders needs the path of the order history file: ",
    "station.allow": "station without the server needs the server's address (IP or host name): ",
}


def missing_settings(on, cfg: dict) -> list[str]:
    """Setting keys (stable order) that modules in `on` need and cfg does not have yet."""
    out = []
    if ("web" in on or "remote" in on) and check_setting("web.public_url", str(_lookup(cfg, "web.public_url") or "")):
        out.append("web.public_url")
    if "orders" in on and not _lookup(cfg, "orders.file"):
        out.append("orders.file")
    if "station" in on and "server" not in on:
        allow = _lookup(cfg, "station.allow") or []
        if not any(str(e).strip() not in _LOCAL_HOSTS for e in allow):
            out.append("station.allow")
    return out


def collect_settings(on, cfg: dict, ask: Callable[[str], str | None],
                     say: Callable[[str], None] = print) -> dict[str, str] | None:
    """Ask for each missing setting, validating the answer; returns {key: value}. A blank answer (or EOF)
    gives None: the caller goes back to the checklist."""
    got: dict[str, str] = {}
    work = copy.deepcopy(cfg)
    for key in missing_settings(on, work):
        while True:
            raw = ask(_SETTING_PROMPTS[key])
            if raw is None or not raw.strip():
                return None
            err = check_setting(key, raw)
            if err:
                say(err)
                continue
            got[key] = raw.strip()
            set_setting(work, key, raw.strip())
            break
    return got
