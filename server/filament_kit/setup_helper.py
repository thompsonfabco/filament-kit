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
    apply                                      start `modules apply --no-pair` (filament-kit-setup-apply.service)

Every request carries the setup code and the page's client address, and this process is the only place a code is
checked (setup_code.check on the root-only hash, against the per-client and global lockout in
/etc/filament-kit/setup_lockout), before it reads anything else: a local process that reaches the socket without
the code can change nothing. Only root and the filament-kit user may connect (SO_PEERCRED; the socket is 660 and
the web unit cannot see it). The request must arrive within READ_TIMEOUT seconds. Values are never logged, never echoed in a reply, never put in a
command line. What the CLI functions print goes to the journal (stderr), not into the reply.

`python -I -m filament_kit.setup_helper apply-run` is what filament-kit-setup-apply.service runs: `modules apply
--no-pair` with its output in /run/filament-kit-setup/apply.log (root:filament-kit 640), which the page reads; the
apply runs in its own unit, so it goes on when it restarts the kit server (and the page with it)."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from . import config, modules, setup_code

log = logging.getLogger(__name__)

MAX_REQUEST = 16 * 1024
READ_TIMEOUT = 5.0
APPLY_UNIT = "filament-kit-setup-apply.service"
WRAPPER = "/usr/local/bin/filament-kit"
FINISHED = "==> finished (exit"
SETTINGS = ("web.public_url", "station.url")
WRONG = "wrong setup code"
LOCKED = ("too many wrong setup codes: wait 10 minutes (longer after many from everywhere), or make a new code "
          "at the server, which also lifts the lock: sudo filament-kit setup-code --new")
NO_CODE = "no setup code is set on this server yet; make one at the server: sudo filament-kit setup-code"
APPLYING = "the last change is still being applied; wait until it has finished"
# the checklist's setting prompts, back to their keys (cli._apply_selection asks by prompt)
_PROMPT_KEYS = {v: k for k, v in modules._SETTING_PROMPTS.items()}


class Refused(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def run_dir() -> Path:
    return Path(os.environ.get("FK_SETUP_RUN", "/run/filament-kit-setup"))


def apply_log() -> Path:
    return run_dir() / "apply.log"


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


def _applying() -> bool:
    """True while filament-kit-setup-apply.service runs (one apply at a time)."""
    if _no_systemd():
        return False
    r = subprocess.run(["systemctl", "show", "--property=ActiveState", "--value", APPLY_UNIT], capture_output=True,
                       text=True, timeout=30, check=False)
    # a oneshot is "activating" while it runs (is-active would say no) and "inactive" once it has finished
    return r.stdout.strip() in ("activating", "active", "deactivating", "reloading")


def _start_apply() -> None:
    if _no_systemd():
        return
    r = subprocess.run(["systemctl", "start", "--no-block", APPLY_UNIT], capture_output=True, text=True,
                       timeout=60, check=False)
    if r.returncode != 0:
        log.error("setup helper: cannot start %s: %s", APPLY_UNIT, r.stderr.strip())
        raise Refused(500, "saved, but the apply did not start; run at the server: sudo filament-kit modules apply")


def _not_applying() -> None:
    if _applying():
        raise Refused(409, APPLYING)


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


def _check(req: dict) -> dict:
    return {}


def _apply(req: dict) -> dict:
    _not_applying()
    _start_apply()
    return {}


OPS = {"check": _check, "key_set": _key_set, "key_remove": _key_remove, "passphrase_set": _passphrase_set,
       "library_token_set": _library_token_set, "library_token_remove": _library_token_remove,
       "module": _module, "setting": _setting, "apply": _apply}


def handle(req) -> dict:
    """One request -> one reply {ok, status[, error][, ...]}. Never raises; the reply never holds a value."""
    try:
        if not isinstance(req, dict) or req.get("op") not in OPS:
            raise Refused(400, "unknown request")
        _check_code(req.get("code"), req.get("client"))
        return {"ok": True, "status": 200, **OPS[req["op"]](req)}
    except Refused as e:
        return {"ok": False, "status": e.status, "error": e.message, **e.extra}
    except Exception:  # noqa: BLE001 - logged (without values) to the journal, a plain refusal to the page
        log.exception("setup helper: %s failed", req.get("op") if isinstance(req, dict) else "request")
        return {"ok": False, "status": 500, "error": "the setup helper failed; see: journalctl -u 'filament-kit-setup@*'"}


# ---------- the background apply ----------

def run_apply(cmd: list[str] | None = None) -> int:
    """filament-kit-setup-apply.service: `modules apply --no-pair`, its output in apply_log() for the page. /run is
    root's, so the log cannot be swapped for a link by the service user; it is made 640 root:filament-kit."""
    d = run_dir()
    d.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chmod(d, 0o750)
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    if root:
        shutil.chown(d, user="root", group=setup_code.GROUP)
    fd = os.open(apply_log(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        if root:
            os.fchmod(fh.fileno(), 0o640)
            os.fchown(fh.fileno(), 0, setup_code._gid(setup_code.GROUP))
        cmd = cmd or [WRAPPER, "modules", "apply", "--no-pair"]
        fh.write("==> filament-kit modules apply\n")
        fh.flush()
        try:
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, check=False,
                               env={**os.environ, "PYTHONUNBUFFERED": "1"})
            code = r.returncode
        except OSError as e:
            fh.write(f"error: {e}\n")
            code = 1
        fh.write(f"\n{FINISHED} {code})\n")
    return code


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
    if argv == ["apply-run"]:
        return run_apply()
    if argv:
        print("usage: python -m filament_kit.setup_helper [apply-run]", file=sys.stderr)
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
