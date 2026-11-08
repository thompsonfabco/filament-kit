"""The filament spec library: downloaded on request, validated updates with rollback, and local additions.

The program does not bundle the library (the wheel carries only the schema and an empty index, version 0);
`update` downloads it from `library.url`, a release asset `library*.tar.gz` (or a directory URL serving
index.json and the entries). An archive from a GitHub release (the default URL) is checked against that release's
signed SHA256SUMS (release.verify_sums, the program's own release key) before it is unpacked, and refused without
it; a custom mirror is checked the same way when it serves SHA256SUMS next to the archive, else only by the
per-entry hashes in its index.json (the result carries a note saying so). With nothing downloaded, `load()` is an
empty library and profiles are built from Spoolman values and the Bambu/Orca parents alone. An install that
already downloaded a copy keeps using it.

Layout in the state directory:
  library/current.json            {"dir", "version", "at"}: the version directory in use (absent = none)
  library/previous.json           the current.json before the last update (absent = none)
  library/last_check.json         {"at", "ok", "error", "last_ok_at"}
  library/versions/<v>-<stamp>/   index.json + library/<vendor>/<product>.json
  library-local/<vslug>/<pslug>.json   the owner's own additions; never touched by `update`

`validate` is a port of filament-library `tools/fl.py` (schema_version 1), so no jsonschema dependency.

Compatibility: the library moves faster than an installed kit. Authoring stays strict (the library's own tools and `add_local`, so
a typo is caught where it's made), and so does anything unsigned. Installing a SIGNED library (`update`) drops what this kit can't
validate, a field or a whole entry, and says how many in `status`: the data is signed and the slicer's parent preset is the fallback.
It refuses instead when more than MAX_DROPPED of the entries would go, which looks like a broken release, not newer rules. A wrong
hash, an unreadable file or an entry at the wrong path is fatal, and a different index `schema_version` refuses and says why.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import hmac
import io
import json
import logging
import os
import re
import shutil
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import __version__, config, release
from .pairing import _write_atomic, give_to_state_owner, make_state_dir, open_lock

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the service only runs on Linux)
    fcntl = None

DEFAULT_LIBRARY_URL = "https://github.com/thompsonfabco/filament-kit/releases/latest/download/library.tar.gz"
BUNDLED = Path(__file__).parent / "library_data"   # schema + an empty index; the entries are downloaded
SCHEMA_VERSION = 1

INDEX_LIMIT = 8 * 2**20
ENTRY_LIMIT = 256 * 2**10
LOCAL_LIMIT = 256 * 2**10
MAX_ENTRIES = 20_000
TIMEOUT = 30
DEADLINE = 600                  # seconds for a whole update
TOTAL_LIMIT = 256 * 2**20       # bytes downloaded by one update
ARCHIVE_LIMIT = 64 * 2**20      # the compressed library tarball
TAR_SUFFIXES = (".tar.gz", ".tgz")
TOKEN_FILE = "github_token"     # in /etc/filament-kit: optional, for a private repository (testing)
PRIVATE_STATUSES = (401, 403, 404)
_clock = time.monotonic
SCHEDULES = {"daily": 20 * 3600, "weekly": 6.5 * 86400, "off": None}

ROW_PATH = re.compile(r"library/[a-z0-9-]+/[a-z0-9-]+\.json")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION_DIR = re.compile(r"\d+-[0-9A-Za-z-]+")
LOCAL_HOST = re.compile(r"http://(127\.0\.0\.1|localhost):\d{1,5}/.*")

# ---------- fl.py port ----------

TOP_KEYS = ["schema_version", "vendor", "product", "material", "colors", "bambu_parent", "orca_parent", "fields",
            "published_ranges", "conflicts", "source_quality", "sources", "updated"]
PARENT_KEYS = ("bambu_parent", "orca_parent")     # optional; orca_parent = OrcaFilamentLibrary base name (Task 3)
REQUIRED = [k for k in TOP_KEYS if k not in PARENT_KEYS]
LOCAL_OPTIONAL = ("sources", "source_quality", "conflicts", "colors", "updated", "published_ranges")
REQUIRED_LOCAL = [k for k in REQUIRED if k not in LOCAL_OPTIONAL]
FIELD_KEYS = ["nozzle_temperature_range_low", "nozzle_temperature_range_high", "filament_density",
              "filament_diameter", "filament_soluble", "filament_is_support", "filament_shrink",
              "filament_max_volumetric_speed"]
RANGE_KEYS = ["bed_all_plates", "cool_plate_temp", "hot_plate_temp", "textured_plate_temp", "chamber_temperatures",
              "fan_max_speed", "fan_min_speed/fan_max_speed", "filament_retraction_length",
              "filament_retraction_speed", "overhang_fan_threshold", "filament_shrink"]
SOURCE_QUALITY = ["official_tds", "official_page", "brand_amazon_listing", "reseller_tds_copy"]
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")   # fl.py runs on 3.10, whose fromisoformat takes only this form


class LibraryError(Exception):
    pass


def slug(text: str) -> str:
    """'PLA+ 2.0' -> 'pla-plus-2-0'; '+' is spelled out so 'PLA' and 'PLA+' never share a file."""
    s = text.lower().replace("+", " plus ").replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def rel_path(entry: dict) -> str:
    return f"library/{slug(entry['vendor'])}/{slug(entry['product'])}.json"


def line_id(vendor: str, product: str) -> str:
    return slug(vendor) + "--" + slug(product)


def canonical(entry: dict) -> dict:
    """Top-level keys in schema order (unknown keys last)."""
    out = {k: entry[k] for k in TOP_KEYS if k in entry}
    out.update({k: v for k, v in entry.items() if k not in out})
    return out


def dumps(entry: dict) -> str:
    return json.dumps(canonical(entry), indent=2, ensure_ascii=False) + "\n"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


log = logging.getLogger(__name__)

MAX_DROPPED = 0.25      # of a signed library's entries; more than this refuses the update


def _first(f: dict, key: str):
    v = f.get(key)
    return v[0] if isinstance(v, list) and v else None


def validate(entry: dict, *, local: bool = False) -> list[str]:
    """List of problems with one entry (empty = valid). `local`: the relaxed rules for the owner's additions,
    where sources, source_quality, conflicts, colors, updated and published_ranges may be left out."""
    if not isinstance(entry, dict):
        return ["entry is not a JSON object"]
    errs = []
    for k in (REQUIRED_LOCAL if local else REQUIRED):
        if k not in entry:
            errs.append(f"missing required key '{k}'")
    for k in entry:
        if k not in TOP_KEYS:
            errs.append(f"unknown top-level key '{k}'")
    if "schema_version" in entry and entry["schema_version"] != SCHEMA_VERSION:
        errs.append(f"schema_version must be {SCHEMA_VERSION}")
    for k in ("vendor", "product", "material", *PARENT_KEYS):
        if k in entry and not (isinstance(entry[k], str) and entry[k].strip()):
            errs.append(f"'{k}' must be a non-empty string")
    if isinstance(entry.get("bambu_parent"), str) and "@" in entry["bambu_parent"]:
        errs.append("bambu_parent must not carry an '@<printer>' suffix")
    if isinstance(entry.get("orca_parent"), str) and "@" in entry["orca_parent"]:
        errs.append("orca_parent must not carry an '@' suffix (give the base name, without ' @System')")
    for k in ("vendor", "product"):
        if isinstance(entry.get(k), str) and not slug(entry[k]):
            errs.append(f"'{k}' has no filesystem-safe characters")
    for k in ("colors", "conflicts"):
        if k in entry and not (isinstance(entry[k], list) and all(isinstance(x, str) for x in entry[k])):
            errs.append(f"'{k}' must be a list of strings")
    if "source_quality" in entry and entry["source_quality"] not in SOURCE_QUALITY:
        errs.append(f"source_quality must be one of {', '.join(SOURCE_QUALITY)}")
    src = entry.get("sources")
    if "sources" in entry:
        if not (isinstance(src, list) and src):
            errs.append("at least one source is required")
        else:
            for s in src:
                try:
                    u = urllib.parse.urlparse(s) if isinstance(s, str) else None
                except ValueError:
                    u = None
                if not (u and u.scheme in ("http", "https") and u.netloc):
                    errs.append(f"source is not an http(s) URL: {s!r}")
    if "updated" in entry:
        try:
            if not (isinstance(entry["updated"], str) and _DATE.fullmatch(entry["updated"])):
                raise ValueError
            datetime.date.fromisoformat(entry["updated"])
        except (TypeError, ValueError):
            errs.append("updated must be a YYYY-MM-DD date")

    f = entry.get("fields")
    if "fields" in entry and not isinstance(f, dict):
        errs.append("fields must be an object")
        f = {}
    f = f if isinstance(f, dict) else {}
    for k, v in f.items():
        errs += _field_errors(k, v)
    lo = _num(_first(f, "nozzle_temperature_range_low"))
    hi = _num(_first(f, "nozzle_temperature_range_high"))
    if lo is not None and hi is not None and lo > hi:
        errs.append(f"nozzle range low {lo:g} is above high {hi:g}")

    pr = entry.get("published_ranges")
    if "published_ranges" in entry and not isinstance(pr, dict):
        errs.append("published_ranges must be an object")
        pr = {}
    for k, v in (pr if isinstance(pr, dict) else {}).items():
        errs += _range_errors(k, v)
    return errs


def _field_errors(k: str, v) -> list[str]:
    if k == "temperature_vitrification":
        return ["fields.temperature_vitrification is not allowed (Bambu's heat-creep threshold, not Tg); "
                "put Tg/Vicat/HDT in published_ranges._vitrification/_vicat/_hdt_0.45MPa"]
    if k not in FIELD_KEYS:
        return [f"unknown fields key '{k}'"]
    if not (isinstance(v, list) and len(v) == 1 and isinstance(v[0], str) and v[0].strip()):
        return [f"fields.{k} must be a one-element string array, got {v!r}"]
    s = v[0]
    x = _num(s)
    if k.startswith("nozzle_temperature_range"):
        if x is None or not 150 <= x <= 450:
            return [f"fields.{k} {s!r} is outside 150-450 C"]
    elif k == "filament_density":
        if x is None or not 0.5 <= x <= 3.0:
            return [f"fields.filament_density {s!r} is outside 0.5-3.0 g/cm3"]
    elif k == "filament_diameter":
        if x not in (1.75, 2.85):
            return [f"fields.filament_diameter {s!r} must be 1.75 or 2.85"]
    elif k in ("filament_soluble", "filament_is_support"):
        if s not in ("0", "1"):
            return [f"fields.{k} must be \"0\" or \"1\""]
    elif k == "filament_shrink":
        if not re.fullmatch(r"\d+(\.\d+)?%", s) or not 90 <= float(s[:-1]) <= 110:
            return [f"fields.filament_shrink {s!r} must be a percentage like \"99.6%\""]
    elif k == "filament_max_volumetric_speed":
        if x is None or not 0 < x <= 100:
            return [f"fields.filament_max_volumetric_speed {s!r} must be a number in (0, 100] mm3/s"]
    return []


def _range_errors(k: str, v) -> list[str]:
    errs = []
    if not (k.startswith("_") or k in RANGE_KEYS):
        errs.append(f"unknown published_ranges key '{k}' (note keys must start with '_')")
    if not (isinstance(v, str) and v.strip()):
        errs.append(f"published_ranges.{k} must be a non-empty string, got {v!r}")
    return errs


def salvage(entry) -> tuple[dict | None, int]:
    """For a signed library's entry that doesn't validate: (what this kit can read of it, or None when that's nothing whole;
    how many parts went). Only parts an entry can do without go: an unknown top-level key, a field, a published range. A
    missing or unreadable required key loses the entry, since the kit would be guessing."""
    if not isinstance(entry, dict):
        return None, 0
    out, gone = {k: v for k, v in entry.items() if k in TOP_KEYS}, 0
    gone += len(entry) - len(out)
    if isinstance(out.get("fields"), dict):
        fields = {k: v for k, v in out["fields"].items() if not _field_errors(k, v)}
        lo, hi = _num(_first(fields, "nozzle_temperature_range_low")), _num(_first(fields, "nozzle_temperature_range_high"))
        if lo is not None and hi is not None and lo > hi:     # neither can be trusted
            fields.pop("nozzle_temperature_range_low")
            fields.pop("nozzle_temperature_range_high")
        gone += len(out["fields"]) - len(fields)
        out["fields"] = fields
    if isinstance(out.get("published_ranges"), dict):
        ranges = {k: v for k, v in out["published_ranges"].items() if not _range_errors(k, v)}
        gone += len(out["published_ranges"]) - len(ranges)
        out["published_ranges"] = ranges
    return (None, gone) if validate(out) else (out, gone)


# ---------- state ----------

_lock = threading.Lock()


@contextmanager
def _locked():
    """Serialize library state changes between threads and with the CLI in another process."""
    with _lock:
        if fcntl is None:
            yield
            return
        state = config.paths().state
        state.mkdir(parents=True, exist_ok=True)
        with open_lock(state / "library.lock") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _dir() -> Path:
    return config.paths().state / "library"


def _local_dir() -> Path:
    return config.paths().state / "library-local"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, obj) -> None:
    make_state_dir(path.parent)
    _write_atomic(path, (json.dumps(obj, indent=2) + "\n").encode("utf-8"), 0o644, state_owned=True)


def _pointer(name: str) -> dict | None:
    """current.json / previous.json, or None when absent or unusable (= the bundled snapshot)."""
    p = _read_json(_dir() / name)
    if not (isinstance(p, dict) and isinstance(p.get("dir"), str) and VERSION_DIR.fullmatch(p["dir"])):
        return None
    if not (_dir() / "versions" / p["dir"] / "index.json").is_file():
        return None
    return p


# ---------- the library ----------

@dataclass
class Lookup:
    library: dict | None
    local: dict | None


def _key(text: str) -> str:
    return text.casefold()


class _Names:
    """(vendor, product) -> item, matched case-insensitively first, then by slug."""

    def __init__(self, items):
        self.exact: dict = {}
        self.slugged: dict = {}
        self.vendors: dict = {}
        for vendor, product, item in items:
            self.exact.setdefault((_key(vendor), _key(product)), item)
            self.slugged.setdefault((slug(vendor), slug(product)), item)
            self.vendors.setdefault(slug(vendor), []).append((product, item))

    def find(self, vendor: str, product: str):
        hit = self.exact.get((_key(vendor), _key(product)))
        return hit if hit is not None else self.slugged.get((slug(vendor), slug(product)))

    def of_vendor(self, vendor: str) -> list:
        return self.vendors.get(slug(vendor), [])


class Library:
    def __init__(self, root: Path, index: dict, source: str, local: list[dict]):
        self.root = root
        self.index = index
        self.version: int = index["library_version"]
        self.source: str = source
        rows = [r for r in index.get("entries", []) if isinstance(r, dict)
                and isinstance(r.get("vendor"), str) and isinstance(r.get("product"), str)]
        self._rows = _Names((r["vendor"], r["product"], r) for r in rows)
        self._local = _Names((e["vendor"], e["product"], e) for e in local)
        self._local_list = local
        self._cache: dict[str, dict | None] = {}

    @property
    def local_count(self) -> int:
        return len(self._local_list)

    def _entry(self, row: dict) -> dict | None:
        path = row.get("path")
        if not isinstance(path, str):
            return None
        if path not in self._cache:
            e = _read_json(self.root / path) if ROW_PATH.fullmatch(path) else None
            self._cache[path] = e if isinstance(e, dict) else None
        e = self._cache[path]
        return copy.deepcopy(e) if e is not None else None

    def lookup(self, vendor: str, product: str) -> Lookup:
        row = self._rows.find(vendor, product)
        loc = self._local.find(vendor, product)
        return Lookup(self._entry(row) if row is not None else None,
                      copy.deepcopy(loc) if loc is not None else None)

    def vendor_entries(self, vendor: str) -> list[dict]:
        """Every entry of the vendor (matched by slug, so case-insensitive), library and local; a local entry
        replaces the library's entry for the same product."""
        local = [copy.deepcopy(e) for _, e in self._local.of_vendor(vendor)]
        taken = {slug(e["product"]) for e in local}
        out = []
        for product, row in self._rows.of_vendor(vendor):
            if slug(product) not in taken:
                e = self._entry(row)
                if e is not None:
                    out.append(e)
        return out + local


