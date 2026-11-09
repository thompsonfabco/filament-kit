"""`filament-kit klipper ...`: Klipper/Moonraker printers (spec 2026-11-03-klipper-printers §6, §7).

    klipper add NAME HOST [--port 7125]     add a printer by host name and show what it is
    klipper scan [--subnet CIDR]            look for Moonraker on this machine's /24 (or CIDR); found ones are listed
    klipper detect ID                       ask the printer again what it is (read only)
    klipper set ID --lane-data auto|on|off  publishing slots to Moonraker lane_data
    klipper api-key ID                      store a Moonraker API key (asked, never echoed; empty clears it)
    klipper pack                            print the verified command that installs this version's printer pack

All read-only towards the printer except what the running server does later. Kept in its own module so cli.py only
hooks it in (`add_parser`, `run`).

The web console calls the data-returning halves; the CLI prints from them, with the same text as before:
    detect(p) -> dict           what `klipper add` / `detect` show, plus the Spoolman Moonraker reports to
    pack_info(version, cfg, spoolman_url=, allow=) -> {version, sha256, url, lines}   the checked command (raises
                                ReleaseError); the two values, when given, are written into its install line
    pack_spoolman(kit_url, printer_host) -> {url, choices, allow, problem}   what to give pack_info for this printer
"""
from __future__ import annotations

import argparse
import ipaddress
import re
import shlex
import socket
import sys
from getpass import getpass

from . import config, hostaddr, pairing, release, updates
from .bridge import registry
from .bridge.klipper import detect as kdetect
from .bridge.klipper import discovery
from .bridge.klipper import hardware as kh
from .bridge.klipper import usage as kusage
from .bridge.klipper.moonraker import Moonraker, MoonrakerError, Unauthorized
from .release import ReleaseError

PACK = "fk-printer-pack.tar.gz"
PACK_URL = re.compile(r"https?://[A-Za-z0-9._\-\[\]:]+(/[A-Za-z0-9._~/\-]*)?")     # no user, no password, no shell
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")     # as release.Fetcher.release checks it


def pack_url(version: str, repo: str = release.REPO) -> str:
    """The printer pack of release v<version> (the running kit's own version, never a moving tag) in `repo`,
    the same repo `_signed_table` takes the hash from."""
    return f"https://github.com/{repo}/releases/download/v{version}/{PACK}"


def _signed_table(version: str, cfg: dict, fetcher: release.Fetcher | None) -> dict[str, str]:
    """The signature-checked SHA256SUMS table of release `version`: the kept copy in the updater's store when
    it has both files (a kept copy that fails the check is an error, not a reason to go to the network),
    else both files fetched for tag v<version>. Raises ReleaseError."""
    kept = updates.store() / version
    sums, sig = kept / release.SUMS, kept / release.SIG
    if sums.is_file() and sig.is_file():
        try:
            return release.verify_sums(sums.read_bytes(), sig.read_bytes())
        except ReleaseError as e:
            raise ReleaseError(f"the kept release in {kept}: {e}") from None
    # `updates.api` (a test server, docs/testing-e2e.md) changes only where the hash is fetched; the printed URL
    # always points at GitHub, so with a test server the printer's check fails and nothing runs.
    f = fetcher or updates.default_fetcher(cfg)
    rel = f.release(updates.settings(cfg)["repo"], version=version)
    for need in (release.SUMS, release.SIG):
        if need not in rel["assets"]:
            raise ReleaseError(f"release {version} has no {need}")
    return release.verify_sums(f.get(rel["assets"][release.SUMS], release.LIMIT_SUMS),
                               f.get(rel["assets"][release.SIG], release.LIMIT_SIG))


