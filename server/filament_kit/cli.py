"""Command line: status, pair, devices, recent, config, cert, ensure-fields, printer (list, show, test, add, map, ...), library,
profiles, modules, web, remote, setup-code."""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import http.client
import io
import json
import os
import re
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__
from . import storage, storage_api
from . import hostaddr, apply, config, inventory, klipper_cli, library, locations_cli, menu_ui, modules, output, pairing, qr, secret_input, steps
from . import status as status_rows
from .bridge import registry
from .profiles import builds, lines as lines_mod
from .profiles.errors import ProfileError
from .spoolman import Spoolman, SpoolmanError
from .station_client import StationClient, StationUnreachable, station_reach

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
        output.note(f"could not restart filament-kit: {e}")


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


def _hardware_lines() -> bool:
    return status_rows.print_rows(status_rows.hardware_rows())


def cmd_status(client_factory, station_pairing: str | None = None) -> int:
    """`station_pairing`: the wrapper's answer from root (server_api.pairing_state), for a status run as the service
    user, which can't read the station's pairing."""
    with output.wait("Checking…", programs=True):
        rows = list(status_rows.rows(client_factory=client_factory, station_pairing=station_pairing))
    if not (output.json_mode() or output.quiet()):
        output.out(status_rows.header_line())
        output.out()
    return 0 if status_rows.print_rows(rows, summary=True) else output.FAILED


def _library_status_lines() -> None:
    status_rows.print_rows(status_rows.library_rows())


def _attempt_failed(st: dict) -> str | None:
    """The last build attempt's error, unless it only waited for the first PC sync (a normal state)."""
    la = st.get("last_attempt") or {}
    if la.get("ok") is False and la.get("error") and la["error"] != builds.NO_SYSTEM:
        return str(la["error"])
    return None


# ---------- pair / unpair ----------

def _qr_text(payload: str) -> str:
    """The QR code as block characters with its 4-module quiet zone (drawn by the Hub: qr.py); the link itself when it
    does not fit one."""
    return qr.text(payload) or payload


def _station_server(cfg: dict) -> str:
    """The kit server's address a station-only machine answers (its first non-loopback station.allow), or ""."""
    allow = (cfg.get("station") or {}).get("allow") or []
    return next((str(a).strip() for a in allow if str(a).strip() not in ("127.0.0.1", "localhost", "::1")), "")


def _fingerprint_lines(fp: str) -> list[str]:
    """The certificate fingerprint in groups of four, eight groups to a line."""
    groups = [fp[i:i + 4] for i in range(0, len(fp), 4)]
    return ["  " + " ".join(groups[i:i + 8]) for i in range(0, len(groups), 8)]


def _pending_device(token: str) -> str | None:
    """The id of the device a fresh pairing made, whose first use or code claims it."""
    h = pairing._hash(token)
    return next((d["id"] for d in pairing._read("devices.json") if d.get("hash") == h), None)


PAIR_POLL = 1.0         # seconds between looks for the device while `pair` waits (the Hub page looks every 3)


def _wait_for_device(device_id: str | None, expires: float, who: str, cmd: str) -> int:
    """06 9.4: wait until the device has paired or the code runs out. Ctrl-C stops the wait; the code stays valid."""
    if device_id is None:               # the pairing is gone already (nothing to watch)
        return 0
    until = time.strftime("%H:%M", time.localtime(expires))
    paired = None
    try:
        with output.wait(f"Waiting for {who}… (the code works until {until})"):
            while True:
                paired = next((d for d in pairing.devices() if d["id"] == device_id), None)
                if paired is not None or time.time() >= expires:
                    break
                time.sleep(PAIR_POLL)
    except KeyboardInterrupt:
        output.out(f"Stopped waiting. The code works until {until}.")
        return output.INTERRUPTED
    if paired is None:
        output.error("the pairing code expired before a device paired.", "make a new one with:", cmd=cmd)
        return output.FAILED
    output.result(f"Paired: {paired['name']}.")
    return 0


def cmd_pair(slicer_sync: bool = False, weigh_station: bool = False, text: bool = False, wait: bool = True) -> int:
    """`pair` (06 9.4): what the Hub page's pairing dialog shows, in its order (the QR code for a phone, the instruction,
    the pairing code, the certificate fingerprint, the expiry), then waits for the device. `--json` ends after the document."""
    cmd = "sudo spoolwarden pair" + (" --slicer-sync" if slicer_sync else " --weigh-station" if weigh_station else "")
    cfg = config.load()                 # unreadable: main() says to run it with sudo
    if "server" not in modules.enabled(cfg):
        # a Weigh Station (or another machine without the Hub): no certificate here, and none is needed
        addr = _station_server(cfg)
        output.error("this machine has no Hub, so it cannot pair devices.",
                     "run it on the Hub" + (f" ({addr}, from station.allow)." if addr else "."))
        return 1
    try:
        pr = pairing.issue(device_hint="pc" if slicer_sync else "station" if weigh_station else "",
                           scope="station" if weigh_station else None)
    except pairing.PairingError as e:
        # /etc/filament-kit is root's: as a user the certificate cannot be read (or even seen)
        unreadable = isinstance(e, pairing.CertUnreadable) or not _is_root()
        _err_line(f"{e}" + (f"\nfix: run it with sudo: {cmd}" if unreadable else ""))
        return 1
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    if output.json_mode():
        output.emit({"ok": True, "code": pr.code, "link": pr.qr, "fingerprint": fp, "expires": _iso(pr.expires)})
        return 0
    text = text or output.plain()       # --plain: no QR code (06 6.2)
    if slicer_sync or weigh_station:
        # no QR scanner there: the link is pasted (printed by design, never logged)
        output.out("Paste this link into the Slicer Sync when it asks:" if slicer_sync else
                   "On the Weigh Station run: sudo spoolwarden station pair, then paste this link:")
        output.out(pr.qr)
    elif text:
        # no terminal (an install log): the link as text, for a phone that gets it some other way
        output.out("Open the Spoolwarden app and type the pairing code, or give it this link:")
        output.out(pr.qr)
    else:
        print(_qr_text(pr.qr), flush=True)
        output.out("Open the Spoolwarden app and scan this code, or type the pairing code.")
    output.out(f"Pairing code: {pr.code[:3]} {pr.code[3:]}")
    output.out("Certificate fingerprint (" + ("the phone asks for two groups of it" if not (slicer_sync or weigh_station)
               else f"check it matches the one the {'Slicer Sync' if slicer_sync else 'Weigh Station'} shows") + "):")
    output.out_lines(_fingerprint_lines(fp))
    output.out(f"Expires at {time.strftime('%H:%M', time.localtime(pr.expires))} "
               f"(in {max(1, -(-int(pr.expires - time.time()) // 60))} min).")
    if not wait:                        # 06 9.4 (R68): the code, then when it stops working; no waiting line
        output.out(f"The code works until {time.strftime('%H:%M', time.localtime(pr.expires))}.")
        return 0
    return _wait_for_device(_pending_device(pr.token), pr.expires,
                            "Slicer Sync" if slicer_sync else "the Weigh Station" if weigh_station else "the phone", cmd)


def _paired_with_hub(link, result) -> None:
    """`Paired with the Hub at 192.0.2.10.`, then what happened to the service (the rest of the pairing's own message)."""
    output.emit({"ok": True, "address": link.host})
    output.result(f"Paired with the Hub at {link.host}.")
    rest = result.message.partition("Paired.")[2].strip().replace("modules enable station", "features on weigh-station")
    if rest and result.status != "paired_not_restarted":
        output.result(rest)


def cmd_station_pair(ask=input) -> int:
    """On the Weigh Station's computer: take the link from `spoolwarden pair --weigh-station`, check the Hub's
    fingerprint with the owner, save the pairing for the button flow (station/server_api.py). Nothing answers the
    comparison but a person: no `--yes`."""
    from .station import server_api
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return output.need_sudo(_sudo_command("sudo spoolwarden weigh-station pair"))
    if ask is input and not output.terminal():
        output.error("pairing asks for the link and for you to compare the fingerprint, and there is no terminal to ask.",
                     "run it at a terminal:", cmd=_sudo_command("sudo spoolwarden weigh-station pair"))
        return output.USAGE
    no_terminal = ("sudo spoolwarden weigh-station pair needs a terminal: it asks for the link and for you to "
                   "compare the fingerprint. Nothing was saved.")
    try:
        text = ask("Paste the link from the Hub (sudo spoolwarden pair --weigh-station): ")
    except (EOFError, RuntimeError, OSError):  # `< /dev/null`; `<&-` is no stdin (RuntimeError) or a dead one (OSError)
        _err_line(no_terminal)
        return 1
    try:
        link = server_api.parse_link(text)
    except ValueError as e:
        _err_line(str(e))
        return 1

    def owner_compares(seen: str) -> bool:
        with output.shown():
            output.out_lines(_fingerprint_lines(seen))
        try:
            answer = ask("Does it match the fingerprint the Hub shows? [y/N] ")
        except (EOFError, RuntimeError, OSError):  # no answer is a no
            _err_line(no_terminal)
            return False
        return answer.strip().lower() in ("y", "yes")

    result = server_api.pair_with_link(link, confirm=owner_compares)
    if result.status == "declined":
        output.result("Not paired. Nothing changed.")
        return output.CANCELLED
    if result.status == "failed":
        _err_line(result.message)
        return 1
    if result.status == "paired_not_restarted":
        output.note(result.message)
    _paired_with_hub(link, result)
    return 0


def _port_check(port: str, boards: list[tuple[str, ...]], what: str) -> str | None:
    """`--port` names a board the command would itself offer: its own scan's boards, each a port and its other names.
    The board's port when it is one of them; otherwise the Error and Fix are said and None is returned (exit 2)."""
    if not port.strip():
        output.error("--port needs the board's port name; nothing was written.",
                     ("use one of: " + ", ".join(b[0] for b in boards) + ".") if boards else
                     "no board was found; plug it into this PC with a data cable (a charge-only cable shows nothing).")
        return None
    want = os.path.realpath(port)
    for names in boards:
        if any(n == port or os.path.realpath(n) == want for n in names):
            return names[0]
    output.error(f"{port} is not one of the boards {what}; nothing was written.",
                 ("use one of: " + ", ".join(b[0] for b in boards) + ".") if boards else
                 "no such board was found; plug it into this PC with a data cable (a charge-only cable shows nothing).")
    return None


def cmd_station_flash_panel(ask=input, run=subprocess.run, yes: bool = False, only_port: str | None = None) -> int:
    """On the station PC: write the panel firmware to a blank ESP32-C3 board. A Printer Station plugged in for power looks
    the same as a blank panel, so each candidate port is flashed only after the owner says yes to that port."""
    from .station import panel
    if not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden weigh-station flash-display"))
    if not yes and ask is input and not output.terminal():     # nobody to ask which board: nothing is stopped or written
        return output.no_terminal("writing the firmware",
                                  _sudo_command("sudo spoolwarden weigh-station flash-display") + " --yes")
    service = "filament-kit-station.service"
    was_active = run(["systemctl", "is-active", service], check=False).returncode == 0  # only restart what was running
    try:
        with output.wait("Stopping the Weigh Station service…", programs=True):
            stopped = run(["systemctl", "stop", service], check=False)
        if stopped.returncode not in (0, 5):  # 5: the unit isn't loaded (no service to stop)
            _err_line(f"could not stop {service} (systemctl exit {stopped.returncode}); its panel port may look "
                      "blank. Nothing was flashed.")
            return 1
        version = panel.fw_version()
        if not version:
            _err_line("this station has no panel firmware bundled; nothing was flashed.")
            return 1
        ports = panel.blank_c3_ports()
        if only_port is not None:       # only a board this scan would offer: not the PN532, a running panel or a path that is no board
            only_port = _port_check(only_port, [(p,) for p in ports], "weigh-station flash-display would write")
            if only_port is None:
                return output.USAGE
            ports = [only_port]
        if not ports:
            output.error("no blank display board found on USB.", "plug the display in with a data cable, then run this "
                         "again (a board that already runs the display firmware does not need flashing).")
            return 1
        if yes and len(ports) > 1:      # --yes answers for one named board, never for a pick among several (06 7)
            output.error("more than one board could be the intake panel: " + ", ".join(ports) + "; nothing was written.",
                         "name the board with --port, for example --port " + ports[0] + ".")
            return output.USAGE
        for port in ports:
            if only_port is None:
                print(f"Found a USB serial board on {port} that does not answer as the intake panel.")
            try:
                stop = _confirm(f"Write the intake panel firmware to {port}?",
                                "writing the firmware", yes=yes, ask=None if ask is input else ask)
            except KeyboardInterrupt:
                output.result("\nNothing was flashed.")
                return 1
            if stop is None:
                return _flash_and_verify(panel, port, version)
        return output.CANCELLED     # every board was declined: "Nothing changed." was said
    finally:
        if was_active:
            started = run(["systemctl", "start", service], check=False)
            if started.returncode == 0:
                output.result("Started the Weigh Station service again.")
            else:
                output.error(f"could not start {service} again (systemctl exit {started.returncode}).",
                             "see why:", cmd=f"sudo journalctl -u {service} -n 50")


def _flash_and_verify(panel, port: str, version: str) -> int:
    """Flash port, then ask the board for its HELLO: success only when it reports the bundled version."""
    with output.wait(f"Writing the firmware to {port}…", programs=True):
        written = panel.flash_panel(port, version)
    if not written:
        _err_line(f"writing the firmware to {port} failed (esptool); the board may still be blank. Unplug and "
                  "replug it, then run this again.")
        return 1
    time.sleep(2)
    ser = panel.open_panel(port)
    seen = ser.panel_version if ser else None
    if ser:
        ser.close()
    if seen != version:
        _err_line(f"{port} was written but does not answer with firmware {version}"
                  + (f" (it says {seen})" if seen else "") + ". Unplug and replug it, then run this again.")
        return 1
    output.emit({"ok": True, "port": port, "version": version})
    output.out_lines(output.status_row("done", "The display answered."))
    return 0


def cmd_station_pair_local() -> int:
    """`station pair --local`: the station on the machine that is also the kit server (the setup page's button). Nothing
    to compare by eye, nothing to paste: this machine makes the link, and pair_with_link checks the certificate it finds
    on loopback against it. Prints no token: the output goes to the page's job log."""
    from .station import server_api
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return output.need_sudo(_sudo_command("sudo spoolwarden weigh-station pair --local"))
    if "server" not in modules.enabled(config.load()):
        _err_line("--local pairs a Weigh Station with the Hub on the same machine, and the Hub service is off "
                  "here.\nfix: run sudo spoolwarden pair --weigh-station on the Hub, then sudo spoolwarden "
                  "weigh-station pair here")
        return 1
    try:
        result = server_api.pair_with_link(server_api.parse_link(pairing.issue(device_hint="station", scope="station").qr),
                                           step=steps.Steps(3).next)
    except (pairing.PairingError, ValueError) as e:
        _err_line(str(e))
        return 1
    if result.status in ("failed", "paired_not_restarted"):
        print(result.message, file=sys.stderr)
    else:
        output.emit({"ok": True})
        output.result("The Weigh Station on this machine is paired with this Hub.")
    return 1 if result.status == "failed" else 0


_BACKUP_KIND = {"made": "made here", "pre-restore": "before a restore", "daily": "nightly"}     # the Hub page's words


def cmd_backup(action: str, out: str | None, days: int | None = None) -> int:
    """`backup create`, `list` and `keep <days>` (06 9.10); the same helper functions the Hub page's routes use."""
    from . import backup, setup_helper
    if not _is_root():
        return output.need_sudo(_sudo_command(f"sudo spoolwarden backup {action}" + (f" {days}" if days else "")))
    if action == "keep":
        try:
            r = setup_helper._backup_keep({"days": days})
        except setup_helper.Refused as e:
            output.error(str(e).rstrip(".") + ".")
            return output.USAGE
        _hub_audit(f"backups kept for {r['days']} days")
        output.emit({"ok": True, "days": r["days"]})
        output.result(f"Backups are kept for {r['days']} days.")
        return 0
    if action == "list":
        rows = backup.listing()
        keep = backup.keep_days(config.load())
        output.emit({"backups": [{"name": e.name, "download": e.download, "size": e.size,
                                  "kind": e.kind, "at": _iso(e.at)} for e in rows],
                     "keep_days": keep, "folder": str(backup.backups_dir())})
        if not rows:
            output.out(f"No backups in {backup.backups_dir()} yet.")
            output.out("Back up now: sudo spoolwarden backup create")
            return 0
        output.out(f"Nightly backups are kept {keep} days.")
        output.out()
        output.out_lines(output.table(
            ["Made", "Kind", "Size", "Name"],
            [[time.strftime("%Y-%m-%d %H:%M", time.localtime(e.at)), _BACKUP_KIND.get(e.kind, e.kind),
              f"{e.size // 1024:,} KiB", e.name] for e in rows], long=3, right=(2,), whole=True))   # restore needs the whole name
        output.out()
        output.out(f"Folder: {backup.backups_dir()}")
        return 0
    try:
        with output.wait("Backing up…", programs=True):
            path = backup.create(Path(out) if out else None, step=steps.Steps(3).next)
    except (OSError, backup.BackupError) as e:
        _err_line(f"the backup was not written: {e}")
        return 1
    output.emit({"ok": True, "path": str(path)})
    output.result(f"Backup written: {path}")
    output.note("the zip is not encrypted and holds the setup secrets: store it somewhere safe.")
    return 0


def _restore_out(text: str) -> None:
    """What `backup.restore` says: its `error: ...` lines are errors (standard error), `Restored.` is the done row, the
    rest results."""
    if text.startswith("error: "):
        output.error(text[len("error: "):])
    elif text.startswith("Restored."):
        output.out_lines(output.status_row("done", text))
    else:
        output.out(text)


def cmd_restore(zip_path: str | None, *, uploaded: bool = False, yes: bool = False) -> int:
    from . import backup
    if not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden restore <backup.zip>"))
    if not yes and not output.terminal():           # the typed word cannot be asked: nothing is read or changed
        return output.no_terminal("restoring a backup", _sudo_command("sudo spoolwarden restore <backup.zip>") + " --yes")
    if uploaded:
        try:
            path = backup.take_upload()
        except (OSError, backup.BackupError) as e:
            _err_line(str(e))
            return 1
    else:
        path = Path(zip_path)
        if not path.is_file():
            _err_line(f"{zip_path}: no such file")
            return 1
    try:
        waiting = output.wait("Restoring…", programs=True)
        held: list[str] = []        # --quiet: what is said before the question is its context, shown only if one is asked

        def say(text: str) -> None:
            if output.quiet() and not text.startswith("error: "):
                held.append(text)
            else:
                _restore_out(text)

        def ask(prompt: str) -> str:
            with waiting.paused(), output.shown():      # the wait starts after the answer, never over the question
                for text in held:
                    _restore_out(text)
                held.clear()
                return input(prompt)
        with waiting:
            return backup.restore(path, yes=yes, ask=ask, out=say,
                                  step=steps.Steps(backup.restore_steps()).next)
    finally:
        if uploaded:
            path.unlink(missing_ok=True)


def cmd_station_pairing_state(old_spelling: bool = False) -> int:
    """`weigh-station pairing-state` (06 9.7): `paired with 192.0.2.10:8710`, `not paired` or `not checked yet`; its `--json`
    `state` keeps `paired`, `unpaired`, `unchecked`. The old spelling `station pairing-state` still prints the one line
    the root wrapper passes on to `status` (install/spoolwarden-cli.sh reads that text until it reads the `--json`)."""
    from .station import server_api
    state = server_api.pairing_state()
    word, _, address = state.partition(" ")
    output.emit({"state": word, "address": address or None})
    if old_spelling:
        print(state)
    else:
        print({"paired": f"paired with {address}", "unpaired": "not paired", "unchecked": "not checked yet"}.get(word, state))
    return 0


def _fmt_time(t) -> str:
    if isinstance(t, str):
        return t
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "never"


def _iso(t) -> str | None:
    """A time for `--json`: ISO 8601 with the offset (06 6.8); text is kept as it is; no time is None."""
    if isinstance(t, str):
        return t
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not t:
        return None
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


def _confirm(question: str, doing: str, *, yes: bool, word: str | None = None, ask=None) -> int | None:
    """06 7: None to go on, else the exit code (5 after no, 2 with no terminal and no --yes, which names the command
    again with --yes)."""
    return output.confirm(question, yes=yes, doing=doing, rerun=_sudo_command("sudo spoolwarden <command>") + " --yes",
                          word=word, ask=ask)


def cmd_devices(yes: bool = False, forget: str | None = None) -> int:
    """`devices` (06 9.4): the paired devices, as the Hub page lists them; `devices forget <device>` unpairs one."""
    if forget is not None:
        return _devices_forget(forget, yes)
    from .web.slots import CLI_DEVICE, INTAKE_DEVICE
    devs = pairing.devices()
    built_in = lambda d: d["name"] in (INTAKE_DEVICE, CLI_DEVICE)       # noqa: E731
    reach = station_reach(devs, (config.load().get("station") or {}).get("url"))    # an idle station is not a dead one
    output.emit([{"id": d["id"], "name": d["name"], "type": d.get("type"), "paired": _iso(d["paired"]),
                  "last_seen": _iso(d["last_seen"]), "reachable": reach.get(d["id"]), "built_in": built_in(d)} for d in devs])
    if not devs:
        output.out("Nothing paired yet.")
        output.out("Pair a phone: sudo spoolwarden pair")
        return 0
    word = lambda d: {True: "answering", False: "not answering"}.get(reach.get(d["id"]), "")      # noqa: E731
    seen = lambda d: (_fmt_time(d["last_seen"]) + " (last intake)") if d.get("type") == "station" and d["last_seen"] else _fmt_time(d["last_seen"])      # noqa: E731
    output.out_lines(output.table(
        ["Name", "Type", "Paired", "Last seen", "Status", "ID"],
        [[d["name"], "Weigh Station" if d.get("type") == "station" else "",
          "built in: this Hub's own pairing" if built_in(d) else _fmt_time(d["paired"]),
          "" if built_in(d) else seen(d), word(d), d["id"]] for d in devs], whole=True))     # `forget` takes the id or the name
    return 0


def _device_named(arg: str, rows: list[dict], unclaimed: list[dict]) -> dict | None:
    """06 5: an exact id, else an exact name, else the start of exactly one name; ignoring case. A pairing nobody has
    claimed yet (`unpair <id>` always removed one) is found by its exact id only. None after the error (exit 2)."""
    a = arg.strip().lower()
    hit = [r for r in rows + unclaimed if r["id"].lower() == a] if a else []
    if len(hit) != 1:
        hit = [r for r in rows if r["name"].lower() == a] or [r for r in rows if r["name"].lower().startswith(a)] if a else []
    if len(hit) == 1:
        return hit[0]
    close = [r for r in rows if a and (a in r["name"].lower() or a in r["id"].lower())][:5]
    output.error(f'"{arg}" does not name one device.', "use a name or id from spoolwarden devices." + (
        " Close matches:\n" + "\n".join(f"{r['name']}  {r['id']}" for r in close) if close else ""))
    return None


def _devices_forget(arg: str, yes: bool) -> int:
    from .web.slots import CLI_DEVICE, INTAKE_DEVICE
    rows = pairing.devices()
    unclaimed = [{"id": d["id"], "name": d.get("name") or d["id"]} for d in pairing._read("devices.json")
                 if d.get("claimed") is None and isinstance(d.get("id"), str)]
    dev = _device_named(arg, rows, unclaimed)
    if dev is None:
        return output.USAGE
    name = dev.get("name") or dev["id"]
    if name in (INTAKE_DEVICE, CLI_DEVICE):
        output.error(f"{name} is built in: it is this Hub's own pairing.")
        return output.USAGE
    stop = _confirm(f"Unpair {name}? It can no longer reach the Hub until it is paired again.",
                    f"unpairing {name}", yes=yes)
    if stop is not None:
        return stop
    if pairing.revoke(dev["id"]):
        output.emit({"ok": True, "id": dev["id"], "name": name})
        output.result(f"Unpaired {name}.")
        return 0
    output.error(f'"{arg}" does not name one device.', "use a name or id from spoolwarden devices.")
    return output.USAGE


# ---------- config ----------

def _ask(prompt: str) -> str | None:
    with output.shown():            # a question is seen even where --quiet drops the results
        print(prompt, end="", flush=True)
    line = sys.stdin.readline()
    if line == "":
        return None
    return line.rstrip("\r\n")


def _secret(prompt: str) -> str:
    """`secret_input.ask` inside the menus: the end of input ends the session (exit 5, 06 8.2)."""
    try:
        return secret_input.ask(prompt)
    except EOFError:
        raise _Ended from None


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
    """The Storage locations screen on its own, for the installer's first-run question: the list is written to
    storage.xml when `q` leaves the screen with changes staged (nothing is stored in Spoolman yet, so nothing is renamed)."""
    session = _ConfigMenu(copy.deepcopy(cfg), menu_ui.NumberedUi(_ask, secret_input.ask))
    session.embedded = True
    try:
        session.group("storage")
    except _Ended:
        pass                                  # the input ended: what was staged is still kept
    if "storage" in session.staged:
        try:
            session.storage_editor().save_rows(session.staged["storage"])
        except (storage_api.StorageRefused, storage.StorageError, ValueError, SpoolmanError, OSError) as e:
            output.error(f"the storage locations were not saved: {locations_cli.reason(e).rstrip('.')}.",
                         "change them later with: sudo spoolwarden locations")


# ---------- config: the settings menu (06 8.3) ----------

class _Ended(Exception):
    """The input ended (Ctrl-D, the end of piped input) while a screen waited for an answer."""


class _Sentence(ValueError):
    """An error that is a whole sentence already (the Error: line says it as it is)."""


class _Remove:
    """A staged removal of a secret (the Anthropic key, the Catalog token)."""


_THEMES = (("console", "Console (dense and technical)"), ("workbench", "Workbench (calm cards)"),
           ("palette", "Palette (colourful and roomy)"), ("panes", "Panes (simple lists)"))
_ENGINES = (("auto", "Automatic: On this Hub first, Cloud (Claude) when it is unsure or fails"),
            ("local-then-cloud", "On this Hub, then Cloud (Claude)"),
            ("cloud-then-local", "Cloud (Claude), then On this Hub"),
            ("cloud", "Cloud (Claude) only"), ("local", "On this Hub only"))
_TIERS = (("auto", "Automatic"), ("cpu", "Processor (CPU)"), ("gpu", "Graphics card (GPU)"))
_VOICES = (("auto", "Piper (natural; a 60-80 MB download)"), ("espeak", "espeak-ng (robotic; no download)"))
_SETUP_WORDS = {"server": "Hub", "station": "Weigh Station", "all-in-one": "Hub with Weigh Station", "custom": "Custom"}
# The setup sentence of `features setup` (06 9.6) and the new words for the three setups (N27).
_SETUP_SENTENCE = {"server": "Hub", "station": "Weigh Station only", "all-in-one": "Hub with Weigh Station"}
FEATURES_ROW = 11          # the number the main list gives Features: the texts that point at it say so
_APPLY_KEYS = ("station.tts", "web.public_url", "station.url", "spoolman_url")     # saving these applies (modules apply)


class _Item:
    """One setting of the menu: its label, the kind of answer and the key `config set` knows it by (06 8.3)."""

    def __init__(self, id, label, kind, key, *, choices=(), sep="", low=0, high=0, words="", restarts=False,
                 keep_spaces=False):
        self.id, self.label, self.kind, self.key = id, label, kind, key
        self.choices, self.sep, self.low, self.high, self.words = choices, sep, low, high, words
        self.restarts, self.keep_spaces = restarts, keep_spaces


_ITEMS = {i.id: i for i in (
    _Item("theme", "Theme for new devices", "choice", "appearance.theme", choices=_THEMES),
    _Item("name", "Display name", "text", "server_name"),
    _Item("spoolman", "Spoolman address", "text", "spoolman_url"),
    _Item("storage", "Storage locations", "storage", None),
    _Item("engine", "Engine order", "choice", "intake.reader", choices=_ENGINES),
    _Item("apikey", "Anthropic API key", "secret", "anthropic_key"),
    _Item("model", "Claude model", "text", "model", restarts=True),
    _Item("reads", "Reads per day", "int", "reads_per_day", low=1, high=100000, words="from 1", restarts=True),
    _Item("address", "Address", "text", "local_intake.url"),
    _Item("tier", "Tier", "choice", "local_intake.tier", choices=_TIERS),
    _Item("keep", "Records kept", "int", "intake.history_keep", low=0, high=500, words="0 to 500"),
    _Item("days", "Keep nightly backups for", "int", "backup.keep_days", low=1, high=365, words="1 to 365"),
    _Item("public", "Public address", "text", "web.public_url"),
    _Item("station", "Weigh Station address", "text", "station.url"),
    _Item("hosts", "Names for this page", "list", "setup.hosts", sep=" "),
    _Item("changes", "Allow printer changes from the public address", "bool", "web.printer_changes"),
    _Item("passphrase", "New passphrase", "secret", "web_passphrase"),
    _Item("token", "Catalog token", "secret", "library_token"),
    _Item("voice", "Voice", "choice", "station.tts", choices=_VOICES),
)}

# the groups, in the Hub page's order (03 10.1): id, title
_GROUPS = (("appearance", "Appearance"), ("general", "General"), ("storage", "Storage locations"),
           ("reader", "Label Reader"), ("backups", "Backups and restore"), ("network", "Network and addresses"),
           ("passphrase", "Web passphrase"), ("catalog", "Filament Catalog"), ("voice", "Weigh Station voice"))
_GROUP_ITEMS = {"appearance": ("theme",), "general": ("name", "spoolman"),
                "storage": ("storage",),
                "reader": ("engine", "apikey", "model", "reads", "address", "tier", "keep"),
                "backups": ("days",), "network": ("public", "station", "hosts", "changes"),
                "passphrase": ("passphrase",), "catalog": ("token",), "voice": ("voice",)}


def _lower_first(label: str) -> str:
    """`Display name` -> `display name` for the line after saving; names and acronyms (`PLA rack`) stay."""
    first = label.split(" ")[0]
    return label if first.isupper() or first in ("Spoolman", "Anthropic", "Claude", "Weigh") else label[:1].lower() + label[1:]


def _changes_word(n: int) -> str:
    return f"{n} change{'' if n == 1 else 's'}"


def _general_value(cfg: dict, key: str):
    from . import setup_helper
    if key == "backup.keep_days":
        from . import backup
        return backup.keep_days(cfg)
    return setup_helper.general_value(cfg, key)


def _set_path(cfg: dict, key: str, value) -> None:
    parts = key.split(".")
    cur = cfg
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


