"""Command line: status, pair, unpair, config, cert, ensure-fields, printer map / unpin, library, profiles, modules,
web, remote, migrate-ops, setup-code."""
from __future__ import annotations

import argparse
import copy
import http.client
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import hostaddr, apply, config, inventory, klipper_cli, library, menu_ui, modules, pairing, secret_input
from . import status as status_rows
from .bridge import registry
from .profiles import builds, lines as lines_mod
from .profiles.errors import ProfileError
from .spoolman import Spoolman, SpoolmanError
from .station_client import StationClient, StationUnreachable

KEY_FILE = "anthropic_key"

def services_for(on: frozenset[str]) -> tuple[str, ...]:
    """systemd services that must be active for the modules that are on."""
    out = []
    if "spoolman" in on:
        out.append("spoolman")
    if "server" in on:
        out.append("filament-kit")
    if "station" in on:
        out.append("filament-kit-station")
    return tuple(out)


def _no_systemd() -> bool:
    return os.environ.get("FK_NO_SYSTEMD") == "1"


def _restart_service() -> None:
    if _no_systemd():
        return
    try:
        subprocess.run(["systemctl", "restart", "filament-kit"], check=False, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"could not restart filament-kit: {e}", file=sys.stderr)


def _default_client(key: str):
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=10, max_retries=0)


# ---------- status ----------

def _line(ok: bool, text: str, fix: str = "") -> bool:
    print(f"{'OK  ' if ok else 'FAIL'} {text}")
    if not ok and fix:
        print(f"     fix: {fix}")
    return ok


def _reads_today() -> int:
    from .intake import reads_today
    return reads_today(config.paths().state / "reads.json")


def _api_answers(port: int) -> tuple[bool, str]:
    url = f"https://127.0.0.1:{port}/api/info"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # local self-check of our own self-signed cert
    try:
        with urllib.request.urlopen(url, timeout=5, context=ctx) as r:
            return r.status == 200, url
    except (OSError, ValueError, http.client.HTTPException):
        return False, url


def _station_lines(url: str) -> bool:
    return status_rows.print_rows(status_rows.station_rows(url))


def _hardware_lines() -> bool:
    return status_rows.print_rows(status_rows.hardware_rows())


def cmd_status(client_factory, station_pairing: str | None = None) -> int:
    """`station_pairing`: the wrapper's answer from root (server_api.pairing_state), for a status run as the service
    user, which can't read the station's pairing."""
    rows = status_rows.rows(client_factory=client_factory, station_pairing=station_pairing)
    return 0 if status_rows.print_rows(rows) else 1


def _library_status_lines() -> None:
    status_rows.print_rows(status_rows.library_rows())


def _attempt_failed(st: dict) -> str | None:
    """The last build attempt's error, unless it only waited for the first PC sync (a normal state)."""
    la = st.get("last_attempt") or {}
    if la.get("ok") is False and la.get("error") and la["error"] != builds.NO_SYSTEM:
        return str(la["error"])
    return None


def _profile_status_lines() -> bool:
    return status_rows.print_rows(status_rows.profile_rows())


# ---------- pair / unpair ----------

def _qr_text(payload: str) -> str:
    if shutil.which("qrencode"):
        try:
            # -m 4: the 4-module quiet zone QR readers expect (qrencode's default, kept explicit)
            r = subprocess.run(["qrencode", "-t", "ansiutf8", "-m", "4", payload], capture_output=True,
                               text=True, timeout=10, check=True)
            return r.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return payload


def _station_server(cfg: dict) -> str:
    """The kit server's address a station-only machine answers (its first non-loopback station.allow), or ""."""
    allow = (cfg.get("station") or {}).get("allow") or []
    return next((str(a).strip() for a in allow if str(a).strip() not in ("127.0.0.1", "localhost", "::1")), "")


def cmd_pair(pc: bool = False, station: bool = False, text: bool = False) -> int:
    cmd = "sudo filament-kit pair" + (" --pc" if pc else " --station" if station else "")
    cfg = config.load()                 # unreadable: main() says to run it with sudo
    if "server" not in modules.enabled(cfg):
        # a station (or another machine without the server): no certificate here, and none is needed
        addr = _station_server(cfg)
        where = (f"the kit server ({addr}, from station.allow)" if addr
                 else "the kit server (its address is not set here: station.allow names none)")
        print(f"error: the server module is off on this machine; pairing runs on the kit server.\n"
              f"fix: run `{cmd}` on {where}", file=sys.stderr)
        return 1
    try:
        pr = pairing.issue(device_hint="pc" if pc else "station" if station else "")
    except pairing.PairingError as e:
        # /etc/filament-kit is root's: as a user the certificate cannot be read (or even seen)
        unreadable = isinstance(e, pairing.CertUnreadable) or not _is_root()
        print(f"error: {e}" + (f"\nfix: run it with sudo: {cmd}" if unreadable else ""), file=sys.stderr)
        return 1
    if pc or station:
        # no QR scanner there: the link is pasted (printed by design, never logged)
        print("Link for filament-kit-sync (paste it when asked):" if pc else
              "Link for the intake station (on the station PC: sudo filament-kit station pair, then paste it):")
        print(pr.qr)
        fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
        print(f"Certificate fingerprint (check it matches the one the {'PC' if pc else 'station'} shows):")
    elif text:
        # no terminal (an install log): the link as text, for a phone that gets it some other way
        print(f"Pairing link: {pr.qr}")
        fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
        print("Certificate fingerprint (the phone asks for two groups of it):")
    else:
        print(_qr_text(pr.qr))
        fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
        print("Certificate fingerprint (the phone asks for two groups of it):")
    print("  " + " ".join(fp[i:i + 4] for i in range(0, len(fp), 4)))
    print(f"Pairing code: {pr.code}")
    print(f"Expires at {time.strftime('%H:%M:%S', time.localtime(pr.expires))} "
          f"(in {max(0, int(pr.expires - time.time()) // 60)} min)")
    if station:
        print(f"The link works for {pairing.TOKEN_TTL // 60} minutes: run `sudo filament-kit station pair` on the "
              "station PC before then.")
    return 0


def cmd_station_pair(ask=input) -> int:
    """On the station PC: take the link from `filament-kit pair --station`, check the server's fingerprint with the
    owner, save the pairing for the button flow (station/server_api.py)."""
    from .station import server_api
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("error: run as root: sudo filament-kit station pair", file=sys.stderr)
        return 1
    no_terminal = ("error: `sudo filament-kit station pair` needs a terminal: it asks for the link and for you to "
                   "compare the fingerprint. Nothing was saved.")
    try:
        text = ask("Paste the link from 'sudo filament-kit pair --station' on the server: ")
    except (EOFError, RuntimeError, OSError):  # `< /dev/null`; `<&-` is no stdin (RuntimeError) or a dead one (OSError)
        print(no_terminal, file=sys.stderr)
        return 1
    try:
        link = server_api.parse_link(text)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    def owner_compares(seen: str) -> bool:
        print("The server's certificate fingerprint:")
        print("  " + " ".join(seen[i:i + 4] for i in range(0, len(seen), 4)))
        try:
            answer = ask("Does it match the one 'sudo filament-kit pair --station' showed? [y/N] ")
        except (EOFError, RuntimeError, OSError):  # no answer is a no
            print(no_terminal, file=sys.stderr)
            return False
        return answer.strip().lower() in ("y", "yes")

    result = server_api.pair_with_link(link, confirm=owner_compares)
    if result.status == "failed":
        print(f"error: {result.message}", file=sys.stderr)
    else:
        print(result.message, file=sys.stderr if result.status == "paired_not_restarted" else sys.stdout)
    return 1 if result.status in ("failed", "declined") else 0