def _load_local() -> list[dict]:
    out = []
    root = _local_dir()
    if not root.is_dir():
        return out
    for p in sorted(root.glob("*/*.json")):
        e = _read_json(p)
        if isinstance(e, dict) and not validate(e, local=True):
            out.append(e)
    return out


_EMPTY_INDEX = {"schema_version": SCHEMA_VERSION, "library_version": 0, "count": 0, "entries": []}


def _bundled() -> tuple[Path, dict]:
    """What ships in the program: an empty index (version 0), so a fresh install has no library until asked."""
    try:
        idx = json.loads((BUNDLED / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idx = None
    if not (isinstance(idx, dict) and isinstance(idx.get("library_version"), int)):
        idx = copy.deepcopy(_EMPTY_INDEX)
    return BUNDLED, idx


def _current() -> tuple[Path, dict, str]:
    p = _pointer("current.json")
    if p is not None:
        root = _dir() / "versions" / p["dir"]
        idx = _read_json(root / "index.json")
        if isinstance(idx, dict) and isinstance(idx.get("library_version"), int):
            return root, idx, "updated"
    root, idx = _bundled()
    # "bundled": only when BUNDLED holds entries, which the shipped package never does (tests use it to exercise
    # the fallback); the shipped fallback is the empty index, "none"
    return root, idx, "bundled" if idx.get("entries") else "none"


def load() -> Library:
    root, idx, source = _current()
    return Library(root, idx, source, _load_local())


# ---------- local additions ----------

def add_local(data: bytes) -> tuple[dict, str]:
    """Validate and store one of the owner's own entries. Returns (entry, line_id); ValueError lists problems."""
    if len(data) > LOCAL_LIMIT:
        raise ValueError(f"entry is larger than {LOCAL_LIMIT // 1024} KiB")
    try:
        entry = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"not a JSON document: {e}") from None
    except RecursionError:
        raise ValueError("not a JSON document: nested too deeply") from None
    if not isinstance(entry, dict):
        raise ValueError("entry is not a JSON object")
    entry.pop("local", None)               # a marker some callers send; not a schema key, never stored
    entry.setdefault("schema_version", SCHEMA_VERSION)
    entry.setdefault("updated", datetime.date.today().isoformat())
    problems = validate(entry, local=True)
    if problems:
        raise ValueError("; ".join(problems))
    entry = canonical(entry)
    path = _local_dir() / rel_path(entry).removeprefix("library/")
    with _locked():
        make_state_dir(path.parent)
        _write_atomic(path, dumps(entry).encode("utf-8"), 0o644, state_owned=True)
    return entry, line_id(entry["vendor"], entry["product"])


# ---------- adopting an older bundled copy ----------

def adopt(src: Path) -> int | None:
    """Install the library found at `src` (a folder with index.json and library/**.json, e.g. the snapshot an older
    program version bundled) as the downloaded copy, when none is installed. Every entry is checked like a
    download. Returns the library version adopted, or None when a copy is already installed or `src` has none.
    Raises LibraryError when `src` is damaged; nothing is installed then."""
    if _pointer("current.json") is not None:
        return None
    raw_idx = _read_json(Path(src) / "index.json")
    if not (isinstance(raw_idx, dict) and (Path(src) / "library").is_dir()):
        return None
    try:
        raw = (Path(src) / "index.json").read_bytes()
        idx, rows = _parse_index(raw, 0)
        if not rows:
            return None
        files = {}
        for r in rows:
            data = (Path(src) / r["path"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != r["sha256"]:
                raise _Abort(f"{r['path']}: sha256 does not match index.json")
            entry = json.loads(data.decode("utf-8"))
            problems = validate(entry)
            if problems or rel_path(entry) != r["path"]:
                raise _Abort(f"{r['path']}: " + ("; ".join(problems) or "not at its own path"))
            files[r["path"]] = data
    except (_Abort, OSError, ValueError) as e:
        raise LibraryError(f"cannot adopt the old library: {e}") from None
    now = time.time()
    with _locked():
        if _pointer("current.json") is not None:
            return None
        make_state_dir(_dir() / "versions")
        name = _new_dir_name(idx["library_version"], now)
        tmp = _dir() / "versions" / (name + ".tmp")
        try:
            make_state_dir(tmp)
            for path, data in files.items():
                dest = tmp / path
                make_state_dir(dest.parent)
                dest.write_bytes(data)
                give_to_state_owner(dest)
            (tmp / "index.json").write_bytes(raw)
            give_to_state_owner(tmp / "index.json")
            os.replace(tmp, _dir() / "versions" / name)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        _write_json(_dir() / "current.json", {"dir": name, "version": idx["library_version"], "at": now})
    return idx["library_version"]


# ---------- update / rollback ----------

@dataclass
class UpdateResult:
    changed: bool
    version: int
    downloaded: int
    error: str | None
    http_status: int | None = None     # set when the error was an HTTP status (401/403/404: maybe private)
    note: str | None = None            # e.g. a custom URL that is not signature-checked


class _Abort(Exception):
    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


def configured_url(cfg: dict | None = None) -> str:
    cfg = config.load() if cfg is None else cfg
    return (cfg.get("library") or {}).get("url") or DEFAULT_LIBRARY_URL


ASSET_API = re.compile(r"/repos/[^/]+/[^/]+/releases/assets/\d+")


def _is_archive(url: str) -> bool:
    """A .tar.gz URL, or a GitHub release-asset API URL (what a private repository's asset needs)."""
    u = urllib.parse.urlsplit(url)
    if u.path.lower().endswith(TAR_SUFFIXES):
        return True
    return (u.hostname or "").lower() == "api.github.com" and ASSET_API.fullmatch(u.path) is not None


RELEASE_ASSET = re.compile(r"/[^/]+/[^/]+/releases/(?:latest/download|download/[^/]+)/[^/]+")


def _release_dir(url: str) -> str | None:
    """The release folder of a GitHub release download URL (https://github.com/<owner>/<repo>/releases/latest/
    download/<file>, or .../releases/download/<tag>/<file>), where that release's SHA256SUMS sits; else None."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (u.hostname or "").lower() != "github.com" or u.port not in (None, 443):
        return None
    if not RELEASE_ASSET.fullmatch(u.path):
        return None
    return url.rsplit("/", 1)[0] + "/"


def _auth_headers(url: str) -> dict:
    """Extra request headers for `url`: the GitHub token (if any) only for the hosts release.py sends it to
    (release.TOKEN_HOSTS over https on port 443: one policy for the updater, get.sh and the library), never for
    any other host; GitHub's asset API also needs Accept: application/octet-stream to return the file itself."""
    u = urllib.parse.urlsplit(url)
    out = {}
    if (u.scheme == "https" and _is_archive(url) and (u.hostname or "").lower() == "api.github.com"
            and u.port in (None, 443)):
        out["Accept"] = "application/octet-stream"
    if not release._host_ok_for_token(url):
        return out
    token = _token()
    if token:
        out["Authorization"] = "Bearer " + token
        out.setdefault("Accept", "application/octet-stream")
    return out


def write_token(token: str) -> Path:
    """Store the GitHub token (root; the setup page's helper), root:filament-kit 640 like the Anthropic key, so the
    library update (the service user) can send it. ValueError for one with spaces or control characters."""
    token = (token or "").strip()
    if not token or not token.isprintable() or " " in token or len(token) > 400:
        raise ValueError("a GitHub token is one word of printable characters")
    dest = config.paths().etc / TOKEN_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        if os.name == "nt":
            tmp.write_bytes((token + "\n").encode())
        else:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
            with os.fdopen(fd, "wb") as fh:
                os.fchmod(fh.fileno(), 0o640)
                fh.write((token + "\n").encode())
                fh.flush()
                os.fsync(fh.fileno())
            if os.geteuid() == 0:
                try:
                    shutil.chown(tmp, user="root", group="filament-kit")
                except (LookupError, OSError):
                    pass
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def remove_token() -> bool:
    try:
        (config.paths().etc / TOKEN_FILE).unlink()
        return True
    except FileNotFoundError:
        return False


def _token() -> str | None:
    """The optional GitHub token (/etc/filament-kit/github_token), only ever sent as a request header."""
    try:
        t = (config.paths().etc / TOKEN_FILE).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    return t if t and t.isprintable() and " " not in t else None


def _check_url(url: str) -> str:
    """The URL of a .tar.gz archive, or a base URL ending in '/'. https only, except a local test server on 127.0.0.1/localhost:<port>."""
    if not isinstance(url, str):
        raise LibraryError("the library url must be a string")
    try:
        u = urllib.parse.urlsplit(url)
        u.port
    except ValueError:
        raise LibraryError("the library url is not a valid URL") from None
    if u.query or u.fragment or u.username or u.password:
        raise LibraryError("the library url must not carry a query string, fragment or credentials")
    if not url.endswith("/") and not _is_archive(url):
        url += "/"
    if u.scheme == "https" and u.hostname:
        return url
    if LOCAL_HOST.fullmatch(url):
        return url
    raise LibraryError("the library url must be https:// (plain http only for 127.0.0.1 or localhost with a port)")


def _redirect_allowed(origin: str, target: str) -> bool:
    """A redirect may go to any https URL, or (for the local test server) to the same http host and port."""
    try:
        o, t = urllib.parse.urlsplit(origin), urllib.parse.urlsplit(target)
        o.port, t.port
    except ValueError:
        return False
    if t.username or t.password:
        return False
    if t.scheme == "https" and t.hostname:
        return True
    return (t.scheme == "http" and o.scheme == "http" and LOCAL_HOST.fullmatch(origin) is not None
            and (t.hostname, t.port) == (o.hostname, o.port))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _redirect_allowed(req.full_url, newurl):
            raise _Abort("the library server redirected to a location that is not https; refused")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")      # a signed asset host must never see the token
        return new


def _safe_opener():
    """http(s) only (no ftp, file or data handlers); redirects checked by `_SafeRedirect`."""
    od = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
              _SafeRedirect(), urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor(),
              urllib.request.UnknownHandler()):   # any other scheme: URLError "unknown url type"
        od.add_handler(h)
    return od.open


class _Fetcher:
    """Downloads for one update, within the time deadline and the total byte cap."""

    def __init__(self, opener, version: int):
        self.opener = opener
        self.version = version
        self.start = _clock()
        self.total = 0
        self.missing_ok: set[str] = set()       # names whose 404 means "not there" (get returns None)

    def remaining(self) -> float:
        left = DEADLINE - (_clock() - self.start)
        if left <= 0:
            raise _Abort(f"the update took longer than {DEADLINE} s; stopped")
        return left

    def get(self, url: str, name: str, limit: int) -> bytes:
        timeout = max(1.0, min(TIMEOUT, self.remaining()))
        budget = TOTAL_LIMIT - self.total
        headers = {"User-Agent": "filament-kit", **_auth_headers(url)}
        req = urllib.request.Request(url, headers=headers)
        try:
            with self.opener(req, timeout=timeout) as r:
                status = getattr(r, "status", 200)
                if status != 200:
                    raise _Abort(f"{name}: HTTP {status}", status)
                data = r.read(min(limit, budget) + 1)
        except urllib.error.HTTPError as e:
            if e.code == 404 and name in self.missing_ok:
                return None
            msg = f"{name}: HTTP {e.code}"
            if e.code in PRIVATE_STATUSES:
                msg += ("; the library repository may be private; using version " + str(self.version)
                        if self.version else "; the library may be private or not published yet")
            raise _Abort(msg, e.code) from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, _Abort):
                raise e.reason from None
            raise _Abort(f"{name}: cannot connect ({e.reason})") from None
        except (OSError, ValueError) as e:
            raise _Abort(f"{name}: download failed ({type(e).__name__})") from None
        self.remaining()
        if len(data) > limit:
            raise _Abort(f"{name}: too large (over {limit // 1024} KiB)")
        if len(data) > budget:
            raise _Abort(f"the update downloaded more than {TOTAL_LIMIT // 2**20} MiB; stopped")
        self.total += len(data)
        return data


def _signed_sums(fetch: _Fetcher, url: str) -> tuple[dict[str, str] | None, str | None]:
    """(the verified SHA256SUMS table, None) for an archive URL, or (None, note) when a custom URL has no SHA256SUMS
    beside it. A GitHub release URL without signed sums, a bad signature or a missing .sig raise _Abort."""
    rel = _release_dir(url)
    folder = rel or url.rsplit("/", 1)[0] + "/"
    if rel is None and (urllib.parse.urlsplit(url).hostname or "").lower() == "api.github.com":
        return None, ("the library archive comes from a GitHub asset API URL and is not signature-checked "
                      "(only the hashes in its index.json are)")
    if rel is None:
        fetch.missing_ok.add(release.SUMS)
    try:
        sums = fetch.get(folder + release.SUMS, release.SUMS, release.LIMIT_SUMS)
    except _Abort as e:
        if rel is not None:
            raise _Abort(f"{e}; the release has no signed {release.SUMS}, so the library is not installed",
                         e.http_status) from None
        raise
    finally:
        fetch.missing_ok.discard(release.SUMS)
    if sums is None:
        return None, (f"{url} has no {release.SUMS} beside it: the archive is not signature-checked (only the "
                      "hashes in its index.json are)")
    sig = fetch.get(folder + release.SIG, release.SIG, release.LIMIT_SIG)
    try:
        return release.verify_sums(sums, sig), None
    except release.ReleaseError as e:
        raise _Abort(f"{e} (library not installed)") from None


def _check_archive(table: dict[str, str], url: str, data: bytes) -> None:
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    want = table.get(name)
    if want is None:
        raise _Abort(f"the signed {release.SUMS} does not list {name}; the library is not installed")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), want):
        raise _Abort(f"{name} does not match its hash in the signed {release.SUMS} (a damaged or changed "
                     "download); the library is not installed")


