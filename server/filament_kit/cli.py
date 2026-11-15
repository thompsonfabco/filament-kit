"""Command line: status, pair, unpair, config, cert, ensure-fields, printer map / unpin, library, profiles, modules,
web, remote, setup-code."""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import http.client
import io
import json
import os
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

from . import hostaddr, apply, config, inventory, klipper_cli, library, menu_ui, modules, output, pairing, qr, secret_input, steps
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


def cmd_pair(pc: bool = False, station: bool = False, text: bool = False) -> int:
    cmd = "sudo filament-kit pair" + (" --pc" if pc else " --station" if station else "")
    cfg = config.load()                 # unreadable: main() says to run it with sudo
    if "server" not in modules.enabled(cfg):
        # a station (or another machine without the server): no certificate here, and none is needed
        addr = _station_server(cfg)
        where = (f"the kit server ({addr}, from station.allow)" if addr
                 else "the kit server (its address is not set here: station.allow names none)")
        _err_line(f"the server module is off on this machine; pairing runs on the kit server.\n"
                  f"fix: run {cmd} on {where}")
        return 1
    try:
        pr = pairing.issue(device_hint="pc" if pc else "station" if station else "", scope="station" if station else None)
    except pairing.PairingError as e:
        # /etc/filament-kit is root's: as a user the certificate cannot be read (or even seen)
        unreadable = isinstance(e, pairing.CertUnreadable) or not _is_root()
        _err_line(f"{e}" + (f"\nfix: run it with sudo: {cmd}" if unreadable else ""))
        return 1
    if output.json_mode():
        output.emit({"ok": True, "code": pr.code, "link": pr.qr,
                     "fingerprint": pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes()),
                     "expires": _iso(pr.expires)})
        return 0
    if pc or station:
        # no QR scanner there: the link is pasted (printed by design, never logged)
        output.out("Link for filament-kit-sync (paste it when asked):" if pc else
                   "Link for the intake station (on the station PC: sudo filament-kit station pair"
                   + ", then paste it):")
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
        output.out(f"The link works for {pairing.TOKEN_TTL // 60} minutes: run sudo filament-kit station pair on the "
                   "station PC before then.")
    return 0


def cmd_station_pair(ask=input) -> int:
    """On the station PC: take the link from `filament-kit pair --station`, check the server's fingerprint with the
    owner, save the pairing for the button flow (station/server_api.py)."""
    from .station import server_api
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return output.need_sudo(_sudo_command("sudo filament-kit station pair"))
    no_terminal = ("sudo filament-kit station pair needs a terminal: it asks for the link and for you to "
                   "compare the fingerprint. Nothing was saved.")
    try:
        text = ask("Paste the link from sudo filament-kit pair --station on the server: ")
    except (EOFError, RuntimeError, OSError):  # `< /dev/null`; `<&-` is no stdin (RuntimeError) or a dead one (OSError)
        _err_line(no_terminal)
        return 1
    try:
        link = server_api.parse_link(text)
    except ValueError as e:
        _err_line(str(e))
        return 1

    def owner_compares(seen: str) -> bool:
        print("The server's certificate fingerprint:")
        print("  " + " ".join(seen[i:i + 4] for i in range(0, len(seen), 4)))
        try:
            answer = ask("Does it match the one sudo filament-kit pair --station showed? [y/N] ")
        except (EOFError, RuntimeError, OSError):  # no answer is a no
            _err_line(no_terminal)
            return False
        return answer.strip().lower() in ("y", "yes")

    result = server_api.pair_with_link(link, confirm=owner_compares)
    if result.status == "failed":
        _err_line(result.message)
    else:
        if result.status == "paired_not_restarted":
            print(result.message, file=sys.stderr)
        else:
            output.result(result.message)
    return 1 if result.status in ("failed", "declined") else 0


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
        return output.need_sudo(_sudo_command("sudo filament-kit station flash-panel"))
    if not yes and ask is input and not output.terminal():     # nobody to ask which board: nothing is stopped or written
        return output.no_terminal("writing the firmware", _sudo_command("sudo filament-kit station flash-panel") + " --yes")
    service = "filament-kit-station.service"
    was_active = run(["systemctl", "is-active", service], check=False).returncode == 0  # only restart what was running
    try:
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
            only_port = _port_check(only_port, [(p,) for p in ports], "station flash-panel would write")
            if only_port is None:
                return output.USAGE
            ports = [only_port]
        if not ports:
            _err_line("no blank ESP32-C3 board found. Nothing was flashed.\nfix: plug the board's USB port into this PC (a "
                      "board that already runs the panel firmware doesn't need flashing).")
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
            run(["systemctl", "start", service], check=False)


def _flash_and_verify(panel, port: str, version: str) -> int:
    """Flash port, then ask the board for its HELLO: success only when it reports the bundled version."""
    if not panel.flash_panel(port, version):
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
    print(f"Wrote panel firmware {version} to {port}; the board answers.")
    return 0


def cmd_station_pair_local() -> int:
    """`station pair --local`: the station on the machine that is also the kit server (the setup page's button). Nothing
    to compare by eye, nothing to paste: this machine makes the link, and pair_with_link checks the certificate it finds
    on loopback against it. Prints no token: the output goes to the page's job log."""
    from .station import server_api
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return output.need_sudo(_sudo_command("sudo filament-kit station pair --local"))
    if "server" not in modules.enabled(config.load()):
        _err_line("--local pairs a station with the kit server on the same machine, and the server module is off "
                  "here.\nfix: run sudo filament-kit pair --station on the kit server, then sudo filament-kit station "
                  "pair here")
        return 1
    try:
        result = server_api.pair_with_link(server_api.parse_link(pairing.issue(device_hint="station", scope="station").qr),
                                           step=steps.Steps(3).next)
    except (pairing.PairingError, ValueError) as e:
        _err_line(str(e))
        return 1
    print(result.message, file=sys.stderr if result.status in ("failed", "paired_not_restarted") else sys.stdout)
    return 1 if result.status == "failed" else 0


def cmd_backup(action: str, out: str | None) -> int:
    from . import backup
    if not _is_root():
        return output.need_sudo(_sudo_command(f"sudo filament-kit backup {action}"))
    if action == "list":
        rows = backup.listing()
        output.emit({"backups": [{"name": e.name, "download": e.download, "size": e.size, "kind": e.kind,
                                  "at": _iso(e.at)} for e in rows],
                     "keep_days": backup.keep_days(config.load()), "folder": str(backup.backups_dir())})
        if not rows:
            output.out(f"No backups in {backup.backups_dir()}.")
            return 0
        output.out_lines(output.table(
            ["When", "Kind", "Size", "Name"],
            [[time.strftime("%Y-%m-%d %H:%M", time.localtime(e.at)), e.kind, f"{e.size // 1024:,} KiB", e.name]
             for e in rows], long=3, right=(2,), whole=True))   # restore needs the whole name
        return 0
    try:
        with output.wait("Backing up…", programs=True):
            path = backup.create(Path(out) if out else None, step=steps.Steps(3).next)
    except (OSError, backup.BackupError) as e:
        _err_line(f"the backup was not written: {e}")
        return 1
    output.emit({"ok": True, "path": str(path)})
    print(f"backup written: {path}")
    return 0