def cmd_station_pair_local() -> int:
    """`station pair --local`: the station on the machine that is also the kit server (the setup page's button). Nothing
    to compare by eye, nothing to paste: this machine makes the link, and pair_with_link checks the certificate it finds
    on loopback against it. Prints no token: the output goes to the page's job log."""
    from .station import server_api
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("error: run as root: sudo filament-kit station pair --local", file=sys.stderr)
        return 1
    if "server" not in modules.enabled(config.load()):
        print("error: --local pairs a station with the kit server on the same machine, and the server module is off "
              "here.\nfix: run `sudo filament-kit pair --station` on the kit server, then `sudo filament-kit station "
              "pair` here", file=sys.stderr)
        return 1
    try:
        result = server_api.pair_with_link(server_api.parse_link(pairing.issue(device_hint="station").qr))
    except (pairing.PairingError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(result.message, file=sys.stderr if result.status in ("failed", "paired_not_restarted") else sys.stdout)
    return 1 if result.status == "failed" else 0


def cmd_backup(action: str, out: str | None) -> int:
    from . import backup
    if not _is_root():
        print(f"error: run as root: sudo filament-kit backup {action}", file=sys.stderr)
        return 1
    if action == "list":
        rows = backup.listing()
        if not rows:
            print(f"no backups in {backup.backups_dir()}")
        for e in rows:
            print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(e.at))}  {e.kind:<11} {e.size // 1024:>8} KiB  {e.name}")
        return 0
    try:
        path = backup.create(Path(out) if out else None)
    except (OSError, backup.BackupError) as e:
        print(f"error: the backup was not written: {e}", file=sys.stderr)
        return 1
    print(f"backup written: {path}")
    return 0


def cmd_restore(zip_path: str | None, *, uploaded: bool = False, yes: bool = False) -> int:
    from . import backup
    if not _is_root():
        print("error: run as root: sudo filament-kit restore <backup.zip>", file=sys.stderr)
        return 1
    if uploaded:
        try:
            path = backup.take_upload()
        except (OSError, backup.BackupError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    else:
        path = Path(zip_path)
        if not path.is_file():
            print(f"error: {zip_path}: no such file", file=sys.stderr)
            return 1
    try:
        return backup.restore(path, yes=yes)
    finally:
        if uploaded:
            path.unlink(missing_ok=True)


def cmd_station_pairing_state() -> int:
    """One line for the wrapper, run as root: see server_api.pairing_state."""
    from .station import server_api
    print(server_api.pairing_state())
    return 0


def _fmt_time(t) -> str:
    if isinstance(t, str):
        return t
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "never"


def cmd_unpair(device_id: str | None) -> int:
    if device_id is None:
        devs = pairing.devices()
        if not devs:
            print("no paired devices")
        for d in devs:
            print(f"{d['id']}  {d['name']}  paired {_fmt_time(d['paired'])}  last seen {_fmt_time(d['last_seen'])}")
        return 0
    if pairing.revoke(device_id):
        print(f"unpaired {device_id}")
        return 0
    print(f"error: no paired device {device_id}", file=sys.stderr)
    return 1


# ---------- config ----------

def _ask(prompt: str) -> str | None:
    print(prompt, end="", flush=True)
    line = sys.stdin.readline()
    if line == "":
        return None
    return line.rstrip("\r\n")


def _ask_int(prompt: str, minimum: int) -> int | None:
    raw = _ask(prompt)
    if raw is None:
        return None
    try:
        n = int(raw.strip())
        if n < minimum:
            raise ValueError
        return n
    except ValueError:
        print(f"Please enter a number of at least {minimum}.")
        return None


def check_key(client_factory=None) -> tuple[bool, str]:
    """(ok, text) for the stored Anthropic key: one models.list() call (`status` and the setup page). The text
    never holds the key."""
    keyfile = config.paths().etc / KEY_FILE
    try:
        key = keyfile.read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    if not key:
        return False, f"Anthropic key missing ({keyfile})"
    try:
        (client_factory or _default_client)(key).models.list()
        return True, "Anthropic key accepted"
    except Exception as e:  # noqa: BLE001 - any failure means the key/network is unusable
        msg = str(e).replace(key, "***")
        return False, f"Anthropic key not accepted or API unreachable: {msg}"


def remove_key() -> bool:
    """Remove the stored Anthropic key (root); False when there was none."""
    dest = config.paths().etc / KEY_FILE
    try:
        dest.unlink()
        return True
    except FileNotFoundError:
        return False


def write_key(key: str) -> Path:
    dest = config.paths().etc / KEY_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    data = (key.strip() + "\n").encode("utf-8")
    try:
        if os.name == "nt":
            tmp.write_bytes(data)
        else:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
            with os.fdopen(fd, "wb") as fh:
                os.fchmod(fh.fileno(), 0o640)
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            if os.geteuid() == 0:
                try:
                    shutil.chown(tmp, group="filament-kit")
                except (LookupError, OSError):
                    pass
        config.grant_web_read(tmp)        # the web unit reads labels with it as its own user
        os.replace(tmp, dest)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    return dest


def _storage_menu(cfg: dict) -> None:
    pl = cfg["placement"]
    while True:
        print("\nStorage\n"
              f"  1) locations          {', '.join(cfg['locations'])}\n"
              f"  2) PLA rack           {pl['pla_location']}\n"
              f"  3) box prefix         {pl['box_prefix']!r}\n"
              f"  4) box count          {pl['box_count']}\n"
              f"  5) overflow           {pl['overflow']}\n"
              "  0) back")
        choice = _ask("> ")
        if choice is None or choice.strip() == "0":
            return
        choice = choice.strip()
        if choice == "1":
            v = _ask("Locations, comma separated: ")
            items = [s.strip() for s in (v or "").split(",") if s.strip()]
            if items:
                cfg["locations"] = items
        elif choice == "2":
            v = _ask("PLA rack location: ")
            if v and v.strip():
                pl["pla_location"] = v.strip()
        elif choice == "3":
            v = _ask("Box location prefix (e.g. 'Storage box '): ")
            if v:
                pl["box_prefix"] = v
        elif choice == "4":
            n = _ask_int("Number of storage boxes: ", 0)
            if n is not None:
                pl["box_count"] = n
        elif choice == "5":
            v = _ask("Overflow location: ")
            if v and v.strip():
                pl["overflow"] = v.strip()
        else:
            print("Unknown choice.")


def _pick_printer(printers: list) -> "registry.Printer | None":
    raw = _ask("Printer number: ")
    try:
        n = int((raw or "").strip())
        if n >= 1:
            return printers[n - 1]
    except (ValueError, IndexError):
        pass
    print("No such printer.")
    return None


def _printers_action(choice: str, printers: list) -> None:
    if choice == "1":
        return
    if choice == "2":
        name = (_ask("Name: ") or "").strip()
        ip = hostaddr.clean(_ask("Address (IP or name): ") or "")
        serial = (_ask("Serial number: ") or "").strip()
        if not (name and ip and serial):
            print("Name, address and serial number are all needed.")
            return
        _, problem, note = hostaddr.inspect(ip)
        if problem:
            print(f"Not added: {problem}.")
            return
        if note:
            print(f"Note: {note}.")
        if not registry.SERIAL.fullmatch(serial):
            print(f"Not added: {registry.BAD_SERIAL}.")
            return
        # a printer added by hand may never announce its model, and the model decides which camera it has
        model = (_ask("Model (e.g. H2D, X1C, P1S; Enter to skip): ") or "").strip()
        code = secret_input.ask("Access Code: ").strip()
        if not code:
            print("No Access Code entered; nothing added.")
            return
        problem = registry.check_fields(serial, code)
        if problem:
            print(f"Not added: {problem}.")
            return
        old = registry.load().get(serial)
        # a fresh entry: adding the printer again also clears its TLS pin (cert_fp), as POST /api/printers does
        registry.upsert(registry.Printer(serial, name, model or (old.model if old else ""), ip, code, True))
        print(f"Added {name}.")
    elif choice in ("3", "4"):
        p = _pick_printer(printers)
        if p is None:
            return
        if choice == "3":
            name = (_ask("New name: ") or "").strip()
            if name:
                registry.rename(p.serial, name)
        else:
            registry.remove(p.serial)
            print(f"Removed {p.name}.")
    else:
        print("Unknown choice.")


def _printers_menu() -> None:
    while True:
        printers = list(registry.load().values())
        print("\nPrinters")
        for i, p in enumerate(printers, 1):
            state = "set up" if p.configured else "detected, not set up"
            print(f"  {i}. {p.name}  {p.model}  {p.ip}  serial {p.serial}  ({state})")
        if not printers:
            print("  (none yet; printers on your network appear here once they announce themselves)")
        print("  1) refresh list\n  2) add printer\n  3) rename\n  4) remove\n  0) back")
        choice = _ask("> ")
        if choice is None or choice.strip() == "0":
            return
        choice = choice.strip()
        try:
            _printers_action(choice, printers)
        except registry.RegistryError as e:
            print(f"error: {e}")


def _tts_name(cfg: dict) -> str:
    st = config._merge(config.DEFAULTS["station"], cfg.get("station") or {})
    if not st.get("speech"):
        return "off (station.speech)"
    return "espeak-ng" if st.get("tts") == "espeak" else "Piper"


def _station_voice_menu(cfg: dict) -> None:
    """How the button panel speaks: Piper (natural, a 60-80 MB voice download) or espeak-ng (no download)."""
    v = _ask("The station's voice: 1) Piper (natural; downloads a 60-80 MB voice)  "
             "2) espeak-ng (robotic; no download)  [Enter keeps it]: ")
    v = (v or "").strip()
    if v in ("1", "2"):
        cfg.setdefault("station", {})["tts"] = "auto" if v == "1" else "espeak"


def cmd_config() -> int:
    cfg = config.load()
    before = _module_state(cfg)
    while True:
        print("\nfilament-kit settings\n"
              f"  1) display name       {cfg['server_name']}\n"
              "  2) storage\n"
              f"  3) Claude model       {cfg['model']}, {cfg['reads_per_day']} reads/day\n"
              "  4) Anthropic key      only for AI label reading (ai_intake)\n"
              "  5) Printers\n"
              f"  6) Modules            {modules.mode_of(modules.enabled(cfg))}\n"
              f"  7) Station voice      {_tts_name(cfg)}\n"
              "  0) save and exit")
        choice = _ask("> ")
        if choice is None or choice.strip() == "0":
            break
        choice = choice.strip()
        if choice == "1":
            v = _ask("Display name (shown in the app): ")
            if v and v.strip():
                cfg["server_name"] = v.strip()
        elif choice == "2":
            _storage_menu(cfg)
        elif choice == "3":
            v = _ask("Model: ")
            if v and v.strip():
                cfg["model"] = v.strip()
            n = _ask_int("Reads per day: ", 1)
            if n is not None:
                cfg["reads_per_day"] = n
        elif choice == "4":
            key = secret_input.ask("Anthropic API key: ").strip()
            if key:
                write_key(key)
                print("Key saved.")
                if "ai_intake" not in modules.enabled(cfg):  # AI is optional: the key alone turns nothing on
                    print("AI label reading is off: turn on ai_intake in 6) Modules to use the key.")
            else:
                print("No key entered; unchanged.")
        elif choice == "5":
            _printers_menu()
        elif choice == "6":
            _modules_menu(cfg)
        elif choice == "7":
            _station_voice_menu(cfg)
        else:
            print("Unknown choice.")
    changed = _module_state(cfg) != before
    if changed:
        if not _require_root():
            return 1
        err = _plan_error(cfg)
        if err:
            print(f"error: {err}\nNothing was saved.", file=sys.stderr)
            return 1
    config.save(cfg)
    print("Saved.")
    if changed:
        # the apply restarts what changed, so it replaces the plain restart
        return _run_apply(pairing=False)
    _restart_service()
    return 0


# ---------- cert / ensure-fields ----------

def cmd_cert() -> int:
    cert = config.paths().etc / "cert.pem"
    if cert.exists():
        print(pairing.fingerprint(cert.read_bytes()))
        return 0
    cert.parent.mkdir(parents=True, exist_ok=True)
    full, short = socket.gethostname(), pairing.short_hostname()
    print(pairing.make_cert(short, pairing.local_ips(), cert.parent, extra_dns=[full] if full != short else []))
    return 0


def cmd_ensure_fields() -> int:
    try:
        created = Spoolman(config.load()["spoolman_url"]).ensure_fields()
    except SpoolmanError as e:
        print(f"error: Spoolman: {e}", file=sys.stderr)
        return 1
    print("Spoolman: added the kit's extra fields: " + ", ".join(created) if created
          else "Spoolman: the kit's extra fields are in place")
    return 0


# ---------- printer map / unpin ----------
# The CLI is its own process (run with sudo), like `config` it works on the registry and state files directly; it
# has no API token. `printer map` therefore runs a short-lived Manager of its own, connected to that one printer
# only, for the length of the job (a second MQTT session next to the service's). The service's slot-map readers
# (loading, usage) read the saved map from disk, and its GET /map shows the result from the status file; the
# lock file keeps the service and the CLI from mapping the same printer at once.

CONNECT_WAIT = 20.0   # seconds for the CLI's connection to come up
REPORT_WAIT = 10.0    # seconds for its first full report


def _default_manager(serial: str):
    from .bridge.connection import Manager
    return Manager(only={serial})


def _err_line(text: str) -> None:
    print(f"error: {text}", file=sys.stderr)


STOP_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP")


def _on_stop_signals(handler) -> dict:
    """Install `handler` for Ctrl-C / SIGTERM / SIGHUP; returns the previous handlers (for `_restore_signals`)."""
    old = {}
    for name in STOP_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            old[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):      # not the main thread, or not settable here
            pass
    return old


def _restore_signals(old: dict) -> None:
    for sig, h in old.items():
        try:
            signal.signal(sig, h)
        except (ValueError, OSError):
            pass


def cmd_printer_map(serial: str, manager_factory) -> int:
    from .bridge import mapping
    from .bridge.connection import PrinterOffline, UnknownPrinter
    from .bridge.slottest import PrinterBusy
    p = registry.load().get(serial)
    if p is None or not p.configured:
        _err_line(f"no printer {serial} is set up (see: sudo filament-kit config, Printers)")
        return 1
    print(f"Mapping the slots of {registry.display_name(p)}. Each slot's colour changes briefly and the printer runs a "
          f"job with no heating and no motion.")
    m = manager_factory(serial)
    stopped = []
    try:
        m.sync()
        m.wait_settled(serial, CONNECT_WAIT)
        m.wait_report(serial, lambda r: "gcode_state" in r, REPORT_WAIT)
        mapper = mapping.Mapper(m)

        def on_signal(signum, frame):
            # Ctrl-C, a closed terminal (SIGHUP) or SIGTERM mid-job: stop cooperatively so every slot is put back.
            # Abort first (lock-free); the message is a courtesy: a print can fail here (a reentrant call when
            # the signal lands mid-print, EIO once the terminal is gone) and must not lose the abort.
            first = not stopped
            stopped.append(signum)
            mapper.abort(serial)
            if first:
                try:
                    print("\n  Stopping: putting the slots back first (this takes a few seconds) ...", flush=True)
                except (OSError, RuntimeError):
                    pass
        old = _on_stop_signals(on_signal)
        try:
            v = mapper.run(serial, on_step=lambda t: print(f"  {t}", flush=True))
        except mapping.LoadRunning:
            _err_line("a spool is being loaded into this printer; try again in a moment")
            return 1
        except mapping.AlreadyRunning:
            _err_line("slot mapping is already running for this printer")
            return 1
        except mapping.CertChanged:
            _err_line("the printer's certificate changed. If you reset the printer or its mainboard was replaced, "
                      "add it again with its Access Code (or run: sudo filament-kit printer unpin " + serial + "). "
                      "If not, something else may be answering at the printer's address: check the printer's IP "
                      "before re-adding")
            return 1
        except PrinterBusy as e:
            _err_line(f"the printer is busy ({e}); try again once it is idle")
            return 1
        except (PrinterOffline, UnknownPrinter):
            _err_line("the printer is offline (or its Access Code is wrong); check that it is on and on the network")
            return 1
        finally:
            _restore_signals(old)
    finally:
        m.stop()
    for s in v["slots"]:
        where = "no number yet" if s["global"] is None else f"printer slot {s['global']}"
        print(f"  {s['label']}: AMS {s['ams_id']} tray {s['tray_id']} -> {where}")
    for prob in v["problems"]:
        print(f"  problem: {prob}")
    for note in v["notes"]:
        print(f"  note: {note}")
    if v.get("report_wanted"):
        print(f"  {v.get('report_why') or 'A printer report would help.'} To collect one: "
              f"sudo filament-kit printer report {serial}")
    if stopped:
        print("Mapping stopped. Any slot listed above as not restored may still hold a test colour; the next "
              "mapping run restores it first.")
        return 130 if stopped[0] == getattr(signal, "SIGINT", None) else 1
    if v["state"] == "done" and v["calibrated"]:
        print("Done: slots mapped; filament use is now taken off the spools in Spoolman.")
        return 0
    if v["state"] == "done":
        print("Done, but the slot numbering was not confirmed: filament use is only logged (observe mode).")
    else:
        print("Mapping failed. Until mapping succeeds, filament use is only logged (observe mode).")
    return 1


def cmd_printer_report(serial: str, manager_factory) -> int:
    """`printer report <serial>`: the file an owner attaches to help add a printer or an AMS the kit doesn't know."""
    from .bridge import mapping
    from .bridge.connection import PrinterOffline, UnknownPrinter
    p = registry.load().get(serial)
    if p is None or not p.configured or p.family != "bambu":
        _err_line(f"no Bambu printer {serial} is set up here")
        return 1
    m = manager_factory(serial)
    try:
        m.sync()
        m.wait_report(serial, lambda r: "gcode_state" in r, REPORT_WAIT)
        r = mapping.Mapper(m).report(serial)
    except (PrinterOffline, UnknownPrinter):
        _err_line("the printer is offline (or its Access Code is wrong); check that it is on and on the network")
        return 1
    finally:
        m.stop()
    print(f"Printer report saved: {r['path']}")
    print("It holds no serial, address, name or account id. Attach it to a 'Printer report' issue on the project's GitHub.")
    return 0


def cmd_printer_unpin(serial: str) -> int:
    p = registry.load().get(serial)
    if p is None or not registry.clear_pin(serial):
        _err_line(f"no printer {serial}")
        return 1
    # the service's Manager notices the cleared pin at its next registry sync (within 15 s) and reconnects
    print(f"Forgot the certificate of {p.name or serial}; the next connection trusts the one it presents.")
    return 0


# ---------- library ----------

def _request_rebuild(reason: str) -> None:
    """Ask for a profile rebuild (filament-kit-build.path starts the build)."""
    builds.request_rebuild(reason)


def _library_line(st: dict) -> str:
    n = st["local"]
    if st["source"] == "none":
        return (f"library not downloaded (run: filament-kit library update), "
                f"{n} local addition{'' if n == 1 else 's'}")
    return (f"library version {st['version']} ({st['source']}), "
            f"{n} local addition{'' if n == 1 else 's'}")


def cmd_library_status() -> int:
    st = library.status()
    print(_library_line(st))
    print(f"url: {st['url']}")
    lc = st["last_check"]
    if lc is None:
        print("last check: never")
    else:
        print(f"last check: {_fmt_time(lc['at'])} {'ok' if lc['ok'] else 'failed: ' + str(lc['error'])}")
    if st["skipped"]:
        print(st["skipped"])
    return 0


def cmd_library_update(scheduled: bool) -> int:
    cfg = config.load()
    try:
        if scheduled:
            if library.schedule(cfg) == "off":
                print("library updates are off")
                return 0
            if not library.due(cfg, time.time()):
                print("library update not due yet")
                return 0
        r = library.update(cfg["library"].get("url") or None)
    except (library.LibraryError, ValueError) as e:
        _err_line(str(e))
        return 1
    if r.note:
        print(f"note: {r.note}")
    if r.error:
        if scheduled and r.http_status in library.PRIVATE_STATUSES:
            # the library may simply not be published yet: the timer run is not a failure, the last good
            # version (or none) stays in use
            print(f"warning: {r.error}", file=sys.stderr)
            return 0
        _err_line(r.error)
        return 1
    if not r.changed:
        print(f"library version {r.version} is up to date")
        return 0
    print(f"library version {r.version} installed ({r.downloaded} entr{'y' if r.downloaded == 1 else 'ies'} "
          f"downloaded)")
    text = library.skipped_text()
    if text:
        print(text)
    _request_rebuild(f"library updated to version {r.version}")
    return 0


def cmd_library_adopt(folder: str) -> int:
    try:
        v = library.adopt(Path(folder))
    except library.LibraryError as e:
        _err_line(str(e))
        return 1
    if v is not None:
        print(f"kept the library of the earlier program version (library version {v})")
    return 0


def cmd_library_rollback() -> int:
    try:
        v = library.rollback()
    except library.LibraryError as e:
        _err_line(str(e))
        return 1
    print(f"rolled back to library version {v}")
    _request_rebuild(f"library rolled back to version {v}")
    return 0


def cmd_library_add(source: str) -> int:
    limit = library.LOCAL_LIMIT
    try:
        if source == "-":
            if hasattr(sys.stdin, "buffer"):
                data = sys.stdin.buffer.read(limit + 1)
            else:
                data = sys.stdin.read(limit + 1).encode("utf-8")
        else:
            with open(source, "rb") as fh:
                data = fh.read(limit + 1)
    except OSError as e:
        _err_line(f"cannot read {source}: {e.strerror or e}")
        return 1
    if len(data) > limit:
        _err_line(f"entry not added: larger than {limit // 1024} KiB")
        return 1
    try:
        entry, line = library.add_local(data)
    except ValueError as e:
        _err_line(f"entry not added: {e}")
        return 1
    print(f"added local entry {entry['vendor']} {entry['product']} (line {line})")
    _request_rebuild(f"local library addition {line}")
    return 0


# ---------- profiles ----------

def _default_spoolman() -> Spoolman:
    return Spoolman(config.load()["spoolman_url"])


def cmd_profiles_build(sm_factory) -> int:
    r = builds.run_build(sm_factory())
    if r.get("waiting"):
        # waiting for the first PC sync is a normal state: the build unit must not show as failed
        err = r.get("error") or builds.NO_SYSTEM
        print(err + (" (see README: Pair your PC)" if err == builds.NO_SYSTEM else ""))
        return 0
    if not r.get("ok"):
        _err_line(f"build failed: {r.get('error')}; the last good build stays in use "
                  f"(see: sudo journalctl -u filament-kit-build -n 50)")
        return 1
    c = builds.current() or {}
    problems = r.get("problems") or []
    print(f"build {r['stamp']}: {c.get('presets', 0)} presets, {len(problems)} "
          f"problem{'' if len(problems) == 1 else 's'}")
    for prob in problems:
        print(f"  problem: {prob}")
    return 0


def cmd_profiles_status() -> int:
    st = builds.status()
    b, la, inst, pc = st["build"], st["last_attempt"], st["installed"], st["pc"]
    print(f"lines: {st['lines']}")
    if b:
        orca = (f"{st['orca_presets']} Orca presets, {len(st['orca_stale'])} Orca stale, "
                if st.get("orca_presets") is not None else "")
        print(f"build: {b['stamp']} ({_fmt_time(b.get('created'))}), {st['presets']} presets, {orca}"
              f"{b.get('problems', 0)} problems")
    else:
        print("build: no build yet")
    if la:
        state = "ok" if la.get("ok") else ("waiting" if la.get("error") in (builds.NO_SYSTEM, builds.WAIT_LIVE)
                                           else "failed")
        print(f"last attempt: {_fmt_time(la.get('at'))} {state}"
              + (f": {la['error']}" if la.get("error") and not la.get("ok") else ""))
        if not la.get("ok") and la.get("error") == builds.WAIT_LIVE:
            print("  the PC sync has to run once (it runs every 10 minutes while Bambu Studio is closed); "
                  "the build follows its upload")
    print(f"installed on the PC: {inst['stamp']} ({_fmt_time(inst.get('at'))})" if inst
          else "installed on the PC: nothing yet")
    up = st.get("updates") or {}
    if up.get("count"):
        acc = f", {up['accepted']} accepted (the PC sync writes them next)" if up.get("accepted") else ""
        print(f"{up['count']} update{'' if up['count'] == 1 else 's'} available ({up['lines']} "
              f"line{'' if up['lines'] == 1 else 's'}){acc}: presets already in your slicers differ from the "
              "generated ones and are never replaced on their own")
        if up["count"] > up.get("accepted", 0):
            print("  see them: sudo filament-kit profiles apply-updates --all --dry-run; "
                  "apply: sudo filament-kit profiles apply-updates --line <id> | --all")
    elif b:
        print("updates: none (presets already in your slicers are never replaced)")
    if up.get("yours"):
        print(f"  {up['yours']} generated preset{'' if up['yours'] == 1 else 's'} differ from your own preset of the "
              "same name in Bambu Studio's filament folder; yours stay (rename or delete yours to get ours)")
    print(f"PC sync: device {pc['device_id']}, last upload {_fmt_time(pc.get('last_upload'))}" if pc
          else "PC sync: not set up (see README: Pair your PC)")
    wait = builds.pc_waiting_text(pc)
    if wait:
        print(f"  {wait}")
    for name in st["stale"]:
        print(f"  delete in Bambu Studio: {name}")
    for name in st.get("orca_stale", []):
        print(f"  delete in Orca Slicer: {name}")
    for prob in st["problems"]:
        print(f"  problem: {prob}")
    return 0


def cmd_profiles_lines() -> int:
    try:
        ls = lines_mod.load()
    except lines_mod.LineStoreError as e:
        _err_line(e.message)
        return 1
    c = builds.current()
    per_line: dict[str, int] = {}
    for row in builds.bambu_rows(builds.manifest(c["stamp"]) if c else None):
        if isinstance(row, dict) and isinstance(row.get("line_id"), str):
            per_line[row["line_id"]] = per_line.get(row["line_id"], 0) + 1
    if not ls:
        print("no lines yet (they are made from the Spoolman filaments at the next build or intake)")
    for lid in sorted(ls):
        line = ls[lid]
        parent = f"{line.bambu_parent} ({line.parent_source})" if line.bambu_parent else "none"
        oparent = f"{line.orca_parent} ({line.orca_parent_source})" if line.orca_parent else "none"
        ids = ", ".join(str(i) for i in line.filaments) or "-"
        print(f"{lid}  {line.vendor} {line.product}  {line.material}  parent {parent}  orca {oparent}  "
              f"filaments {ids}  presets {per_line.get(lid, 0)}")
    return 0


def set_parent_checked(line_id: str, parent: str, orca: bool = False):
    """Check a parent the owner picked, save it on the line and ask for a build; the line. This command and the setup
    page's Presets tab. Raises ValueError or ProfileError (the parent), KeyError (the line), LineStoreError."""
    parent = parent.strip()
    if not parent:
        raise ValueError("give the name of an Orca Slicer library preset (without ' @System')" if orca
                         else "give the name of a Bambu Studio system preset")
    inventory.check_line_text("set-parent", "parent", parent)
    if orca:
        parent = lines_mod.check_orca_parent(parent, builds.orca_store())   # the store's spelling (fix I1)
    else:
        lines_mod.check_parent(parent, builds.system_store())
    line = lines_mod.set_parent_saved(line_id, parent, target="orca" if orca else "bambu")
    _request_rebuild(f"{'Orca ' if orca else ''}parent of line {line.line_id} set")
    return line


def cmd_profiles_set_parent(line_id: str, parent: str, orca: bool = False) -> int:
    try:
        line = set_parent_checked(line_id, parent, orca)
    except (ValueError, ProfileError) as e:
        _err_line(str(e))
        return 1
    except KeyError:
        _err_line(f"no line {line_id} (see: sudo filament-kit profiles lines)")
        return 1
    except lines_mod.LineStoreError as e:
        _err_line(e.message)
        return 1
    if orca:
        print(f"line {line.line_id}: Orca parent {line.orca_parent} (set by you)")
    else:
        print(f"line {line.line_id}: parent {line.bambu_parent} (set by you)")
    return 0


def cmd_profiles_apply_updates(line_id: str | None, all_: bool, dry_run: bool) -> int:
    """Accept the listed updates of one line or all: the next PC sync writes them over the presets in the slicers
    (after its backup); nothing else ever writes over an existing preset."""
    try:
        r = builds.apply_updates(line_id=line_id, all_=all_, dry_run=dry_run)
    except ValueError as e:
        _err_line(str(e))
        return 1
    chosen = r["chosen"]
    if r["stamp"] is None:
        print("no build yet: nothing to update")
        return 0
    if not chosen:
        print(f"no updates for line {line_id} (see: sudo filament-kit profiles status)" if line_id
              else "no updates available")
        return 1 if line_id else 0
    for u in chosen:
        app = "Orca Slicer" if u["target"] == "orca" else "Bambu Studio"
        keys = ", ".join(u["keys"][:6]) + (", ..." if len(u["keys"]) > 6 else "")
        where = f" (in your file {u['file']})" if u.get("file") else ""
        print(f"  {u['line_id']}  {app}: {u['name']}{where}: {keys}")
    lines = len({u["line_id"] for u in chosen})
    what = f"{len(chosen)} update{'' if len(chosen) == 1 else 's'} ({lines} line{'' if lines == 1 else 's'})"
    if dry_run:
        print(f"dry run: {what} would be accepted; nothing was changed")
    else:
        print(f"accepted {what}; the PC sync writes them at its next run (after its backup)")
    return 0


def cmd_profiles_restore_deleted() -> int:
    builds.restore_deleted_next()
    _request_rebuild("restore presets deleted in Bambu Studio")
    print("the next build brings back the presets deleted in Bambu Studio; a build was requested")
    return 0


# ---------- modules ----------

def cmd_modules_units() -> int:
    """Every unit of every module, with companion services (uninstall.sh reads this)."""
    for mod in modules.MODULES.values():
        for unit in mod.units:
            for u in apply._unit_files(unit):
                print(u)
    return 0


def _require_root() -> bool:
    """False (with a hint) when not root; checked before anything is saved."""
    if not _no_systemd() and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("error: run as root: sudo filament-kit modules <command>", file=sys.stderr)
        return False
    return True


def _run_apply(*, pairing: bool = True) -> int:
    """Plan, execute and finish for the saved config. `pairing` shows the QR code at the end."""
    if not _require_root():
        return 1
    cfg = config.load()
    try:
        actions = apply.plan(cfg)
    except modules.ModuleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    on = modules.enabled(cfg)
    print(f"Mode: {modules.mode_of(on)} ({', '.join(n for n in modules.MODULES if n in on)})")
    for a in actions:
        if a.kind == "install_file" and a.arg[0] == apply.DROPIN:
            allow = next(ln for ln in a.arg[1].splitlines() if ln.startswith("IPAddressAllow="))
            print(f"Station answers: {allow.split('=', 1)[1]}")
    try:
        apply.execute(actions)
    except apply.ApplyError:
        return 1
    try:
        apply.finish(cfg, pairing=pairing)
    except apply.ApplyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_modules_apply(pair: bool = True) -> int:
    return _run_apply(pairing=pair)


def _module_state(cfg: dict) -> tuple:
    """What an apply cares about: the module set, the station link and its voice (the drop-in, the download)."""
    st = cfg.get("station") or {}
    return (modules.enabled(cfg), st.get("url"), tuple(st.get("allow") or ()), st.get("tts"))


def _with_modules(cfg: dict, on) -> dict:
    """Copy of cfg with the module set `on` written true/false (never an empty dict; modules.module_map leaves out a
    newer module, such as klipper, that is off and was never named)."""
    out = copy.deepcopy(cfg)
    out["modules"] = modules.module_map(on, cfg)
    return out


def _link_station(cfg: dict) -> None:
    """Station on beside the server: all-in-one semantics (spec section 3)."""
    st = cfg.setdefault("station", {})
    st["allow"] = ["127.0.0.1"]
    st["url"] = "http://127.0.0.1:5003"


def _change_module(cfg: dict, name: str, want_on: bool, *, confirm=None, ask_address=None, ask_settings=None,
                   server: str | None = None, notes: list[str] | None = None) -> str | None:
    """Turn `name` on/off in `cfg` (in place). Returns an error text, or None when changed.

    `confirm(text) -> bool` is asked before dependents go off, or needs go on, too (None: refuse).
    `ask_address() -> str | None` supplies the server address for a station without a server.
    `ask_settings(new_cfg, on) -> error | None` fills in what the new module set needs, once that set is known.
    `notes` gets the sentence saying what else changed: the caller prints it when the change has really passed its checks."""
    if name not in modules.MODULES:
        return f"unknown module {name!r}"
    on = set(modules.enabled(cfg))
    said: list[str] = []
    if want_on:
        missing = modules.needs_closure([name], on)
        if missing:
            listed = ", ".join(missing)
            # without a terminal it stays a refusal: a script gets the failure the docs describe
            if confirm is None or not confirm(f"{name} needs {listed}. Also turn on {listed}? [y/N] "):
                return f"{name} needs {listed}\nfix: enable {listed} first"
            on |= set(missing)
            said = modules.change_note(name, True, missing)
        on.add(name)
    else:
        deps = modules.dependents_closure(name, on)     # not only the direct ones: the rest would refuse after the yes
        if deps:
            listed = ", ".join(deps)
            if confirm is None or not confirm(f"Also turn off {listed}? [y/N] "):
                # the list is parents first; the fix has to go children first, or each step refuses
                return f"{listed} depend on {name}\nfix: disable {', '.join(reversed(deps))} first"
            on -= set(deps)
            said = modules.change_note(name, False, deps)
        on.discard(name)
    new = _with_modules(cfg, on)
    if not {"server", "station"} <= on:
        modules.drop_local_station_link(new)
    if want_on and name == "station":
        if "server" in on:
            _link_station(new)
        elif server:
            new.setdefault("station", {})["allow"] = [server]
        elif _server_addr_missing(new) and ask_address is not None:
            addr = ask_address()
            if addr is None:
                return "station needs the server's address; unchanged"
            new.setdefault("station", {})["allow"] = [addr]
    if want_on and ask_settings is not None:
        err = ask_settings(new, on)
        if err:
            return err
    try:
        modules.validate(new)
    except modules.ModuleError as e:
        return str(e)
    cfg.clear()
    cfg.update(new)
    if notes is not None:
        notes.extend(said)
    return None


def _server_addr_missing(cfg: dict) -> bool:
    """True when station.allow holds only loopback (an existing real address is kept)."""
    allow = (cfg.get("station") or {}).get("allow") or []
    return not any(str(e).strip() not in ("127.0.0.1", "localhost", "::1") for e in allow)


def _tty_confirm(text: str) -> bool:
    if not apply._tty():
        return False
    ans = _ask(text)
    return bool(ans) and ans.strip().lower() in ("y", "yes")


def cmd_modules_list() -> int:
    on = modules.enabled(config.load())
    width = max(len(n) for n in modules.MODULES)
    for n, m in modules.MODULES.items():
        print(f"{n:<{width}}  {'on ' if n in on else 'off'}  {m.title}")
    print(f"mode: {modules.mode_of(on)}")
    return 0


def _plan_error(cfg: dict) -> str | None:
    """apply.plan's refusal (validation or name resolution) for `cfg`, or None. No side effects:
    checked before config.json is saved, so a refused change leaves the settings as they were."""
    try:
        apply.plan(cfg)
    except modules.ModuleError as e:
        return str(e)
    return None


def _save_and_apply(cfg: dict, notes=()) -> int:
    err = _plan_error(cfg)
    if err:
        print(f"error: {err}\nNothing was changed.", file=sys.stderr)
        return 1
    for note in notes:
        print(note)
    config.save(cfg)
    return _run_apply(pairing=False)


def _server_addr_error(addr: str) -> str | None:
    try:
        modules.validate({"modules": {"station": True}, "station": {"allow": [addr]}})
    except modules.ModuleError as e:
        return str(e)
    return None


def cmd_modules_set(mode: str, server: str | None = None) -> int:
    if not _require_root():
        return 1
    try:
        cfg = modules.set_mode(config.load(), mode)
        if server:
            err = _server_addr_error(server)
            if err:
                raise modules.ModuleError(err)
            if mode == "station":
                cfg["station"]["allow"] = [server]
        modules.validate(cfg)
    except modules.ModuleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return _save_and_apply(cfg)


def cmd_modules_toggle(name: str, want_on: bool, server: str | None = None) -> int:
    if not _require_root():
        return 1
    cfg = config.load()
    if server:
        err = _server_addr_error(server)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 1
    notes: list[str] = []
    err = _change_module(cfg, name, want_on, confirm=_tty_confirm, server=server, notes=notes,
                         ask_settings=_ask_module_settings if apply._tty() else None)
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return _save_and_apply(cfg, notes)


def _ask_module_settings(cfg: dict, on) -> str | None:
    """`modules enable NAME` at a terminal: ask for the settings the new set `on` needs (web.public_url, orders.file, a
    remote Spoolman's address), with the menu's prompts, into cfg (in place). Not for the station's server address
    (--server and _change_module see to it). Returns an error text or None."""
    also = ("spoolman_url",) if modules.needs_spoolman_url(on, cfg) else ()
    got = modules.collect_settings(on, cfg, _ask, skip=("station.allow",), also=also)
    if got is None:
        return "a setting was left blank; nothing was changed"
    for key, value in got.items():
        modules.set_setting(cfg, key, value)
    return None


def _ask_station_server() -> str | None:
    """Server address for a station-only machine; a blank answer cancels."""
    while True:
        raw = _ask("Server address (single IP or host name, blank to cancel): ")
        if raw is None or not raw.strip():
            return None
        addr = raw.strip()
        try:
            modules.validate({"modules": {"station": True}, "station": {"allow": [addr]}})
        except modules.ModuleError:
            print("Enter a single address or host name, not a range or wildcard.")
            continue
        return addr


def _station_link(new: dict, on) -> None:
    if not {"server", "station"} <= set(on):
        modules.drop_local_station_link(new)


def _apply_selection(cfg: dict, on, *, ask=None) -> str | None:
    """Set the module set of `cfg` (in place) to `on` with the station link rules; asks for settings the modules
    need. Returns an error text or None."""
    old = modules.enabled(cfg)
    new = _with_modules(cfg, on)
    _station_link(new, on)
    if "station" in on and "station" not in old and "server" in on:
        _link_station(new)
    got = modules.collect_settings(on, new, ask or _ask)
    if got is None:
        return "a setting was left blank; unchanged"
    for key, value in got.items():
        modules.set_setting(new, key, value)
    try:
        modules.validate(new)
    except modules.ModuleError as e:
        return str(e)
    cfg.clear()
    cfg.update(new)
    return None


def _modules_menu(cfg: dict) -> None:
    """One checklist (menu_ui: cursor keys and Space, or numbers without a terminal): needs go on too, dependents
    go off, a/s/t presets, Enter applies."""
    on = modules.enabled(cfg)
    print()
    print(f"Modules (mode: {modules.mode_of(on)})")
    chosen = menu_ui.run_menu(on, _ask)
    if chosen is None or chosen == on:
        print("Unchanged.")
        return
    err = _apply_selection(cfg, chosen)
    if err:
        print(f"error: {err}")


def _config_has_content() -> bool:
    """False for a first install: no config file, or one with nothing in it (as set_mode counts it)."""
    f = config.paths().etc / "config.json"
    try:
        return bool(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def cmd_modules_menu(raw: bool) -> int:
    """The checklist on its own. --raw: prompts on stderr; stdout gets the chosen modules as a comma list, then
    one `set <key>=<value>` line per setting asked for (install.sh custom mode). Changes nothing."""
    cfg = config.load()
    on = modules.enabled(cfg)
    if not raw:
        _modules_menu(cfg)
        return 0
    if not _config_has_content():
        on = modules.MODES["server"]            # a first install: AI intake and the library start off
    out = sys.stdout
    sys.stdout = sys.stderr                     # prompts and the checklist go to the terminal, not the capture
    try:
        while True:
            chosen = menu_ui.run_menu(on, _ask)
            if chosen is None:
                return 1
            trial = _with_modules(cfg, chosen)
            _station_link(trial, chosen)
            if {"server", "station"} <= set(chosen):
                _link_station(trial)
            got = modules.collect_settings(chosen, trial, _ask)
            if got is None:
                print("A setting was left blank; change the selection (q cancels).")
                on = chosen
                continue
            for key, value in got.items():
                modules.set_setting(trial, key, value)
            try:
                modules.validate(trial)
            except modules.ModuleError as e:
                print(f"error: {e}")
                print("fix: change the selection and press Enter again (q cancels)")
                on = chosen
                continue
            break
    finally:
        sys.stdout = out
    print(",".join(n for n in modules.MODULES if n in chosen))
    for key, value in got.items():
        print(f"set {key}={value}")
    return 0


# ---------- uninstall ----------

def _kept_release() -> tuple[str, Path] | None:
    """(version, tarball) of the kept release to uninstall with: the running version's copy, else the newest
    kept one that still verifies."""
    from . import release, updates
    store = updates.store()
    cur = updates.current_version()
    others = []
    if store.is_dir():
        for d in store.iterdir():
            try:
                if d.is_dir() and not d.name.startswith(".") and d.name != cur:
                    others.append((release.parse_version(d.name), d.name))
            except (release.ReleaseError, ValueError):
                continue
    for ver in [cur] + [v for _, v in sorted(others, reverse=True)]:
        try:
            return ver, release.verify_dir(store / ver, ver)
        except (release.ReleaseError, OSError):
            continue
    return None


def cmd_uninstall(purge: bool, run=None) -> int:
    """Run uninstall.sh of the kept release (/opt/filament-kit/releases/<version>/), unpacked outside /opt, which
    it removes. Its own confirmation for --purge stays: it reads the terminal as `./uninstall.sh --purge` does."""
    from . import release, updates
    if not _no_systemd() and not _is_root():
        print("error: run as root: sudo filament-kit uninstall", file=sys.stderr)
        return 1
    run = run or subprocess.call
    kept = _kept_release()
    if kept is None:
        ver = updates.current_version()
        print(f"error: no kept copy of a release in {updates.store()}, so there is no uninstall.sh to run.\n"
              f"fix: download filament-kit-{ver}.tar.gz from https://github.com/{release.REPO}/releases, unpack it "
              f"(tar xzf filament-kit-{ver}.tar.gz), then in its folder run: sudo ./uninstall.sh"
              + (" --purge" if purge else ""), file=sys.stderr)
        return 1
    ver, tarball = kept
    running = updates.current_version()
    if ver != running:
        print(f"Using the uninstall.sh of {ver}, the newest kept release: there is no kept copy of {running} "
              f"(the installed version).")
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="filament-kit-uninstall-"))
    try:
        root = release.extract(tarball, ver, work)
        return run(["bash", str(root / "uninstall.sh")] + (["--purge"] if purge else []))
    except (release.ReleaseError, OSError) as e:
        print(f"error: cannot unpack the kept release {ver}: {e}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------- web (the MCP endpoint and phone web app) ----------

WEB_PASSPHRASE = "web_passphrase"


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


class GroupMissing(OSError):
    """A root-owned secret could not be given to the filament-kit group; nothing was changed."""


def write_passphrase(text: str) -> Path:
    """Store the web passphrase as a salted scrypt hash, root:filament-kit 640, so the service can check it but
    not change it (root: `web passphrase` and the setup page's helper). ValueError for a short one; GroupMissing
    when the group does not exist. Nothing changes on either."""
    from .web import auth  # needs the [web] extra
    hashed = auth.hash_passphrase(text)
    dest = config.paths().etc / WEB_PASSPHRASE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(hashed + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o640)          # O_CREAT's mode does not apply to a leftover tmp file
        try:
            shutil.chown(tmp, user="root", group="filament-kit")
        except (LookupError, OSError) as e:
            tmp.unlink(missing_ok=True)
            raise GroupMissing(f"cannot give {dest} to the filament-kit group ({e})") from None
        config.grant_web_read(tmp)        # the web unit checks it as its own user
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def cmd_web_passphrase() -> int:
    """Set the passphrase that approves Claude's connector on the web unit's /login (the phone web app has no
    sign-in). Typed twice, hidden; stored by `write_passphrase`."""
    from .web import auth  # needs the [web] extra
    if not _is_root():
        print("error: run as root: sudo filament-kit web passphrase", file=sys.stderr)
        return 1
    first = secret_input.ask(f"New web passphrase, at least {auth.MIN_PASSPHRASE} characters: ")
    second = secret_input.ask("Again: ")
    if first != second:
        print("error: the two passphrases do not match; nothing was changed", file=sys.stderr)
        return 1
    try:
        dest = write_passphrase(first)
    except GroupMissing as e:
        print(f"error: {e}; nothing was changed\n"
              "     fix: install the kit first (it creates the filament-kit user and group), "
              "or: sudo groupadd --system filament-kit", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}; nothing was changed", file=sys.stderr)
        return 1
    print(f"Passphrase saved ({dest}). Sign-ins from now on use it; existing sessions and connectors stay "
          "signed in.")
    return 0


def cmd_setup_code(new: bool, revoke_trusted: bool = False) -> int:
    """`setup-code [--new] [--revoke-trusted]` (root): the code the server's /setup page asks for before any change,
    made when there is none. At a terminal it is printed with the page's address; without one (a log) only the address
    and how to see it, as no secret may end up in a log. A new code keeps trusted computers trusted (the owner's
    choice, said so here); --revoke-trusted forgets them, with or without a new code."""
    from . import setup_code, trusted
    if not _is_root():
        print("error: run as root: sudo filament-kit setup-code", file=sys.stderr)
        return 1
    if new:
        code = setup_code.generate()
        setup_code.write(code)
    else:
        code = setup_code.ensure()
    url = setup_code.page_url(config.load())
    if apply._tty():
        print(f"Open {url}  (setup code: {setup_code.shown(code)})")
    else:
        print(f"Setup page: {url}  (see its setup code at a terminal: sudo filament-kit setup-code)")
    if new:
        print("The old setup code no longer works.")
    if revoke_trusted:
        n = trusted.revoke_all()
        print(f"{n} trusted computer{'' if n == 1 else 's'} revoked: each needs the setup code again.")
    elif new:
        n = len(trusted.listing())
        if n:
            print(f"Trusted computers stay trusted ({n}): revoke them in Devices on the setup page, or with "
                  "sudo filament-kit setup-code --revoke-trusted.")
    return 0


def cmd_reader(action: str, name: str | None = None, ref: str | None = None) -> int:
    """`reader token [--name X]` (root): a new reader token, printed once for the reader's secrets.h (only its
    sha256 is kept); `reader tokens`: the tokens (id, name, made); `reader revoke <id|name>` (root)."""
    try:
        from .web import reader  # needs the [web] extra
    except ImportError as e:
        print(f"error: the reader commands need the kit's [web] packages ({e.name or e} is missing); install them "
              "into the kit's Python: <venv>/bin/python -m pip install 'filament-kit[web]' (or re-run the "
              "installer, which adds them)", file=sys.stderr)
        return 1
    store = reader.TokenStore()
    if action in ("token", "revoke") and not _is_root():
        print(f"error: run as root: sudo filament-kit reader {action}", file=sys.stderr)
        return 1
    try:
        if action == "token":
            tid, tok = store.issue(name)
            print(f"New reader token {tid} ({reader._clean_name(name)}). It is shown only this once:\n\n  {tok}\n\n"
                  "Put it in the reader's src/secrets.h as READER_TOKEN, then build and flash (reader/README.md).\n"
                  f"Remove it later with: sudo filament-kit reader revoke {tid}")
            return 0
        if action == "tokens":
            rows = store.list()
            for t in rows:
                print(f"{t['id']:<6} {t['name']:<24} {t['created']}")
            if not rows:
                print("no reader tokens (make one: sudo filament-kit reader token --name bench)")
            return 0
        if store.revoke(ref or ""):
            print(f"revoked {ref}; a reader using it is refused from now on")
            return 0
        print(f"error: no single reader token {ref!r} (see: filament-kit reader tokens)", file=sys.stderr)
        return 1
    except reader.TokenFileError as e:
        print(f"error: {e}; nothing was changed", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"error: {e} (try with sudo)", file=sys.stderr)
        return 1


def _web_health(port: int) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            body = r.read().decode(errors="replace").strip()
        return body == "ok", body or "empty answer"
    except (OSError, http.client.HTTPException) as e:
        return False, str(e)


def cmd_web_status() -> int:
    return 0 if status_rows.print_rows(status_rows.web_rows()) else 1


# ---------- migrate-ops (from filament-ops, sub-project 4) ----------

def cmd_migrate_ops(bundle: str, apply_: bool, replace_spoolman: bool, allow_unknown_spoolman: bool = False) -> int:
    """Report (default) or carry out the move of a filament-ops export bundle into this install."""
    from . import migrate
    if apply_ and not _is_root():
        print(f"error: run as root: sudo filament-kit migrate-ops {bundle} --apply", file=sys.stderr)
        return 1
    return migrate.run(bundle, apply=apply_, replace_spoolman=replace_spoolman,
                       allow_unknown_spoolman=allow_unknown_spoolman)


def cmd_migrate_scanner(calibration: str, apply_: bool, replace_map: bool, serial: str | None) -> int:
    """Report (default) or carry out the move of the H2D from h2d-filament-scanner (Spoolman slot locations and
    the slot map seeded from the scanner's calibration)."""
    from . import migrate_scanner
    if apply_ and not _is_root():
        print(f"error: run as root: sudo filament-kit migrate-scanner {calibration} --apply", file=sys.stderr)
        return 1
    return migrate_scanner.run(calibration, apply=apply_, replace_map=replace_map, serial=serial)


def main(argv: list[str] | None = None, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    """The CLI. A root-only file (/etc/filament-kit/config.json and the like) read as another user is one line
    saying to run it with sudo, not a traceback (C-M7)."""
    try:
        return _main(argv, client_factory=client_factory, manager_factory=manager_factory, sm_factory=sm_factory)
    except PermissionError as e:
        args = list(sys.argv[1:] if argv is None else argv)
        where = f"{e.filename}: " if e.filename else ""
        print(f"error: {where}permission denied; run it with sudo: sudo filament-kit {' '.join(args)}".rstrip(),
              file=sys.stderr)
        return 1


def _main(argv: list[str] | None = None, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    ap = argparse.ArgumentParser(prog="filament-kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    stat = sub.add_parser("status", help="check services, Spoolman, key, certificate")
    stat.add_argument("--station-pairing", help=argparse.SUPPRESS)  # passed by the wrapper, from its check as root
    pp = sub.add_parser("pair", help="show a QR code and code to pair a phone (--pc: a link for the PC sync)")
    pkind = pp.add_mutually_exclusive_group()
    pkind.add_argument("--pc", action="store_true", help="pair the Windows PC sync: print the link, no QR code")
    pkind.add_argument("--station", action="store_true", help="pair the intake station's button flow: print the link")
    stp = sub.add_parser("station", help="intake station commands (run on the station PC)")
    stp_sub = stp.add_subparsers(dest="station_cmd", required=True)
    stpp = stp_sub.add_parser("pair", help="pair the station's button flow with the server (link from 'pair --station')")
    stpp.add_argument("--local", action="store_true", help="the kit server is this machine: no link, nothing to compare")
    stp_sub.add_parser("pairing-state", help="print whether the button flow is paired, as one line")
    pkind.add_argument("--text", action="store_true", help="print the pairing link as text instead of a QR code")
    up = sub.add_parser("unpair", help="list or remove paired phones")
    up.add_argument("device_id", nargs="?")
    sub.add_parser("config", help="interactive settings menu")
    sub.add_parser("cert", help="create the server certificate if missing")
    sub.add_parser("ensure-fields", help="create the Spoolman extra fields")
    pr = sub.add_parser("printer", help="printer tasks: map slots, forget a certificate")
    psub = pr.add_subparsers(dest="printer_cmd", required=True)
    pm = psub.add_parser("map", help="map the AMS slots (changes slot colours briefly, runs a no-motion job)")
    pm.add_argument("serial")
    prp = psub.add_parser("report", help="make a report that helps add a printer or AMS the kit doesn't know yet")
    prp.add_argument("serial")
    pu = psub.add_parser("unpin", help="forget the printer's pinned TLS certificate")
    pu.add_argument("serial")
    lb = sub.add_parser("library", help="the filament spec library: status, update, rollback, local additions")
    lsub = lb.add_subparsers(dest="library_cmd", required=True)
    lsub.add_parser("status", help="show the library version, local additions and the last update check")
    lu = lsub.add_parser("update", help="download or update the library (library.url)")
    lu.add_argument("--scheduled", action="store_true", help="only if config library.schedule says it is due")
    lsub.add_parser("rollback", help="go back to the library version before the last update")
    la = lsub.add_parser("adopt", help="keep the library an older program version bundled (used by the installer)")
    la.add_argument("folder", help="the old library_data folder (index.json and library/)")
    la = lsub.add_parser("add", help="add or replace a local entry from a JSON file ('-' reads stdin)")
    la.add_argument("file")
    _pf_help = "the generated Bambu Studio and Orca Slicer presets: build, status, lines, parents"
    pf = sub.add_parser("profiles", help=_pf_help, description=_pf_help)
    pfsub = pf.add_subparsers(dest="profiles_cmd", required=True)
    pfsub.add_parser("build", help="build the presets now (needs the PC sync to have run once)")
    pfsub.add_parser("status", help="show the last build, the PC sync and the problems")
    pfsub.add_parser("lines", help="list the product lines and their Bambu Studio and Orca Slicer parents")
    sp = pfsub.add_parser("set-parent", help="set the Bambu Studio system preset (or with --orca the Orca Slicer "
                                             "library preset) a line is built from")
    sp.add_argument("line_id")
    sp.add_argument("parent")
    sp.add_argument("--orca", action="store_true",
                    help="set the line's Orca Slicer library parent instead (the name without ' @System')")
    pfsub.add_parser("restore-deleted", help="bring back the presets deleted in Bambu Studio at the next build")
    au = pfsub.add_parser("apply-updates", help="write the listed updates over presets already in your slicers "
                                                "(at the next PC sync); they are never replaced otherwise")
    aug = au.add_mutually_exclusive_group(required=True)
    aug.add_argument("--line", dest="line_id", help="the updates of one product line (see: profiles lines)")
    aug.add_argument("--all", dest="all_", action="store_true", help="every listed update")
    au.add_argument("--dry-run", action="store_true", help="only show what would be accepted")
    md = sub.add_parser("modules", help="the switchable parts of the kit: apply the settings, list units")
    mdsub = md.add_subparsers(dest="modules_cmd", required=True)
    mda = mdsub.add_parser("apply", help="install, start and stop what config.json's modules say (root)")
    mda.add_argument("--no-pair", action="store_true", help="show no pairing code at the end (the setup page)")
    mdsub.add_parser("list", help="show each module on/off and the mode")
    mm = mdsub.add_parser("menu", help="the module checklist (cursor keys move, Space switches, a/s/t presets, Enter applies)")
    mm.add_argument("--raw", action="store_true", help="print the chosen modules as a comma list; change nothing")
    ms = mdsub.add_parser("set", help="switch to an install mode and apply (root)")
    ms.add_argument("mode", choices=list(modules.MODES))
    ms.add_argument("--server", help="the kit server's name or IP (station mode)")
    me = mdsub.add_parser("enable", help="turn a module on and apply (root)")
    me.add_argument("name")
    me.add_argument("--server", help="the kit server's name or IP (when enabling station without a server)")
    mx = mdsub.add_parser("disable", help="turn a module off and apply; its data is kept (root)")
    mx.add_argument("name")
    mdsub.add_parser("units", help="print every systemd unit of every module, one per line")
    wb = sub.add_parser("web", help="the MCP endpoint and phone web app: passphrase, status")
    wbsub = wb.add_subparsers(dest="web_cmd", required=True)
    wbsub.add_parser("passphrase", help="set the sign-in passphrase (root; typed twice, hidden)")
    wbsub.add_parser("status", help="check the web unit: public URL, passphrase, health, connectors")
    rd = sub.add_parser("reader", help="the bench NFC reader's tokens: make, list, revoke")
    rdsub = rd.add_subparsers(dest="reader_cmd", required=True)
    rdt = rdsub.add_parser("token", help="make a reader token and print it once, for secrets.h (root)")
    rdt.add_argument("--name", help="what the token is for, e.g. bench")
    rdsub.add_parser("tokens", help="list the reader tokens (never the tokens themselves)")
    rdr = rdsub.add_parser("revoke", help="remove a reader token (root)")
    rdr.add_argument("ref", help="its id (r1 ...) or name")
    bk = sub.add_parser("backup", help="a whole-kit backup as one zip: make one, list them (root)")
    bksub = bk.add_subparsers(dest="backup_cmd", required=True)
    bkc = bksub.add_parser("create", help="write a backup zip (default: into /var/backups/filament-kit)")
    bkc.add_argument("--out", help="the folder to write it into")
    bksub.add_parser("list", help="the backups in /var/backups/filament-kit")
    rs = sub.add_parser("restore", help="bring this machine to the state in a backup zip (root)")
    rs_what = rs.add_mutually_exclusive_group(required=True)
    rs_what.add_argument("zip", nargs="?", help="the backup zip")
    rs_what.add_argument("--uploaded", action="store_true", help="the zip the setup page received")
    rs.add_argument("--yes", action="store_true", help="ask nothing (no terminal: the installer, the setup page)")
    rm_ = sub.add_parser("remote", help="remote access: get the certificate, show the firewall rules")
    rmsub = rm_.add_subparsers(dest="remote_cmd", required=True)
    rmsub.add_parser("issue", help="get the certificate with certbot (standalone on port 80) (root)")
    rmsub.add_parser("firewall", help="print the firewall and port-forward rules to set up by hand")
    mo = sub.add_parser("migrate-ops", help="move a filament-ops export bundle into this install (dry run unless "
                                            "--apply)")
    mo.add_argument("bundle", help="the bundle tools/export_ops.sh wrote (tar.gz or its folder)")
    mo.add_argument("--apply", action="store_true", help="do it (root); without it nothing is written")
    mo.add_argument("--replace-spoolman", action="store_true",
                    help="replace a Spoolman database that already holds spools (a backup is kept)")
    mo.add_argument("--allow-unknown-spoolman", action="store_true",
                    help="accept a bundle database without a schema revision (only if it came from Spoolman 0.27.0)")
    msc = sub.add_parser("migrate-scanner", help="move the H2D from h2d-filament-scanner: Spoolman slot locations "
                                                 "and the slot map from its calibration (dry run unless --apply)")
    msc.add_argument("calibration", help="the scanner's calibration.json (/var/lib/h2d-usage/calibration.json)")
    msc.add_argument("--printer", metavar="SERIAL", help="the kit printer to migrate (needed with several printers)")
    msc.add_argument("--apply", action="store_true", help="do it (root); without it nothing is written")
    msc.add_argument("--replace-map", action="store_true",
                     help="replace a slot map the printer already has (the old one goes into the backup)")
    ud = sub.add_parser("update", help="install the latest signed release (root); --check only looks, --rollback "
                                       "goes back to the version before the last update")
    udx = ud.add_mutually_exclusive_group()
    udx.add_argument("--check", action="store_true", help="say whether a newer release exists; change nothing")
    udx.add_argument("--rollback", action="store_true", help="reinstall the version the last update replaced")
    udx.add_argument("--feed", action="store_true", help=argparse.SUPPRESS)  # the new program, after an update
    udx.add_argument("--scheduled", action="store_true", help="the timer's run: only with the updates module on "
                                                              "and a check due")
    un = sub.add_parser("uninstall", help="remove the kit with the kept release's uninstall.sh (root); --purge "
                                          "also deletes the data, after a typed confirmation")
    un.add_argument("--purge", action="store_true", help="also delete settings, spool data, paired phones, backups")
    sc = sub.add_parser("setup-code", help="show the setup page's address and its setup code (root); --new "
                                           "replaces the code")
    sc.add_argument("--new", action="store_true", help="make a new setup code; the old one stops working (trusted "
                                                        "computers stay trusted)")
    sc.add_argument("--revoke-trusted", action="store_true",
                    help="forget every trusted computer, so each needs the setup code again (alone, or with --new)")
    klipper_cli.add_parser(sub)       # its own module (Klipper printers), see klipper_cli.py
    args = ap.parse_args(argv)

    if args.cmd == "klipper":
        return klipper_cli.run(args)
    if args.cmd == "status":
        return cmd_status(client_factory or _default_client, station_pairing=args.station_pairing)
    if args.cmd == "pair":
        return cmd_pair(pc=args.pc, station=args.station, text=args.text)
    if args.cmd == "station" and args.station_cmd == "pair" and args.local:
        return cmd_station_pair_local()
    if args.cmd == "station":
        return cmd_station_pairing_state() if args.station_cmd == "pairing-state" else cmd_station_pair()
    if args.cmd == "unpair":
        return cmd_unpair(args.device_id)
    if args.cmd == "config":
        return cmd_config()
    if args.cmd == "cert":
        return cmd_cert()
    if args.cmd == "printer":
        if args.printer_cmd == "map":
            return cmd_printer_map(args.serial, manager_factory or _default_manager)
        if args.printer_cmd == "report":
            return cmd_printer_report(args.serial, manager_factory or _default_manager)
        return cmd_printer_unpin(args.serial)
    if args.cmd == "library":
        if args.library_cmd == "status":
            return cmd_library_status()
        if args.library_cmd == "update":
            return cmd_library_update(args.scheduled)
        if args.library_cmd == "rollback":
            return cmd_library_rollback()
        if args.library_cmd == "adopt":
            return cmd_library_adopt(args.folder)
        return cmd_library_add(args.file)
    if args.cmd == "profiles":
        if args.profiles_cmd == "build":
            return cmd_profiles_build(sm_factory or _default_spoolman)
        if args.profiles_cmd == "status":
            return cmd_profiles_status()
        if args.profiles_cmd == "lines":
            return cmd_profiles_lines()
        if args.profiles_cmd == "set-parent":
            return cmd_profiles_set_parent(args.line_id, args.parent, orca=args.orca)
        if args.profiles_cmd == "apply-updates":
            return cmd_profiles_apply_updates(args.line_id, args.all_, args.dry_run)
        return cmd_profiles_restore_deleted()
    if args.cmd == "web":
        return cmd_web_passphrase() if args.web_cmd == "passphrase" else cmd_web_status()
    if args.cmd == "reader":
        return cmd_reader(args.reader_cmd, getattr(args, "name", None), getattr(args, "ref", None))
    if args.cmd == "migrate-ops":
        return cmd_migrate_ops(args.bundle, args.apply, args.replace_spoolman, args.allow_unknown_spoolman)
    if args.cmd == "migrate-scanner":
        return cmd_migrate_scanner(args.calibration, args.apply, args.replace_map, args.printer)
    if args.cmd == "backup":
        return cmd_backup(args.backup_cmd, args.out if args.backup_cmd == "create" else None)
    if args.cmd == "restore":
        return cmd_restore(args.zip, uploaded=args.uploaded, yes=args.yes)
    if args.cmd == "remote":
        from . import remote
        cfg = config.load()
        return remote.issue(cfg) if args.remote_cmd == "issue" else remote.firewall(cfg)
    if args.cmd == "uninstall":
        return cmd_uninstall(args.purge)
    if args.cmd == "update":
        from . import updates
        cfg = config.load()
        if args.check:
            return updates.check(cfg)
        if args.rollback:
            return updates.rollback(cfg)
        if args.feed:
            return updates.feed_now(cfg)
        return updates.update(cfg, scheduled=args.scheduled)
    if args.cmd == "modules":
        if args.modules_cmd == "units":
            return cmd_modules_units()
        if args.modules_cmd == "list":
            return cmd_modules_list()
        if args.modules_cmd == "menu":
            return cmd_modules_menu(args.raw)
        if args.modules_cmd == "set":
            return cmd_modules_set(args.mode, args.server)
        if args.modules_cmd in ("enable", "disable"):
            return cmd_modules_toggle(args.name, args.modules_cmd == "enable",
                                      getattr(args, "server", None))
        return cmd_modules_apply(pair=not args.no_pair)
    if args.cmd == "setup-code":
        return cmd_setup_code(args.new, args.revoke_trusted)
    return cmd_ensure_fields()
