"""The Hub's port (R82 section 1): which port a first install takes, whether a port is taken, the capability drop-in
that lets a unit bind a port below 1024, and the sentences the installer and the port change use.

The code's fallback stays 8710 (`config.DEFAULTS["port"]` is not changed). A first install writes `port` into the config
file; an install whose file has no `port` key keeps 8710, and no update ever moves an existing Hub. The station's
listener (AF2) uses the same free-port test and drop-in text.

Run as a program (`python -I -m filament_kit.hubport state|check|dropin ...`) for install.sh, which is shell: it asks
the questions and prints its own lines, this module answers what it needs to know.

The sentences below are plain constants: step AF5 moves them to the string catalogue.
"""
from __future__ import annotations

import errno
import socket
import sys

# ---- the rules the owner may still change (R82 section 12, open points 1, 2 and 5): each is one place

# open point 1: Remote access's nginx owns 443, so a Hub on 443 and Remote access cannot share a machine.
# True: switching Remote access on is refused while the Hub holds 443, and a first install that chooses Remote access
# takes 8710. False: no refusal, no offer (the alternative: the public address on another port, the router forwarding 443).
REMOTE_EXCLUDES_HUB_443 = True

# open point 2: a port that redirects plain http to the https address. None: nothing listens on port 80 (ruled).
# A number: `firewall_ports` names it too (the redirect itself is not built here).
HTTP_REDIRECT_PORT: int | None = None

# open point 5 (Guided Setup's default answer and what Yes asks) lives in install/install.sh: GUIDED_DEFAULT.

NEW_INSTALL_PORT = 443        # what a first install of the Hub takes when it is free
FALLBACK_PORT = 8710          # what it takes otherwise; also the code's own default (config.DEFAULTS)
STATION_NEW_INSTALL_PORT = 443    # a new Weigh Station install (R82 section 2 point 2)
STATION_FALLBACK_PORT = 5003      # the station's code default, and what it takes beside a Hub or when 443 is taken
LOW_LIMIT = 1024              # below it a unit needs CAP_NET_BIND_SERVICE
HIGH_LIMIT = 65535

FREE, TAKEN, UNSURE = "free", "taken", "unsure"

# ---- texts (AF5 moves these to the catalogue; the installer's own lines are literals in install.sh)
TEXT_NOT_A_NUMBER = "{text!r} is not a port number."
TEXT_RANGE = "Port {port} is not allowed: use 1024 to 65535."
TEXT_RANGE_CHANGE = "Port {port} is not allowed: use 443, or 1024 to 65535."
TEXT_TAKEN = "Port {port} is already in use on this machine."
TEXT_UNSURE = "Port {port} could not be checked: this machine did not say whether it is free."
TEXT_REMOTE_REFUSAL = ("Remote access needs port 443, and the Hub is using it. Move the Hub to another port first: "
                       "Settings > Network and addresses, Hub port.")
TEXT_REMOTE_REFUSAL_SHORT = "Remote access needs port 443, and the Hub is using it"   # the command line's Error text
TEXT_REMOTE_ON_443 = "Remote access is on and uses port 443, so the Hub cannot take it."
TEXT_REMOTE_FIX = "sudo spoolwarden port 8710"
# What each paired device needs after a port change. Proof 3 (R82 s10) failed: the Android app tries discovered hosts on
# its stored port only (Discovery.hosts() drops the port) and Slicer Sync never browses, so the fallback sentence holds.
# After AF7 and AF8 land and a phone is seen finding a moved Hub, TEXT_PAIRED_FOUND replaces its first sentence.
TEXT_PAIRED_FOUND = "Phones and the Slicer Sync PC find the Hub again on your network."
TEXT_PAIRED_AGAIN = "Pair your phones and the Slicer Sync PC again."
TEXT_PAIRED_STATION = "A Weigh Station on another machine must be paired again."
TEXT_PAIRED_DEVICES = f"{TEXT_PAIRED_AGAIN} {TEXT_PAIRED_STATION}"
TEXT_CHANGED = "The Hub now uses port {port}."


# ---- is a port taken

PROC_NET = "/proc/net"        # the kernel's table of sockets (tests point it elsewhere)


def listening(port: int) -> bool | None:
    """Does any socket of this machine listen on `port`, on any address of either family (the kernel's table, which
    anyone may read: it needs no privilege and also sees a listener bound to one address or to IPv6 only). None: the
    table cannot be read (not Linux)."""
    seen = False
    for name in ("tcp", "tcp6"):
        try:
            with open(f"{PROC_NET}/{name}", encoding="ascii") as fh:
                lines = fh.read().splitlines()[1:]
        except (OSError, UnicodeDecodeError):
            continue
        seen = True
        for line in lines:
            f = line.split()
            if len(f) > 3 and f[3] == "0A":          # 0A: LISTEN
                try:
                    if int(f[1].rsplit(":", 1)[1], 16) == port:
                        return True
                except (IndexError, ValueError):
                    continue
    return False if seen else None