def _restore_out(text: str) -> None:
    """What `backup.restore` says: its `error: ...` lines are errors (standard error), the rest results."""
    if text.startswith("error: "):
        output.error(text[len("error: "):])
    else:
        output.out(text)


def cmd_restore(zip_path: str | None, *, uploaded: bool = False, yes: bool = False) -> int:
    from . import backup
    if not _is_root():
        return output.need_sudo(_sudo_command("sudo filament-kit restore <backup.zip>"))
    if not yes and not output.terminal():           # the typed word cannot be asked: nothing is read or changed
        return output.no_terminal("restoring a backup", _sudo_command("sudo filament-kit restore <backup.zip>") + " --yes")
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


def cmd_station_pairing_state() -> int:
    """One line for the wrapper, run as root: see server_api.pairing_state."""
    from .station import server_api
    state = server_api.pairing_state()
    word, _, address = state.partition(" ")
    output.emit({"state": word, "address": address or None})
    print(state)
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
    return output.confirm(question, yes=yes, doing=doing, rerun=_sudo_command("sudo filament-kit <command>") + " --yes",
                          word=word, ask=ask)


def cmd_unpair(device_id: str | None, yes: bool = False) -> int:
    if device_id is None:
        devs = pairing.devices()
        from .web.slots import CLI_DEVICE, INTAKE_DEVICE
        output.emit([{"id": d["id"], "name": d["name"], "paired": _iso(d["paired"]), "last_seen": _iso(d["last_seen"]),
                      "built_in": d["name"] in (INTAKE_DEVICE, CLI_DEVICE)} for d in devs])
        if not devs:
            output.out("No paired devices.")
            return 0
        output.out_lines(output.table(
            ["Id", "Name", "Paired", "Last seen"],
            [[d["id"], d["name"], _fmt_time(d["paired"]), _fmt_time(d["last_seen"])] for d in devs], long=1, whole=True))   # `unpair` takes the id; the name is what tells phones apart
        return 0
    dev = next((d for d in pairing.devices() if d["id"] == device_id), None)
    if dev is None:     # a pairing token nobody has claimed yet is removed too (`unpair <id>` always did)
        dev = next((d for d in pairing._read("devices.json") if d.get("id") == device_id), None)
    if dev is None:
        _err_line(f"no paired device {device_id}")
        return output.USAGE
    name = dev.get("name") or device_id
    stop = _confirm(f"Unpair {name}? It can no longer reach the kit server until it is paired again.",
                    f"unpairing {name}", yes=yes)
    if stop is not None:
        return stop
    if pairing.revoke(device_id):
        output.result(f"Unpaired {device_id}.")
        return 0
    _err_line(f"no paired device {device_id}")
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
    """The Storage locations group on its own, for the installer's first-run question: the changes go into `cfg` (in
    place) when `s` or `q` leaves the screen."""
    session = _ConfigMenu(copy.deepcopy(cfg), menu_ui.NumberedUi(_ask, secret_input.ask))
    session.embedded = True
    try:
        session.group("storage")
    except _Ended:
        pass
    session.stage_into(cfg)


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
    _Item("locations", "Locations", "list", "locations", sep=","),
    _Item("pla", "PLA rack", "text", "placement.pla_location"),
    _Item("prefix", "Box location prefix", "text", "placement.box_prefix", keep_spaces=True),
    _Item("boxes", "Number of storage boxes", "int", "placement.box_count", low=0, high=999, words="0 or more"),
    _Item("overflow", "Overflow location", "text", "placement.overflow"),
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
                "storage": ("locations", "pla", "prefix", "boxes", "overflow"),
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

    # ----- values
    def stored(self, it: _Item, cfg: dict | None = None):
        return _general_value(self.cfg if cfg is None else cfg, it.key)

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
            pl, boxes = self.value(it["pla"]), self.value(it["boxes"])
            n = len(self.value(it["locations"]) or [])
            return f"{n} location{'' if n == 1 else 's'}{sep}PLA rack {pl}{sep}{boxes} box{'' if boxes == 1 else 'es'}", False
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
            after = ["Back up now: sudo filament-kit backup create", "Restore: sudo filament-kit restore <zip>"]
        elif gid == "catalog":
            after = ["Update now: sudo filament-kit library update"]
        elif gid == "network":
            after = ["Firewall rules: filament-kit remote firewall"]
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

    def stage_into(self, cfg: dict) -> None:
        """The staged settings written into `cfg` (in place), checked: the installer's storage question."""
        for iid, value in self.staged.items():
            if _ITEMS[iid].kind != "secret":
                _set_path(cfg, _ITEMS[iid].key, value)

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
            if it.kind == "secret":
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
            if it.kind == "secret":
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