class _ConfigMenu:
    """`config`: the Hub's settings, changed in a list of groups, collected, then saved together with `s` (06 8.3)."""

    def __init__(self, cfg: dict, ui):
        self.cfg = cfg                        # the settings as stored when the menu opened (or were last saved)
        self.ui = ui
        self.staged: dict[str, object] = {}   # item id -> the checked value, in the order it was changed
        self.rc = 0
        self.embedded = False                 # the Storage group alone, for the installer: no `s`, nothing is written
        self.final: list[str] = []            # said after the screen is gone
        self.sm_factory = None                # Spoolman for how full the storage locations are and for renames
        self._storage = None                  # the Storage locations screens (locations_cli.StorageEditor), made when opened

    # ----- values
    def stored(self, it: _Item, cfg: dict | None = None):
        if it.kind == "storage":
            return self.storage_editor().base
        return _general_value(self.cfg if cfg is None else cfg, it.key)

    def storage_editor(self) -> "locations_cli.StorageEditor":
        if self._storage is None:
            self._storage = locations_cli.StorageEditor(self, self.sm_factory)
        return self._storage

    def ended(self) -> Exception:
        return _Ended()

    def value(self, it: _Item):
        return self.staged[it.id] if it.id in self.staged else self.stored(it)

    def show(self, it: _Item, value) -> str:
        if it.kind == "secret":
            return "will be removed" if value is _Remove else "new value, not saved yet" if value else ""
        if it.kind == "choice":
            return dict(it.choices).get(value, str(value))
        if it.kind == "bool":
            return "on" if value else "off"
        if it.kind == "list":
            return (", " if it.sep == "," else " ").join(value or [])
        if value is None or value == "":
            return "not set" if it.id in ("public", "station", "spoolman", "hosts") else ""
        if it.keep_spaces and (str(value) != str(value).strip()):
            return f'"{value}"'
        return str(value)

    def row_value(self, it: _Item) -> str:
        if it.kind == "secret":
            gone = self.staged.get(it.id) is _Remove
            text = "set" if self.is_set(it) else "not set"
            return text + ("  (will be removed)" if gone else "  (not saved)" if it.id in self.staged else "")
        v = self.value(it)
        text = self.show(it, v)
        if it.id in self.staged and it.kind != "secret":
            text += "  (not saved" + ("; restarts the Hub" if it.restarts else "") + ")"
        return text

    # ----- checking an answer
    def check(self, it: _Item, raw: str):
        """The checked value of the typed `raw`; ValueError with the sentence to print (no `Error:`)."""
        from . import local_reader, setup_helper
        label = _lower_first(it.label)
        text = raw if it.keep_spaces else raw.strip()
        try:
            if it.id == "spoolman":
                if modules.check_setting("spoolman_url", text):
                    raise _Sentence("give the address of the Spoolman to use, on another machine, e.g. "
                                    "http://spoolman.example:7912.")
                return text.rstrip("/")
            if it.id == "public":
                if modules.check_setting("web.public_url", text):
                    raise _Sentence("the public address must start with https://, e.g. https://hub.example/filament.")
                return text.rstrip("/")
            if it.id == "station":
                if text == "-":
                    return None
                if setup_helper.station_url_error(text):
                    raise _Sentence("give the Weigh Station's address, e.g. http://station.local:5003.")
                return text.rstrip("/")
            if it.id == "address":
                err = local_reader.check_url(text)
                if err:
                    raise _Sentence(f"the {label} is not usable: {err.rstrip('.')}.")
            if it.kind == "int":
                return _check_general(it, int(text))
            if it.kind == "list":
                split = text.replace(",", " ").split() if it.sep == " " else text.split(",")
                return _check_general(it, [x.strip() for x in split if x.strip()])
            return _check_general(it, text)
        except _Sentence:
            raise
        except ValueError as e:
            if it.kind == "int":
                raise _Sentence(f"the {label} is a whole number, {it.words}.") from None
            raise _Sentence(f"the {label} {str(e).rstrip('.')}.") from None

    # ----- one item
    def edit(self, it: _Item) -> None:
        ui = self.ui
        if it.kind == "secret":
            return self.edit_secret(it)
        if it.kind == "bool":
            new = not bool(self.value(it))
            self.stage(it, new)
            return
        if it.kind == "choice":
            return self.edit_choice(it)
        current = self.value(it)
        shown = self.show(it, current)
        while True:
            raw = ui.ask(f"{it.label} [{shown}]: ")
            if raw is None:
                raise _Ended
            if raw == "" or (not it.keep_spaces and not raw.strip()):
                ui.say("Unchanged.")
                return
            try:
                value = self.check(it, raw)
            except ValueError as e:
                ui.error(str(e))
                continue
            self.stage(it, value)
            return

    def stage(self, it: _Item, value) -> None:
        """Keep `value` for the next save, or drop the change when it is what is stored."""
        if value == self.stored(it):
            self.staged.pop(it.id, None)
            self.ui.say("Unchanged.")
        elif it.id in self.staged and self.staged[it.id] == value:
            self.ui.say("Unchanged.")
        else:
            self.staged[it.id] = value
            self.ui.say("Changed, not saved yet.")

    def edit_choice(self, it: _Item) -> None:
        now = self.value(it)
        rows = [menu_ui.Row(words + ("  (now)" if value == now else "")) for value, words in it.choices]
        sc = menu_ui.Screen(f"choice-{it.id}", it.label, rows, leave="back", empty_leaves=True,
                            prompt="Number (Enter keeps it): ")
        ev = self.ui.choose(sc, True)
        if ev[0] == "eof":
            raise _Ended
        if ev[0] == "open":
            self.stage(it, it.choices[ev[1]][0])
        else:
            self.ui.say("Unchanged.")

    def edit_secret(self, it: _Item) -> None:
        ui = self.ui
        if it.id == "passphrase":
            return self.edit_passphrase(it)
        while True:
            raw = ui.ask(f"{it.label} (Enter keeps it): ", secret=True)
            if raw is None:
                raise _Ended
            raw = raw.strip()
            if not raw:
                ui.say("Unchanged.")
                return
            if it.id == "token" and (" " in raw or not raw.isprintable() or len(raw) > 400):
                ui.error("a GitHub token is one word of printable characters.")
                continue
            self.staged[it.id] = raw
            ui.say("Changed, not saved yet.")
            return

    def edit_passphrase(self, it: _Item) -> None:
        ui = self.ui
        while True:
            first = ui.ask("New passphrase (Enter keeps it): ", secret=True)
            if first is None:
                raise _Ended
            if not first:
                ui.say("Unchanged.")
                return
            try:
                from .web import auth
                if len(first) < auth.MIN_PASSPHRASE:
                    ui.error(f"use at least {auth.MIN_PASSPHRASE} characters. This one has {len(first)}.")
                    continue
            except ImportError:
                pass            # without the web extra the save says so
            second = ui.ask("New passphrase again: ", secret=True)
            if second is None:
                raise _Ended
            if first != second:
                ui.error("the two passphrases do not match. Type them again.")
                continue
            self.staged[it.id] = first
            ui.say("Changed, not saved yet.")
            return

    # ----- screens
    def labels(self) -> str:
        return ", ".join(_ITEMS[i].label for i in self.staged)

    def title(self) -> str:
        return f"Settings{output.sym('sep')}{self.cfg.get('server_name', '')}"

    def features_on(self) -> frozenset[str]:
        return modules.enabled(self.cfg)

    def summary(self, gid: str) -> tuple[str, bool]:
        """The main list's value for a group, and whether it is dim (off)."""
        on, sep, cfg = self.features_on(), output.sym("sep"), self.cfg
        it = _ITEMS
        if gid == "appearance":
            return f"Theme for new devices: {self.show(it['theme'], self.value(it['theme'])).split(' (')[0]}", False
        if gid == "general":
            return str(self.value(it["name"])), False
        if gid == "storage":
            return locations_cli.summary(self.storage_editor().rows), False
        if gid == "reader":
            from . import intake
            order = intake.reader_order(cfg)
            if not order:
                return "off: only Records kept", True
            names = {"local": "On this Hub", "cloud": "Cloud (Claude)"}
            text = " then ".join(names[r] for r in order)
            if "cloud" in order:
                text += f"{sep}{self.value(it['reads'])} reads a day{sep}key {'set' if self.key_set() else 'not set'}"
            return text, False
        if gid == "backups":
            return f"Nightly backups kept {self.value(it['days'])} days", False
        if gid == "network":
            url = self.value(it["public"])
            return (f"Public address {url}" if url else "Public address not set"), False
        if gid == "passphrase":
            return ("set" if self.passphrase_set() else "not set"), False
        if gid == "catalog":
            if "library" not in on:
                return "off: only Catalog token", True
            return f"Catalog token {'set' if self.token_set() else 'not set'}", False
        if "station" not in on:
            return f"off: switch it on in Features ({FEATURES_ROW})", True
        return {"auto": "Piper (natural)", "espeak": "espeak-ng (robotic)"}.get(self.value(it["voice"]), ""), False

    def is_set(self, it: _Item) -> bool:
        return {"apikey": self.key_set, "token": self.token_set, "passphrase": self.passphrase_set}[it.id]()

    def key_set(self) -> bool:
        if "apikey" in self.staged:
            return self.staged["apikey"] is not _Remove
        try:
            return bool((config.paths().etc / KEY_FILE).read_text(encoding="utf-8").strip())
        except OSError:
            return False

    def token_set(self) -> bool:
        if "token" in self.staged:
            return self.staged["token"] is not _Remove
        return library._token() is not None

    def passphrase_set(self) -> bool:
        return "passphrase" in self.staged or (config.paths().etc / WEB_PASSPHRASE).exists()

    def main_screen(self) -> menu_ui.Screen:
        rows = []
        for gid, title in _GROUPS:
            text, dim = self.summary(gid)
            rows.append(menu_ui.Row(title, text, dim=dim, note=_group_note(gid)))
        printers = list(registry.load().values())
        found = sum(1 for p in printers if not p.configured)
        rows.append(menu_ui.Row("Printers", f"{len(printers) - found} set up{output.sym('sep')}{found} found",
                                before=("These open their own screens; changes there apply at once:",),
                                note="Opens the Printers screen."))
        rows.append(menu_ui.Row("Features", _SETUP_WORDS[modules.mode_of(self.features_on())],
                                note="Opens the Features checklist."))
        return menu_ui.Screen("config", self.title(), rows, save="save", changes=len(self.staged))

    def group_screen(self, gid: str) -> tuple[menu_ui.Screen, list[str | None]]:
        """The screen of one group and, row by row, the item it opens (None: a row that cannot be opened)."""
        title = dict(_GROUPS)[gid]
        on, rows, targets, after, actions = self.features_on(), [], [], [], []
        cloud, local = "ai_intake" in on, "local_intake" in on

        def add(iid: str, before: tuple[str, ...] = (), extra: str = "") -> None:
            it = _ITEMS[iid]
            rows.append(menu_ui.Row(it.label, self.row_value(it) + extra, before=before, note=_item_note(it)))
            targets.append(iid)

        if gid == "reader":
            if cloud and local:
                add("engine")
            elif cloud or local:
                one = "Cloud (Claude)" if cloud else "On this Hub"
                rows.append(menu_ui.Row("Engine order", f"Engine: {one}. Switch on the other one in Features "
                                        f"({FEATURES_ROW}) to use both.", dim=True))
                targets.append(None)
            if cloud:
                add("apikey", ("Cloud (Claude)",))
                add("model")
                add("reads")
                actions += [("c", "check the key"), ("x", "remove the key")]
            if local:
                add("address", ("On this Hub",))
                add("tier")
            use = _history_use()
            add("keep", ("Recently added",), f"  Now {use['count']} record{'' if use['count'] == 1 else 's'}, "
                f"{use['photo_bytes'] / 1e6:.1f} MB of photos")
        else:
            for iid in _GROUP_ITEMS[gid]:
                if iid == "spoolman" and not ("server" in on and "spoolman" not in on):
                    continue
                if iid == "changes" and "web" not in on:
                    continue
                add(iid)
                if iid == "token":
                    actions.append(("x", "remove the token"))
        if gid == "backups":
            after = ["Back up now: sudo spoolwarden backup create", "Restore: sudo spoolwarden restore <zip>"]
        elif gid == "catalog":
            after = ["Update now: sudo spoolwarden catalog update"]
        elif gid == "network":
            after = ["Firewall rules: spoolwarden remote firewall"]
        sc = menu_ui.Screen(f"group-{gid}", f"Settings > {title}", rows, actions=tuple(actions),
                            save="" if self.embedded else "save", leave="back", changes=len(self.staged),
                            after=tuple(after))
        return sc, targets

    # ----- running
    def run(self) -> int:
        ui, show = self.ui, True
        while True:
            ev = ui.choose(self.main_screen(), show)
            show = False
            if ev[0] == "eof":
                raise _Ended
            if ev[0] == "save":
                self.save()
            elif ev[0] == "leave":
                if self.leave():
                    return self.rc or (5 if self.staged else 0)
            elif ev[0] == "open":
                i = ev[1]
                if i < len(_GROUPS):
                    self.group(_GROUPS[i][0])
                elif i == len(_GROUPS):
                    _printers_screen(ui)
                else:
                    self.features()
                show = True

    def leave(self) -> bool:
        """`q` at the top: True to end (nothing staged, or the person said yes to losing it)."""
        if not self.staged:
            return True
        n = len(self.staged)
        yes = self.ui.yesno(f"Leave without saving {_changes_word(n)} ({self.labels()})?")
        if yes is None:
            raise _Ended
        if yes:
            self.final.append("Nothing saved.")
        return bool(yes)

    def group(self, gid: str) -> None:
        ui, on = self.ui, self.features_on()
        if gid == "voice" and "station" not in on:
            ui.say(f"Weigh Station is off on this Hub. Switch it on in Features ({FEATURES_ROW}) first.")
            return
        if gid == "reader" and not ({"ai_intake", "local_intake"} & on):
            ui.say(f"The Label Reader is switched off. Spools are then added by hand. Switch it on in Features "
                   f"({FEATURES_ROW}).")
        if gid == "catalog" and "library" not in on:
            ui.say(f"The Filament Catalog is switched off. Switch it on in Features ({FEATURES_ROW}).")
        if gid == "storage":
            return self.storage_editor().run()
        show = True
        while True:
            on = self.features_on()
            sc, targets = self.group_screen(gid)
            if gid == "reader" and not ({"ai_intake", "local_intake"} & on):
                sc.rows, targets = sc.rows[-1:], targets[-1:]
            if gid == "catalog" and "library" not in on:
                sc.rows, targets = sc.rows[:1], targets[:1]
                sc.after = ()
            ev = ui.choose(sc, show)
            show = False
            if ev[0] == "eof":
                raise _Ended
            if ev[0] == "leave":
                return
            if ev[0] == "save":
                self.save()
            elif ev[0] == "action":
                self.action(gid, ev[1])
            elif ev[0] == "open":
                iid = targets[ev[1]]
                if iid is None:
                    ui.say(sc.rows[ev[1]].value)
                    continue
                self.edit(_ITEMS[iid])

    def action(self, gid: str, letter: str) -> None:
        ui = self.ui
        if letter == "c":
            ui.say("Checking the key…")
            ok, text = check_key()
            ui.say(text if ok else f"{text}.")
        elif letter == "x" and gid == "reader":
            if not self.key_set():
                ui.say("No key is set.")
                return
            yes = ui.yesno("Remove the Anthropic API key? Label Reader: Cloud (Claude) stops reading labels until a "
                           "new key is set.")
            if yes is None:
                raise _Ended
            if yes:
                self.staged["apikey"] = _Remove
                ui.say("Changed, not saved yet.")
        elif letter == "x" and gid == "catalog":
            if not self.token_set():
                ui.say("No token is set.")
                return
            yes = ui.yesno("Remove the Catalog token? The Filament Catalog can then download only from public sources.")
            if yes is None:
                raise _Ended
            if yes:
                self.staged["token"] = _Remove
                ui.say("Changed, not saved yet.")

    def features(self) -> None:
        state, rc = _features_screen(self.ui, self.cfg, fresh=True)
        self.cfg = config.load()
        self.rc = self.rc or rc
        if state == "discarded":
            self.ui.say("Nothing applied.")

    # ----- saving
    def save(self) -> None:
        """Every staged change at once, all or nothing (06 8.3). The Hub's rules: each value checked first, the
        settings written together, one restart and one apply for the group."""
        ui = self.ui
        if not self.staged:
            ui.say("Nothing to save.")
            return
        now = config.load()
        for iid in list(self.staged):
            it = _ITEMS[iid]
            if it.kind in ("secret", "storage"):
                continue
            mine, theirs = self.stored(it), self.stored(it, now)
            if theirs != mine and theirs != self.staged[iid]:
                yes = ui.yesno(f'{it.label} was changed elsewhere to "{self.show(it, theirs)}" while this menu was '
                               "open. Keep yours?")
                if yes is None:
                    raise _Ended
                if not yes:
                    del self.staged[iid]
        self.cfg = now
        if not self.staged:
            ui.say("Nothing to save.")
            return
        new = copy.deepcopy(now)
        err = self.build(new)
        if err:
            ui.error(f"nothing was saved: {err.rstrip('.')}. Your changes are still here.")
            return
        saved = [_lower_first(_ITEMS[i].label) for i in self.staged]
        restarts = any(_ITEMS[i].restarts for i in self.staged)
        applies = any(_ITEMS[i].key in _APPLY_KEYS for i in self.staged)
        renamed = ""
        if "storage" in self.staged:        # first: it is the part that can need Spoolman and take a while
            try:
                renamed = self.storage_editor().save_rows(self.staged["storage"]).get("text", "")
            except (storage_api.StorageRefused, storage.StorageError, ValueError, SpoolmanError, OSError) as e:
                ui.error(f"nothing was saved: {locations_cli.reason(e).rstrip('.')}. Your changes are still here.")
                return
            del self.staged["storage"]
        try:
            config.save(new)
        except (GroupMissing, ValueError, library.LibraryError, OSError) as e:
            ui.error(f"nothing was saved: {str(e).rstrip('.')}. Your changes are still here.")
            return
        done: list[str] = []
        try:
            self.write_secrets(done)
        except (GroupMissing, ValueError, library.LibraryError, OSError) as e:
            config.save(now)                  # the settings go back: one save or none
            kept = f" ({', '.join(_ITEMS[i].label for i in done)} had already been written)" if done else ""
            ui.error(f"not everything was saved: {str(e).rstrip('.')}. The settings are as before{kept}. Your changes "
                     "are still here.")
            return
        self.cfg, self.staged = new, {}
        ui.say(f"Saved {_changes_word(len(saved))}: {', '.join(saved)}.")
        if renamed:
            ui.say(renamed)
        if applies or restarts:
            with ui.suspended():
                if applies:
                    self.rc = self.rc or _run_apply(pairing=False)
                if restarts and not _no_systemd():
                    output.out(f"{output.glyph('working')} The Hub is restarting{output.sym('ellipsis')}".strip())
                    _restart_service()
                    output.out("The Hub is back.")

    def build(self, new: dict) -> str | None:
        """Put the staged settings into `new`; the sentence saying what is wrong, or None."""
        for iid, value in self.staged.items():
            it = _ITEMS[iid]
            if it.kind in ("secret", "storage"):
                continue
            if it.key == "backup.keep_days":
                new.setdefault("backup", {})["keep_days"] = value
            elif it.key == "station.url":
                _set_path(new, it.key, value)
            else:
                _set_path(new, it.key, value)
        if "spoolman" in self.staged:
            try:
                Spoolman(self.staged["spoolman"], timeout=5).ping()
            except (SpoolmanError, OSError, ValueError) as e:
                return f"no Spoolman answered at that address ({e})"
        if any(i in self.staged for i in ("public", "station", "spoolman")):
            try:
                modules.validate(new)
            except modules.ModuleError as e:
                return str(e)
        if any(_ITEMS[i].key in _APPLY_KEYS for i in self.staged):
            err = _plan_error(new)
            if err:
                return err
        return None

    def write_secrets(self, done: list[str]) -> None:
        """Written after the settings are saved; `done` collects the ids written so far (what a failure leaves)."""
        s = self.staged
        if "passphrase" in s:
            write_passphrase(s["passphrase"])
            done.append("passphrase")
        if "apikey" in s:
            if s["apikey"] is _Remove:
                remove_key()
            else:
                write_key(s["apikey"])
            done.append("apikey")
        if "token" in s:
            if s["token"] is _Remove:
                library.remove_token()
            else:
                library.write_token(s["token"])
            done.append("token")


def _check_general(it: _Item, raw):
    """The Hub's check of `raw` for this item's key (setup_helper.GENERAL), or the item's own rule."""
    from . import setup_helper
    if it.key in setup_helper.GENERAL:
        return setup_helper.GENERAL[it.key][0](raw)
    if it.key == "backup.keep_days":
        return setup_helper._whole(raw, 1, 365)
    return raw


def _item_note(it: _Item) -> str:
    return {"text": "Enter to type a new value; an empty answer keeps it.",
            "int": f"A whole number, {it.words}. Enter to change it.",
            "list": "Separate the entries with " + ("commas." if it.sep == "," else "spaces."),
            "choice": "Enter to choose.", "bool": "Enter switches it on or off.",
            "secret": "Typed hidden. It is never shown back."}[it.kind]


def _group_note(gid: str) -> str:
    return {"appearance": "How new devices look.", "general": "The Hub's name and its Spoolman.",
            "storage": "Where spools are put away.", "reader": "Reads a spool's label from a photo.",
            "backups": "One zip with everything the kit keeps.", "network": "How the Hub is reached.",
            "passphrase": "Approves Claude's connector on the web access page.",
            "catalog": "Known filaments and their settings.", "voice": "The voice the Weigh Station speaks with."}[gid]


def _history_use() -> dict:
    from . import intake_history
    try:
        d = intake_history.list_records(False)
        return {"count": d["count"], "photo_bytes": d["photo_bytes"]}
    except Exception:  # noqa: BLE001 - a line beside a setting
        return {"count": 0, "photo_bytes": 0}


def cmd_config(sm_factory=None) -> int:
    """`config`: the settings menu (06 8.3). A menu needs a terminal, or `--numbered` with its answers on standard input."""
    if not output.numbered() and not menu_ui._stdin_tty():
        output.error("config is a menu, and there is no terminal to ask on.",
                     "run it again with --numbered, giving the answers on standard input.")
        return output.USAGE
    if not _no_systemd() and hasattr(os, "geteuid") and os.geteuid() != 0:
        return output.need_sudo(_sudo_command("sudo spoolwarden config"))
    session = None
    try:
        with menu_ui.open_ui(_ask, secret_input.ask) as ui:
            session = _ConfigMenu(config.load(), ui)
            session.sm_factory = sm_factory
            try:
                rc = session.run()
            except _Ended:
                n = len(session.staged)
                if n:
                    session.final.append(f"Input ended: {_changes_word(n)} not saved.")
                rc = 5 if n else 0
    except KeyboardInterrupt:
        n = len(session.staged) if session else 0
        if n:
            output.out(f"Left without saving {_changes_word(n)}.")
        return output.INTERRUPTED
    for line in session.final:
        output.out(line)
    return rc

# ---------- config show and config set (06 9.8) ----------

_KEY_ALIASES = {"backups.keep_days": "backup.keep_days"}      # 06 8.3 writes the key this way; the file holds backup.keep_days
_SECRET_WHERE = {"apikey": "Label Reader", "passphrase": "Web passphrase", "token": "Filament Catalog"}


def _menu_items(cfg: dict) -> list[tuple[str, list[_Item]]]:
    """The groups of the menu with the items it shows now, in its order (what `config show` prints)."""
    on = modules.enabled(cfg)
    out = []
    for gid, title in _GROUPS:
        items = []
        for iid in _GROUP_ITEMS[gid]:
            if iid == "spoolman" and not ("server" in on and "spoolman" not in on):
                continue
            if iid == "changes" and "web" not in on:
                continue
            if gid == "reader" and iid in ("apikey", "model", "reads") and "ai_intake" not in on:
                continue
            if gid == "reader" and iid in ("address", "tier") and "local_intake" not in on:
                continue
            if gid == "reader" and iid == "engine" and not ("ai_intake" in on and "local_intake" in on):
                continue
            items.append(_ITEMS[iid])
        if gid == "voice" and "station" not in on:
            continue
        if items:
            out.append((title, items))
    return out


def cmd_config_show(sm_factory=None) -> int:
    """`config show`: every setting in the menu's order, a heading per group, secrets as set / not set."""
    cfg = config.load()
    menu = _ConfigMenu(cfg, None)
    groups = _menu_items(cfg)
    label_width = max(len(it.label) for _, items in groups for it in items)
    from .setup_console import general_tab
    # the Hub's own values (GENERAL's keys, null where nothing is stored, the theme as config.look reads it), then the
    # menu's keys the Hub keeps elsewhere (backups, addresses)
    doc, lines = {"values": dict(general_tab._view()["values"]), "secrets": {}, "groups": []}, []
    for title, items in groups:
        lines.append(output.paint(title, "bold", sys.stdout))
        rows = []
        for it in items:
            if it.kind == "storage":
                lines += _storage_show_lines(rows, sm_factory)
                continue
            if it.kind == "secret":
                is_set = menu.is_set(it)
                doc["secrets"][it.key] = {"set": is_set}
                shown = "set" if is_set else "not set"
            else:
                value = doc["values"].setdefault(it.key, menu.stored(it))
                text = value
                if it.id == "keep" and value is None:       # the number the Hub keeps when none is set
                    from . import intake_history
                    text = intake_history.keep(cfg)
                shown = (menu.show(it, text).split(" (")[0] if it.kind == "choice" else menu.show(it, text)) or "not set"
            rows.append({"label": it.label, "key": it.key, "value": {"set": is_set} if it.kind == "secret" else value})
            gap = " " * (label_width - len(it.label) + 2)
            lines += output.wrap(f"{it.label}{gap}{shown}", indent=2 + label_width + 2, first=2)
        doc["groups"].append({"group": title, "items": rows})
    output.emit(doc)
    output.out_lines(lines)
    return 0


def _storage_show_lines(rows: list, sm_factory) -> list[str]:
    """`config show` for Storage locations: the list as the menu shows it (numbered, in fill order); its document
    holds the locations of `GET api/storage`."""
    try:
        view = storage_api.current_view((sm_factory or locations_cli.default_spoolman)())
    except (SpoolmanError, OSError, KeyError):          # without Spoolman the list is still shown, with nothing used
        view = storage_api.view(storage.current(), {})
    rows.append({"label": "Locations", "key": None, "value": view["locations"]})
    width = max(len(r["name"]) for r in view["locations"])
    return [f"  {r['position']:>2}  {r['name']:<{width}}  {locations_cli.row_line(r, view['locations'])}"
            for r in view["locations"]]


# the keys of the five storage settings (and the list of locations) before the list: `config set` refuses them (06 8.3)
_OLD_STORAGE_KEYS = ("locations", "placement.pla_location", "placement.box_prefix", "placement.box_count",
                     "placement.overflow", "placement.sealed_location")


def _set_keys() -> list[str]:
    return [it.key for it in _ITEMS.values() if it.kind not in ("secret", "storage") and it.id != "spoolman"]


def _config_set_value(it: _Item, raw: str):
    """The checked value of `raw` for `config set` (the menu's checks), or raises _Sentence with what is wrong."""
    session = _ConfigMenu({}, None)
    if it.kind == "choice":
        word = raw.strip().lower()
        by_name = {words.split(" (")[0].split(":")[0].lower(): value for value, words in it.choices}
        value = word if word in dict(it.choices) else by_name.get(word)
        if value is None:
            raise _Sentence(f"{raw!r} is not a choice for {_lower_first(it.label)}.")
        return value
    if it.kind == "bool":
        word = raw.strip().lower()
        if word in ("on", "true", "yes", "1"):
            return True
        if word in ("off", "false", "no", "0"):
            return False
        raise _Sentence(f"the {_lower_first(it.label)} is on or off.")
    return session.check(it, raw)


def cmd_config_set(key: str, raw: str) -> int:
    """`config set <key> <value>`: one setting, checked as the menu checks it and saved the way `s` saves."""
    key = _KEY_ALIASES.get(key, key)
    if key in _OLD_STORAGE_KEYS:
        output.error("storage locations are a list now.", "spoolwarden locations")
        return output.USAGE
    item = next((it for it in _ITEMS.values() if it.key == key), None)
    keys = ", ".join(k for k in ("backups.keep_days" if k == "backup.keep_days" else k for k in _set_keys()))
    if item is not None and item.kind == "secret":
        output.error(f"the {_lower_first(item.label)} is a secret.", f"sudo spoolwarden config, {_SECRET_WHERE[item.id]}.")
        return output.USAGE
    if item is not None and item.id == "spoolman" or key == "spoolman_url":
        output.error("the Spoolman address is not set this way.", "check and save it with:",
                     cmd="sudo spoolwarden spoolman address <url>")
        return output.USAGE
    if item is None:
        output.error(f'there is no setting called "{key}".', f"the keys are {keys}.")
        return output.USAGE
    if not _no_systemd() and not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden config set " + shlex.join([key, raw])))
    try:
        value = _config_set_value(item, raw)
    except _Sentence as e:
        output.error(str(e))
        return output.USAGE
    except ValueError as e:
        output.error(str(e))
        return output.USAGE
    if item.id == "station" and "station" not in modules.enabled(config.load()):
        output.error('the "Weigh Station" Feature is off.', "turn it on first:", cmd="sudo spoolwarden features on weigh-station")
        return output.FAILED
    session = _ConfigMenu(config.load(), None)
    shown = session.show(item, value).split(' (')[0] if item.kind == 'choice' else session.show(item, value)
    sentence = f"Nightly backups are kept for {shown} days." if item.id == "days" else f"{item.label} is {shown}."
    if value == session.stored(item):
        output.emit({"ok": True, "key": item.key, "changed": False})
        output.result(f"Unchanged: {sentence}")
        return 0
    session.staged[item.id] = value
    new = copy.deepcopy(session.cfg)
    err = session.build(new)
    if err:
        output.error(f"nothing was saved: {err.rstrip('.')}.")
        return 1
    try:
        config.save(new)
    except (GroupMissing, ValueError, library.LibraryError, OSError) as e:
        output.error(f"nothing was saved: {str(e).rstrip('.')}.")
        return 1
    _hub_audit(f"setting {item.key} changed")
    output.emit({"ok": True, "key": item.key, "changed": True, "restarts": item.restarts,
                 "applies": item.key in _APPLY_KEYS})
    output.result(f"Saved: {sentence}")
    if item.key in _APPLY_KEYS:
        rc = _run_apply(pairing=False)
        if rc:
            return rc
    if item.restarts and not _no_systemd():
        with output.wait("The Hub is restarting…", programs=True):
            _restart_service()
        output.result("The Hub is back.")
    return 0


_THEME_WORDS = {"console": "dense and technical; the default", "workbench": "calm cards",
                "palette": "colourful and roomy", "panes": "simple lists"}


def cmd_config_theme(raw: str | None) -> int:
    """`config theme [<theme>]` (06 9.8): the Hub's theme for new devices, shown (no rights needed) or set (root, as
    `config set` needs). The name in any case; a device that chose its own theme keeps it."""
    def line(value: str) -> str:
        return f"Theme for new devices: {value.capitalize()} ({_THEME_WORDS[value]})."
    if raw is None:
        value = config.look(config.load())
        output.emit({"theme": value})
        output.result(line(value))
        return 0
    value = raw.strip().lower()
    if value not in _THEME_WORDS:
        output.error(f'there is no theme called "{raw.strip()}".',
                     "choose console, workbench, palette or panes. Light and dark are chosen on each device, in Settings > Appearance.")
        return output.USAGE
    if not _no_systemd() and not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden config theme " + shlex.join([value])))
    session = _ConfigMenu(config.load(), None)
    if value == config.look(session.cfg):
        output.emit({"ok": True, "key": "appearance.theme", "changed": False})
        output.result("Unchanged: " + line(value))
        return 0
    session.staged["theme"] = value
    new = copy.deepcopy(session.cfg)
    err = session.build(new)
    if err:
        output.error(f"nothing was saved: {err.rstrip('.')}.")
        return 1
    try:
        config.save(new)
    except (GroupMissing, ValueError, library.LibraryError, OSError) as e:
        output.error(f"nothing was saved: {str(e).rstrip('.')}.")
        return 1
    _hub_audit("setting appearance.theme changed")
    output.emit({"ok": True, "key": "appearance.theme", "changed": True, "restarts": False, "applies": False})
    output.result(line(value))
    output.result("Devices that already chose a theme keep theirs.")
    return 0


# ---------- logs and the pointer commands (06 9.14, 10) ----------

def cmd_logs(service: str | None, lines: int = 100) -> int:
    """`logs [<service>] [--lines 50|100|200]` (06 9.14): the end of a service's journal, as the Hub page's Logs tab reads
    it (setup_helper's journal op), whole: addresses and serials are not hidden here."""
    from . import setup_helper
    if not _no_systemd() and not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden logs" + (f" {service}" if service else "")))
    units = setup_helper.journal_units(config.load())
    unit = None
    if service is None:
        unit = "filament-kit.service" if "filament-kit.service" in units else None
    else:
        word = service.strip().lower()
        hits = [u for u in units if u.lower() in (word, word + ".service")]
        hits = hits or [u for u in units if u.lower().startswith(word)]
        unit = hits[0] if len(hits) == 1 else None
    if unit is None:
        which = f'"{service}" is not one of the services the switched-on features run.' if service             else "the Hub's service does not run here."
        output.error(which,
                     "name one of: " + (", ".join(u.removesuffix(".service") for u in units) or "none is running here")
                     + ".")
        return output.USAGE
    try:
        r = setup_helper._journal({"unit": unit, "lines": lines})
    except setup_helper.Refused as e:
        output.error(str(e).rstrip(".") + ".")
        return output.FAILED
    _hub_audit(f"log of {r['unit']} read")
    output.emit({"unit": r["unit"], "text": r["text"], "truncated": r["truncated"]})
    shown = r["text"].splitlines()
    if not shown:
        output.out("Nothing logged.")
        return 0
    output.out_lines(shown)
    if r["truncated"] or len(shown) >= lines:
        output.out(f"Only the last {lines} lines are shown.")
        output.out(f"Fix: for more, run journalctl -u {r['unit'].removesuffix('.service')}")
    return 0


def _intake_url() -> str:
    """The web app's address on this Hub, for the lines that say where something is (06 10)."""
    ips = pairing.local_ips()
    host = ips[0] if ips else f"{pairing.short_hostname()}.local"
    return f"https://{host}:{int(config.load().get('port', 8710))}/intake"


def _pointer(where: str, sentence: str, url: str) -> int:
    """06 10: one line saying where a thing the command line cannot do is, the address on the next line when the two do
    not fit together; exit 0. `--json`: {"available": false, "where", "url"}."""
    output.emit({"available": False, "where": where, "url": url})
    if len(sentence) + 1 + len(url) <= output.width() - 1:
        output.out_lines([f"{sentence} {url}"])
    else:
        output.out_lines([sentence, url])
    return 0


def cmd_add() -> int:
    return _pointer("web app", "Add spools in the web app, app or Weigh Station:", _intake_url())


def cmd_spool() -> int:
    return _pointer("web app", "Spools are opened and tagged in the web app or app:", _intake_url())


# ---------- the Printers screen (06 8.4) ----------

_BAMBU_KEYS = (("c", "collect a report"), ("t", "test connection"), ("m", "map slots"),
               ("b", "map by loading filament"), ("v", "saved reports"), ("r", "rename"), ("e", "change address"),
               ("k", "replace Access Code"), ("u", "forget certificate"), ("f", "forget printer"))
_KLIPPER_KEYS = (("t", "test connection"), ("d", "detect model and slots"), ("b", "map by loading filament"),
                 ("r", "rename"), ("e", "change address"), ("k", "set or replace Moonraker API key"),
                 ("n", "lane data"), ("x", "clear API key"), ("f", "forget printer"))
_FOUND_KEYS = (("u", "use this printer"), ("t", "test connection"), ("f", "dismiss"))
ACCESS_WHERE = "(on the printer: Settings > Network/LAN)"


def _printer_states() -> dict:
    """serial -> the running Hub's word for each printer's connection (empty when the Hub does not answer)."""
    api = _server_api()
    if api is None:
        return {}
    try:
        return {p["id"]: p.get("state") for p in api.get("/api/printers").get("printers", [])}
    except Exception:  # noqa: BLE001 - a word beside a row: the list is useful without it
        return {}


def _printer_state_word(p, states: dict) -> str:
    if not p.configured:
        return "found, not added"
    st = states.get(p.serial)
    return "" if st is None else "connected" if st == "connected" else "offline"


def _printer_address(p) -> str:
    return f"{p.host}:{p.port}" if p.family == "klipper" else p.ip


def _printers_screen(ui) -> None:
    """The list of printers: a number opens one, `a` adds, `l` reads the list again."""
    sep, show = output.sym("sep"), True
    while True:
        try:
            printers = list(registry.load().values())
        except registry.RegistryError as e:
            ui.error(str(e))
            return
        states = _printer_states()
        rows = []
        for p in printers:
            word = _printer_state_word(p, states)
            state = output.state(word, io.StringIO()) if word else ""
            kind = "Klipper" if p.family == "klipper" else "Bambu"
            rows.append(menu_ui.Row(registry.display_name(p), f"{kind:<8} {_printer_address(p)}  {state}".rstrip(),
                                    note="Enter opens this printer."))
        found = sum(1 for p in printers if not p.configured)
        sc = menu_ui.Screen("printers", f"Printers{sep}{len(printers) - found} set up{sep}{found} found", rows,
                            actions=(("a", "add a printer"), ("l", "look again")), leave="back",
                            empty="No printers yet. Printers on your network appear here once they announce themselves.")
        ev = ui.choose(sc, show)
        show = False
        if ev[0] == "eof":
            raise _Ended
        if ev[0] == "leave":
            return
        if ev[0] == "action":
            if ev[1] == "a":
                with ui.suspended():
                    _printer_add(ui)
            show = True
        elif ev[0] == "open":
            _printer_screen(ui, printers[ev[1]].serial)
            show = True


def _printer_add(ui) -> None:
    """`a` on the list: the questions of `printer add` (8.7): the kind first, then its fields in the Hub form's order."""
    kind = _ask("Add a Bambu Lab printer (b) or a Klipper printer (k)? [b]: ")
    if kind is None:
        raise _Ended
    try:
        if kind.strip().lower() in ("k", "klipper"):
            host = hostaddr.clean(_ask("Address: ") or "")
            port = _ask("Port [7125]: ")
            name = (_ask("Name (optional): ") or "").strip()
            key = _secret("Moonraker API key (optional): ").strip()
            bad = hostaddr.form_error(host) if host else "give the printer's address"
            if bad:
                output.error(str(bad))
                return
            try:
                number = int((port or "").strip() or 7125)
            except ValueError:
                output.error("the port is a number.", "give the port as digits, for example 7125.")
                return
            from .bridge.klipper import discovery
            p = discovery.add(name, host, number)
            if key:
                registry.set_api_key(p.serial, key)
            output.out(f"Added {registry.display_name(p)}.")
            return
        ip = hostaddr.clean(_ask("IP address or name (e.g. 192.0.2.40 or printer.local): ") or "")
        code = _secret(f"Access Code {ACCESS_WHERE}: ").strip()
        name = (_ask("Name (optional): ") or "").strip()
        serial = (_ask("Serial (optional: read from the printer): ") or "").strip()
        model = (_ask("Model (optional, e.g. H2D, X1C, P1S; it picks the camera): ") or "").strip()
        if not code:
            output.out("No Access Code entered; nothing added.")
            return
        if not ip:
            output.error("an address is needed.")
            return
        _, problem, note = hostaddr.inspect(ip)
        if problem:
            output.error(f"not added: {problem}.")
            return
        if note:
            output.note(f"{note}.")
        from . import setup_page          # the Hub's own reader: the serial a printer names in its certificate
        try:
            seen, why = setup_page.setup_serial(ip), ""
        except OSError as e:
            seen, why = None, f"the printer at {ip} did not answer ({type(e).__name__})"
        if seen and serial and seen.upper() != serial.upper():
            output.error(f"not added: the printer at {ip} names itself {seen}, not {serial.upper()}.",
                         "check the address, or leave the serial empty to take the printer's own.")
            return
        serial = seen or serial
        if not serial:
            output.error(f"{why or f'the printer at {ip} did not name its serial'}, so it cannot be read.",
                         "give the serial number; it is on the printer's label and in Bambu Studio.")
            return
        if not registry.SERIAL.fullmatch(serial):
            output.error(f"not added: {registry.BAD_SERIAL}.")
            return
        problem = registry.check_fields(serial, code)
        if problem:
            output.error(f"not added: {problem}.")
            return
        old = registry.load().get(serial)
        added = registry.add_bambu(serial, name or serial, model or (old.model if old else ""), ip, code)
        output.out(f"Added {added.name}.")
    except (registry.RegistryError, ValueError) as e:
        output.error(str(e))


def _printer_keys(p, state: str) -> tuple[tuple[str, str], ...]:
    if not p.configured:
        return _FOUND_KEYS
    if p.family == "klipper":
        return _KLIPPER_KEYS
    keys = list(_BAMBU_KEYS)
    if state != "connected":          # a problem is shown: the report comes first, then the test
        return tuple(keys)
    keys[0], keys[1] = keys[1], keys[0]
    return tuple(keys)


def _printer_screen(ui, serial: str) -> None:
    """One printer: its facts, then the actions as letters (8.4)."""
    sep, show = output.sym("sep"), True
    while True:
        p = registry.load().get(serial)
        if p is None:
            return
        word = _printer_state_word(p, _printer_states())
        facts = [f"{'Klipper' if p.family == 'klipper' else 'Bambu'}{sep}{_printer_address(p)}" +
                 (f"{sep}{p.model}" if p.model else "") + (f"{sep}serial {p.serial}" if p.family != "klipper" else "")]
        facts.append((output.state(word, io.StringIO()) if word else "set up") +
                     (f"{sep}certificate pinned" if p.cert_fp else ""))
        sc = menu_ui.Screen(f"printer-{serial}", f"Printers > {registry.display_name(p)}", [], intro=tuple(facts),
                            actions=_printer_keys(p, word), leave="back", prompt="Number or letter: ")
        ev = ui.choose(sc, show)
        show = False
        if ev[0] == "eof":
            raise _Ended
        if ev[0] == "leave":
            return
        if ev[0] == "action":
            with ui.suspended():
                try:
                    gone = _printer_do(p, ev[1])
                except registry.RegistryError as e:
                    output.error(str(e))
                    gone = False
            if gone:
                return
            show = True


def _printer_do(p, letter: str) -> bool:
    """What one letter of the printer screen does; True when the printer is gone from the list."""
    name = registry.display_name(p)
    serial = p.serial
    if letter == "c":
        cmd_printer_report(serial, _default_manager)
    elif letter == "m":
        cmd_printer_map(serial, _default_manager)
    elif letter == "b":
        cmd_printer_map(serial, _default_manager, manual=True)
    elif letter == "u" and p.configured:
        cmd_printer_unpin(serial)
    elif letter == "u":
        if p.family == "klipper":
            registry.configure_klipper(serial)
            output.out(f"Using {name}.")
            return False
        code = secret_input.ask(f"Access Code of {name} {ACCESS_WHERE}: ").strip()
        problem = registry.check_fields(serial, code) if code else None
        if not code:
            output.out("No Access Code entered; nothing added.")
        elif problem:
            output.error(f"not added: {problem}.")
        else:
            registry.set_code(serial, code)
            output.out(f"Added {name}.")
    elif letter == "t":
        _printer_test(p)
    elif letter == "d":
        output.out(f"{name} ({p.host}:{p.port})")
        klipper_cli._describe(p)
    elif letter == "v":
        found = sorted((config.paths().state / "printers" / serial).glob("printer-report-*.xml"))
        output.out_lines([f"  {f}" for f in found] if found else [f"No saved reports for {name}."])
    elif letter == "r":
        new = (_ask("New name: ") or "").strip()
        if new:
            registry.rename(serial, new)
            output.out(f"Renamed {name} to {new}.")
        else:
            output.out("Unchanged.")
    elif letter == "e":
        _printer_address_change(p)
    elif letter == "k" and p.family == "klipper":
        key = secret_input.ask(f"Moonraker API key for {name}: ").strip()
        if key:
            registry.set_api_key(serial, key)
            output.out(f"Stored the API key of {name}.")
        else:
            output.out("Unchanged.")
    elif letter == "k":
        code = secret_input.ask(f"New Access Code for {name} {ACCESS_WHERE}: ").strip()
        problem = registry.check_fields(serial, code) if code else None
        if not code:
            output.out("Unchanged.")
        elif problem:
            output.error(f"nothing changed: {problem}.")
        else:
            registry.set_code(serial, code, replace=True)
            output.out(f"Replaced the Access Code of {name}.")
    elif letter == "n":
        mode = (_ask(f"Lane data of {name} (auto, on or off) [{p.lane_data}]: ") or "").strip().lower()
        if mode in registry.LANE_DATA:
            registry.set_lane_data(serial, mode)
            output.out(f"{name}: lane_data {mode}.")
        else:
            output.out("Unchanged.")
    elif letter == "x":
        stop = _confirm(f"Clear the Moonraker API key of {name}? Spoolwarden then connects without a key. If Moonraker "
                        "asks for one, the printer's test says so until a key is set.",
                        f"clearing the API key of {name}", yes=False, ask=_ask)
        if stop is None:
            registry.set_api_key(serial, "")
            output.out(f"Cleared the API key of {name}.")
    elif letter == "f":
        if not p.configured:
            stop = _confirm(f"Dismiss {name}? It leaves this list. A new scan may find it again.",
                            f"dismissing {name}", yes=False, ask=_ask)
            word = "Dismissed"
        else:
            what = ("its Moonraker API key, if one is saved." if p.family == "klipper" else
                    "its Access Code. To use it again, add it again.")
            stop = _confirm(f"Forget {name}? Spoolwarden stops connecting to it and deletes {what}",
                            f"forgetting {name}", yes=False, ask=_ask)
            word = "Forgot"
        if stop is None:
            registry.remove(serial)
            output.out(f"{word} {name}.")
            return True
    return False