def _probe(family: int, port: int) -> str:
    """Bind the wildcard address of one family without keeping it: "ok", "taken", "denied" (the user may not bind
    this port), "absent" (the machine has no such family) or "unsure"."""
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        return "absent"
    try:
        if family == socket.AF_INET6:
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)     # the v4 probe tests the v4 side
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):                         # Windows: REUSEADDR would take it over
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)        # as the Hub binds: a TIME_WAIT is not "taken"
        s.bind(("::" if family == socket.AF_INET6 else "0.0.0.0", port))
        return "ok"
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, 10048):
            return "taken"
        if e.errno in (errno.EACCES, errno.EPERM, 10013):
            return "denied"
        if e.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL, getattr(errno, "EPROTONOSUPPORT", -1)):
            return "absent"
        return "unsure"
    finally:
        s.close()


def port_state(port: int) -> str:
    """FREE, TAKEN or UNSURE for a TCP port, the same way for every kind of listener: another web server, the Hub's
    own nginx, a listener on one address only, an IPv6-only listener. TAKEN when the kernel's table lists a listener on
    it or a bind of the wildcard address (IPv4, then IPv6) finds it in use. FREE when neither does (a bind the user is
    not allowed to try, a port below 1024 for a user who is not root, counts as free when the table could be read).
    UNSURE when neither the table nor the bind says: callers ask the person."""
    table = listening(port)
    if table:
        return TAKEN
    probes = [_probe(socket.AF_INET, port), _probe(socket.AF_INET6, port)]
    if "taken" in probes:
        return TAKEN
    if table is False:
        return FREE
    return UNSURE if any(p in ("denied", "unsure") for p in probes) or probes == ["absent", "absent"] else FREE


def next_free(start: int, *, state=port_state) -> int | None:
    """The first port from `start` up whose state is FREE (UNSURE is not free), or None below 65536."""
    for p in range(max(start, LOW_LIMIT), HIGH_LIMIT + 1):
        if state(p) == FREE:
            return p
    return None


def parse_port(text) -> int | None:
    """A port number from typed text, or None."""
    try:
        n = int(str(text).strip())
    except ValueError:
        return None
    return n if 0 < n <= HIGH_LIMIT else None


def check_port(text, *, current: int | None = None, allow_443: bool = False, state=port_state) -> tuple[int | None, str]:
    """(the port, "") when the typed port may be used, else (None, the reason in a sentence). `current`: the port the
    Hub holds now (it is not "taken" by itself). `allow_443`: the port change allows 443; the installer's question
    does not (443 is what it offers first)."""
    n = parse_port(text)
    if n is None:
        return None, TEXT_NOT_A_NUMBER.format(text=str(text).strip())
    if not (LOW_LIMIT <= n <= HIGH_LIMIT or (allow_443 and n == NEW_INSTALL_PORT)):
        return None, (TEXT_RANGE_CHANGE if allow_443 else TEXT_RANGE).format(port=n)
    if n != current:
        s = state(n)
        if s == TAKEN:
            return None, TEXT_TAKEN.format(port=n)
        if s == UNSURE:
            return None, TEXT_UNSURE.format(port=n)
    return n, ""


# ---- first install: which port, and whether to ask

def offer(remote: bool, *, state=port_state) -> tuple[str, int]:
    """What a first install of the Hub does about its port: (kind, port). ("free", 443): take 443, no question.
    Otherwise the kind says why 443 is not taken ("remote": Remote access's nginx owns it, "taken", "unsure": the test
    could not tell, so the person is asked) and the port is the one offered instead: 8710, or the next free port above
    it when 8710 is taken too."""
    if remote and REMOTE_EXCLUDES_HUB_443:
        kind = "remote"
    else:
        s = state(NEW_INSTALL_PORT)
        if s == FREE:
            return "free", NEW_INSTALL_PORT
        kind = s
    return kind, _offered(FALLBACK_PORT, state)


def station_offer(hub_here: bool, *, state=port_state) -> tuple[str, int]:
    """The same for a new Weigh Station install (R82 section 2 point 2): ("beside", 5003) on a machine that also runs
    the Hub (443 is the Hub's: no question), ("free", 443), or (kind, 5003 or the next free port above it)."""
    if hub_here:
        return "beside", STATION_FALLBACK_PORT
    s = state(STATION_NEW_INSTALL_PORT)
    if s == FREE:
        return "free", STATION_NEW_INSTALL_PORT
    return s, _offered(STATION_FALLBACK_PORT, state)


def _offered(default: int, state) -> int:
    if state(default) == FREE:
        return default
    return next_free(default + 1, state=state) or default


# ---- the capability drop-in: a unit with empty capability sets cannot bind below 1024

HUB_UNIT = "filament-kit.service"
HUB_DROPIN = f"/etc/systemd/system/{HUB_UNIT}.d/port.conf"
CAPABILITY = "CAP_NET_BIND_SERVICE"


def needs_capability(port) -> bool:
    return int(port) < LOW_LIMIT