def cmd_config() -> int:
    """`config`: the settings menu (06 8.3). A menu needs a terminal, or `--numbered` with its answers on standard input."""
    if not output.numbered() and not menu_ui._stdin_tty():
        output.error("config is a menu, and there is no terminal to ask on.",
                     "run it again with --numbered, giving the answers on standard input.")
        return output.USAGE
    if not _no_systemd() and hasattr(os, "geteuid") and os.geteuid() != 0:
        return output.need_sudo(_sudo_command("sudo filament-kit config"))
    session = None
    try:
        with menu_ui.open_ui(_ask, secret_input.ask) as ui:
            session = _ConfigMenu(config.load(), ui)
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
        stop = _confirm(f"Clear the Moonraker API key of {name}? filament-kit then connects without a key. If Moonraker "
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
            stop = _confirm(f"Forget {name}? filament-kit stops connecting to it and deletes {what}",
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


def _ask_feature_settings(on, new: dict) -> tuple[dict | None, str]:
    """The settings the chosen features need and the Hub does not have yet, one prompt each in the table's order, each
    after one line saying which feature needs it (8.5). (answers, "") or (None, the feature that was not answered)."""
    need = modules.missing_settings(on, new)
    keys = [k for k in ("web.public_url", "orders.file") if k in need]
    keys += ["spoolman_url"] if modules.needs_spoolman_url(on, new) else []
    keys += ["station.allow"] if "station.allow" in need else []
    got: dict[str, str] = {}
    owners = {"web.public_url": "web" if "web" in on else "remote", "orders.file": "orders", "spoolman_url": "server",
              "station.allow": "station"}
    for key in keys:
        line, prompt, wrong = _FEATURE_ASKS[key]
        output.out(line.format(who=modules.MODULES[owners[key]].title))
        while True:
            raw = _ask(prompt)
            if raw is None or not raw.strip():
                return None, modules.MODULES[owners[key]].title
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
            got[key] = value
            break
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


def _intake_line(s: dict) -> str:
    sp = s.get("spools") or []
    what = ", ".join(sorted({f"{x.get('vendor')} {x.get('name')}" for x in sp})) or "no spools"
    ids = ", ".join(str(x.get("spool_id")) for x in sp)
    return f"{s['id']}  {s.get('at', '')[:16].replace('T', ' ')}  {s.get('source')}  {s.get('state')}  {what} (spool {ids})"


def _show_values(v: dict) -> str:
    from . import intake_history
    return ", ".join(f"{k} {v.get(k)}" for k in intake_history.FIELDS if v.get(k) is not None)


def cmd_intake(args) -> int:
    from . import intake, intake_history
    sm = Spoolman(config.load()["spoolman_url"])
    try:
        if args.intake_cmd == "history":
            d = intake_history.list_records("ai_intake" in modules.enabled(config.load()))
            output.emit(d)
            print(f"Intake history: {d['count']} record(s), keeping {d['keep']}, "
                  f"{d['photo_bytes'] / 1048576:.1f} MB of photos.")
            for s in d["records"]:
                print(_intake_line(s))
                for p in intake_history.photo_paths(s["id"]):
                    print(f"    photo {p}")
            return 0
        if args.intake_cmd == "show":
            r = intake_history.get(args.id)
            output.emit(r)
            print(_intake_line(r))
            for p in intake_history.photo_paths(args.id):
                print(f"  photo {p}")
            for s in r["saved"]:
                print(f"  item {s['item']}: {_show_values(s['values'])} (spools {s['spool_ids']}, "
                      f"filament {s['filament_id']})")
            for rv in r["revisions"]:
                ch = "; ".join(sorted({f"{c['field']} {c['old']} -> {c['new']}" for c in rv["changes"]}))
                print(f"  revision {rv['n']} {rv['at'][:16].replace('T', ' ')} by {rv['by']}"
                      f"{' (undone)' if rv.get('undone') else ''}: {ch}"
                      + (f" | note: {rv['note']}" if rv.get("note") else ""))
                if rv["filaments"].get("orphaned"):
                    print(f"    filament {rv['filaments']['orphaned']} has no spools left (not deleted)")
            return 0
        if args.intake_cmd == "revise":
            from . import intake
            cfg = config.load()
            if not intake.reading_on(cfg):
                _err_line("label reading (ai_intake or local_intake) is off on this server: use "
                          + "filament-kit intake edit")
                return 1
            if not args.yes and not output.terminal():      # before the read is spent: nobody can accept it
                return output.no_terminal("applying the revision", _sudo_command("sudo filament-kit <command>") + " --yes")
            p = intake_history.revise(sm, args.id, args.note, args.item)
            if p.get("reader"):
                print(f"Read again by {'the local reader' if p['reader'] == 'local' else 'Claude'}"
                      + (f", {round(p['confidence'] * 100)} % sure" if p.get("confidence") is not None else "")
                      + (f" ({p['note']})" if p.get("note") else "") + ".")
            print(f"Before: {_show_values(p['before'])}\nAfter:  {_show_values(p['after'])}")
            if not p["changes"]:
                print("The AI changed nothing.")
                return 0
            print("Changes: " + ", ".join(p["changes"]) + (" (no photo was kept for this record)" if p["no_photo"] else ""))
            stop = _confirm("Accept these changes?", "applying the revision", yes=args.yes)
            if stop is not None:
                return stop
            r = intake_history.apply(sm, args.id, proposal=p["proposal"], device="command line")
            return _say_revision(r)
        if args.intake_cmd == "edit":
            vals = {}
            for kv in args.values:
                k, sep, v = kv.partition("=")
                if not sep:
                    _err_line(f"{kv}: write field=value")
                    return 1
                vals[k.strip()] = _cli_value(k.strip(), v.strip())
            spools = None
            if args.spools:
                try:
                    spools = [int(x) for x in args.spools.split(",") if x.strip()]
                except ValueError:
                    _err_line("--spools takes spool ids, e.g. 41,42")
                    return 1
            return _say_revision(intake_history.apply(sm, args.id, item=args.item, values=vals, spool_ids=spools,
                                                      device="command line"))
        if args.intake_cmd == "undo":
            r = intake_history.undo(sm, args.id, None)
            output.emit({"ok": True, **r})
            print(f"Undone. The record is now {r['state']}.")
            return 0
    except intake_history.HistoryError as e:
        _err_line(str(e))
        return 1
    except intake.ReadError as e:
        _err_line(str(e))
        return 1
    return 1


def _cli_value(k: str, v: str):
    if k in ("nozzle", "bed"):
        return int(v) if v.lstrip("-").isdigit() else v
    if k in ("net", "tare", "density", "price_per_kg"):
        try:
            return float(v)
        except ValueError:
            return v
    return v or None


def _say_revision(r: dict) -> int:
    output.emit({"ok": True, **r})
    if output.quiet():                  # `intake revise` is not muted as a whole: its proposal is what was asked for
        return 0
    rv = r["revisions"][-1]
    print(f"Saved as revision {rv['n']}: " + "; ".join(sorted({f"{c['field']} {c['old']} -> {c['new']}"
                                                               for c in rv["changes"]})))
    fl = rv["filaments"]
    if fl["to"] != fl["from"]:
        print(f"Spools {rv['spool_ids']} moved from filament {fl['from']} to {fl['to']}"
              + (" (new)" if fl["created"] else "") + ".")
    if fl.get("orphaned"):
        print(f"Filament {fl['orphaned']} has no spools left; it was not deleted.")
    return 0


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
        _err_line(f"Spoolman: {e}")
        return 1
    output.emit({"ok": True, "made": list(created)})
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
                   + f"sudo filament-kit printer report {serial}")
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
    "wrong_code": "the printer refused its Access Code; enter it again (sudo filament-kit config"
                  + ", Printers)",
    "cert_changed": "the printer's certificate changed; add it again with its Access Code ("
                    + "sudo filament-kit config, Printers)",
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
        _err_line(f"no printer {serial} is set up (see: sudo filament-kit config, Printers)")
        return output.USAGE
    if manual:
        api = _server_api()
        if api is None:     # the session lives in the server, shared with the other three interfaces
            _err_line("map by loading filament needs the running kit server.\nfix: sudo systemctl start filament-kit")
            return output.HUB_DOWN
        return _manual_map_via_server(api, serial)
    if p.family != "bambu":
        _err_line(f"{registry.display_name(p)} is a Klipper printer; Klipper printers are mapped by loading filament: "
                  f"filament-kit printer map --manual {serial}")
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


def cmd_printer_unpin(serial: str, yes: bool = False) -> int:
    """`printer unpin <serial>`: asks for the Access Code, as the API does (R103), and saves it with the cleared pin."""
    p = registry.load().get(serial)
    if p is None:
        _err_line(f"no printer {serial}")
        return output.USAGE
    if p.family != "bambu":
        _err_line("unpin is for a Bambu printer")
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
    try:
        code = secret_input.ask("Access Code: ").strip()
    except (EOFError, RuntimeError, OSError):      # no terminal to ask on
        _err_line("printer unpin needs a terminal to ask for the Access Code; nothing changed")
        return 1
    if not code:
        _err_line("trusting a new certificate needs the printer's Access Code; nothing changed")
        return 1
    problem = registry.check_fields(serial, code)
    if problem:
        _err_line(f"nothing changed: {problem}")
        return 1
    registry.set_code(serial, code, replace=True)     # clears the pin, as adding the printer again
    # the service's Manager notices the cleared pin at its next registry sync (within 15 s) and reconnects
    print(f"Forgot the certificate of {p.name or serial} and saved its Access Code; the next connection trusts the one it presents.")
    return 0


# ---------- library ----------

def _request_rebuild(reason: str) -> None:
    """Ask for a profile rebuild (filament-kit-build.path starts the build)."""
    builds.request_rebuild(reason)


def _library_line(st: dict) -> str:
    n = st["local"]
    if st["source"] == "none":
        return ("library not downloaded (run: filament-kit library update" + f"), "
                f"{n} local addition{'' if n == 1 else 's'}")
    return (f"library version {st['version']} ({st['source']}), "
            f"{n} local addition{'' if n == 1 else 's'}")


def cmd_library_status() -> int:
    st = library.status()
    if output.json_mode():
        from .setup_console import library_tab
        view = library_tab._view()          # the Hub page's own reply
        if isinstance(view.get("last_check"), dict):
            view["last_check"]["at"] = _iso((st.get("last_check") or {}).get("at"))
        output.emit(view)
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
        job = steps.Steps(4)
        with output.wait("Updating the Filament Catalog…", programs=True):
            r = library.update(cfg["library"].get("url") or None, scheduled=scheduled, step=job.next)
    except (library.LibraryError, ValueError) as e:
        _err_line(str(e))
        return 1
    if r.note:
        output.note(r.note)
    if r.error:
        if scheduled and r.http_status in library.PRIVATE_STATUSES:
            # the library may simply not be published yet: the timer run is not a failure, the last good
            # version (or none) stays in use
            output.note(r.error)
            return 0
        _err_line(r.error)
        return 1
    if r.held_from is not None:
        output.out(f"library version {r.version} kept: version {r.held_from} was rolled back and is the newest published; "
                   "scheduled updates wait for a newer one (run: sudo filament-kit library update"
                   + " to install it anyway)")
        return 0
    if not r.changed:
        print(f"library version {r.version} is up to date")
        return 0
    print(f"library version {r.version} installed ({r.downloaded} entr{'y' if r.downloaded == 1 else 'ies'} "
          f"downloaded)")
    text = library.skipped_text()
    if text:
        print(text)
    job.next("Asking for a preset build")
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


def cmd_library_rollback(yes: bool = False) -> int:
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
    print(f"rolled back to library version {v}")
    left = library.rolled_back_from()
    if left is not None:
        output.out(f"scheduled updates will skip version {left} until a newer one is published "
                   "(run: sudo filament-kit library update to install it anyway)")
    job.next("Asking for a preset build")
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
    output.emit({"ok": True, "vendor": entry["vendor"], "product": entry["product"], "line": line})
    print(f"added local entry {entry['vendor']} {entry['product']} (line {line})")
    _request_rebuild(f"local library addition {line}")
    return 0


# ---------- profiles ----------

def _default_spoolman() -> Spoolman:
    return Spoolman(config.load()["spoolman_url"])


def cmd_profiles_build(sm_factory) -> int:
    with output.wait("Building the Slicer presets…"):
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
    if output.json_mode():
        from .setup_console import presets_tab
        output.emit(presets_tab._view())        # the Hub page's own reply
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
            output.out("  see them: sudo filament-kit profiles apply-updates --all --dry-run"
                       + "; apply: sudo filament-kit profiles apply-updates --line <id> | --all")
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
    if output.json_mode():
        from . import profiles_api
        counts = profiles_api._preset_counts()
        output.emit({"lines": [profiles_api._line_view(line, counts) for _k, line in sorted(ls.items())]})
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
        return output.USAGE
    except lines_mod.LineStoreError as e:
        _err_line(e.message)
        return 1
    output.emit({"ok": True, "line": line.line_id, "target": "orca" if orca else "bambu",
                 "parent": line.orca_parent if orca else line.bambu_parent})
    if orca:
        print(f"line {line.line_id}: Orca parent {line.orca_parent} (set by you)")
    else:
        print(f"line {line.line_id}: parent {line.bambu_parent} (set by you)")
    return 0


def cmd_profiles_apply_updates(line_id: str | None, all_: bool, dry_run: bool, yes: bool = False) -> int:
    """Accept the listed updates of one line or all: the next PC sync writes them over the presets in the slicers
    (after its backup); nothing else ever writes over an existing preset."""
    try:
        r = builds.apply_updates(line_id=line_id, all_=all_, dry_run=True)      # what would be accepted, before asking
    except ValueError as e:
        _err_line(str(e))
        return 1
    chosen = r["chosen"]
    if r["stamp"] is None:
        print("no build yet: nothing to update")
        return 0
    if not chosen:
        output.out(f"no updates for line {line_id} (see: sudo filament-kit profiles status)" if line_id
                   else "no updates available")
        return 1 if line_id else 0
    if not dry_run and not yes and not output.terminal():       # nothing is listed or accepted when nobody can answer
        return output.no_terminal("accepting the updates", _sudo_command("sudo filament-kit <command>") + " --yes")
    with output.shown() if dry_run or not yes else contextlib.nullcontext():    # asked-for data, or what the question is about
        for u in chosen:
            app = "Orca Slicer" if u["target"] == "orca" else "Bambu Studio"
            keys = ", ".join(u["keys"][:6]) + (", ..." if len(u["keys"]) > 6 else "")
            where = f" (in your file {u['file']})" if u.get("file") else ""
            print(f"  {u['line_id']}  {app}: {u['name']}{where}: {keys}")
    lines = len({u["line_id"] for u in chosen})
    what = f"{len(chosen)} update{'' if len(chosen) == 1 else 's'} ({lines} line{'' if lines == 1 else 's'})"
    if not dry_run:
        stop = _confirm(f"Accept {'this' if len(chosen) == 1 else f'these {len(chosen)}'} update"
                        f"{'' if len(chosen) == 1 else 's'}? The PC sync writes {'it' if len(chosen) == 1 else 'them'} at "
                        "its next run, after its backup.", "accepting the updates", yes=yes)
        if stop is not None:
            return stop
        try:        # exactly what was shown: a build that landed while the question was open is accepted unseen by no one
            builds.apply_updates(line_id=line_id, all_=all_, dry_run=False, only={u["name"] for u in chosen},
                                 expect_stamp=r["stamp"])
        except builds.UpdatesChanged:
            output.error("the updates changed while you were asked; nothing was accepted.",
                         "run it again to see them as they are now.")
            return 1
        except ValueError as e:
            _err_line(str(e))
            return 1
    output.emit({"ok": True, "dry_run": dry_run, "count": len(chosen), "updates": chosen})
    if dry_run:
        with output.shown():
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
    units = [u for mod in modules.MODULES.values() for unit in mod.units for u in apply._unit_files(unit)]
    output.emit({"units": units})
    for u in units:
        print(u)
    return 0


def _require_root() -> bool:
    """False (with the error and its Fix line) when not root; checked before anything is saved. The caller returns
    `output.NEEDS_SUDO`."""
    if not _no_systemd() and hasattr(os, "geteuid") and os.geteuid() != 0:
        output.need_sudo(_sudo_command("sudo filament-kit modules <command>"))
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
    print(f"Mode: {modules.mode_of(on)} ({', '.join(n for n in modules.MODULES if n in on)})")
    for a in actions:
        if a.kind == "install_file" and a.arg[0] == apply.DROPIN:
            allow = next(ln for ln in a.arg[1].splitlines() if ln.startswith("IPAddressAllow="))
            print(f"Station answers: {allow.split('=', 1)[1]}")
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
    output.emit({"modules": [{"name": n, "title": m.title, "description": m.description, "needs": modules.needs_of(n),
                              "optional_ai": m.optional_ai, "on": n in on} for n, m in modules.MODULES.items()],
                 "setup": modules.mode_of(on)})
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


def cmd_modules_set(mode: str, server: str | None = None) -> int:
    mode = modules.canonical_mode(mode)
    if not _require_root():
        return output.NEEDS_SUDO
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
        _err_line(str(e))
        return 1
    return _save_and_apply(cfg)


def cmd_modules_toggle(name: str, want_on: bool, server: str | None = None, yes: bool = False) -> int:
    if not _require_root():
        return output.NEEDS_SUDO
    cfg = config.load()
    if server:
        err = _server_addr_error(server)
        if err:
            _err_line(err)
            return 1
    notes: list[str] = []
    tty = apply._tty() and not output.json_mode()         # --json never asks
    asked: list[str] = []
    unset: list[str] = []                                   # --json: the settings a question would have asked for

    def _json_confirm(text: str) -> bool:       # --json: a question stops the command with exit 2 (06 6.8)
        asked.append(text)
        return False

    def _json_settings(new_cfg: dict, on) -> None:
        also = ("spoolman_url",) if modules.needs_spoolman_url(on, new_cfg) else ()
        unset.extend(k for k in [*modules.missing_settings(on, new_cfg), *also] if k != "station.allow")

    def _json_address() -> None:
        unset.append("station.allow")

    json_ = output.json_mode()
    err = _change_module(cfg, name, want_on, confirm=(lambda text: True) if yes else _json_confirm if json_ else _tty_confirm,
                         server=server, notes=notes,
                         ask_address=_json_address if json_ else _ask_station_server if tty else None,
                         ask_settings=_json_settings if json_ else _ask_module_settings if tty else None)
    if asked:
        return output.no_terminal(f"turning {name} {'on' if want_on else 'off'} with the modules it "
                                  f"{'needs' if want_on else 'carries'}",
                                  _sudo_command(f"sudo filament-kit modules {'enable' if want_on else 'disable'} {name}")
                                  + " --yes")
    if unset:
        key = unset[0]
        if key == "station.allow":
            output.error("station needs the server's address, and there is no terminal to ask.",
                         "give it with --server:", cmd=_sudo_command(f"sudo filament-kit modules enable {name}") + " --server <address>")
        else:
            output.error(f"{name} needs {key}, and there is no terminal to ask.",
                         "run it again at a terminal without --json to answer it:",
                         cmd=_sudo_command(f"sudo filament-kit modules {'enable' if want_on else 'disable'} {name}")
                         .replace(" --json", ""))
        return output.USAGE
    if err:
        _err_line(err)
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
        return _confirm(f"Roll back to {target}? filament-kit stops while it installs and starts again by itself. "
                        "Settings and data stay.", "rolling back", yes=False)
    try:
        info = updates.check_info(cfg)
    except release.ReleaseError:
        return None
    if not info["newer"]:
        return None
    return _confirm(f"Update to {info['latest']}? filament-kit stops while it installs and starts again by itself. "
                    "Settings and data stay. The version before is kept, so you can roll back.", "updating", yes=False)


def cmd_uninstall(purge: bool, run=None, yes: bool = False) -> int:
    """Run uninstall.sh of the kept release (/opt/filament-kit/releases/<version>/), unpacked outside /opt, which
    it removes. The question and, for --purge, the typed word are asked here (06 7); uninstall.sh asks its own for
    `./uninstall.sh --purge` too, which this answers with the word it was just given."""
    from . import release, updates
    if not _no_systemd() and not _is_root():
        return output.need_sudo(_sudo_command("sudo filament-kit uninstall"))
    kept = _kept_release()
    if kept is None:
        ver = updates.current_version()
        _err_line(f"no kept copy of a release in {updates.store()}, so there is no uninstall.sh to run.\n"
                  f"fix: download filament-kit-{ver}.tar.gz from https://github.com/{release.REPO}/releases, unpack it "
                  f"(tar xzf filament-kit-{ver}.tar.gz), then in its folder run: "
                  + "sudo ./uninstall.sh" + (" --purge" if purge else ""))
        return 1
    if purge:
        stop = _confirm("Remove filament-kit and delete everything it keeps on this machine? Type purge to go on: ",
                        "removing filament-kit and deleting everything it keeps", yes=yes, word="purge")
    else:
        stop = _confirm("Remove filament-kit from this machine? Its data stays unless you add --purge.",
                        "removing filament-kit", yes=yes)
    if stop is not None:
        return stop
    ver, tarball = kept
    running = updates.current_version()
    if ver != running:
        print(f"Using the uninstall.sh of {ver}, the newest kept release: there is no kept copy of {running} "
              f"(the installed version).")
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="filament-kit-uninstall-"))
    try:
        root = release.extract(tarball, ver, work)
        cmd = ["bash", str(root / "uninstall.sh")] + (["--purge"] if purge else [])
        if run is not None:
            return run(cmd)
        if not purge:
            return subprocess.call(cmd)
        kept_word = work / "purge-answer"       # uninstall.sh's own typed word, answered from here
        kept_word.write_text("purge\n")
        with open(kept_word) as answer:
            return subprocess.call(cmd, stdin=answer)
    except (release.ReleaseError, OSError) as e:
        _err_line(f"cannot unpack the kept release {ver}: {e}")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
        return output.need_sudo(_sudo_command("sudo filament-kit reader setup"))
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
    password = ask_secret("Its Wi-Fi password: ")
    if ask_secret("The password again: ") != password:
        _err_line("the two passwords differ; nothing was changed")
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
            return output.no_terminal("writing the firmware", _sudo_command("sudo filament-kit reader setup") + " --yes")
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
                   + f"sudo filament-kit reader revoke {tid}")
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
            return output.no_terminal("writing the firmware", _sudo_command("sudo filament-kit reader setup") + " --yes")
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
                     cmd="sudo filament-kit reader token")
        return output.NEEDS_SUDO
    ssid = a.ssid or ask("Wi-Fi name the reader joins: ").strip()
    password = ask_secret("Its Wi-Fi password: ")
    if ask_secret("The password again: ") != password:
        _err_line("the two passwords differ; nothing was changed")
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
                       + f"filament-kit reader setup --secrets {out} --source <checkout>/reader")
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
                   + f"sudo filament-kit reader revoke {tid}")
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
        return output.need_sudo(_sudo_command("sudo filament-kit web passphrase"))
    try:
        first = secret_input.ask(f"New passphrase, at least {auth.MIN_PASSPHRASE} characters: ")
        second = secret_input.ask("New passphrase again: ")
    except EOFError:
        return _input_ended()
    if first != second:
        _err_line("the two passphrases do not match.")
        return 1
    try:
        dest = write_passphrase(first)
    except GroupMissing as e:
        _err_line(f"{e}; nothing was changed\n"
                  "fix: install the kit first (it creates the filament-kit user and group), "
                  "or: sudo groupadd --system filament-kit")
        return 1
    except ValueError as e:
        _err_line(f"{e}; nothing was changed")
        return 1
    print(f"Passphrase saved ({dest}). Sign-ins from now on use it; existing sessions and connectors stay "
          "signed in.")
    return 0


