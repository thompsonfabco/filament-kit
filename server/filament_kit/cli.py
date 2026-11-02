"""Command line: status, pair, unpair, config, cert, ensure-fields, printer map / unpin, library, profiles, modules."""
from __future__ import annotations

import argparse
import copy
import getpass
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

from . import apply, config, inventory, library, modules, pairing
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
    try:
        stamps = json.loads((config.paths().state / "reads.json").read_text(encoding="utf-8"))
        return sum(1 for t in stamps if t > time.time() - 86400)
    except (OSError, ValueError, TypeError):
        return 0


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
    try:
        state = StationClient(url, backoff=0).state()
    except StationUnreachable:
        return _line(False, f"station not answering at {url}",
                     f"check the station machine: sudo systemctl status filament-kit-station  (url {url})")
    good = _line(True, f"station answering at {url}")
    # a fresh station has seen neither the reader nor the scale: informational, not a failure.
    # "tag" is always an object; its nfc_id stays null until the reader has read a tag.
    if not (state.get("tag") or {}).get("nfc_id"):
        print("--   station reader not seen")
    if not state.get("scale") and not state.get("last_weight"):
        print("--   station scale not seen")
    return good


def cmd_status(client_factory) -> int:
    cfg = config.load()
    p = config.paths()
    on = modules.enabled(cfg)
    good = True

    if _no_systemd():
        print("--   service checks skipped (FK_NO_SYSTEMD=1)")
    else:
        for svc in services_for(on):
            try:
                r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=15)
                active = r.stdout.strip() == "active"
            except (OSError, subprocess.SubprocessError):
                active = False
            good &= _line(active, f"service {svc} active", f"sudo systemctl start {svc}")
        if "server" in on:
            ok, url = _api_answers(cfg["port"])
            good &= _line(ok, f"filament-kit API {'answering' if ok else 'not answering'} at {url}",
                          "sudo journalctl -u filament-kit -n 50")

    if "server" in on or "spoolman" in on:
        try:
            version = Spoolman(cfg["spoolman_url"]).ping()
            good &= _line(True, f"Spoolman reachable at {cfg['spoolman_url']} (v{version})")
        except SpoolmanError as e:
            good &= _line(False, f"Spoolman not reachable at {cfg['spoolman_url']}: {e}",
                          "sudo systemctl start spoolman" if "spoolman" in on
                          else "check that the remote Spoolman is running and spoolman_url is right")

    if "ai_intake" in on:
        keyfile = p.etc / KEY_FILE
        try:
            key = keyfile.read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
        if not key:
            good &= _line(False, f"Anthropic key missing ({keyfile})", "run: sudo filament-kit config  (option 4)")
        else:
            try:
                client_factory(key).models.list()
                good &= _line(True, "Anthropic key accepted")
            except Exception as e:  # noqa: BLE001 - any failure means the key/network is unusable
                msg = str(e).replace(key, "***")
                good &= _line(False, f"Anthropic key not accepted or API unreachable: {msg}",
                              "run: sudo filament-kit config  (option 4) or check internet access")

    if "server" in on:
        cert = p.etc / "cert.pem"
        if cert.exists():
            good &= _line(True, f"certificate present, fingerprint {pairing.fingerprint(cert.read_bytes())}")
        else:
            good &= _line(False, f"certificate missing ({cert})", "run: sudo filament-kit cert")

    station_url = (cfg.get("station") or {}).get("url")
    if station_url:
        good &= _station_lines(station_url)

    if "server" in on:
        print(f"--   display name: {cfg['server_name']}")
        print(f"--   paired devices: {len(pairing.devices())}")
        print(f"--   reads used today: {_reads_today()} of {cfg['reads_per_day']}")
    if "presets" in on:
        good &= _profile_status_lines()
    elif "library" in on:
        try:
            _library_status_lines()
        except Exception as e:  # noqa: BLE001 - status reports, it does not crash
            print(f"--   library: could not be read ({e.__class__.__name__}: {e})")
    return 0 if good else 1


