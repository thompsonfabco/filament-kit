"""What `spoolwarden status` and `web status` check, as data: rows the CLI prints and the setup console's Overview
shows. `rows()` yields as it goes, so the terminal shows each line when its check ends; `collect()` is the list.

A row's text may hold addresses (Spoolman's URL, the station's, the public URL). The console's Overview answers without
the setup code, so it shows them through `redact.text` unless the code was given.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from typing import Iterable, Iterator

from . import config, modules, output, pairing, remote

OK, FAIL, INFO, DETAIL = "ok", "fail", "info", "detail"
_MARKS = {"OK": OK, "--": INFO}


@dataclass(frozen=True)
class Row:
    state: str              # ok, fail, info (a note, not a check), detail (a line under the row before)
    text: str
    fix: str = ""
    action: str = ""        # what the console can do about it, by its own name ("" = nothing)
    group: str = ""         # the heading the Overview files it under (06 section 13); `print_rows` does not print it
    key: str = ""           # who the row is, the same whether it is OK or needs a look: `<group>.<name>`, unique in a run


def _in(group: str, source: Iterable[Row]) -> Iterator[Row]:
    """The rows of `source` filed under `group`; a row that already has a group keeps it."""
    for r in source:
        yield r if r.group else replace(r, group=group)


# The headings of the Hub page's Overview, in its order (06 section 9.1); a row's group is one of these
GROUPS = ("Hub", "Spoolman", "Label Reader", "Weigh Station", "Devices", "Printers", "Slicer presets", "Filament Catalog")
_WORDS = {OK: "OK", FAIL: "needs a look", INFO: "note"}      # 06 6.1: the code's values as the words people read


def _grouped(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    """The rows under their headings, the groups in the Overview's order and the rows of each in the order they came.
    Rows with no group (`web status`) come last, with no heading."""
    known = {g: [r for r in rows if r.group == g] for g in GROUPS}
    other = [r for r in rows if r.group not in known]
    return [(g, rs) for g, rs in known.items() if rs] + ([("", other)] if other else [])


def _fours(text: str) -> str:
    """A long run of hex digits (a certificate fingerprint) in groups of four, which can be read aloud and wrapped
    (CLI-9, 06 9.4); nothing else is touched."""
    return re.sub(r"[0-9A-Fa-f]{32,}", lambda m: " ".join(m[0][i:i + 4] for i in range(0, len(m[0]), 4)), text)


def header_line(cfg: dict | None = None) -> str:
    """`Spoolwarden 0.5.2 · Workshop hub · server`: the version, the Hub's display name and the setup."""
    from . import updates
    cfg = cfg if cfg is not None else config.load()
    sep = output.sym("sep")
    return sep.join([f"Spoolwarden {updates.current_version()}", str(cfg.get("server_name") or "Hub"),
                     modules.mode_of(modules.enabled(cfg))])


def summary_line(rows: Iterable[Row]) -> str:
    """`2 need a look · 9 OK · 3 notes`: the rows counted by their word, none left out that has a count."""
    n = {w: 0 for w in _WORDS.values()}
    for r in rows:
        if r.state in _WORDS:
            n[_WORDS[r.state]] += 1
    parts = [f"{n['needs a look']} need{'s' if n['needs a look'] == 1 else ''} a look" if n["needs a look"] else "",
             f"{n['OK']} OK" if n["OK"] else "",
             f"{n['note']} note{'' if n['note'] == 1 else 's'}" if n["note"] else ""]
    return output.sym("sep").join(p for p in parts if p) or "No rows"


def row_dicts(rows: Iterable[Row]) -> list[dict]:
    """The rows as the Overview's reply holds them (`GET /setup/api/overview`): state, text, fix, action, group."""
    return [asdict(r) for r in rows]


def summary_counts(rows: Iterable[Row]) -> dict:
    """The summary line's counts, for `--json`: rows that need a look, rows that are fine, notes."""
    n = {w: 0 for w in _WORDS}
    for r in rows:
        if r.state in n:
            n[r.state] += 1
    return {"needs_a_look": n[FAIL], "ok": n[OK], "notes": n[INFO]}