def capability_lines(port) -> str:
    """The two lines that give a unit exactly CAP_NET_BIND_SERVICE (bounding and ambient), or "" for a port of 1024 or
    more. Proven on a real systemd: the unit then binds 443 as its unprivileged user with NoNewPrivileges=yes and
    the rest of its hardening kept (R82 s10 item 1)."""
    if not needs_capability(port):
        return ""
    return f"CapabilityBoundingSet={CAPABILITY}\nAmbientCapabilities={CAPABILITY}\n"


def dropin_text(port) -> str | None:
    """The Hub unit's drop-in file for `port`, or None: no file (the drop-in is removed; the unit keeps its empty
    capability sets). The station's unit takes the same lines inside its kit.conf (apply.station_dropin)."""
    lines = capability_lines(port)
    return f"[Service]\n{lines}" if lines else None


def remote_conflict(cfg: dict) -> str | None:
    """Why Remote access may not be switched on for this config (the Hub holds 443), or None. `modules.validate`
    raises it, so nothing is changed first."""
    if not REMOTE_EXCLUDES_HUB_443:
        return None
    try:
        port = int(cfg.get("port", FALLBACK_PORT))
    except (TypeError, ValueError):
        return None
    return TEXT_REMOTE_REFUSAL if port == NEW_INSTALL_PORT else None


def url_port(port) -> str:
    """The `:port` an address shows: nothing for 443 (https://<host>.local/), `:8710` otherwise."""
    return "" if int(port) == NEW_INSTALL_PORT else f":{int(port)}"


def firewall_ports(cfg: dict) -> list[str]:
    """The Hub's own ports for the firewall line: its port, mDNS, and the redirect port when open point 2 asks one."""
    ports = [f"{int(cfg.get('port', FALLBACK_PORT))}/tcp", "5353/udp"]
    if HTTP_REDIRECT_PORT:
        ports.append(f"{HTTP_REDIRECT_PORT}/tcp")
    return ports


# ---- changing the port later (also how an existing Hub moves to 443)

class PortError(ValueError):
    """The change is refused; the message is the reason (Error), `fix` the command that helps (Fix) or ""."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


def change_port(text, *, run=None, root=None, state=port_state) -> list[str]:
    """Move the Hub to another port: refuses a port that is taken or not allowed (443, or 1024 to 65535) and 443 while
    Remote access is on, then writes the config, the unit's capability drop-in, the network advert and the station's
    drop-in (a Weigh Station on this machine), restarts the Hub and the web unit and prints the firewall line. Returns
    the lines to show, ending with what each paired device needs. Raises PortError before anything is changed.
    Run as root. `run` and `root` as in apply.execute (tests)."""
    from pathlib import Path
    from . import apply, config, modules
    cfg = config.load()
    current = int(cfg.get("port", FALLBACK_PORT))
    n, why = check_port(text, current=current, allow_443=True, state=state)
    if n is None:
        raise PortError(why)
    if n == NEW_INSTALL_PORT and "remote" in modules.enabled(cfg) and REMOTE_EXCLUDES_HUB_443:
        raise PortError(TEXT_REMOTE_ON_443, "choose another port, or switch Remote access off first")
    cfg["port"] = n
    run = run or apply.run_checked
    ex = apply._Exec(run, config.paths().opt / "resources", Path(root) if root else Path("/"))
    on = modules.enabled(cfg)
    config.save(cfg)
    apply.write_hub_dropin(ex, n)
    apply.write_avahi(ex, n)
    if "station" in on:
        apply.refresh_station(cfg, run=run, root=Path(root) if root else Path("/"))
    ex.cmd(["systemctl", "daemon-reload"])
    ex.cmd(["systemctl", "restart", HUB_UNIT])
    if "web" in on:
        ex.cmd(["systemctl", "restart", apply.WEB_UNIT])
    if not ex.dry:
        apply._firewall_note(cfg, set(on))
    return [TEXT_CHANGED.format(port=n), TEXT_PAIRED_DEVICES]


# ---- the program install.sh calls

def _main(argv: list[str]) -> int:
    """`state PORT` prints free, taken or unsure. `check PORT [change]` exits 0 for a usable port (and prints it), else
    1 with the reason on standard error. `next PORT` prints the first free port from PORT. `offer remote|plain` and `station-offer hub|alone` print
    "<kind> <port>" (see `offer`): the installer's first-install decision."""
    if len(argv) >= 2 and argv[0] == "state" and parse_port(argv[1]):
        print(port_state(int(argv[1])))
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        n, why = check_port(argv[1], allow_443="change" in argv[2:])
        if n is None:
            print(why, file=sys.stderr)
            return 1
        print(n)
        return 0
    if len(argv) == 2 and argv[0] == "offer" and argv[1] in ("remote", "plain"):
        print(*offer(argv[1] == "remote"))
        return 0
    if len(argv) == 2 and argv[0] == "station-offer" and argv[1] in ("hub", "alone"):
        print(*station_offer(argv[1] == "hub"))
        return 0
    if len(argv) >= 2 and argv[0] == "next" and parse_port(argv[1]):
        n = next_free(int(argv[1]))
        if n is None:
            return 1
        print(n)
        return 0
    print("usage: python -I -m filament_kit.hubport state PORT | check PORT [change] | next PORT | offer remote|plain | "
          "station-offer hub|alone", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