def cmd_setup_code(new: bool, revoke_trusted: bool = False, yes: bool = False) -> int:
    """`setup-code [--new] [--revoke-trusted]` (root): the code the server's /setup page asks for before any change,
    made when there is none. At a terminal it is printed with the page's address; without one (a log) only the address
    and how to see it, as no secret may end up in a log. A new code keeps trusted computers trusted (the owner's
    choice, said so here); --revoke-trusted forgets them, with or without a new code."""
    from . import setup_code, trusted
    if not _is_root():
        return output.need_sudo(_sudo_command("sudo filament-kit setup-code"))
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
        output.out(f"Setup page: {url}  (see its setup code at a terminal: sudo filament-kit setup-code)")
    if new and not output.quiet():
        print("The old setup code no longer works.")
    if revoke_trusted:
        n = trusted.revoke_all()
        if not output.quiet():
            print(f"{n} trusted computer{'' if n == 1 else 's'} revoked: each needs the setup code again.")
    elif new and not output.quiet():
        n = len(trusted.listing())
        if n:
            output.out(f"Trusted computers stay trusted ({n}): revoke them in Devices on the setup page, or with "
                       + "sudo filament-kit setup-code --revoke-trusted.")
    return 0


def cmd_reader(action: str, name: str | None = None, ref: str | None = None, yes: bool = False) -> int:
    """`reader token [--name X]` (root): a new reader token, printed once for the reader's secrets.h (only its
    sha256 is kept); `reader tokens`: the tokens (id, name, made); `reader revoke <id|name>` (root)."""
    try:
        from .web import reader  # needs the [web] extra
    except ImportError as e:
        _err_line(f"the reader commands need the kit's [web] packages ({e.name or e} is missing); install them "
                  "into the kit's Python: <venv>/bin/python -m pip install 'filament-kit[web]' (or re-run the "
                  "installer, which adds them)")
        return 1
    store = reader.TokenStore()
    if action in ("token", "revoke") and not _is_root():
        return output.need_sudo(_sudo_command(f"sudo filament-kit reader {action}"))
    try:
        if action == "token":
            tid, tok = store.issue(name)
            output.emit({"ok": True, "id": tid, "name": reader._clean_name(name), "token": tok})
            output.out(f"New reader token {tid} ({reader._clean_name(name)}). It is shown only this once:\n\n  {tok}\n\n"
                       "Put it in the reader's src/secrets.h as READER_TOKEN, then build and flash (reader/README.md).\n"
                       "Remove it later with: " + f"sudo filament-kit reader revoke {tid}")
            return 0
        if action == "tokens":
            rows = store.list()
            output.emit(rows)
            if not rows:
                output.out("No reader tokens yet. Make one with:")
                output.out("  sudo filament-kit reader token --name printer-station")
                return 0
            output.out_lines(output.table(["Id", "Name", "Made"], [[t["id"], t["name"], t["created"]] for t in rows],
                                          long=1, whole=True))   # `reader revoke` takes the id or the name
            return 0
        rows = store.list()
        if len([t for t in rows if t["id"] == ref] or [t for t in rows if t["name"] == ref]) == 1:   # one that is there
            stop = _confirm(f"Revoke the token {ref}? A reader using it is refused from now on. Set it up again with "
                            "sudo filament-kit reader setup to give it a new token.", f"revoking the token {ref}", yes=yes)
            if stop is not None:
                return stop
        if store.revoke(ref or ""):
            print(f"revoked {ref}; a reader using it is refused from now on")
            return 0
        _err_line(f"no single reader token {ref!r} (see: filament-kit reader tokens)")
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


