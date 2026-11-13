"""A whole-kit backup as one standard zip, and the restore that brings a fresh install back to the deployed state.

The zip: `manifest.xml` (format 1: kit version, API version, host, date, modules, the units' enable state, and every
folder and file with its mode, owner, group and sha256), the Spoolman database (`spoolman/spoolman.db`, an online
copy), and `files/<root>/<path>` for each root folder below. Left out: what is downloaded again (the uploaded Bambu
system presets, earlier library versions), half-written builds, a restore's own upload, the releases and the program
(/opt), logs and /var/backups.

Restore (`restore`): checks every hash first and refuses a backup from a newer kit, keeps a backup of what is there,
stops the kit, puts each root folder back by extracting into an empty folder beside it and swapping (a failure swaps
everything back), puts the Spoolman database back, runs `modules apply` (which installs and starts the recorded
modules), gives the files their owners once the apply has made the users, and runs `status`. Onto another host
name the certificate is made again, so phones and the PC sync pair again.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import os
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from defusedxml import ElementTree as SafeET

from . import API_VERSION, __version__, config, modules, release

FORMAT = "1"
WRAPPER = "/usr/local/bin/filament-kit"
PREFIX = "filament-kit-backup"
PRE_RESTORE = "pre-restore"
NEW, OLD = ".fk-restore-new", ".fk-restore-old"
MAX_MANIFEST = 16 * 2**20
MAX_TOTAL = 8 * 2**30          # what a zip may unpack to
CHUNK = 2**20
UPLOAD = "restore-upload"      # in the state folder: what the setup page received, until the restore job takes it
# Relative to their root: left out, as install/backup.sh leaves them out.
EXCLUDE = {"var/lib/filament-kit": ("profiles/live/system", "library/versions", UPLOAD)}
EXCLUDE_GLOB = {"var/lib/filament-kit": (re.compile(r"profiles/builds/[^/]+\.tmp(/.*)?"),)}
NAME = re.compile(r"(filament-kit-backup|pre-restore)-[A-Za-z0-9-]{1,63}-\d{8}-\d{4}(-\d+)?-v\d+\.\d+\.\d+\.zip")
DAILY = re.compile(r"\d{4}-\d{2}-\d{2}\.tar\.gz")


class BackupError(Exception):
    """A backup that cannot be made, read or restored; the message says why, never a value from it."""


class Unfit(BackupError):
    """A sound backup this kit will not restore (refusal: a newer kit made it, say)."""


def roots() -> list[tuple[str, Path]]:
    """(name in the zip, folder on this machine)."""
    p = config.paths()
    return [("etc/filament-kit", p.etc), ("var/lib/filament-kit", p.state), ("var/lib/filament-kit-web", p.web),
            ("etc/filament-kit-station", p.etc.with_name(p.etc.name + "-station"))]


def spoolman_db() -> Path:
    return Path(os.environ.get("FK_SPOOLMAN_DB", "/var/lib/spoolman/spoolman.db"))


def backups_dir() -> Path:
    return config.paths().backups


def host() -> str:
    """This machine's short name, as the setup page shows it, safe for a file name."""
    name = socket.gethostname().split(".")[0]
    return re.sub(r"[^A-Za-z0-9-]", "-", name).strip("-")[:63] or "kit"


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _no_systemd() -> bool:
    return os.environ.get("FK_NO_SYSTEMD") == "1"


def default_run(cmd: list[str]) -> int:
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, check=False).returncode


# ---------------------------------------------------------------- owners

def _names(st: os.stat_result) -> tuple[str, str]:
    try:
        import grp
        import pwd
    except ImportError:                 # Windows (tests): no owners to keep
        return "", ""
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return owner, group


def _ids(owner: str, group: str) -> tuple[int, int] | None:
    """The ids of these names here, or None when either does not exist yet (an apply makes the kit's users)."""
    try:
        import grp
        import pwd
    except ImportError:
        return None
    try:
        return pwd.getpwnam(owner).pw_uid, grp.getgrnam(group).gr_gid
    except KeyError:
        return None


# ---------------------------------------------------------------- writing

def _excluded(root: str, rel: str) -> bool:
    if any(rel == p or rel.startswith(p + "/") for p in EXCLUDE.get(root, ())):
        return True
    return any(rx.fullmatch(rel) for rx in EXCLUDE_GLOB.get(root, ()))


