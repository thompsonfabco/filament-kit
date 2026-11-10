"""Server configuration: paths, defaults, load/save of config.json."""
from __future__ import annotations

import copy
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    etc: Path
    state: Path
    backups: Path
    opt: Path
    web: Path            # the web unit's own state (its OAuth store, kit token, Web Push keys), user filament-kit-web


def paths() -> Paths:
    return Paths(
        etc=Path(os.environ.get("FK_ETC", "/etc/filament-kit")),
        state=Path(os.environ.get("FK_STATE", "/var/lib/filament-kit")),
        backups=Path(os.environ.get("FK_BACKUPS", "/var/backups/filament-kit")),
        opt=Path(os.environ.get("FK_OPT", "/opt/filament-kit")),
        web=_web_state(),
    )


def _web_state() -> Path:
    """FK_WEB_STATE; else beside an FK_STATE given (tests, a dev copy: `<state>-web`); else the installed place."""
    if os.environ.get("FK_WEB_STATE"):
        return Path(os.environ["FK_WEB_STATE"])
    if os.environ.get("FK_STATE"):
        st = Path(os.environ["FK_STATE"])
        return st.with_name(st.name + "-web")
    return Path("/var/lib/filament-kit-web")


WEB_USER = "filament-kit-web"   # the web unit's user: its own group, never in the filament-kit group
KIT_USER = "filament-kit"


def uid_of(user: str) -> int | None:
    try:
        import pwd
        return pwd.getpwnam(user).pw_uid
    except (ImportError, KeyError):
        return None


def grant_web_read(path) -> None:
    """Let the web unit's user read `path` (a root-owned settings file it needs: config.json, web_passphrase,
    anthropic_key) with a POSIX ACL; a no-op unless root, with that user, on a file system with ACLs."""
    from . import acl
    if not acl.supported() or getattr(os, "geteuid", lambda: -1)() != 0:
        return
    uid = uid_of(WEB_USER)
    if uid is not None:
        try:
            acl.grant(path, {uid: acl.R})
        except OSError as e:
            import logging
            logging.getLogger(__name__).warning(
                "cannot let %s read %s (%s); the web unit will fail to read it: check that the file system "
                "supports ACLs, then run: sudo filament-kit modules apply", WEB_USER, path, e)


# The one install line (README). It also repairs an install: get.sh fetches the release, unlike an ./install.sh it deleted.
GET_COMMAND = "curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh"

DEFAULTS: dict = {
    "server_name": socket.gethostname(),
    "spoolman_url": "http://127.0.0.1:7912",
    "port": 8710,
    "model": "claude-opus-5-5",
    "reads_per_day": 60,
    "locations": ["Sealed stock", "Rack 1", "Storage box", "Overflow"],
    "placement": {
        "pla_location": "Rack 1",
        "box_prefix": "Storage box ",
        "box_count": 0,
        "overflow": "Overflow",
        "sealed_location": "Sealed stock",
    },
    "printers": [],
    "auto_remap": True,         # re-map a printer's slots by itself (when idle) after its AMS layout changed
    "library": {"url": None, "schedule": "daily"},
    "station": {"url": None, "allow": ["127.0.0.1"], "port": 5003,
                "nfc_device": "auto", "beep": True, "beep_device": "",
                "speech": True, "tts": "auto", "voice": None, "camera": "auto", "panel_flash": True,
                "panel_swap": False,  # the panel's yellow and red are wired to each other's pins
                "speaker_volume": 50},  # the C3 panel's speaker, percent
    # merge-ops: web unit, remote access, orders file, tag readers, slot service, slicer/presets/intake extras
    "web": {"port": 8101, "public_url": None, "push": False,   # push: Web Push alerts (needs internet egress)
            "lan": ["192.168.0.0/16", "10.0.0.0/8"]},   # not 172.16/12: Docker's bridges live there (A-M6)
    "remote": {"hostname": None, "acme_window": None, "email": None},
    # who may reach the spoolman module's listener, which has no sign-in. None: the same ranges as web.lan
    "spoolman": {"allow": None},
    "orders": {"file": None},
    "tag_sources": [],          # [{"name": str, "url": str}]: extra readers speaking the lasttag shape
    "slot_service": None,       # {"state_url", "set_url", "token_file"}
    "slicer_printers": [],
    "presets_orca": False,
    "intake": {"tare_hints": {}, "model": None},
    "web_instructions": None,
}


def _merge(base: dict, over: dict) -> dict:
    """Merge `over` onto `base`; dict values are merged one level down."""
    out = copy.deepcopy(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key].update(copy.deepcopy(val))
        else:
            out[key] = copy.deepcopy(val)
    return out


def _file() -> Path:
    return paths().etc / "config.json"


def load() -> dict:
    defaults = copy.deepcopy(DEFAULTS)
    defaults["server_name"] = socket.gethostname()
    f = _file()
    if not f.exists():
        return defaults
    return _merge(defaults, json.loads(f.read_text(encoding="utf-8")))


def save(cfg: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o640)
        grant_web_read(tmp)
        os.replace(tmp, f)
        token = (cfg.get("slot_service") or {}).get("token_file") if isinstance(cfg.get("slot_service"), dict) else None
        if token and Path(token).is_file() and not Path(token).is_symlink():
            grant_web_read(token)       # the owner's H2D slot token: the web unit's printer_set_slot reads it
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