def cmd_local_intake_status() -> int:
    cfg = config.load()
    if "local_intake" not in modules.enabled(cfg):
        _err_line("the local_intake module is off.\nfix: sudo filament-kit modules enable local_intake")
        return 1
    return 0 if status_rows.print_rows(status_rows.local_reader_rows(cfg)) else 1


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
                                  _sudo_command("sudo filament-kit local-intake install") + " --yes")
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
                  + "filament-kit local-intake status")
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


def cmd_local_intake_token(remove: bool) -> int:
    """Set (hidden prompt) or remove the local reader's bearer token, <etc>/local_intake_token (root). Never printed."""
    from . import local_reader
    if not _is_root() and not _no_systemd():
        return output.need_sudo(_sudo_command("sudo filament-kit local-intake token"))
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


def cmd_local_intake_test(photos: list[str]) -> int:
    """Read photos with the local reader only (no cloud, no daily read used) and print what it read."""
    from . import intake
    cfg = config.load()
    if "local_intake" not in modules.enabled(cfg):
        _err_line("the local_intake module is off.\nfix: sudo filament-kit modules enable local_intake")
        return 1
    try:
        images = intake.check_photos([(p, Path(p).read_bytes()) for p in photos])
    except OSError as e:
        _err_line(f"{e.filename}: {e.strerror}")
        return 1
    except intake.PhotoError as e:
        _err_line(str(e))
        return 1
    try:
        with output.wait(f"Reading {len(images)} photo{'' if len(images) == 1 else 's'} with On this Hub…"):
            out = intake._call(Spoolman(cfg["spoolman_url"]), images, "", None, None, readers=["local"])
    except intake.ReadError as e:
        _err_line(str(e))
        return 1
    except SpoolmanError as e:
        _err_line(f"Spoolman: {e}")
        return 1
    output.emit({"ok": True, **out})
    conf = out.get("confidence")
    print(f"Read by the local reader ({out.get('tier') or '?'} tier"
          + (f", {round(conf * 100)} % sure" if conf is not None else "") + (", unsure" if out.get("unsure") else "")
          + (f", {out['usage']['ms'] / 1000:.1f} s" if out["usage"].get("ms") is not None else "") + "):")
    for it in out["items"]:
        colour = it.get("color_name") or "?"
        print(f"  {it['vendor']} {it['name']} ({it['material']}), colour {colour}"
              + (f" #{it['color_hex']}" if it.get("color_hex") else "")
              + f", {it['count']} x {it['net']} g, {'sealed' if it.get('sealed') else 'opened'}; {it['match']}"
              + (f"; {round(it['confidence'] * 100)} % sure" if it.get("confidence") is not None else ""))
    for q in out.get("questions") or []:
        print(f"  question: {q}")
    return 0