def _octal(mode: int) -> str:
    return f"{mode & 0o7777:04o}"


class _Writer:
    def __init__(self, fh):
        self.zf = zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED, allowZip64=True)
        self.root = ET.Element("filament-kit-backup", format=FORMAT)
        self.files = ET.SubElement(self.root, "files")

    def folder(self, root: str, rel: str, mode: int, owner: str, group: str) -> None:
        tag = "root" if rel == "" else "dir"
        el = ET.SubElement(self.files, tag, root=root, mode=_octal(mode), owner=owner, group=group)
        if rel:
            el.set("path", rel)

    def stream(self, name: str, src, mtime: float, mode: int) -> tuple[str, int]:
        zi = zipfile.ZipInfo(name, date_time=time.localtime(max(mtime, 315532800))[:6])
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = (0o100000 | (mode & 0o777)) << 16
        h, n = hashlib.sha256(), 0
        with self.zf.open(zi, "w", force_zip64=True) as out:
            while chunk := src.read(CHUNK):
                h.update(chunk)
                n += len(chunk)
                out.write(chunk)
        return h.hexdigest(), n

    def file(self, root: str, rel: str, src, mtime: float, mode: int, owner: str, group: str) -> None:
        sha, size = self.stream(f"files/{root}/{rel}", src, mtime, mode)
        ET.SubElement(self.files, "file", root=root, path=rel, sha256=sha, size=str(size), mode=_octal(mode),
                      owner=owner, group=group)

    def spoolman(self, src, mtime: float, mode: int, owner: str, group: str) -> None:
        sha, size = self.stream("spoolman/spoolman.db", src, mtime, mode)
        ET.SubElement(self.root, "spoolman", sha256=sha, size=str(size), mode=_octal(mode), owner=owner, group=group)

    def finish(self, *, kit: str, created: float, mods: Iterable[str], units: dict[str, str], source: str) -> None:
        r = self.root
        r.set("kit", kit)
        r.set("api", str(API_VERSION))
        r.set("host", host())
        r.set("created", time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(created)))
        r.set("source", source)
        el = ET.SubElement(r, "modules")
        for m in sorted(mods):
            ET.SubElement(el, "module", name=m)
        el = ET.SubElement(r, "units")
        for u, state in sorted(units.items()):
            ET.SubElement(el, "unit", name=u, enabled=state)
        ET.indent(r)
        self.zf.writestr("manifest.xml", ET.tostring(r, encoding="utf-8", xml_declaration=True) + b"\n")
        self.zf.close()


def _modules_here() -> list[str]:
    try:
        return sorted(modules.enabled(config.load()))
    except (OSError, ValueError):
        return []


def _units(mods: Iterable[str]) -> dict[str, str]:
    """Each unit of the modules that are on, and what `systemctl is-enabled` says of it."""
    if _no_systemd():
        return {}
    from . import apply
    names = sorted({f for m in mods if m in modules.MODULES for u in modules.MODULES[m].units
                    for f in apply._unit_files(u) if "@" not in f})
    out = {}
    for u in names:
        try:
            r = subprocess.run(["systemctl", "is-enabled", u], stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=10, check=False)
            out[u] = (r.stdout.strip() or "unknown")[:40]
        except (OSError, subprocess.SubprocessError):
            out[u] = "unknown"
    return out


def _walk(w: _Writer) -> None:
    for name, base in roots():
        try:
            st = os.lstat(base)
        except FileNotFoundError:
            continue
        if not os.path.isdir(base) or os.path.islink(base):
            continue
        w.folder(name, "", st.st_mode, *_names(st))
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            rel_dir = Path(dirpath).relative_to(base).as_posix()
            rel_dir = "" if rel_dir == "." else rel_dir
            keep = []
            for d in sorted(dirnames):
                rel = f"{rel_dir}/{d}" if rel_dir else d
                full = Path(dirpath) / d
                if os.path.islink(full) or _excluded(name, rel):
                    continue
                dst = os.lstat(full)
                w.folder(name, rel, dst.st_mode, *_names(dst))
                keep.append(d)
            dirnames[:] = keep
            for f in sorted(filenames):
                rel = f"{rel_dir}/{f}" if rel_dir else f
                full = Path(dirpath) / f
                if _excluded(name, rel):
                    continue
                fst = os.lstat(full)
                if not os.path.isfile(full) or os.path.islink(full):
                    continue        # sockets, links: nothing to keep
                fd = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
                with os.fdopen(fd, "rb") as src:
                    w.file(name, rel, src, fst.st_mtime, fst.st_mode, *_names(fst))