def _printer_address_change(p) -> None:
    name = registry.display_name(p)
    host = hostaddr.clean(_ask(f"Address of {name} [{_printer_address(p)}]: ") or "")
    if not host:
        output.out("Unchanged.")
        return
    bad = hostaddr.form_error(host)
    if bad:
        output.error(str(bad))
        return
    if p.family == "klipper":
        port = _ask(f"Port [{p.port}]: ")
        registry.set_address(p.serial, host, int(port.strip()) if (port or "").strip().isdigit() else None)
        output.out(f"Changed the address of {name}.")
        return
    code = secret_input.ask(f"Access Code of {name} {ACCESS_WHERE}: ").strip()
    if not code:
        output.out("No Access Code entered; nothing changed.")
        return
    problem = registry.check_fields(p.serial, code)
    if problem:
        output.error(f"nothing changed: {problem}.")
        return
    pinned = p.cert_fp
    registry.set_address(p.serial, host)
    registry.set_code(p.serial, code, replace=True)
    if pinned:
        registry.pin(p.serial, pinned)          # the pin is of the printer, not of its address
    output.out(f"Changed the address of {name}.")


def _printer_test(p) -> None:
    name = registry.display_name(p)
    if p.family == "klipper":
        with output.wait(f"Asking {name}…"):
            d = klipper_cli.detect(p, spoolman=False)
        output.out(f"{output.state('connected')} {name} answers at {p.host}:{p.port}." if d["ok"] else d["message"])
        return
    state = _printer_states().get(p.serial)
    if state is not None:
        output.out(f"{name}: {output.state('connected') if state == 'connected' else output.state('offline')}")
        return
    m = _default_manager(p.serial)
    try:
        why = _connect(m, p.serial)
    finally:
        m.stop()
    if why:
        output.error(why)
    else:
        output.out(f"{output.state('connected')} {name} answers at {p.ip}.")


# ---------- the Features checklist (06 8.5) ----------

_FEATURE_ASKS = {
    "web.public_url": ("{who} needs the address people use.",
                       "Public https address of the web app (e.g. https://hub.example/filament): ",
                       "give the https address people use, e.g. https://hub.example/filament."),
    "orders.file": ("Order history needs its file.", "Path of the order history file: ",
                    "give the path of the order history file."),
    "spoolman_url": ("The Hub service needs a Spoolman: none runs on this machine.",
                     "Address of your Spoolman (e.g. http://spoolman.example:7912): ",
                     "give the address of a Spoolman on another machine, e.g. http://spoolman.example:7912."),
    "station.allow": ("Weigh Station only needs the Hub's address.", "The Hub's address (IP address or name): ",
                      "enter one address or name, not a range or wildcard."),
}
_FEATURES_HINT = ("Type numbers to switch (several: 2 5 7); h, w, b choose a setup; s applies; q leaves; ? help.")


def _titles(names) -> str:
    return ", ".join(modules.MODULES[n].title for n in names)


def _and_list(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def _feature_note(name: str, chosen) -> str:
    """The checklist's first footer line: what the row needs and what switching it off also switches off (8.5)."""
    needs = [modules.MODULES[n].title if n in modules.MODULES else n for n in modules.needs_of(name)]
    gone = modules.dependents_closure(name, chosen)
    return (f"Needs {_and_list(needs)}." if needs else "Needs nothing else.") + \
        f" Off also turns off: {_titles(gone) if gone else 'nothing else'}."


def _feature_plan(on, chosen, explicit) -> tuple[str, str]:
    """(the plan line, the short list for the leave question): `Turns on: ... Turns off: ...` as the Hub's preview."""
    turned_on = [n for n in modules.MODULES if n in chosen and n not in on]
    turned_off = [n for n in modules.MODULES if n in on and n not in chosen]
    if not turned_on and not turned_off:
        return "Changes: none", ""
    parts, short = [], []
    if turned_on:
        words = []
        for n in turned_on:
            title = modules.MODULES[n].title
            who = [modules.MODULES[e].title for e in turned_on if e in explicit and e != n
                   and n in modules.needs_closure([e], frozenset())]
            words.append(f"{title} ({_and_list(who)} {'needs' if len(who) == 1 else 'need'} it)" if who and n not in explicit
                         else title)
        parts.append(f"Turns on: {', '.join(words)}.")
        short += [f"{modules.MODULES[n].title} on" for n in turned_on]
    if turned_off:
        parts.append(f"Turns off: {_titles(turned_off)}.")
        short += [f"{modules.MODULES[n].title} off" for n in turned_off]
    return " ".join(parts), ", ".join(short)


def _features_checklist(on, chosen, explicit) -> menu_ui.Screen:
    names = list(modules.MODULES)
    rows = [menu_ui.Row(modules.MODULES[n].title, modules.MODULES[n].description, mark="x" if n in chosen else " ",
                        note=_feature_note(n, chosen),
                        detail=("needs: " + ", ".join(modules.MODULES[d].title if d in modules.MODULES else d
                                                      for d in modules.needs_of(n))) if modules.needs_of(n) else "")
            for n in names]
    plan, _ = _feature_plan(on, chosen, explicit)
    return menu_ui.Screen("features", f"Features{output.sym('sep')}{_SETUP_WORDS[modules.mode_of(chosen)]}", rows,
                          kind="checklist", actions=(("h", "Hub setup"), ("w", "Weigh Station only"),
                                                     ("b", "Hub with Weigh Station")),
                          save="apply", plan=plan, after=(plan, _FEATURES_HINT), hint=_FEATURES_HINT)


_SETTING_OWNERS = {"web.public_url": "web", "orders.file": "orders", "spoolman_url": "server", "station.allow": "station"}


def _ask_setting(key: str, owner: str) -> str | None:
    """One setting of the table in 8.5: the line saying which feature needs it, then the prompt, asked again after a
    wrong value. The value, or None for an empty answer or the end of input."""
    line, prompt, wrong = _FEATURE_ASKS[key]
    output.out(line.format(who=modules.MODULES[owner].title))
    while True:
        raw = _ask(prompt)
        if raw is None or not raw.strip():
            return None
        value = raw.strip()
        if key == "station.allow":
            if modules._bad_allow(value):
                err = wrong
            elif value in modules._LOCAL_HOSTS:
                err = "give the address of the machine the Hub runs on."
            else:
                err = None
        else:
            err = wrong if modules.check_setting(key, value) else None
        if err:
            output.error(err)
            continue
        return value


def _ask_feature_settings(on, new: dict) -> tuple[dict | None, str]:
    """The settings the chosen features need and the Hub does not have yet, one prompt each in the table's order, each
    after one line saying which feature needs it (8.5). (answers, "") or (None, the feature that was not answered)."""
    need = modules.missing_settings(on, new)
    keys = [k for k in ("web.public_url", "orders.file") if k in need]
    keys += ["spoolman_url"] if modules.needs_spoolman_url(on, new) else []
    keys += ["station.allow"] if "station.allow" in need else []
    got: dict[str, str] = {}
    owners = {**_SETTING_OWNERS, "web.public_url": "web" if "web" in on else "remote"}
    for key in keys:
        value = _ask_setting(key, owners[key])
        if value is None:
            return None, modules.MODULES[owners[key]].title
        got[key] = value
    return got, ""


def _apply_features(ui, cfg: dict, chosen, explicit, on, raw_apply) -> tuple[bool, int]:
    """`s` in the checklist: (applied, exit code). Not applied: the rows stay as they are and the person is told why."""
    if chosen == on and raw_apply is None:
        ui.say("Unchanged.")
        return False, 0
    plan, short = _feature_plan(on, chosen, explicit)
    with ui.suspended():
        output.out(plan)
        if raw_apply is None and not _require_root():
            return False, output.NEEDS_SUDO
        new = _with_modules(cfg, chosen)
        _station_link(new, chosen)
        if "station" in chosen and "station" not in on and "server" in chosen:
            _link_station(new)
        got, owner = _ask_feature_settings(chosen, new)
        if got is None:
            output.out(f"Not applied: {owner} needs that setting.")
            return False, 0
        for key, value in got.items():
            modules.set_setting(new, key, value)
        try:
            modules.validate(new)
        except modules.ModuleError as e:
            output.error(f"{e}", "change the rows and apply again.")
            return False, 0
        if raw_apply is not None:
            return raw_apply(chosen, got), 0
        err = _plan_error(new)
        if err:
            output.error(f"{err}\nNothing was applied.")
            return False, 1
        config.save(new)
        rc = _run_apply(pairing=False)
        if rc == 0:
            output.out(f"Features applied: {short}.")
        return True, rc


def _features_screen(ui, cfg: dict, on=None, raw_apply=None, fresh=False) -> tuple[str, int]:
    """The Features checklist. ("applied", code), ("left", 0) or ("discarded", 0) after a yes to losing the switched
    rows. `raw_apply(chosen, answers) -> bool` stands in for saving and applying (`modules menu --raw`). `fresh`: the
    settings are read again when `s` applies (inside `config`, where they may have changed since the menu opened)."""
    on = frozenset(modules.enabled(cfg) if on is None else on)
    chosen, explicit, show = on, set(), True
    names = list(modules.MODULES)
    while True:
        ev = ui.choose(_features_checklist(on, chosen, explicit), show)
        show = True
        if ev[0] == "eof":
            raise _Ended
        if ev[0] == "toggle":
            for i in ev[1]:
                chosen, notes = modules.toggle(chosen, names[i])
                explicit.add(names[i])
                for note in notes:
                    ui.say(note)
        elif ev[0] == "action":
            mode = {"h": "server", "w": "station", "b": "all-in-one"}[ev[1]]
            before = chosen
            chosen, notes = modules.preset(chosen, mode)
            explicit |= set(before) ^ set(chosen)
            for note in notes:
                ui.say(note)
        elif ev[0] == "save":
            done, rc = _apply_features(ui, config.load() if fresh else cfg, chosen, explicit, on, raw_apply)
            if done:
                return "applied", rc
            if rc:
                return "left", rc
        elif ev[0] == "leave":
            if chosen == on:
                return "left", 0
            _, short = _feature_plan(on, chosen, explicit)
            n = len([1 for x in names if (x in chosen) != (x in on)])
            yes = ui.yesno(f"Leave without applying {_changes_word(n)} ({short})?")
            if yes is None:
                raise _Ended
            if yes:
                return "discarded", 0


def _need_terminal(what: str) -> int | None:
    """06 6.7: a menu with no terminal to ask on (and no `--numbered`): exit 2 after its Error and Fix."""
    if output.numbered() or menu_ui._stdin_tty():
        return None
    output.error(f"{what} is a menu, and there is no terminal to ask on.",
                 "run it again with --numbered, giving the answers on standard input.")
    return output.USAGE


def _modules_menu(cfg: dict) -> int:
    """`modules menu` (the Features checklist on its own): the exit code."""
    with menu_ui.open_ui(_ask, secret_input.ask) as ui:
        try:
            state, rc = _features_screen(ui, cfg)
        except _Ended:
            output.out("Input ended: nothing applied.")
            return output.CANCELLED
    if state == "discarded":
        output.out("Nothing applied.")
        return output.CANCELLED
    return rc


def cmd_modules_menu(raw: bool) -> int:
    """The checklist on its own. --raw: prompts on stderr; stdout gets the chosen modules as a comma list, then
    one `set <key>=<value>` line per setting asked for (install.sh custom mode). Changes nothing."""
    stop = _need_terminal("modules menu")
    if stop is not None:
        return stop
    cfg = config.load()
    on = modules.enabled(cfg)
    if not raw:
        return _modules_menu(cfg)
    if not _config_has_content():
        on = modules.MODES["server"]            # a first install: AI intake and the library start off
    result: dict = {}

    def keep(chosen, got) -> bool:
        """The installer's apply: check the whole choice, remember it; a refusal puts the person back in the list."""
        trial = _with_modules(cfg, chosen)
        _station_link(trial, chosen)
        if {"server", "station"} <= set(chosen):
            _link_station(trial)
        for key, value in got.items():
            modules.set_setting(trial, key, value)
        try:
            modules.validate(trial)
        except modules.ModuleError as e:
            output.error(str(e), "change the selection and apply again (q leaves).")
            return False
        result.update(chosen=chosen, got=got)
        return True

    out = sys.stdout
    sys.stdout = sys.stderr                     # prompts and the checklist go to the terminal, not the capture
    try:
        with menu_ui.open_ui(_ask, secret_input.ask, raw=True) as ui:
            try:
                state, _ = _features_screen(ui, cfg, on, keep)
            except _Ended:
                output.out("Input ended: nothing applied.")
                return output.CANCELLED
        if state == "discarded":
            output.out("Nothing applied.")
            return output.CANCELLED
        if state != "applied":
            return 1
    except KeyboardInterrupt:                   # the capture stays empty; the word goes to the terminal (06 6.7)
        output.out("Stopped.")
        return output.INTERRUPTED
    finally:
        sys.stdout = out
    print(",".join(n for n in modules.MODULES if n in result["chosen"]))
    for key, value in result["got"].items():
        print(f"set {key}={value}")
    return 0


# ---------- recent: Recently added (06 9.3) ----------
# The Hub page's own history code does the work (intake_history, the functions setup_console/intake_tab calls too).

# [field, the Hub page's label, its group], in the order of a group's rows
_REC_FIELDS = (("vendor", "Brand", "Identity"), ("name", "Name", "Identity"), ("material", "Material", "Identity"),
               ("color_hex", "Colour", "Identity"), ("net", "Net weight", "Weights"),
               ("tare", "Empty spool weight", "Weights"), ("density", "Density", "Weights"),
               ("nozzle", "Nozzle", "Temperatures"), ("bed", "Bed", "Temperatures"),
               ("nozzle_range", "Nozzle range", "Temperatures"), ("bed_range", "Bed range", "Temperatures"),
               ("price_per_kg", "Price per kg", "Other"), ("line", "Line", "Other"))
_REC_LABEL = {f: label for f, label, _ in _REC_FIELDS}
_REC_GROUPS = ("Identity", "Weights", "Temperatures", "Other")
# the keys of `recent edit` (06 9.3) and the other spellings of each; `color-hex` and the underscored names worked before
_REC_KEYS = {"brand": "vendor", "vendor": "vendor", "name": "name", "material": "material", "colour": "color_hex",
             "color": "color_hex", "color-hex": "color_hex", "net-weight": "net", "net": "net",
             "empty-spool-weight": "tare", "spool-weight": "tare", "tare": "tare", "density": "density",
             "nozzle": "nozzle", "bed": "bed", "nozzle-range": "nozzle_range", "bed-range": "bed_range",
             "price-per-kg": "price_per_kg", "line": "line"}
_REC_KEY_LIST = ("brand, name, material, colour, net-weight, empty-spool-weight, density, nozzle, bed, nozzle-range, "
                 "bed-range, price-per-kg, line")
_REC_STATE = {"detected": "as detected", "revised_ai": "revised by AI", "edited": "edited by hand"}
_REC_FROM = {"phone": "phone photo", "web": "web app", "station": "Weigh Station", "cli": "command line"}
_REC_FROM_SENTENCE = {"phone photo": "from a phone photo", "web app": "from the web app",
                      "Weigh Station": "from the Weigh Station", "by hand": "added by hand",
                      "command line": "from the command line"}
# a read confidence below high: its word (06 6.1), the glyph meaning of the word and its colour
_REC_LEVELS = {"low": ("low: check this", "error", "bad"), "medium": ("medium", "look", "warn"),
               "not_on_label": ("not on label", "off", "muted")}
_REC_EDIT_NOTHING = "nothing to change"       # intake_history.apply's refusal of values equal to the current ones


def _num_text(v) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _rec_value(field: str, v) -> str:
    """A value as the Hub page shows it: the colour with its #, a unit after a number, `(empty)` for none."""
    if v is None or v == "":
        return "(empty)"
    if field == "color_hex":
        return "#" + str(v).lstrip("#").upper()
    if field in ("net", "tare"):
        return f"{_num_text(v)} g"
    if field == "density":
        return f"{_num_text(v)} g/cm" + ("³" if output.unicode_glyphs() else "3")
    if field in ("nozzle", "bed"):
        return f"{_num_text(v)}{output.sym('degree')}"
    if field in ("nozzle_range", "bed_range"):
        return str(v) if re.search(r"[Cc]\s*$", str(v)) else f"{v}{output.sym('degree')}"
    return _num_text(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def _rec_when(at) -> str:
    return (at or "")[:16].replace("T", " ")


def _rec_from(r: dict) -> str:
    """The words of the FROM column: where the record came from (a phone or web record with no photo was typed in)."""
    if r.get("source") in ("station", "cli"):
        return _REC_FROM[r["source"]]
    return _REC_FROM.get(r.get("source"), "phone photo") if r.get("photos") else "by hand"


def _rec_filament_text(r: dict) -> str:
    """The filaments of a record's spools: `Bambu Lab PETG HF Orange x2`, a comma between different ones."""
    seen: dict[str, int] = {}
    for sp in r.get("spools") or []:
        name = f"{sp.get('vendor')} {sp.get('name')}"
        seen[name] = seen.get(name, 0) + 1
    return ", ".join(n + (f" x{c}" if c > 1 else "") for n, c in seen.items()) or "(no spools)"


def _paint_in(lines: list[str], text: str, token: str) -> list[str]:
    """`text` painted where it stands in every one of `lines` that holds it; a line's width is the same without colour."""
    painted = output.paint(text, token, sys.stdout)
    if painted == text:
        return lines
    return [ln.replace(text, painted) for ln in lines]


def _history_error(e, rid: str | None = None) -> int:
    """A refusal of the Hub's history code, as an error: a wrong record or value is exit 2, anything else 1."""
    from . import intake_history
    if rid is not None and e.code == "not_found" and str(e) == "no such intake record":
        output.error(f'"{rid}" is not a record in Recently added; only the newest {intake_history.keep()} are kept.',
                     "use an ID from spoolwarden recent.")
        return output.USAGE
    output.error(str(e))
    return output.USAGE if e.status in (400, 404) else output.FAILED


def cmd_recent(show_from: bool = False) -> int:
    """`recent` (06 9.3): a summary line, then the records newest first."""
    from . import intake, intake_history
    ai = intake.reading_on(config.load())
    d = intake_history.list_records(ai)
    output.emit(d)
    n = d["count"]
    if not d["keep"]:
        output.out("Recently added keeps no records. Set how many to keep with spoolwarden config (Records kept).")
    else:
        output.out(f"Recently added: {n} record{'s' if n != 1 else ''}, keeping {d['keep']}, "
                   f"{d['photo_bytes'] / 1048576:.1f} MB of photos.")
    if not ai:
        output.note("the Label Reader is off on this Hub, so corrections are by hand only.")
    if not n:
        if d["keep"]:
            output.out("No spool has been added since the history started.")
        return 0
    wide = output.width() >= 100 or not output._is_tty(sys.stdout) or output.plain()
    with_from = show_from and wide                      # the FROM column is for wide terminals; `show` and --json have it
    head = ["ID", "Added", "State", "Spools"] + (["From"] if with_from else []) + ["Filament"]
    rows = [[r["id"], _rec_when(r.get("at")), _REC_STATE.get(r.get("state"), r.get("state")),
             ", ".join(str(sp["spool_id"]) for sp in r["spools"])] + ([_rec_from(r)] if with_from else [])
            + [_rec_filament_text(r)] for r in d["records"]]
    output.out()
    output.out_lines(_paint_in(output.table(head, rows, long=len(head) - 1), "revised by AI", "info"))
    low = [r["id"] for r in d["records"] if (r.get("confidence") or {}).get("low")]
    if low:
        glyph = output.paint(output.glyph("look"), "warn", sys.stdout)
        output.out()
        output.out((glyph + " " if glyph else "") + (
            f"{low[0]} has fields read with low confidence: spoolwarden recent show {low[0]}" if len(low) == 1 else
            f"{len(low)} records have fields read with low confidence, the newest: spoolwarden recent show {low[0]}"))
    return 0


def _rec_reading(r: dict, item: int) -> dict | None:
    """The read the Hub kept for one item: {levels: field -> level, rated, filled}, or None for a record typed by hand."""
    read = r.get("read") if isinstance(r.get("read"), dict) else {}
    items = read.get("items") or []
    it = items[item] if 0 <= item < len(items) and isinstance(items[item], dict) else None
    if not it or not it.get("confidence_levels"):
        return None
    rated = read.get("confidence_rated") is not False
    return {"levels": {k: (None if v == "high" and not rated else v) for k, v in it["confidence_levels"].items()},
            "rated": rated, "filled": it.get("confidence_filled") or []}


def _rec_changed(r: dict) -> set:
    return {c["field"] for rv in r.get("revisions") or [] if not rv.get("undone") for c in rv.get("changes") or []}


def _rec_change_text(c: dict) -> str:
    """`Nozzle range 190-230 °C → 190-220 °C`."""
    f = c["field"]
    return f"{_REC_LABEL.get(f, f)} {_rec_value(f, c['old'])} {output.sym('arrow')} {_rec_value(f, c['new'])}"


def _rec_changes(rv: dict) -> list[dict]:
    """A revision's changes, each field once (an edit of several spools lists it for each)."""
    seen: set = set()
    return [c for c in rv.get("changes") or [] if not (c["field"] in seen or seen.add(c["field"]))]


def _rec_item_lines(r: dict, s: dict) -> list[str]:
    """One item's fields in groups, a confidence mark only where it is not high (06 9.3)."""
    reading, changed = _rec_reading(r, s["item"]), _rec_changed(r)
    shown = {f: _rec_value(f, s["values"].get(f)) for f, _, _ in _REC_FIELDS}
    room = min(max(len(v) for v in shown.values()), 30)
    lines: list[str] = []
    for group in _REC_GROUPS:
        lines.append(group)
        for field, label, g in _REC_FIELDS:
            if g != group:
                continue
            value, mark, painted = shown[field], "", ""
            lv = reading["levels"].get(field) if reading and field not in changed else None
            if lv in _REC_LEVELS:
                word, glyph, _ = _REC_LEVELS[lv]
                painted = (output.glyph(glyph) + " " if not output.plain() else "") + word
                mark = painted + (": filled in by the Hub" if lv == "medium" and field in reading["filled"] else "")
            text = value.ljust(room + 3) + mark if mark and len(value) <= room else value + ("  " + mark if mark else "")
            body = output.wrap(text.rstrip(), indent=22)
            body[0] = f"  {label:<20}" + body[0][22:]
            lines += _paint_in(body, painted, _REC_LEVELS[lv][2]) if mark else body
    if reading:
        lines.append("Read confidence is high unless marked." if reading["rated"] else
                     "This reader does not say how sure it is. Check the values against the label.")
    return lines


def cmd_recent_show(rid: str, photos: bool = False) -> int:
    """`recent show <record>`: where it came from, its fields in groups, its revisions."""
    from . import intake_history, setup_code
    try:
        r = intake_history.get(rid)
    except intake_history.HistoryError as e:
        return _history_error(e, rid)
    output.emit(r)
    sep = output.sym("sep")
    state = _REC_STATE.get(r.get("state"), str(r.get("state")))
    head = output.wrap(f"Record {r['id']}{sep}{_rec_when(r.get('at'))}{sep}{_REC_FROM_SENTENCE[_rec_from(r)]}{sep}{state}")
    output.out_lines(_paint_in(head, state, "info") if r.get("state") == "revised_ai" else head)
    ids = [str(sp["spool_id"]) for sp in r["spools"]]
    items = r["saved"]
    eng = (r.get("engine") or {}).get("reader")
    facts = [(f"Spool {ids[0]}" if len(ids) == 1 else f"Spools {', '.join(ids)}") if ids else "No spools"]
    if len(items) == 1 and items[0].get("filament_id") is not None:
        facts.append(f"filament {items[0]['filament_id']}")
    if r.get("photos"):
        facts.append(f"{r['photos']} photo{'s' if r['photos'] != 1 else ''}")
    if eng in ("cloud", "local"):
        facts.append("read by " + ("Cloud (Claude)" if eng == "cloud" else "On this Hub"))
    output.out(sep.join(facts))
    if not items:
        output.out()
        output.out("This record has no spools to edit now.")
    for s in items:
        output.out()
        if len(items) > 1:
            some = ", ".join(str(x) for x in s["spool_ids"])
            output.out(f"Item {s['item'] + 1}: spool{'s' if len(s['spool_ids']) > 1 else ''} {some} "
                       f"(filament {s['filament_id']}); changes apply to all of them")
        output.out_lines(_rec_item_lines(r, s))
    output.out()
    revs = r.get("revisions") or []
    if not revs:
        output.out("Revisions: none.")
    else:
        output.out("Revisions:")
        for rv in revs:
            by = "by the Label Reader" if rv.get("by") == "ai" else "by hand"
            line = (f"  {rv['n']}  {_rec_when(rv.get('at'))}  {by}  "
                    + "; ".join(_rec_change_text(c) for c in _rec_changes(rv)))
            fl = rv.get("filaments") or {}
            gone = (fl.get("orphaned_by_undo") if rv.get("undone") else fl.get("orphaned")) or []
            if rv.get("note"):
                line += f"{sep}note: {rv['note']}"
            if gone:
                line += f"{sep}filament {', '.join(str(g) for g in gone)} has no spools left (not deleted)"
            lines = output.wrap(line.lstrip() + (" (undone)" if rv.get("undone") else ""), indent=5, first=2)
            output.out_lines(_paint_in(lines[::-1], "(undone)", "muted")[::-1] if rv.get("undone") else lines)
    paths = intake_history.photo_paths(rid)
    if paths:
        output.out("Photos open on the Hub page: " + setup_code.page_url(config.load()) + f"#recent/{rid}")
        if photos:
            output.out("Photo files on the Hub:")
            output.out_lines(["  " + p for p in paths])
    else:
        output.out("No photo: this spool was added by hand." if _rec_from(r) == "by hand"
                   else "No photo was taken for this addition.")
    return 0


def _rec_filament_sentences(rv: dict, *, undone: bool = False) -> list[str]:
    """The Hub's sentences about the filament a change moved the spools to or emptied (03 6.4)."""
    fl = rv.get("filaments") or {}
    out = []
    if not undone and fl.get("to") is not None and fl.get("to") != fl.get("from"):
        out.append(f"The spools now use filament {fl['to']}" + (" (new)." if fl.get("created") else "."))
    gone = (fl.get("orphaned_by_undo") if undone else fl.get("orphaned")) or []
    if gone:
        out.append(f"Filament {', '.join(str(g) for g in gone)} has no spools left; it was not deleted.")
    return out


def _say_revision(r: dict, *, detail: bool = True) -> int:
    """`Saved as revision 2: Empty spool weight 140 g → 150 g.` (an edit), or `... 2: Name, Nozzle range.` (a revision
    the Label Reader proposed), then the Hub's sentences about the filament."""
    output.emit({"ok": True, **r})
    rv = r["revisions"][-1]
    changes = _rec_changes(rv)
    what = ("; ".join(_rec_change_text(c) for c in changes) if detail
            else ", ".join(_REC_LABEL.get(c["field"], c["field"]) for c in changes))
    output.result(f"Saved as revision {rv['n']}: {what}.")
    for sentence in _rec_filament_sentences(rv):
        output.result(sentence)
    return 0


def _rec_item_arg(item: int | None) -> int | None | bool:
    """`--item N` is the number the Hub page and `recent show` give an item (from 1); the history counts from 0. False
    after the error (exit 2)."""
    if item is None:
        return None
    if item < 1:
        output.error("item numbers start at 1.", "use --item 1 for the first item, as spoolwarden recent show numbers them.")
        return False
    return item - 1


def _history_audit(rid: str, what: str) -> None:
    """The Hub page's audit line for a change to a record, written as its routes write it (intake_tab.py)."""
    _hub_audit(f"recently added record {rid} {what}")


def _history_charge():
    """The read a revision by Claude takes off the daily cap, as the Hub's route takes it (reads.json, reads_per_day)."""
    from . import intake
    cap = intake.ReadCap(config.paths().state / "reads.json", config.load()["reads_per_day"])

    def charge():
        ticket = cap.take("command line")
        return lambda: intake.refund_quietly(cap, ticket, "command line")
    return charge


def cmd_recent_revise(rid: str, note: str, item: int | None = None, yes: bool = False) -> int:
    """`recent revise <record> --note`: ask the Label Reader again with the record's photos and the note, show what it
    suggests, and save it once it is accepted."""
    from . import intake, intake_history
    index = _rec_item_arg(item)
    if index is False:
        return output.USAGE
    try:
        intake_history.get(rid)
        if not intake.reading_on(config.load()):
            output.error("the Label Reader is off on this Hub, so only edits by hand work.",
                         cmd=f'sudo spoolwarden recent edit {rid} name="{output.sym("ellipsis")}"')
            return output.FAILED
        if not yes and not output.terminal():           # before the read is spent: nobody can accept it
            return output.no_terminal("applying the revision", _sudo_command("sudo spoolwarden <command>") + " --yes")
        sm = Spoolman(config.load()["spoolman_url"])
        with output.wait("Asking the Label Reader… (up to a minute)"):
            p = intake_history.revise(sm, rid, note, index, charge=_history_charge())
        _history_audit(rid, "revision asked of the AI")
        if p.get("no_photo"):
            output.note("no photo was kept for this record; the Label Reader worked from the saved values and your note.")
        if not p["changes"]:
            output.result("The Label Reader changed nothing.")
            return 0
        output.out("The Label Reader suggests:")
        limit = output.width() - 1
        arrow = output.sym("arrow")
        for k in p["changes"]:
            label, old, new = _REC_LABEL.get(k, k), _rec_value(k, p["before"].get(k)), _rec_value(k, p["after"].get(k))
            one = f"  {label}: {old} {arrow} {new}"
            output.out_lines([one] if len(one) <= limit else [f"  {label}: {old}", f"     {arrow} {new}"])
        stop = _confirm("Accept these changes?", "applying the revision", yes=yes)
        if stop is not None:
            return stop
        r = intake_history.apply(sm, rid, proposal=p["proposal"], device="command line")
        _history_audit(rid, "revised")
        return _say_revision(r, detail=False)
    except intake_history.HistoryError as e:
        return _history_error(e, rid)
    except intake.CapReached as e:
        output.error(str(e), "wait until a read is 24 hours old, or raise Reads per day in spoolwarden config.")
        return output.FAILED
    except intake.ReadError as e:
        output.error(str(e))
        return output.FAILED


def _rec_number(field: str, text: str, what: str, unit: str, whole: bool = False):
    """A number typed with or without its unit (`1000` or `1000 g`); empty is no value. ValueError says what was expected."""
    t = text.strip()
    if not t:
        return None
    m = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:" + unit + r")?", t, re.I)
    if not m:
        raise ValueError(f"{_REC_LABEL[field]} must be {what}.")
    n = float(m.group(1).replace(",", "."))
    if whole and not n.is_integer():
        raise ValueError(f"{_REC_LABEL[field]} must be {what}.")
    return int(n) if n.is_integer() else n


def _rec_edit_value(field: str, text: str):
    if field in ("net", "tare"):
        return _rec_number(field, text, "a number of grams, like 1000 or 1000 g", "g")
    if field == "density":
        return _rec_number(field, text, "a number in g/cm³, like 1.24", r"g/cm[³3]")
    if field in ("nozzle", "bed"):
        return _rec_number(field, text, "whole degrees, like 210", r"°\s*c|c", whole=True)
    if field == "price_per_kg":
        return _rec_number(field, text, "a number, like 24.5", "")
    return text.strip() or None


def cmd_recent_edit(rid: str, pairs: list[str], item: int | None = None, spools: str | None = None) -> int:
    """`recent edit <record> field=value ...`: change the saved values by hand (one revision)."""
    from . import intake_history
    values: dict = {}
    for kv in pairs:
        key, sep, text = kv.partition("=")
        if not sep:
            output.error(f'"{kv}" is not field=value.', "write each change as field=value, for example nozzle=230.")
            return output.USAGE
        field = _REC_KEYS.get(key.strip().lower().replace("_", "-"))
        if field is None:
            output.error(f'"{key.strip()}" is not a field of a record.', "use one of: " + _REC_KEY_LIST + ".")
            return output.USAGE
        try:
            values[field] = _rec_edit_value(field, text)
        except ValueError as e:
            output.error(str(e))
            return output.USAGE
    ids = None
    if spools:
        try:
            ids = [int(x) for x in spools.split(",") if x.strip()]
        except ValueError:
            ids = []
        if not ids:
            output.error("--spools takes spool ids.", "give them like --spools 41,42.")
            return output.USAGE
    index = _rec_item_arg(item)
    if index is False:
        return output.USAGE
    try:
        sm = Spoolman(config.load()["spoolman_url"])
        r = intake_history.apply(sm, rid, item=index, values=values, spool_ids=ids, device="command line")
        _history_audit(rid, "revised")
        return _say_revision(r)
    except intake_history.HistoryError as e:
        if str(e).startswith(_REC_EDIT_NOTHING):
            output.result("Nothing changed.")
            return 0
        return _history_error(e, rid)


def cmd_recent_undo(rid: str) -> int:
    """`recent undo <record>`: take back its newest revision that is not undone (the revision is kept, marked undone)."""
    from . import intake_history
    try:
        newest = next((rv for rv in reversed(intake_history.get(rid)["revisions"]) if not rv.get("undone")), None)
        r = intake_history.undo(Spoolman(config.load()["spoolman_url"]), rid, newest["n"] if newest else None)
    except intake_history.HistoryError as e:
        return _history_error(e, rid)
    _history_audit(rid, "revision undone")
    output.emit({"ok": True, **r})
    output.result(f"Undone: revision {newest['n']}. Record {rid} is {_REC_STATE.get(r['state'], r['state'])} again.")
    for sentence in _rec_filament_sentences(r["revisions"][newest["n"] - 1], undone=True):
        output.result(sentence)
    return 0


def cmd_cert() -> int:
    """`certificate` (06 9.12): make the Hub's certificate when there is none, print its fingerprint."""
    cert = config.paths().etc / "cert.pem"
    made = not cert.exists()
    if made:
        cert.parent.mkdir(parents=True, exist_ok=True)
        full, short = socket.gethostname(), pairing.short_hostname()
        fp = pairing.make_cert(short, pairing.local_ips(), cert.parent, extra_dns=[full] if full != short else [])
    else:
        fp = pairing.fingerprint(cert.read_bytes())
    output.emit({"ok": True, "made": made, "fingerprint": fp})
    output.out("Made a new certificate." if made else "Certificate present.")
    output.out("Fingerprint:")
    output.out_lines(_fingerprint_lines(fp))
    return 0


def cmd_ensure_fields() -> int:
    """`spoolman fields` (06 9.12)."""
    try:
        created = Spoolman(config.load()["spoolman_url"]).ensure_fields()
    except SpoolmanError as e:
        _err_line(f"Spoolman: {e}")
        return 1
    output.emit({"ok": True, "made": list(created)})
    output.result("Spoolman: added the kit's extra fields: " + ", ".join(created) + "." if created
                  else "Spoolman: the kit's extra fields are in place.")
    return 0


def cmd_spoolman_address(url: str | None) -> int:
    """`spoolman address [<url>]` (06 9.12): show the Spoolman in use, or check an address and save it the way the Hub's
    Settings > General does (it must answer first; the kit applies the change)."""
    cfg = config.load()
    if url is None:
        output.emit({"url": cfg.get("spoolman_url")})
        output.out(f"Spoolman in use: {cfg.get('spoolman_url')}.")
        return 0
    on = modules.enabled(cfg)
    if "server" not in on or "spoolman" in on:
        output.error("this machine runs its own Spoolman, so its address is not set.",
                     "turn the Spoolman Feature off first:", cmd="sudo spoolwarden features off spoolman")
        return output.FAILED
    if not _no_systemd() and not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden spoolman address " + shlex.quote(url)))
    menu = _ConfigMenu(copy.deepcopy(cfg), None)
    try:
        value = menu.check(_ITEMS["spoolman"], url)
    except _Sentence as e:
        output.error(str(e))
        return output.USAGE
    with output.wait(f"Checking {value}…"):
        menu.staged["spoolman"] = value
        new = copy.deepcopy(cfg)
        err = menu.build(new)
    if err:
        output.error(f"nothing was changed: {err.rstrip('.')}.")
        return output.FAILED
    try:
        config.save(new)
    except (GroupMissing, ValueError, library.LibraryError, OSError) as e:
        output.error(f"nothing was changed: {str(e).rstrip('.')}.")
        return output.FAILED
    _hub_audit("Spoolman address changed")
    output.emit({"ok": True, "url": value})
    output.result(f"Saved. The kit now uses the Spoolman at {value}.")
    return _run_apply(pairing=False)


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
    output.error(text)


def _input_ended() -> int:
    """The end of input at a secret prompt of a command: nothing was changed (06 8.2)."""
    output.out("Input ended.")
    return 5


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


CLI_TOKEN = "cli_kit_token"     # in the state folder: this command line's own pairing with the running server


def _server_api():
    """The running kit server's API, when it answers: `printer map` and `printer report` then ask it, since it already
    holds each printer's connection (a second one of our own gets nothing while the server's is up). None: no server
    here, and the command connects to the printer itself. It pairs once, in-process, as the built-in device
    "command line (this server)" (the commands run as the server's own user)."""
    try:
        port = int(config.load().get("port", 8710))
    except (OSError, ValueError, TypeError):
        return None
    if not _api_answers(port)[0]:
        return None
    from .web import slots
    return slots.KitApi(f"https://127.0.0.1:{port}", token_file=config.paths().state / CLI_TOKEN,
                        device=slots.CLI_DEVICE)


def _printer_name(serial: str) -> str:
    p = registry.load().get(serial)
    return registry.display_name(p) if p else serial


def _print_map_view(serial: str, v: dict, stopped: list) -> int:
    output.emit({**v, "ok": not stopped and v.get("outcome") in ("confirmed", "partial")})
    for s in v.get("slots") or []:
        where = "no number yet" if s.get("global") is None else f"printer slot {s['global']}"
        print(f"  {s['label']}: AMS {s['ams_id']} tray {s['tray_id']} -> {where}")
    for prob in v.get("problems") or []:
        print(f"  problem: {prob}")
    for note in v.get("notes") or []:
        print(f"  note: {note}")
    if v.get("report_wanted"):
        output.out(f"  {v.get('report_why') or 'A printer report would help.'} To collect one: "
                   + f"sudo spoolwarden printer report {serial}")
    if stopped:
        print("Mapping stopped. Any slot listed above as not restored may still hold a test colour; the next "
              "mapping run restores it first.")
        return 130 if stopped[0] == getattr(signal, "SIGINT", None) else 1
    print(v["outcome_text"])
    if v.get("next_step"):
        print(f"Next: {v['next_step']}")
    return 0 if v["outcome"] in ("confirmed", "partial") else 1


def _map_via_server(api, serial: str) -> int:
    """`printer map` through the running server: start its job, follow it, Ctrl-C stops it (slots put back first)."""
    from .web.slots import SlotError
    try:
        api.post(f"/api/printers/{serial}/map", {})
    except SlotError as e:
        _err_line(str(e))
        return 1
    stopped: list = []

    def on_signal(signum, frame):
        first = not stopped
        stopped.append(signum)
        if first:
            try:
                print("\n  Stopping: putting the slots back first (this takes a few seconds) ...", flush=True)
                api.post(f"/api/printers/{serial}/map/stop", {})
            except (OSError, RuntimeError, SlotError):
                pass
    old = _on_stop_signals(on_signal)
    seen = None
    try:
        with output.wait(f"Mapping the slots of {_printer_name(serial)}…"):
            while True:
                try:
                    v = api.get(f"/api/printers/{serial}/map")
                except SlotError as e:
                    _err_line(str(e))
                    return 1
                if v.get("state") == "running":
                    if v.get("step") and v["step"] != seen:
                        seen = v["step"]
                        print(f"  {seen}", flush=True)
                    time.sleep(1.0)
                    continue
                break
    finally:
        _restore_signals(old)
    return _print_map_view(serial, v, stopped)
NOT_CONNECTED = {
    "wrong_code": "the printer refused its Access Code; enter it again (sudo spoolwarden config"
                  + ", Printers)",
    "cert_changed": "the printer's certificate changed; add it again with its Access Code ("
                    + "sudo spoolwarden config, Printers)",
}


CONNECT_POLL = 0.1    # seconds between looks at the connection's state while it retries


def _connect(m, serial: str) -> str | None:
    """Start this command's own connection and wait until it is connected, then for the printer's first full
    report. `sync` only starts the connection and `wait_report` answers None at once until it is connected, so a
    real printer (whose TLS and MQTT take a moment) always looked offline without this wait. A refused or failed
    attempt is not the end: paho retries, so a printer still booting or back from a Wi-Fi drop within CONNECT_WAIT
    is waited for. Only a refused Access Code or a changed certificate, which no retry cures, stops it early.
    None when ready, else the line to print."""
    m.sync()
    p = registry.load().get(serial)
    name = registry.display_name(p) if p else serial
    deadline = time.monotonic() + CONNECT_WAIT
    with output.wait(f"Connecting to {name}" + (f" at {p.ip}" if p and p.ip else "") + "…"):
        state = m.wait_settled(serial, CONNECT_WAIT)
        while state not in ("connected", *NOT_CONNECTED, "not_configured") and time.monotonic() < deadline:
            time.sleep(min(CONNECT_POLL, max(0.0, deadline - time.monotonic())))
            state = m.state(serial)
    if state != "connected":
        return NOT_CONNECTED.get(state, "the printer did not answer; check that it is on and on the network "
                                        "({state})").format(serial=serial, state=state)
    with output.wait(f"Waiting for {name} to report…"):
        report = m.wait_report(serial, lambda r: "gcode_state" in r, REPORT_WAIT)
    if report is None:
        return "the printer connected but sent no report; try again in a moment"
    return None


MANUAL_POLL = 1.0     # seconds between looks at the manual-map session
SHARE_WAIT = 60.0     # seconds the share question waits for a line after the session (then it stays open)


def _stdin_lines():
    """Lines typed at the terminal, read on a thread so the session can be followed while the owner loads."""
    import queue
    q: queue.Queue = queue.Queue()

    def read():
        for line in sys.stdin:
            q.put(line)
        q.put(None)
    threading.Thread(target=read, daemon=True, name="manual-map-input").start()
    return q


def _manual_status(q: dict) -> str:
    """One position's row at the end of Map by loading filament (06 8.6): its state word, then the detail."""
    st = q.get("status")
    if st == "confirmed":
        nozzle = f", {q['nozzle']} nozzle" if q.get("nozzle") else ""
        return f"{output.state('confirmed')} ({q.get('reported_label')}{nozzle})"
    if st == "by_hand":
        return f"{output.state('entered by hand')} ({q.get('reported_label')})"
    if st == "skipped":
        return output.state("skipped")
    return str(st)


def _manual_prompt(v: dict) -> tuple[list[str], bool] | None:
    """The Hub's own sentences for the session's current step, then the line the command line adds: the answers it takes.
    (lines, asking), `asking` when an answer is wanted now; None while nothing is asked."""
    st = v.get("step")
    if not st:
        return None
    label = st["position"]["label"]
    if st.get("seen") and st.get("ask"):
        nozzle = v.get("dual_nozzle") and not st["seen"].get("nozzle_reported")
        return ([st["ask"], f"  y{' right or y left' if nozzle else ''} yes{output.sym('sep')}a slot (e.g. "
                 f"{label}{' left' if nozzle else ''}) I loaded that one{output.sym('sep')}s skip {label}"
                 f"{output.sym('sep')}q stop"], True)
    if not v.get("reports_loads"):
        lines = [st["say"]]
        lines += [f"  {i}  {c['label']}" for i, c in enumerate(v.get("choices") or [], 1)]
        lines.append(f"  a number{output.sym('sep')}s skip {label}{output.sym('sep')}q stop")
        return lines, True
    return [st["say"], f"  s skip {label}{output.sym('sep')}q stop"], False


def _manual_answer(v: dict, line: str) -> tuple[str, dict] | str:
    """(step, body) for what the owner typed, or the line to print when it means nothing here."""
    st = v.get("step")
    words = line.strip().split()
    if not words:
        return ""
    if words[0].lower() in ("q", "quit", "stop"):
        return "stop", {}
    if words[0] == "?":
        return "y yes, or the slot you loaded (e.g. A2); s skips it, q stops, Ctrl-C leaves at once"
    if not st:
        return "nothing is being asked now"
    pos = st["position"]
    if words[0].lower() in ("s", "skip"):
        return "skip", {"position": pos["id"]}
    seen = st.get("seen")
    if seen and st.get("ask"):
        nozzle = seen.get("nozzle") if seen.get("nozzle_reported") else None
        if v.get("dual_nozzle") and not seen.get("nozzle_reported"):
            if len(words) < 2 or words[1].lower() not in ("left", "right"):
                return "say which nozzle too: right or left"
            nozzle = words[1].lower()
        if words[0].lower() in ("y", "yes"):
            target = pos["id"]
        else:
            target = next((q["id"] for q in v.get("positions") or [] if q["label"].lower() == words[0].lower()), None)
            if target is None:
                return f"no position {words[0]} on this printer"
        return "confirm", {"position": target, "reported": seen.get("reported"), "nozzle": nozzle}
    if not v.get("reports_loads"):
        choices = v.get("choices") or []
        if words[0].isdigit() and 1 <= int(words[0]) <= len(choices):
            return "confirm", {"position": pos["id"], "reported": choices[int(words[0]) - 1]["reported"],
                               "by_hand": True}
        return f"type a number from 1 to {len(choices)}, s or q"
    return "the printer has not reported a new load yet; load it, or s skips, q stops"


def _manual_done(v: dict) -> str:
    """`Done: 3 confirmed, 1 skipped.`; `Stopped: ...` while positions were not asked."""
    got = [q.get("status") for q in v.get("positions") or []]
    parts = [f"{n} {word}" for word, n in (("confirmed", got.count("confirmed")),
                                           ("entered by hand", got.count("by_hand")),
                                           ("skipped", got.count("skipped"))) if n]
    pending = len(got) - len([g for g in got if g in ("confirmed", "by_hand", "skipped")])
    if pending:
        parts.append(f"{pending} not asked")
    return ("Stopped: " if pending else "Done: ") + (", ".join(parts) or "nothing mapped") + "."


def _manual_map_via_server(api, serial: str, lines=None) -> int:
    """`printer map --manual`: Map by loading filament in the terminal, on the running server's session (the same one
    the setup page, the phone web app and the Android app show; one session per printer). The owner loads each
    position; the printer reports what it sees; the owner answers here. Nothing is sent to the printer. The Hub's own
    sentences are printed as they come; the command line adds only the answer line (06 8.6)."""
    import queue
    from .web.slots import SlotError
    base = f"/api/printers/{serial}/manual-map"
    try:
        v = api.post(base + "/start", {})
    except SlotError as e:
        _err_line(str(e))
        return 1
    print(f"Map by loading filament: {_printer_name(serial)}\n"
          "Load each slot to the nozzle when asked. Nothing is sent to the printer.\n", flush=True)
    lines = lines if lines is not None else _stdin_lines()
    said, done_input = None, False
    stopped: list = []
    held = None                                     # the wait is paused while a question stands
    waiting = output.wait("Waiting for the printer to report a change…")
    waiting.__enter__()
    old = _on_stop_signals(lambda signum, frame: stopped.append(signum))
    try:
        while v.get("open"):
            if stopped:
                try:
                    v = api.post(base + "/stop", {"session": v.get("session")})
                except SlotError:
                    pass
                break
            asked = _manual_prompt(v)
            text = "\n".join(asked[0]) if asked else None
            if text and text != said:
                print(text, flush=True)
                if asked[1]:
                    if held is None:
                        held = waiting.paused()
                        held.__enter__()
                    print("Answer: ", end="", flush=True)
                said = text
            line = None
            if not done_input:
                try:
                    line = lines.get(timeout=MANUAL_POLL)
                except queue.Empty:
                    line = ""
                if line is None:             # the input ended (no terminal): stop rather than wait forever
                    done_input, line = True, "q"
            else:
                time.sleep(MANUAL_POLL)
            try:
                if line:
                    ans = _manual_answer(v, line)
                    if isinstance(ans, str):
                        if ans:
                            print(f"  {ans}", flush=True)
                        continue
                    step, body = ans
                    v = api.post(f"{base}/{step}", {"session": v.get("session"), **body})
                    said = None
                    if held is not None:
                        held.__exit__(None, None, None)
                        held = None
                else:
                    v = api.get(base)
            except SlotError as e:
                print(f"  {e}", flush=True)
                said = None
                try:
                    v = api.get(base)
                except SlotError as e2:
                    _err_line(str(e2))
                    return 1
    finally:
        _restore_signals(old)
        if held is not None:
            held.__exit__(None, None, None)
        waiting.__exit__(None, None, None)
    print()
    print(_manual_done(v))
    for q in v.get("positions") or []:
        print(f"  {q['label']}  {_manual_status(q)}")
    if "Not mapped" in (v.get("summary") or ""):
        print(v["summary"])
    if v.get("offer_report") and not stopped and not done_input:
        print("Share this map in a printer report, so other owners of this model benefit?\n"
              "Nothing is sent unless you choose to. [y/N]", flush=True)
        try:
            answer = lines.get(timeout=SHARE_WAIT)
        except queue.Empty:
            answer = None
        if answer is None:      # no answer is not a "no": the question stays for the setup page and the apps
            print("No answer; the setup page and the apps ask again.")
        else:
            try:
                r = api.post(base + "/offer", {"share": answer.strip().lower() in ("y", "yes")})
                print(r.get("message", ""))
            except SlotError as e:
                print(f"  {e}")
    if stopped:
        return 130 if stopped[0] == getattr(signal, "SIGINT", None) else 1
    if done_input:              # the input ended (no terminal): stopped, not finished, so a script sees a failure
        return 1
    return 0


def cmd_printer_map(serial: str, manager_factory, manual: bool = False, yes: bool = False) -> int:
    from .bridge import mapping
    from .bridge.connection import PrinterOffline, UnknownPrinter
    from .bridge.slottest import PrinterBusy
    p = registry.load().get(serial)
    if p is None or not p.configured:
        _err_line(f"no printer {serial} is set up (see: sudo spoolwarden config, Printers)")
        return output.USAGE
    if manual:
        api = _server_api()
        if api is None:     # the session lives in the server, shared with the other three interfaces
            _err_line("map by loading filament needs the running kit server.\nfix: sudo systemctl start filament-kit")
            return output.HUB_DOWN
        return _manual_map_via_server(api, serial)
    if p.family != "bambu":
        _err_line(f"{registry.display_name(p)} is a Klipper printer; Klipper printers are mapped by loading filament: "
                  f"spoolwarden printer map --manual {serial}")
        return 1
    name = registry.display_name(p)
    stop = _confirm(f"Map the slots of {name}? The printer changes its slot colours briefly and runs a short job with "
                    "no motion. The colours are put back afterwards.", f"mapping the slots of {name}", yes=yes)
    if stop is not None:
        return stop
    print(f"Mapping the slots of {name}. Each slot's colour changes briefly and the printer runs a "
          f"job with no heating and no motion.")
    api = _server_api()
    if api is not None:                 # the running server holds the printer: it maps, this follows
        return _map_via_server(api, serial)
    m = manager_factory(serial)
    stopped = []
    try:
        why = _connect(m, serial)
        if why:
            _err_line(why)
            return 1
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
            with output.wait(f"Mapping the slots of {registry.display_name(p)}…"):
                v = mapper.run(serial, on_step=lambda t: print(f"  {t}", flush=True))
        except mapping.LoadRunning:
            _err_line("a spool is being loaded into this printer; try again in a moment")
            return 1
        except mapping.AlreadyRunning:
            _err_line("slot mapping is already running for this printer")
            return 1
        except mapping.CertChanged:
            _err_line("the printer's certificate changed. If you reset the printer or its mainboard was replaced, "
                      "add it again with its Access Code. "
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
    return _print_map_view(serial, v, stopped)


def cmd_printer_report(serial: str, manager_factory) -> int:
    """`printer report <serial>`: the file an owner attaches to help add a printer or an AMS the kit doesn't know."""
    from .bridge import mapping
    from .bridge.connection import PrinterOffline, UnknownPrinter
    p = registry.load().get(serial)
    if p is None or not p.configured or p.family != "bambu":
        _err_line(f"no Bambu printer {serial} is set up here")
        return output.USAGE
    api = _server_api()
    if api is not None:                 # the running server holds the printer (its own connection gets nothing)
        from .web.slots import SlotError
        try:
            with output.wait(f"Collecting a report from {registry.display_name(p)}…"):
                r = api.post(f"/api/printers/{serial}/report", {})
        except SlotError as e:
            _err_line(str(e))
            return 1
        r = {**r, "path": str(config.paths().state / "printers" / serial / r["name"])}
        return _report_said(r)
    m = manager_factory(serial)
    try:
        why = _connect(m, serial)      # not reached: the report is built from what the kit saved instead
        r = mapping.Mapper(m).report(serial)
    except (PrinterOffline, UnknownPrinter):
        _err_line(f"{why or 'the printer cannot be reached'}; and the kit has saved nothing about it yet (no slot map, "
                  "no mapping run), so there is no report to make")
        return 1
    finally:
        m.stop()
    if why and not r.get("live", True):
        print(f"Not reached: {why}.")
    return _report_said(r)


def _report_said(r: dict) -> int:
    output.emit({"ok": True, **r})
    if not r.get("live", True):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["saved_until"])) if r.get("saved_until") else "unknown"
        print(f"The printer could not be reached: this report is built from what the kit saved (newest record {when}),"
              " without the printer's own live state.")
    print(f"Printer report saved: {r['path']}")
    print("It holds no serial, address, name or account id. Attach it to a 'Printer report' issue on the project's GitHub.")
    return 0