def _needing_a_look(rows: list[Row]) -> list[Row]:
    """`--quiet`: the rows that need a look, each with the detail lines under it."""
    keep, on = [], False
    for r in rows:
        if r.state != DETAIL:
            on = r.state == FAIL
        if on:
            keep.append(r)
    return keep


def print_rows(rows: Iterable[Row], *, summary: bool = False) -> bool:
    """The rows as the command line shows them (06 9.1): a heading per group, then a glyph, the state word and the text
    of each row, a needs-a-look row followed by its `Fix:` line. Detail rows are aligned with the text. True when none
    needs a look. `--json`: the document `{"rows": [...], "summary": {...}}` instead; `--quiet`: only the rows that need
    a look, and no summary line."""
    rows = list(rows)
    if output.json_mode():
        output.emit({"rows": row_dicts(rows), "summary": summary_counts(rows)})
        return not any(r.state == FAIL for r in rows)
    ok = not any(r.state == FAIL for r in rows)
    if output.quiet():
        rows, summary = _needing_a_look(rows), False
    lines: list[str] = []
    for group, members in _grouped(rows):
        if group:
            lines.append(output.paint(group, "bold", sys.stdout))
        for r in members:
            if r.state == DETAIL:
                text = r.text.strip()
                if text[:5].lower() == "fix: ":      # a fix that is its own line: the same word as the others
                    text = "Fix: " + text[5:]
                lines += output.status_row("", text)
            else:
                lines += output.status_row(_WORDS[r.state], _fours(r.text), r.fix if r.state == FAIL else "")
    if summary:
        lines += ["", summary_line(rows)]
    output.out_lines(lines)
    return ok


def station_rows(url: str) -> Iterator[Row]:
    yield from _in("Weigh Station", _station_rows(url))


def _station_rows(url: str) -> Iterator[Row]:
    from . import cli
    try:
        state = cli.StationClient(url, backoff=0).state()
    except cli.StationUnreachable:
        yield Row(FAIL, f"Weigh Station not answering at {url}",
                  "check the Weigh Station machine: sudo systemctl status filament-kit-station"
                  + f"  (url {url})", key="weigh-station.answering")
        return
    yield Row(OK, f"Weigh Station answering at {url}", key="weigh-station.answering")
    # a fresh station has seen neither the reader nor the scale: informational, not a failure.
    # "tag" is always an object; its nfc_id stays null until the reader has read a tag.
    if not (state.get("tag") or {}).get("nfc_id"):
        yield Row(INFO, "Weigh Station reader not seen", key="weigh-station.reader")
    if not state.get("scale") and not state.get("last_weight"):
        yield Row(INFO, "Weigh Station scale not seen", key="weigh-station.scale")


def hardware_rows() -> Iterator[Row]:
    yield from _in("Printers", _hardware_rows())


def _hardware_rows() -> Iterator[Row]:
    """The printer hardware data (`bambu_hardware.xml`, `klipper_hardware.xml`; bundled + optional override): a failure
    per error (a refused override: the last good data stays in use), a note per warning (ignored unknown parts). The
    Klipper file only speaks when it has something to say."""
    from .bridge import hardware
    from .bridge.klipper import hardware as klipper_hardware
    yield from _klipper_hardware_rows(klipper_hardware)
    try:
        hw = hardware.load()
    except Exception as e:  # noqa: BLE001 - status reports, it does not crash
        yield Row(FAIL, f"printer hardware data could not be loaded ({type(e).__name__}: {e})",
                  key="printers.hardware-data")
        return
    if hw.errors:
        for n, e in enumerate(hw.errors, 1):
            yield Row(FAIL, f"printer hardware data: {e}",
                      f"fix or remove {hardware.override_path()} (the last good data is in use)",
                      key="printers.hardware-data" if n == 1 else f"printers.hardware-data.{n}")
    else:
        yield Row(OK, "printer hardware data loaded", key="printers.hardware-data")
    for n, w in enumerate(hw.warnings, 1):
        yield Row(INFO, f"printer hardware data: {w}", key=f"printers.hardware-data.note-{n}")