def _library_status_lines() -> None:
    st = library.status()
    source = st["source"]
    if source == "updated":
        at = (library._pointer("current.json") or {}).get("at")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            source = f"updated {time.strftime('%Y-%m-%d', time.localtime(at))}"
    n = st["local"]
    print(f"--   library version {st['version']} ({source}), {n} local addition{'' if n == 1 else 's'}")
    lc = st["last_check"]
    if lc is not None and not lc["ok"]:
        # a warning, not a failure: the bundled or last good version stays in use
        print(f"--   library update: {lc['error']}")


def _attempt_failed(st: dict) -> str | None:
    """The last build attempt's error, unless it only waited for the first PC sync (a normal state)."""
    la = st.get("last_attempt") or {}
    if la.get("ok") is False and la.get("error") and la["error"] != builds.NO_SYSTEM:
        return str(la["error"])
    return None


def _profile_status_lines() -> bool:
    good = True
    try:
        _library_status_lines()
    except Exception as e:  # noqa: BLE001 - status reports, it does not crash
        print(f"--   library: could not be read ({e.__class__.__name__}: {e})")
    try:
        st = builds.status()
    except Exception as e:  # noqa: BLE001
        return _line(False, f"profiles: status could not be read ({e.__class__.__name__}: {e})",
                     "sudo journalctl -u filament-kit-build -n 50")
    b = st.get("build")
    error = _attempt_failed(st)
    if error is not None:
        good &= _line(False, f"profiles: last build failed: {error}; "
                             + (f"using build {b['stamp']}" if b else "no good build yet"),
                      "sudo journalctl -u filament-kit-build -n 50")
    elif b:
        good &= _line(True, f"profiles: build {b['stamp']}, {st.get('presets', 0)} presets for "
                            f"{st.get('lines', 0)} lines ({b.get('problems', 0)} problems)")
    else:
        print("--   profiles: no build yet (waiting for the PC sync)")
    pc = st.get("pc")
    if pc:
        inst = st.get("installed")
        print(f"--   PC sync: last upload {_fmt_time(pc.get('last_upload'))}, "
              + (f"installed build {inst['stamp']}" if inst else "no build installed yet"))
    else:
        print("--   PC sync: not set up (see README: Pair your PC)")
    return good


# ---------- pair / unpair ----------

def _qr_text(payload: str) -> str:
    if shutil.which("qrencode"):
        try:
            r = subprocess.run(["qrencode", "-t", "ansiutf8", payload], capture_output=True,
                               text=True, timeout=10, check=True)
            return r.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return payload


def cmd_pair(pc: bool = False) -> int:
    try:
        pr = pairing.issue(device_hint="pc") if pc else pairing.issue()
    except pairing.PairingError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if pc:
        # the PC has no QR scanner: the link is pasted into filament-kit-sync (printed by design, never logged)
        print("Link for filament-kit-sync (paste it when asked):")
        print(pr.qr)
        fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
        print("Certificate fingerprint (check it matches the one the PC shows):")
    else:
        print(_qr_text(pr.qr))
        fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
        print("Certificate fingerprint (check it matches the phone):")
    print("  " + " ".join(fp[i:i + 4] for i in range(0, len(fp), 4)))
    print(f"Pairing code: {pr.code}")
    print(f"Expires at {time.strftime('%H:%M:%S', time.localtime(pr.expires))} "
          f"(in {max(0, int(pr.expires - time.time()) // 60)} min)")
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
        ip = (_ask("IP address: ") or "").strip()
        serial = (_ask("Serial number: ") or "").strip()
        if not (name and ip and serial):
            print("Name, IP address and serial number are all needed.")
            return
        if not registry.SERIAL.fullmatch(serial):
            print(f"Not added: {registry.BAD_SERIAL}.")
            return
        # a printer added by hand may never announce its model, and the model decides which camera it has
        model = (_ask("Model (e.g. H2D, X1C, P1S; Enter to skip): ") or "").strip()
        code = getpass.getpass("Access Code (hidden): ").strip()
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