def cmd_printer_unpin(serial: str, yes: bool = False, access_code: str | None = None) -> int:
    """`printer forget-certificate <printer>` (once `printer unpin`): asks for the Access Code, as the API does (R103), and
    saves it with the cleared pin. `--access-code -` gives it on standard input."""
    p = registry.load().get(serial)
    if p is None:
        _err_line(f"no printer {serial}")
        return output.USAGE
    if p.family != "bambu":
        _err_line(f"{registry.display_name(p)} is a Klipper printer; it has no certificate to forget.")
        return 1
    if not p.configured:
        _err_line(f"{serial} is not set up here; add it with its Access Code first")
        return 1
    name = p.name or serial
    stop = _confirm(f"Forget the certificate of {name}? The next connection trusts whatever certificate answers at "
                    f"{p.ip or 'its address'} and remembers it. Do this only after the printer was reset or replaced.",
                    f"forgetting the certificate of {name}", yes=yes)
    if stop is not None:
        return stop
    code = _secret_answer(access_code, f"Access Code of {name} (on the printer: Settings > Network/LAN): ",
                          "--access-code", "printer forget-certificate")
    if code is None:
        return output.USAGE
    if not code:
        output.result("No Access Code entered; nothing changed.")
        return output.CANCELLED
    problem = registry.check_fields(serial, code)
    if problem:
        _err_line(f"nothing changed: {problem}")
        return 1
    registry.set_code(serial, code, replace=True)     # clears the pin, as adding the printer again
    # the service's Manager notices the cleared pin at its next registry sync (within 15 s) and reconnects
    output.emit({"ok": True, "serial": serial, "name": name})
    output.result(f"Forgot the certificate of {name}; the next connection pins the one it presents.")
    return 0


# ---------- printer commands (06 5, 9.2) ----------
# The Hub page's own printer code does the work: setup_page.SetupPage's printer routes and setup_console/printers_tab,
# run in this process with no setup code and no HTTP (these commands run as the Hub's own user). What that code asks
# the Hub's connection manager for (a printer's state, its slots) the running Hub answers through its API; with no
# Hub running every state is "unknown" (06 9.2).

def _families() -> frozenset:
    """The printer families whose module is on, as the running Hub serves them (api.py): nothing here acts on the others."""
    on = modules.enabled(config.load())
    return frozenset(f for m, f in (("printers", "bambu"), ("klipper", "klipper")) if m in on)


class _Hub:
    """Stands in for the connection manager the Hub page's printer code asks, and runs its routes. `api`: the running
    Hub's API (`_server_api()`), or None. Read once, `GET /api/printers`; `up` is False when nothing answered."""

    def __init__(self, api=None):
        self.api = api
        self._views: dict | None = None
        self._page = None

    def _read(self) -> dict:
        if self._views is None:
            self._views = {}
            if self.api is not None:
                from .web.slots import SlotError
                try:
                    self._views = {v["id"]: v for v in self.api.get("/api/printers")["printers"]}
                except (SlotError, KeyError, TypeError):
                    self.api = None
        return self._views

    @property
    def up(self) -> bool:
        self._read()
        return self.api is not None

    def view(self, serial: str) -> dict | None:
        """The Hub's own view of one printer (`GET /api/printers`), None when it does not know it."""
        return self._read().get(serial)

    def state(self, serial: str) -> str:
        views = self._read()
        return "unknown" if self.api is None else (views[serial]["state"] if serial in views else "offline")

    def sync(self) -> None:
        """The Hub's manager sees a change in the registry at its next round (within 15 s)."""

    def slots(self, serial: str) -> list | None:
        """The units and slots of a printer's status (`GET /api/printers/<id>`), None when there is none."""
        if self.api is None:
            return None
        from .web.slots import SlotError
        try:
            return self.api.get(f"/api/printers/{serial}")["status"]["ams"]
        except (SlotError, KeyError, TypeError):
            return None

    def rows(self) -> list[dict]:
        """The printer objects of `GET /setup/api/state` (`printers.list`), in the Hub page's order."""
        from types import SimpleNamespace
        from .setup_page import SetupPage
        return SetupPage._printer_rows(SimpleNamespace(families=_families(), printers=self, mapper=None))

    @property
    def page(self):
        if self._page is None:
            from .setup_page import SetupPage
            page = SetupPage(self, families=_families())
            page.guard = lambda fn, write=False, raw=False: fn       # no setup code: the user running this is the Hub's own
            page.audit = lambda request, what: None
            page._gap = lambda: None                                 # one command, no page to keep from asking too often
            self._page = page
        return self._page

    def route(self, path: str, method: str = "POST"):
        """One of the Hub page's printer routes (setup_console/printers_tab), without its guard."""
        from .setup_console import printers_tab
        return next(fn for p, fn, m in printers_tab.routes(self.page) if (p, m) == (path, method))

    def call(self, handler, serial: str | None = None, body: dict | None = None) -> tuple:
        """(the Hub's reply, None), or (None, exit code) after the Hub's refusal was printed as an error."""
        import asyncio
        from types import SimpleNamespace
        from .setup_page import Refused
        request = SimpleNamespace(path_params={"serial": serial} if serial else {}, headers={}, client=None)
        try:
            return asyncio.run(handler(request, body or {})), None
        except Refused as e:
            return None, self.refused(e)

    @staticmethod
    def refused(e) -> int:
        """Print the Hub's refusal as an error (a module that is off gets the command that turns it on); its exit code."""
        module = re.fullmatch(r"the (\w+) module is off on this server", e.message)
        output.error(e.message, cmd=f"sudo spoolwarden modules enable {module.group(1)}" if module else None)
        return output.USAGE if e.status in (400, 404) else output.FAILED


def _hub() -> _Hub:
    return _Hub(_server_api())


_STATE_WORD = {"connected": "connected", "unknown_model": "connected", "offline": "offline", "connecting": "offline",
               "wrong_code": "wrong Access Code", "cert_changed": "certificate changed", "unknown": "unknown",
               "not_configured": "not set up"}


def _state_word(row: dict) -> str:
    """The status word of a printer (06 6.1): what the Hub says, or that it is only found."""
    return "found, not added" if not row["configured"] else _STATE_WORD.get(row["state"], "needs a look")