def _spoolman_copy(w: _Writer, scratch: Path) -> None:
    db = spoolman_db()
    if not db.is_file():
        return
    st = os.stat(db)
    copy = scratch / "spoolman.db"
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)       # an online copy: Spoolman may be writing
    dst = sqlite3.connect(copy)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    with open(copy, "rb") as fh:
        w.spoolman(fh, st.st_mtime, st.st_mode, *_names(st))


def zip_name(prefix: str = PREFIX, now: float | None = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(time.time() if now is None else now))
    return f"{prefix}-{host()}-{stamp}-v{__version__}.zip"


def create(dest: Path | None = None, *, prefix: str = PREFIX, now: float | None = None) -> Path:
    """Write a backup zip into `dest` (default the backups folder); its path. Root, on an install."""
    dest = Path(dest) if dest is not None else backups_dir()
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    if dest == backups_dir():
        os.chmod(dest, 0o700)       # root only: a backup holds the setup code and the TLS key; the page gets one via the helper
    name = zip_name(prefix, now)
    out, n = dest / name, 1
    while out.exists():
        n += 1
        out = dest / name.replace(f"-v{__version__}.zip", f"-{n}-v{__version__}.zip")
    part = out.with_name(out.name + ".part")
    mods = _modules_here()
    with tempfile.TemporaryDirectory(dir=dest, prefix=".backup-") as scratch:
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                w = _Writer(fh)
                _spoolman_copy(w, Path(scratch))
                _walk(w)
                w.finish(kit=__version__, created=time.time() if now is None else now, mods=mods,
                         units=_units(mods), source="made")
            os.replace(part, out)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    return out


def from_daily(tar_path: Path, out) -> None:
    """A daily `<date>.tar.gz` (install/backup.sh) as the same zip, written to the file object `out`, for a download.
    The tar names no kit version: the version that runs here made it, at most `keep_days` ago."""
    w = _Writer(out)
    names = dict(roots())
    mods: list[str] = []
    with tarfile.open(tar_path, "r:gz") as tf:
        for m in tf:
            name = m.name[2:] if m.name.startswith("./") else m.name
            if name in ("", "."):
                continue
            if name == "spoolman.db" and m.isfile():
                w.spoolman(tf.extractfile(m), m.mtime, m.mode, m.uname, m.gname)
                continue
            root = next((r for r in names if name == r or name.startswith(r + "/")), None)
            if root is None or not (m.isfile() or m.isdir()):
                continue
            rel = name[len(root) + 1:]
            if rel and (_excluded(root, rel) or _bad_rel(rel)):
                continue
            if m.isdir():
                w.folder(root, rel, m.mode, m.uname, m.gname)
                continue
            data = tf.extractfile(m)
            if root == "etc/filament-kit" and rel == "config.json":
                raw = data.read(16 * 2**20)
                try:
                    import json
                    mods = sorted(modules.enabled(json.loads(raw.decode("utf-8"))))
                except (ValueError, UnicodeDecodeError, AttributeError, TypeError):
                    mods = []
                data = io.BytesIO(raw)
            w.file(root, rel, data, m.mtime, m.mode, m.uname, m.gname)
    w.finish(kit=__version__, created=os.stat(tar_path).st_mtime, mods=mods, units={}, source=f"daily {tar_path.name}")


# ---------------------------------------------------------------- listing

@dataclass
class Entry:
    name: str           # the file in the backups folder
    download: str       # the name the browser saves
    size: int
    at: float
    kind: str           # made | pre-restore | daily


