"""What `filament-kit status` and `web status` check, as data: rows the CLI prints and the setup console's Overview
shows. `rows()` yields as it goes, so the terminal shows each line when its check ends; `collect()` is the list.

A row's text may hold addresses (Spoolman's URL, the station's, the public URL). The console's Overview answers without
the setup code, so it shows them through `redact.text` unless the code was given.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable, Iterator

from . import config, modules, pairing, remote

OK, FAIL, INFO, DETAIL = "ok", "fail", "info", "detail"
_MARKS = {"OK": OK, "--": INFO}


@dataclass(frozen=True)
class Row:
    state: str              # ok, fail, info (a note, not a check), detail (a line under the row before)
    text: str
    fix: str = ""
    action: str = ""        # what the console can do about it, by its own name ("" = nothing)


def print_rows(rows: Iterable[Row]) -> bool:
    """The rows as the CLI has always shown them. True when none failed."""
    good = True
    for r in rows:
        if r.state == OK:
            print(f"OK   {r.text}")
        elif r.state == FAIL:
            good = False
            print(f"FAIL {r.text}")
            if r.fix:
                print(f"     fix: {r.fix}")
        elif r.state == INFO:
            print(f"--   {r.text}")
        else:
            print(f"     {r.text}")
    return good


def station_rows(url: str) -> Iterator[Row]:
    from . import cli
    try:
        state = cli.StationClient(url, backoff=0).state()
    except cli.StationUnreachable:
        yield Row(FAIL, f"station not answering at {url}",
                  f"check the station machine: sudo systemctl status filament-kit-station  (url {url})")
        return
    yield Row(OK, f"station answering at {url}")
    # a fresh station has seen neither the reader nor the scale: informational, not a failure.
    # "tag" is always an object; its nfc_id stays null until the reader has read a tag.
    if not (state.get("tag") or {}).get("nfc_id"):
        yield Row(INFO, "station reader not seen")
    if not state.get("scale") and not state.get("last_weight"):
        yield Row(INFO, "station scale not seen")


def hardware_rows() -> Iterator[Row]:
    """The printer hardware data (`bambu_hardware.xml`, `klipper_hardware.xml`; bundled + optional override): a failure
    per error (a refused override: the last good data stays in use), a note per warning (ignored unknown parts). The
    Klipper file only speaks when it has something to say."""
    from .bridge import hardware
    from .bridge.klipper import hardware as klipper_hardware
    yield from _klipper_hardware_rows(klipper_hardware)
    try:
        hw = hardware.load()
    except Exception as e:  # noqa: BLE001 - status reports, it does not crash
        yield Row(FAIL, f"printer hardware data could not be loaded ({type(e).__name__}: {e})")
        return
    if hw.errors:
        for e in hw.errors:
            yield Row(FAIL, f"printer hardware data: {e}",
                      f"fix or remove {hardware.override_path()} (the last good data is in use)")
    else:
        yield Row(OK, "printer hardware data loaded")
    for w in hw.warnings:
        yield Row(INFO, f"printer hardware data: {w}")


def _klipper_hardware_rows(module) -> Iterator[Row]:
    try:
        hw = module.load()
    except Exception as e:  # noqa: BLE001 - status reports, it does not crash
        yield Row(FAIL, f"Klipper hardware data could not be loaded ({type(e).__name__}: {e})")
        return
    for e in hw.errors:
        yield Row(FAIL, f"Klipper hardware data: {e}",
                  f"fix or remove {module.override_path()} (the last good data is in use)")
    for w in hw.warnings:
        yield Row(INFO, f"Klipper hardware data: {w}")


def library_rows() -> Iterator[Row]:
    from . import cli, library
    st = cli.library.status()
    source = st["source"]
    if source == "updated":
        at = (library._pointer("current.json") or {}).get("at")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            source = f"updated {time.strftime('%Y-%m-%d', time.localtime(at))}"
    n = st["local"]
    if source == "none":
        yield Row(INFO, f"library not downloaded (filament-kit library update), {n} local addition"
                        f"{'' if n == 1 else 's'}")
    else:
        yield Row(INFO, f"library version {st['version']} ({source}), {n} local addition{'' if n == 1 else 's'}")
    lc = st["last_check"]
    if lc is not None and not lc["ok"]:
        # a warning, not a failure: the last good version (or none) stays in use
        yield Row(INFO, f"library update: {lc['error']}")
    if st.get("skipped"):          # .get: the CLI snapshot tests' fake status has no such key
        yield Row(INFO, f"library: {st['skipped']}")


def _library_safe() -> Iterator[Row]:
    try:
        yield from library_rows()
    except Exception as e:  # noqa: BLE001 - status reports, it does not crash
        yield Row(INFO, f"library: could not be read ({e.__class__.__name__}: {e})")


def profile_rows() -> Iterator[Row]:
    from . import cli
    from .profiles import builds
    yield from _library_safe()
    try:
        st = builds.status()
    except Exception as e:  # noqa: BLE001
        yield Row(FAIL, f"profiles: status could not be read ({e.__class__.__name__}: {e})",
                  "sudo journalctl -u filament-kit-build -n 50")
        return
    b = st.get("build")
    error = cli._attempt_failed(st)
    if error is not None:
        yield Row(FAIL, f"profiles: last build failed: {error}; "
                        + (f"using build {b['stamp']}" if b else "no good build yet"),
                  "sudo journalctl -u filament-kit-build -n 50")
    elif b:
        yield Row(OK, f"profiles: build {b['stamp']}, {st.get('presets', 0)} presets for "
                      f"{st.get('lines', 0)} lines ({b.get('problems', 0)} problems)")
    else:
        yield Row(INFO, "profiles: no build yet (waiting for the PC sync)")
    pc = st.get("pc")
    if pc:
        inst = st.get("installed")
        yield Row(INFO, f"PC sync: last upload {cli._fmt_time(pc.get('last_upload'))}, "
                        + (f"installed build {inst['stamp']}" if inst else "no build installed yet"))
        wait = builds.pc_waiting_text(pc)
        if wait:
            yield Row(INFO, wait)
        if pc.get("failure"):
            yield Row(INFO, f"PC sync at {cli._fmt_time(pc['failure']['at'])}: {pc['failure']['text']}")
    else:
        yield Row(INFO, "PC sync: not set up (see README: Pair your PC)")


def _station_pairing_rows(state: str | None = None) -> Iterator[Row]:
    """server_api.pairing_lines() (also the install's finish, as text) as rows."""
    from .station import server_api
    fixes = []
    for line in server_api.pairing_lines(state):
        mark, text = line[:2], line[5:]
        if mark in _MARKS:
            yield Row(_MARKS[mark], text)
        else:
            fixes.append(line.strip())
    for line in fixes:
        yield Row(DETAIL, line)


def _key_rows(client_factory, live_key: bool) -> Iterator[Row]:
    from . import cli
    if not live_key:        # a look at the page spends no call: the Check button in Settings does that
        key = config.paths().etc / cli.KEY_FILE
        try:
            if key.stat().st_size > 0:
                yield Row(OK, "Anthropic key set (Check it under Settings)")
                return
        except OSError:
            pass
        yield Row(FAIL, "Anthropic key missing", "enter it under Settings")
        return
    ok, text = cli.check_key(client_factory)
    if ok:
        yield Row(OK, text)
    elif text.startswith("Anthropic key missing"):
        yield Row(FAIL, text, "run: sudo filament-kit config  (option 4)")
    else:
        yield Row(FAIL, text, "run: sudo filament-kit config  (option 4) or check internet access")


def rows(cfg: dict | None = None, client_factory=None, *, live_key: bool = True,
         station_pairing: str | None = None) -> Iterator[Row]:
    """`filament-kit status`, row by row. `live_key` False: the Anthropic key is only looked at, not tried.
    `station_pairing`: server_api.pairing_state() as root gave it, for a process that can't read the pairing."""
    from . import cli
    cfg = cfg if cfg is not None else config.load()
    p = config.paths()
    on = modules.enabled(cfg)

    if cli._no_systemd():
        yield Row(INFO, "service checks skipped (FK_NO_SYSTEMD=1)")
    else:
        for svc in cli.services_for(on):
            try:
                r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=15)
                active = r.stdout.strip() == "active"
            except (OSError, subprocess.SubprocessError):
                active = False
            yield Row(OK if active else FAIL, f"service {svc} active", f"sudo systemctl start {svc}")
        if "server" in on:
            ok, url = cli._api_answers(cfg["port"])
            yield Row(OK if ok else FAIL, f"filament-kit API {'answering' if ok else 'not answering'} at {url}",
                      "sudo journalctl -u filament-kit -n 50")

    if "server" in on or "spoolman" in on:
        try:
            version = cli.Spoolman(cfg["spoolman_url"]).ping()
            yield Row(OK, f"Spoolman reachable at {cfg['spoolman_url']} (v{version})")
        except cli.SpoolmanError as e:
            yield Row(FAIL, f"Spoolman not reachable at {cfg['spoolman_url']}: {e}",
                      "sudo systemctl start spoolman" if "spoolman" in on
                      else "check that the remote Spoolman is running and spoolman_url is right")

    if "ai_intake" in on:
        yield from _key_rows(client_factory, live_key)

    if "server" in on:
        cert = p.etc / "cert.pem"
        if cert.exists():
            yield Row(OK, f"certificate present, fingerprint {cli.pairing.fingerprint(cert.read_bytes())}")
        else:
            yield Row(FAIL, f"certificate missing ({cert})", "run: sudo filament-kit cert")

    station_url = (cfg.get("station") or {}).get("url")
    if station_url:
        yield from station_rows(station_url)
    if "station" in on:
        yield from _station_pairing_rows(station_pairing)

    if "server" in on:
        yield Row(INFO, f"display name: {cfg['server_name']}")
        yield Row(INFO, f"paired devices: {len(pairing.devices())}")
        yield Row(INFO, f"reads used today: {cli._reads_today()} of {cfg['reads_per_day']}")
    if "printers" in on:
        yield from hardware_rows()
    if "presets" in on:
        yield from profile_rows()
    elif "library" in on:
        yield from _library_safe()


