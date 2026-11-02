"""Zips for the sync API: pack a preset folder for upload, unpack a server build safely.

pack() refuses (TooLarge) a folder over the upload limits before zipping it, and is deterministic: the same files give the same bytes (sorted names, fixed timestamps
and attributes), so it never depends on mtimes.

orca_system() packs Orca Slicer's system presets the same way (Ruling L: BBL JSON + the packed library's index).

unpack_build() accepts only `BUILD.json`, `base/<name>.json|.info` and `orca/<name>.json|.info` (the Orca
Slicer tree; both flat) with a safe <name>,
refuses everything else before writing anything, caps the uncompressed size while it reads,
and only moves the result to `dest` once every entry has been written.
"""
import datetime
import hashlib
import io
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from . import orca_opc
from .treehash import preset_files

MAX_BUILD_UNCOMPRESSED = 64 * 1024 * 1024
# upload limits (Decision "Sync uploads"); the server refuses anything over them with 413
LIVE_MAX = 32 << 20
SYSTEM_MAX = 64 << 20
MAX_ENTRIES = 20_000
MAX_FILE = 4 << 20
MAX_TOTAL = 512 << 20
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_CHUNK = 64 * 1024
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class TooLarge(ValueError):
    """A folder is over the server's upload limits; nothing was sent."""


def pack(root: Path, max_bytes: int | None = None) -> bytes:
    """Zip every .json/.info file under root. TooLarge when the folder breaks an upload limit
    (MAX_ENTRIES files, MAX_FILE per file, MAX_TOTAL uncompressed, max_bytes for the zip)."""
    root = Path(root)
    return _pack(str(root), preset_files(root), {}, max_bytes)


LIBRARY_INDEX = "OrcaFilamentLibrary/index.json"


