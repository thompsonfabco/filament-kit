"""Setting up a bench reader (ESP32-C3) with the firmware as it is: its Wi-Fi, server address, token and update key
are compiled in from `reader/src/secrets.h`, so a setup is a token, that file, a PlatformIO build and a USB flash
(reader/README.md, "Build"). This module finds a reader on USB, writes `secrets.h` and runs the build and flash; the
CLI is `filament-kit reader setup`. Nothing secret is printed or logged: the token and the Wi-Fi password go only
into the file, which is written 0600 and, for a flash, into a private temporary folder deleted afterwards.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    import pwd
except ImportError:         # Windows: only the tests run there
    pwd = None

ESPRESSIF_VID = "303a"          # the ESP32-C3's own USB serial/JTAG unit (and every Espressif board's)
ENV = "esp32-c3-supermini"      # reader/platformio.ini
SYSFS = Path("/sys/bus/usb/devices")
BY_ID = Path("/dev/serial/by-id")
TTY = re.compile(r"tty[A-Za-z]+[0-9]+")
PEM = re.compile(r"-----BEGIN PUBLIC KEY-----\n[A-Za-z0-9+/=\n]+-----END PUBLIC KEY-----\n?")
PLACEHOLDER_KEY = ("-----BEGIN PUBLIC KEY-----\nREPLACE-WITH-THE-KEY-FROM-ota_publish.py--init-key\n"
                   "-----END PUBLIC KEY-----\n")


class SetupError(Exception):
    pass


@dataclass
class Reader:
    port: str           # /dev/ttyACM0
    by_id: str | None   # /dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_..., when udev made one
    product: str


def find_readers(sysfs: Path = SYSFS, by_id: Path = BY_ID) -> list[Reader]:
    """Espressif USB devices with a tty, from sysfs. Today's firmware says nothing on USB, so this is the board, not
    proof that it holds the reader firmware."""
    links: dict[str, str] = {}
    if by_id.is_dir():
        for link in by_id.iterdir():
            try:
                links[os.path.realpath(link)] = str(link)
            except OSError:
                continue
    out = []
    if not sysfs.is_dir():
        return out
    for dev in sorted(sysfs.iterdir()):
        try:
            vid = (dev / "idVendor").read_text().strip().lower()
        except OSError:
            continue
        if vid != ESPRESSIF_VID:
            continue
        product = _read(dev / "product") or "Espressif USB device"
        for tty in sorted(dev.glob("*/tty/tty*")) + sorted(dev.glob("*/tty*")):
            if not TTY.fullmatch(tty.name):        # ttyACM0, ttyUSB0; not the "tty" folder itself
                continue
            port = f"/dev/{tty.name}"
            if all(r.port != port for r in out):
                out.append(Reader(port, links.get(port), product))
    return out


def _read(p: Path) -> str | None:
    try:
        return p.read_text().strip() or None
    except OSError:
        return None


def reader_base(cfg: dict) -> str:
    """The reader's READER_BASE: the kit's public HTTPS address plus /reader (the reader pins a public root
    certificate, so only that address works)."""
    url = str((cfg.get("web") or {}).get("public_url") or "").rstrip("/")
    if not url.startswith("https://"):
        raise SetupError("web.public_url is not an https address, and the reader only calls the kit over its public "
                         "HTTPS address (set it with the web module, see docs/remote-access.md)")
    return url + "/reader"


def c_string(text: str) -> str:
    """`text` as a C string literal. Every byte outside printable ASCII, and \\ " ?, as three-digit octal, which
    (unlike \\x) never runs into the next character."""
    out = []
    for b in text.encode("utf-8"):
        ch = chr(b)
        out.append(ch if 0x20 <= b < 0x7f and ch not in '\\"?' else f"\\{b:03o}")
    return '"' + "".join(out) + '"'


def pubkey(text: str | None) -> tuple[str, bool]:
    """The OTA public key PEM to compile in, and whether it is a real one (None: the placeholder, refusing every
    update until the reader is flashed again with a key)."""
    if text is None:
        return PLACEHOLDER_KEY, False
    pem = text.replace("\r\n", "\n").strip() + "\n"
    if not PEM.fullmatch(pem):
        raise SetupError("the OTA key file is not a PEM public key (print it with: py tools/ota_publish.py --init-key)")
    return pem, True


def secrets_h(ssid: str, password: str, base: str, token: str, key_pem: str) -> str:
    if not ssid or len(ssid.encode()) > 32:
        raise SetupError("the Wi-Fi name must be 1 to 32 bytes")
    if len(password.encode()) > 63:
        raise SetupError("the Wi-Fi password must be at most 63 bytes")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        raise SetupError("that is not a reader token")
    return ("// Written by `filament-kit reader setup`. It holds the reader's token and the Wi-Fi password: keep it\n"
            "// out of version control and delete it once the reader is flashed.\n"
            "#pragma once\n"
            f"static const char* WIFI_SSID = {c_string(ssid)};\n"
            f"static const char* WIFI_PASS = {c_string(password)};\n"
            f"static const char* READER_BASE = {c_string(base)};\n"
            f"static const char* READER_TOKEN = {c_string(token)};\n"
            f'static const char* OTA_PUBKEY = R"KEY({key_pem})KEY";\n')


def write_private(path: Path, text: str) -> None:
    """`text` into `path`, created 0600 (never through a link), written whole."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