def _read_archive(raw: bytes, check=lambda: None) -> dict[str, bytes]:
    """The index and entry files of a library tarball, in memory (nothing is extracted to disk). Files may sit
    at the root or under one top directory; links, devices and anything else that is not a plain file are refused."""
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            names: dict = {}
            for i, m in enumerate(tar):
                if i > MAX_ENTRIES + 100:
                    raise _Abort("the library archive has too many files")
                check()
                if m.isdir():
                    continue
                if not m.isreg():
                    raise _Abort(f"the library archive holds {m.name!r}, which is not a plain file; refused")
                name = m.name.removeprefix("./")
                if name in names:
                    raise _Abort(f"the library archive lists {name!r} twice; refused")
                names[name] = m
            prefix = ""
            if "index.json" not in names:
                tops = [n[:-len("index.json")] for n in names
                        if n.endswith("/index.json") and n.count("/") == 1]
                if len(tops) != 1:
                    raise _Abort("the library archive has no index.json")
                prefix = tops[0]
            for name, m in names.items():
                check()
                if not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
                if rel != "index.json" and not ROW_PATH.fullmatch(rel):
                    continue                    # README, schema, anything that is not an index or an entry
                limit = INDEX_LIMIT if rel == "index.json" else ENTRY_LIMIT
                if m.size > limit:
                    raise _Abort(f"{rel}: too large (over {limit // 1024} KiB)")
                total += m.size
                if total > TOTAL_LIMIT:
                    raise _Abort(f"the library archive holds more than {TOTAL_LIMIT // 2**20} MiB; stopped")
                fh = tar.extractfile(m)
                data = fh.read(m.size + 1) if fh is not None else b""
                if len(data) != m.size:
                    raise _Abort(f"{rel}: the archive is damaged")
                files[rel] = data
    except (tarfile.TarError, EOFError, OSError, ValueError) as e:
        raise _Abort(f"the library archive cannot be read ({type(e).__name__})") from None
    if "index.json" not in files:
        raise _Abort("the library archive has no index.json")
    return files


