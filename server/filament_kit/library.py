"""The filament spec library: the bundled snapshot, validated updates with rollback, and local additions.

Layout in the state directory:
  library/current.json            {"dir", "version", "at"}: the version directory in use (absent = bundled)
  library/previous.json           the current.json before the last update (absent = bundled)
  library/last_check.json         {"at", "ok", "error", "last_ok_at"}
  library/versions/<v>-<stamp>/   index.json + library/<vendor>/<product>.json
  library-local/<vslug>/<pslug>.json   the owner's own additions; never touched by `update`

`validate` is a port of filament-library `tools/fl.py` (schema_version 1), so no jsonschema dependency.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import config
from .pairing import _write_atomic, give_to_state_owner, make_state_dir, open_lock

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the service only runs on Linux)
    fcntl = None

DEFAULT_LIBRARY_URL = "https://raw.githubusercontent.com/thompsonfabco/filament-library/main/"
BUNDLED = Path(__file__).parent / "library_data"
SCHEMA_VERSION = 1

INDEX_LIMIT = 8 * 2**20
ENTRY_LIMIT = 256 * 2**10
LOCAL_LIMIT = 256 * 2**10
MAX_ENTRIES = 20_000
TIMEOUT = 30
SCHEDULES = {"daily": 20 * 3600, "weekly": 6.5 * 86400, "off": None}

ROW_PATH = re.compile(r"library/[a-z0-9-]+/[a-z0-9-]+\.json")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION_DIR = re.compile(r"\d+-[0-9A-Za-z-]+")
LOCAL_HOST = re.compile(r"http://(127\.0\.0\.1|localhost):\d{1,5}/.*")

# ---------- fl.py port ----------

TOP_KEYS = ["schema_version", "vendor", "product", "material", "colors", "bambu_parent", "fields",
            "published_ranges", "conflicts", "source_quality", "sources", "updated"]
REQUIRED = [k for k in TOP_KEYS if k != "bambu_parent"]
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
    for k in ("vendor", "product", "material", "bambu_parent"):
        if k in entry and not (isinstance(entry[k], str) and entry[k].strip()):
            errs.append(f"'{k}' must be a non-empty string")
    if isinstance(entry.get("bambu_parent"), str) and "@" in entry["bambu_parent"]:
        errs.append("bambu_parent must not carry an '@<printer>' suffix")
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
        if k == "temperature_vitrification":
            errs.append("fields.temperature_vitrification is not allowed (Bambu's heat-creep threshold, not Tg); "
                        "put Tg/Vicat/HDT in published_ranges._vitrification/_vicat/_hdt_0.45MPa")
            continue
        if k not in FIELD_KEYS:
            errs.append(f"unknown fields key '{k}'")
            continue
        if not (isinstance(v, list) and len(v) == 1 and isinstance(v[0], str) and v[0].strip()):
            errs.append(f"fields.{k} must be a one-element string array, got {v!r}")
            continue
        s = v[0]
        x = _num(s)
        if k.startswith("nozzle_temperature_range"):
            if x is None or not 150 <= x <= 450:
                errs.append(f"fields.{k} {s!r} is outside 150-450 C")
        elif k == "filament_density":
            if x is None or not 0.5 <= x <= 3.0:
                errs.append(f"fields.filament_density {s!r} is outside 0.5-3.0 g/cm3")
        elif k == "filament_diameter":
            if x not in (1.75, 2.85):
                errs.append(f"fields.filament_diameter {s!r} must be 1.75 or 2.85")
        elif k in ("filament_soluble", "filament_is_support"):
            if s not in ("0", "1"):
                errs.append(f"fields.{k} must be \"0\" or \"1\"")
        elif k == "filament_shrink":
            if not re.fullmatch(r"\d+(\.\d+)?%", s) or not 90 <= float(s[:-1]) <= 110:
                errs.append(f"fields.filament_shrink {s!r} must be a percentage like \"99.6%\"")
        elif k == "filament_max_volumetric_speed":
            if x is None or not 0 < x <= 100:
                errs.append(f"fields.filament_max_volumetric_speed {s!r} must be a number in (0, 100] mm3/s")
    lo = _num(_first(f, "nozzle_temperature_range_low"))
    hi = _num(_first(f, "nozzle_temperature_range_high"))
    if lo is not None and hi is not None and lo > hi:
        errs.append(f"nozzle range low {lo:g} is above high {hi:g}")

    pr = entry.get("published_ranges")
    if "published_ranges" in entry and not isinstance(pr, dict):
        errs.append("published_ranges must be an object")
        pr = {}
    for k, v in (pr if isinstance(pr, dict) else {}).items():
        if not (k.startswith("_") or k in RANGE_KEYS):
            errs.append(f"unknown published_ranges key '{k}' (note keys must start with '_')")
        if not (isinstance(v, str) and v.strip()):
            errs.append(f"published_ranges.{k} must be a non-empty string, got {v!r}")
    return errs


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


def _bundled() -> tuple[Path, dict]:
    return BUNDLED, json.loads((BUNDLED / "index.json").read_text(encoding="utf-8"))


def _current() -> tuple[Path, dict, str]:
    p = _pointer("current.json")
    if p is not None:
        root = _dir() / "versions" / p["dir"]
        idx = _read_json(root / "index.json")
        if isinstance(idx, dict) and isinstance(idx.get("library_version"), int):
            return root, idx, "updated"
    root, idx = _bundled()
    return root, idx, "bundled"


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


# ---------- update / rollback ----------

@dataclass
class UpdateResult:
    changed: bool
    version: int
    downloaded: int
    error: str | None


class _Abort(Exception):
    pass


def configured_url(cfg: dict | None = None) -> str:
    cfg = config.load() if cfg is None else cfg
    return (cfg.get("library") or {}).get("url") or DEFAULT_LIBRARY_URL


def _check_url(url: str) -> str:
    """The base URL, ending in '/'. https only, except a local test server on 127.0.0.1/localhost:<port>."""
    if not isinstance(url, str):
        raise LibraryError("the library url must be a string")
    try:
        u = urllib.parse.urlsplit(url)
        u.port
    except ValueError:
        raise LibraryError("the library url is not a valid URL") from None
    if u.query or u.fragment or u.username or u.password:
        raise LibraryError("the library url must not carry a query string, fragment or credentials")
    if not url.endswith("/"):
        url += "/"
    if u.scheme == "https" and u.hostname:
        return url
    if LOCAL_HOST.fullmatch(url):
        return url
    raise LibraryError("the library url must be https:// (plain http only for 127.0.0.1 or localhost with a port)")


def _fetch(opener, url: str, name: str, limit: int, version: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "filament-kit"})
    try:
        with opener(req, timeout=TIMEOUT) as r:
            status = getattr(r, "status", 200)
            if status != 200:
                raise _Abort(f"{name}: HTTP {status}")
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        msg = f"{name}: HTTP {e.code}"
        if e.code in (401, 403, 404):
            msg += f"; the library repository may be private; using version {version}"
        raise _Abort(msg) from None
    except urllib.error.URLError as e:
        raise _Abort(f"{name}: cannot connect ({e.reason})") from None
    except (OSError, ValueError) as e:
        raise _Abort(f"{name}: download failed ({type(e).__name__})") from None
    if len(data) > limit:
        raise _Abort(f"{name}: too large (over {limit // 1024} KiB)")
    return data


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


def _record_check(now: float, error: str | None) -> None:
    old = _read_json(_dir() / "last_check.json")
    last_ok = old.get("last_ok_at") if isinstance(old, dict) else None
    _write_json(_dir() / "last_check.json",
                {"at": now, "ok": error is None, "error": error, "last_ok_at": now if error is None else last_ok})


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


def update(url: str | None = None, *, opener=urllib.request.urlopen, now: float | None = None) -> UpdateResult:
    """Fetch the index at `url` (default: config, else DEFAULT_LIBRARY_URL) and swap to it only if every entry
    downloads, matches its sha256, validates and sits at its own path. Raises LibraryError for an unusable URL;
    every other failure is returned in `error` (and recorded in last_check.json) with the current version kept."""
    base = _check_url(configured_url() if url is None else url)
    now = time.time() if now is None else now
    with _locked():
        cur_root, cur_idx, _ = _current()
        cur_version = cur_idx["library_version"]
        cur_rows = {r.get("path"): r.get("sha256") for r in cur_idx.get("entries", []) if isinstance(r, dict)}
        make_state_dir(_dir() / "versions")
        tmp = None
        downloaded = 0
        try:
            raw = _fetch(opener, base + "index.json", "index.json", INDEX_LIMIT, cur_version)
            idx, rows = _parse_index(raw, cur_version)
            new_rows = {r["path"]: r["sha256"] for r in rows}
            if idx["library_version"] == cur_version and new_rows == cur_rows:
                _record_check(now, None)
                return UpdateResult(False, cur_version, 0, None)
            name = _new_dir_name(idx["library_version"], now)
            tmp = _dir() / "versions" / (name + ".tmp")
            make_state_dir(tmp)
            for r in rows:
                path, sha = r["path"], r["sha256"]
                src = cur_root / path
                if cur_rows.get(path) == sha and _file_sha(src) == sha:
                    data = src.read_bytes()
                else:
                    data = _fetch(opener, base + path, path, ENTRY_LIMIT, cur_version)
                    downloaded += 1
                if hashlib.sha256(data).hexdigest() != sha:
                    raise _Abort(f"{path}: sha256 does not match index.json")
                try:
                    entry = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise _Abort(f"{path}: not valid JSON") from None
                problems = validate(entry)
                if problems:
                    raise _Abort(f"{path}: " + "; ".join(problems))
                if rel_path(entry) != path:
                    raise _Abort(f"{path}: the entry belongs at {rel_path(entry)}")
                dest = tmp / path
                make_state_dir(dest.parent)
                dest.write_bytes(data)
                give_to_state_owner(dest)
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
            _record_check(now, None)
            return UpdateResult(True, idx["library_version"], downloaded, None)
        except (_Abort, OSError) as e:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
            error = str(e) if isinstance(e, _Abort) else f"cannot write the library ({type(e).__name__})"
            _record_check(now, error)
            return UpdateResult(False, cur_version, downloaded, error)


def rollback() -> int:
    """Go back to the version before the last update (the bundled snapshot if there was none); returns it.
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
    return {"at": lc.get("at"), "ok": lc.get("ok") is True, "error": lc.get("error")}


def status() -> dict:
    lib = load()
    return {"version": lib.version, "source": lib.source, "local": lib.local_count, "url": configured_url(),
            "last_check": last_check()}
