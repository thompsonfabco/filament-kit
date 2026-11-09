"""The root side of the kit server's /setup page (setup_page.py): the few writes the server, running as
filament-kit, cannot make itself, because they land in root's /etc/filament-kit or start a `modules apply`.

How it runs: `filament-kit-setup.socket` listens on /run/filament-kit-setup/setup.sock (root:filament-kit 660, so only
the service user and root can connect) with Accept=yes; each connection starts one `filament-kit-setup@.service`
(root, ProtectSystem=strict, writes only /etc/filament-kit) running `python -I -m filament_kit.setup_helper`, which
reads ONE request line (JSON, at most MAX_REQUEST bytes) from the socket, answers ONE line and exits.

What it accepts is a closed list (`OPS`), never a command, a path or a file name:

    check                                      only the code check: the page's own writes (printers, pairings,
                                               readers) ask this first; the server never checks a code itself
    key_set {key}  key_remove                  the Anthropic key (cli.write_key / cli.remove_key)
    passphrase_set {passphrase}                the web passphrase (cli.write_passphrase: scrypt, root:filament-kit 640)
    library_token_set {token}  library_token_remove   /etc/filament-kit/github_token (library.write_token)
    module {name, on[, settings]}              one module on/off with the checklist's rules (modules.toggle,
                                               cli._apply_selection, cli._plan_error), saved, then an apply
    setting {key, value}                       web.public_url or station.url, checked, saved, then an apply
    mode {mode[, settings]}                    a mode preset (modules.set_mode, as `modules set`), saved, then an apply;
                                               never a mode without the server, which this page is part of
    apply                                      start the job `apply`
    job {name}                                 start one of the closed list of jobs (JOBS), one at a time
    journal {unit, lines}                      the last lines (at most 200) of a service of a module that is on, by an
                                               argument list; read only, at most JOURNAL_MAX bytes back
    station_pairing                            server_api.pairing_state(): the station's pairing folder is closed to the
                                               service user, so a whole Overview asks here
    trust_status {token}                       is this cookie's computer trusted (no code: it says nothing else)
    trust_add {name}                           trust a computer, only with the typed code; the one reply holding a secret,
                                               which goes to the browser's cookie and nowhere else
    trust_list  trust_rename {id, name}  trust_revoke {id}  trust_revoke_all  trust_enabled {enabled}

Every request carries the setup code and the page's client address, and this process is the only place a code is
checked (setup_code.check on the root-only hash, against the per-client and global lockout in
/etc/filament-kit/setup_lockout), before it reads anything else: a local process that reaches the socket without
the code can change nothing. A trusted computer's token stands in for the code here and nowhere else (trusted.py). Only root and the filament-kit user may connect (SO_PEERCRED; the socket is 660 and
the web unit cannot see it). The request must arrive within READ_TIMEOUT seconds. Values are never logged, never echoed in a reply, never put in a
command line. What the CLI functions print goes to the journal (stderr), not into the reply.

Jobs: long work runs in its own unit, `filament-kit-setup-job@<name>.service` (`python -I -m filament_kit.setup_helper
job-run <name>`), so it goes on when it restarts the kit server (and the page with it). The name passes the closed list
here, is the unit's instance, and is checked against the list again by the job; no argument is ever a secret, since
instance names show in systemctl and the journal. The job runs the same command the CLI has, with its output in
/run/filament-kit-setup/job.log (root:filament-kit 640), which the page reads. Without a terminal those
commands print neither the setup code nor a pairing link. filament-kit-setup-apply.service, the name up to 0.4.0, stays
for one release and runs the job `apply` (`apply-run`)."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

try:
    import fcntl
except ImportError:  # Windows dev PCs: tests only
    fcntl = None

from . import config, modules, setup_code, trusted

log = logging.getLogger(__name__)

MAX_REQUEST = 16 * 1024
READ_TIMEOUT = 5.0
JOB_PREFIX = "filament-kit-setup-job@"              # one instance per job: filament-kit-setup-job@update.service
APPLY_UNIT = "filament-kit-setup-apply.service"     # the job unit's name up to 0.4.0
UPDATE_UNIT = "filament-kit-update.service"         # the timer's update; `sudo filament-kit update` at a terminal has no unit
ACTIVE = ("activating", "active", "deactivating", "reloading")      # a oneshot is "activating" while it runs
# The closed list of jobs: the `filament-kit` arguments each one runs.
JOBS = {"apply": ("modules", "apply", "--no-pair"), "update": ("update",), "rollback": ("update", "--rollback"),
        "check": ("update", "--check"), "station_pair": ("station", "pair", "--local"),
        "library_update": ("library", "update"), "library_rollback": ("library", "rollback")}
WRAPPER = "/usr/local/bin/filament-kit"
FINISHED = "==> finished (exit"
SETTINGS = ("web.public_url", "station.url")
JOURNAL_MAX = 64 * 1024
JOURNAL_LINES = 200
WRONG = "wrong setup code"
TRUST_GONE = "this computer is no longer trusted: type the setup code"
TRUST_OFF = "trusted computers are turned off (Devices)"
LOCKED = ("too many wrong setup codes: wait 10 minutes (longer after many from everywhere), or make a new code "
          "at the server, which also lifts the lock: sudo filament-kit setup-code --new")
NO_CODE = "no setup code is set on this server yet; make one at the server: sudo filament-kit setup-code"
APPLYING = "the last change is still being applied; wait until it has finished"
BUSY = {"apply": APPLYING, "update": "an update is running; wait until it has finished",
        "rollback": "a rollback is running; wait until it has finished",
        "check": "the check for updates is running; try again in a moment",
        "station_pair": "the station is being paired; wait until it has finished",
        "library_update": "the library is being updated; wait until it has finished",
        "library_rollback": "the library is going back; wait until it has finished"}
# the checklist's setting prompts, back to their keys (cli._apply_selection asks by prompt)
_PROMPT_KEYS = {v: k for k, v in modules._SETTING_PROMPTS.items()}


class Refused(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def run_dir() -> Path:
    return Path(os.environ.get("FK_SETUP_RUN", "/run/filament-kit-setup"))


def apply_log() -> Path:
    """Where 0.4.0's page reads its apply: never written now; removed by a job, so a rollback finds no stale one."""
    return run_dir() / "apply.log"