def _parse_index(raw: bytes, current: int) -> tuple[dict, list[dict]]:
    try:
        idx = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _Abort("index.json is not valid JSON") from None
    if not isinstance(idx, dict) or idx.get("schema_version") != SCHEMA_VERSION:
        raise _Abort(f"index.json: schema_version must be {SCHEMA_VERSION}")
    v = idx.get("library_version")
    if not (isinstance(v, int) and not isinstance(v, bool)):
        raise _Abort("index.json: library_version must be an integer")
    if v < current:
        raise _Abort(f"index.json: library_version {v} is older than the current version {current}")
    rows = idx.get("entries")
    if not isinstance(rows, list) or len(rows) > MAX_ENTRIES:
        raise _Abort(f"index.json: entries must be a list of at most {MAX_ENTRIES} rows")
    seen = set()
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or not isinstance(r.get("path"), str) or not ROW_PATH.fullmatch(r["path"]):
            raise _Abort(f"index.json: entry {i} has an invalid path")
        if not isinstance(r.get("sha256"), str) or not SHA256.fullmatch(r["sha256"]):
            raise _Abort(f"index.json: entry {i} ({r['path']}) has an invalid sha256")
        if r["path"] in seen:
            raise _Abort(f"index.json: {r['path']} is listed twice")
        seen.add(r["path"])
    return idx, rows