def pack_spoolman(kit_url: str | None, printer_host: str) -> dict:
    """What to give pack_info for this printer: {"url": the kit's Spoolman as the printer reaches it, or None; "choices":
    the URLs to choose from when that can't be decided; "allow": the kit's own address on the printer's network, for
    lasttag; "problem": None | "password" | "unreadable" | "no_address"}. `spoolman_url` as written unless it's loopback,
    which on the printer would mean the printer: then the kit's LAN address on the printer's /24. A URL holding a
    password isn't for a line people copy, and is refused rather than stripped."""
    out = {"url": None, "choices": [], "allow": [], "problem": None}
    url = (kit_url or "").strip()
    hp = kusage._host_port(url)
    if "@" in url.partition("://")[2]:
        return {**out, "problem": "password"}
    if hp is None or not PACK_URL.fullmatch(url):
        return {**out, "problem": "unreadable"}
    ips = pairing.local_ips()
    try:
        printer = {a[4][0] for a in socket.getaddrinfo(printer_host.strip("[]"), None, socket.AF_INET)}
        nets = {ipaddress.ip_network(f"{a}/24", strict=False) for a in printer}
    except (OSError, UnicodeError):
        nets = set()
    near = [i for i in ips if any(ipaddress.ip_address(i) in n for n in nets)]
    if not kusage._names_loopback(url):
        return {**out, "url": url, "allow": near[:1]}
    if not ips:
        return {**out, "problem": "no_address"}
    scheme = url.partition("://")[0]
    if len(near) == 1:
        return {**out, "url": f"{scheme}://{near[0]}:{hp[1]}", "allow": near}
    return {**out, "choices": [f"{scheme}://{i}:{hp[1]}" for i in (near or ips)]}