def job_log() -> Path:
    return run_dir() / "job.log"


def job_unit(name: str) -> str:
    return f"{JOB_PREFIX}{name}.service"


def header(name: str) -> str:
    return "==> filament-kit " + " ".join(JOBS[name])


def job_name_of(first_line: str) -> str | None:
    """Which job a log's first line names."""
    return next((n for n in JOBS if header(n) == first_line.strip()), None)


def _no_systemd() -> bool:
    return os.environ.get("FK_NO_SYSTEMD") == "1"


# ---------- the request ----------

def _text(req: dict, key: str, limit: int, *, word: bool = False, blank: bool = False) -> str:
    """A text field: at most `limit` characters, printable; `word`: no spaces inside; `blank`: may be empty."""
    v = req.get(key)
    if not isinstance(v, str):
        raise Refused(400, f"{key} must be text")
    v = v.strip()
    if (not v and not blank) or len(v) > limit or not v.isprintable() or (word and any(c.isspace() for c in v)):
        raise Refused(400, f"{key} is not usable" + (": one word of printable characters" if word else ""))
    return v


def _check_code(text, client) -> None:
    lock = setup_code.Lockout(setup_code.lockout_file())
    ticket = lock.attempt(client if isinstance(client, str) else "?")
    if ticket is None:
        raise Refused(429, LOCKED)
    ok = setup_code.check(text)
    if ok is None:
        lock.release(ticket)
        raise Refused(503, NO_CODE)
    if not ok:
        raise Refused(403, WRONG)
    lock.release(ticket, ok=True)


_HOSTNAME = re.compile(r"(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}"
                       r"[A-Za-z0-9])?)*\.?")


def _no_dns(host: str) -> list[str]:
    """apply.plan's `resolve` here: the helper has no network (PrivateNetwork), so a station.allow name is only
    checked for its form; the apply unit resolves it."""
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    if not _HOSTNAME.fullmatch(str(host)):
        raise OSError(f"{host!r} is not a host name")
    return [host]


def _plan_error(cfg: dict) -> str | None:
    """cli._plan_error without name lookups (see _no_dns)."""
    from . import apply
    try:
        apply.plan(cfg, resolve=_no_dns)
    except modules.ModuleError as e:
        return str(e)
    return None


