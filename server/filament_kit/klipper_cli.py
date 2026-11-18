"""`spoolwarden klipper add-on` and the Klipper halves of the `printer` commands (spec 2026-11-03-klipper-printers
§6, §7; 06 9.2).

    klipper add-on                          print the verified command that installs this version's Klipper add-on
    printer detect                          `detect_printer` below; cli.py asks and names the printer (`printer add
                                            --klipper` and `scan` run the Hub's own routes, cli.py).
                                            The old `klipper add|scan|detect|set|api-key|pack` are aliases: `run` hands
                                            them to the printer commands (06 4)

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
import urllib.parse

from . import config, output, pairing, release, spools_cli, updates
from .bridge import registry
from .bridge.klipper import detect as kdetect
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


ADD_ON_INTRO = ("Installs the spool macros and filament-kit's Moonraker settings on a Klipper printer. Run these on the "
                "printer:")        # the Hub page's sentence (strings.js cli_klipper_add_on_intro)


def pack(cfg: dict | None = None, *, fetcher: release.Fetcher | None = None) -> int:
    """`klipper add-on` (06 9.2): the Hub page's sentence and the add-on's install command, pinned to this kit's version
    and to the add-on's SHA-256 from the release's signed SHA256SUMS, each command on its own unbroken line. Prints no
    command at all when that hash cannot be had."""
    version = updates.current_version()
    try:
        info = pack_info(version, cfg, fetcher=fetcher)
    except ReleaseError as e:
        output.error(f"cannot give a verified printer-pack command for filament-kit {version}: {e}",
                     "the pack's hash comes only from the signed release of this exact version (a "
                     "development build has none), so there is nothing to run.")
        return output.FAILED
    output.emit({"ok": True, **info})
    output.out(ADD_ON_INTRO)
    output.out()
    output.out_lines(info["lines"])      # a command is never wrapped
    return 0


def dash(value: str) -> str:
    """The value of an option that takes a secret (06 8.7): only `-`, and the secret comes on standard input. One
    typed on the command line would show to the other users of the machine."""
    if value != "-":
        raise argparse.ArgumentTypeError("a secret is never given on the command line: give - and type it on "
                                         "standard input")
    return value


def add_parser(sub) -> None:
    kp = sub.add_parser("klipper", help="the Klipper add-on (the old spellings of the printer commands still work)")
    ks = kp.add_subparsers(dest="klipper_cmd", required=True)
    ks.add_parser("add-on", help="print the command that installs the Klipper add-on on a printer")
    ks.add_parser("pack", help=argparse.SUPPRESS)       # the old spellings of 06 4 (`printer add --klipper`, ...)
    a = ks.add_parser("add", help=argparse.SUPPRESS)
    a.add_argument("name")
    a.add_argument("host", help="host name (a *.home.arpa or .local name is best) or address")
    a.add_argument("--port", type=int, default=7125)
    s = ks.add_parser("scan", help=argparse.SUPPRESS)
    s.add_argument("--subnet", help="CIDR to scan, at most a /24 (default: this machine's /24)")
    d = ks.add_parser("detect", help=argparse.SUPPRESS)
    d.add_argument("id")
    st = ks.add_parser("set", help=argparse.SUPPRESS)
    st.add_argument("id")
    st.add_argument("--lane-data", choices=registry.LANE_DATA, required=True,
                    help="publish slots to Moonraker lane_data (auto = multi-tool printers only)")
    k = ks.add_parser("api-key", help=argparse.SUPPRESS)
    k.add_argument("id")
    k.add_argument("--api-key", type=dash, metavar="-", help="give - and type the key on standard input")
    k.add_argument("--clear", action="store_true")
    k.add_argument("-y", "--yes", action="store_true")


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
                                              f"run `spoolwarden klipper api-key {p.serial}`")
        return out
    except MoonrakerError as e:
        out.update(problem="offline", message=f"{e}; the server keeps trying once it runs")
        return out
    m = hw.model(d.model_key)
    out.update(ok=True, model_key=d.model_key, model=m.name, verified=d.verified, system=d.system_key,
               slots=[s.label for s in m.slots], reasons=list(d.reasons), hostname=d.hostname,
               spoolman=_spoolman(client, kit_spoolman, p.host) if spoolman else None)
    return out


def _model_text(d: dict) -> str:
    return f"{d['model']}{'' if d['verified'] else ' (not verified)'}"


def _slots_text(d: dict) -> str:
    return ", ".join(d["slots"]) or "from the printer"


def _describe(p: registry.Printer, added: dict | None = None) -> int:
    """What `printer add --klipper` shows after the result line (06 9.2): what the printer says it is, indented, each
    reason a line further in. `--json`: that answer, inside `added` (what `add` did). A printer that does not answer is
    a note: it is saved, and the Hub keeps trying."""
    with output.wait(f"Asking {registry.display_name(p)}…"):
        d = detect(p, spoolman=False)     # it prints no Spoolman, so a bad config.json must not stop it
    output.emit({**added, "detect": d} if added is not None else d)
    if not d["ok"]:
        output.note(d["message"])
        return 0
    output.out_lines([f"  Model: {_model_text(d)}", f"  Slots: {_slots_text(d)}"])
    output.out_lines([f"    {r}" for r in d["reasons"]])
    return 0


def detect_printer(p: registry.Printer) -> int:
    """`printer detect` (06 9.2): ask the printer again what it is (read only): one result line, the reasons under it,
    the Spoolman warning of the Hub as a note."""
    with output.wait(f"Asking {registry.display_name(p)}…"):
        d = detect(p)
    output.emit(d)
    if not d["ok"]:
        output.error(d["message"])
        return 1
    output.out(f"{registry.display_name(p)}: {_model_text(d)}. Slots: {_slots_text(d)}.")
    output.out_lines([f"    {r}" for r in d["reasons"]])
    warning = (d.get("spoolman") or {}).get("warning")
    if warning:
        output.note(warning)
    return 0


# ---------- the printer commands that call the Hub (R83 10.5): slots, usage, watch ----------
# `api` is the kit API client (cli._server_api()), None when no Hub answers; `printer` is {"serial", "name"} (cli.py
# resolves the name the person typed). Every changing command asks for a dry run, shows it, asks, and then does it.
# The CLI_* constants are catalogue keys in capitals (see spools_cli.py).

CLI_SLOT_LOAD_PREVIEW = "Load spool {n}, {name}, into slot {slot} of {printer}."
CLI_SLOT_LOAD_ASK = "Load spool {n} into slot {slot} of {printer}?"
CLI_SLOT_LOAD_DONE = "Spool {n} is loaded in slot {slot} of {printer}."
CLI_SLOT_LOAD_WAITING = "Waiting for the spool to load in {slot}."
CLI_SLOT_UNLOAD_PREVIEW = "Unload slot {slot} of {printer}: spool {n}, {name}, goes back to {place}."
CLI_SLOT_UNLOAD_ASK = "Unload slot {slot} of {printer}?"
CLI_SLOT_UNLOAD_DONE = "Slot {slot} of {printer} is unloaded. Spool {n} is at {place}."
CLI_SLOT_CLEAR_ASK = "Clear slot {slot}? The Hub forgets the spool recorded here."
CLI_SLOT_CLEAR_ASK_SPOOL = "Clear slot {slot}? The Hub forgets the spool recorded here. {name} goes back to {place}."
CLI_SLOT_CLEAR_DONE = "Slot {slot} of {printer} is cleared."
CLI_SLOT_MOVED_BACK = "Spool {n} goes back to {place}."
CLI_SLOT_WAITING_ENDED = "No spool waits for slot {slot} any more."
CLI_SLOT_WAITING_ENDS = "The spool waiting for slot {slot} stops waiting."
CLI_SLOT_PRINTER_CLEARED = "The slot's setting on the printer is cleared."
CLI_SLOT_NO_SPOOL = "No spool is recorded in slot {slot}."
CLI_SLOT_BAD = "{value} is not a slot of a printer."
CLI_SLOT_BAD_FIX = "see the slots: spoolwarden printer show <name>"
CLI_SLOT_REFUSED = "the Hub did not change slot {slot}: {why}"
CLI_USAGE_EMPTY = "No filament used in the last {days} days."
CLI_USAGE_EMPTY_DEFAULT = "No filament used lately."
CLI_USAGE_NO_SPOOL = "no spool"
CLI_USAGE_UNDONE = "undone"
CLI_USAGE_OBSERVED = "seen only"
CLI_USAGE_DAYS_BAD = "{value} is not a number of days."
CLI_WATCH_STOP = "(Ctrl-C stops)"
CLI_WATCH_NO_STATE = "No state yet."

_SLOT = re.compile(r"[A-Za-z0-9-]{1,16}")


def _slot_call(api, printer: dict, slot: str, action: str, body: dict, dry: bool):
    quote = urllib.parse.quote
    return api.post(f"/api/printers/{quote(printer['serial'], safe='')}/slots/{quote(slot, safe='')}/{action}",
                    {**body, "dry_run": dry})


def _slot_refused(e, slot: str) -> int:
    if getattr(e, "code", None) == "unreachable":
        return spools_cli.fail(e)
    if getattr(e, "http", None) in (400, 404):
        output.error(str(e).rstrip(".") + ".")
        return output.USAGE
    output.error(CLI_SLOT_REFUSED.format(slot=slot, why=str(e).rstrip(".") + "."))
    return output.FAILED


def _spool_label(spool: dict) -> str:
    """Brand and name of a spool: the raw Spoolman spool load and unload answer with, or a spool view."""
    f = spool.get("filament") if isinstance(spool.get("filament"), dict) else None
    if f is not None:
        return f"{(f.get('vendor') or {}).get('name') or ''} {f.get('name') or ''}".strip() or "no name"
    return spools_cli.spool_name(spool)


def _q(name: str) -> str:
    return name if re.fullmatch(r"[\w.-]+", name) else shlex.quote(name)


def cmd_printer_slot(api, printer: dict, action: str, slot: str, spool=None, yes: bool = False) -> int:
    """`printer load|unload|clear <name> <slot> [<spool n>]`: the preview (a dry run), the question, the change."""
    if not _SLOT.fullmatch(slot or ""):
        output.error(CLI_SLOT_BAD.format(value=slot), CLI_SLOT_BAD_FIX)
        return output.USAGE
    body: dict = {}
    if action == "load":
        n = spools_cli._number(spool)
        if n is None:
            output.error(spools_cli.CLI_SPOOL_NUMBER_BAD.format(value=spool), spools_cli.CLI_SPOOL_NOT_FOUND_FIX)
            return output.USAGE
        body = {"spool_id": n}
    if api is None:
        return spools_cli.down()
    from .web.slots import SlotError
    name = printer["name"]
    try:
        plan = _slot_call(api, printer, slot, action, body, True)
    except SlotError as e:
        return _slot_refused(e, slot)
    spool_v = plan.get("spool") or {}
    sid, label = spool_v.get("id"), _spool_label(spool_v)
    back = [m for m in plan.get("moved_back") or [] if isinstance(m, dict)]
    place = next((m.get("location") for m in back if m.get("id") == sid), None) or spool_v.get("location") or "its place"
    if action == "load":
        lines = [CLI_SLOT_LOAD_PREVIEW.format(n=body["spool_id"], name=label, slot=slot, printer=name)]
        lines += [CLI_SLOT_MOVED_BACK.format(n=m.get("id"), place=m.get("location")) for m in back]
        ask = CLI_SLOT_LOAD_ASK.format(n=body["spool_id"], slot=slot, printer=name)
    elif action == "unload":
        lines = [CLI_SLOT_UNLOAD_PREVIEW.format(slot=slot, printer=name, n=sid, name=label, place=place)]
        ask = CLI_SLOT_UNLOAD_ASK.format(slot=slot, printer=name)
    else:
        moved = plan.get("moved_back")
        lines = [] if plan.get("spool") else [CLI_SLOT_NO_SPOOL.format(slot=slot)]
        if plan.get("waiting_ended"):
            lines.append(CLI_SLOT_WAITING_ENDS.format(slot=slot))
        ask = (CLI_SLOT_CLEAR_ASK_SPOOL.format(slot=slot, name=label, place=moved) if plan.get("spool") and moved
               else CLI_SLOT_CLEAR_ASK.format(slot=slot))
    output.out_lines(lines)
    rerun = f"spoolwarden printer {action} {_q(name)} {slot}" + (f" {body['spool_id']}" if body else "")
    rc = spools_cli.confirmed(ask, f"{action} of slot {slot} on {name}", rerun, yes)
    if rc is not None:
        return rc
    try:
        r = _slot_call(api, printer, slot, action, body, False)
    except SlotError as e:
        return _slot_refused(e, slot)
    output.emit(r)
    if action == "load":
        output.out(CLI_SLOT_LOAD_WAITING.format(slot=slot) if r.get("pending") else
                   CLI_SLOT_LOAD_DONE.format(n=body["spool_id"], slot=slot, printer=name))
    elif action == "unload":
        output.out(CLI_SLOT_UNLOAD_DONE.format(slot=slot, printer=name, n=sid, place=r.get("location") or place))
        if r.get("waiting_ended"):
            output.out(CLI_SLOT_WAITING_ENDED.format(slot=slot))
    else:
        output.out(CLI_SLOT_CLEAR_DONE.format(slot=slot, printer=name))
        if r.get("spool") and r.get("moved_back"):
            output.out(CLI_SLOT_MOVED_BACK.format(n=r["spool"].get("id"), place=r["moved_back"]))
        if r.get("waiting_ended"):
            output.out(CLI_SLOT_WAITING_ENDED.format(slot=slot))
        if r.get("printer_cleared"):
            output.out(CLI_SLOT_PRINTER_CLEARED)
    return 0


def _when(at) -> str:
    """A log time as `2026-11-17 14:05` (the Hub's ISO 8601 text, in the time it was written)."""
    m = re.match(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d)", at) if isinstance(at, str) else None
    return f"{m.group(1)} {m.group(2)}" if m else (str(at) if at else "")


def cmd_printer_usage(api, printer: dict, days=None) -> int:
    """`printer usage <name> [--days n]`: the filament the printer used, newest first, with the spool it came off."""
    query = ""
    if days is not None:
        try:
            if not float(days) >= 0:
                raise ValueError
        except (TypeError, ValueError):
            output.error(CLI_USAGE_DAYS_BAD.format(value=days))
            return output.USAGE
        query = "?" + urllib.parse.urlencode({"days": f"{float(days):g}"})
    if api is None:
        return spools_cli.down()
    from .web.slots import SlotError
    try:
        r = api.get(f"/api/printers/{urllib.parse.quote(printer['serial'], safe='')}/usage{query}")
    except SlotError as e:
        return spools_cli.fail(e)
    output.emit(r)
    entries = r.get("entries") or []
    if not entries:
        output.out(CLI_USAGE_EMPTY.format(days=f"{float(days):g}") if days is not None else CLI_USAGE_EMPTY_DEFAULT)
        return 0

    def note(e: dict) -> str:
        return ", ".join(x for x in (CLI_USAGE_UNDONE if e.get("undone") else "",
                                     CLI_USAGE_OBSERVED if e.get("observe") else "", e.get("error") or "") if x)

    def spool_cell(e: dict) -> str:
        if e.get("spool"):
            return f"{e['spool'].get('id')} {spools_cli.spool_name(e['spool'])}"
        return str(e["spool_id"]) if e.get("spool_id") is not None else CLI_USAGE_NO_SPOOL

    output.out_lines(output.table(
        ["When", "Job", "Slot", "Used", "Spool", "Note"],
        [[_when(e.get("at")), e.get("job") or "", e.get("slot") or "", spools_cli.grams(e.get("grams")),
          spool_cell(e), note(e)] for e in entries], long=1, right=(3,)))
    return 0


def _snapshot(r: dict) -> list[str]:
    """The lines of one look at a printer (`GET /api/printers/<id>`): state, job, temperatures, slots."""
    st = r.get("status") or {}
    if not st:
        return [CLI_WATCH_NO_STATE]
    name = (r.get("printer") or {}).get("name") or ""
    state = ", ".join(x for x in (st.get("gcode_state") or st.get("state") or "unknown", st.get("stage")) if x)
    lines = [f"{name}: {state}" if name else state]
    if st.get("job"):
        job = f"  {st['job']}, {st.get('percent') or 0}%"
        if st.get("layer") is not None and st.get("total_layers"):
            job += f", layer {st['layer']} of {st['total_layers']}"
        if st.get("remaining_min"):
            m = int(st["remaining_min"])
            job += f", {m // 60} h {m % 60:02d} min left" if m >= 60 else f", {m} min left"
        lines.append(job)
    temps = st.get("temps") or {}
    nozzles = temps.get("nozzle") or []
    parts = []
    for label, t in ([(f"nozzle {i + 1}" if len(nozzles) > 1 else "nozzle", t) for i, t in enumerate(nozzles)]
                     + [("bed", temps.get("bed")), ("chamber", temps.get("chamber"))]):
        if isinstance(t, dict) and isinstance(t.get("current"), (int, float)):
            tgt = t.get("target")
            parts.append(f"{label} {t['current']:g}" + (f"/{tgt:g}" if isinstance(tgt, (int, float)) and tgt else "") + " °C")
    if parts:
        lines.append("  " + ", ".join(parts))
    rows = []
    for u in st.get("ams") or []:
        for s in u.get("slots") or []:
            spool = s.get("spool") or {}
            what = spool.get("name") or s.get("type") or ("empty" if not s.get("present", True) else "unknown")
            if s.get("pending"):
                what += f" (waiting: spool {s['pending'].get('spool_id')})"
            rows.append([s.get("label", ""), what,
                         spools_cli.grams(spool["remaining_weight"]) if spool.get("remaining_weight") is not None else ""])
    if rows:
        lines += [""] + output.table(["Slot", "Filament", "Left"], rows, long=1, right=(2,))
    return lines


def cmd_printer_watch(api, printer: dict, *, every: float = 2.0, sleep=None, ticks: int | None = None) -> int:
    """`printer show <name> --watch`: the printer's state, asked every `every` seconds until Ctrl-C (`ticks`: at most
    that many looks, for a test). `--json` gives one look and stops."""
    import time
    sleep = sleep or time.sleep
    if api is None:
        return spools_cli.down()
    from .web.slots import SlotError
    at_screen = output.terminal() and not output.plain() and not output.json_mode()
    looks = 0
    try:
        while True:
            try:
                r = api.get(f"/api/printers/{urllib.parse.quote(printer['serial'], safe='')}")
            except SlotError as e:
                return spools_cli.fail(e)
            output.emit(r)
            if output.json_mode():
                return 0
            if at_screen:
                sys.stdout.write("\x1b[H\x1b[J")
            elif looks:
                output.out()
            output.out_lines(_snapshot(r) + ([""] + [CLI_WATCH_STOP] if at_screen else []))
            looks += 1
            if ticks is not None and looks >= ticks:
                return 0
            sleep(every if at_screen else max(every, output.PLAIN_EVERY))
    except KeyboardInterrupt:
        return 0


def add_printer_parsers(psub) -> None:
    """`printer load|unload|clear|usage` (the `--watch` of `printer show` is cli.py's own parser line)."""
    PRINTER = dict(metavar="printer", help="its name, serial or id (or the start of its name)")
    for name, text in (("load", "load a spool into a slot"), ("unload", "take the spool out of a slot"),
                       ("clear", "make the Hub forget which spool is in a slot")):
        p = psub.add_parser(name, help=text)
        p.add_argument("printer", **PRINTER)
        p.add_argument("slot", help="the slot's label, as printer show gives it")
        if name == "load":
            p.add_argument("spool", help="the spool's number")
        p.add_argument("-y", "--yes", action="store_true", help="do not ask")
    u = psub.add_parser("usage", help="the filament the printer used, newest first")
    u.add_argument("printer", **PRINTER)
    u.add_argument("--days", type=float, help="how many days back (default: the last week)")


def run_printer(args, api, printer: dict) -> int:
    """Run one of the commands above on `printer` ({"serial", "name"})."""
    if args.printer_cmd == "usage":
        return cmd_printer_usage(api, printer, args.days)
    return cmd_printer_slot(api, printer, args.printer_cmd, args.slot, getattr(args, "spool", None), args.yes)


def run(args) -> int:
    """The old spellings (06 4): each does what its new spelling does."""
    from . import cli
    c = args.klipper_cmd
    if c in ("pack", "add-on"):
        return pack()
    if c == "add":
        return cli.cmd_printer_add(klipper=True, address=args.host, port=args.port, name=args.name)
    if c == "scan":
        return cli.cmd_printer_scan(args.subnet)
    if c == "detect":
        return cli.cmd_printer_detect(args.id)
    if c == "set":
        return cli.cmd_printer_lane_data(args.id, args.lane_data)
    return cli.cmd_printer_api_key(args.id, args.api_key, args.clear, yes=args.yes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spoolwarden")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add_parser(sub)
    return run(ap.parse_args(["klipper", *(argv or [])]))