_invoked: list[str] = []      # the arguments of this run, for the Fix line of a command that needs root


def _sudo_command(fallback: str) -> str:
    """The command that was run with `sudo` in front, so the Fix line holds it whole; `fallback` when `main` did not
    record it."""
    return "sudo filament-kit " + shlex.join(_invoked) if _invoked else fallback


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
            output.error(f"{where}permission denied.", "run it with sudo:", cmd=_sudo_command("sudo filament-kit"))
            return output.NEEDS_SUDO
        except KeyboardInterrupt:
            output.out("Stopped.")
            return output.INTERRUPTED
    with output.children_to_stderr():       # --json, --quiet: what a child prints on standard output goes to standard error
        return output.run_json(run) if output.json_mode() else run()


def _add_yes(parser, help: str = "answer yes to the question this command asks (a script has no terminal to ask on)") -> None:
    parser.add_argument("-y", "--yes", action="store_true", help=help)


class _Parser(argparse.ArgumentParser):
    """A wrong command or option is an error in the words of 06 6.5 (exit code 2), not argparse's own."""

    def error(self, message: str):
        output.error(message, f"see what it takes with: {self.prog} -h")
        raise SystemExit(output.USAGE)


def _main(argv: list[str] | None = None, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    ap = _Parser(prog="filament-kit")
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
    fpp = stp_sub.add_parser("flash-panel", help="write the panel firmware to a blank ESP32-C3 board, after you "
                                                 "confirm the port")
    fpp.add_argument("--port", help="the board's serial port (/dev/ttyACM0): only that one is offered")
    _add_yes(fpp)
    stp_sub.add_parser("pairing-state", help="print whether the button flow is paired, as one line")
    pkind.add_argument("--text", action="store_true", help="print the pairing link as text instead of a QR code")
    up = sub.add_parser("unpair", help="list or remove paired phones")
    up.add_argument("device_id", nargs="?")
    _add_yes(up)
    sub.add_parser("config", help="interactive settings menu")
    sub.add_parser("cert", help="create the server certificate if missing")
    ih = sub.add_parser("intake", help="the intake history: the last spool additions, their photos, revisions")
    isub = ih.add_subparsers(dest="intake_cmd", required=True)
    isub.add_parser("history", help="the newest records first, with their photo files")
    ish = isub.add_parser("show", help="one record with its revisions")
    ish.add_argument("id")
    irv = isub.add_parser("revise", help="ask the AI again with a note, e.g. --note 'brand is Polymaker'")
    irv.add_argument("id")
    irv.add_argument("--note", required=True)
    irv.add_argument("--item", type=int, default=None)
    _add_yes(irv, "apply the proposal without asking")
    ied = isub.add_parser("edit", help="change saved values by hand: field=value ...")
    ied.add_argument("id")
    ied.add_argument("values", nargs="+", metavar="field=value")
    ied.add_argument("--item", type=int, default=None)
    ied.add_argument("--spools", default=None, help="only these of the item's spools, e.g. 41,42 (default: all)")
    iun = isub.add_parser("undo", help="undo the record's newest revision")
    iun.add_argument("id")
    sub.add_parser("ensure-fields", help="create the Spoolman extra fields")
    pr = sub.add_parser("printer", help="printer tasks: map slots, forget a certificate")
    psub = pr.add_subparsers(dest="printer_cmd", required=True)
    pm = psub.add_parser("map", help="map the AMS slots (changes slot colours briefly, runs a no-motion job)")
    pm.add_argument("serial")
    pm.add_argument("--manual", action="store_true",
                    help="map by loading filament: you load each slot, the printer says which one it sees (needs the "
                         "running server; the same session as the setup page and the phone apps)")
    _add_yes(pm, "answer yes to the question before mapping (not asked with --manual)")
    prp = psub.add_parser("report", help="make a report that helps add a printer or AMS the kit doesn't know yet")
    prp.add_argument("serial")
    pu = psub.add_parser("unpin", help="forget a Bambu printer's pinned TLS certificate (asks for its Access Code)")
    pu.add_argument("serial")
    _add_yes(pu)
    lb = sub.add_parser("library", help="the filament spec library: status, update, rollback, local additions")
    lsub = lb.add_subparsers(dest="library_cmd", required=True)
    lsub.add_parser("status", help="show the library version, local additions and the last update check")
    lu = lsub.add_parser("update", help="download or update the library (library.url)")
    lu.add_argument("--scheduled", action="store_true", help="only if config library.schedule says it is due")
    _add_yes(lsub.add_parser("rollback", help="go back to the library version before the last update"))
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
    _add_yes(au, "accept without asking (a script has no terminal to ask on)")
    md = sub.add_parser("modules", help="the switchable parts of the kit: apply the settings, list units")
    mdsub = md.add_subparsers(dest="modules_cmd", required=True)
    mda = mdsub.add_parser("apply", help="install, start and stop what config.json's modules say (root)")
    mda.add_argument("--no-pair", action="store_true", help="show no pairing code at the end (the setup page)")
    mdsub.add_parser("list", help="show each module on/off and the mode")
    mm = mdsub.add_parser("menu", help="the module checklist (cursor keys move, Space switches, a/s/t presets, Enter applies)")
    mm.add_argument("--raw", action="store_true", help="print the chosen modules as a comma list; change nothing")
    ms = mdsub.add_parser("set", help="switch to an install mode and apply (root)")
    ms.add_argument("mode", choices=[*modules.MODES, *modules.MODE_ALIASES])
    ms.add_argument("--server", "--hub", dest="server", help="the kit server's name or IP (station mode)")
    me = mdsub.add_parser("enable", help="turn a module on and apply (root)")
    me.add_argument("name")
    me.add_argument("--server", "--hub", dest="server", help="the kit server's name or IP (when enabling station without a server)")
    _add_yes(me, "also turn on the modules it needs, without asking (a script has no terminal to ask on)")
    mx = mdsub.add_parser("disable", help="turn a module off and apply; its data is kept (root)")
    mx.add_argument("name")
    _add_yes(mx, "also turn off the modules that depend on it, without asking (a script has no terminal to ask on)")
    mdsub.add_parser("units", help="print every systemd unit of every module, one per line")
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
    rd = sub.add_parser("reader", help="the Printer Station reader tokens: make, list, revoke")
    rdsub = rd.add_subparsers(dest="reader_cmd", required=True)
    rdt = rdsub.add_parser("token", help="make a reader token and print it once, for secrets.h (root)")
    rdt.add_argument("--name", help="what the token is for, e.g. printer-station")
    rdsub.add_parser("tokens", help="list the reader tokens (never the tokens themselves)")
    rdr = rdsub.add_parser("revoke", help="remove a reader token (root)")
    rdr.add_argument("ref", help="its id (r1 ...) or name")
    _add_yes(rdr)
    rds = rdsub.add_parser("setup", help="set up the Printer Station plugged into this server's USB: the kit's "
                                         "firmware, then its Wi-Fi and token (root to make the token). --source or "
                                         "--out build it with PlatformIO instead")
    rds.add_argument("--name", help="what its token is for, e.g. printer-station")
    _add_yes(rds, "answer yes to the question before writing the firmware to the board (the one found, or --port)")
    rds.add_argument("--ssid", help="the Wi-Fi network it joins (asked if left out); the password is always asked")
    rds.add_argument("--source", help="the reader's source folder (a checkout's reader/): build and flash it here")
    rds.add_argument("--port", help="its USB serial port (found when one ESP32 board is plugged in, which you are asked to confirm)")
    rds.add_argument("--out", help="write its secrets.h here (0600) to build elsewhere")
    rds.add_argument("--ota-pubkey", help="the PEM public key OTA images are signed with (ota_publish.py --init-key)")
    rds.add_argument("--token-file", help="a token made on the server (reader token) instead of a new one")
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
    bk = sub.add_parser("backup", help="a whole-kit backup as one zip: make one, list them (root)")
    bksub = bk.add_subparsers(dest="backup_cmd", required=True)
    bkc = bksub.add_parser("create", help="write a backup zip (default: into /var/backups/filament-kit)")
    bkc.add_argument("--out", help="the folder to write it into")
    bksub.add_parser("list", help="the backups in /var/backups/filament-kit")
    rs = sub.add_parser("restore", help="bring this machine to the state in a backup zip (root)")
    rs_what = rs.add_mutually_exclusive_group(required=True)
    rs_what.add_argument("zip", nargs="?", help="the backup zip")
    rs_what.add_argument("--uploaded", action="store_true", help="the zip the setup page received")
    _add_yes(rs, "ask nothing, the typed word included (no terminal: the installer, the setup page)")
    rm_ = sub.add_parser("remote", help="remote access: get the certificate, show the firewall rules")
    rmsub = rm_.add_subparsers(dest="remote_cmd", required=True)
    _add_yes(rmsub.add_parser("issue", help="get the certificate with certbot (standalone on port 80) (root)"))
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
    if output.json_mode():
        refused = _json_refusal(args)
        if refused is not None:
            return refused
    with output.muted() if _reports_results(args) else contextlib.nullcontext():
        return _dispatch(args, client_factory=client_factory, manager_factory=manager_factory, sm_factory=sm_factory)


def _sub_of(a) -> str | None:
    """The word after the command: `backup create` is `create`."""
    for name in ("station_cmd", "intake_cmd", "printer_cmd", "library_cmd", "profiles_cmd", "modules_cmd", "web_cmd",
                 "li_cmd", "reader_cmd", "backup_cmd", "remote_cmd", "klipper_cmd"):
        if hasattr(a, name):
            return getattr(a, name)
    return None


def _json_refusal(a) -> int | None:
    """06 6.8: the menus take no `--json`, and a command that needs typed answers has nothing to ask them on. The exit
    code (2) when this is one of them, after its Error and Fix."""
    c, sub = a.cmd, _sub_of(a)
    if c == "config":
        output.error("config is a menu.", "use filament-kit config show --json")
        return output.USAGE
    if c == "modules" and sub == "menu":
        output.error("modules menu is a menu.", "use filament-kit modules list --json")
        return output.USAGE
    asks = ((c == "station" and sub == "pair" and not a.local, "station pair"),
            (c == "reader" and sub == "setup" and not a.pending, "reader setup"),
            (c == "web" and sub == "passphrase", "web passphrase"),
            (c == "local-intake" and sub == "token" and not a.remove, "local-intake token"),
            (c == "printer" and sub == "unpin", "printer unpin"),
            (c == "printer" and sub == "map" and a.manual, "printer map --manual"),
            (c == "klipper" and sub == "api-key", "klipper api-key"))
    for yes, name in asks:
        if yes:
            output.error(f"{name} asks for typed answers, and --json does not ask.", "run it without --json.")
            return output.USAGE
    return None


# `--quiet`: the commands whose standard output is only results (06 6.8 drops them). Every other command prints what it
# exists to print there (a list, a detail, an answer, a link or token) or is a screen, and stays as it is.
_RESULTS_ONLY = {("station", "flash-panel"), ("backup", "create"), ("restore", None), ("intake", "edit"),
                 ("intake", "undo"), ("ensure-fields", None), ("printer", "report"), ("printer", "unpin"),
                 ("library", "update"), ("library", "rollback"), ("library", "adopt"), ("library", "add"),
                 ("profiles", "build"), ("profiles", "set-parent"), ("profiles", "restore-deleted"),
                 ("profiles", "apply-updates"), ("modules", "apply"), ("modules", "set"), ("modules", "enable"),
                 ("modules", "disable"), ("web", "passphrase"), ("local-intake", "install"),
                 ("local-intake", "remove"), ("local-intake", "token"), ("reader", "revoke"), ("remote", "issue"),
                 ("uninstall", None), ("update", None), ("klipper", "add"), ("klipper", "set")}


def _reports_results(a) -> bool:
    """Is this run, with `--quiet`, a command whose standard output is only results."""
    if not output.quiet():
        return False
    c, sub = a.cmd, _sub_of(a)
    if c == "station" and sub == "pair":
        return a.local
    if c == "printer" and sub == "map":
        return not a.manual
    if c == "unpair":
        return a.device_id is not None
    if c == "update":
        return not a.check
    return (c, sub) in _RESULTS_ONLY


def _dispatch(args, *, client_factory=None, manager_factory=None, sm_factory=None) -> int:
    if args.cmd == "klipper":
        return klipper_cli.run(args)
    if args.cmd == "status":
        return cmd_status(client_factory or _default_client, station_pairing=args.station_pairing)
    if args.cmd == "pair":
        return cmd_pair(pc=args.pc, station=args.station, text=args.text)
    if args.cmd == "station" and args.station_cmd == "pair" and args.local:
        return cmd_station_pair_local()
    if args.cmd == "station" and args.station_cmd == "flash-panel":
        return cmd_station_flash_panel(yes=args.yes, only_port=args.port)
    if args.cmd == "station":
        return cmd_station_pairing_state() if args.station_cmd == "pairing-state" else cmd_station_pair()
    if args.cmd == "unpair":
        return cmd_unpair(args.device_id, yes=args.yes)
    if args.cmd == "config":
        return cmd_config()
    if args.cmd == "intake":
        return cmd_intake(args)
    if args.cmd == "cert":
        return cmd_cert()
    if args.cmd == "printer":
        if args.printer_cmd == "map":
            return cmd_printer_map(args.serial, manager_factory or _default_manager, manual=args.manual, yes=args.yes)
        if args.printer_cmd == "report":
            return cmd_printer_report(args.serial, manager_factory or _default_manager)
        return cmd_printer_unpin(args.serial, yes=args.yes)
    if args.cmd == "library":
        if args.library_cmd == "status":
            return cmd_library_status()
        if args.library_cmd == "update":
            return cmd_library_update(args.scheduled)
        if args.library_cmd == "rollback":
            return cmd_library_rollback(yes=args.yes)
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
            return cmd_profiles_apply_updates(args.line_id, args.all_, args.dry_run, yes=args.yes)
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
        if args.li_cmd == "remove":
            return cmd_local_intake_remove(args.yes)
        return cmd_local_intake_status() if args.li_cmd == "status" else cmd_local_intake_test(args.photos)
    if args.cmd == "reader" and args.reader_cmd == "setup":
        return cmd_reader_setup(args)
    if args.cmd == "reader":
        return cmd_reader(args.reader_cmd, getattr(args, "name", None), getattr(args, "ref", None),
                          yes=getattr(args, "yes", False))
    if args.cmd == "backup":
        return cmd_backup(args.backup_cmd, args.out if args.backup_cmd == "create" else None)
    if args.cmd == "restore":
        return cmd_restore(args.zip, uploaded=args.uploaded, yes=args.yes)
    if args.cmd == "remote":
        from . import remote
        cfg = config.load()
        if args.remote_cmd != "issue":
            return remote.firewall(cfg)
        if "remote" in modules.enabled(cfg) and (_no_systemd() or _is_root()):     # else `issue` says what is wrong
            stop = _confirm("Get the certificate now? Port 80 on your router must reach this kit server while it runs. "
                            "filament-kit never changes your firewall or router.", "getting the certificate",
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
                                      getattr(args, "server", None), yes=args.yes)
        return cmd_modules_apply(pair=not args.no_pair)
    if args.cmd == "setup-code":
        return cmd_setup_code(args.new, args.revoke_trusted, yes=args.yes)
    return cmd_ensure_fields()