def web_rows(cfg: dict | None = None) -> Iterator[Row]:
    """`filament-kit web status`, row by row."""
    from . import cli
    cfg = cfg if cfg is not None else config.load()
    web = cfg.get("web") or {}
    on = modules.enabled(cfg)
    yield Row(OK if "web" in on else FAIL, "web module is on", "sudo filament-kit modules enable web")
    public = str(web.get("public_url") or "").rstrip("/")
    yield Row(OK if public.startswith("https://") else FAIL, f"public URL {public or '(not set)'}",
              "set web.public_url in config.json (e.g. https://mcp.example.com/filament)")
    if public:
        yield Row(DETAIL, f"connector: {public}/mcp   phone app: {public}/intake")
    if (config.paths().etc / cli.WEB_PASSPHRASE).is_file():
        yield Row(OK, "sign-in passphrase is set")
    else:   # only Claude's connector signs in with it: not a failure for someone using the phone web app alone
        yield Row(INFO, "sign-in passphrase not set: the Claude connector cannot sign in until "
                        "`sudo filament-kit web passphrase`")
    port = int(web.get("port") or config.DEFAULTS["web"]["port"])
    up, why = cli._web_health(port)
    yield Row(OK if up else FAIL, f"web unit answers on 127.0.0.1:{port}" + ("" if up else f" ({why})"),
              "sudo systemctl restart filament-kit-web; journalctl -u filament-kit-web")
    if "remote" in on:
        warn = remote.certificate_warning(remote.served_certificate())
        if warn:
            expired, text, fix = warn
            if expired:
                yield Row(FAIL, text, fix)
            else:
                yield Row(INFO, text)
                yield Row(DETAIL, f"fix: {fix}")
    try:
        d = json.loads((config.paths().web / "oauth.json").read_text(encoding="utf-8"))
        now = time.time()
        live = sum(1 for v in (d.get("refresh") or {}).values() if (v.get("expires_at") or 0) > now)
        yield Row(DETAIL, f"connectors: {len(d.get('clients') or {})} registered, {live} signed in")
    except FileNotFoundError:
        yield Row(DETAIL, "connectors: none signed in yet")
    except PermissionError:
        yield Row(DETAIL, "connectors: cannot read (run as root)")
    except (OSError, ValueError, AttributeError) as e:
        yield Row(DETAIL, f"connectors: cannot read the OAuth state ({type(e).__name__})")
    slots = "the kit's printer bridge" if "printers" in on else "none"
    yield Row(DETAIL, f"printer slots: {slots}; tag readers: {len(cfg.get('tag_sources') or [])} "
                      f"+ {'station' if (cfg.get('station') or {}).get('url') else 'no station'}")


def _fields_rows(cfg: dict) -> Iterator[Row]:
    """The console's own check: Spoolman has the kit's extra fields (the fix is `ensure-fields`, a button there)."""
    from . import cli
    try:
        missing = cli.Spoolman(cfg["spoolman_url"]).missing_fields()
    except cli.SpoolmanError:
        return              # the row above already says Spoolman does not answer
    if missing:
        yield Row(FAIL, "Spoolman is missing the kit's extra fields: " + ", ".join(missing),
                  "sudo filament-kit ensure-fields", action="ensure_fields")


def collect(cfg: dict | None = None, client_factory=None, station_pairing: str | None = None) -> list[Row]:
    """The console's Overview: `status` without spending an Anthropic call, the Spoolman fields, and `web status` when
    the web module is on."""
    cfg = cfg if cfg is not None else config.load()
    on = modules.enabled(cfg)
    out = list(rows(cfg, client_factory, live_key=False, station_pairing=station_pairing))
    if "server" in on or "spoolman" in on:
        out += list(_fields_rows(cfg))
    if "web" in on:
        out += [r for r in web_rows(cfg) if r.text != "web module is on"]
    return out