def library_index(opc: Path) -> bytes:
    """`OrcaFilamentLibrary/index.json` for a packed library (Ruling L); the same file gives the same bytes."""
    st = opc.stat()
    when = datetime.datetime.fromtimestamp(int(st.st_mtime), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index = {"version": 1, "source": f"{opc.name} {when}", "presets": orca_opc.library_presets(opc.read_bytes())}
    return (json.dumps(index, indent=1, sort_keys=True) + "\n").encode("utf-8")


def orca_system(orca, max_bytes: int | None = None) -> tuple[bytes, str]:
    """(zip, tree hash) of Orca's system presets for `PUT /api/sync/system?target=orca` (Ruling L):
    `BBL/filament/**.json` from Orca's unpacked %APPDATA%\\OrcaSlicer\\system\\BBL\\filament, plus
    `OrcaFilamentLibrary/index.json` listing the presets packed in OrcaFilamentLibrary.opc (left out when this
    PC has no .opc). The hash is what the server's tree hash of the unpacked zip gives."""
    files = [(f"BBL/filament/{rel}", p) for rel, p in preset_files(orca.system_bbl)
             if rel.casefold().endswith(".json")]
    extra = {LIBRARY_INDEX: library_index(orca.library_opc)} if orca.library_opc is not None else {}
    data = _pack("Orca Slicer's system presets", files, extra, max_bytes)
    h = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:   # hash exactly what was sent
        for name in zf.namelist():
            h.update(name.encode("utf-8") + b"\0" + hashlib.sha256(zf.read(name)).digest())
    return data, h.hexdigest()


def _pack(label: str, files: list[tuple[str, Path]], extra: dict[str, bytes], max_bytes: int | None) -> bytes:
    """Zip `files` [(rel, path)] and `extra` {rel: bytes}, sorted by name, after checking the upload limits."""
    if len(files) + len(extra) > MAX_ENTRIES:
        raise TooLarge(f"{label} is too large to upload: {len(files) + len(extra)} files "
                       f"(the server takes at most {MAX_ENTRIES})")
    total = sum(len(v) for v in extra.values())
    for rel, path in files:
        size = path.stat().st_size
        if size > MAX_FILE:
            raise TooLarge(f"{label} is too large to upload: {rel} is {_mib(size)} "
                           f"(the server takes at most {_mib(MAX_FILE)} per file)")
        total += size
    if total > MAX_TOTAL:
        raise TooLarge(f"{label} is too large to upload: {_mib(total)} uncompressed "
                       f"(the server takes at most {_mib(MAX_TOTAL)})")
    entries = sorted([(rel, path) for rel, path in files] + list(extra.items()), key=lambda t: t[0])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, src in entries:
            info = zipfile.ZipInfo(rel, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            data = src if isinstance(src, bytes) else src.read_bytes()
            if len(data) > MAX_FILE:  # grew since the stat
                raise TooLarge(f"{label} is too large to upload: {rel} is over {_mib(MAX_FILE)}")
            zf.writestr(info, data)
    data = buf.getvalue()
    if max_bytes is not None and len(data) > max_bytes:
        raise TooLarge(f"{label} is too large to upload: the zip is {_mib(len(data))} "
                       f"(the server takes at most {_mib(max_bytes)})")
    return data


def _mib(n: int) -> str:
    return f"{n / (1 << 20):.1f} MiB"


def _safe_name(name: str) -> bool:
    """A preset file name that is safe as a single Windows/POSIX path component."""
    stem, dot, suffix = name.rpartition(".")
    if not dot or suffix not in ("json", "info") or not stem or len(name) > 200:
        return False
    if _BAD_CHARS.search(name) or name.startswith(".") or stem[-1] in " ." or stem[0] == " ":
        return False
    return stem.split(".")[0].upper().rstrip() not in _RESERVED


def _check_entries(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    files, seen, declared = [], set(), 0
    for info in zf.infolist():
        name = info.filename
        if name in ("base/", "orca/") and info.is_dir():
            continue
        if "\\" in info.orig_filename:  # zipfile turns "\\" into "/" on Windows only; refuse on every OS
            raise ValueError(f"build zip: refusing entry {info.orig_filename!r}")
        ftype = stat.S_IFMT(info.external_attr >> 16)
        if info.is_dir() or ftype not in (0, stat.S_IFREG):  # 0: no Unix mode recorded (DOS attrs only)
            raise ValueError(f"build zip: refusing entry {name!r} (not a regular file)")
        if name != "BUILD.json":
            head, sep, tail = name.partition("/")
            if head not in ("base", "orca") or not sep or not _safe_name(tail):
                raise ValueError(f"build zip: refusing entry {name!r}")
        key = name.casefold()
        if key in seen:
            raise ValueError(f"build zip: duplicate entry {name!r}")
        seen.add(key)
        declared += info.file_size
        if declared > MAX_BUILD_UNCOMPRESSED:
            raise ValueError("build zip: too large uncompressed")
        files.append(info)
    if "build.json" not in seen:
        raise ValueError("build zip: BUILD.json missing")
    return files


def unpack_build(data: bytes, dest: Path) -> dict:
    """Extract a server build zip into dest (which must not exist or be empty); returns BUILD.json."""
    dest = Path(dest)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError(f"build zip: destination {dest} is not empty")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError(f"build zip: not a zip ({e})") from None
    with zf:
        files = _check_entries(zf)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent))
        try:
            total = 0
            for info in files:
                out = tmp / Path(*info.filename.split("/"))
                out.parent.mkdir(exist_ok=True)
                with zf.open(info) as src, open(out, "xb") as dst:
                    while chunk := src.read(_CHUNK):
                        total += len(chunk)
                        if total > MAX_BUILD_UNCOMPRESSED:
                            raise ValueError("build zip: too large uncompressed")
                        dst.write(chunk)
            try:
                build = json.loads((tmp / "BUILD.json").read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError(f"build zip: BUILD.json is not valid JSON ({e})") from None
            if not isinstance(build, dict):
                raise ValueError("build zip: BUILD.json is not an object")
            if dest.exists():
                dest.rmdir()  # checked empty above
            tmp.replace(dest)
        except (zipfile.BadZipFile, OSError, EOFError) as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ValueError(f"build zip: corrupt ({e})") from None
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    return build
