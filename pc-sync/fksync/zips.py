"""Zips for the sync API: pack a preset folder for upload, unpack a server build safely.

pack() is deterministic: the same files give the same bytes (sorted names, fixed timestamps
and attributes), so it never depends on mtimes.

unpack_build() accepts only `BUILD.json` and `base/<name>.json|.info` with a safe <name>,
refuses everything else before writing anything, caps the uncompressed size while it reads,
and only moves the result to `dest` once every entry has been written.
"""
import io
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from .treehash import preset_files

MAX_BUILD_UNCOMPRESSED = 64 * 1024 * 1024
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_CHUNK = 64 * 1024
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def pack(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, path in preset_files(root):
            info = zipfile.ZipInfo(rel, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


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
        if name == "base/" and info.is_dir():
            continue
        if "\\" in info.orig_filename:  # zipfile turns "\\" into "/" on Windows only; refuse on every OS
            raise ValueError(f"build zip: refusing entry {info.orig_filename!r}")
        ftype = stat.S_IFMT(info.external_attr >> 16)
        if info.is_dir() or ftype not in (0, stat.S_IFREG):  # 0: no Unix mode recorded (DOS attrs only)
            raise ValueError(f"build zip: refusing entry {name!r} (not a regular file)")
        if name != "BUILD.json":
            head, sep, tail = name.partition("/")
            if head != "base" or not sep or not _safe_name(tail):
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