def _klipper_hardware_rows(module) -> Iterator[Row]:
    try:
        hw = module.load()
    except Exception as e:  # noqa: BLE001 - status reports, it does not crash
        yield Row(FAIL, f"Klipper hardware data could not be loaded ({type(e).__name__}: {e})",
                  key="printers.klipper-hardware-data")
        return
    for n, e in enumerate(hw.errors, 1):
        yield Row(FAIL, f"Klipper hardware data: {e}",
                  f"fix or remove {module.override_path()} (the last good data is in use)",
                  key="printers.klipper-hardware-data" if n == 1 else f"printers.klipper-hardware-data.{n}")
    for n, w in enumerate(hw.warnings, 1):
        yield Row(INFO, f"Klipper hardware data: {w}", key=f"printers.klipper-hardware-data.note-{n}")


def library_rows() -> Iterator[Row]:
    yield from _in("Filament Catalog", _library_rows())


def _library_rows() -> Iterator[Row]:
    from . import cli, library
    st = cli.library.status()
    source = st["source"]
    if source == "updated":
        at = (library._pointer("current.json") or {}).get("at")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            source = f"updated {time.strftime('%Y-%m-%d', time.localtime(at))}"
    n = st["local"]
    if source == "none":
        yield Row(INFO, "Filament Catalog not downloaded (spoolwarden library update"
                  + f"), {n} local addition{'' if n == 1 else 's'}", key="filament-catalog.version")
    else:
        yield Row(INFO, f"Filament Catalog version {st['version']} ({source}), {n} local addition{'' if n == 1 else 's'}",
                  key="filament-catalog.version")
    lc = st["last_check"]
    if lc is not None and not lc["ok"]:
        # a warning, not a failure: the last good version (or none) stays in use
        yield Row(INFO, f"Filament Catalog update: {lc['error']}", key="filament-catalog.update")
    if st.get("skipped"):          # .get: the CLI snapshot tests' fake status has no such key
        yield Row(INFO, f"Filament Catalog: {st['skipped']}", key="filament-catalog.skipped")


def _library_safe() -> Iterator[Row]:
    try:
        yield from library_rows()
    except Exception as e:  # noqa: BLE001 - status reports, it does not crash
        yield Row(INFO, f"Filament Catalog: could not be read ({e.__class__.__name__}: {e})", group="Filament Catalog",
                  key="filament-catalog.unreadable")


def profile_rows() -> Iterator[Row]:
    yield from _in("Slicer presets", _profile_rows())


def _profile_rows() -> Iterator[Row]:
    from . import cli
    from .profiles import builds
    yield from _library_safe()
    try:
        st = builds.status()
    except Exception as e:  # noqa: BLE001
        yield Row(FAIL, f"Slicer presets: status could not be read ({e.__class__.__name__}: {e})",
                  "sudo journalctl -u filament-kit-build -n 50", key="slicer-presets.build")
        return
    b = st.get("build")
    error = cli._attempt_failed(st)
    if error is not None:
        yield Row(FAIL, f"Slicer presets: last build failed: {error}; "
                        + (f"using build {b['stamp']}" if b else "no good build yet"),
                  "sudo journalctl -u filament-kit-build -n 50", key="slicer-presets.build")
    elif b:
        yield Row(OK, f"Slicer presets: build {b['stamp']}, {st.get('presets', 0)} Slicer presets for "
                      f"{st.get('lines', 0)} lines ({b.get('problems', 0)} problems)", key="slicer-presets.build")
    else:
        yield Row(INFO, "Slicer presets: no build yet (waiting for Slicer Sync)", key="slicer-presets.build")
    pc = st.get("pc")
    if pc:
        inst = st.get("installed")
        yield Row(INFO, f"Slicer Sync: last upload {cli._fmt_time(pc.get('last_upload'))}, "
                        + (f"installed build {inst['stamp']}" if inst else "no build installed yet"),
                  key="slicer-presets.sync")
        wait = builds.pc_waiting_text(pc)
        if wait:
            yield Row(INFO, wait, key="slicer-presets.sync-waiting")
        if pc.get("failure"):
            yield Row(INFO, f"Slicer Sync at {cli._fmt_time(pc['failure']['at'])}: {pc['failure']['text']}", key="slicer-presets.sync-failure")
    else:
        yield Row(INFO, "Slicer Sync: not set up (see README: Pair your PC)", key="slicer-presets.sync")


