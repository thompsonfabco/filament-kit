"""Command line: status, pair, unpair, config, cert, ensure-fields, printer map / unpin."""
from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import config, pairing
from .bridge import registry
from .spoolman import Spoolman, SpoolmanError

KEY_FILE = "anthropic_key"
SERVICES = ("spoolman", "filament-kit")


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


def cmd_status(client_factory) -> int:
    cfg = config.load()
    p = config.paths()
    good = True

    if _no_systemd():
        print("--   service checks skipped (FK_NO_SYSTEMD=1)")
    else:
        for svc in SERVICES:
            try:
                r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=15)
                active = r.stdout.strip() == "active"
            except (OSError, subprocess.SubprocessError):
                active = False
            good &= _line(active, f"service {svc} active", f"sudo systemctl start {svc}")
        ok, url = _api_answers(cfg["port"])
        good &= _line(ok, f"filament-kit API {'answering' if ok else 'not answering'} at {url}",
                      "sudo journalctl -u filament-kit -n 50")

    try:
        version = Spoolman(cfg["spoolman_url"]).ping()
        good &= _line(True, f"Spoolman reachable at {cfg['spoolman_url']} (v{version})")
    except SpoolmanError as e:
        good &= _line(False, f"Spoolman not reachable at {cfg['spoolman_url']}: {e}",
                      "sudo systemctl start spoolman")

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

    cert = p.etc / "cert.pem"
    if cert.exists():
        good &= _line(True, f"certificate present, fingerprint {pairing.fingerprint(cert.read_bytes())}")
    else:
        good &= _line(False, f"certificate missing ({cert})", "run: sudo filament-kit cert")

    print(f"--   display name: {cfg['server_name']}")
    print(f"--   paired devices: {len(pairing.devices())}")
    print(f"--   reads used today: {_reads_today()} of {cfg['reads_per_day']}")
    return 0 if good else 1


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


def cmd_pair() -> int:
    try:
        pr = pairing.issue()
    except pairing.PairingError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(_qr_text(pr.qr))
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    print("Certificate fingerprint (check it matches the phone):")
    print("  " + " ".join(fp[i:i + 4] for i in range(0, len(fp), 4)))
    print(f"Pairing code: {pr.code}")
    print(f"Expires at {time.strftime('%H:%M:%S', time.localtime(pr.expires))} "
          f"(in {max(0, int(pr.expires - time.time()) // 60)} min)")
    return 0


def _fmt_time(t) -> str:
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
    while True:
        print("\nfilament-kit settings\n"
              f"  1) display name       {cfg['server_name']}\n"
              "  2) storage\n"
              f"  3) Claude model       {cfg['model']}, {cfg['reads_per_day']} reads/day\n"
              "  4) Anthropic key\n"
              "  5) Printers\n"
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
        else:
            print("Unknown choice.")
    config.save(cfg)
    print("Saved.")
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


def cmd_printer_map(serial: str, manager_factory) -> int:
    from .bridge import mapping
    from .bridge.connection import PrinterOffline, UnknownPrinter
    from .bridge.slottest import PrinterBusy
    p = registry.load().get(serial)
    if p is None or not p.configured:
        _err_line(f"no printer {serial} is set up (see: sudo filament-kit config, Printers)")
        return 1
    print(f"Mapping the slots of {p.name or serial}. Each slot's colour changes briefly and the printer runs a "
          f"job with no heating and no motion.")
    m = manager_factory(serial)
    try:
        m.sync()
        m.wait_settled(serial, CONNECT_WAIT)
        m.wait_report(serial, lambda r: "gcode_state" in r, REPORT_WAIT)
        try:
            v = mapping.Mapper(m).run(serial, on_step=lambda t: print(f"  {t}", flush=True))
        except mapping.AlreadyRunning:
            _err_line("slot mapping is already running for this printer")
            return 1
        except mapping.CertChanged:
            _err_line("the printer's certificate changed; add it again with its Access Code "
                      "(or, if you trust the new one, run: sudo filament-kit printer unpin " + serial + ")")
            return 1
        except PrinterBusy as e:
            _err_line(f"the printer is busy ({e}); try again once it is idle")
            return 1
        except (PrinterOffline, UnknownPrinter):
            _err_line("the printer is offline (or its Access Code is wrong); check that it is on and on the network")
            return 1
    finally:
        m.stop()
    for s in v["slots"]:
        print(f"  {s['label']}: AMS {s['ams_id']} tray {s['tray_id']} -> printer slot {s['global']}")
    for prob in v["problems"]:
        print(f"  problem: {prob}")
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


def main(argv: list[str] | None = None, *, client_factory=None, manager_factory=None) -> int:
    ap = argparse.ArgumentParser(prog="filament-kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="check services, Spoolman, key, certificate")
    sub.add_parser("pair", help="show a QR code and code to pair a phone")
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
    args = ap.parse_args(argv)

    if args.cmd == "status":
        return cmd_status(client_factory or _default_client)
    if args.cmd == "pair":
        return cmd_pair()
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
    return cmd_ensure_fields()