def open_for_download(name: str) -> tuple[int, str]:
    """(an open file descriptor of the zip, the name to save it as) for the backup `name` in the listing: a stored zip
    as it is, a nightly tar.gz turned into the zip in an anonymous temporary file. Root: the folder is root only.
    BackupError when there is no such backup."""
    found = next((e for e in listing() if e.name == name), None)
    if found is None:
        raise BackupError("no such backup")
    path = backups_dir() / found.name
    if found.kind != "daily":
        return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)), found.download
    tmp = tempfile.TemporaryFile()
    try:
        from_daily(path, tmp)
        tmp.flush()
        fd = os.dup(tmp.fileno())
    finally:
        tmp.close()
    os.lseek(fd, 0, os.SEEK_SET)
    return fd, found.download


def listing(folder: Path | None = None) -> list[Entry]:
    folder = folder or backups_dir()
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for n in names:
        p = folder / n
        if not p.is_file() or p.is_symlink():
            continue
        if NAME.fullmatch(n):
            kind, download = ("pre-restore" if n.startswith(PRE_RESTORE) else "made"), n
        elif DAILY.fullmatch(n):
            kind = "daily"
            download = zip_name(now=p.stat().st_mtime)
        else:
            continue
        st = p.stat()
        out.append(Entry(n, download, st.st_size, st.st_mtime, kind))
    return sorted(out, key=lambda e: e.at, reverse=True)


# ---------------------------------------------------------------- reading

@dataclass
class Item:
    root: str
    path: str           # "" for the root folder itself
    kind: str           # root | dir | file
    mode: int
    owner: str
    group: str
    sha256: str = ""
    size: int = 0


@dataclass
class Manifest:
    kit: str
    api: str
    host: str
    created: str
    source: str
    modules: list[str]
    units: dict[str, str]
    items: list[Item] = field(default_factory=list)
    spoolman: Item | None = None

    @property
    def files(self) -> list[Item]:
        return [i for i in self.items if i.kind == "file"]

    def summary(self) -> dict:
        return {"kit": self.kit, "host": self.host, "created": self.created, "modules": self.modules,
                "files": len(self.files), "spoolman": self.spoolman is not None,
                "size": sum(i.size for i in self.files) + (self.spoolman.size if self.spoolman else 0)}


def _bad_rel(rel: str) -> bool:
    parts = rel.split("/")
    return (not rel or rel.startswith("/") or "\\" in rel or "\0" in rel or len(rel) > 1024
            or any(p in ("", ".", "..") for p in parts))


def _mode(text: str | None, kind: str) -> int:
    if not text or not re.fullmatch(r"[0-7]{3,4}", text):
        raise BackupError("the manifest has a bad mode")
    m = int(text, 8)
    return m & (0o3777 if kind != "file" else 0o0777)       # never a set-user-id bit; setgid only on folders


def _who(text: str | None) -> str:
    text = text or ""
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}|\d{1,10}|", text):
        raise BackupError("the manifest has a bad owner or group")
    return text


