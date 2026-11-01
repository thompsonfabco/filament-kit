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


def paths() -> Paths:
    return Paths(
        etc=Path(os.environ.get("FK_ETC", "/etc/filament-kit")),
        state=Path(os.environ.get("FK_STATE", "/var/lib/filament-kit")),
        backups=Path(os.environ.get("FK_BACKUPS", "/var/backups/filament-kit")),
        opt=Path(os.environ.get("FK_OPT", "/opt/filament-kit")),
    )


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
    "library": {"url": None, "schedule": "daily"},
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
        os.replace(tmp, f)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
