"""The panel's Piper voices: the one table naming them (where each comes from, its pinned SHA-256 hashes, its
licence), and the installer's download of the chosen one.

DEFAULT (one line, at the top of the table) is the voice a station gets; `station.voice` in the config picks another
voice from VOICES; `modules apply` points the station at it (STATION_PIPER_VOICE) and
install.sh fetches it. To add a voice, add a row here with the hashes of its .onnx and .onnx.json.

`python -m filament_kit.station.voice DIR [NAME]` (the `station_voice` step of `modules apply`, station on,
`station.tts` not `espeak`): fetch the voice's files into DIR, checked against its hashes. Present with the right
hash: skipped. A mismatch fails (exit 1, that file not kept). Offline: a note and exit 0, since espeak-ng still
speaks. A voice is 60-80 MB; at runtime it is
all offline.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# The voice every station gets unless station.voice says otherwise: libritts_r, speaker 0 (Piper's default for this
# multi-speaker model), the owner's pick by ear on the panel (2026-11-07), knowing the licence caveat below.
DEFAULT = "en_US-libritts_r-medium"

_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = {
    # LJ Speech: public domain (dataset and voice), trained from scratch: the pick with no licence question.
    "en_US-ljspeech-medium": {
        "url": _HF + "en/en_US/ljspeech/medium/", "licence": "public domain (LJ Speech dataset)",
        "files": {"en_US-ljspeech-medium.onnx": "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
                  "en_US-ljspeech-medium.onnx.json":
                      "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860"}},
    # LibriTTS-R: CC BY 4.0, so the credit goes with it (THIRD-PARTY.md, station/PANEL.md). 904 speakers; Piper
    # speaks with speaker 0. CAVEAT: its model card says it was fine-tuned from en_US-lessac-medium, whose dataset is
    # research-only, so these weights may carry that restriction (the owner accepted this, 2026-11-07).
    "en_US-libritts_r-medium": {
        "url": _HF + "en/en_US/libritts_r/medium/", "licence": "CC BY 4.0 (fine-tuned from lessac: see above)",
        "credit": "Piper voice en_US-libritts_r-medium, trained on LibriTTS-R (Koizumi et al., 2023, "
                  "http://www.openslr.org/141/), licensed CC BY 4.0",
        "files": {"en_US-libritts_r-medium.onnx": "10bb85e071d616fcf4071f369f1799d0491492ab3c5d552ec19fb548fac13195",
                  "en_US-libritts_r-medium.onnx.json":
                      "b471dc60d2d8335e819c393d196d6fbf792817f40051257b269878505bc9afb3"}},
    # lessac: RESEARCH-ONLY (Blizzard 2013 licence on its dataset). Never a default: only when the owner sets
    # station.voice to it explicitly for their own station.
    "en_US-lessac-medium": {
        "url": _HF + "en/en_US/lessac/medium/", "licence": "research only (Blizzard 2013)",
        "files": {"en_US-lessac-medium.onnx": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
                  "en_US-lessac-medium.onnx.json":
                      "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"}},
}
DIR = "/opt/filament-kit/resources/voice"  # install.sh puts voices here; `modules apply` points the station at one


class HashMismatch(Exception):
    """A downloaded voice file is not the pinned one."""


def get(name: str | None = None) -> dict:
    """The table row for voice `name` (default DEFAULT); ValueError for a voice the table doesn't know."""
    name = name or DEFAULT
    if name not in VOICES:
        raise ValueError(f"unknown Piper voice {name!r}; known: {', '.join(VOICES)}")
    return VOICES[name]


def model_path(directory: str | os.PathLike = DIR, name: str | None = None) -> str:
    get(name)
    return f"{os.fspath(directory).rstrip('/')}/{name or DEFAULT}.onnx"  # a Linux path: the station and drop-in


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def fetch(directory: str | os.PathLike = DIR, name: str | None = None, urlopen=urllib.request.urlopen) -> str:
    """Put voice `name`'s files into directory: "present" (already there, right hashes), "installed", or "offline"
    (a file not reachable: its partial download is dropped, but a file that already arrived and matched its hash
    is kept, so the next run fetches only what is missing). Raises HashMismatch for a file that isn't the pinned
    one (that file is not kept)."""
    v = get(name)
    d = Path(directory)
    todo = [(n, h) for n, h in v["files"].items() if _sha256(d / n) != h]
    if not todo:
        return "present"
    d.mkdir(parents=True, exist_ok=True)
    for fname, want in todo:
        part = d / (fname + ".part")
        h = hashlib.sha256()
        try:
            with urlopen(v["url"] + fname, timeout=60) as r, open(part, "wb") as out:
                for block in iter(lambda: r.read(1 << 20), b""):
                    h.update(block)
                    out.write(block)
        except (urllib.error.URLError, OSError, TimeoutError):
            part.unlink(missing_ok=True)
            return "offline"
        if h.hexdigest() != want:
            part.unlink(missing_ok=True)
            raise HashMismatch(f"piper voice {fname}: hash mismatch (got {h.hexdigest()[:16]}..., "
                               f"pinned {want[:16]}...)")
        os.replace(part, d / fname)
        os.chmod(d / fname, 0o644)
    return "installed"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    directory = argv[0] if argv else DIR
    name = argv[1] if len(argv) > 1 and argv[1] else DEFAULT
    try:
        got = fetch(directory, name)
    except (HashMismatch, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if got == "offline":
        print(f"note: could not download the Piper voice ({name}); the panel speaks with espeak-ng", file=sys.stderr)
    else:
        print(f"Piper voice {name} ({get(name)['licence']}): {got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