def verify(path: Path) -> Manifest:
    """Read and check a backup zip: its manifest, that it lists exactly what the zip holds, and every hash."""
    names = {r for r, _ in roots()}
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise BackupError(f"not a zip file ({type(e).__name__})") from None
    with zf:
        try:
            info = zf.getinfo("manifest.xml")
        except KeyError:
            raise BackupError("this zip is not a filament-kit backup: it has no manifest.xml") from None
        if info.file_size > MAX_MANIFEST:
            raise BackupError("the manifest is too large")
        try:
            root = SafeET.fromstring(zf.read(info))
        except Exception:  # noqa: BLE001 - defusedxml raises its own and the parser's errors
            raise BackupError("the manifest cannot be read") from None
        if root.tag != "filament-kit-backup" or root.get("format") != FORMAT:
            raise BackupError("this backup has a format this kit does not know")
        kit = root.get("kit") or ""
        try:
            release.parse_version(kit)
        except release.ReleaseError:
            raise BackupError("the manifest names no kit version") from None
        m = Manifest(kit=kit, api=root.get("api") or "", host=re.sub(r"[^A-Za-z0-9-]", "", root.get("host") or "")[:63],
                     created=(root.get("created") or "")[:40], source=(root.get("source") or "")[:120],
                     modules=sorted({e.get("name") for e in root.iterfind("modules/module")
                                     if e.get("name") in modules.MODULES}),
                     units={e.get("name"): (e.get("enabled") or "")[:40] for e in root.iterfind("units/unit")
                            if re.fullmatch(r"[A-Za-z0-9@._-]{1,100}", e.get("name") or "")})
        expected = {"manifest.xml"}
        seen_paths = set()
        for e in root.iterfind("files/*"):
            kind = e.tag
            if kind not in ("root", "dir", "file") or e.get("root") not in names:
                raise BackupError("the manifest names a place outside the kit's folders")
            rel = "" if kind == "root" else (e.get("path") or "")
            if kind != "root" and _bad_rel(rel):
                raise BackupError("the manifest names a path outside its folder")
            key = (e.get("root"), rel)
            if key in seen_paths:
                raise BackupError("the manifest names one path twice")
            seen_paths.add(key)
            item = Item(e.get("root"), rel, kind, _mode(e.get("mode"), kind), _who(e.get("owner")), _who(e.get("group")))
            if kind == "file":
                item.sha256 = e.get("sha256") or ""
                try:
                    item.size = int(e.get("size") or "-1")
                except ValueError:
                    item.size = -1
                if not re.fullmatch(r"[0-9a-f]{64}", item.sha256) or item.size < 0:
                    raise BackupError("the manifest has a bad hash or size")
                expected.add(f"files/{item.root}/{rel}")
            m.items.append(item)
        sp = root.find("spoolman")
        if sp is not None:
            m.spoolman = Item("", "spoolman.db", "file", _mode(sp.get("mode"), "file"), _who(sp.get("owner")),
                              _who(sp.get("group")), sp.get("sha256") or "", int(sp.get("size") or "-1"))
            if not re.fullmatch(r"[0-9a-f]{64}", m.spoolman.sha256) or m.spoolman.size < 0:
                raise BackupError("the manifest has a bad hash or size")
            expected.add("spoolman/spoolman.db")
        held = {i.filename for i in zf.infolist()}
        if held != expected:
            raise BackupError("the zip and its manifest do not match: "
                              + ("files not listed are in it" if held - expected else "listed files are missing"))
        total = sum(i.size for i in m.files) + (m.spoolman.size if m.spoolman else 0)
        if total > MAX_TOTAL:
            raise BackupError("the backup is larger than a kit restores")
        for it in m.files + ([m.spoolman] if m.spoolman else []):
            name = "spoolman/spoolman.db" if it is m.spoolman else f"files/{it.root}/{it.path}"
            h, n = hashlib.sha256(), 0
            try:
                with zf.open(name) as src:
                    while chunk := src.read(CHUNK):
                        n += len(chunk)
                        if n > it.size:
                            break
                        h.update(chunk)
            except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError):
                n = -1                      # damaged compressed data: the same answer as a changed file
            if n != it.size or h.hexdigest() != it.sha256:
                raise BackupError(f"a file in the backup is damaged or changed ({it.root or 'spoolman'}/{it.path})")
    return m


def refusal(m: Manifest) -> str | None:
    """Why this kit will not restore `m`, or None."""
    if release.parse_version(m.kit) > release.parse_version(__version__):
        return (f"this backup was made by filament-kit {m.kit}, newer than this {__version__}: install {m.kit} first "
                f"({config.GET_COMMAND} --version {m.kit}), then restore")
    return None


# ---------------------------------------------------------------- restoring

def _has_data() -> bool:
    return (config.paths().etc / "config.json").exists()


# Who owns a restored file is never read from the zip (audit v0.5.0, finding 1: a zip written by a compromised service
# user could give it the setup code). Under /etc the kit's own files keep the modes the kit gives them; every other
# file there is root's alone, 600 (folders 700), and `modules apply` afterwards sets what a module needs. The state
# folders belong to their service user, as on any install; their modes come from the zip, never above 666/777.
SERVICE_READS = {"config.json": 0o640, "anthropic_key": 0o640, "web_passphrase": 0o640, "github_token": 0o640,
                 "key.pem": 0o640,                              # root:filament-kit, as the kit writes them
                 "local_intake_token": 0o640}                   # the local label reader's bearer token, when set
WORLD_READS = {"cert.pem": 0o644, "bambu_hardware.xml": 0o644, "bambu_hardware.xml.previous": 0o644,
               "klipper_hardware.xml": 0o644, "klipper_hardware.xml.previous": 0o644}     # root:root