def _station_pairing_rows(state: str | None = None) -> Iterator[Row]:
    yield from _in("Weigh Station", _station_pairing_lines(state))


def _station_pairing_lines(state: str | None = None) -> Iterator[Row]:
    """server_api.pairing_lines() (also the install's finish, as text) as rows."""
    from .station import server_api
    fixes, n = [], 0
    for line in server_api.pairing_lines(state):
        mark, text = line[:2], line[5:]
        if mark in _MARKS:
            n += 1
            yield Row(_MARKS[mark], text, key=f"weigh-station.pairing-{n}")
        else:
            fixes.append(line.strip())
    for n, line in enumerate(fixes, 1):
        yield Row(DETAIL, line, key=f"weigh-station.pairing-fix-{n}")


def _key_rows(client_factory, live_key: bool) -> Iterator[Row]:
    yield from _in("Label Reader", _key_lines(client_factory, live_key))


def _key_lines(client_factory, live_key: bool) -> Iterator[Row]:
    from . import cli
    if not live_key:        # a look at the page spends no call: the Check button in Settings does that
        key = config.paths().etc / cli.KEY_FILE
        try:
            if key.stat().st_size > 0:
                yield Row(OK, "Anthropic key set (Check it under Settings)", key="label-reader.anthropic-key")
                return
        except OSError:
            pass
        yield Row(FAIL, "Anthropic key missing", "enter it under Settings", key="label-reader.anthropic-key")
        return
    ok, text = cli.check_key(client_factory)
    if ok:
        yield Row(OK, text, key="label-reader.anthropic-key")
    elif text.startswith("Anthropic key missing"):
        yield Row(FAIL, text, "run: sudo spoolwarden config  (option 4)", key="label-reader.anthropic-key")
    else:
        yield Row(FAIL, text, "run: sudo spoolwarden config"
                  + "  (option 4) or check internet access", key="label-reader.anthropic-key")


def rows(cfg: dict | None = None, client_factory=None, *, live_key: bool = True,
         station_pairing: str | None = None) -> Iterator[Row]:
    """`spoolwarden status`, row by row, each filed under its group (the Overview's headings).
    `live_key` False: the Anthropic key is only looked at, not tried.
    `station_pairing`: server_api.pairing_state() as root gave it, for a process that can't read the pairing."""
    from . import cli
    cfg = cfg if cfg is not None else config.load()
    p = config.paths()
    on = modules.enabled(cfg)

    api_up = False
    if cli._no_systemd():
        yield Row(INFO, "service checks skipped (FK_NO_SYSTEMD=1)", group="Hub", key="hub.service-checks")
    else:
        for svc in cli.services_for(on):
            try:
                r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=15)
                active = r.stdout.strip() == "active"
            except (OSError, subprocess.SubprocessError):
                active = False
            yield Row(OK if active else FAIL, f"service {svc} active", f"sudo systemctl start {svc}",
                      group="Hub", key=f"hub.service.{svc}")
        if "server" in on:
            ok, url = cli._api_answers(cfg["port"])
            api_up = ok
            yield Row(OK if ok else FAIL, f"Spoolwarden API {'answering' if ok else 'not answering'} at {url}",
                      "sudo journalctl -u filament-kit -n 50", group="Hub", key="hub.api")

    if "server" in on or "spoolman" in on:
        try:
            version = cli.Spoolman(cfg["spoolman_url"]).ping()
            yield Row(OK, f"Spoolman reachable at {cfg['spoolman_url']} (v{version})", group="Spoolman", key="spoolman.reachable")
        except cli.SpoolmanError as e:
            yield Row(FAIL, f"Spoolman not reachable at {cfg['spoolman_url']}: {e}",
                      "sudo systemctl start spoolman" if "spoolman" in on
                      else "check that the remote Spoolman is running and spoolman_url is right",
                      group="Spoolman", key="spoolman.reachable")

    if "ai_intake" in on:
        yield from _key_rows(client_factory, live_key)
    if "local_intake" in on:
        yield from local_reader_rows(cfg)

    if "server" in on:
        cert = p.etc / "cert.pem"
        if cert.exists():
            yield Row(OK, f"certificate present, fingerprint {cli.pairing.fingerprint(cert.read_bytes())}",
                      group="Hub", key="hub.certificate")
        else:
            yield Row(FAIL, f"certificate missing ({cert})", "run: sudo spoolwarden cert",
                      group="Hub", key="hub.certificate")
        yield from storage_rows(api_up)

    station_url = (cfg.get("station") or {}).get("url")
    if station_url:
        yield from station_rows(station_url)
    if "station" in on:
        yield from _station_pairing_rows(station_pairing)

    if "server" in on:
        yield Row(INFO, f"display name: {cfg['server_name']}", group="Hub", key="hub.display-name")
        yield Row(INFO, f"paired devices: {len(pairing.devices())}", group="Devices", key="devices.paired")
        yield Row(INFO, f"reads used today: {cli._reads_today()} of {cfg['reads_per_day']}", group="Label Reader",
                  key="label-reader.reads-today")
    if "printers" in on:
        yield from hardware_rows()
    if "presets" in on:
        yield from profile_rows()
    elif "library" in on:
        yield from _library_safe()