class CannotTell(subprocess.SubprocessError):
    """systemctl gave no answer (it can fail during a daemon-reload): not the same as "nothing is running"."""


def _asked(*args: str) -> str:
    """What systemctl says. No match, or a unit that doesn't exist, is still exit 0 with nothing or "inactive"."""
    r = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=30, check=False)
    if r.returncode != 0:
        raise CannotTell(f"systemctl {args[0]} exited {r.returncode}")
    return r.stdout


def _running_jobs() -> list[str]:
    """The jobs whose unit is running or queued. list-units takes a pattern, `show` does not; --all because a oneshot
    is "activating" while it runs and a queued one still "inactive", which list-jobs shows."""
    names: list[str] = []
    pattern = JOB_PREFIX + "*"
    units = _asked("list-units", "--all", "--plain", "--no-legend", pattern)
    queued = _asked("list-jobs", "--plain", "--no-legend", pattern)
    for line in units.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0].startswith(JOB_PREFIX) and f[2] in ACTIVE:
            names.append(f[0][len(JOB_PREFIX):].removesuffix(".service"))
    for line in queued.splitlines():
        unit = next((w for w in line.split() if w.startswith(JOB_PREFIX)), None)
        if unit:
            names.append(unit[len(JOB_PREFIX):].removesuffix(".service"))
    return names


def _applying() -> bool:
    """True while a job's unit runs or is queued (one job at a time), under either unit name. Raises CannotTell: the
    guards then refuse, and the log's reader keeps calling the job running."""
    if _no_systemd():
        return False
    return bool(_running_jobs()) or bool(_other_units())


def _other_units() -> list[str]:
    """The old job unit and the timer's update, when they run."""
    out = []
    for unit in (APPLY_UNIT, UPDATE_UNIT):
        if _asked("show", "--property=ActiveState", "--value", unit).strip() in ACTIVE:
            out.append(unit)
    return out


def _busy_text() -> str:
    if not _no_systemd():
        try:
            names = _running_jobs()
            if names:
                return BUSY.get(names[0], APPLYING)
            if UPDATE_UNIT in _other_units():
                return BUSY["update"]
        except CannotTell:      # it answered a moment ago that something runs: the log's first line can still name it
            pass
    try:
        with open(job_log(), encoding="utf-8", errors="replace") as fh:
            return BUSY.get(job_name_of(fh.readline()), APPLYING)
    except OSError:
        return APPLYING