def _is_ip(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return "%" not in value     # a scope id isn't an address lasttag would see, and it has no place in a shell line


def pack_info(version: str, cfg: dict | None = None, *, fetcher: release.Fetcher | None = None,
              spoolman_url: str | None = None, allow=()) -> dict:
    """The printer-pack install command for release `version`, pinned to the pack's SHA-256 from that release's
    signed SHA256SUMS (the signature is checked here): {version, sha256, url, lines} with `lines` the commands
    to run on the printer, one per line. `spoolman_url` and `allow` (see pack_spoolman), when given, go into the install
    line; it never carries --yes or --parts: the pack still asks about each part and shows each edit. Raises ReleaseError
    (a development build, no signed release, a bad signature, the pack not listed, no network, a value that isn't a plain
    address): then there is no command at all."""
    if spoolman_url and not PACK_URL.fullmatch(spoolman_url):       # the value may hold a password: never in the error
        raise ReleaseError("the Spoolman URL for the printer must be a plain http:// or https:// address, with no "
                           "user or password")
    if any(not _is_ip(h) for h in allow):
        raise ReleaseError("each address lasttag allows must be an IP address: it compares them as text, so a name "
                           "would lock the kit out")
    options = (f" --spoolman {shlex.quote(spoolman_url)}" if spoolman_url else "") + (
        f" --allow {shlex.quote(','.join(allow))}" if allow else "")
    try:
        release.parse_version(version)
        cfg = cfg if cfg is not None else config.load()
        repo = updates.settings(cfg)["repo"]        # one repo for the hash and the URL
        # it goes into a shell line, and a kept copy never reaches the fetcher's own check
        if not isinstance(repo, str) or not REPO_NAME.fullmatch(repo):
            raise ReleaseError(f"bad repo name {repo!r} (owner/name)")
        table = _signed_table(version, cfg, fetcher)
    except (OSError, ValueError) as e:
        raise ReleaseError(str(e)) from None
    want = table.get(PACK)
    if want is None:
        raise ReleaseError(f"the signed {release.SUMS} does not list {PACK}")
    url = pack_url(version, repo)
    return {"version": version, "sha256": want, "url": url, "lines": [
        f"curl -fsSLo {PACK} {url}",
        f'echo "{want}  {PACK}" | sha256sum -c - && tar xzf {PACK} && sh fk-printer-pack/fk-printer-pack.sh install{options}']}


def pack(cfg: dict | None = None, *, fetcher: release.Fetcher | None = None) -> int:
    """Print the printer-pack install command, pinned to this kit's version and to the pack's SHA-256 from the
    release's signed SHA256SUMS. Prints no command at all when that hash cannot be had."""
    version = updates.current_version()
    try:
        info = pack_info(version, cfg, fetcher=fetcher)
    except ReleaseError as e:
        print(f"error: cannot give a verified printer-pack command for filament-kit {version}: {e}",
              file=sys.stderr)
        print("error: the pack's hash comes only from the signed release of this exact version (a "
              "development build has none); nothing to run", file=sys.stderr)
        return 1
    print("Run this on the printer (as its normal user, not root):")
    for line in info["lines"]:
        print(f"  {line}")
    print(f"The hash is the one in the signed {release.SUMS} of release v{version} (checked here against the "
          "filament-kit release key); nothing is unpacked or run unless the download matches it.")
    return 0


def add_parser(sub) -> None:
    kp = sub.add_parser("klipper", help="Klipper/Moonraker printers: add, scan, detect, lane_data, API key, pack")
    ks = kp.add_subparsers(dest="klipper_cmd", required=True)
    a = ks.add_parser("add", help="add a Klipper printer by its Moonraker host name")
    a.add_argument("name")
    a.add_argument("host", help="host name (a *.home.arpa or .local name is best) or address")
    a.add_argument("--port", type=int, default=7125)
    s = ks.add_parser("scan", help="look for Moonraker on the LAN (only when you run it)")
    s.add_argument("--subnet", help="CIDR to scan, at most a /24 (default: this machine's /24)")
    d = ks.add_parser("detect", help="ask a printer what it is (read only)")
    d.add_argument("id")
    st = ks.add_parser("set", help="change a Klipper printer's settings")
    st.add_argument("id")
    st.add_argument("--lane-data", choices=registry.LANE_DATA, required=True,
                    help="publish slots to Moonraker lane_data (auto = multi-tool printers only)")
    k = ks.add_parser("api-key", help="store the printer's Moonraker API key (asked, not echoed)")
    k.add_argument("id")
    ks.add_parser("pack", help="print the command that installs the printer pack on a printer")


def _spoolman(client: Moonraker, kit_url: str | None, printer_host: str) -> dict | None:
    """The Spoolman Moonraker reports usage to, as host:port (never the URL: it may carry a password); whether it is
    the kit's own (config's spoolman_url when `kit_url` is None): `same_as_kit`, and `match` same | different | unknown
    (None when there's nothing to compare); `connected`, Moonraker's word on reaching it (None when it won't say); and
    the server's warning line. None when that is not known: Moonraker would not give its config, gave an odd one, or
    the kit's own config cannot be read."""
    try:
        if kit_url is None:
            kit_url = config.load().get("spoolman_url")
        cfg = client.server_config()
    except (MoonrakerError, OSError, ValueError, TypeError, AttributeError):
        return None
    section = cfg.get("spoolman", {})
    if not isinstance(section, dict):
        return None
    report = kusage.spoolman_report(cfg, kit_url, printer_host)
    connected = kusage.spoolman_connected(client)
    return {"server": report["server"], "same_as_kit": report["match"] == "same", "match": report["match"],
            "connected": connected, "warning": kusage.with_connection(report["warning"], connected)}


def detect(p: registry.Printer, *, kit_spoolman: str | None = None, spoolman: bool = True,
           client_factory=Moonraker) -> dict:
    """Ask the printer what it is (read only): the model and its slots, the filament system (single, AFC, Happy
    Hare, tool macros ...), why, and the Spoolman Moonraker reports to (compared with `kit_spoolman`, the kit's
    own; config's spoolman_url when not given; `spoolman` False skips this, and the result's "spoolman" is None).
    `ok` False with `problem` "api_key" (Moonraker wants one) or "offline" (any other Moonraker error) and `message`
    the line the CLI prints; the API key is never in it."""
    out = {"ok": False, "problem": None, "message": "", "id": p.serial, "host": p.host, "port": p.port,
           "model_key": None, "model": None, "verified": None, "system": None, "slots": [], "reasons": [],
           "hostname": "", "spoolman": None}
    hw = kh.load()
    client = client_factory(p.host, p.port, api_key=p.api_key, timeout=5)
    try:
        d = kdetect.probe(client, hw)
    except Unauthorized:
        out.update(problem="api_key", message=f"{p.host}:{p.port} wants a Moonraker API key: "
                                              f"run `filament-kit klipper api-key {p.serial}`")
        return out
    except MoonrakerError as e:
        out.update(problem="offline", message=f"{e}; the server keeps trying once it runs")
        return out
    m = hw.model(d.model_key)
    out.update(ok=True, model_key=d.model_key, model=m.name, verified=d.verified, system=d.system_key,
               slots=[s.label for s in m.slots], reasons=list(d.reasons), hostname=d.hostname,
               spoolman=_spoolman(client, kit_spoolman, p.host) if spoolman else None)
    return out


def _describe(p: registry.Printer) -> int:
    d = detect(p, spoolman=False)     # it prints no Spoolman, so a bad config.json must not stop it
    if not d["ok"]:
        print(f"  {d['message']}")
        return 0
    print(f"  model: {d['model']} ({d['model_key']}){'' if d['verified'] else ' - unverified entry'}")
    print(f"  filament system: {d['system']}; slots: {', '.join(d['slots']) or 'from the printer'}")
    for r in d["reasons"]:
        print(f"    {r}")
    return 0


def run(args) -> int:
    c = args.klipper_cmd
    if c == "add":
        host = hostaddr.clean(args.host)
        bad = hostaddr.form_error(host)
        if bad:
            print(f"error: {bad}", file=sys.stderr)
            return 1
        seen = hostaddr.inspect(host)       # a name that won't resolve is still saved: the printer may just be off
        try:
            p = discovery.add(args.name, host, args.port)
        except registry.DuplicatePrinter as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"added {registry.display_name(p)} as {p.serial} ({p.host}:{p.port})")
        if seen.problem or seen.note:
            print(f"note: {seen.problem or seen.note}")
        return _describe(p)
    if c == "scan":
        try:
            net = ipaddress.ip_network(args.subnet, strict=False) if args.subnet else discovery.own_subnet()
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if net is None:
            print("error: cannot tell this machine's network; give --subnet", file=sys.stderr)
            return 1
        try:
            found = discovery.scan(net, port=discovery.DEFAULT_PORT)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not found:
            print(f"no Moonraker found on {net}")
            return 0
        added = discovery.added_at()
        for host, port in found:
            p = added.get((host, port)) or registry.detected_klipper(host, port)
            state = (f"added already as {registry.display_name(p)}" if p.configured
                     else f"add it: filament-kit klipper add NAME {host}")
            print(f"{host}:{port}  ({state})")
        return 0
    p = registry.load().get(getattr(args, "id", "") or "")
    if c == "pack":
        return pack()
    if p is None or p.family != "klipper":
        print(f"error: no Klipper printer {getattr(args, 'id', '')!r}", file=sys.stderr)
        return 1
    if c == "detect":
        print(f"{registry.display_name(p)} ({p.host}:{p.port})")
        return _describe(p)
    if c == "set":
        registry.set_lane_data(p.serial, args.lane_data)
        print(f"{registry.display_name(p)}: lane_data {args.lane_data}")
        return 0
    if c == "api-key":
        key = getpass("Moonraker API key (empty clears it): ")
        registry.set_api_key(p.serial, key)
        print(f"{registry.display_name(p)}: API key {'stored' if key.strip() else 'cleared'}")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="filament-kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add_parser(sub)
    return run(ap.parse_args(["klipper", *(argv or [])]))
