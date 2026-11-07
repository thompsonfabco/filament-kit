"""The panel's Piper voice: the one place it is named (the model, where it comes from, its pinned SHA-256 hashes),
and the installer's download of it.

The owner picked `en_US-lessac-medium` by ear over espeak-ng on the real panel (2026-11-04). To swap the voice,
change NAME, URL and FILES here; the station's default path (STATION_PIPER_VOICE) and the drop-in follow.

`python -m filament_kit.station.voice DIR` (install.sh, station on, `station.tts` not `espeak`): fetch both files
into DIR, checked against FILES. Present with the right hash: skipped. A mismatch fails (exit 1, nothing kept).
Offline: a note and exit 0, since espeak-ng still speaks. The voice is about 63 MB; at runtime it is all offline.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

NAME = "en_US-lessac-medium"
MODEL = NAME + ".onnx"
URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/"
FILES = {
    MODEL: "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
    MODEL + ".json": "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0",
}
DIR = "/opt/filament-kit/resources/voice"  # install.sh puts it here; `modules apply` points the station at it


class HashMismatch(Exception):
    """A downloaded voice file is not the pinned one."""


def model_path(directory: str | os.PathLike = DIR) -> str:
    return f"{os.fspath(directory).rstrip('/')}/{MODEL}"  # a Linux path: the station and the drop-in use it


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def fetch(directory: str | os.PathLike = DIR, urlopen=urllib.request.urlopen) -> str:
    """Put the voice's files into directory: "present" (already there, right hashes), "installed", or "offline"
    (not reachable; nothing kept). Raises HashMismatch for a file that isn't the pinned one."""
    d = Path(directory)
    todo = [(n, h) for n, h in FILES.items() if _sha256(d / n) != h]
    if not todo:
        return "present"
    d.mkdir(parents=True, exist_ok=True)
    for name, want in todo:
        part = d / (name + ".part")
        h = hashlib.sha256()
        try:
            with urlopen(URL + name, timeout=60) as r, open(part, "wb") as out:
                for block in iter(lambda: r.read(1 << 20), b""):
                    h.update(block)
                    out.write(block)
        except (urllib.error.URLError, OSError, TimeoutError):
            part.unlink(missing_ok=True)
            return "offline"
        if h.hexdigest() != want:
            part.unlink(missing_ok=True)
            raise HashMismatch(f"piper voice {name}: hash mismatch (got {h.hexdigest()[:16]}..., "
                               f"pinned {want[:16]}...)")
        os.replace(part, d / name)
        os.chmod(d / name, 0o644)
    return "installed"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    directory = argv[0] if argv else DIR
    try:
        got = fetch(directory)
    except HashMismatch as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if got == "offline":
        print(f"note: could not download the Piper voice ({NAME}); the panel speaks with espeak-ng", file=sys.stderr)
    else:
        print(f"Piper voice {NAME}: {got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
