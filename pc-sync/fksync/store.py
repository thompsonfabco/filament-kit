"""The PC sync's own files: config, encrypted token, log, lock and state paths.

The token is encrypted with Windows DPAPI (CurrentUser scope, entropy b"filament-kit-sync"),
so only this Windows user on this PC can read it. Off Windows (tests, CI) it is a 0600 plain
file. The token is never logged or printed by this module.
"""
import contextlib
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

ENTROPY = b"filament-kit-sync"
LOG_MAX = 1024 * 1024
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class AlreadyRunning(Exception):
    pass


class AppDirs:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.config = self.base / "config.json"
        self.token = self.base / "token.bin"
        self.log_file = self.base / "sync.log"
        self.backups = self.base / "backups"
        self.installed = self.base / "installed"
        self.partial = self.base / "partial"      # a build whose install stopped part-way (ruling S28)
        self.state = self.base / "state.json"
        self.lock = self.base / "sync.lock"

    def ensure(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)


def _write_atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write data to a temp file next to path, then replace path with it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if sys.platform != "win32":
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# --- DPAPI (Windows) -------------------------------------------------------------------------

def _blob_api():
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    proto = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    crypt32.CryptProtectData.argtypes = proto
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR)] + proto[2:]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return ctypes, DATA_BLOB, crypt32, kernel32


def _dpapi(data: bytes, entropy: bytes, protect: bool) -> bytes:
    ctypes, DATA_BLOB, crypt32, kernel32 = _blob_api()
    in_buf, ent_buf = ctypes.create_string_buffer(data, len(data)), ctypes.create_string_buffer(entropy, len(entropy))
    blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    blob_ent = DATA_BLOB(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), "filament-kit-sync", ctypes.byref(blob_ent),
                                      None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
                                        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _dpapi_protect(data: bytes, entropy: bytes = ENTROPY) -> bytes:
    return _dpapi(data, entropy, True)


def _dpapi_unprotect(data: bytes, entropy: bytes = ENTROPY) -> bytes:
    return _dpapi(data, entropy, False)


# --- token -------------------------------------------------------------------------------------

def save_token(dirs: AppDirs, token: str) -> None:
    raw = token.encode("utf-8")
    _write_atomic(dirs.token, _dpapi_protect(raw) if sys.platform == "win32" else raw)


def load_token(dirs: AppDirs) -> str | None:
    """The stored token, or None when there is none or it cannot be decrypted (re-pair then)."""
    try:
        raw = dirs.token.read_bytes()
    except FileNotFoundError:
        return None
    if sys.platform == "win32":
        try:
            raw = _dpapi_unprotect(raw)
        except OSError:
            return None
    try:
        token = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return token or None


# --- config ------------------------------------------------------------------------------------

def load_config(dirs: AppDirs) -> dict:
    try:
        text = dirs.config.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        cfg = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"sync config {dirs.config} is not valid JSON: {e}") from None
    if not isinstance(cfg, dict):
        raise ValueError(f"sync config {dirs.config} is not a JSON object")
    return cfg


def save_config(dirs: AppDirs, cfg: dict) -> None:
    _write_atomic(dirs.config, (json.dumps(cfg, indent=2, sort_keys=True) + "\n").encode("utf-8"))


# --- log ---------------------------------------------------------------------------------------

def log(dirs: AppDirs, msg: str) -> None:
    """Append a timestamped line; rotate to sync.log.1 once the log reaches 1 MiB."""
    dirs.ensure()
    with contextlib.suppress(FileNotFoundError):
        if dirs.log_file.stat().st_size >= LOG_MAX:
            os.replace(dirs.log_file, dirs.log_file.with_name(dirs.log_file.name + ".1"))
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n"
    with open(dirs.log_file, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)


# --- single instance ---------------------------------------------------------------------------

@contextlib.contextmanager
def single_instance(dirs: AppDirs):
    """Hold an exclusive lock on dirs.lock for the duration; AlreadyRunning if another run holds it."""
    dirs.ensure()
    f = open(dirs.lock, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise AlreadyRunning("another filament-kit-sync run is in progress") from None
            try:
                yield
            finally:
                f.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise AlreadyRunning("another filament-kit-sync run is in progress") from None
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()