@dataclass
class Owner:
    """Who builds and flashes: under sudo the user who ran it (root never runs PlatformIO, the checkout's build
    scripts or the toolchain's downloads), else whoever runs the command."""
    name: str
    uid: int
    gid: int
    home: Path


def owner(environ=os.environ) -> Owner | None:
    """The user behind sudo, or None when there is none (not sudo, sudo from root, or no such user)."""
    name, uid = environ.get("SUDO_USER"), environ.get("SUDO_UID")
    if pwd is None or not name or not uid or name == "root" or not uid.isdigit():
        return None
    try:
        pw = pwd.getpwnam(name)
    except KeyError:
        return None
    if pw.pw_uid != int(uid):
        return None
    return Owner(pw.pw_name, pw.pw_uid, pw.pw_gid, Path(pw.pw_dir))


def _bin_dirs(home: Path) -> list[Path]:
    """Where a user's PlatformIO lands: its installer's ~/.platformio/penv/bin, pip --user's ~/.local/bin."""
    return [home / ".platformio" / "penv" / "bin", home / ".local" / "bin"]


def find_pio(who: Owner | None = None) -> str | None:
    """PlatformIO's command: in `who`'s home and the system's folders when given (sudo's PATH and HOME are root's),
    else on PATH and in this user's home."""
    if who is not None:
        dirs = _bin_dirs(who.home) + [Path(p) for p in ("/usr/local/bin", "/usr/bin")]
    else:
        for name in ("pio", "platformio"):
            hit = shutil.which(name)
            if hit:
                return hit
        dirs = _bin_dirs(Path.home())
    for d in dirs:
        for name in ("pio", "platformio"):
            f = d / name
            if f.is_file() and os.access(f, os.X_OK):
                return str(f)
    return None


def is_source(folder: Path) -> bool:
    return (folder / "platformio.ini").is_file() and (folder / "src" / "main.cpp").is_file()


def _give(tree: Path, who: Owner) -> None:
    """The private copy to `who` (the folder stays 0700 and secrets.h 0600: only they and root can read it)."""
    os.chown(tree.parent, who.uid, who.gid)
    for dirpath, dirnames, filenames in os.walk(tree):
        os.chown(dirpath, who.uid, who.gid, follow_symlinks=False)
        for n in dirnames + filenames:
            os.chown(os.path.join(dirpath, n), who.uid, who.gid, follow_symlinks=False)


def flash(source: Path, secrets: str, port: str, pio: str, run=subprocess.run, who: Owner | None = None) -> int:
    """Build the reader from `source` with `secrets` and flash it to `port`. The sources are copied into a private
    temporary folder (secrets.h never lands in the checkout) that is deleted afterwards. With `who` (sudo), the copy
    is theirs and pio runs as them, with their groups (dialout: the serial port) and home (PlatformIO's toolchain).
    PlatformIO's own output is shown; it never prints secrets.h. Returns pio's exit status."""
    if not is_source(source):
        raise SetupError(f"{source} is not the reader's source folder (it has no platformio.ini and src/main.cpp)")
    work = Path(tempfile.mkdtemp(prefix="fk-reader-"))     # 0700
    try:
        tree = work / "reader"
        shutil.copytree(source, tree, symlinks=True,
                        ignore=shutil.ignore_patterns(".pio", "secrets.h", "__pycache__"))
        write_private(tree / "src" / "secrets.h", secrets)
        cmd = [pio, "run", "-d", str(tree), "-e", ENV, "-t", "upload", "--upload-port", port]
        if who is None:
            return run(cmd).returncode
        _give(tree, who)
        env = {"HOME": str(who.home), "USER": who.name, "LOGNAME": who.name, "LANG": os.environ.get("LANG", "C.UTF-8"),
               "PATH": os.pathsep.join([str(d) for d in _bin_dirs(who.home)] + ["/usr/local/bin", "/usr/bin", "/bin"])}
        groups = os.getgrouplist(who.name, who.gid)
        return run(cmd, user=who.uid, group=who.gid, extra_groups=groups, env=env, cwd=str(work)).returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)


def out_ok(path: Path, uid: int) -> bool:
    """--out may create a file, or replace a regular file of `uid`'s; never anything else (a typo like /etc/hosts)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return True
    import stat as _stat
    return _stat.S_ISREG(st.st_mode) and st.st_uid == uid
