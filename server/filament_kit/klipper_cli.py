"""`filament-kit klipper ...`: Klipper/Moonraker printers (spec 2026-11-03-klipper-printers §6, §7).

    klipper add NAME HOST [--port 7125]     add a printer by host name and show what it is
    klipper scan [--subnet CIDR]            look for Moonraker on this machine's /24 (or CIDR); found ones are listed
    klipper detect ID                       ask the printer again what it is (read only)
    klipper set ID --lane-data auto|on|off  publishing slots to Moonraker lane_data
    klipper api-key ID                      store a Moonraker API key (asked, never echoed; empty clears it)
    klipper pack                            print the verified command that installs this version's printer pack

All read-only towards the printer except what the running server does later. Kept in its own module so cli.py only
hooks it in (`add_parser`, `run`).
"""
from __future__ import annotations

import argparse
import ipaddress
import sys
from getpass import getpass

from . import config, release, updates
from .bridge import registry
from .bridge.klipper import detect, discovery
from .bridge.klipper import hardware as kh
from .bridge.klipper.moonraker import Moonraker, MoonrakerError, Unauthorized
from .release import ReleaseError

PACK = "fk-printer-pack.tar.gz"


def pack_url(version: str) -> str:
    """The printer pack of release v<version> (the running kit's own version, never a moving tag)."""
    return f"https://github.com/{release.REPO}/releases/download/v{version}/{PACK}"


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
    f = fetcher or updates.default_fetcher(cfg)
    rel = f.release(updates.settings(cfg)["repo"], version=version)
    for need in (release.SUMS, release.SIG):
        if need not in rel["assets"]:
            raise ReleaseError(f"release {version} has no {need}")
    return release.verify_sums(f.get(rel["assets"][release.SUMS], release.LIMIT_SUMS),
                               f.get(rel["assets"][release.SIG], release.LIMIT_SIG))


def pack(cfg: dict | None = None, *, fetcher: release.Fetcher | None = None) -> int:
    """Print the printer-pack install command, pinned to this kit's version and to the pack's SHA-256 from the
    release's signed SHA256SUMS. Prints no command at all when that hash cannot be had."""
    version = updates.current_version()
    try:
        release.parse_version(version)
        table = _signed_table(version, cfg if cfg is not None else config.load(), fetcher)
        want = table.get(PACK)
        if want is None:
            raise ReleaseError(f"the signed {release.SUMS} does not list {PACK}")
    except (ReleaseError, OSError, ValueError) as e:
        print(f"error: cannot give a verified printer-pack command for filament-kit {version}: {e}",
              file=sys.stderr)
        print("error: the pack's hash comes only from the signed release of this exact version (a "
              "development build has none); nothing to run", file=sys.stderr)
        return 1
    print("Run this on the printer (as its normal user, not root):")
    print(f"  curl -fsSLo {PACK} {pack_url(version)}")
    print(f'  echo "{want}  {PACK}" | sha256sum -c - && tar xzf {PACK} '
          f"&& sh fk-printer-pack/fk-printer-pack.sh install")
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


def _describe(p: registry.Printer) -> int:
    try:
        d = detect.probe(Moonraker(p.host, p.port, api_key=p.api_key, timeout=5), kh.load())
    except Unauthorized:
        print(f"  {p.host}:{p.port} wants a Moonraker API key: run `filament-kit klipper api-key {p.serial}`")
        return 0
    except MoonrakerError as e:
        print(f"  {e}; the server keeps trying once it runs")
        return 0
    m = kh.load().model(d.model_key)
    print(f"  model: {m.name} ({d.model_key}){'' if d.verified else ' - unverified entry'}")
    print(f"  filament system: {d.system_key}; slots: {', '.join(s.label for s in m.slots) or 'from the printer'}")
    for r in d.reasons:
        print(f"    {r}")
    return 0


def run(args) -> int:
    c = args.klipper_cmd
    if c == "add":
        p = registry.add_klipper(args.name, args.host, args.port)
        print(f"added {registry.display_name(p)} as {p.serial} ({p.host}:{p.port})")
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
        for host, port in found:
            p = registry.detected_klipper(host, port)
            state = "added already" if p.configured else f"add it: filament-kit klipper add NAME {host}"
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