STATE_OWNER = {"var/lib/filament-kit": "filament-kit", "var/lib/filament-kit-web": "filament-kit-web"}


def _policy(it: Item, folder: tuple[int, int, int] | None = None) -> tuple[str, str, int]:
    """(owner, group, mode) a restored item gets here. `folder`: (uid, gid, mode) of the root folder the install in
    place has, kept for the root folder itself."""
    if it.kind == "root" and folder is not None:
        return str(folder[0]), str(folder[1]), folder[2] & 0o2755
    if it.root in STATE_OWNER:
        user = STATE_OWNER[it.root]
        return user, user, it.mode & (0o777 if it.kind != "file" else 0o666)
    if it.kind == "root":
        return "root", "root", 0o755
    if it.kind == "dir":
        return "root", "root", 0o700
    if it.root == "etc/filament-kit" and "/" not in it.path:
        if it.path in SERVICE_READS:
            return "root", "filament-kit", SERVICE_READS[it.path]
        if it.path in WORLD_READS:
            return "root", "root", WORLD_READS[it.path]
    return "root", "root", 0o600


def _own(path: Path, it: Item, folder: tuple[int, int, int] | None = None) -> bool:
    """The policy's mode, and its owners when they exist here; False when one does not exist yet."""
    owner, group, mode = _policy(it, folder)
    os.chmod(path, mode)
    if not _is_root():
        return True
    if owner.isdigit() and group.isdigit():
        ids = (int(owner), int(group))
    else:
        ids = _ids(owner, group) or (_ids(owner, owner) if group != owner else None)
    if ids is None:
        return False
    os.chown(path, *ids, follow_symlinks=False)
    return True


def _spoolman_own(path: Path, it: Item) -> None:
    """The Spoolman database: owned like the folder it sits in (Spoolman's), never more open than 664."""
    os.chmod(path, it.mode & 0o664)
    if _is_root():
        st = os.stat(path.parent)
        os.chown(path, st.st_uid, st.st_gid, follow_symlinks=False)


def _extract(zf: zipfile.ZipFile, items: list[Item], target: Path, folder=None) -> None:
    """Every item of one root into the empty folder `target`; `folder`: the install's own root folder (_policy)."""
    for it in sorted((i for i in items if i.kind != "file"), key=lambda i: i.path.count("/") if i.path else -1):
        d = target / it.path if it.path else target
        d.mkdir(parents=True, exist_ok=True)
    for it in (i for i in items if i.kind == "file"):
        dst = target / it.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
                     0o600)
        with os.fdopen(fd, "wb") as out, zf.open(f"files/{it.root}/{it.path}") as src:
            shutil.copyfileobj(src, out, CHUNK)
    for it in sorted(items, key=lambda i: -i.path.count("/") if i.path else 1):     # folders last, deepest first
        _own(target / it.path if it.path else target, it, folder)


def _stop_kit(run: Callable[[list[str]], int]) -> None:
    if _no_systemd():
        return
    from . import apply
    units = sorted({f for m in modules.MODULES.values() for u in m.units for f in apply._unit_files(u) if "@" not in f})
    run(["systemctl", "stop", *units])