def _bare(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _quoted(name: str) -> str:
    return name if re.fullmatch(r"[\w.-]+", name) else '"' + name.replace('"', '\\"') + '"'


def _address_of(row: dict) -> str:
    return f"{row['host']}:{row['port']}" if row["family"] == "klipper" else row["ip"]


def _printer_match(arg: str, rows: list[dict]) -> dict | None:
    """06 5: an exact serial or id, else an exact name, else the start of exactly one name; ignoring case."""
    a = arg.strip().lower()
    if not a:
        return None
    hit = [r for r in rows if r["serial"].lower() == a]
    if len(hit) != 1:
        hit = [r for r in rows if r["name"].lower() == a]
        if not hit:
            hit = [r for r in rows if r["name"].lower().startswith(a)]
    return hit[0] if len(hit) == 1 else None


def _printer_named(arg: str, *, found: bool = False, found_verb: str = "use") -> dict | None:
    """The printer `arg` names (06 5), or None after the error (the caller then exits with 2). `found`: a printer a scan
    found but nobody added may be named (`show`, `test`, `use`, `dismiss`); any other command says to run
    `printer <found_verb>` first. Names come from the registry alone: no Hub is asked."""
    rows = _Hub().rows()
    row = _printer_match(arg, rows)
    if row is None:
        a = arg.strip().lower()
        close = [r for r in rows if a and (a in r["name"].lower() or a in r["serial"].lower())][:5]
        fix = "use a name, serial or id from spoolwarden printer list." + (
            " Close matches:\n" + "\n".join(f"{r['name']}  {r['serial']}" for r in close) if close else "")
        output.error(f'"{arg}" does not name one printer.', fix)
        return None
    if not row["configured"] and not found:
        fix = (f"sudo spoolwarden printer add --address {row['ip']}" if row["family"] == "bambu" and found_verb == "use"
               else f"sudo spoolwarden printer {found_verb} {_quoted(row['name'])}")      # `use` refuses a Bambu printer
        output.error(f"{row['name']} is found on the network but not added yet.", cmd=fix)
        return None
    return row


def _family_refusal(row: dict, family: str, what: str, fix_cmd: str | None = None) -> bool:
    """True after saying that the printer is of the other family and has no `what`; `fix_cmd` is the command of its own
    family that does the same, where there is one."""
    if row["family"] == family:
        return False
    kind = "a Klipper printer" if row["family"] == "klipper" else "a Bambu Lab printer"
    output.error(f"{row['name']} is {kind}; it has no {what}.", cmd=fix_cmd)
    return True


def _entry(row: dict) -> "registry.Printer":
    return registry.load()[row["serial"]]


def _prompted(given, prompt: str):
    """What a flag gave, else what is typed at a terminal; None when there is no terminal to ask on (nothing is asked)."""
    if given is not None:
        return given
    return (_ask(prompt) or "").strip() if output.terminal() else None


def _secret_answer(given: str | None, prompt: str, flag: str, doing: str) -> str | None:
    """A secret (06 8.7): `-` reads one line of standard input, else it is asked, hidden. The text (maybe empty), or None
    after the error (nothing to ask on, or --json, which does not ask)."""
    if given == "-":
        try:
            return sys.stdin.readline().strip()
        except (OSError, ValueError):
            return ""
    if not output.json_mode():
        try:
            return secret_input.ask(prompt).strip()
        except (EOFError, RuntimeError, OSError):
            pass
    output.error(f"{doing} needs it, and " + ("--json does not ask." if output.json_mode() else
                                              "there is no terminal to ask."), f"give it on standard input with {flag} -.")
    return None


def _api_key_ok(key: str) -> bool:
    from .setup_console import printers_tab
    if key and not printers_tab.API_KEY.fullmatch(key):
        output.error(printers_tab.BAD_API_KEY)
        return False
    return True


def cmd_printer_list() -> int:
    hub = _hub()
    rows = hub.rows()
    output.emit(rows)
    if not hub.up:
        output.note("the Hub is not running, so connection states are unknown.")
    if not rows:
        output.out("No printer yet. Printers on the network appear here once they announce themselves.")
        output.out("Add one: sudo spoolwarden printer add")
        return 0
    lines = output.table(["Name", "Type", "Id", "Address", "State"],
                         [[r["name"], "Klipper" if r["family"] == "klipper" else "Bambu", r["serial"], _address_of(r),
                           _bare(output.state(_state_word(r)))] for r in rows], long=0, whole=True)
    if len(lines) == len(rows) + 1:         # a table, not blocks: the colour goes on after the layout is made
        for i, r in enumerate(rows, 1):
            word = output.state(_state_word(r))
            if lines[i].endswith(_bare(word)):
                lines[i] = lines[i][:len(lines[i]) - len(_bare(word))] + word
    output.out_lines(lines)
    output.out()
    mine = [r for r in rows if r["configured"]]
    found = [r for r in rows if not r["configured"]]
    words = [_state_word(r) for r in mine]
    summary = f"{len(mine)} set up"
    if hub.up and mine:
        looking = [r for r in mine if _state_word(r) not in ("connected", "offline")]
        summary += f": {words.count('connected')} connected, {words.count('offline')} offline" + (
            f", {len(looking)} need a look" if looking else "")
    output.out(summary + "." + (f" {len(found)} found on the network, not added." if found else ""))
    mark = "" if output.plain() else output.paint("▲" if output.unicode_glyphs() else "!", "warn", sys.stdout) + " "
    for r in mine if hub.up else []:
        if _state_word(r) != "connected":
            output.out(f"{mark}{r['name']} needs a look: spoolwarden printer show {_quoted(r['name'])}")
    for r in found:
        how = f"use {_quoted(r['name'])}" if r["family"] == "klipper" else f"add --address {r['ip']}"
        output.out(f"Add the found one: sudo spoolwarden printer {how}" if len(found) == 1 else
                   f"Add {r['name']}: sudo spoolwarden printer {how}")
    return 0


def _slot_rows(units: list) -> list[list]:
    rows = []
    for u in units or []:
        for s in u.get("slots") or []:
            spool = s.get("spool") or {}
            filament = spool.get("name") or s.get("type") or ""
            if not s.get("present", True) and not filament:
                rows.append([s.get("label", ""), "empty", "", ""])
                continue
            weight = spool.get("remaining_weight")
            rows.append([s.get("label", ""), filament or "unknown",
                         "#" + s["color_hex"].upper() if s.get("color_hex") else "",
                         f"{round(weight)} g" if isinstance(weight, (int, float)) else ""])
    return rows


def cmd_printer_show(arg: str) -> int:
    row = _printer_named(arg, found=True)
    if row is None:
        return output.USAGE
    hub = _hub()
    row = next((r for r in hub.rows() if r["serial"] == row["serial"]), row)
    output.emit(row)
    from .bridge import ams, models
    klipper = row["family"] == "klipper"
    fields = [("Model", (hub.view(row["serial"]) or {}).get("model_name") or models.model_name(row["model"])
               or "not known yet"),
              ("Address", _address_of(row)), ("ID" if klipper else "Serial", row["serial"]),
              ("State", output.state(_state_word(row)))]
    if row["configured"] and klipper:
        fields += [("API key", output.state("set" if row["api_key"] else "not set")), ("Lane data", row["lane_data"])]
    elif row["configured"]:
        fields += [("Certificate", "pinned" if row["pinned"] else "not pinned yet"),
                   ("Slots", "mapped" if ams.load_map(row["serial"]).slots else "not mapped")]
    output.out_lines([row["name"]] + [f"  {label:<11}  {value}" for label, value in fields])
    if row.get("report_why"):
        output.out_lines(output.status_row("needs a look", row["report_why"]))
    if not row["configured"]:
        return 0
    slots = hub.slots(row["serial"]) if _state_word(row) == "connected" else None
    output.out()
    if slots is None:
        output.out("No slot data while offline." if hub.up else "No slot data while the Hub is not running.")
    else:
        output.out_lines(output.table(["Slot", "Filament", "Colour", "Left"], _slot_rows(slots), long=1, right=(3,)))
    return 0


def cmd_printer_test(arg: str) -> int:
    row = _printer_named(arg, found=True)
    if row is None:
        return output.USAGE
    hub = _hub()
    with output.wait(f"Testing {row['name']}…"):
        r, rc = hub.call(hub.page.printer_test, row["serial"])
    if rc is not None:
        return rc
    output.emit(r)
    text = r["text"][:1].upper() + r["text"][1:]
    output.out_lines(output.status_row("OK" if r["reachable"] else "failed", text.rstrip(".") + "."))
    return 0 if r["reachable"] else 1


def cmd_printer_add(*, klipper: bool = False, address: str | None = None, port: int | None = None,
                    name: str | None = None, serial: str | None = None, access_code: str | None = None,
                    api_key: str | None = None) -> int:
    """`printer add` (06 9.2): asks for what the flags do not give (06 8.7). A Bambu Lab printer is added by the Hub
    page's own route, a Klipper printer as the Klipper commands always did."""
    address = _prompted(address, "Address: " if klipper else "IP address or name (e.g. 192.0.2.40 or printer.local): ")
    if address is None:
        output.error("printer add needs an address, and there is no terminal to ask.", "give it with --address.")
        return output.USAGE
    if not address.strip():
        output.error("give the printer's address.", "give it with --address.")
        return output.USAGE
    if klipper:
        if port is None:
            raw = _prompted(None, "Port [7125]: ")
            try:
                port = int(raw) if raw else 7125
            except ValueError:
                output.error("the port must be a number from 1 to 65535")
                return output.USAGE
        name = _prompted(name, "Name (optional): ") or ""
        key = ""
        if api_key == "-" or (api_key is None and output.terminal()):
            key = _secret_answer(api_key, "Moonraker API key (optional): ", "--api-key", "printer add")
        if key is None or not _api_key_ok(key):
            return output.USAGE
        return _klipper_add(name, address, port, key)
    code = _secret_answer(access_code, "Access Code (on the printer: Settings > Network/LAN): ", "--access-code",
                          "printer add")
    if code is None:
        return output.USAGE
    if not code:
        output.result("No Access Code entered; nothing added.")
        return output.CANCELLED
    body = {"address": address, "access_code": code, "name": _prompted(name, "Name (optional): ") or "",
            "serial": _prompted(serial, "Serial (optional: read from the printer): ") or ""}
    hub = _hub()
    with output.wait(f"Asking the printer at {address}…"):
        r, rc = hub.call(hub.page.printer_add, None, body)
    if rc is not None:
        return rc
    p = registry.load().get(r["serial"])
    shown = registry.display_name(p) if p else r["serial"]
    output.emit({"ok": True, "serial": r["serial"], "name": shown, **({"note": r["note"]} if r.get("note") else {})})
    output.result(f"Added {shown} (serial {r['serial']}).")
    if r.get("note"):
        output.note(r["note"])
    return 0


def cmd_printer_use(arg: str, api_key: str | None = None) -> int:
    row = _printer_named(arg, found=True)
    if row is None:
        return output.USAGE
    if row["configured"]:
        output.error(f"{row['name']} is already added.")
        return 1
    if row["family"] == "bambu":
        output.error(f"{row['name']} is a Bambu Lab printer; it needs its Access Code.",
                     cmd=f"sudo spoolwarden printer add --address {row['ip']}")
        return output.USAGE
    key = _secret_answer(api_key, "", "--api-key", "printer use") if api_key == "-" else ""
    if key is None or not _api_key_ok(key):
        return output.USAGE
    hub = _hub()
    _, rc = hub.call(hub.route("/printers/{serial}/connect"), row["serial"], {"api_key": key})
    if rc is not None:
        return rc
    output.emit({"ok": True, "serial": row["serial"], "name": row["name"], "host": row["host"], "port": row["port"]})
    output.result(f"Added {row['name']} ({_address_of(row)}).")
    return 0


def cmd_printer_dismiss(arg: str, yes: bool = False) -> int:
    row = _printer_named(arg, found=True)
    if row is None:
        return output.USAGE
    if row["configured"]:
        output.error(f"{row['name']} is added, so it cannot be dismissed.",
                     cmd=f"sudo spoolwarden printer forget {_quoted(row['name'])}")
        return output.USAGE
    stop = _confirm(f"Dismiss {row['name']}? It leaves this list. A new scan may find it again.",
                    f"dismissing {row['name']}", yes=yes)
    if stop is not None:
        return stop
    hub = _hub()
    _, rc = hub.call(hub.page.printer_forget, row["serial"])
    if rc is not None:
        return rc
    output.emit({"ok": True, "serial": row["serial"], "name": row["name"]})
    output.result(f"Dismissed {row['name']}.")
    return 0


def cmd_printer_forget(arg: str, yes: bool = False) -> int:
    row = _printer_named(arg, found_verb="dismiss")
    if row is None:
        return output.USAGE
    if row["family"] == "klipper":
        question = (f"Forget {row['name']}? Spoolwarden stops connecting to it and deletes its Moonraker API key, if one "
                    "is saved.")
    else:
        question = (f"Forget {row['name']}? Spoolwarden stops connecting to it and deletes its Access Code. To use it "
                    "again, add it again.")
    stop = _confirm(question, f"forgetting {row['name']}", yes=yes)
    if stop is not None:
        return stop
    hub = _hub()
    _, rc = hub.call(hub.page.printer_forget, row["serial"])
    if rc is not None:
        return rc
    output.emit({"ok": True, "serial": row["serial"], "name": row["name"]})
    output.result(f"Forgot {row['name']}.")
    return 0


def cmd_printer_rename(arg: str, name: str) -> int:
    row = _printer_named(arg)
    if row is None:
        return output.USAGE
    hub = _hub()
    _, rc = hub.call(hub.route("/printers/{serial}/rename"), row["serial"], {"name": name})
    if rc is not None:
        return rc
    new = registry.display_name(_entry(row))
    output.emit({"ok": True, "serial": row["serial"], "name": new})
    output.result(f"Renamed {row['name']} to {new}.")
    return 0


def cmd_printer_address(arg: str, address: str, port: int | None = None, access_code: str | None = None) -> int:
    row = _printer_named(arg)
    if row is None:
        return output.USAGE
    body: dict = {"address": address}
    if port is not None:
        body["port"] = port
    if row["family"] == "bambu":       # as the Hub page's Change address dialog: the Access Code comes with it
        code = _secret_answer(access_code, f"Access Code of {row['name']} (on the printer: Settings > Network/LAN): ",
                              "--access-code", "printer address")
        if code is None:
            return output.USAGE
        if not code:
            output.result("No Access Code entered; nothing changed.")
            return output.CANCELLED
        body["access_code"] = code
    elif access_code is not None:
        output.error(f"{row['name']} is a Klipper printer; it has no Access Code.")
        return output.USAGE
    hub = _hub()
    r, rc = hub.call(hub.route("/printers/{serial}/address"), row["serial"], body)
    if rc is not None:
        return rc
    p = _entry(row)
    where = f"{p.host}:{p.port}" if p.family == "klipper" else p.ip
    output.emit({"ok": True, "serial": row["serial"], "name": row["name"], "address": where,
                 **({"note": r["note"]} if r.get("note") else {})})
    output.result(f"Saved. {row['name']} is at {where}.")
    if r.get("note"):
        output.note(r["note"])
    return 0


def cmd_printer_access_code(arg: str, access_code: str | None = None) -> int:
    row = _printer_named(arg)
    if row is None or _family_refusal(row, "bambu", "Access Code", f"sudo spoolwarden printer api-key {_quoted(row['name'])}"):
        return output.USAGE
    code = _secret_answer(access_code, f"New Access Code for {row['name']} (on the printer: Settings > Network/LAN): ",
                          "--access-code", "printer access-code")
    if code is None:
        return output.USAGE
    if not code:
        output.emit({"ok": True, "serial": row["serial"], "name": row["name"], "changed": False})
        output.result("Unchanged.")
        return 0
    hub = _hub()
    _, rc = hub.call(hub.page.printer_code, row["serial"], {"access_code": code})
    if rc is not None:
        return rc
    output.emit({"ok": True, "serial": row["serial"], "name": row["name"], "changed": True})
    output.result(f"Saved the Access Code of {row['name']}.")
    return 0


def cmd_printer_api_key(arg: str, api_key: str | None = None, clear: bool = False, yes: bool = False) -> int:
    row = _printer_named(arg)
    if row is None or _family_refusal(row, "klipper", "Moonraker API key",
                                      f"sudo spoolwarden printer access-code {_quoted(row['name'])}"):
        return output.USAGE
    if clear and api_key is not None:
        output.error("--clear and --api-key do not go together.", "use one of them.")
        return output.USAGE
    if clear:
        stop = _confirm(f"Clear the Moonraker API key of {row['name']}? Spoolwarden then connects without a key. If "
                        "Moonraker asks for one, the printer's test says so until a key is set.",
                        f"clearing the API key of {row['name']}", yes=yes)
        if stop is not None:
            return stop
        key = ""
    else:
        key = _secret_answer(api_key, f"Moonraker API key for {row['name']}: ", "--api-key", "printer api-key")
        if key is None:
            return output.USAGE
        if not key:
            output.emit({"ok": True, "serial": row["serial"], "name": row["name"], "set": row["api_key"]})
            output.result("Unchanged.")
            return 0
    hub = _hub()
    _, rc = hub.call(hub.route("/printers/{serial}/api_key"), row["serial"], {"key": key})
    if rc is not None:
        return rc
    output.emit({"ok": True, "serial": row["serial"], "name": row["name"], "set": bool(key)})
    output.result(f"Saved the API key of {row['name']}." if key else f"Cleared the API key of {row['name']}.")
    return 0


def cmd_printer_lane_data(arg: str, mode: str) -> int:
    row = _printer_named(arg)
    if row is None or _family_refusal(row, "klipper", "lane data"):
        return output.USAGE
    hub = _hub()
    _, rc = hub.call(hub.route("/printers/{serial}/lane_data"), row["serial"], {"mode": mode})
    if rc is not None:
        return rc
    output.emit({"ok": True, "serial": row["serial"], "name": row["name"], "lane_data": mode})
    output.result(f"Saved. Lane data: {mode}.")
    return 0


def cmd_printer_detect(arg: str) -> int:
    row = _printer_named(arg)
    if row is None or _family_refusal(row, "klipper", "model to detect"):
        return output.USAGE
    return klipper_cli.detect_printer(_entry(row))


def cmd_printer_scan(subnet: str | None = None) -> int:
    return _scan(subnet)


def _klipper_add(name: str | None, host: str, port: int, key: str) -> int:
    """`printer add --klipper`: the Hub's own route (`POST /printers/klipper`), so a printer a scan found is put into use
    as the Hub page does; then what the printer says it is (06 9.2)."""
    hub = _hub()
    r, rc = hub.call(hub.route("/printers/klipper"), None, {"host": host, "port": port, "name": name or "", "api_key": key})
    if rc is not None:
        return rc
    p = registry.load()[r["serial"]]
    output.result(f"Added {registry.display_name(p)} as {p.serial} ({p.host}:{p.port}).")
    if r.get("note"):
        output.note(r["note"])
    return klipper_cli._describe(p, {"ok": True, "id": p.serial, "name": registry.display_name(p), "host": p.host,
                                     "port": p.port})


def _scan(subnet: str | None) -> int:
    """`printer scan` (06 9.2): the Hub's own route (`POST /printers/scan`: a private IPv4 network, at most a /24); one
    line per printer found, and each is recorded (not added) so `printer use` can name it."""
    hub = _hub()
    from .setup_console import printers_tab
    from .setup_page import Refused
    try:                                    # the Hub's own checks first: a network it refuses is never named as looked at
        hub.page._manager("klipper")
        net = printers_tab.scan_net(subnet)
    except Refused as e:
        return _Hub.refused(e)
    with output.wait(f"Looking for Moonraker on {net}…"):
        r, rc = hub.call(hub.route("/printers/scan"), None, {"subnet": subnet})
    if rc is not None:
        return rc
    net, listed, lines = r["subnet"], [], []
    for f in r["found"]:
        p = registry.load()[f["serial"]]
        listed.append({**f, "id": p.serial, "name": registry.display_name(p)})
        where = f"{f['host']}:{f['port']}"
        lines.append(f"Found on {net}: {where} (added as {registry.display_name(p)})" if f["configured"] else
                     f"Found on {net}: {where} (add it: sudo spoolwarden printer use {p.serial})")
    output.emit({"ok": True, "subnet": net, "found": listed})
    if not lines:
        output.out(f"No Moonraker found on {net}.")
    for line in lines:
        output.out(line)
    return 0


def cmd_printer_reports(arg: str) -> int:
    row = _printer_named(arg)
    if row is None or _family_refusal(row, "bambu", "printer reports"):
        return output.USAGE
    hub = _hub()
    r, rc = hub.call(hub.route("/printers/{serial}/reports"), row["serial"])
    if rc is not None:
        return rc
    output.emit({**r, "reports": [{**x, "at": _iso(x["at"])} for x in r["reports"]]})
    if not r["reports"]:
        output.out("No report kept for this printer yet.")
        return 0
    output.out_lines(output.table(["Made", "Size", "Name"],
                                  [[_fmt_time(x["at"]), f"{max(1, round(x['size'] / 1024)):,} KiB", x["name"]]
                                   for x in r["reports"]], long=2, right=(1,)))
    output.out(f"Kept in {config.paths().state / 'printers' / row['serial']}.")
    return 0


def cmd_printer_live(arg: str) -> int:
    """06 10: the camera and the controls need a screen; say where they are."""
    if _printer_named(arg) is None:
        return output.USAGE
    ips = pairing.local_ips()
    host = ips[0] if ips else f"{pairing.short_hostname()}.local"
    url = f"https://{host}:{int(config.load().get('port', 8710))}/intake#printers"
    output.emit({"available": False, "where": "web app", "url": url})
    output.out(f"Camera and controls are in the web app: {url}")
    return 0


def _config_unreadable() -> int | None:
    """None when config.json reads; else the Error (06 6.5) and its exit code: the Hub page cannot list printers without it."""
    try:
        config.load()
    except ValueError as e:
        output.error(f"config.json cannot be read: {e}.",
                     f"correct {config.paths().etc / 'config.json'}, then run the command again.")
        return output.FAILED
    return None


def _dispatch_printer(a, manager_factory) -> int:
    bad = _config_unreadable()
    if bad is not None:
        return bad
    c = {"unpin": "forget-certificate"}.get(a.printer_cmd, a.printer_cmd)
    if c == "list":
        return cmd_printer_list()
    if c == "menu":
        return cmd_printer_menu()
    if c == "scan":
        return cmd_printer_scan(a.subnet)
    if c == "add":
        return cmd_printer_add(klipper=a.klipper, address=a.address, port=a.port, name=a.name, serial=a.serial,
                               access_code=a.access_code, api_key=a.api_key)
    simple = {"show": cmd_printer_show, "test": cmd_printer_test, "detect": cmd_printer_detect,
              "reports": cmd_printer_reports, "live": cmd_printer_live}
    if c in simple:
        return simple[c](a.printer)
    if c == "use":
        return cmd_printer_use(a.printer, a.api_key)
    if c == "dismiss":
        return cmd_printer_dismiss(a.printer, yes=a.yes)
    if c == "forget":
        return cmd_printer_forget(a.printer, yes=a.yes)
    if c == "rename":
        return cmd_printer_rename(a.printer, a.name)
    if c == "address":
        return cmd_printer_address(a.printer, a.address, a.port, a.access_code)
    if c == "access-code":
        return cmd_printer_access_code(a.printer, a.access_code)
    if c == "api-key":
        return cmd_printer_api_key(a.printer, a.api_key, a.clear, yes=a.yes)
    if c == "lane-data":
        return cmd_printer_lane_data(a.printer, a.mode)
    # map, report, forget-certificate: what they did before, on the printer the name stands for
    row = _printer_named(a.printer)
    if row is None:
        return output.USAGE
    if c == "map":
        return cmd_printer_map(row["serial"], manager_factory, manual=a.manual, yes=a.yes)
    if c == "report":
        return cmd_printer_report(row["serial"], manager_factory)
    return cmd_printer_unpin(row["serial"], yes=a.yes, access_code=a.access_code)


def cmd_printer_menu() -> int:
    """`printer menu`: the Printers screen of `config` (06 8.4), on its own."""
    if not output.numbered() and not menu_ui._stdin_tty():
        output.error("printer menu is a menu, and there is no terminal to ask on.",
                     "run it again with --numbered, giving the answers on standard input.")
        return output.USAGE
    try:
        with menu_ui.open_ui(_ask, secret_input.ask) as ui:
            try:
                _printers_screen(ui)
            except _Ended:
                pass
    except KeyboardInterrupt:
        return output.INTERRUPTED
    return 0


# ---------- library ----------

def _request_rebuild(reason: str) -> None:
    """Ask for a profile rebuild (filament-kit-build.path starts the build)."""
    builds.request_rebuild(reason)


_CATALOG_SOURCE = {"updated": "signed release", "bundled": "bundled with this version"}


def cmd_library_status() -> int:
    """`catalog status` (06 9.11): the version, where it comes from, the last check and what was skipped."""
    st = library.status()
    if output.json_mode():
        from .setup_console import library_tab
        view = library_tab._view()          # the Hub page's own reply
        if isinstance(view.get("last_check"), dict):
            view["last_check"]["at"] = _iso((st.get("last_check") or {}).get("at"))
        output.emit(view)
    n = st["local"]
    additions = f"{n} local addition{'' if n == 1 else 's'}"
    if st["source"] == "none":
        output.out("The Filament Catalog is not downloaded yet.")
        output.out("Fix: sudo spoolwarden catalog update")
    else:
        output.out(f"Filament Catalog version {st['version']} ({_CATALOG_SOURCE.get(st['source'], st['source'])}), "
                   f"{additions}.")
    output.out(f"Source: {st['url']}")
    lc = st["last_check"]
    if lc is None:
        output.out("Last check: never.")
    else:
        output.out(f"Last check {_fmt_time(lc['at'])}: " + ("ok." if lc["ok"] else f"failed: {str(lc['error']).rstrip('.')}."))
    if st["skipped"]:
        output.out(st["skipped"])
    return 0


def _failed_row(text: str, fix: str = "") -> int:
    """`× failed  <text>` (06 6.1), the way a command's job ends when it did not work."""
    output.out_lines(output.status_row("failed", text, fix))
    return output.FAILED


def cmd_library_update(scheduled: bool) -> int:
    """`catalog update [--scheduled]` (06 9.11)."""
    cfg = config.load()
    try:
        if scheduled:
            if library.schedule(cfg) == "off":
                output.out("Filament Catalog updates are off.")
                return 0
            if not library.due(cfg, time.time()):
                output.out("Not due yet.")
                return 0
        job = steps.Steps(4)
        with output.wait("Updating the Filament Catalog…", programs=True):
            r = library.update(cfg["library"].get("url") or None, scheduled=scheduled, step=job.next)
    except (library.LibraryError, ValueError) as e:
        return _failed_row(str(e))
    if r.note:
        output.note(r.note)
    if r.error:
        if scheduled and r.http_status in library.PRIVATE_STATUSES:
            # the catalog may simply not be published yet: the timer run is not a failure, the last good
            # version (or none) stays in use
            output.note(f"{r.error.rstrip('.')}. The version in use stays.")
            return 0
        return _failed_row(r.error)
    if r.held_from is not None:
        output.out(f"Version {r.version} stays: version {r.held_from} was rolled back and is the newest published. "
                   "Scheduled updates wait for a newer one; to install it anyway run: "
                   "sudo spoolwarden catalog update")
        return 0
    if not r.changed:
        output.out(f"Up to date: {r.version}.")
        return 0
    output.out(f"Installed {r.version} ({r.downloaded} entr{'y' if r.downloaded == 1 else 'ies'} downloaded).")
    text = library.skipped_text()
    if text:
        output.out(text)
    job.next("Asking for a preset build")
    _request_rebuild(f"library updated to version {r.version}")
    return 0


def cmd_library_adopt(folder: str) -> int:
    """`catalog adopt <folder>` (06 9.11)."""
    try:
        library.adopt(Path(folder))
    except library.LibraryError as e:
        _err_line(str(e))
        return 1
    n = library.load().local_count
    output.result(f"Took over the catalog in {folder}: {n} local addition{'' if n == 1 else 's'}.")
    return 0


def cmd_library_rollback(yes: bool = False) -> int:
    """`catalog rollback` (06 7, 9.11)."""
    stop = _confirm("Go back to the previous Filament Catalog? The version before the last update comes back. Your own "
                    "entries are kept.", "going back to the previous Filament Catalog", yes=yes)
    if stop is not None:
        return stop
    job = steps.Steps(2)
    job.next("Putting the previous Filament Catalog back")
    try:
        v = library.rollback()
    except library.LibraryError as e:
        _err_line(str(e))
        return 1
    output.result(f"Back to version {v}.")
    left = library.rolled_back_from()
    if left is not None:
        output.note(f"scheduled updates skip version {left} until a newer one is published; "
                    "sudo spoolwarden catalog update installs it anyway.")
    job.next("Asking for a preset build")
    _request_rebuild(f"library rolled back to version {v}")
    return 0


def cmd_library_add(source: str) -> int:
    """`catalog add <file | ->` (06 9.11)."""
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
    except OSError:
        output.error(f"there is no readable file at {source}.", "give the path of one catalog entry as a JSON file.")
        return output.USAGE
    if len(data) > limit:
        _err_line(f"entry not added: larger than {limit // 1024} KiB.")
        return 1
    try:
        entry, line = library.add_local(data)
    except ValueError as e:
        _err_line(f"entry not added: {e}")
        return 1
    output.emit({"ok": True, "vendor": entry["vendor"], "product": entry["product"], "line": line})
    output.result(f"Added {entry['vendor']} {entry['product']}. A preset build follows.")
    _request_rebuild(f"local library addition {line}")
    return 0


def cmd_library_token(remove: bool, yes: bool = False) -> int:
    """`catalog token [--remove]` (06 9.11, 8.7): set, replace or remove the token the Filament Catalog downloads with."""
    if not _no_systemd() and not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden catalog token" + (" --remove" if remove else "")))
    if remove:
        stop = _confirm("Remove the Catalog token? The Filament Catalog can then download only from public sources.",
                        "removing the Catalog token", yes=yes)
        if stop is not None:
            return stop
        try:
            removed = library.remove_token()
        except (OSError, library.LibraryError) as e:
            _err_line(f"the token was not removed: {e}")
            return 1
        output.emit({"ok": True, "token": {"set": False}})
        if not removed:
            output.result("There was no Catalog token to remove.")
            return 0
        _hub_audit("library token removed")
        output.result("Removed the Catalog token.")
        return 0
    if output.json_mode():
        output.error("catalog token asks for the token, and --json does not ask.", "run it without --json.")
        return output.USAGE
    try:
        token = secret_input.ask("Catalog token (typing is not shown): ").strip()
    except EOFError:
        return _input_ended()
    if not token or " " in token or not token.isprintable() or len(token) > 400:
        output.error("a GitHub token is one word of printable characters.")
        return output.USAGE
    from .setup_page import _present
    had = _present(library.TOKEN_FILE)
    try:
        library.write_token(token)
    except (OSError, library.LibraryError, ValueError) as e:
        _err_line(f"the token was not saved: {e}")
        return 1
    _hub_audit("library token replaced" if had else "library token set")
    output.result("Saved the catalog token.")
    return 0


# ---------- presets (06 9.5; `profiles` is the old spelling) ----------

def _default_spoolman() -> Spoolman:
    return Spoolman(config.load()["spoolman_url"])


def _journal_address() -> str | None:
    """The syslog socket the systemd journal reads, or None where there is none (Windows, dev machines)."""
    return "/dev/log" if hasattr(socket, "AF_UNIX") and os.path.exists("/dev/log") else None


def _log_to_journal() -> None:
    """Audit lines go to the journal directly (ident filament-kit), never to the terminal: stderr carries only Error,
    Fix and Note lines (06). Without a journal the lines are dropped silently."""
    import logging
    import logging.handlers
    app_log = logging.getLogger("filament_kit")
    if any(getattr(h, "_filament_kit_journal", False) for h in app_log.handlers):
        return
    address = _journal_address()
    if address is None:
        return
    try:
        handler = logging.handlers.SysLogHandler(address=address)
    except OSError:
        return
    handler.ident = "filament-kit: "
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler._filament_kit_journal = True
    app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)


def _hub_audit(what: str) -> None:
    """The Hub page's audit line for a change, written as its routes write it (setup_page.audit), to the journal."""
    from types import SimpleNamespace
    from .setup_page import SetupPage
    _log_to_journal()
    SetupPage.audit(SetupPage, SimpleNamespace(client=None), what)


def _presets_on() -> bool:
    """False, after its Error and Fix, while the Slicer presets Feature is off: the Hub page refuses the same way."""
    if "presets" in modules.enabled(config.load()):
        return True
    output.error('the "Slicer presets" Feature is off.', "turn it on first:",
                 cmd="sudo spoolwarden features on presets")
    return False


def _when(t) -> str:
    """A time of the Hub's own view (ISO text, or none) as local `2026-11-12 07:30`."""
    try:
        return datetime.datetime.fromisoformat(str(t)).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(t)


def _stamp_when(stamp: str) -> str:
    """A build's stamp (UTC `20261112-030500`) as local `2026-11-12 03:05`."""
    try:
        return datetime.datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(
            tzinfo=datetime.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def cmd_profiles_build(sm_factory) -> int:
    """`presets build`: runs the build here and waits for it (the Hub page asks the build unit for one instead)."""
    with output.wait("Building the Slicer presets…"):
        r = builds.run_build(sm_factory())
    if r.get("waiting"):
        # waiting for the first Slicer Sync run is a normal state: the build unit must not show as failed
        text = r.get("error") or builds.NO_SYSTEM
        output.emit({"ok": True, "waiting": True, "text": text})
        output.out_lines(output.status_row("note", text.rstrip(".") + ".",
                                           "sudo spoolwarden pair --slicer-sync"
                                           if text == builds.NO_SYSTEM else ""))
        return 0
    if not r.get("ok"):
        output.error(f"The build failed: {str(r.get('error')).rstrip('.')}. The last good build stays in use.",
                     "see what it logged:", cmd="sudo journalctl -u filament-kit-build -n 50")
        return 1
    n = int((builds.current() or {}).get("presets") or 0)
    problems = [str(p) for p in r.get("problems") or []]
    output.emit({"ok": True, "presets": n, "problems": problems})
    output.out_lines(output.status_row(
        "done", f"Presets built: {n}. Problems: " + (f"{len(problems)}:" if problems else "none.")))
    for p in problems:
        output.out_lines(output.status_row("needs a look", p))
    return 0


def cmd_profiles_status() -> int:
    """`presets status`: the Hub page's reply (`--json`) as lines in the page's order."""
    from .setup_console import presets_tab
    v = presets_tab._view()
    if not v["on"] and not _presets_on():               # an error says so, with exit 1, as text and as --json (06 6.8)
        return 1
    if v["on"] and v["lines_error"]:
        output.error(v["lines_error"])
        return 1
    output.emit(v)
    if not v["on"]:
        return 0
    output.out(f"Lines: {len(v['lines'])}.")
    b = v["build"]
    if b:
        orca = f" ({v['orca_presets']} for Orca Slicer)" if v.get("orca_presets") is not None else ""
        found = b.get("problems") or 0
        output.out(f"Last build {_when(b.get('created'))}. Presets: {v['presets']}{orca}. "
                   f"Problems: {found or 'none'}.")
    else:
        output.out("No build yet.")
    la = v["last_attempt"]
    if la and not la.get("ok") and la.get("error") and la["error"] not in (builds.NO_SYSTEM, builds.WAIT_LIVE):
        output.out(f"The last build attempt failed ({_when(la.get('at'))}): {str(la['error']).rstrip('.')}.")
    if la and la.get("error") == builds.WAIT_LIVE:
        output.out("Waiting for the PC's next sync: the Slicer Sync runs every 10 minutes while Bambu Studio is closed, "
                   "and the build follows its upload.")
    if v["waiting_text"]:
        output.out(v["waiting_text"].rstrip(".") + ".")
    inst = v["installed"]
    output.out(f"Installed on the PC: the build of {_stamp_when(inst['stamp'])}, written {_when(inst.get('at'))}."
               if inst else "Installed on the PC: nothing yet.")
    pc = v["pc"]
    if pc:
        output.out(f"Slicer Sync: last reported {_when(pc['last_upload'])}." if pc.get("last_upload")
                   else "Slicer Sync: set up, nothing reported yet.")
    else:
        output.out_lines(output.status_row("needs a look", "Slicer Sync: not set up.",
                                           "sudo spoolwarden pair --slicer-sync"))
    up = v["updates"]
    accepted = f" {_plural(up['accepted'], 'update')} accepted; the Slicer Sync writes them next." if up["accepted"] else ""
    output.out((f"Updates: {up['count']} on {_plural(up['lines'], 'line')}." if up["count"] else "Updates: none.")
               + " Presets already in your slicers are never replaced unless you accept them." + accepted)
    if up["count"] > up["accepted"]:
        output.out("See them: " + "sudo spoolwarden presets updates")
    if up["yours"]:
        output.out(f"{_plural(up['yours'], 'generated preset')} differ from your own preset of the same name in Bambu "
                   "Studio's filament folder; yours stay (rename or delete yours to get ours).")
    for name in v["stale"]:
        output.out(f"Delete in Bambu Studio: {name}")
    for name in v["orca_stale"]:
        output.out(f"Delete in Orca Slicer: {name}")
    for prob in v["problems"]:
        output.out_lines(output.status_row("needs a look", prob))
    return 0


def _parents_text(line: dict) -> str:
    sep = output.sym("sep")
    one = lambda app, name, src: f"{app} {name} ({src})" if name else f"{app} none"      # noqa: E731
    return "parents: " + sep.join((one("Bambu Studio", line["bambu_parent"], line["parent_source"]),
                                   one("Orca Slicer", line["orca_parent"], line["orca_parent_source"])))


def cmd_profiles_lines() -> int:
    """`presets lines`: the Hub page's lines, each with its parents and filaments under it."""
    if not _presets_on():
        return 1
    from . import profiles_api
    try:
        ls = lines_mod.load()
    except lines_mod.LineStoreError as e:
        output.error(e.message)
        return 1
    counts = profiles_api._preset_counts()
    views = [profiles_api._line_view(line, counts) for _k, line in sorted(ls.items())]
    output.emit({"lines": views})
    if not views:
        output.out("No lines yet. They are made from the Spoolman filaments at the next build or addition.")
        return 0
    details = [[_parents_text(w), "filaments: " + (", ".join(str(i) for i in w["spoolman_ids"]) or "none")]
               for w in views]
    lines = output.table(["ID", "Line", "Material", "Presets"],
                         [[w["line_id"], f"{w['vendor']} {w['product']}".strip(), w["material"], w["presets"]]
                          for w in views], long=1, right=(3,))
    dim = lambda d: [output.paint(ln, "muted", sys.stdout) for ln in output.wrap(d, indent=4, first=2)]    # noqa: E731
    if len(lines) == len(views) + 1:                    # a table: the details go under their rows
        shown = [lines[0]]
        for row, det in zip(lines[1:], details):
            shown += [row] + [ln for d in det for ln in dim(d)]
    else:                                               # blocks (plain, narrow): after each block's fields
        shown, per, i = [], 4, 0
        for n, det in enumerate(details):
            shown += ([""] if n else []) + lines[i:i + per] + [ln for d in det for ln in output.wrap(d, indent=4, first=2)]
            i += per + 1
    output.out_lines(shown)
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
    if not _presets_on():
        return 1
    from .setup_console import presets_tab
    try:
        ls = lines_mod.load()
        material = ls[line_id].material if line_id in ls else ""
        synced = presets_tab._parents(material, "orca" if orca else "bambu")["synced"]     # what the Hub's dialog reads
    except lines_mod.LineStoreError as e:
        output.error(e.message)
        return 1
    if line_id in ls and not synced:
        output.error("the Slicer Sync has not reported any parents yet. It reports them when it runs.")
        return 1
    try:
        line = set_parent_checked(line_id, parent, orca)
    except (ValueError, ProfileError) as e:
        output.error(str(e))
        return 1
    except KeyError:
        output.error(f"there is no line {line_id}.", "use an ID from:", cmd="sudo spoolwarden presets lines")
        return output.USAGE
    except lines_mod.LineStoreError as e:
        output.error(e.message)
        return 1
    target = "orca" if orca else "bambu"
    _hub_audit(f"Slicer preset line {line.line_id}: {target} parent set")
    output.emit({"ok": True, "line": line.line_id, "target": target,
                 "parent": line.orca_parent if orca else line.bambu_parent})
    output.result("Saved. A build was asked for.")
    return 0


def _line_names() -> dict[str, str]:
    try:
        return {k: f"{ln.vendor} {ln.product}".strip() for k, ln in lines_mod.load().items()}
    except lines_mod.LineStoreError:
        return {}


def _update_lines(chosen: list[dict]) -> list[str]:
    names = _line_names()
    out = []
    for u in chosen:
        app = "Orca Slicer" if u["target"] == "orca" else "Bambu Studio"
        keys = ", ".join(u["keys"][:6]) + (", ..." if len(u["keys"]) > 6 else "")
        where = f" (in your file {u['file']})" if u.get("file") else ""
        out.append(f"{names.get(u['line_id'], u['line_id'])}  {app}: {u['name']}{where}: {keys}")
    return out


def cmd_profiles_updates(line_id: str | None, accept: bool = False, yes: bool = False) -> int:
    """`presets updates` lists what would be accepted and changes nothing; `presets accept-updates` lists the same,
    asks, and accepts exactly what it listed: the next Slicer Sync writes them over the presets in the slicers (after
    its backup); nothing else ever writes over an existing preset."""
    if line_id is not None and not line_id.strip():
        output.error("--line needs a line ID.", "see the IDs:", cmd="sudo spoolwarden presets lines")
        return 2
    if not _presets_on():
        return 1
    try:
        r = builds.apply_updates(line_id=line_id, all_=line_id is None, dry_run=True)    # what would be accepted
    except ValueError as e:
        output.error(str(e))
        return 1
    chosen = r["chosen"]
    if r["stamp"] is None or not chosen:
        if line_id and r["stamp"] is not None:
            output.error(f"there are no updates for line {line_id}.", "see them with:",
                         cmd="sudo spoolwarden presets updates")
            return 1
        output.emit({"ok": True, "dry_run": not accept, "stamp": r["stamp"], "chosen": [], "count": 0, "updates": []})
        output.out("No updates to accept." if r["stamp"] is not None else "No build yet, so there are no updates to accept.")
        return 0
    if accept and not yes and not output.terminal():     # nothing is listed or accepted when nobody can answer
        return output.no_terminal("accepting the updates", _sudo_command("sudo spoolwarden presets accept-updates") + " --yes")
    with output.shown() if not accept or not yes else contextlib.nullcontext():    # asked-for data, or what the question is about
        for text in _update_lines(chosen):
            output.out(text)
    n = len(chosen)
    shown = [{"line_id": u["line_id"], "target": u["target"], "name": u["name"], "file": u.get("file"),
              "keys": u["keys"]} for u in chosen]
    if not accept:
        output.emit({"ok": True, "dry_run": True, "stamp": r["stamp"], "chosen": shown, "count": n, "updates": chosen})
        output.out(f"{_plural(n, 'update')} would be accepted; nothing was changed.")
        return 0
    stop = _confirm(f"Accept {'this update' if n == 1 else f'these {n} updates'}? The Slicer Sync writes "
                    f"{'it' if n == 1 else 'them'} at its next run, after its backup.", "accepting the updates", yes=yes)
    if stop is not None:
        return stop
    try:        # exactly what was shown: a build that landed while the question was open is accepted unseen by no one
        builds.apply_updates(line_id=line_id, all_=line_id is None, dry_run=False, only={u["name"] for u in chosen},
                             expect_stamp=r["stamp"])
    except builds.UpdatesChanged:
        output.error("the updates changed since this list.", "run it again to see them.")
        return 1
    except ValueError as e:
        output.error(str(e))
        return 1
    _hub_audit(f"{n} Slicer preset updates accepted")
    output.emit({"ok": True, "dry_run": False, "stamp": r["stamp"], "chosen": shown, "count": n, "updates": chosen})
    output.result(f"{_plural(n, 'update')} accepted; the Slicer Sync writes them at its next run, after its backup.")
    return 0


def cmd_profiles_restore_deleted() -> int:
    if not _presets_on():
        return 1
    builds.restore_deleted_next()
    _request_rebuild("restore Slicer presets deleted in Bambu Studio")
    _hub_audit("Slicer presets deleted in Bambu Studio: restore requested")
    output.emit({"ok": True})
    output.result("The next build brings back the presets deleted in Bambu Studio. A build was asked for.")
    return 0


# ---------- modules ----------

def cmd_modules_units() -> int:
    """Every unit of every module, with companion services (uninstall.sh reads this)."""
    units = [u for mod in modules.MODULES.values() for unit in mod.units for u in apply._unit_files(unit)]
    output.emit({"units": units})
    for u in units:
        print(u)
    return 0


def _require_root() -> bool:
    """False (with the error and its Fix line) when not root; checked before anything is saved. The caller returns
    `output.NEEDS_SUDO`."""
    if not _no_systemd() and hasattr(os, "geteuid") and os.geteuid() != 0:
        output.need_sudo(_sudo_command("sudo spoolwarden modules <command>"))
        return False
    return True


def _run_apply(*, pairing: bool = True) -> int:
    """Plan, execute and finish for the saved config. `pairing` shows the QR code at the end."""
    if not _require_root():
        return output.NEEDS_SUDO
    cfg = config.load()
    try:
        actions = apply.plan(cfg)
    except modules.ModuleError as e:
        _err_line(str(e))
        return 1
    on = modules.enabled(cfg)
    print(f"Setup: {_SETUP_WORDS[modules.mode_of(on)]} ({_titles(n for n in modules.MODULES if n in on)}).")
    for a in actions:
        if a.kind == "install_file" and a.arg[0] == apply.DROPIN:
            allow = next(ln for ln in a.arg[1].splitlines() if ln.startswith("IPAddressAllow="))
            print(f"Weigh Station answers at: {allow.split('=', 1)[1]}")
    job = steps.Steps(len(apply.step_names(actions)) + 1)
    try:
        with output.wait("Applying the changes…", programs=True):
            apply.execute(actions, step=job.next)
    except apply.ApplyError:
        return 1
    job.next("Checking that everything answers")
    try:
        apply.finish(cfg, pairing=pairing)
    except apply.ApplyError as e:
        _err_line(str(e))
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
                   server: str | None = None, notes: list[str] | None = None, show_plan=None) -> str | None:
    """Turn `name` on/off in `cfg` (in place). Returns an error text, or None when changed.

    `confirm(text) -> bool` is asked, one question for each of them, before dependents go off, or needs go on, too
    (None: refuse). `show_plan(before, after)` is called once they are answered, before any setting is asked.
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
            for m in missing:
                who = next((n for n in (name, *missing) if m in modules.MODULES[n].depends), name)
                if confirm is None or not confirm(f"Also turn on {modules.MODULES[m].title}? "
                                                  f"{modules.MODULES[who].title} needs it."):
                    return f"{name} needs {listed}\nfix: enable {listed} first"
            on |= set(missing)
            said = modules.change_note(name, True, missing)
        on.add(name)
    else:
        deps = modules.dependents_closure(name, on)     # not only the direct ones: the rest would refuse after the yes
        if deps:
            listed = ", ".join(deps)
            for d in deps:
                parent = next((n for n in (name, *deps) if n in modules.MODULES[d].depends), name)
                if confirm is None or not confirm(f"Also turn off {modules.MODULES[d].title}? "
                                                  f"It needs {modules.MODULES[parent].title}."):
                    # the list is parents first; the fix has to go children first, or each step refuses
                    return f"{listed} depend on {name}\nfix: disable {', '.join(reversed(deps))} first"
            on -= set(deps)
            said = modules.change_note(name, False, deps)
        on.discard(name)
    new = _with_modules(cfg, on)
    if not {"server", "station"} <= on:
        modules.drop_local_station_link(new)
    if show_plan is not None:
        show_plan(modules.enabled(cfg), frozenset(on))
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


# The Features' keys (06 9.6, in the order of that table) and the old module names they stand for. The old names stay
# accepted everywhere a key is, and are what the code and the stored settings use.
_FEATURE_KEYS = {"spoolman": "spoolman", "hub": "server", "label-reader": "ai_intake",
                 "label-reader-local": "local_intake", "printers": "printers", "klipper": "klipper",
                 "presets": "presets", "catalog": "library", "backups": "backup", "weigh-station": "station",
                 "web": "web", "remote": "remote", "orders": "orders", "updates": "updates"}
_KEY_OF = {old: new for new, old in _FEATURE_KEYS.items()}
# What a feature needs besides other features, as the table shows it (the registry's longer sentence is for the checklist).
_NEEDS_SHOWN = {"server": ["Spoolman"], "ai_intake": ["API key"]}


def _feature_named(arg: str) -> str | None:
    """The module a Feature key (or its old name, or its title) names, ignoring case; None after the Error (exit 2)."""
    a = arg.strip().lower()
    for name, mod in modules.MODULES.items():
        if a in (name, _KEY_OF[name], mod.title.lower()):
            return name
    output.error(f'"{arg}" is not a Feature.', "use a key from the KEY column of:", cmd="sudo spoolwarden features")
    return None


def _feature_needs(name: str) -> str:
    return ", ".join([modules.MODULES[d].title for d in modules.MODULES[name].depends] + _NEEDS_SHOWN.get(name, []))


def cmd_modules_list() -> int:
    """`features` (06 9.6): the setup and every Feature, as the Hub page's Features collection lists them."""
    on = modules.enabled(config.load())
    output.emit({"modules": [{"name": n, "key": _KEY_OF[n], "title": m.title, "description": m.description,
                              "needs": modules.needs_of(n), "optional_ai": m.optional_ai, "on": n in on}
                             for n, m in modules.MODULES.items()],
                 "setup": modules.mode_of(on)})
    mode = modules.mode_of(on)
    output.out(f"Setup: {_SETUP_SENTENCE.get(mode, 'custom')}")
    output.out()
    names = [_FEATURE_KEYS[k] for k in _FEATURE_KEYS]
    word = lambda n: "on" if n in on else "off"                                                       # noqa: E731
    lines = output.table(["Feature", "Key", "State", "Needs"],
                         [[modules.MODULES[n].title, _KEY_OF[n], _bare(output.state(word(n))), _feature_needs(n)]
                          for n in names], long=3)
    if len(lines) == len(names) + 1:        # a table, not blocks: the colour goes on after the layout is made
        for i, n in enumerate(names, 1):
            had = _bare(output.state(word(n)))
            cut = lines[i].find(had)
            if cut >= 0:
                lines[i] = lines[i][:cut] + output.state(word(n)) + lines[i][cut + len(had):]
    output.out_lines(lines)
    ai = [modules.MODULES[n].title for n in names if modules.MODULES[n].optional_ai]
    output.out()
    output.out(f"Uses AI: {', '.join(ai)}.")
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
        _err_line(f"{err}\nNothing was changed.")
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


def _features_report(cfg: dict, before, explicit, notes=(), *, plan_shown: bool = False) -> int:
    """`features on|off|setup` after its questions (06 9.6): the plan, the apply, then `Features applied: …` or
    `Unchanged.`"""
    after = modules.enabled(cfg)
    plan, short = _feature_plan(before, after, explicit)
    if short and not plan_shown:
        output.out(plan)
    rc = _save_and_apply(cfg, notes)
    if rc == 0:
        output.emit({"ok": True, "changed": bool(short),
                     "on": [_KEY_OF[n] for n in modules.MODULES if n in after and n not in before],
                     "off": [_KEY_OF[n] for n in modules.MODULES if n in before and n not in after]})
        output.result(f"Features applied: {short}." if short else "Unchanged.")
    return rc


def cmd_modules_set(mode: str, server: str | None = None) -> int:
    """`features setup <setup>`: `Setup: Weigh Station only.`, the plan and the apply. The Weigh Station only setup
    needs the Hub's address: `--hub`, or asked at a terminal."""
    mode = modules.canonical_mode(mode)
    if not _require_root():
        return output.NEEDS_SUDO
    try:
        before_cfg = config.load()
        before = modules.enabled(before_cfg)
        if mode == "station" and not server and _server_addr_missing(before_cfg) and (
                output.json_mode() or not apply._tty()):     # before any output or change: nobody can be asked
            output.error("the Weigh Station only setup needs the Hub's address, and there is no terminal to ask.",
                         "give it with --hub:", cmd=_sudo_command("sudo spoolwarden features setup weigh-station")
                         + " --hub <address>")
            return output.USAGE
        output.out(f"Setup: {_SETUP_SENTENCE[mode]}.")
        cfg = modules.set_mode(before_cfg, mode)
        if server:
            err = _server_addr_error(server)
            if err:
                raise modules.ModuleError(err)
            if mode == "station":
                cfg["station"]["allow"] = [server]
        elif mode == "station" and _server_addr_missing(cfg):
            addr = _ask_station_server()
            if addr is None:
                output.error("the Weigh Station only setup needs the Hub's address; nothing was changed.")
                return 1
            cfg["station"]["allow"] = [addr]
        modules.validate(cfg)
    except modules.ModuleError as e:
        _err_line(str(e))
        return 1
    return _features_report(cfg, before, set(modules.enabled(cfg)) ^ set(before))