@contextmanager
def _job_lock():
    """Held from the check through any save to the start: the socket starts one helper per connection (Accept=yes), and two
    could both see nothing running, or both save and one then be told it's busy. In /etc/filament-kit, the one place this
    helper may write."""
    if _no_systemd():
        yield
        return
    fd = os.open(config.paths().etc / "job.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _start_job(name: str, why: str = "") -> None:
    if name not in JOBS:
        raise Refused(400, "no such job")
    if _no_systemd():
        return
    _not_applying()
    unit = job_unit(name)
    r = subprocess.run(["systemctl", "start", "--no-block", unit], capture_output=True, text=True,
                       timeout=60, check=False)
    if r.returncode != 0:
        log.error("setup helper: cannot start %s: %s", unit, r.stderr.strip())
        raise Refused(500, why or f"the job did not start; at the server: sudo filament-kit {' '.join(JOBS[name])}")


def _start_apply() -> None:
    _start_job("apply", "saved, but the apply did not start; run at the server: sudo filament-kit modules apply")


def _not_applying() -> None:
    try:
        busy = _applying()
    except CannotTell:
        log.warning("setup helper: systemctl gave no answer on what is running")
        raise Refused(503, "The server can't tell whether a job is running just now. Try again in a moment.") from None
    if busy:
        raise Refused(409, _busy_text())


# ---------- the operations ----------

def _key_set(req: dict) -> dict:
    from . import cli
    cli.write_key(_text(req, "key", 400, word=True))
    return {}


def _key_remove(req: dict) -> dict:
    from . import cli
    return {"removed": cli.remove_key()}


def _passphrase_set(req: dict) -> dict:
    from . import cli
    v = req.get("passphrase")
    if not isinstance(v, str) or len(v) > 1024:
        raise Refused(400, "passphrase must be text")
    try:
        cli.write_passphrase(v)
    except cli.GroupMissing as e:
        raise Refused(500, f"{e}; nothing was changed") from None
    except ValueError as e:
        raise Refused(400, str(e)) from None
    return {}


def _library_token_set(req: dict) -> dict:
    from . import library
    library.write_token(_text(req, "token", 400, word=True))
    return {}


def _library_token_remove(req: dict) -> dict:
    from . import library
    return {"removed": library.remove_token()}


def _answers(raw) -> dict[str, str]:
    """The settings a module needs (web.public_url, orders.file), as the checklist would ask for them."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise Refused(400, "settings must be an object")
    out = {}
    for key, value in raw.items():
        if key not in _PROMPT_KEYS.values() or not isinstance(value, str) or len(value) > 300:
            raise Refused(400, f"unknown or unusable setting {str(key)[:40]!r}")
        err = modules.check_setting(key, value)
        if err:
            raise Refused(400, f"{key}: {err}")
        if key == "orders.file":
            _orders_file(value.strip())
        out[key] = value.strip()
    return out


def _orders_file(value: str) -> None:
    """The order history file must be a regular .json file in the kit's state folder (the server reads it as the
    service user; the page may not point it anywhere else)."""
    state = config.paths().state.resolve()
    p = Path(value)
    try:
        real = p.resolve(strict=True)
    except (OSError, RuntimeError):
        real = None
    if (not p.is_absolute() or p.suffix.lower() != ".json" or real is None or not real.is_file()
            or state not in real.parents):
        raise Refused(400, f"orders.file must be an existing .json file in {state}")


def _module(req: dict) -> dict:
    from . import cli
    name, want = req.get("name"), req.get("on")
    if name not in modules.MODULES or not isinstance(want, bool):
        raise Refused(400, "name must be a module and on true or false")
    if name == "server" and not want:
        raise Refused(409, "this page is the server module's: switch it off at the server: "
                           "sudo filament-kit modules disable server")
    answers = _answers(req.get("settings"))
    _not_applying()
    cfg = config.load()
    on = modules.enabled(cfg)
    if (name in on) == want:
        return {"changed": False, "notes": []}
    chosen, notes = modules.toggle(on, name)
    need = [k for k in modules.missing_settings(chosen, cfg) if k not in answers and k != "station.allow"]
    if need:
        raise Refused(400, f"{name} needs {', '.join(need)} first", needs=need)
    err = cli._apply_selection(cfg, chosen, ask=lambda prompt: answers.get(_PROMPT_KEYS.get(prompt, "")))
    if err is None:
        err = _plan_error(cfg)
    if err:
        raise Refused(400, err)
    config.save(cfg)
    _start_apply()
    return {"changed": True, "notes": notes, "modules": sorted(modules.enabled(cfg))}


def station_url_error(value: str) -> str | None:
    """Why `value` is not a station address (http(s)://<host>[:port], nothing else), or None."""
    try:
        u = urlparse(value)
        u.port
    except ValueError:
        return "give the station's address, e.g. http://station.local:5003"
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment \
            or u.path not in ("", "/"):
        return "give the station's address, e.g. http://station.local:5003"
    return None


def _setting(req: dict) -> dict:
    key = req.get("key")
    if key not in SETTINGS:
        raise Refused(400, "key must be one of: " + ", ".join(SETTINGS))
    value = _text(req, "value", 300, word=True, blank=True)
    if value:
        err = modules.check_setting(key, value) if key == "web.public_url" else station_url_error(value)
        if err:
            raise Refused(400, err)
    _not_applying()
    cfg = config.load()
    modules.set_setting(cfg, key, value.rstrip("/") if key == "station.url" and value else (value or None))
    try:
        modules.validate(cfg)
    except modules.ModuleError as e:
        raise Refused(400, str(e)) from None
    err = _plan_error(cfg)
    if err:
        raise Refused(400, err)
    config.save(cfg)
    _start_apply()
    return {}


def _mode(req: dict) -> dict:
    """A mode preset, as `modules set` does it (a module switched on by hand stays on, see modules.set_mode)."""
    mode = req.get("mode")
    if mode not in modules.MODES:
        raise Refused(400, "mode must be one of: " + ", ".join(modules.MODES))
    if "server" not in modules.MODES[mode]:
        raise Refused(409, "this page is the server module's, and that mode has none: at the server: "
                           f"sudo filament-kit modules set {mode} --server <the kit server's address>")
    answers = _answers(req.get("settings"))
    _not_applying()
    cfg = config.load()
    notes: list[str] = []
    try:
        out = modules.set_mode(cfg, mode, say=notes.append)
        for key, value in answers.items():
            modules.set_setting(out, key, value)
        need = [k for k in modules.missing_settings(modules.enabled(out), out)
                if k not in answers and k != "station.allow"]
        if need:
            raise Refused(400, f"{mode} needs {', '.join(need)} first", needs=need)
        modules.validate(out)
    except modules.ModuleError as e:
        raise Refused(400, str(e)) from None
    if out == cfg:
        return {"changed": False, "notes": notes}
    err = _plan_error(out)
    if err:
        raise Refused(400, err)
    config.save(out)
    _start_apply()
    return {"changed": True, "notes": notes, "modules": sorted(modules.enabled(out))}


def journal_units(cfg: dict) -> list[str]:
    """The services of the modules that are on: the only units `journal` reads."""
    from . import apply
    on = modules.enabled(cfg)
    units = [f for n, m in modules.MODULES.items() if n in on for u in m.units for f in apply._unit_files(u)]
    return sorted({u for u in units if u.endswith(".service") and "@" not in u})


def _journal(req: dict) -> dict:
    unit, lines = req.get("unit"), req.get("lines", 100)
    if not isinstance(unit, str) or unit not in journal_units(config.load()):
        raise Refused(400, "unit must be a service of a module that is on")
    if not isinstance(lines, int) or isinstance(lines, bool) or not 1 <= lines <= JOURNAL_LINES:
        raise Refused(400, f"lines must be a whole number from 1 to {JOURNAL_LINES}")
    if _no_systemd():
        return {"unit": unit, "text": "", "truncated": False}
    r = subprocess.run(["journalctl", "-u", unit, "-n", str(lines), "-o", "short-iso", "--no-pager"],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
    if r.returncode != 0:
        log.error("setup helper: journalctl for %s exited %s", unit, r.returncode)
        raise Refused(500, f"could not read the log; at the server: sudo journalctl -u {unit}")
    out = r.stdout
    cut = len(out) > JOURNAL_MAX
    if cut:
        out = out[-JOURNAL_MAX:]
        out = out[out.find(b"\n") + 1:]        # from a whole line
    return {"unit": unit, "text": out.decode("utf-8", "replace"), "truncated": cut}


def _job(req: dict) -> dict:
    name = req.get("name")
    if not isinstance(name, str) or name not in JOBS:
        raise Refused(400, "job must be one of: " + ", ".join(JOBS))
    _not_applying()
    if name in ("update", "rollback"):
        from . import updates
        why = updates.job_refusal(name)
        if why:
            raise Refused(409, why)
    if name == "apply":
        _start_apply()
    else:
        _start_job(name)
    return {"name": name}


def _station_pairing(req: dict) -> dict:
    from .station import server_api
    return {"state": server_api.pairing_state()}


def _check(req: dict) -> dict:
    return {}


def _access(req: dict) -> None:
    """The code, or a trusted computer's token in its place. A token that doesn't work counts against no lockout: 256 random
    bits are out of a guesser's reach, and a revoked browser's owner shouldn't be locked out for it."""
    code = req.get("code")
    if isinstance(code, str) and code.startswith(trusted.PREFIX):
        d = trusted.use(code[len(trusted.PREFIX):], req["client"] if isinstance(req.get("client"), str) else "?")
        if d is None:
            raise Refused(403, TRUST_GONE, trust_gone=True)
        req["device"] = d["id"]
        return
    _check_code(code, req.get("client"))


def _trust_status(req: dict) -> dict:
    return trusted.status(req.get("token"))


def _trust_add(req: dict) -> dict:
    if str(req.get("code")).startswith(trusted.PREFIX):
        raise Refused(403, "type the setup code to trust another browser")
    got = trusted.add(_text(req, "name", trusted.MAX_NAME * 4), req["client"] if isinstance(req.get("client"), str) else "?")
    if got is None:
        raise Refused(409, TRUST_OFF)
    return {"id": got[0], "token": got[1]}


def _trust_list(req: dict) -> dict:
    return {"enabled": trusted.enabled(), "devices": trusted.listing(), "this": req.get("device")}


def _trust_id(req: dict) -> str:
    did = req.get("id")
    if not isinstance(did, str) or not trusted.ID.fullmatch(did):
        raise Refused(404, "no such trusted computer")
    return did


def _trust_rename(req: dict) -> dict:
    if not trusted.rename(_trust_id(req), _text(req, "name", trusted.MAX_NAME * 4)):
        raise Refused(404, "no such trusted computer")
    return {}


def _trust_revoke(req: dict) -> dict:
    did = _trust_id(req)
    if not trusted.revoke(did):
        raise Refused(404, "no such trusted computer")
    return {"self": did == req.get("device")}


def _trust_revoke_all(req: dict) -> dict:
    return {"count": trusted.revoke_all()}


def _trust_enabled(req: dict) -> dict:
    if not isinstance(req.get("enabled"), bool):
        raise Refused(400, "enabled must be true or false")
    return {"forgotten": trusted.set_enabled(req["enabled"])}


def _apply(req: dict) -> dict:
    _not_applying()
    _start_apply()
    return {}


OPS = {"check": _check, "key_set": _key_set, "key_remove": _key_remove, "passphrase_set": _passphrase_set,
       "library_token_set": _library_token_set, "library_token_remove": _library_token_remove,
       "module": _module, "setting": _setting, "apply": _apply, "mode": _mode, "job": _job,
       "journal": _journal, "station_pairing": _station_pairing, "trust_status": _trust_status, "trust_add": _trust_add,
       "trust_list": _trust_list, "trust_rename": _trust_rename, "trust_revoke": _trust_revoke,
       "trust_revoke_all": _trust_revoke_all, "trust_enabled": _trust_enabled}


# what may save a setting and start a job: these run under _job_lock, whole
LOCKED_OPS = ("module", "setting", "mode", "apply", "job")
NO_CODE_OPS = ("trust_status",)     # it answers only about the token it was given


def handle(req) -> dict:
    """One request -> one reply {ok, status[, error][, ...]}. Never raises; the reply never holds a value, except
    trust_add's new token."""
    try:
        if not isinstance(req, dict) or req.get("op") not in OPS:
            raise Refused(400, "unknown request")
        if req["op"] not in NO_CODE_OPS:
            _access(req)
        if req["op"] in LOCKED_OPS:
            with _job_lock():
                return {"ok": True, "status": 200, **OPS[req["op"]](req)}
        return {"ok": True, "status": 200, **OPS[req["op"]](req)}
    except Refused as e:
        return {"ok": False, "status": e.status, "error": e.message, **e.extra}
    except Exception:  # noqa: BLE001 - logged (without values) to the journal, a plain refusal to the page
        log.exception("setup helper: %s failed", req.get("op") if isinstance(req, dict) else "request")
        return {"ok": False, "status": 500, "error": "the setup helper failed; see: journalctl -u 'filament-kit-setup@*'"}


# ---------- the background jobs ----------

def run_job(name: str, cmd: list[str] | None = None) -> int:
    """filament-kit-setup-job.service: the job's command, its output in job_log() for the page. /run is root's, so
    the log cannot be swapped for a link by the service user; it is made 640 root:filament-kit. stdin is /dev/null:
    with no terminal nothing asks, and neither the setup code nor a pairing link is printed."""
    d = run_dir()
    d.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chmod(d, 0o750)
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    if root:
        shutil.chown(d, user="root", group=setup_code.GROUP)
    apply_log().unlink(missing_ok=True)
    fd = os.open(job_log(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        if root:
            os.fchmod(fh.fileno(), 0o640)
            os.fchown(fh.fileno(), 0, setup_code._gid(setup_code.GROUP))
        cmd = cmd or [WRAPPER, *JOBS[name]]
        fh.write(header(name) + "\n")
        fh.flush()
        # systemd's SIGTERM reaches the command too, whose own handler puts the kit back (updates._sigterm_exits): wait
        # for it, so its exit lands in the log (subprocess.run would kill it on an exception here)
        old = None
        try:
            old = signal.signal(signal.SIGTERM, lambda *a: None)
        except ValueError:              # not the main thread
            pass
        try:
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, check=False,
                               env={**os.environ, "PYTHONUNBUFFERED": "1"})
            code = r.returncode
        except OSError as e:
            fh.write(f"error: {e}\n")
            code = 1
        finally:
            if old is not None:
                signal.signal(signal.SIGTERM, old)
        fh.write(f"\n{FINISHED} {code})\n")
    # the page's own audit line says who started it; the page restarts during a job, so the end is logged here
    log.info("setup: job %s finished (exit %s)", name, code)
    return code


def run_apply(cmd: list[str] | None = None) -> int:
    return run_job("apply", cmd)


def job_run(name: str) -> int:
    """The job unit: `name` is its instance (%i), which the helper checked; checked again, as anyone can start a unit
    of that name by hand."""
    if name not in JOBS:
        print("not a job", file=sys.stderr)
        return 2
    return run_job(name)


def _stdin_fd() -> int | None:
    try:
        return sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        return None


def _is_socket(fd: int) -> bool:
    import stat
    try:
        return stat.S_ISSOCK(os.fstat(fd).st_mode)
    except OSError:
        return False


def _allowed_uids() -> set[int]:
    uids = {0}
    try:
        import pwd
        uids.add(pwd.getpwnam(setup_code.GROUP).pw_uid)
    except (ImportError, KeyError):
        pass
    return uids


def _peer_ok(fd: int) -> bool | None:
    """True/False: the peer of the unix socket `fd` is / is not root or the service user (SO_PEERCRED); None when
    `fd` is no unix socket (run by hand at a terminal: then the caller's own rights apply)."""
    if fd < 0 or not _is_socket(fd) or not hasattr(socket, "SO_PEERCRED"):
        return None
    s = socket.socket(fileno=os.dup(fd))
    try:
        _pid, uid, _gid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                           struct.calcsize("3i")))
    except OSError:
        return False
    finally:
        s.close()
    return uid in _allowed_uids()


def _read_request(fd: int) -> bytes | None:
    """One line from the socket `fd` within READ_TIMEOUT seconds in all; None when it does not come in time. More
    than MAX_REQUEST bytes come back as they are (the caller refuses them)."""
    import time
    s = socket.socket(fileno=os.dup(fd))
    data = b""
    end = time.monotonic() + READ_TIMEOUT
    try:
        while b"\n" not in data and len(data) <= MAX_REQUEST:
            left = end - time.monotonic()
            if left <= 0:
                return None
            s.settimeout(left)
            try:
                chunk = s.recv(4096)
            except (TimeoutError, socket.timeout):
                return None
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    return data.split(b"\n", 1)[0] if b"\n" in data else data


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.getLogger("filament_kit").addHandler(handler)
    logging.getLogger("filament_kit").setLevel(logging.INFO)
    if len(argv) == 2 and argv[0] == "job-run":
        return job_run(argv[1])
    if argv == ["apply-run"]:
        return run_apply()
    if argv:
        print("usage: python -m filament_kit.setup_helper [job-run NAME | apply-run]", file=sys.stderr)
        return 2
    reply_to = sys.stdout.buffer
    sys.stdout = sys.stderr            # whatever a CLI function prints goes to the journal, never into the reply
    fd = _stdin_fd()
    # the request is read (within READ_TIMEOUT) before any answer, even a refusal: closing a socket with unread
    # data resets it, and the caller would never see why
    raw = _read_request(fd) if fd is not None and _is_socket(fd) else sys.stdin.buffer.readline(MAX_REQUEST + 1)
    if fd is not None and _peer_ok(fd) is False:
        log.warning("setup helper: refused a connection from a user that is neither root nor filament-kit")
        reply = {"ok": False, "status": 403, "error": "not allowed"}
    else:
        if raw is None:
            reply = {"ok": False, "status": 408, "error": "no complete request in time"}
        elif len(raw) > MAX_REQUEST:
            reply = {"ok": False, "status": 413, "error": "request too large"}
        else:
            try:
                req = json.loads(raw or b"null")
            except ValueError:
                req = None
            reply = handle(req)
    reply_to.write(json.dumps(reply).encode("utf-8") + b"\n")
    reply_to.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