def restore(zip_path: Path, *, yes: bool = False, ask: Callable[[str], str] = input,
            run: Callable[[list[str]], int] | None = None, out=print) -> int:
    """Bring this machine to the state in the backup. 0 when the data is back and the apply worked."""
    run = run or default_run
    try:
        m = verify(Path(zip_path))
    except BackupError as e:
        out(f"error: {e}. Nothing was changed.")
        return 1
    why = refusal(m)
    if why:
        out(f"error: {why}. Nothing was changed.")
        return 1
    s = m.summary()
    out(f"Backup of {m.host or 'a kit'} made {m.created} by filament-kit {m.kit}: {s['files']} files"
        + (", the Spoolman database" if m.spoolman else "") + f"; modules {', '.join(m.modules) or 'none'}.")
    other_host = bool(m.host) and m.host != host()
    if _has_data():
        out("This replaces the spools, settings, printers and pairings on this machine. What is there now is kept as a "
            f"backup in {backups_dir()} first.")
    if not yes:
        try:
            if ask("Type restore to go on: ").strip() != "restore":
                out("Not restored. Nothing was changed.")
                return 1
        except (EOFError, OSError, RuntimeError):
            out("error: no answer (no terminal): run it again with --yes. Nothing was changed.")
            return 1
    if _has_data():
        try:
            kept = create(prefix=PRE_RESTORE)
            out(f"What was here is kept in {kept}.")
        except (OSError, sqlite3.Error) as e:
            out(f"error: could not keep a backup of what is here first ({type(e).__name__}). Nothing was changed.")
            return 1
    _stop_kit(run)
    here = dict(roots())
    folders = {}            # each root folder's owner and mode on this install: the restored one keeps them
    for name, target in here.items():
        try:
            st = os.stat(target)
            folders[name] = (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode))
        except OSError:
            folders[name] = None
    swapped: list[tuple[Path, Path | None]] = []        # (target, its old copy or None)
    db_target, db_old = spoolman_db(), None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in sorted({i.root for i in m.items}):
                target = here[name]
                new = target.with_name(target.name + NEW)
                shutil.rmtree(new, ignore_errors=True)
                _extract(zf, [i for i in m.items if i.root == name], new, folders.get(name))
                old = target.with_name(target.name + OLD)
                shutil.rmtree(old, ignore_errors=True)
                if target.exists():
                    os.replace(target, old)
                    swapped.append((target, old))
                else:
                    swapped.append((target, None))
                os.replace(new, target)
            if m.spoolman:
                db_target.parent.mkdir(parents=True, exist_ok=True)
                tmp = db_target.with_name(db_target.name + NEW)
                with open(tmp, "wb") as fh, zf.open("spoolman/spoolman.db") as src:
                    shutil.copyfileobj(src, fh, CHUNK)
                if db_target.exists():
                    db_old = db_target.with_name(db_target.name + OLD)
                    os.replace(db_target, db_old)
                os.replace(tmp, db_target)
                _spoolman_own(db_target, m.spoolman)
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        for target, old in reversed(swapped):
            shutil.rmtree(target, ignore_errors=True)
            if old is not None:
                os.replace(old, target)
        if db_old is not None:
            os.replace(db_old, db_target)
        why = f"{type(e).__name__}: {e.strerror if isinstance(e, OSError) else e}"
        if _has_data() and run([WRAPPER, "modules", "apply", "--no-pair"]) == 0:      # it was stopped above
            out(f"error: the restore stopped ({why}); what was here is back in place and running again.")
        else:
            out(f"error: the restore stopped ({why}); what was here is back in place. Start the kit again with: "
                "sudo filament-kit modules apply")
        return 1
    if other_host:
        for n in ("cert.pem", "key.pem"):
            (config.paths().etc / n).unlink(missing_ok=True)
        out(f"The backup is from {m.host}, this machine is {host()}: the server gets a new certificate. Pair the phones "
            "and the PC sync again (Devices on the setup page).")
    out("The data is back. Setting up the modules it names (this installs their packages and may take a while)...")
    rc = run([WRAPPER, "modules", "apply", "--no-pair"])
    # the apply made the users the kit's modules need: the files restored before them get their owners now
    for i in m.items:
        try:
            _own(here[i.root] / i.path if i.path else here[i.root], i, folders.get(i.root))
        except OSError:
            pass
    if not _no_systemd():          # they started under the apply, perhaps before their files were theirs
        from . import apply
        services = sorted({f for n in m.modules if n in modules.MODULES for u in modules.MODULES[n].units
                           for f in apply._unit_files(u) if f.endswith(".service") and "@" not in f})
        if services:
            run(["systemctl", "try-restart", *services])
    if rc != 0:
        out("error: the data is back, but setting up the modules failed. Finish with: sudo filament-kit modules apply"
            + "".join(f"\n  the earlier {t} is in {o}" for t, o in swapped if o is not None))
        return 1
    for _target, old in swapped:
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    if db_old is not None:
        db_old.unlink(missing_ok=True)
    out("Restored. The setup code, trusted computers, printers and pairings are the ones in the backup.")
    run([WRAPPER, "status"])
    return 0


def uploaded() -> Path:
    """Where the setup page writes a zip it receives, until the helper pins it (pin_upload)."""
    return config.paths().state / UPLOAD / "backup.zip"