def cmd_modules_toggle(name: str, want_on: bool, server: str | None = None, yes: bool = False) -> int:
    """`features on|off <feature>` (06 9.6): the `Also turn on|off …?` questions, one for each other Feature, then the
    plan, the setting prompts, the apply and `Features applied: …`."""
    if not _require_root():
        return output.NEEDS_SUDO
    named = _feature_named(name)
    if named is None:
        return output.USAGE
    name = named
    cfg = config.load()
    if server:
        err = _server_addr_error(server)
        if err:
            _err_line(err)
            return 1
    before = modules.enabled(cfg)
    notes: list[str] = []
    tty = apply._tty() and not output.json_mode()         # --json never asks
    asked: list[str] = []
    declined: list[str] = []
    unset: list[str] = []                                   # --json: the settings a question would have asked for
    planned = [False]

    def _cascade(text: str) -> bool:
        """--yes answers it; --json and a missing terminal stop the command; at a terminal the person answers."""
        if yes:
            return True
        if not tty:
            asked.append(text)          # every question is collected, so the Error names all of them; nothing is saved
            return True
        if _tty_confirm(text + " [y/N] "):
            return True
        declined.append(text)
        return False

    def _json_settings(new_cfg: dict, on) -> None:
        also = ("spoolman_url",) if modules.needs_spoolman_url(on, new_cfg) else ()
        unset.extend(k for k in [*modules.missing_settings(on, new_cfg), *also] if k != "station.allow")

    def _json_address() -> None:
        unset.append("station.allow")

    def _show_plan(old, new) -> None:
        if asked:                       # nothing will be applied: no plan to show
            return
        planned[0] = True
        plan, short = _feature_plan(old, new, {name})
        if short:
            output.out(plan)

    json_ = output.json_mode()
    err = _change_module(cfg, name, want_on, confirm=_cascade, server=server, notes=notes, show_plan=_show_plan,
                         ask_address=_json_address if json_ else _ask_station_server if tty else None,
                         ask_settings=_json_settings if json_ else _ask_module_settings if tty else None)
    if asked:
        also = modules.needs_closure([name], before) if want_on else modules.dependents_closure(name, before)
        output.error(f"turning {modules.MODULES[name].title} {'on' if want_on else 'off'} also turns "
                     f"{'on' if want_on else 'off'} {_and_list([modules.MODULES[n].title for n in also])}, which needs "
                     "a yes, and there is no terminal to ask.",
                     "add --yes to accept the cascade, or switch the others first.")
        return output.USAGE
    if declined:
        output.result("Nothing changed.")
        return output.CANCELLED
    if unset:
        key = unset[0]
        if key == "station.allow":
            output.error("Weigh Station needs the Hub's address, and there is no terminal to ask.",
                         "give it with --hub:", cmd=_sudo_command(f"sudo spoolwarden features on {_KEY_OF[name]}")
                         + " --hub <address>")
        elif key in _set_keys():
            output.error(f"{modules.MODULES[name].title} needs {key}, and there is no terminal to ask.",
                         "set it first, then run this again:", cmd=f"sudo spoolwarden config set {key} <value>")
        else:
            output.error(f"{modules.MODULES[name].title} needs {key}, and there is no terminal to ask.",
                         "run it again at a terminal without --json to answer it:",
                         cmd=_sudo_command(f"sudo spoolwarden features {'on' if want_on else 'off'} {_KEY_OF[name]}")
                         .replace(" --json", ""))
        return output.USAGE
    if err:
        _err_line(err)
        return 1
    return _features_report(cfg, before, {name}, plan_shown=planned[0])


def _ask_module_settings(cfg: dict, on) -> str | None:
    """`features on NAME` at a terminal: ask for the settings the new set `on` needs (web.public_url, orders.file, a
    remote Spoolman's address), with the checklist's prompts (8.5), into cfg (in place). The Hub's address for a
    Weigh Station alone is asked before (--hub and _change_module see to it). Returns an error text or None."""
    got, owner = _ask_feature_settings(on, cfg)
    if got is None:
        return f"{owner} needs that setting; nothing was changed."
    for key, value in got.items():
        modules.set_setting(cfg, key, value)
    return None


def _ask_station_server() -> str | None:
    """The Hub's address for a Weigh Station that has no Hub on this machine (8.5); an empty answer cancels."""
    return _ask_setting("station.allow", "station")


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


def _config_has_content() -> bool:
    """False for a first install: no config file, or one with nothing in it (as set_mode counts it)."""
    f = config.paths().etc / "config.json"
    try:
        return bool(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


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


def _confirm_update(cfg: dict, *, rollback: bool, yes: bool) -> int | None:
    """06 7 for `update` and `update --rollback`: asked once there is something to install, with its version. Nobody
    to ask (no terminal, no --yes) stops only then: without root, with an up-to-date kit, no kept version or a release
    that cannot be read the command says so itself, as it does at a terminal."""
    from . import release, updates
    if yes:
        return None
    if not _no_systemd() and not _is_root():
        return None
    if rollback:
        target = updates._read_state().get("previous")
        if not isinstance(target, str) or not updates._kept(target):
            return None
        return _confirm(f"Roll back to {target}? Spoolwarden stops while it installs and starts again by itself. "
                        "Settings and data stay.", "rolling back", yes=False)
    try:
        info = updates.check_info(cfg)
    except release.ReleaseError:
        return None
    if not info["newer"]:
        return None
    return _confirm(f"Update to {info['latest']}? Spoolwarden stops while it installs and starts again by itself. "
                    "Settings and data stay. The version before is kept, so you can roll back.", "updating", yes=False)


def _run_removal(cmd: list[str], stdin_file: Path | None) -> tuple[int, str]:
    """Run the removal script, its lines dim and indented below the wait line as they arrive (06 6.6, 9.13); (its exit
    code, its last non-empty line)."""
    last = ""
    with output.wait("Removing the kit…", programs=True):
        stdin = open(stdin_file) if stdin_file else subprocess.DEVNULL
        try:
            proc = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    errors="replace")
        finally:
            if stdin_file:
                stdin.close()
        for line in proc.stdout:
            line = line.rstrip()
            if line.strip():
                last = line.strip()
                output.out_lines(["    " + output.paint(line, "muted", sys.stdout)])
        return proc.wait(), last


def cmd_uninstall(purge: bool, run=None, yes: bool = False) -> int:
    """`uninstall [--purge]` (06 9.13): run uninstall.sh of the kept release (/opt/filament-kit/releases/<version>/),
    unpacked outside /opt, which it removes. The question and, for --purge, the typed word are asked here (06 7);
    uninstall.sh asks its own for `./uninstall.sh --purge` too, which this answers with the word it was just given."""
    from . import release, updates
    if not _no_systemd() and not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden uninstall"))
    kept = _kept_release()
    if kept is None:
        ver = updates.current_version()
        output.error("no copy of a release is kept, so there is no removal script to run.",
                     f"download filament-kit-{ver}.tar.gz from the releases page, unpack it, then in its folder run:",
                     cmd="sudo ./uninstall.sh" + (" --purge" if purge else ""))
        return 1
    if purge:
        stop = _confirm("This also deletes everything Spoolwarden keeps on this machine. Type purge to go on: ",
                        "removing Spoolwarden and deleting everything it keeps", yes=yes, word="purge")
    else:
        stop = _confirm("Remove Spoolwarden from this machine? Its data stays unless you add --purge.",
                        "removing filament-kit", yes=yes)
    if stop is not None:
        return stop
    ver, tarball = kept
    running = updates.current_version()
    if ver != running:
        output.note(f"using the removal script of {ver}, the newest kept release; no copy of {running} is kept.")
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="filament-kit-uninstall-"))
    try:
        root = release.extract(tarball, ver, work)
        cmd = ["bash", str(root / "uninstall.sh")] + (["--purge"] if purge else [])
        if run is not None:
            rc, last = run(cmd), ""
        else:
            kept_word = None
            if purge:
                kept_word = work / "purge-answer"       # uninstall.sh's own typed word, answered from here
                kept_word.write_text("purge\n")
            rc, last = _run_removal(cmd, kept_word)
    except (release.ReleaseError, OSError) as e:
        _err_line(f"cannot unpack the kept release {ver}: {e}")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if rc != 0:
        output.out_lines(output.status_row("failed", f"The removal stopped: {last.rstrip('.') or f'exit code {rc}'}."))
        return rc if run is not None else output.FAILED
    output.out("filament-kit is removed from this machine.")
    return 0


def _port_hint(who) -> str:
    name = who.name if who else "you"
    return (f". If it could not open the serial port: {name} must be in the dialout group "
            f"(sudo usermod -aG dialout {name if who else '$USER'}, then log in again)")


class _StationBusy(Exception):
    """filament-kit-station.service could not be stopped, so it may still hold the serial ports."""


