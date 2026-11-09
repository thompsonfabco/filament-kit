"""`python -m filament_kit.station.pair_apply`: filament-kit-station-pair.service, root, started by its path unit when the
station has received a pairing (pair_request.py). Saves it as `station pair` does.

The drop file sits in a folder the station's service user owns, so it is read with care: never through a link, a
regular file with one name, at most MAX_BYTES, read once and removed before anything else happens. From it only the
fingerprint, the token and the port are taken; the server's address is `station.allow`'s, as configured by root.
The token must answer /api/station/hello over the pinned certificate before anything is saved.
"""
from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
from pathlib import Path

from .. import apply, config, modules
from . import pair_request, server_api

log = logging.getLogger("intake-station")
MAX_BYTES = 4096
FP = re.compile(r"[0-9a-f]{64}")
TOKEN = re.compile(r"[A-Za-z0-9_-]{16,128}")


class DropError(Exception):
    pass


def read_drop(path: Path) -> dict:
    """The checked contents of the drop file, which is removed in every case."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        raise
    except OSError as e:
        _remove(path)
        raise DropError(f"cannot open the drop file safely ({type(e).__name__})") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_BYTES:
            raise DropError("the drop file is not a plain file of at most 4 KiB")
        raw = os.read(fd, MAX_BYTES + 1)
    finally:
        os.close(fd)
        _remove(path)
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise DropError("the drop file is not JSON") from None
    if not isinstance(d, dict):
        raise DropError("the drop file is not a JSON object")
    fp, token, port = d.get("fp"), d.get("token"), d.get("port")
    if not isinstance(fp, str) or not FP.fullmatch(fp) or not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise DropError("the drop file has no usable fingerprint or token")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise DropError("the drop file has no usable port")
    return {"fp": fp, "token": token, "port": port}


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def apply_drop(path: Path, *, refresh=apply.refresh_station) -> str:
    """Save the pairing in `path`: "saved", or raises DropError with the reason."""
    req = read_drop(path)
    cfg = config.load()
    allow = (config._merge(config.DEFAULTS["station"], cfg.get("station") or {}).get("allow")) or []
    host = next((h for h in allow if h), None)
    if host is None:
        raise DropError("station.allow names no server, so there is nowhere this pairing could be for")
    link = server_api.Link(host, req["port"], req["token"], req["fp"], [host])
    status, body = server_api.ServerApi.from_link(link, timeout=15).hello()
    if status != 200:
        raise DropError(f"the server did not accept the token ({status} {body.get('error') or ''})".strip())
    server_api.save_pairing(link, first=host)
    if "station" in modules.enabled(cfg):
        try:
            refresh(cfg)
        except (apply.ApplyError, modules.ModuleError) as e:
            raise DropError(f"paired, but the station could not be updated ({e}); run: sudo filament-kit modules apply") from None
    return "saved"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = pair_request.drop_dir() / pair_request.REQUEST_FILE
    try:
        apply_drop(path)
    except FileNotFoundError:
        return 0
    except DropError as e:
        log.error("station pairing not saved: %s", e)
        return 1
    log.info("station pairing saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