PENDING = ".restore-pending.zip"        # in the root-only backups folder: the upload the owner saw summarised
CONFIRMED = ".restore-pending.sha256"   # its hash, once the owner typed restore (the helper, before the job)


def pending() -> Path:
    return backups_dir() / PENDING


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _open_upload() -> int:
    """The page's upload, opened by root without following a link anywhere in the folders the service user owns."""
    src = uploaded()
    if not (hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd):
        return os.open(src, os.O_RDONLY | getattr(os, "O_BINARY", 0))       # Windows: only the tests run there
    nofollow = os.O_RDONLY | os.O_NOFOLLOW
    top = os.open(src.parent.parent.parent, os.O_RDONLY | os.O_DIRECTORY)    # /var/lib: root's
    fds = [top]
    try:
        for name in (src.parent.parent.name, src.parent.name):
            fds.append(os.open(name, nofollow | os.O_DIRECTORY, dir_fd=fds[-1]))
        return os.open(src.name, nofollow | os.O_NONBLOCK, dir_fd=fds[-1])
    finally:
        for fd in fds:
            os.close(fd)


def pin_upload() -> tuple[Manifest, str]:
    """Root (the setup helper, when the page checks an upload): copy the page's upload at once into the root-only
    backups folder, hash it and check it (the server removes its own copy). What the owner then sees summarised is
    this copy, and only this copy is restored (take_upload), so the service user cannot swap the file afterwards."""
    try:
        fd = _open_upload()
    except FileNotFoundError:
        raise BackupError("no backup was uploaded on the setup page") from None
    except OSError as e:
        raise BackupError(f"the uploaded backup cannot be opened safely ({type(e).__name__})") from None
    dest = backups_dir()
    dest.mkdir(parents=True, exist_ok=True)
    out, tmp = dest / PENDING, dest / (PENDING + ".tmp")
    (dest / CONFIRMED).unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)
    h = hashlib.sha256()
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BackupError("the upload is not a plain file")
        wfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
                      0o600)
        with os.fdopen(wfd, "wb") as w:
            while chunk := os.read(fd, CHUNK):
                h.update(chunk)
                w.write(chunk)
        os.replace(tmp, out)
    finally:
        os.close(fd)
        tmp.unlink(missing_ok=True)
    try:
        m = verify(out)
        why = refusal(m)
        if why:
            raise Unfit(why)
    except BackupError:
        out.unlink(missing_ok=True)
        raise
    return m, h.hexdigest()


def confirm_pending(sha: str) -> None:
    """The helper, when the owner typed restore: the pinned upload is still the one they saw (its hash), noted for
    the root job. Nothing else is restored."""
    p = pending()
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise BackupError("upload and check the backup again (the page did not say which one it showed)")
    if not p.is_file():
        raise BackupError("upload the backup zip first")
    if not hmac.compare_digest(_sha256(p), sha):
        raise BackupError("the uploaded backup is not the one that was checked; upload it again")
    fd = os.open(backups_dir() / CONFIRMED, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(sha + "\n")


def forget_pending() -> None:
    for name in (PENDING, CONFIRMED):
        (backups_dir() / name).unlink(missing_ok=True)


def take_upload() -> Path:
    """The root job: the pinned upload, if its hash is still the one the owner confirmed, moved aside for the
    restore (which replaces the state folder)."""
    p, c = pending(), backups_dir() / CONFIRMED
    try:
        want = c.read_text(encoding="ascii").strip()
    except OSError:
        raise BackupError("no checked and confirmed backup is waiting; upload it on the setup page again") from None
    if not p.is_file() or not hmac.compare_digest(_sha256(p), want):
        forget_pending()
        raise BackupError("the uploaded backup changed since it was confirmed; nothing was restored")
    out = backups_dir() / f".restore-{int(time.time())}.zip"
    os.replace(p, out)
    c.unlink(missing_ok=True)
    return out


def keep_days(cfg: dict) -> int:
    v = (cfg.get("backup") or {}).get("keep_days", 14)
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 365 else 14


if __name__ == "__main__":     # pragma: no cover - `python -m filament_kit.backup keep-days` for install/backup.sh
    if sys.argv[1:] == ["keep-days"]:
        try:
            print(keep_days(config.load()))
        except Exception:  # noqa: BLE001
            print(14)