def _record_check(now: float, error: str | None, skipped: dict | None = None) -> None:
    old = _read_json(_dir() / "last_check.json")
    last_ok = old.get("last_ok_at") if isinstance(old, dict) else None
    _write_json(_dir() / "last_check.json",
                {"at": now, "ok": error is None, "error": error, "last_ok_at": now if error is None else last_ok,
                 "skipped": skipped})


def _new_dir_name(version: int, now: float) -> str:
    base = f"{version}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}"
    versions = _dir() / "versions"
    name, n = base, 0
    while (versions / name).exists() or (versions / (name + ".tmp")).exists():
        n += 1
        name = f"{base}-{n}"
    return name


def _prune(keep: set[str]) -> None:
    versions = _dir() / "versions"
    if not versions.is_dir():
        return
    for d in versions.iterdir():
        if d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


def _file_sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def update(url: str | None = None, *, opener=None, now: float | None = None) -> UpdateResult:
    """Fetch the index at `url` (default: config, else DEFAULT_LIBRARY_URL) and swap to it only if every entry
    downloads, matches its sha256, validates and sits at its own path. Raises LibraryError for an unusable URL;
    every other failure is returned in `error` (and recorded in last_check.json) with the current version kept.
    `opener` (urlopen-like) defaults to one that speaks only http(s) and refuses redirects away from https."""
    base = _check_url(configured_url() if url is None else url)
    now = time.time() if now is None else now
    with _locked():
        cur_root, cur_idx, _ = _current()
        cur_version = cur_idx["library_version"]
        cur_rows = {r.get("path"): r.get("sha256") for r in cur_idx.get("entries", []) if isinstance(r, dict)}
        make_state_dir(_dir() / "versions")
        tmp = None
        downloaded = 0
        fetch = _Fetcher(opener or _safe_opener(), cur_version)
        note = None
        try:
            archive = None
            if _is_archive(base):
                table, note = _signed_sums(fetch, base)
                data = fetch.get(base, "library archive", ARCHIVE_LIMIT)
                if table is not None:
                    _check_archive(table, base, data)
                archive = _read_archive(data, fetch.remaining)
                raw = archive["index.json"]
            else:
                note = (f"{base} is a folder URL: it is not signature-checked (only the hashes in its index.json "
                        "are)")
                raw = fetch.get(base + "index.json", "index.json", INDEX_LIMIT)
            idx, rows = _parse_index(raw, cur_version)
            new_rows = {r["path"]: r["sha256"] for r in rows}
            # what this kit dropped from a signed library is on disk changed: compare with what was published, and this kit
            # (a newer one may read more of it)
            read_before = cur_idx.get("signed_rows") == new_rows and cur_idx.get("read_by") == __version__
            if idx["library_version"] == cur_version and (new_rows == cur_rows or read_before):
                _record_check(now, None, cur_idx.get("skipped"))
                return UpdateResult(False, cur_version, 0, None, note=note)
            signed = archive is not None and table is not None
            kept: list[dict] = []
            dropped: list[str] = []
            fields_gone = 0
            name = _new_dir_name(idx["library_version"], now)
            tmp = _dir() / "versions" / (name + ".tmp")
            make_state_dir(tmp)
            for r in rows:
                fetch.remaining()
                path, sha = r["path"], r["sha256"]
                src = cur_root / path
                if cur_rows.get(path) == sha and _file_sha(src) == sha:
                    data = src.read_bytes()
                elif archive is not None:
                    data = archive.get(path)
                    if data is None:
                        raise _Abort(f"{path}: listed in index.json but missing from the archive")
                    downloaded += 1
                else:
                    data = fetch.get(base + path, path, ENTRY_LIMIT)
                    downloaded += 1
                if hashlib.sha256(data).hexdigest() != sha:
                    raise _Abort(f"{path}: sha256 does not match index.json")
                try:
                    entry = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise _Abort(f"{path}: not valid JSON") from None
                problems = validate(entry)
                if problems and not signed:
                    raise _Abort(f"{path}: " + "; ".join(problems))
                if problems:
                    entry, gone = salvage(entry)
                    if entry is None:
                        log.warning("library: %s: this kit can't read it: %s", path, "; ".join(problems)[:300])
                        dropped.append(path)
                        continue
                    fields_gone += gone
                    log.warning("library: %s: kept without what this kit can't read: %s", path, "; ".join(problems)[:300])
                    data = (json.dumps(entry, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
                    sha = hashlib.sha256(data).hexdigest()
                if rel_path(entry) != path:
                    raise _Abort(f"{path}: the entry belongs at {rel_path(entry)}")
                kept.append({**r, "sha256": sha})
                dest = tmp / path
                make_state_dir(dest.parent)
                dest.write_bytes(data)
                give_to_state_owner(dest)
            if rows and len(dropped) > MAX_DROPPED * len(rows):
                raise _Abort(f"this kit can't read {len(dropped)} of the library's {len(rows)} entries, which looks like a "
                             "broken release rather than newer rules; keeping the current library (a kit update may help)")
            skipped = {"entries": len(dropped), "parts": fields_gone} if dropped or fields_gone else None
            if skipped:
                raw = json.dumps({**idx, "entries": kept, "signed_rows": new_rows, "read_by": __version__,
                                  "skipped": skipped}, indent=2).encode("utf-8")
            (tmp / "index.json").write_bytes(raw)
            give_to_state_owner(tmp / "index.json")
            final = _dir() / "versions" / name
            os.replace(tmp, final)
            tmp = None
            old = _read_json(_dir() / "current.json") if _pointer("current.json") else None
            if old is not None:
                _write_json(_dir() / "previous.json", old)
            else:
                (_dir() / "previous.json").unlink(missing_ok=True)
            _write_json(_dir() / "current.json", {"dir": name, "version": idx["library_version"], "at": now})
            _prune({name} | ({old["dir"]} if old else set()))
            _record_check(now, None, skipped)
            return UpdateResult(True, idx["library_version"], downloaded, None, note=note)
        except Exception as e:  # noqa: BLE001 - every failure must clean up and be recorded, never half-swap
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
            if isinstance(e, _Abort):
                error = str(e)
            elif isinstance(e, OSError):
                error = f"cannot write the library ({type(e).__name__})"
            else:
                error = f"update failed unexpectedly ({type(e).__name__})"
            _record_check(now, error)
            return UpdateResult(False, cur_version, downloaded, error, getattr(e, "http_status", None))


def rollback() -> int:
    """Go back to the version before the last update (none if there was no earlier one); returns it.
    The two are swapped, so a second rollback goes forward again."""
    with _locked():
        cur = _pointer("current.json")
        prev = _pointer("previous.json")
        if cur is None and prev is None:
            raise LibraryError("there is no previous library version to roll back to")
        if prev is not None:
            _write_json(_dir() / "current.json", prev)
        else:
            (_dir() / "current.json").unlink(missing_ok=True)
        if cur is not None:
            _write_json(_dir() / "previous.json", cur)
        else:
            (_dir() / "previous.json").unlink(missing_ok=True)
        return _current()[1]["library_version"]


# ---------- schedule / status ----------

def schedule(cfg: dict) -> str:
    s = (cfg.get("library") or {}).get("schedule", "daily")
    if s not in SCHEDULES:
        raise ValueError(f"library schedule must be one of {', '.join(SCHEDULES)}, not {s!r}")
    return s


def due(cfg: dict, now: float) -> bool:
    """Whether a scheduled update should run: daily after 20 h since the last good check, weekly after 6.5 days,
    off never. A failed check does not reset the clock."""
    gap = SCHEDULES[schedule(cfg)]
    if gap is None:
        return False
    lc = _read_json(_dir() / "last_check.json")
    last_ok = lc.get("last_ok_at") if isinstance(lc, dict) else None
    if not isinstance(last_ok, (int, float)):
        return True
    return now - last_ok >= gap


def last_check() -> dict | None:
    lc = _read_json(_dir() / "last_check.json")
    if not isinstance(lc, dict):
        return None
    return {"at": lc.get("at"), "ok": lc.get("ok") is True, "error": lc.get("error"), "skipped": lc.get("skipped")}


def display_url(url) -> str:
    """Scheme, host, port and path only: never a query string, fragment or credentials."""
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except (TypeError, ValueError, AttributeError):
        return "(invalid url)"
    if not u.scheme or not u.hostname:
        return "(invalid url)"
    return f"{u.scheme}://{u.hostname}{f':{port}' if port else ''}{u.path}"


def status() -> dict:
    lib = load()
    return {"version": lib.version, "source": lib.source, "local": lib.local_count,
            "url": display_url(configured_url()), "last_check": last_check()}