@contextlib.contextmanager
def _station_stopped(run=subprocess.run):
    """filament-kit-station.service stopped for the block (it holds the panel's and the reader's serial ports), and
    started again after it, even on an error or Ctrl-C. Raises _StationBusy when the stop fails, as `station
    flash-panel` refuses; without root it says it cannot stop the service and goes on (the owner still confirms the
    board). Does nothing without systemd or systemctl."""
    service = "filament-kit-station.service"
    if _no_systemd():
        yield
        return
    if not _is_root():
        output.note(f"not root, so {service} (if it runs) is not stopped and may hold the board's port; run with "
                    "sudo for a reliable check.")
        yield
        return
    try:
        was_active = run(["systemctl", "is-active", service], check=False, timeout=15).returncode == 0
    except FileNotFoundError:  # no systemctl: no service holding a port
        yield
        return
    except (OSError, subprocess.SubprocessError) as e:
        raise _StationBusy(f"could not ask systemd about {service} ({e}). Nothing was flashed.")
    try:
        try:
            stopped = run(["systemctl", "stop", service], check=False, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            raise _StationBusy(f"could not stop {service} ({e}). Nothing was flashed.")
        if stopped.returncode not in (0, 5):  # 5: the unit isn't loaded (no service to stop)
            raise _StationBusy(f"could not stop {service} (systemctl exit {stopped.returncode}); it may hold the "
                               "board's port. Nothing was flashed.")
        yield
    finally:
        if was_active:  # only restart what was running
            try:
                run(["systemctl", "start", service], check=False, timeout=60)
            except (OSError, subprocess.SubprocessError) as e:
                output.note(f"could not start {service} again: {e}")


def _answers_as_panel(port: str) -> bool:
    """True when the board on port says HELLO as the intake panel (a few seconds); false if it doesn't or can't be asked."""
    try:
        from .station import panel
        ser = panel.open_panel(port)
    except Exception:  # no pyserial (the [station] extra), or no such port: nothing to say it is the panel
        return False
    if ser:
        ser.close()
    return ser is not None


@contextlib.contextmanager
def _service_paused(run):
    """The station service stopped for the block when it runs, as `reader setup`'s write does it, and started again."""
    service = "filament-kit-station.service"
    was_active = run(["systemctl", "is-active", service], check=False, capture_output=True).returncode == 0
    if was_active:
        run(["systemctl", "stop", service], check=False, capture_output=True)
    try:
        yield
    finally:
        if was_active:
            run(["systemctl", "start", service], check=False, capture_output=True)


def _refuse_panel_board(port: str, explicit: bool, found, run=None) -> int | None:
    """The board on port is asked for its HELLO (the station stopped meanwhile) before anything is asked or made: None
    when it is no panel, else the exit code. The station's button panel is an ESP32-C3 too, and with the reader
    unplugged it is the lone board (FA-040); a named --port gets the same check as a found board."""
    try:
        with (_service_paused(run) if run else _station_stopped()):    # the service would hold the port, a probe resets it
            is_panel = _answers_as_panel(port)
    except _StationBusy as e:
        _err_line(str(e))
        return 1
    if not is_panel:
        return None
    said = f"{port} answers as the intake station's button panel, not a reader; nothing was written."
    if explicit:
        others = [r.port for r in found if r.port != port]
        output.error(said, ("use one of: " + ", ".join(others) + ".") if others else
                     "plug the reader into this PC with a data cable (a charge-only cable shows nothing).")
        return output.USAGE
    _err_line(said + " Plug the reader in, or name its port with --port.")
    return 1


def _wifi_password(a, ask_secret) -> str | None:
    """The reader's Wi-Fi password (06 8.7): `--password -` reads one line of standard input, else it is asked twice,
    hidden. None after the error (nothing was changed)."""
    if getattr(a, "password", None) == "-":
        try:
            return sys.stdin.readline().rstrip("\r\n")      # only the line ending: spaces can be part of a password
        except (OSError, ValueError):
            return ""
    password = ask_secret("Its Wi-Fi password: ")
    if ask_secret("The password again: ") != password:
        _err_line("the two passwords differ; nothing was changed")
        return None
    return password


def _ask_choice(ask, prompt: str, choices: dict[str, str], default: str) -> str | None:
    """One of `choices` (answer -> value) from the owner; the default on an empty answer; None when it can't ask."""
    for _ in range(3):
        try:
            got = ask(prompt).strip().lower()
        except (EOFError, RuntimeError, OSError):
            return None
        if not got:
            return default
        if got in choices:
            return choices[got]
        print("Please answer " + " or ".join(sorted(choices)) + ".")
    return None


def _reader_setup_usb(a, ask, ask_secret, run=subprocess.run) -> int:
    """`reader setup` with nothing to build: the Printer Station plugged into this server's USB port gets the kit's own
    firmware (no PlatformIO) and then its settings over USB (reader_flash.py). The owner answers the Wi-Fi name and
    password and the buzzer's trigger; the rest is found or made here. Nothing secret is printed."""
    from . import reader_flash as rf
    from . import reader_setup as rs
    from . import reader_tokens
    if not a.token_file and not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden reader setup"))
    answers = None
    if getattr(a, "pending", False):        # the setup page's job: the answers it was given, nothing asked
        answers = rf.take_pending()
        if answers is None:
            _err_line("no answers from the setup page (or they were older than 15 minutes); start it again "
                      "there")
            return 1
        a.ssid, a.port = str(answers.get("ssid") or ""), answers.get("port") or a.port
        a.buzzer, a.name = answers.get("buzzer") or "high", answers.get("name") or a.name
        typed = str(answers.get("pass") or "")
        ask_secret = lambda _prompt: typed  # noqa: E731
    if rf.bundled_image() is None:
        _err_line("this kit has no Printer Station firmware bundled (reader/firmware); update the kit, or build "
                  "one yourself with --source <checkout>/reader")
        return 1
    job = steps.Steps(5)
    job.next("Finding the board")
    found = rs.find_readers()
    yes = bool(getattr(a, "yes", False))
    explicit = a.port is not None
    if explicit:
        port = _port_check(a.port, [(r.port, r.by_id or r.port) for r in found], "reader setup would write")
        if port is None:
            return output.USAGE
    elif not found:
        _err_line("no ESP32 board on this server's USB. Plug the reader in with a data cable (a "
                  "charge-only cable shows nothing), or name the port with --port.")
        return 1
    elif len(found) == 1:
        port = found[0].port
        print(f"Found an ESP32 board on {found[0].by_id or port}.")
    elif answers is not None:
        _err_line("there are several ESP32 boards on this server's USB: pick the Printer Station's port on the "
                  "setup page; nothing was changed")
        return 1
    elif yes:       # --yes answers for one named board, never for a pick among several (06 7)
        output.error("there are several ESP32 boards on this server's USB: " + ", ".join(r.port for r in found)
                     + "; nothing was written.", "name the reader's board with --port, for example --port "
                     + found[0].port + ".")
        return output.USAGE
    else:
        for i, r in enumerate(found, 1):
            print(f"  {i}. {r.by_id or r.port} ({r.product})")
        pick = _ask_choice(ask, "Which one is the reader? [number] ",
                           {str(i): r.port for i, r in enumerate(found, 1)}, "")
        if not pick:
            _err_line("no board picked; nothing was changed")
            return 1
        port = pick
    refused = _refuse_panel_board(port, explicit, found, run)       # before any question or token
    if refused is not None:
        return refused
    try:
        base = a.base.rstrip("/") if a.base else rs.reader_base(config.load())
        if not base.startswith("https://"):
            raise rs.SetupError("--base must be the kit's public https address plus /reader")
        key_pem, real_key = rs.pubkey(Path(a.ota_pubkey).read_text(encoding="utf-8") if a.ota_pubkey else None)
        token = Path(a.token_file).read_text(encoding="utf-8").strip() if a.token_file else None
    except (rs.SetupError, OSError) as e:
        _err_line(str(e))
        return 1
    try:
        ssid = a.ssid or ask("Wi-Fi name the reader joins: ").strip()
    except (EOFError, RuntimeError, OSError):
        _err_line("reader setup needs a terminal to ask you; nothing was changed")
        return 1
    password = _wifi_password(a, ask_secret)
    if password is None:
        return 1
    buzzer = a.buzzer or _ask_choice(
        ask, "Its buzzer: [h]igh-triggered (behind a MOSFET, as in the parts list) or [l]ow-triggered (the older "
             "3-pin module)? [h] ", {"h": "high", "high": "high", "l": "low", "low": "low"}, "high")
    if buzzer is None:
        _err_line("no answer for the buzzer; nothing was changed")
        return 1
    try:
        rs.secrets_h(ssid, password, base, token or "x" * 43, key_pem)      # the same checks as a build's
    except rs.SetupError as e:
        _err_line(f"{e}; nothing was changed")
        return 1
    if not getattr(a, "pending", False):     # the setup page's job was asked there: it has no terminal
        if not yes and ask is input and not output.terminal():      # nobody to ask: nothing is written
            return output.no_terminal("writing the firmware", _sudo_command("sudo spoolwarden reader setup") + " --yes")
        try:
            stop = _confirm(f"Write the reader firmware to {port}? What is on the board now is replaced.",
                            "writing the firmware", yes=yes, ask=None if ask is input else ask)
        except KeyboardInterrupt:
            output.result("\nNothing was flashed.")
            return 1
        if stop is not None:
            return stop
    tid = None
    if token is None:
        try:
            tid, token = reader_tokens.TokenStore().issue(a.name or "printer-station")
        except reader_tokens.TokenFileError as e:
            _err_line(f"{e}; nothing was changed")
            return 1
    settings = {"ssid": ssid, "pass": password, "base": base, "token": token, "buzzer_low": buzzer == "low"}
    if real_key:
        settings["ota_key"] = key_pem
    service = "filament-kit-station.service"      # its panel watcher also opens ESP32 boards: off while we work
    was_active = run(["systemctl", "is-active", service], check=False, capture_output=True).returncode == 0
    if was_active:
        run(["systemctl", "stop", service], check=False, capture_output=True)
    try:
        result = rf.setup(port, settings, reflash=bool(getattr(a, "reflash", False)), run=run, step=job.next)
    finally:
        if was_active:
            run(["systemctl", "start", service], check=False, capture_output=True)
    if not result.ok:
        if tid:
            reader_tokens.TokenStore().revoke(tid)
        _err_line(f"{result.message}" + ("; the new token was removed" if tid else ""))
        return 1
    print(result.message)
    if tid:
        output.out(f"Reader token {tid} ({a.name or 'printer-station'}). Remove it later with: "
                   + f"sudo spoolwarden reader revoke {tid}")
    print(f"Buzzer: {buzzer}-triggered. Unplug it from the server and power it where it lives; it keeps its settings.")
    if not real_key:
        print("Note: without --ota-pubkey it refuses updates over Wi-Fi; running this again with the board plugged in "
              "here updates it.")
    return 0


def cmd_reader_setup(a, ask=input, ask_secret=None) -> int:
    """`reader setup`: with nothing else said, the Printer Station on this server's USB gets the kit's firmware and its
    settings (_reader_setup_usb). --source builds the firmware here with PlatformIO and the settings compiled in;
    --out writes that secrets.h for a build elsewhere; --secrets flashes one written earlier. Makes a token (root,
    unless --token-file). Nothing secret is printed."""
    from . import reader_setup as rs
    from . import reader_tokens
    ask_secret = ask_secret or secret_input.ask
    if not (a.source or a.out or getattr(a, "secrets", None)):
        return _reader_setup_usb(a, ask, ask_secret)
    flashing = bool(a.source)
    low = getattr(a, "buzzer", "high") == "low"
    who = rs.owner()            # under sudo: PlatformIO is looked for, and run, as the user who ran sudo
    pio = rs.find_pio(who) if flashing else None
    if flashing and pio is None:
        whose = f"{who.name}'s" if who else "your"
        _err_line(f"PlatformIO is not installed in {whose} account (no pio in ~/.platformio/penv/bin or "
                  "~/.local/bin, nor in /usr/local/bin or /usr/bin). Install it as that user, not with sudo: "
                  + "python3 -m pip install --user platformio. Or leave out --source, use --out, "
                  "and build on a PC that has it (reader/README.md).")
        return 1
    if flashing and not rs.is_source(Path(a.source)):
        _err_line(f"{a.source} is not the reader's source folder (a checkout's reader/, with platformio.ini)")
        return 1
    if a.secrets and not flashing:
        _err_line("--secrets flashes a secrets.h made earlier, so it needs --source")
        return 1
    port = None
    if flashing:
        found = rs.find_readers()
        explicit = a.port is not None
        if explicit:
            port = _port_check(a.port, [(r.port, r.by_id or r.port) for r in found], "reader setup would write")
            if port is None:
                return output.USAGE
        elif len(found) == 1:
            port = found[0].port
        elif not found:
            _err_line("no ESP32 board on USB here. Plug the reader in with a data cable (a charge-only cable "
                      "shows nothing), or name the port with --port.")
            return 1
        else:
            output.error("there are several ESP32 boards on USB: " + ", ".join(r.port for r in found)
                         + "; nothing was written.", "name the reader's board with --port, for example --port "
                         + found[0].port + ".")
            return output.USAGE
        refused = _refuse_panel_board(port, explicit, found)        # a named port too, before any question or token
        if refused is not None:
            return refused
        shown = next((r for r in found if r.port == port), None)
        yes = bool(getattr(a, "yes", False))        # --port names the board; it never answers the question
        if not yes and ask is input and not output.terminal():      # nobody to ask: nothing is written
            return output.no_terminal("writing the firmware", _sudo_command("sudo spoolwarden reader setup") + " --yes")
        if not explicit and shown:
            print(f"Found a USB board: {shown.by_id or port} ({shown.product})")
        try:
            stop = _confirm(f"Write the reader firmware to {port}? What is on the board now is replaced.",
                            "writing the firmware", yes=yes, ask=None if ask is input else ask)
        except KeyboardInterrupt:
            output.result("\nNothing was flashed.")
            return 1
        if stop is not None:
            return stop
    if a.secrets:
        try:
            text = Path(a.secrets).read_text(encoding="utf-8")
        except OSError as e:
            _err_line(f"cannot read {a.secrets} ({e.strerror or e})")
            return 1
        try:
            with _station_stopped():
                rc = rs.flash(Path(a.source), text, port, pio, who=who)
        except _StationBusy as e:
            _err_line(str(e))
            return 1
        if rc != 0:
            _err_line(f"the build or flash failed (PlatformIO exit {rc}){_port_hint(who)}")
            return 1
        output.result("Flashed.")
        return 0
    try:
        base = a.base.rstrip("/") if a.base else rs.reader_base(config.load())
        if not base.startswith("https://"):
            raise rs.SetupError("--base must be the kit's public https address plus /reader")
        key_pem, real_key = rs.pubkey(Path(a.ota_pubkey).read_text(encoding="utf-8") if a.ota_pubkey else None)
        token = Path(a.token_file).read_text(encoding="utf-8").strip() if a.token_file else None
    except (rs.SetupError, OSError) as e:
        _err_line(str(e))
        return 1
    if token is None and not _is_root():
        output.error("this needs administrator rights to make the reader's token.",
                     "run it with sudo, or pass --token-file with a token made by:",
                     cmd="sudo spoolwarden reader token")
        return output.NEEDS_SUDO
    ssid = a.ssid or ask("Wi-Fi name the reader joins: ").strip()
    password = _wifi_password(a, ask_secret)
    if password is None:
        return 1
    try:
        rs.secrets_h(ssid, password, base, token or "x" * 43, key_pem, low)  # every check before a token is made
        if a.out and not rs.out_ok(Path(a.out), who.uid if who else os.getuid() if hasattr(os, "getuid") else 0):
            raise rs.SetupError(f"{a.out} exists and is not a file of yours; choose a new name")
    except rs.SetupError as e:
        _err_line(f"{e}; nothing was changed")
        return 1
    tid = None
    if token is None:
        try:
            tid, token = reader_tokens.TokenStore().issue(a.name or "reader")
        except reader_tokens.TokenFileError as e:
            _err_line(f"{e}; nothing was changed")
            return 1
    text = rs.secrets_h(ssid, password, base, token, key_pem, low)
    if a.out:
        out = Path(a.out)
        try:
            if not rs.out_ok(out, who.uid if who else os.getuid() if hasattr(os, "getuid") else 0):
                raise OSError(f"{out} exists and is not a file of yours; choose a new name")
            rs.write_private(out, text)
            sudo_uid, sudo_gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
            if _is_root() and sudo_uid and sudo_gid:        # the owner who ran sudo builds with it
                os.chown(out, int(sudo_uid), int(sudo_gid))
        except OSError as e:
            if tid:
                reader_tokens.TokenStore().revoke(tid)
            _err_line(f"cannot write {out} ({e.strerror or e})" + ("; the new token was removed" if tid else ""))
            return 1
        print(f"Wrote {out} (mode 600). It holds the token and the Wi-Fi password: delete it once the reader is "
              "flashed.")
        if not flashing:
            output.out("Build and flash with it as reader/README.md says (copy it to reader/src/secrets.h, then "
                       + "pio run -e esp32-c3-supermini -t upload), or here with: "
                       + f"spoolwarden reader setup --secrets {out} --source <checkout>/reader")
    if flashing:
        busy = None
        try:
            with _station_stopped():
                rc = rs.flash(Path(a.source), text, port, pio, who=who)
        except _StationBusy as e:
            rc, busy = 1, e
        if rc != 0:
            dropped = bool(tid) and not a.out
            if dropped:
                reader_tokens.TokenStore().revoke(tid)
            _err_line(f"{busy}" if busy else f"the build or flash failed (PlatformIO exit {rc})"
                      + ("; the new token was removed, since nothing holds it" if dropped else "") + _port_hint(who))
            if busy and dropped:
                output.note("The new token was removed, since nothing holds it.")
            return 1
        output.result(f"Flashed. The reader joins {ssid} and calls {base}.")
    if a.out or flashing:
        print(f"Buzzer: {'low' if low else 'high'}-triggered"
              + (" (the older 3-pin module)." if low else " (a buzzer behind a MOSFET). A reader with the older 3-pin "
                 "buzzer module needs --buzzer low."))
    if tid:
        output.out(f"Reader token {tid} ({a.name or 'reader'}). Remove it later with: "
                   + f"sudo spoolwarden reader revoke {tid}")
    if not real_key:
        print("Note: without --ota-pubkey this reader refuses every update over Wi-Fi until it is flashed again with "
              "the key (py tools/ota_publish.py --init-key prints it).")
    return 0


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
        return output.need_sudo(_sudo_command("sudo spoolwarden web passphrase"))
    try:
        first = secret_input.ask(f"New passphrase, at least {auth.MIN_PASSPHRASE} characters: ")
        second = secret_input.ask("New passphrase again: ")
    except EOFError:
        return _input_ended()
    if first != second:
        _err_line("the two passphrases do not match.")
        return 1
    try:
        write_passphrase(first)
    except GroupMissing as e:
        _err_line(f"{e}; nothing was changed\n"
                  "fix: install the kit first (it creates the filament-kit user and group), "
                  "or: sudo groupadd --system filament-kit")
        return 1
    except ValueError as e:
        _err_line(f"{e}; nothing was changed")
        return 1
    output.result("Passphrase saved.")
    return 0


def cmd_setup_code(new: bool, revoke_trusted: bool = False, yes: bool = False) -> int:
    """`setup-code [--new] [--revoke-trusted]` (root): the code the server's /setup page asks for before any change,
    made when there is none. At a terminal it is printed with the page's address; without one (a log) only the address
    and how to see it, as no secret may end up in a log. A new code keeps trusted computers trusted (the owner's
    choice, said so here); --revoke-trusted forgets them, with or without a new code."""
    from . import setup_code, trusted
    if not _is_root():
        return output.need_sudo(_sudo_command("sudo spoolwarden setup-code"))
    for asked, question, doing in ((new, "Make a new setup code? The old one stops working.", "making a new setup code"),
                                   (revoke_trusted, "Revoke every trusted computer? Each one needs the setup code "
                                    "again.", "revoking every trusted computer")):
        if asked:
            stop = _confirm(question, doing, yes=yes)
            if stop is not None:
                return stop
    if new:
        code = setup_code.generate()
        setup_code.write(code)
    else:
        code = setup_code.ensure()
    url = setup_code.page_url(config.load())
    if output.json_mode():
        if new:                         # a code made now is printed, once; a stored one is not
            reply = {"ok": True, "address": url, "code": setup_code.shown(code)}
        else:
            reply = {"address": url, "code": {"set": True}}
        if revoke_trusted:
            reply = {"ok": True, **reply}
            reply["trusted_revoked"] = trusted.revoke_all()
        output.emit(reply)
        return 0
    if new or apply._tty():             # a code made now is the answer, with or without a terminal; a stored one needs one
        print(f"Open {url}  (setup code: {setup_code.shown(code)})")
    else:
        output.out(f"Open {url}")
        output.note("the setup code is shown at a terminal only.")
    if new and not output.quiet():
        print("The old setup code no longer works.")
    if revoke_trusted:
        n = trusted.revoke_all()
        if not output.quiet():
            print(f"{n} trusted computer{'' if n == 1 else 's'} revoked. Each needs the setup code again.")
    elif new and not output.quiet():
        n = len(trusted.listing())
        if n:
            output.out(f"Trusted computers stay trusted ({n}): revoke them in Devices on the setup page, or with "
                       + "sudo spoolwarden setup-code --revoke-trusted.")
    return 0


def cmd_reader(action: str, name: str | None = None, ref: str | None = None, yes: bool = False) -> int:
    """`tag-reader new-token [--name X]` (root): a new Tag Reader token, printed once (only its sha256 is kept);
    `tag-reader list`: the tokens (id, name, made); `tag-reader revoke <id|name>` (root). The actions keep their old
    names (token, tokens, revoke) in here."""
    try:
        from .web import reader  # needs the [web] extra
    except ImportError as e:
        _err_line(f"the Tag Reader commands need the kit's [web] packages ({e.name or e} is missing); install them "
                  "into the kit's Python: <venv>/bin/python -m pip install 'filament-kit[web]' (or re-run the "
                  "installer, which adds them)")
        return 1
    store = reader.TokenStore()
    if action in ("token", "revoke") and not _is_root():
        return output.need_sudo(_sudo_command(f"sudo spoolwarden tag-reader {'new-token' if action == 'token' else action}"))
    try:
        if action == "token":
            tid, tok = store.issue(name)
            _hub_audit(f"reader token {tid} made")
            output.emit({"ok": True, "id": tid, "name": reader._clean_name(name), "token": tok})
            output.out(f"New Tag Reader token {tid} ({reader._clean_name(name)}):")
            output.out_lines([tok])         # alone on its line, never wrapped
            output.out("Shown only this once. tag-reader flash puts it on the reader for you.")
            return 0
        if action == "tokens":
            rows = store.list()
            output.emit(rows)
            if not rows:
                output.out("No Tag Reader tokens.")
                output.out("Make one: sudo spoolwarden tag-reader new-token --name bench")
                return 0
            output.out_lines(output.table(["ID", "Name", "Made"], [[t["id"], t["name"], t["created"]] for t in rows],
                                          long=1, whole=True))   # `tag-reader revoke` takes the id or the name
            return 0
        rows = store.list()
        hit = [t for t in rows if t["id"] == ref] or [t for t in rows if t["name"] == ref]
        if len(hit) == 1:                       # one that is there
            tid = hit[0]["id"]
            stop = _confirm(f"Revoke the token {tid}? A Tag Reader using it is refused from now on. Set it up again "
                            "with sudo spoolwarden tag-reader flash to give it a new token.", f"revoking the token {tid}",
                            yes=yes)
            if stop is not None:
                return stop
            if store.revoke(tid):
                _hub_audit(f"reader token {tid} revoked")
                output.emit({"ok": True, "id": tid})
                output.result(f"Revoked the token {tid}.")
                return 0
        output.error(f'"{ref}" does not name one Tag Reader token.', "use an ID or a name from:",
                     cmd="sudo spoolwarden tag-reader list")
        return output.USAGE
    except reader.TokenFileError as e:
        _err_line(f"{e}; nothing was changed")
        return 1
    except PermissionError as e:
        _err_line(f"{e} (try with sudo)")
        return 1


def _web_health(port: int) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            body = r.read().decode(errors="replace").strip()
        return body == "ok", body or "empty answer"
    except (OSError, http.client.HTTPException) as e:
        return False, str(e)


def cmd_web_status() -> int:
    rows = status_rows.hub_web_rows() if output.json_mode() else list(status_rows.web_rows())   # --json: the Overview's rows
    return 0 if status_rows.print_rows(rows) else 1


_ENGINE_NAMES = {"local": "On this Hub", "cloud": "Cloud (Claude)"}


def _label_reader_row_lines(rows) -> list[str]:
    """The rows of one group as `status` prints them: state word, text, and a `Fix:` line under a row that needs a look."""
    lines = []
    for r in rows:
        if r.state == status_rows.DETAIL:
            lines += output.status_row("", r.text.strip())
        else:
            lines += output.status_row(status_rows._WORDS[r.state], status_rows._fours(r.text),
                                       r.fix if r.state == status_rows.FAIL else "")
    return lines


def cmd_local_intake_status() -> int:
    """`label-reader status` (06 9.9): the engine order, then the Label Reader group of `status`."""
    from . import intake
    cfg = config.load()
    order = intake.reader_order(cfg)
    if not order:
        output.error("the Label Reader is off, so no engine reads labels.", "turn an engine on first:",
                     cmd="sudo spoolwarden features on label-reader")
        return output.FAILED
    on = modules.enabled(cfg)
    rows: list = []
    with output.wait("Checking…", programs=True):
        if "ai_intake" in on:
            rows += list(status_rows._key_rows(_default_client, True))
            rows.append(status_rows.Row(status_rows.INFO,
                                        f"Reads used today: {_reads_today()} of {cfg['reads_per_day']}",
                                        group="Label Reader", key="label-reader.reads-today"))
        if "local_intake" in on:
            rows += [r for r in status_rows.local_reader_rows(cfg) if not r.text.startswith("label reading:")]
    engine = ", then ".join(_ENGINE_NAMES[r] for r in order)
    if output.json_mode():
        output.emit({"engine_order": order, "rows": status_rows.row_dicts(rows),
                     "summary": status_rows.summary_counts(rows)})
        return 0 if not any(r.state == status_rows.FAIL for r in rows) else 1
    lines = [output.paint("Label Reader", "bold", sys.stdout)]
    lines += output.status_row("on", f"Engine order: {engine}")
    lines += _label_reader_row_lines(rows)
    output.out_lines(lines)
    return 0 if not any(r.state == status_rows.FAIL for r in rows) else 1


def cmd_local_intake_plan(fetcher=None) -> int:
    """What installing the latest reader release needs (download, disk, time per tier), printed; as root also saved
    in the root-owned store for the setup page (its server cannot reach GitHub; this runs as its job)."""
    from . import local_intake_install as lii
    try:
        p = lii.plan(config.load(), fetcher=fetcher)
    except lii.InstallError as e:
        _err_line(str(e))
        return 1
    output.emit(p)
    for line in lii.plan_text(p):
        print(line)
    lii.save_plan(p)
    return 0


def cmd_local_intake_install(tier: str | None, version: str | None, yes: bool, fetcher=None, run=None,
                             planned: bool = False) -> int:
    """Install or upgrade the local label reader from its signed release, switch the module on and apply. The
    download, disk and time the release states are shown before anything is downloaded (--yes skips the question).
    `planned` (the setup page's job, after the owner confirmed what the page showed): exactly the version and tier of
    the last saved plan, if it is under an hour old, and never a downgrade."""
    from . import local_intake_install as lii, local_reader
    if not _require_root():
        return output.NEEDS_SUDO
    cfg = config.load()
    named_version = version is not None and not planned        # only a version typed at the terminal may go back
    if planned:
        sp = lii.saved_plan()
        if sp is None or not sp["fresh"]:
            _err_line("no plan from the last hour: check for the release again on the page, then install")
            return 1
        if sp["plan"].get("downgrade"):
            _err_line(f"the planned {sp['plan']['version']} is older than the installed one: nothing was installed")
            return 1
        version, tier = sp["plan"]["version"], sp["plan"]["tier"]
    if tier is not None and tier not in local_reader.TIERS:
        _err_line(f"--tier must be one of {', '.join(local_reader.TIERS)}")
        return 1
    try:
        p = lii.plan(cfg, tier=tier, version=version, fetcher=fetcher)
    except lii.InstallError as e:
        _err_line(str(e))
        return 1
    with output.shown() if not yes else contextlib.nullcontext():       # what the question is about
        for line in lii.plan_text(p):
            print(line)
    if p["tier"] not in p["tiers"]:
        return 1
    if not yes and output.json_mode():          # --json never asks
        return output.no_terminal("installing the local label reader",
                                  _sudo_command("sudo spoolwarden local-intake install") + " --yes")
    if not yes:
        a = _ask("Go ahead? [y/N] ")
        if not a or a.strip().lower() not in ("y", "yes"):
            print("Nothing was installed.")
            return 0
    try:
        rec = lii.install(cfg, tier=p["tier"], version=p["version"], fetcher=fetcher, run=run,
                          allow_downgrade=named_version,
                          say=lambda s: print(s, flush=True))
    except lii.InstallError as e:
        _err_line(str(e))
        return 1
    cfg = config.load()
    cfg.setdefault("modules", {n: True for n in modules.enabled(cfg)})["local_intake"] = True
    li = cfg.setdefault("local_intake", {})
    li["url"] = f"http://127.0.0.1:{rec['port']}"
    if tier is not None and not planned:
        li["tier"] = tier               # the tier the owner named; a release without `auto` leaves the setting as it was
    rc = _save_and_apply(cfg, [f"The local label reader {rec['version']} is installed; local_intake is on."])
    if rc != 0:
        return rc
    h = lii.wait_healthy(config.load())
    if not h["ok"]:
        _err_line(f"installed, but the reader does not answer yet: {h['error']}. Check: "
                  + "spoolwarden local-intake status")
        return 1
    print(f"The reader answers: version {h['version'] or '?'}, API {h['api_version']}.")
    return 0


def cmd_local_intake_remove(yes: bool, run=None) -> int:
    """Uninstall the reader installed by `local-intake install`, switch the module off (with whatever needs it only)
    and apply. A reader on another machine is not touched: then only the module goes off."""
    from . import local_intake_install as lii
    if not _require_root():
        return output.NEEDS_SUDO
    cfg = config.load()
    have = lii.installed()
    on = modules.enabled(cfg)
    if have is None and "local_intake" not in on:
        print("The local label reader is not installed and local_intake is off: nothing to do.")
        return 0
    new_on, notes = modules.toggle(on, "local_intake") if "local_intake" in on else (on, [])
    stop = _confirm(("Remove the local label reader " + have["version"] + " from this machine?" if have else
                     "Switch local_intake off? No reader is installed on this machine.") + " Its settings are kept."
                    + (" " + " ".join(notes) if notes else ""), "removing the local label reader", yes=yes)
    if stop is not None:
        return stop
    if have is not None:
        try:
            lii.remove(run=run, say=lambda s: print(s, flush=True))
        except lii.InstallError as e:
            _err_line(str(e))
            return 1
    cfg["modules"] = modules.module_map(new_on, cfg)
    return _save_and_apply(cfg, ["The local label reader is removed." if have else "local_intake is off."])


def cmd_local_intake_share(value: str | None = None, delete_waiting: bool = False, status: bool = False,
                           run=None, wait=None) -> int:
    """Share corrections (`label_reader.share_corrections`) at the terminal and as the setup page's job.
    `on` / `off`: check what the page checks (on needs the reader installed here), delete the waiting corrections
    first when `delete_waiting` is given with `off`, save the setting, set the reader. `--status`: the setting and
    the reader's actual state, no root. Without either: set the reader to the saved value (the page's job).
    `--json` (06 6.8) is the global switch: the document is `output.emit`'s."""
    from . import local_reader, share_corrections as sc

    def failed(what: str, **doc) -> int:
        output.emit({"ok": False, "error": what, "fix": None, **doc})
        output.error(what)
        return output.FAILED
    if status:
        st = sc.state(config.load())
        output.emit({"ok": True, **st})
        output.out(f"Share corrections is {'on' if st['saved'] else 'off'} on this Hub; the reader is "
                   + ("not known" if st["actual"] is None else "on" if st["actual"] else "off")
                   + (f" ({st['reason'].replace('_', ' ')})" if st["reason"] else "")
                   + (": it is set differently." if st["differs"] else "."))
        return output.SUCCESS
    if not _require_root():
        return output.NEEDS_SUDO
    deleted = None
    if value is not None:
        want = value == "on"
        cfg = config.load()
        why = sc.refusal(cfg) if want else None
        if why:
            return failed(why)
        if delete_waiting and not want and sc.saved(cfg):
            try:
                deleted = sc.delete_waiting(cfg)
            except sc.DeleteFailed as e:
                return failed(f"{e}. The setting was NOT changed: run it again to delete the rest.",
                              deleted=e.done, waiting=e.total - e.done)
            except local_reader.LocalReaderError as e:
                return failed(f"nothing was deleted and nothing was changed: the waiting corrections could not be "
                              f"read ({e})", deleted=0)
            output.out(f"Deleted {deleted} waiting corrections.")
        cfg.setdefault("label_reader", {})["share_corrections"] = want
        config.save(cfg)
    extra = {"deleted": deleted} if deleted is not None else {}
    job = steps.Steps(4)
    try:
        got = sc.apply(config.load(), run=run, wait=wait, step=job.next, say=output.out)
    except sc.ShareError as e:
        return failed((f"{deleted} waiting corrections were deleted and the setting is saved, but " if deleted else "")
                      + str(e), **extra)
    output.emit({"ok": True, "share": got["want"], "changed": got["changed"], **extra})
    return output.SUCCESS


def cmd_local_intake_token(remove: bool) -> int:
    """Set (hidden prompt) or remove the local reader's bearer token, <etc>/local_intake_token (root). Never printed."""
    from . import local_reader
    if not _is_root() and not _no_systemd():
        return output.need_sudo(_sudo_command("sudo spoolwarden local-intake token"))
    if remove:
        print("Reader token removed." if local_reader.remove_token() else "No reader token was set.")
        return 0
    try:
        token = secret_input.ask("The local reader's token (hidden): ")
    except EOFError:
        return _input_ended()
    try:
        local_reader.write_token(token)
    except ValueError as e:
        _err_line(f"{e}; nothing was changed")
        return 1
    print("Reader token saved; it goes with each read and revise.")
    return 0


def _corrections_failed(e) -> int:
    """A refusal of the corrections core, as the page words it: `Error:` and, under --json, the error document."""
    output.emit({"ok": False, "error": str(e), "fix": None, "reason": e.code})
    output.error(str(e))
    return output.FAILED


def cmd_local_intake_corrections_list() -> int:
    """The corrections waiting to be shared (the setup page's Corrections waiting): count, size and one line each.
    `--json` (06 6.8) is the global switch: the document is the route's answer."""
    from . import reader_corrections
    if not _require_root():
        return output.NEEDS_SUDO
    try:
        got = reader_corrections.waiting(config.load())
    except reader_corrections.CorrectionsError as e:
        return _corrections_failed(e)
    output.emit({"ok": True, **{k: got[k] for k in ("opt_in", "count", "bytes", "entries", "not_queued")}})
    if not got["count"]:
        output.out("No corrections waiting.")
    else:
        output.out(f"Corrections waiting: {got['count']} - {got['bytes'] / 1048576:.1f} MB. Nothing is sent until you "
                   "run: sudo spoolwarden label-reader corrections send")
        for e in got["entries"]:
            what = ", ".join(f"{k}: {v}" for k, v in (e.get("corrected") or {}).items()) if isinstance(
                e.get("corrected"), dict) else ""
            output.out(f"  {e.get('id')}  {e.get('created_at') or ''}  {what}".rstrip())
    for n in got["not_queued"]:
        output.out(f"Not waiting: {n['name'] or n['record']}: the reader did not take this correction. {n['reason']}")
    return output.SUCCESS


def cmd_local_intake_corrections_remove(ids: list[str]) -> int:
    """Take corrections out of the list; nothing is sent."""
    from . import reader_corrections
    if not _require_root():
        return output.NEEDS_SUDO
    cfg = config.load()
    rc, done, failed = output.SUCCESS, [], []
    for eid in ids:
        try:
            reader_corrections.remove(cfg, eid)
            done.append(eid)
            output.out(f"Removed {eid}. Nothing was sent.")
        except reader_corrections.CorrectionsError as e:
            failed.append({"id": eid, "error": str(e), "reason": e.code})
            output.error(f"{eid}: {e}")
            rc = output.FAILED
    output.emit({"ok": rc == output.SUCCESS, "removed": done, "failed": failed})
    return rc


def cmd_local_intake_corrections_retry(records: list[str]) -> int:
    """Queue records' corrections again (the setup page's Try again), for those `list` shows as not waiting."""
    from . import reader_corrections
    if not _require_root():
        return output.NEEDS_SUDO
    rc, done, failed = output.SUCCESS, [], []
    for rid in records:
        try:
            st = reader_corrections.retry(rid)
        except reader_corrections.CorrectionsError as e:
            failed.append({"record": rid, "error": str(e), "reason": e.code})
            output.error(f"{rid}: {e}")
            rc = output.FAILED
            continue
        done.append({"record": rid, "state": st["state"], "reason": st["reason"]})
        if st["state"] == "not_queued":
            output.error(f"{rid}: the reader did not take this correction. {st['reason']}")
            rc = output.FAILED
        else:
            output.out(f"{rid}: " + ("waiting to be shared." if st["state"] == "waiting" else
                                     "nothing to share for this record."))
    output.emit({"ok": rc == output.SUCCESS, "retried": done, "failed": failed})
    return rc


def cmd_local_intake_corrections_package(dest: str) -> int:
    """Save the exact zip that send would send, to `dest` (a file name, or a folder to put the usual name in)."""
    from . import reader_corrections
    if not _require_root():
        return output.NEEDS_SUDO
    try:
        data, name = reader_corrections.package(config.load())
    except reader_corrections.CorrectionsError as e:
        return _corrections_failed(e)
    path = Path(dest)
    if path.is_dir():
        path = path / name
    try:
        path.write_bytes(data)
    except OSError as e:
        output.emit({"ok": False, "error": f"cannot write {path}", "fix": None})
        output.error(f"cannot write {path}: {e.strerror or e}")
        return output.FAILED
    output.emit({"ok": True, "file": str(path), "bytes": len(data)})
    output.out(f"Saved the package to {path} ({len(data) / 1048576:.1f} MB). It is the file send would send.")
    return output.SUCCESS


def cmd_local_intake_corrections_send() -> int:
    """Ask the local reader to send the corrections waiting (the setup page's job `corrections_send`). The reader does
    the upload to where it sends them itself; nothing waiting is lost when it fails."""
    from . import reader_corrections
    if not _require_root():
        return output.NEEDS_SUDO
    cfg = config.load()
    job = steps.Steps(2)
    job.next("Checking the corrections waiting.")
    try:
        n = reader_corrections.waiting(cfg)["count"]
        if not n:
            raise reader_corrections.CorrectionsError(409, "empty", reader_corrections.EMPTY)
        job.next(f"Sending {n} correction{'s' if n != 1 else ''}.")
        out = reader_corrections.send(cfg)
    except reader_corrections.CorrectionsError as e:
        return _corrections_failed(e)
    sent = out["sent"] if out["sent"] is not None else n
    output.emit({"ok": True, "sent": sent})
    output.out(f"Sent {sent} correction{'s' if sent != 1 else ''}. Thank you.")
    return output.SUCCESS


_READ_LEVEL_WORD = {"high": "high", "medium": "medium", "low": "low: check this", "not_on_label": "not on label"}
_READ_ROWS = (("Brand", "vendor"), ("Name", "name"), ("Material", "material"), ("Colour", "color_hex"),
              ("Net weight", "net"), ("Price per kg", "price_per_kg"))


def _read_item_lines(it: dict) -> list[str]:
    """One read item as the Label Reader test shows it: label, value and how sure the reader was of it."""
    levels = it.get("confidence_levels") or {}
    values = []
    for label, field in _READ_ROWS:
        value = _rec_value(field, it.get(field))
        if field == "color_hex" and it.get("color_hex") and it.get("color_name"):
            value += f" ({it['color_name']})"
        values.append((label, value, levels.get(field)))
    lw = max(len(v) for _, v, _l in values)
    limit = output.width() - 1
    lines = []
    for label, value, level in values:
        word = _READ_LEVEL_WORD.get(level)
        shown = output.state(word) if word else ""
        head = f"  {label:<13} {value}"
        if not word:
            lines.append(head)
        elif len(head) + 2 + 2 + len(word) + 2 <= limit and 2 + 13 + 1 + lw + 2 + 2 + len(word) + 1 <= limit:
            lines.append(f"{head}{' ' * (lw - len(value) + 2)}{shown}")
        else:
            lines += [head, f"      {shown}"]
    return lines


def cmd_local_intake_test(photos: list[str], engine: str | None = None, yes: bool = False) -> int:
    """`label-reader test <photo>... [--engine cloud|local]` (06 9.9): read photos with the chosen engine, or the engine
    order, and print the fields with how sure it was. Nothing is added and no record is made."""
    from . import intake
    cfg = config.load()
    order = intake.reader_order(cfg)
    want = {"cloud": "ai_intake", "local": "local_intake"}.get(engine or "")
    if engine and want not in modules.enabled(cfg):
        output.error(f"{_ENGINE_NAMES[engine]} is not installed.", "turn it on first:",
                     cmd="sudo spoolwarden features on " + _KEY_OF[want])
        return output.FAILED
    if not order:
        output.error("the Label Reader is off, so no engine reads labels.", "turn an engine on first:",
                     cmd="sudo spoolwarden features on label-reader")
        return output.FAILED
    readers = [engine] if engine else order
    try:
        images = intake.check_photos([(p, Path(p).read_bytes()) for p in photos])
    except OSError as e:
        output.error(f"there is no readable file at {e.filename}.", "give the path of a JPEG photo of a label.")
        return output.USAGE
    except intake.PhotoError as e:
        _err_line(str(e))
        return 1
    names = " then ".join(_ENGINE_NAMES[r] for r in readers)
    charged: list[bool] = []
    charge = _history_charge()

    def counted():
        charged.append(True)
        return charge()
    started = time.monotonic()
    try:
        with output.wait(f"Reading {len(images)} photo{'' if len(images) == 1 else 's'} with {names}…"):
            out = intake._call(Spoolman(cfg["spoolman_url"]), images, "", None, None, readers=readers, charge=counted)
    except intake.CapReached as e:
        _err_line(str(e))
        return 1
    except intake.ReadError as e:
        _err_line(str(e))
        return 1
    except SpoolmanError as e:
        _err_line(f"Spoolman: {e}")
        return 1
    seconds = round(time.monotonic() - started)
    output.emit({"ok": True, **out})
    by = _ENGINE_NAMES.get(out.get("reader"), "the Label Reader")
    tier = f" (tier: {out['tier']})" if out.get("tier") else ""
    output.out(f"Read by {by}{tier} in {seconds} s. Nothing was added.")
    for n, it in enumerate(out["items"], 1):
        output.out()
        if len(out["items"]) > 1:
            output.out(f"Item {n} of {len(out['items'])}")
        output.out_lines(_read_item_lines(it))
    for q in out.get("questions") or []:
        output.out(f"Question: {q}")
    if charged and out.get("reader") == "cloud":
        output.note(f"this used 1 of today's {cfg['reads_per_day']} reads.")
    return 0


# ---------- help (06 3, 4) ----------

# The groups of the top-level help (06 3.1), then every command (06 3.2) and the old spellings (06 4). `help
# --markdown` is the guide's command table; a test holds it to the design's table. Commands that are not in this
# program (migrate-ops, migrate-scanner, label-reader corrections) are not listed.
_HELP_GROUPS = [('Everyday',
  [('status', 'What works and what needs a look'),
   ('printer', 'List, test, map and manage printers'),
   ('klipper', 'The Klipper add-on'),
   ('recent', 'Recently added spools: show, correct, undo'),
   ('devices', 'Paired phones, PCs and Weigh Stations'),
   ('pair', 'Pair a phone, the Slicer Sync or a Weigh Station'),
   ('weigh-station', 'Weigh Station: pair it, flash its display'),
   ('tag-reader', 'Tag Readers: tokens, flash one over USB'),
   ('presets', 'Slicer presets: build, status, parents, updates')]),
 ('System',
  [('features', 'Switch features on and off; choose the setup'),
   ('config', 'Settings menu; also config show and set'),
   ('locations', 'Storage locations: the list, add, edit, move, remove'),
   ('label-reader', 'Label Reader: status and test'),
   ('catalog', 'Filament Catalog: status, update, roll back, add'),
   ('backup', 'Make or list backups'),
   ('restore', 'Restore this Hub from a backup'),
   ('web', "Access from outside the home, and Claude's connector"),
   ('remote', 'Remote access: certificate and firewall rules'),
   ('setup-code', "The Hub page's address and setup code"),
   ('certificate', "The Hub's certificate and its fingerprint"),
   ('spoolman', "Spoolman: its address and Spoolwarden's extra fields"),
   ('update', 'Check, install or roll back Spoolwarden'),
   ('uninstall', 'Remove Spoolwarden from this machine'),
   ('logs', "The end of a service's log")])]

_COMMAND_TABLE = [('`status`', 'Checks everything and prints one row per check', '{nav_overview}'),
 ('`printer list`', 'All printers, set up and found', '{nav_printers}'),
 ('`printer show <printer>`', 'One printer: details and slots', '{nav_printers}, expanded row'),
 ('`printer test <printer>`', 'Test connection', '{printers_test}'),
 ('`printer add [--klipper] [options]`', 'Add a printer; asks for what is missing', '{printers_add}'),
 ('`printer use <printer>`', 'Add a Klipper printer that a scan found', '{printers_use}'),
 ('`printer dismiss <printer>`', 'Drop a found printer from the list', '{common_dismiss}'),
 ('`printer rename <printer> <new name>`', 'Rename', '{common_rename}'),
 ('`printer address <printer> <address>`', 'Change address', '{printers_change_address}'),
 ('`printer access-code <printer>`', 'Replace the Access Code (Bambu)', '{printers_replace_access_code}'),
 ('`printer api-key <printer> [--clear]`',
  'Set, replace or clear the Moonraker API key (Klipper)',
  '{printers_set_key} / {printers_replace_key} / {printers_clear_key}'),
 ('`printer lane-data <printer> auto\\|on\\|off`', 'Klipper lane data', '{printers_fact_lane_data}'),
 ('`printer detect <printer>`', 'Detect model and slots (Klipper)', '{printers_detect}'),
 ('`printer scan [--subnet CIDR]`', 'Find Klipper printers on the network', '{printers_find}'),
 ('`printer map <printer> [--by-loading]`',
  'Map slots, or map by loading filament',
  '{printers_map_slots} / {printers_map_loading}'),
 ('`printer report <printer>`', 'Collect a report', '{printers_collect_report}'),
 ('`printer reports <printer>`', 'List saved reports', '{printers_saved_reports}'),
 ('`printer forget-certificate <printer>`', 'Forget certificate (Bambu)', '{printers_forget_cert}'),
 ('`printer forget <printer>`', 'Forget printer', '{printers_forget}'),
 ('`printer live <printer>`', 'Prints where the live view is', '{printers_live_view}'),
 ('`printer menu`', 'The Printers screen', '{nav_printers}'),
 ('`klipper add-on`', 'Prints the commands that install the Klipper add-on', '{printers_addon_title}'),
 ('`recent` (same as `recent history`)', 'Recently added records', '{nav_recently_added}'),
 ('`recent show <record> [--photos]`', 'One record: fields, confidence, revisions', 'Record detail'),
 ('`recent revise <record> --note TEXT [--item N]`',
  'Ask the Label Reader to correct it',
  '{recent_ask_title}'),
 ('`recent edit <record> field=value... [--item N] [--spools 41,42]`', 'Edit by hand', '{recent_edit}, {common_save_changes}'),
 ('`recent undo <record>`', 'Undo the newest revision that is not undone', 'Undo revision N'),
 ('`devices` (same as `devices list`)', 'Paired devices', '{nav_devices}'),
 ('`devices forget <device>`', 'Unpair a device', '{devices_unpair}'),
 ('`pair [--slicer-sync \\| --weigh-station] [--text] [--no-wait]`',
  'Pairing code, QR and fingerprint',
  '{devices_pair_phone} / {devices_link_sync} / {devices_link_station}'),
 ('`weigh-station pair [--local]`',
  'Run on the Weigh Station: pair it with the Hub',
  '{devices_pair_station_here}'),
 ('`weigh-station flash-display`', 'Write the Weigh Station display firmware over USB', '{nav_flash_device}'),
 ('`weigh-station pairing-state`', 'Paired, not paired or not checked yet', '(none)'),
 ('`tag-reader list`', 'Tag Reader tokens', '{nav_devices}, {devices_readers_title}'),
 ('`tag-reader new-token [--name NAME]`', 'Make a token', '{devices_readers_make}'),
 ('`tag-reader revoke <reader>`', 'Revoke a token', '{devices_readers_revoke}'),
 ('`tag-reader flash [options]`', "Write a Tag Reader over the Hub's USB", '{nav_flash_device}'),
 ('`presets status`', 'Build, Slicer Sync and update state', '{nav_slicer_presets}'),
 ('`presets build`', 'Build now', '{presets_build_now}'),
 ('`presets lines`', 'Filament lines and their parents', '{presets_lines_title}'),
 ('`presets set-parent <line> <parent> [--orca]`', 'Set the Bambu Studio or Orca Slicer parent', '{presets_set_parent}'),
 ('`presets restore-deleted`', 'Bring back presets deleted in Bambu Studio', '{presets_restore_deleted}'),
 ('`presets updates (--line ID \\| --all)`',
  'Show what would be accepted (changes nothing)',
  '{presets_updates_show}'),
 ('`presets accept-updates (--line ID \\| --all)`', 'Accept updates (asks)', '{presets_updates_accept}'),
 ('`features` (same as `features list`)', 'Features, on or off', '{nav_features}'),
 ('`features menu [--numbered] [--raw]`', 'The Features checklist', '{nav_features}'),
 ('`features on <feature> [--hub ADDRESS]` / `features off <feature>`',
  'Switch one feature (`--hub` when switching on the Weigh Station without the Hub service)',
  '{features_turn_on} / {common_turn_off}'),
 ('`features setup <setup> [--hub ADDRESS]`', 'Choose the setup', '{features_setup_title}'),
 ('`features apply [--no-pair]`', 'Apply the features again', '{features_apply_again}'),
 ('`features units`', 'The service files the features need, one per line', '(none)'),
 ('`config [--numbered]`', 'The settings menu', '{nav_settings}'),
 ('`config show`', 'All settings, in menu order', '{nav_settings}'),
 ('`config set <key> <value>`', 'Change one setting', '{nav_settings}, one field'),
 ('`config theme [<theme>]`', 'Show or set the theme for new devices', '{nav_settings} > {settings_group_appearance} > {appearance_theme_default_title}'),
 ('`locations` (same as `locations list`)', 'The storage locations in fill order', '{nav_settings} > {settings_group_storage}'),
 ('`locations add <name> [--type bulk\\|containers] [--limit N] [--count N] [--takes any\\|none\\|MATERIALS] [--overflow]`',
  'Add a location', '{storage_add_location}'),
 ('`locations edit <name> [--name NEW] [same options as add] [--no-overflow]`',
  'Change a location; a new name also renames it on its spools; `--no-overflow` switches overflow off', '{common_edit}'),
 ('`locations move <name> (--first \\| --last \\| --before <other>)`', 'Change the fill order', 'Move up, Move down'),
 ('`locations remove <name>`', 'Remove a location (asks)', '{common_remove}'),
 ('`locations default-overflow <name>`',
  'Make it the default overflow (a Bulk storage location that is not overflow becomes overflow as well)',
  '{storage_make_default_overflow}'),
 ('`locations sealed <name>`', 'Sealed spools go here', '{storage_sealed_here}'),
 ('`label-reader status`', 'Label Reader engines and their health', '{nav_settings} > {settings_group_label_reader}'),
 ('`label-reader test <photo>... [--engine cloud\\|local]`', 'Read label photos without adding anything', '{settings_reader_test}'),
 ('`catalog status`', 'Filament Catalog version and last check', '{nav_settings} > {settings_group_catalog}'),
 ('`catalog update [--scheduled]`', 'Update now', '{settings_catalog_update}'),
 ('`catalog rollback`', 'Go back to the version before', '{settings_catalog_back}'),
 ('`catalog add <file \\| ->`', 'Add your own entry', '{settings_catalog_entry_add}'),
 ('`catalog adopt <folder>`', 'Take over a catalog folder from an older install', '(none)'),
 ('`catalog token [--remove]`', 'Set, replace or remove the catalog token', '{settings_catalog_token}'),
 ('`backup create [--out DIR]`', 'Back up now', '{settings_backups_now}'),
 ('`backup list`', 'Backups on this Hub', '{settings_backups_list}'),
 ('`backup keep <days>`', 'Keep nightly backups for N days', '{settings_backups_keep}'),
 ('`restore <zip> \\| --uploaded`', 'Restore (asks for the typed word)', '{settings_restore_heading}'),
 ('`web status`', 'Access from outside: rows as in `status`', '{nav_settings} > {settings_group_network}'),
 ('`web passphrase`', 'Set or replace the web passphrase', '{settings_group_passphrase}'),
 ('`remote firewall`', 'Print the firewall rules (changes nothing)', '{settings_network_firewall}'),
 ('`remote get-certificate`', 'Get the public certificate now', '{settings_network_certificate}'),
 ('`setup-code [--new] [--revoke-trusted]`', 'Hub page address and setup code', '{unlock_field_label}, {devices_trusted_title}'),
 ('`certificate`', "Make the Hub's certificate if missing; print its fingerprint", '(none)'),
 ('`spoolman fields`', "Make Spoolwarden's extra fields in Spoolman", '{nav_overview}, {overview_make_fields}'),
 ('`spoolman address [<url>]`',
  'Show or change the Spoolman in use (checked before saving)',
  '{nav_settings} > {settings_group_general}, {settings_general_spoolman}'),
 ('`update [--check \\| --rollback] [--scheduled]`', 'Updates', '{nav_updates}'),
 ('`uninstall [--purge]`', 'Remove Spoolwarden (asks)', '{nav_updates}, footer line'),
 ('`logs [<service>] [--lines 50\\|100\\|200]`', "The end of a service's log", '{nav_logs}'),
 ('`add`', 'Prints where spools are added', '(none)'),
 ('`spool`', 'Prints where spools are opened, tagged and moved', '(none)'),
 ('`help [<command> \\| aliases \\| --markdown]`',
  'Help; `--markdown` prints the command table for the user guide',
  '(none)')]

_ALIASES = [('pair --pc', 'pair --slicer-sync'),
 ('pair --station', 'pair --weigh-station'),
 ('station pair [--local]', 'weigh-station pair [--local]'),
 ('station flash-panel', 'weigh-station flash-display'),
 ('station pairing-state', 'weigh-station pairing-state'),
 ('unpair', 'devices list'),
 ('unpair <id>', 'devices forget <device>'),
 ('cert', 'certificate'),
 ('intake history', 'recent` (or `recent history`)'),
 ('intake show`, `revise`, `edit`, `undo', 'recent show`, `revise`, `edit`, `undo'),
 ('ensure-fields', 'spoolman fields'),
 ('printer map --manual', 'printer map --by-loading'),
 ('printer unpin', 'printer forget-certificate'),
 ('library status`, `update`, `rollback`, `adopt`, `add', 'catalog status`, `update`, `rollback`, `adopt`, `add'),
 ('profiles build`, `status`, `lines`, `set-parent`, `restore-deleted',
  'presets build`, `status`, `lines`, `set-parent`, `restore-deleted'),
 ('profiles apply-updates --dry-run', 'presets updates'),
 ('profiles apply-updates', 'presets accept-updates'),
 ('modules list`, `menu`, `apply`, `units', 'features list`, `menu`, `apply`, `units'),
 ('modules enable <name>` / `disable <name>', 'features on <feature>` / `off <feature>'),
 ('modules enable <name> --server ADDR', 'features on <feature> --hub ADDRESS'),
 ('modules set server\\|station\\|all-in-one [--server ADDR]',
  'features setup hub\\|weigh-station\\|hub-with-weigh-station [--hub ADDRESS]'),
 ('reader tokens', 'tag-reader list'),
 ('reader token [--name]', 'tag-reader new-token [--name]'),
 ('reader revoke', 'tag-reader revoke'),
 ('reader setup', 'tag-reader flash'),
 ('remote issue', 'remote get-certificate'),
 ('klipper add NAME HOST [--port]', 'printer add --klipper --name NAME --address HOST [--port]'),
 ('klipper scan [--subnet]', 'printer scan [--subnet]'),
 ('klipper detect ID', 'printer detect <printer>'),
 ('klipper set ID --lane-data X', 'printer lane-data <printer> X'),
 ('klipper api-key ID', 'printer api-key <printer>'),
 ('klipper pack', 'klipper add-on'),
 ('local-intake status`, `test', 'label-reader status`, `test'),
 ('status --station-pairing` (hidden)', 'status --weigh-station-pairing` (hidden)')]

def _top_help() -> str:
    """06 3.1: the groups in the Hub page's order, what each command is for, and the switches every command takes."""
    lines = ["Spoolwarden on this Hub. Commands marked (sudo) in their own help need sudo.",
             "Usage: spoolwarden <command> [options]    More: spoolwarden <command> -h", ""]
    for group, items in _HELP_GROUPS:
        lines.append(group)
        lines += [f"  {name:<16} {text}" for name, text in items]
        lines.append("")
    lines += ["Every command: -h  --json  -q/--quiet  -y/--yes  --color auto|always|never",
              "               --plain  --no-progress"]
    return "\n".join(lines) + "\n"


def _hub_catalogue() -> dict:
    """The Hub page's string catalogue (shared_static/strings.js, generated from strings/en.json), read without the web extra."""
    text = (Path(__file__).parent / "shared_static" / "strings.js").read_text(encoding="utf-8")
    return json.loads(re.sub(r",\s*}$", "}", text[text.index("{"):text.rindex("}") + 1]))


def _hub_place(cell: str) -> str:
    """A place cell of the command table: each {key} is the catalogue text the Hub page shows for that button or section."""
    cat = _hub_catalogue()
    return re.sub(r"\{(\w+)\}", lambda m: cat[m.group(1)], cell)


def _markdown_table() -> str:
    """`help --markdown`: the command table of 06 3.2 as the user guide holds it."""
    rows = [("Command", "What it does", "Hub page place"), ("---", "---", "---"),
            *[(c, w, _hub_place(p)) for c, w, p in _COMMAND_TABLE]]
    return "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n"


def _help(args, ap, sub) -> int:
    """`help [<command> | aliases | --markdown]` (06 3.2)."""
    if args.markdown:
        output.emit({"markdown": _markdown_table()})
        sys.stdout.write(_markdown_table())
        return 0
    if args.topic is None:
        return _print_help(ap.format_help())
    if args.topic == "aliases":
        pairs = [(old.replace("`, `", ", "), new.replace("`, `", ", ")) for old, new in _ALIASES if "(hidden)" not in old]
        output.emit({"aliases": [{"old": old, "new": new} for old, new in pairs]})
        output.out("The old spellings keep working. Each does what the new one does.")
        output.out()
        for old, new in pairs:
            output.out_lines(output.wrap(f"{old} {output.sym('arrow')} {new}", indent=4))
        return 0
    if args.topic not in sub.choices:
        output.error(f'there is no command called "{args.topic}".', "see the commands with: spoolwarden help")
        return output.USAGE
    return _print_help(sub.choices[args.topic].format_help())


def _print_help(text: str) -> int:
    """Help text as it is, or under --json as {"ok": true, "help": text} (like -h)."""
    output.emit({"ok": True, "help": text})
    print(text, end="")
    return 0


def _add_catalog(sub, name: str, *, alias: bool) -> None:
    """`catalog` and its old spelling `library` (06 9.11, 4): the same subcommands; `token` is the new one's."""
    lb = sub.add_parser(name, help="the Filament Catalog: status, update, roll back, add" if not alias
                        else "the old spelling of catalog")
    lsub = lb.add_subparsers(dest="library_cmd", required=True)
    lsub.add_parser("status", help="the catalog version, its local additions and the last update check")
    lu = lsub.add_parser("update", help="download or update the catalog (library.url)")
    lu.add_argument("--scheduled", action="store_true", help="only if config library.schedule says it is due")
    _add_yes(lsub.add_parser("rollback", help="go back to the catalog version before the last update"))
    la = lsub.add_parser("adopt", help="keep the catalog an older program version bundled (used by the installer)")
    la.add_argument("folder", help="the old library_data folder (index.json and library/)")
    la = lsub.add_parser("add", help="add or replace your own entry from a JSON file ('-' reads stdin)")
    la.add_argument("file")
    if not alias:
        lt = lsub.add_parser("token", help="set, replace or remove the token the catalog downloads with (root)")
        lt.add_argument("--remove", action="store_true", help="remove it (asks first)")
        _add_yes(lt, "answer yes to the question before removing the token")


_invoked: list[str] = []      # the arguments of this run, for the Fix line of a command that needs root


def _sudo_command(fallback: str) -> str:
    """The command that was run with `sudo` in front, so the Fix line holds it whole; `fallback` when `main` did not
    record it."""
    return "sudo spoolwarden " + shlex.join(_invoked) if _invoked else fallback


def main(argv: list[str] | None = None, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    """The CLI. A root-only file (/etc/filament-kit/config.json and the like) read as another user is one error line
    saying to run it with sudo, not a traceback (C-M7). `--color`, `--plain` and `--no-progress` are taken out first
    (06 6.2, 6.6: every command accepts them); Ctrl-C ends with `Stopped.` and exit code 130."""
    args, switches = output.extract_switches(list(sys.argv[1:] if argv is None else argv))
    output.reset()
    output.configure(**switches)
    _invoked[:] = args

    def run() -> int:
        if switches.get("color", "auto") not in ("auto", "always", "never"):   # inside run: --json gives its document
            output.error(f"--color takes always, never or auto, not {switches['color']!r}.",
                         "use --color auto, --color always or --color never.")
            return output.USAGE
        try:
            return _main(args, client_factory=client_factory, manager_factory=manager_factory, sm_factory=sm_factory)
        except PermissionError as e:
            where = f"{e.filename}: " if e.filename else ""
            output.error(f"{where}permission denied.", "run it with sudo:", cmd=_sudo_command("sudo spoolwarden"))
            return output.NEEDS_SUDO
        except KeyboardInterrupt:
            output.out("Stopped.")
            return output.INTERRUPTED
    with output.children_to_stderr():       # --json, --quiet: what a child prints on standard output goes to standard error
        return output.run_json(run) if output.json_mode() else run()


def _add_locations(sub) -> None:
    """`locations` (06 9.15): the storage list and its changes."""
    lc = sub.add_parser("locations", help="the storage locations in fill order; add, edit, move, remove (root)")
    lcs = lc.add_subparsers(dest="loc_cmd")
    lcs.add_parser("list", help="the storage locations in fill order (also what locations alone shows)")

    def options(p) -> None:
        p.add_argument("--type", choices=("bulk", "containers"), help="bulk: a shelf, rack or drawer; containers: "
                       "boxes or bags, one spool each")
        p.add_argument("--limit", metavar="N", help="Bulk storage: the most spools it takes (1 to 9999; none: no limit)")
        p.add_argument("--count", metavar="N", help="Containers: how many (1 to 999)")
        p.add_argument("--takes", metavar="any|none|MATERIALS", help="what fills it automatically: any material, "
                       "none (only when you choose it) or a comma list of materials, e.g. PLA,PETG")

    la = lcs.add_parser("add", help="add a location at the end of the list (root)")
    la.add_argument("name", help="the new location's name")
    options(la)
    la.add_argument("--overflow", action="store_true", help="it takes spools when their own places are full")
    le = lcs.add_parser("edit", help="change a location; a new name also renames it on its spools (root)")
    le.add_argument("name", help="the location's name, capitals ignored")
    le.add_argument("--name", dest="new_name", metavar="NEW", help="rename it (its spools get the new name)")
    options(le)
    over = le.add_mutually_exclusive_group()
    over.add_argument("--overflow", action="store_true", help="it takes spools when their own places are full")
    over.add_argument("--no-overflow", action="store_true", help="it is no longer an overflow location")
    lm = lcs.add_parser("move", help="change the fill order (root)")
    lm.add_argument("name", help="the location to move")
    where = lm.add_mutually_exclusive_group(required=True)
    where.add_argument("--first", action="store_true", help="put it first")
    where.add_argument("--last", action="store_true", help="put it last")
    where.add_argument("--before", metavar="OTHER", help="put it just before this location")
    lr_ = lcs.add_parser("remove", help="remove a location, after asking; its spools keep their location text (root)")
    lr_.add_argument("name", help="the location to remove")
    _add_yes(lr_)
    ld = lcs.add_parser("default-overflow", help="make it the default overflow (root)")
    ld.add_argument("name", help="a Bulk storage location")
    lz = lcs.add_parser("sealed", help="sealed spools go to this Bulk storage location (root)")
    lz.add_argument("name", help="a Bulk storage location")


def _add_yes(parser, help: str = "answer yes to the question this command asks (a script has no terminal to ask on)") -> None:
    parser.add_argument("-y", "--yes", action="store_true", help=help)


class _Parser(argparse.ArgumentParser):
    """A wrong command or option is an error in the words of 06 6.5 (exit code 2), not argparse's own."""

    def error(self, message: str):
        output.error(message, f"see what it takes with: {self.prog} -h")
        raise SystemExit(output.USAGE)

    def format_help(self) -> str:
        """The top-level help is the grouped text of 06 3.1 (the old spellings are not in it)."""
        return _top_help() if getattr(self, "grouped_help", False) else super().format_help()


def _add_recent(sub, name: str, help: str, *, alias: bool) -> None:
    """`recent` and its old spelling `intake`: the same subcommands (06 9.3). `recent` alone is `recent history`."""
    rp = sub.add_parser(name, help=help)
    if not alias:
        rp.add_argument("--from", dest="show_from", action="store_true", help="add the FROM column on a wide terminal")
    rsub = rp.add_subparsers(dest="recent_cmd", required=alias)
    rh = rsub.add_parser("history", help="the newest records first (what recent alone shows)")
    rh.add_argument("--from", dest="show_from", action="store_true", default=argparse.SUPPRESS,
                    help="add the FROM column on a wide terminal")
    rs = rsub.add_parser("show", help="one record: its fields, revisions and photos")
    rs.add_argument("record", help="its ID, as recent shows it")
    rs.add_argument("--photos", action="store_true", help="also list the photos' file paths on the Hub")
    rr = rsub.add_parser("revise", help="ask the Label Reader again with a note, e.g. --note 'brand is Polymaker'")
    rr.add_argument("record", help="its ID")
    rr.add_argument("--note", required=True, help="what is wrong")
    rr.add_argument("--item", type=int, default=None, help="the item to ask about, as recent show numbers it (from 1)")
    _add_yes(rr, "apply the suggestion without asking")
    re_ = rsub.add_parser("edit", help="change saved values by hand: field=value ...")
    re_.add_argument("record", help="its ID")
    re_.add_argument("values", nargs="+", metavar="field=value")
    re_.add_argument("--item", type=int, default=None, help="the item to change, as recent show numbers it (from 1)")
    re_.add_argument("--spools", default=None, help="only these of the item's spools, e.g. 41,42 (default: all)")
    ru = rsub.add_parser("undo", help="undo the record's newest revision")
    ru.add_argument("record", help="its ID")


def _add_weigh_station(sub, name: str, *, alias: bool) -> None:
    """`weigh-station` and its old spelling `station` (06 9.7, 4): the same subcommands, `flash-panel` for `flash-display`."""
    stp = sub.add_parser(name, help="the Weigh Station on this computer: pair it, write its display, ask its pairing" if not alias
                         else "the old spelling of weigh-station")
    stp_sub = stp.add_subparsers(dest="station_cmd", required=True)
    stpp = stp_sub.add_parser("pair", help="pair this Weigh Station with the Hub (the link comes from 'pair --weigh-station')")
    stpp.add_argument("--local", action="store_true", help="the Hub is this machine: no link, nothing to compare")
    fpp = stp_sub.add_parser("flash-panel" if alias else "flash-display",
                             help="write the display firmware to a blank ESP32-C3 board, after you confirm the port")
    fpp.add_argument("--port", help="the board's serial port (/dev/ttyACM0): only that one is offered")
    _add_yes(fpp)
    stp_sub.add_parser("pairing-state", help="whether this Weigh Station is paired, as one line (paired, unpaired, "
                                             "unchecked in --json)")


def _add_presets(sub, name: str, *, alias: bool) -> None:
    """`presets` and its old spelling `profiles` (06 9.5, 4). `profiles apply-updates` is `presets updates` with
    --dry-run and `presets accept-updates` without."""
    text = "the generated Bambu Studio and Orca Slicer presets: build, status, lines, parents, updates"
    pf = sub.add_parser(name, help=text if not alias else "the old spelling of presets", description=text)
    pfsub = pf.add_subparsers(dest="presets_cmd", required=True)
    pfsub.add_parser("build", help="build the presets now and wait for it (needs the Slicer Sync to have run once)")
    pfsub.add_parser("status", help="the last build, the Slicer Sync and the problems")
    pfsub.add_parser("lines", help="the product lines and their Bambu Studio and Orca Slicer parents")
    sp = pfsub.add_parser("set-parent", help="set the Bambu Studio system preset (or with --orca the Orca Slicer "
                                             "library preset) a line is built from")
    sp.add_argument("line_id")
    sp.add_argument("parent")
    sp.add_argument("--orca", action="store_true",
                    help="set the line's Orca Slicer library parent instead (the name without ' @System')")
    pfsub.add_parser("restore-deleted", help="bring back the presets deleted in Bambu Studio at the next build")
    if alias:
        au = pfsub.add_parser("apply-updates", help="the old spelling of updates (--dry-run) and accept-updates")
        aug = au.add_mutually_exclusive_group(required=True)
        aug.add_argument("--line", dest="line_id", help="the updates of one product line (see: profiles lines)")
        aug.add_argument("--all", dest="all_", action="store_true", help="every listed update")
        au.add_argument("--dry-run", action="store_true", help="only show what would be accepted")
        _add_yes(au, "accept without asking (a script has no terminal to ask on)")
        return
    up = pfsub.add_parser("updates", help="list the updates that accept-updates would accept; changes nothing")
    upg = up.add_mutually_exclusive_group()
    upg.add_argument("--line", dest="line_id", help="only the updates of one product line (see: presets lines)")
    upg.add_argument("--all", dest="all_", action="store_true", help="every listed update (also what no switch means)")
    au = pfsub.add_parser("accept-updates", help="write the listed updates over presets already in your slicers "
                                                 "(at the next Slicer Sync run); they are never replaced otherwise")
    aug = au.add_mutually_exclusive_group()
    aug.add_argument("--line", dest="line_id", help="only the updates of one product line (see: presets lines)")
    aug.add_argument("--all", dest="all_", action="store_true", help="every listed update (also what no switch means)")
    _add_yes(au, "accept without asking (a script has no terminal to ask on)")


def _add_features(sub, name: str, *, alias: bool) -> None:
    """`features` and its old spelling `modules` (06 9.6, 4): `enable` is `on`, `disable` is `off`, `set` is `setup`."""
    HUB = dict(dest="server", metavar="ADDRESS", help="the Hub's address (IP address or name), for a Weigh Station "
                                                    "with no Hub on this machine")
    ft = sub.add_parser(name, help="the switchable parts of the kit: list, switch on or off, set up, apply" if not alias
                        else "the old spelling of features")
    fsub = ft.add_subparsers(dest="features_cmd", required=alias)
    fsub.add_parser("list", help="every Feature, its key, whether it is on and what it needs (what features alone shows)")
    fm = fsub.add_parser("menu", help="the Features checklist (cursor keys move, Space switches, h/w/b choose a setup, "
                                      "s applies)")
    fm.add_argument("--raw", action="store_true", help="print the chosen features as a comma list; change nothing")
    on = fsub.add_parser("enable" if alias else "on", help="turn a Feature on and apply (root)")
    on.add_argument("name", metavar="feature", help="its key (see: features)")
    on.add_argument("--server", "--hub", **HUB)
    _add_yes(on, "also turn on the Features it needs, without asking (a script has no terminal to ask on)")
    off = fsub.add_parser("disable" if alias else "off", help="turn a Feature off and apply; its data is kept (root)")
    off.add_argument("name", metavar="feature", help="its key (see: features)")
    if not alias:
        off.add_argument("--hub", **{k: v for k, v in HUB.items() if k != "dest"}, dest="server")
    _add_yes(off, "also turn off the Features that depend on it, without asking (a script has no terminal to ask on)")
    st = fsub.add_parser("set" if alias else "setup", help="switch to a setup and apply (root)")
    st.add_argument("mode", metavar="setup", choices=[*modules.MODES, *modules.MODE_ALIASES])
    st.add_argument("--server", "--hub", **HUB)
    ap_ = fsub.add_parser("apply", help="install, start and stop what the settings say (root)")
    ap_.add_argument("--no-pair", action="store_true", help="show no pairing code at the end (the setup page)")
    fsub.add_parser("units", help="print every systemd unit of every Feature, one per line")


def _add_tag_reader(sub, name: str, *, alias: bool) -> None:
    """`tag-reader` and its old spelling `reader` (06 9.7, 4): `tokens` is `list`, `token` is `new-token`, `setup` is
    `flash`."""
    rd = sub.add_parser(name, help="the Tag Reader tokens and the reader's firmware: make, list, revoke, flash" if not alias
                        else "the old spelling of tag-reader")
    rdsub = rd.add_subparsers(dest="tag_reader_cmd", required=True)
    rdt = rdsub.add_parser("token" if alias else "new-token", help="make a Tag Reader token and print it once (root)")
    rdt.add_argument("--name", help="what the token is for, e.g. bench")
    rdsub.add_parser("tokens" if alias else "list", help="list the Tag Reader tokens (never the tokens themselves)")
    rdr = rdsub.add_parser("revoke", help="remove a Tag Reader token (root)")
    rdr.add_argument("ref", help="its id (r1 ...) or name")
    _add_yes(rdr)
    rds = rdsub.add_parser("setup" if alias else "flash", help="write the kit's firmware to the Tag Reader plugged into "
                                                               "this computer's USB, then its Wi-Fi and token (root to "
                                                               "make the token). --source or --out build it with "
                                                               "PlatformIO instead")
    rds.add_argument("--name", help="what its token is for, e.g. bench")
    _add_yes(rds, "answer yes to the question before writing the firmware to the board (the one found, or --port)")
    rds.add_argument("--ssid", help="the Wi-Fi network it joins (asked if left out); the password is always asked")
    rds.add_argument("--password", type=klipper_cli.dash, metavar="-",
                     help="give - and type the Wi-Fi password on standard input")
    rds.add_argument("--source", help="the reader's source folder (a checkout's reader/): build and flash it here")
    rds.add_argument("--port", help="its USB serial port (found when one ESP32 board is plugged in, which you are asked to confirm)")
    rds.add_argument("--out", help="write its secrets.h here (0600) to build elsewhere")
    rds.add_argument("--ota-pubkey", help="the PEM public key OTA images are signed with (ota_publish.py --init-key)")
    rds.add_argument("--token-file", help="a token made on the server (new-token) instead of a new one")
    rds.add_argument("--base", help="READER_BASE when this machine is not the server: <web.public_url>/reader")
    rds.add_argument("--secrets", help="flash a secrets.h written earlier with --out (needs --source)")
    rds.add_argument("--reflash", action="store_true",
                     help="write the kit's firmware even when the board already runs that build")
    rds.add_argument("--pending", action="store_true",
                     help="take the answers the setup page left (its job runs this; nothing is asked)")
    rds.add_argument("--buzzer", choices=("high", "low"), default=None,
                     help="the buzzer's trigger: high (a buzzer behind a MOSFET, the default; asked when left out) "
                          "or low (the older 3-pin "
                          "module)")


def _dispatch_recent(args) -> int:
    which = args.recent_cmd or "history"
    if which == "history":
        return cmd_recent(show_from=getattr(args, "show_from", False))
    if which == "show":
        return cmd_recent_show(args.record, photos=args.photos)
    if which == "revise":
        return cmd_recent_revise(args.record, args.note, item=args.item, yes=args.yes)
    if which == "edit":
        return cmd_recent_edit(args.record, args.values, item=args.item, spools=args.spools)
    return cmd_recent_undo(args.record)


def _main(argv: list[str] | None = None, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    ap = _Parser(prog="spoolwarden")
    ap.grouped_help = True
    ap.add_argument("--version", action="version", version=f"Spoolwarden {__version__}", help=argparse.SUPPRESS)
    ap.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                    help="colour on the terminal: always, never, or auto (default; NO_COLOR and TERM=dumb turn it off)")
    ap.add_argument("--plain", action="store_true",
                    help="the screen-reader mode: words without glyphs, ASCII only, no colour, progress as whole lines "
                         "(also SPOOLWARDEN_PLAIN=1; implied by TERM=dumb)")
    ap.add_argument("--no-progress", action="store_true",
                    help="print each progress line once, as a whole line, instead of rewriting it")
    ap.add_argument("--numbered", action="store_true",
                    help="menus and checklists as numbered lines, never full-screen (also SPOOLWARDEN_MENU=numbered; "
                         "implied by --plain)")
    ap.add_argument("--json", action="store_true",
                    help="standard output is one JSON document; nothing asks (a command that would needs --yes)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="print only what the command exists to print: errors, lists and details asked for, answers")
    sub = ap.add_subparsers(dest="cmd", required=False)
    stat = sub.add_parser("status", help="check services, Spoolman, key, certificate")
    stat.add_argument("--station-pairing", help=argparse.SUPPRESS)  # passed by the wrapper, from its check as root
    pp = sub.add_parser("pair", help="show a QR code and code to pair a phone, then wait for it (--slicer-sync, "
                                     "--weigh-station: a link to paste instead)")
    pkind = pp.add_mutually_exclusive_group()
    pkind.add_argument("--slicer-sync", "--pc", dest="slicer_sync", action="store_true",
                       help="pair the Slicer Sync on a PC: print the link, no QR code")
    pkind.add_argument("--weigh-station", "--station", dest="weigh_station", action="store_true",
                       help="pair a Weigh Station on another computer: print the link")
    pp.add_argument("--no-wait", action="store_true", help="show the code and end without waiting for the device")
    _add_weigh_station(sub, "weigh-station", alias=False)
    _add_weigh_station(sub, "station", alias=True)
    pp.add_argument("--text", action="store_true", help="print the pairing link and code without the QR code")
    dv = sub.add_parser("devices", help="the paired devices; devices forget unpairs one")
    dsub = dv.add_subparsers(dest="devices_cmd")
    dsub.add_parser("list", help="the paired devices (also what devices alone shows)")
    dfg = dsub.add_parser("forget", help="unpair a device, after asking")
    dfg.add_argument("device", help="its name or ID (or the start of its name)")
    _add_yes(dfg)
    up = sub.add_parser("unpair", help="list or remove paired devices (the old spelling of devices and devices forget)")
    up.add_argument("device", nargs="?")
    _add_yes(up)
    cf = sub.add_parser("config", help="the settings menu; config show and config set read and change one setting")
    cfsub = cf.add_subparsers(dest="config_cmd")
    cfsub.add_parser("show", help="every setting in the menu's order; secrets as set or not set")
    cft = cfsub.add_parser("theme", help="show or set the theme for new devices (setting it needs root)")
    cft.add_argument("theme", nargs="?", help="console, workbench, palette or panes, in any case")
    cfs = cfsub.add_parser("set", help="change one setting, checked as the menu checks it (root)")
    cfs.add_argument("key", help="the setting's key, e.g. server_name")
    cfs.add_argument("value", help="its new value")
    _add_locations(sub)
    sub.add_parser("certificate", help="make the Hub's certificate if missing; print its fingerprint")
    sub.add_parser("cert", help="the old spelling of certificate")
    _add_recent(sub, "recent", "Recently added: the last spool additions, their photos and revisions", alias=False)
    _add_recent(sub, "intake", "the old spelling of recent", alias=True)
    sub.add_parser("ensure-fields", help="the old spelling of spoolman fields")
    sm = sub.add_parser("spoolman", help="Spoolman: its address and Spoolwarden's extra fields")
    smsub = sm.add_subparsers(dest="spoolman_cmd", required=True)
    smsub.add_parser("fields", help="make Spoolwarden's extra fields in Spoolman")
    sma = smsub.add_parser("address", help="show the Spoolman in use, or check an address and use it (root)")
    sma.add_argument("url", nargs="?", help="the new address, e.g. http://spoolman.example:7912")
    lg = sub.add_parser("logs", help="the end of a service's log (root)")
    lg.add_argument("service", nargs="?", help="a service the switched-on features run (default: the Hub's)")
    lg.add_argument("--lines", type=int, choices=(50, 100, 200), default=100, help="how many lines (default 100)")
    sub.add_parser("add", help="where spools are added")
    sub.add_parser("spool", help="where spools are opened, tagged and moved")
    hp = sub.add_parser("help", help="help for a command; help aliases lists the old spellings; help --markdown the command table")
    hp.add_argument("topic", nargs="?", help="a command, or aliases")
    hp.add_argument("--markdown", action="store_true", help="the command table for the user guide")
    pr = sub.add_parser("printer", help="printers: list, show, test, add, change, map slots, reports, forget")
    psub = pr.add_subparsers(dest="printer_cmd", required=True)
    PRINTER = dict(metavar="printer", help="its name, serial or id (or the start of its name)")
    SECRET = dict(type=klipper_cli.dash, metavar="-", help="give - and type the secret on standard input")
    psub.add_parser("list", help="every printer, set up or found, with its state")
    for name, text in (("show", "one printer: its fields and its slots"), ("test", "check that a printer answers"),
                       ("detect", "ask a Klipper printer what it is (read only)"),
                       ("reports", "the printer reports kept for a Bambu Lab printer"),
                       ("live", "where the camera and the controls are")):
        psub.add_parser(name, help=text).add_argument("printer", **PRINTER)
    pa = psub.add_parser("add", help="add a Bambu Lab printer, or with --klipper a Klipper printer (asks for what is left out)")
    pa.add_argument("--klipper", action="store_true", help="a Klipper printer (Moonraker), not a Bambu Lab printer")
    pa.add_argument("--address", help="its IP address or name")
    pa.add_argument("--port", type=int, help="Klipper: Moonraker's port (7125)")
    pa.add_argument("--name", help="what to call it (default: its serial, or its address for a Klipper printer)")
    pa.add_argument("--serial", help="Bambu Lab: its serial number (read from the printer when left out)")
    pa.add_argument("--access-code", **SECRET)
    pa.add_argument("--api-key", **SECRET)
    pu_ = psub.add_parser("use", help="put a Klipper printer a scan found into use")
    pu_.add_argument("printer", **PRINTER)
    pu_.add_argument("--api-key", **SECRET)
    pd = psub.add_parser("dismiss", help="take a printer a scan found off the list")
    pd.add_argument("printer", **PRINTER)
    _add_yes(pd)
    prn = psub.add_parser("rename", help="give a printer another name")
    prn.add_argument("printer", **PRINTER)
    prn.add_argument("name", help="the new name")
    pad = psub.add_parser("address", help="change the address of a printer (a Bambu Lab printer asks for its Access Code)")
    pad.add_argument("printer", **PRINTER)
    pad.add_argument("address")
    pad.add_argument("--port", type=int, help="Klipper: Moonraker's port")
    pad.add_argument("--access-code", **SECRET)
    pac = psub.add_parser("access-code", help="replace the Access Code of a Bambu Lab printer (asked, not echoed)")
    pac.add_argument("printer", **PRINTER)
    pac.add_argument("--access-code", **SECRET)
    pak = psub.add_parser("api-key", help="set the Moonraker API key of a Klipper printer (asked, not echoed), or --clear it")
    pak.add_argument("printer", **PRINTER)
    pak.add_argument("--api-key", **SECRET)
    pak.add_argument("--clear", action="store_true", help="remove the key (asks first)")
    _add_yes(pak)
    pld = psub.add_parser("lane-data", help="what a Klipper printer publishes to Moonraker's lane_data: auto, on or off")
    pld.add_argument("printer", **PRINTER)
    pld.add_argument("mode", choices=registry.LANE_DATA)
    psc = psub.add_parser("scan", help="look for Moonraker on the network (only when you run it)")
    psc.add_argument("--subnet", help="CIDR to scan, at most a /24 (default: this machine's /24)")
    pm = psub.add_parser("map", help="map the AMS slots (changes slot colours briefly, runs a no-motion job)")
    pm.add_argument("printer", **PRINTER)
    pm.add_argument("--by-loading", "--manual", dest="manual", action="store_true",
                    help="map by loading filament: you load each slot, the printer says which one it sees (needs the "
                         "running server; the same session as the setup page and the phone apps)")
    _add_yes(pm, "answer yes to the question before mapping (not asked with --by-loading)")
    prp = psub.add_parser("report", help="make a report that helps add a printer or AMS the kit doesn't know yet")
    prp.add_argument("printer", **PRINTER)
    pu = psub.add_parser("forget-certificate", aliases=["unpin"],
                         help="forget a Bambu printer's pinned TLS certificate (asks for its Access Code)")
    pu.add_argument("printer", **PRINTER)
    pu.add_argument("--access-code", **SECRET)
    _add_yes(pu)
    pf = psub.add_parser("forget", help="stop using a printer and delete what is kept for it")
    pf.add_argument("printer", **PRINTER)
    _add_yes(pf)
    psub.add_parser("menu", help="the Printers screen")
    _add_catalog(sub, "catalog", alias=False)
    _add_catalog(sub, "library", alias=True)
    lr = sub.add_parser("label-reader", help="the Label Reader: its engines and their health; read photos to test")
    lrsub = lr.add_subparsers(dest="lr_cmd", required=True)
    lrsub.add_parser("status", help="the engine order and how each engine is doing")
    lrt = lrsub.add_parser("test", help="read label photos and print the fields (nothing is added, no record is made)")
    lrt.add_argument("photos", nargs="+", help="JPEG photos of one or more labels")
    lrt.add_argument("--engine", choices=("cloud", "local"), default=None,
                     help="read with this engine only (default: the engine order)")
    lrc = lrsub.add_parser("corrections", help="the corrections waiting to be shared: list, remove, retry, package, "
                                               "send (nothing is sent by itself)")
    lrcsub = lrc.add_subparsers(dest="lrc_cmd")
    lrcsub.add_parser("list", help="the corrections waiting to be shared (the default)")
    lcr = lrcsub.add_parser("remove", help="take corrections out of the list; nothing is sent")
    lcr.add_argument("ids", nargs="+", help="the ids `list` shows")
    lcy = lrcsub.add_parser("retry", help="queue the corrections of records again that `list` shows as not waiting")
    lcy.add_argument("records", nargs="+", help="the record ids `list` shows")
    lcp = lrcsub.add_parser("package", help="save the exact zip that send would send, to look at it first")
    lcp.add_argument("file", help="a file name, or a folder")
    lrcsub.add_parser("send", help="ask the Label Reader to send the corrections waiting (it does the upload)")
    _add_presets(sub, "presets", alias=False)
    _add_presets(sub, "profiles", alias=True)
    _add_features(sub, "features", alias=False)
    _add_features(sub, "modules", alias=True)
    wb = sub.add_parser("web", help="the MCP endpoint and phone web app: passphrase, status")
    wbsub = wb.add_subparsers(dest="web_cmd", required=True)
    wbsub.add_parser("passphrase", help="set the sign-in passphrase (root; typed twice, hidden)")
    wbsub.add_parser("status", help="check the web unit: public URL, passphrase, health, connectors")
    li = sub.add_parser("local-intake", help="the local label reader (local_intake module): status, test a photo")
    lisub = li.add_subparsers(dest="li_cmd", required=True)
    lisub.add_parser("status", help="does the local reader answer, which tiers it can use, the reader order")
    lii = lisub.add_parser("install", help="install or upgrade the local reader from its signed release on this "
                                           "machine (root; sizes are shown first)")
    lii.add_argument("--tier", choices=["auto", "cpu", "gpu"], help="default: local_intake.tier (auto)")
    lii.add_argument("--version", help="a release version instead of the latest")
    _add_yes(lii, "do not ask (the sizes are still printed)")
    lii.add_argument("--planned", action="store_true", help="the version and tier the last `local-intake plan` "
                                                            "saved (the setup page's job)")
    lis = lisub.add_parser("share-corrections", help="Share corrections: `on` / `off` sets it (root); no word sets "
                                                     "the reader to the saved value (the setup page's job); "
                                                     "--status shows both")
    lis.add_argument("value", nargs="?", choices=["on", "off"], help="switch it on or off")
    lis.add_argument("--delete-waiting", action="store_true", help="with off: first delete the corrections waiting "
                                                                   "on the reader")
    lis.add_argument("--status", action="store_true", help="the saved setting and the reader's own state, no root")
    litk = lisub.add_parser("token", help="set the local reader's bearer token (root; asked hidden, never shown)")
    litk.add_argument("--remove", action="store_true", help="remove it instead")
    lisub.add_parser("plan", help="what installing the latest reader release needs, per tier (saved for the setup "
                                  "page when run as root)")
    lir = lisub.add_parser("remove", help="uninstall the local reader from this machine and switch local_intake off "
                                          "(root; its settings are kept)")
    _add_yes(lir, "do not ask")
    lit = lisub.add_parser("test", help="read photos with the local reader only and print the result (no Claude, "
                                        "no daily read used, nothing saved)")
    lit.add_argument("photos", nargs="+", help="JPEG photos of one or more labels")
    lit.add_argument("--engine", choices=("cloud", "local"), default=None, help=argparse.SUPPRESS)
    _add_tag_reader(sub, "tag-reader", alias=False)
    _add_tag_reader(sub, "reader", alias=True)
    bk = sub.add_parser("backup", help="a whole-kit backup as one zip: make one, list them (root)")
    bksub = bk.add_subparsers(dest="backup_cmd", required=True)
    bkc = bksub.add_parser("create", help="write a backup zip (default: into /var/backups/filament-kit)")
    bkc.add_argument("--out", help="the folder to write it into")
    bksub.add_parser("list", help="the backups in /var/backups/filament-kit")
    bkk = bksub.add_parser("keep", help="keep the nightly backups for this many days (1 to 365)")
    bkk.add_argument("days", type=int)
    rs = sub.add_parser("restore", help="bring this machine to the state in a backup zip (root)")
    rs_what = rs.add_mutually_exclusive_group(required=True)
    rs_what.add_argument("zip", nargs="?", help="the backup zip")
    rs_what.add_argument("--uploaded", action="store_true", help="the zip the setup page received")
    _add_yes(rs, "ask nothing, the typed word included (no terminal: the installer, the setup page)")
    rm_ = sub.add_parser("remote", help="remote access: get the certificate, show the firewall rules")
    rmsub = rm_.add_subparsers(dest="remote_cmd", required=True)
    _add_yes(rmsub.add_parser("get-certificate", aliases=["issue"],
                              help="get the certificate with certbot (standalone on port 80) (root)"))
    rmsub.add_parser("firewall", help="print the firewall and port-forward rules to set up by hand")
    ud = sub.add_parser("update", help="install the latest signed release (root); --check only looks, --rollback "
                                       "goes back to the version before the last update")
    _add_yes(ud, "answer yes to the question before installing (a script has no terminal to ask on)")
    udx = ud.add_mutually_exclusive_group()
    udx.add_argument("--check", action="store_true", help="say whether a newer release exists; change nothing")
    udx.add_argument("--rollback", action="store_true", help="reinstall the version the last update replaced")
    udx.add_argument("--feed", action="store_true", help=argparse.SUPPRESS)  # the new program, after an update
    udx.add_argument("--scheduled", action="store_true", help="the timer's run: only with the updates module on "
                                                              "and a check due")
    un = sub.add_parser("uninstall", help="remove the kit with the kept release's uninstall.sh (root); --purge "
                                          "also deletes the data, after a typed confirmation")
    un.add_argument("--purge", action="store_true", help="also delete settings, spool data, paired phones, backups")
    _add_yes(un, "answer yes to both questions, the typed word of --purge included (a script has no terminal)")
    sc = sub.add_parser("setup-code", help="show the setup page's address and its setup code (root); --new "
                                           "replaces the code")
    sc.add_argument("--new", action="store_true", help="make a new setup code; the old one stops working (trusted "
                                                        "computers stay trusted)")
    sc.add_argument("--revoke-trusted", action="store_true",
                    help="forget every trusted computer, so each needs the setup code again (alone, or with --new)")
    _add_yes(sc)
    klipper_cli.add_parser(sub)       # its own module (Klipper printers), see klipper_cli.py
    args = ap.parse_args(argv)
    if args.cmd is None:                        # no command: the top-level help (06 3.1)
        return _print_help(ap.format_help())
    if args.cmd == "help":
        return _help(args, ap, sub)
    if args.cmd == "intake":                    # the old spellings are the same commands (06 4)
        args.cmd = "recent"
    elif args.cmd == "unpair":
        args.cmd, args.devices_cmd = "devices", "forget" if args.device else "list"
    elif args.cmd == "library":
        args.cmd = "catalog"
    elif args.cmd == "cert":
        args.cmd = "certificate"
    elif args.cmd == "ensure-fields":
        args.cmd, args.spoolman_cmd = "spoolman", "fields"
    elif args.cmd == "local-intake" and args.li_cmd in ("status", "test"):
        args.cmd, args.lr_cmd = "label-reader", args.li_cmd
        if args.li_cmd == "test" and not getattr(args, "engine", None):
            args.engine = "local"           # the old spelling reads with the local reader only, as it always did
    elif args.cmd == "remote" and args.remote_cmd == "issue":
        args.remote_cmd = "get-certificate"
    else:
        _old_spelling(args)
    if output.json_mode():
        refused = _json_refusal(args)
        if refused is not None:
            return refused
    with output.muted() if _reports_results(args) else contextlib.nullcontext():
        return _dispatch(args, client_factory=client_factory, manager_factory=manager_factory, sm_factory=sm_factory)


def _old_spelling(args) -> None:
    """06 4: the old groups and subcommands are the same commands as the new ones (silently, 06 2)."""
    if args.cmd == "station":
        args.cmd, args.old_spelling = "weigh-station", True
        if args.station_cmd == "flash-panel":
            args.station_cmd = "flash-display"
    elif args.cmd == "profiles":
        args.cmd = "presets"
        if args.presets_cmd == "apply-updates":
            args.presets_cmd = "updates" if args.dry_run else "accept-updates"
            args.line_id = None if args.all_ else args.line_id
    elif args.cmd == "modules":
        args.cmd = "features"
        args.features_cmd = {"enable": "on", "disable": "off", "set": "setup"}.get(args.features_cmd, args.features_cmd)
    elif args.cmd == "reader":
        args.cmd = "tag-reader"
        args.tag_reader_cmd = {"tokens": "list", "token": "new-token", "setup": "flash"}.get(args.tag_reader_cmd,
                                                                                              args.tag_reader_cmd)


def _sub_of(a) -> str | None:
    """The word after the command: `backup create` is `create`."""
    for name in ("station_cmd", "recent_cmd", "devices_cmd", "printer_cmd", "library_cmd", "presets_cmd", "features_cmd",
                 "web_cmd", "li_cmd", "lr_cmd", "tag_reader_cmd", "backup_cmd", "remote_cmd", "klipper_cmd",
                 "config_cmd", "spoolman_cmd", "loc_cmd"):
        if hasattr(a, name):
            return getattr(a, name)
    return None


def _json_refusal(a) -> int | None:
    """06 6.8: the menus take no `--json`, and a command that needs typed answers has nothing to ask them on. The exit
    code (2) when this is one of them, after its Error and Fix."""
    c, sub = a.cmd, _sub_of(a)
    if c == "config" and sub is None:
        output.error("config is a menu.", "use spoolwarden config show --json")
        return output.USAGE
    if c == "features" and sub == "menu":
        output.error("features menu is a menu.", "use spoolwarden features --json")
        return output.USAGE
    if c == "printer" and sub == "menu":
        output.error("printer menu is a menu.", "use spoolwarden printer list --json")
        return output.USAGE
    asks = ((c == "weigh-station" and sub == "pair" and not a.local, "weigh-station pair"),
            (c == "tag-reader" and sub == "flash" and not a.pending, "tag-reader flash"),
            (c == "web" and sub == "passphrase", "web passphrase"),
            (c == "catalog" and sub == "token" and not a.remove, "catalog token"),
            (c == "local-intake" and sub == "token" and not a.remove, "local-intake token"),
            (c == "printer" and sub in ("unpin", "forget-certificate") and not a.access_code, f"printer {sub}"),
            (c == "printer" and sub == "map" and a.manual, "printer map --manual"),
            (c == "klipper" and sub == "api-key" and not a.api_key and not a.clear, "klipper api-key"))
    for yes, name in asks:
        if yes:
            output.error(f"{name} asks for typed answers, and --json does not ask.", "run it without --json.")
            return output.USAGE
    return None


# `--quiet`: the commands whose standard output is only results (06 6.8 drops them). Every other command prints what it
# exists to print there (a list, a detail, an answer, a link or token) or is a screen, and stays as it is.
_RESULTS_ONLY = {("locations", "add"), ("locations", "edit"), ("locations", "move"), ("locations", "remove"),
                 ("locations", "default-overflow"), ("locations", "sealed"), ("weigh-station", "flash-display"), ("backup", "create"), ("backup", "keep"), ("restore", None),
                 ("recent", "edit"), ("recent", "undo"), ("devices", "forget"), ("spoolman", "fields"),
                 ("spoolman", "address"), ("config", "set"), ("printer", "report"), ("printer", "unpin"),
                 ("catalog", "update"), ("catalog", "rollback"), ("catalog", "adopt"), ("catalog", "add"),
                 ("catalog", "token"),
                 ("presets", "build"), ("presets", "set-parent"), ("presets", "restore-deleted"),
                 ("presets", "accept-updates"), ("features", "apply"), ("features", "setup"), ("features", "on"),
                 ("features", "off"), ("web", "passphrase"), ("local-intake", "install"),
                 ("local-intake", "remove"), ("local-intake", "token"), ("tag-reader", "revoke"), ("remote", "get-certificate"),
                 ("uninstall", None), ("update", None), ("klipper", "add"), ("klipper", "set"), ("klipper", "api-key"),
                 ("printer", "forget-certificate"), ("printer", "add"), ("printer", "use"), ("printer", "dismiss"),
                 ("printer", "forget"), ("printer", "rename"), ("printer", "address"), ("printer", "access-code"),
                 ("printer", "api-key"), ("printer", "lane-data")}


def _reports_results(a) -> bool:
    """Is this run, with `--quiet`, a command whose standard output is only results."""
    if not output.quiet():
        return False
    c, sub = a.cmd, _sub_of(a)
    if c == "weigh-station" and sub == "pair":
        return a.local
    if c == "printer" and sub == "map":
        return not a.manual
    if c == "update":
        return not a.check
    if c == "spoolman" and sub == "address":
        return a.url is not None            # without an address it shows the one in use
    return (c, sub) in _RESULTS_ONLY


def _dispatch(args, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    if args.cmd == "klipper":
        return klipper_cli.run(args)
    if args.cmd == "status":
        return cmd_status(client_factory or _default_client, station_pairing=args.station_pairing)
    if args.cmd == "pair":
        return cmd_pair(slicer_sync=args.slicer_sync, weigh_station=args.weigh_station, text=args.text,
                        wait=not args.no_wait)
    if args.cmd == "weigh-station" and args.station_cmd == "pair" and args.local:
        return cmd_station_pair_local()
    if args.cmd == "weigh-station" and args.station_cmd == "flash-display":
        return cmd_station_flash_panel(yes=args.yes, only_port=args.port)
    if args.cmd == "weigh-station":
        return (cmd_station_pairing_state(old_spelling=getattr(args, "old_spelling", False))
                if args.station_cmd == "pairing-state" else cmd_station_pair())
    if args.cmd == "devices":
        return cmd_devices(yes=getattr(args, "yes", False), forget=args.device if args.devices_cmd == "forget" else None)
    if args.cmd == "config":
        if args.config_cmd == "show":
            return cmd_config_show(sm_factory)
        if args.config_cmd == "theme":
            return cmd_config_theme(args.theme)
        return cmd_config_set(args.key, args.value) if args.config_cmd == "set" else cmd_config(sm_factory)
    if args.cmd == "locations":
        return locations_cli.run(args, sm_factory or _default_spoolman)
    if args.cmd == "recent":
        return _dispatch_recent(args)
    if args.cmd == "certificate":
        return cmd_cert()
    if args.cmd == "spoolman":
        return cmd_ensure_fields() if args.spoolman_cmd == "fields" else cmd_spoolman_address(args.url)
    if args.cmd == "logs":
        return cmd_logs(args.service, args.lines)
    if args.cmd == "add":
        return cmd_add()
    if args.cmd == "spool":
        return cmd_spool()
    if args.cmd == "label-reader":
        if args.lr_cmd == "status":
            return cmd_local_intake_status()
        if args.lr_cmd == "corrections":
            if args.lrc_cmd == "remove":
                return cmd_local_intake_corrections_remove(args.ids)
            if args.lrc_cmd == "retry":
                return cmd_local_intake_corrections_retry(args.records)
            if args.lrc_cmd == "package":
                return cmd_local_intake_corrections_package(args.file)
            if args.lrc_cmd == "send":
                return cmd_local_intake_corrections_send()
            return cmd_local_intake_corrections_list()
        return cmd_local_intake_test(args.photos, getattr(args, "engine", None))
    if args.cmd == "printer":
        return _dispatch_printer(args, manager_factory or _default_manager)
    if args.cmd == "catalog":
        if args.library_cmd == "token":
            return cmd_library_token(args.remove, yes=args.yes)
        if args.library_cmd == "status":
            return cmd_library_status()
        if args.library_cmd == "update":
            return cmd_library_update(args.scheduled)
        if args.library_cmd == "rollback":
            return cmd_library_rollback(yes=args.yes)
        if args.library_cmd == "adopt":
            return cmd_library_adopt(args.folder)
        return cmd_library_add(args.file)
    if args.cmd == "presets":
        which = args.presets_cmd
        if which == "build":
            return cmd_profiles_build(sm_factory or _default_spoolman)
        if which == "status":
            return cmd_profiles_status()
        if which == "lines":
            return cmd_profiles_lines()
        if which == "set-parent":
            return cmd_profiles_set_parent(args.line_id, args.parent, orca=args.orca)
        if which in ("updates", "accept-updates"):
            return cmd_profiles_updates(args.line_id, accept=which == "accept-updates", yes=getattr(args, "yes", False))
        return cmd_profiles_restore_deleted()
    if args.cmd == "web":
        return cmd_web_passphrase() if args.web_cmd == "passphrase" else cmd_web_status()
    if args.cmd == "local-intake":
        if args.li_cmd == "install":
            return cmd_local_intake_install(args.tier, args.version, args.yes, planned=args.planned)
        if args.li_cmd == "plan":
            return cmd_local_intake_plan()
        if args.li_cmd == "token":
            return cmd_local_intake_token(args.remove)
        if args.li_cmd == "share-corrections":
            return cmd_local_intake_share(args.value, args.delete_waiting, args.status)
        if args.li_cmd == "remove":
            return cmd_local_intake_remove(args.yes)
        return cmd_local_intake_status() if args.li_cmd == "status" else cmd_local_intake_test(args.photos)
    if args.cmd == "tag-reader" and args.tag_reader_cmd == "flash":
        return cmd_reader_setup(args)
    if args.cmd == "tag-reader":
        return cmd_reader({"list": "tokens", "new-token": "token"}.get(args.tag_reader_cmd, args.tag_reader_cmd),
                          getattr(args, "name", None), getattr(args, "ref", None), yes=getattr(args, "yes", False))
    if args.cmd == "backup":
        return cmd_backup(args.backup_cmd, args.out if args.backup_cmd == "create" else None,
                          days=args.days if args.backup_cmd == "keep" else None)
    if args.cmd == "restore":
        return cmd_restore(args.zip, uploaded=args.uploaded, yes=args.yes)
    if args.cmd == "remote":
        from . import remote
        cfg = config.load()
        if args.remote_cmd != "get-certificate":
            return remote.firewall(cfg)
        if "remote" in modules.enabled(cfg) and (_no_systemd() or _is_root()):     # else `issue` says what is wrong
            stop = _confirm("Get the certificate now? Port 80 on your router must reach this Hub while it runs. "
                            "Spoolwarden never changes your firewall or router.", "getting the certificate",
                            yes=args.yes)
            if stop is not None:
                return stop
        return remote.issue(cfg)
    if args.cmd == "uninstall":
        return cmd_uninstall(args.purge, yes=args.yes)
    if args.cmd == "update":
        from . import updates
        cfg = config.load()
        if args.check:
            if output.json_mode():
                from . import release
                try:
                    updates.check_info(cfg)             # saves what it read, which `view` then reports
                    output.emit(updates.view(cfg))      # the Hub's GET /setup/api/updates
                except release.ReleaseError as e:
                    output.error(str(e))
                    return output.FAILED
                return 0
            return updates.check(cfg)
        if args.feed:
            return updates.feed_now(cfg)
        if not args.scheduled:
            stop = _confirm_update(cfg, rollback=args.rollback, yes=args.yes)
            if stop is not None:
                return stop
        if args.rollback:
            return updates.rollback(cfg)
        return updates.update(cfg, scheduled=args.scheduled)
    if args.cmd == "features":
        which = args.features_cmd or "list"
        if which == "units":
            return cmd_modules_units()
        if which == "list":
            return cmd_modules_list()
        if which == "menu":
            return cmd_modules_menu(args.raw)
        if which == "setup":
            return cmd_modules_set(args.mode, args.server)
        if which in ("on", "off"):
            return cmd_modules_toggle(args.name, which == "on", getattr(args, "server", None), yes=args.yes)
        return cmd_modules_apply(pair=not args.no_pair)
    if args.cmd == "setup-code":
        return cmd_setup_code(args.new, args.revoke_trusted, yes=args.yes)
    return cmd_ensure_fields()