def storage_rows(hub_running: bool = False) -> Iterator[Row]:
    """The storage locations' one row, when the list could not be saved or read (storage.checks_row): the same row for
    `spoolwarden status` and the Overview's answer, filed under Hub. Nothing when all is well."""
    from . import storage
    row = storage.checks_row(hub_running)
    if row:
        yield Row(FAIL, row["text"], row["fix"], group=row["group"], key="hub.storage-locations")


def local_reader_rows(cfg: dict | None = None) -> Iterator[Row]:
    yield from _in("Label Reader", _local_reader_rows(cfg))


def _local_reader_rows(cfg: dict | None = None) -> Iterator[Row]:
    """The local label reader (local_intake): does it answer, which tiers it can use, the reader order."""
    from . import intake, local_reader
    cfg = cfg if cfg is not None else config.load()
    h = local_reader.health(cfg)
    if h["ok"]:
        tiers = ", ".join(f"{k} {'usable' if t['usable'] else 'not usable'}" for k, t in h["tiers"].items())
        yield Row(OK, f"local label reader answering at {h['url']} (version {h['version'] or '?'}, API "
                      f"{h['api_version']}; {tiers or 'no tiers listed'})", key="label-reader.local")
        if h["degraded"]:
            yield Row(INFO, f"local label reader {h['error']}", key="label-reader.local-degraded")
        if h["last_read_at"]:
            yield Row(INFO, f"local label reader: last read {h['last_read_at']}", key="label-reader.local-last-read")
    else:
        from . import local_intake_install as lii
        unit = lii.installed_identity()[3].removesuffix(".service")
        yield Row(FAIL, f"local label reader at {h['url']}: {h['error']}",
                  f"check that it runs (on its machine: systemctl status {unit}"
                  + "), or set its address: spoolwarden config, 9) Label reader", key="label-reader.local")
    order = intake.reader_order(cfg)
    names = {"local": "the local reader", "cloud": "Claude"}
    yield Row(INFO, "label reading: " + (", then ".join(names[r] for r in order) if order else "off"),
              key="label-reader.order")