def cmd_config() -> int:
    cfg = config.load()
    before = _module_state(cfg)
    while True:
        print("\nfilament-kit settings\n"
              f"  1) display name       {cfg['server_name']}\n"
              "  2) storage\n"
              f"  3) Claude model       {cfg['model']}, {cfg['reads_per_day']} reads/day\n"
              "  4) Anthropic key\n"
              "  5) Printers\n"
              f"  6) Modules            {modules.mode_of(modules.enabled(cfg))}\n"
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
            key = getpass.getpass("Anthropic API key (hidden): ").strip()
            if key:
                write_key(key)
                print("Key saved.")
            else:
                print("No key entered; unchanged.")
        elif choice == "5":
            _printers_menu()
        elif choice == "6":
            _modules_menu(cfg)
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
    print("created fields: " + ", ".join(created) if created else "fields already present")
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
        print(f"  {s['label']}: AMS {s['ams_id']} tray {s['tray_id']} -> printer slot {s['global']}")
    for prob in v["problems"]:
        print(f"  problem: {prob}")
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
    if r.error:
        if scheduled and r.http_status in library.PRIVATE_STATUSES:
            # the repository may simply not be public yet: the timer run is not a failure, the bundled
            # or last good version stays in use
            print(f"warning: {r.error}", file=sys.stderr)
            return 0
        _err_line(r.error)
        return 1
    if not r.changed:
        print(f"library version {r.version} is up to date")
        return 0
    print(f"library version {r.version} installed ({r.downloaded} entr{'y' if r.downloaded == 1 else 'ies'} "
          f"downloaded)")
    _request_rebuild(f"library updated to version {r.version}")
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
        print(f"build: {b['stamp']} ({_fmt_time(b.get('created'))}), {st['presets']} presets, "
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
    print(f"PC sync: device {pc['device_id']}, last upload {_fmt_time(pc.get('last_upload'))}" if pc
          else "PC sync: not set up (see README: Pair your PC)")
    for name in st["stale"]:
        print(f"  delete in Bambu Studio: {name}")
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
    for row in ((builds.manifest(c["stamp"]) or {}).get("presets", []) if c else []):
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


def cmd_profiles_set_parent(line_id: str, parent: str, orca: bool = False) -> int:
    parent = parent.strip()
    try:
        if not parent:
            raise ValueError("give the name of an Orca Slicer library preset (without ' @System')" if orca
                             else "give the name of a Bambu Studio system preset")
        inventory.check_line_text("set-parent", "parent", parent)
        if orca:
            lines_mod.check_orca_parent(parent, builds.orca_store())
        else:
            lines_mod.check_parent(parent, builds.system_store())
    except (ValueError, ProfileError) as e:
        _err_line(str(e))
        return 1
    try:
        line = lines_mod.set_parent_saved(line_id, parent, target="orca" if orca else "bambu")
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
    _request_rebuild(f"{'Orca ' if orca else ''}parent of line {line.line_id} set")
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
    apply.finish(cfg, pairing=pairing)
    return 0


def cmd_modules_apply() -> int:
    return _run_apply(pairing=True)


def _module_state(cfg: dict) -> tuple:
    """What an apply cares about: the module set and the station link."""
    st = cfg.get("station") or {}
    return (modules.enabled(cfg), st.get("url"), tuple(st.get("allow") or ()))


def _with_modules(cfg: dict, on) -> dict:
    """Copy of cfg with every module name written true/false (never an empty dict)."""
    out = copy.deepcopy(cfg)
    out["modules"] = {n: n in on for n in modules.MODULES}
    return out


def _link_station(cfg: dict) -> None:
    """Station on beside the server: all-in-one semantics (spec section 3)."""
    st = cfg.setdefault("station", {})
    st["allow"] = ["127.0.0.1"]
    st["url"] = "http://127.0.0.1:5003"


def _change_module(cfg: dict, name: str, want_on: bool, *, confirm=None, ask_address=None,
                   server: str | None = None) -> str | None:
    """Turn `name` on/off in `cfg` (in place). Returns an error text, or None when changed.

    `confirm(text) -> bool` is asked before dependents go off too (None: refuse).
    `ask_address() -> str | None` supplies the server address for a station without a server."""
    if name not in modules.MODULES:
        return f"unknown module {name!r}"
    on = set(modules.enabled(cfg))
    if want_on:
        missing = [d for d in modules.MODULES[name].depends if d not in on]
        if missing:
            listed = ", ".join(missing)
            return f"{name} needs {listed}\nfix: enable {listed} first"
        on.add(name)
    else:
        deps = modules.dependents(name, frozenset(on))
        if deps:
            listed = ", ".join(deps)
            if confirm is None or not confirm(f"Also turn off {listed}? [y/N] "):
                return f"{listed} depend on {name}\nfix: disable {listed} first"
            on -= set(deps)
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
    try:
        modules.validate(new)
    except modules.ModuleError as e:
        return str(e)
    cfg.clear()
    cfg.update(new)
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


def _save_and_apply(cfg: dict) -> int:
    err = _plan_error(cfg)
    if err:
        print(f"error: {err}\nNothing was changed.", file=sys.stderr)
        return 1
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
    err = _change_module(cfg, name, want_on, confirm=_tty_confirm, server=server)
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return _save_and_apply(cfg)


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


def _modules_menu(cfg: dict) -> None:
    names = list(modules.MODULES)
    while True:
        on = modules.enabled(cfg)
        print(f"\nModules (mode: {modules.mode_of(on)})")
        for i, n in enumerate(names, 1):
            m = modules.MODULES[n]
            print(f"  {i}) {'on ' if n in on else 'off'}  {m.title}: {m.description}")
        print("  m) choose mode\n  0) back")
        choice = _ask("> ")
        if choice is None or choice.strip() == "0":
            return
        choice = choice.strip().lower()
        if choice == "m":
            modes = list(modules.MODES)
            for i, m in enumerate(modes, 1):
                print(f"  {i}) {m}")
            pick = _ask_int("Mode: ", 1)
            if pick is None or pick > len(modes):
                print("Unknown mode.")
                continue
            mode = modes[pick - 1]
            new = modules.set_mode(cfg, mode)
            if mode == "station":
                addr = _ask_station_server()
                if addr is None:
                    print("Unchanged.")
                    continue
                new["station"]["allow"] = [addr]
            try:
                modules.validate(new)
            except modules.ModuleError as e:
                print(f"error: {e}")
                continue
            cfg.clear()
            cfg.update(new)
        elif choice.isdigit() and 1 <= int(choice) <= len(names):
            name = names[int(choice) - 1]
            err = _change_module(cfg, name, name not in on,
                                 confirm=lambda t: (_ask(t) or "").strip().lower() in ("y", "yes"),
                                 ask_address=_ask_station_server)
            if err:
                print(f"error: {err}")
        else:
            print("Unknown choice.")


def main(argv: list[str] | None = None, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    ap = argparse.ArgumentParser(prog="filament-kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="check services, Spoolman, key, certificate")
    pp = sub.add_parser("pair", help="show a QR code and code to pair a phone (--pc: a link for the PC sync)")
    pp.add_argument("--pc", action="store_true", help="pair the Windows PC sync: print the link, no QR code")
    up = sub.add_parser("unpair", help="list or remove paired phones")
    up.add_argument("device_id", nargs="?")
    sub.add_parser("config", help="interactive settings menu")
    sub.add_parser("cert", help="create the server certificate if missing")
    sub.add_parser("ensure-fields", help="create the Spoolman extra fields")
    pr = sub.add_parser("printer", help="printer tasks: map slots, forget a certificate")
    psub = pr.add_subparsers(dest="printer_cmd", required=True)
    pm = psub.add_parser("map", help="map the AMS slots (changes slot colours briefly, runs a no-motion job)")
    pm.add_argument("serial")
    pu = psub.add_parser("unpin", help="forget the printer's pinned TLS certificate")
    pu.add_argument("serial")
    lb = sub.add_parser("library", help="the filament spec library: status, update, rollback, local additions")
    lsub = lb.add_subparsers(dest="library_cmd", required=True)
    lsub.add_parser("status", help="show the library version, local additions and the last update check")
    lu = lsub.add_parser("update", help="fetch the latest library version")
    lu.add_argument("--scheduled", action="store_true", help="only if config library.schedule says it is due")
    lsub.add_parser("rollback", help="go back to the library version before the last update")
    la = lsub.add_parser("add", help="add or replace a local entry from a JSON file ('-' reads stdin)")
    la.add_argument("file")
    pf = sub.add_parser("profiles", help="the generated Bambu Studio presets: build, status, lines, parents")
    pfsub = pf.add_subparsers(dest="profiles_cmd", required=True)
    pfsub.add_parser("build", help="build the presets now (needs the PC sync to have run once)")
    pfsub.add_parser("status", help="show the last build, the PC sync and the problems")
    pfsub.add_parser("lines", help="list the product lines and their Bambu Studio and Orca Slicer parents")
    sp = pfsub.add_parser("set-parent", help="set the Bambu Studio system preset a line is built from")
    sp.add_argument("line_id")
    sp.add_argument("parent")
    sp.add_argument("--orca", action="store_true",
                    help="set the line's Orca Slicer library parent instead (the name without ' @System')")
    pfsub.add_parser("restore-deleted", help="bring back the presets deleted in Bambu Studio at the next build")
    md = sub.add_parser("modules", help="the switchable parts of the kit: apply the settings, list units")
    mdsub = md.add_subparsers(dest="modules_cmd", required=True)
    mdsub.add_parser("apply", help="install, start and stop what config.json's modules say (root)")
    mdsub.add_parser("list", help="show each module on/off and the mode")
    ms = mdsub.add_parser("set", help="switch to an install mode and apply (root)")
    ms.add_argument("mode", choices=list(modules.MODES))
    ms.add_argument("--server", help="the kit server's name or IP (station mode)")
    me = mdsub.add_parser("enable", help="turn a module on and apply (root)")
    me.add_argument("name")
    me.add_argument("--server", help="the kit server's name or IP (when enabling station without a server)")
    mx = mdsub.add_parser("disable", help="turn a module off and apply; its data is kept (root)")
    mx.add_argument("name")
    mdsub.add_parser("units", help="print every systemd unit of every module, one per line")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        return cmd_status(client_factory or _default_client)
    if args.cmd == "pair":
        return cmd_pair(pc=args.pc)
    if args.cmd == "unpair":
        return cmd_unpair(args.device_id)
    if args.cmd == "config":
        return cmd_config()
    if args.cmd == "cert":
        return cmd_cert()
    if args.cmd == "printer":
        if args.printer_cmd == "map":
            return cmd_printer_map(args.serial, manager_factory or _default_manager)
        return cmd_printer_unpin(args.serial)
    if args.cmd == "library":
        if args.library_cmd == "status":
            return cmd_library_status()
        if args.library_cmd == "update":
            return cmd_library_update(args.scheduled)
        if args.library_cmd == "rollback":
            return cmd_library_rollback()
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
        return cmd_profiles_restore_deleted()
    if args.cmd == "modules":
        if args.modules_cmd == "units":
            return cmd_modules_units()
        if args.modules_cmd == "list":
            return cmd_modules_list()
        if args.modules_cmd == "set":
            return cmd_modules_set(args.mode, args.server)
        if args.modules_cmd in ("enable", "disable"):
            return cmd_modules_toggle(args.name, args.modules_cmd == "enable",
                                      getattr(args, "server", None))
        return cmd_modules_apply()
    return cmd_ensure_fields()