def web_rows(cfg: dict | None = None) -> Iterator[Row]:
    """`spoolwarden web status`, row by row."""
    from . import cli
    cfg = cfg if cfg is not None else config.load()
    web = cfg.get("web") or {}
    on = modules.enabled(cfg)
    yield Row(OK if "web" in on else FAIL, "Web access is " + ("on" if "web" in on else "off"), "sudo spoolwarden modules enable web",
              key="web.access")
    public = str(web.get("public_url") or "").rstrip("/")
    yield Row(OK if public.startswith("https://") else FAIL, f"public URL {public or '(not set)'}",
              "set web.public_url in config.json (e.g. https://mcp.example.com/filament)", key="web.public-url")
    if public:
        yield Row(DETAIL, f"connector: {public}/mcp   web app: {public}/intake", key="web.public-url.detail")
    if (config.paths().etc / cli.WEB_PASSPHRASE).is_file():
        yield Row(OK, "sign-in passphrase is set", key="web.passphrase")
    else:   # only Claude's connector signs in with it: not a failure for someone using the phone web app alone
        yield Row(INFO, "sign-in passphrase not set: the Claude connector cannot sign in until "
                        + "sudo spoolwarden web passphrase", key="web.passphrase")
    port = int(web.get("port") or config.DEFAULTS["web"]["port"])
    up, why = cli._web_health(port)
    yield Row(OK if up else FAIL, f"web unit answers on 127.0.0.1:{port}" + ("" if up else f" ({why})"),
              "sudo systemctl restart filament-kit-web; "
              + "journalctl -u filament-kit-web", key="web.unit")
    if "remote" in on:
        warn = remote.certificate_warning(remote.served_certificate())
        if warn:
            expired, text, fix = warn
            if expired:
                yield Row(FAIL, text, fix, key="web.certificate")
            else:
                yield Row(INFO, text, key="web.certificate")
                yield Row(DETAIL, f"fix: {fix}", key="web.certificate.detail")
    try:
        d = json.loads((config.paths().web / "oauth.json").read_text(encoding="utf-8"))
        now = time.time()
        live = sum(1 for v in (d.get("refresh") or {}).values() if (v.get("expires_at") or 0) > now)
        yield Row(DETAIL, f"connectors: {len(d.get('clients') or {})} registered, {live} signed in", key="web.connectors")
    except FileNotFoundError:
        yield Row(DETAIL, "connectors: none signed in yet", key="web.connectors")
    except PermissionError:
        yield Row(DETAIL, "connectors: cannot read (run as root)", key="web.connectors")
    except (OSError, ValueError, AttributeError) as e:
        yield Row(DETAIL, f"connectors: cannot read the OAuth state ({type(e).__name__})", key="web.connectors")
    slots = "the Hub's printer bridge" if "printers" in on else "none"
    yield Row(DETAIL, f"printer slots: {slots}; tag readers: {len(cfg.get('tag_sources') or [])} "
                      f"+ {'Weigh Station' if (cfg.get('station') or {}).get('url') else 'no Weigh Station'}",
              key="web.slots")


def _fields_rows(cfg: dict) -> Iterator[Row]:
    """The console's own check: Spoolman has the kit's extra fields (the fix is `ensure-fields`, a button there)."""
    from . import cli
    try:
        missing = cli.Spoolman(cfg["spoolman_url"]).missing_fields()
    except cli.SpoolmanError:
        return              # the row above already says Spoolman does not answer
    if missing:
        yield Row(FAIL, "Spoolman is missing Spoolwarden's extra fields: " + ", ".join(missing),
                  "sudo spoolwarden ensure-fields", action="ensure_fields", group="Spoolman",
                  key="spoolman.fields")


def hub_web_rows(cfg: dict | None = None) -> list[Row]:
    """`web_rows` as the Overview files them: under Hub, without "Web access is on" (design gap: no group for it)."""
    return [r for r in _in("Hub", web_rows(cfg)) if r.text != "Web access is on"]


def collect(cfg: dict | None = None, client_factory=None, station_pairing: str | None = None) -> list[Row]:
    """The console's Overview: `status` without spending an Anthropic call, the Spoolman fields, and `web status` when
    the web module is on."""
    cfg = cfg if cfg is not None else config.load()
    on = modules.enabled(cfg)
    out = list(rows(cfg, client_factory, live_key=False, station_pairing=station_pairing))
    if "server" in on or "spoolman" in on:
        out += list(_fields_rows(cfg))
    if "web" in on:
        out += hub_web_rows(cfg)
    return out
