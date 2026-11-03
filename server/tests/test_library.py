import copy
import functools
import hashlib
import http.server
import io
import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from filament_kit import config, library

FIXTURE = Path(__file__).parent / "data" / "library"
BUNDLED = Path(__file__).parent / "data" / "library_snapshot"   # stands in for a downloaded library (conftest)
PACKAGED = Path(library.__file__).parent / "library_data"


def _bundled_version() -> int:
    return json.loads((BUNDLED / "index.json").read_text(encoding="utf-8"))["library_version"]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path


def dumps(entry: dict) -> str:
    return json.dumps(entry, indent=2, ensure_ascii=False) + "\n"


def reindex(root: Path, version: int) -> None:
    """Rebuild index.json under `root` with the library's build_index rules."""
    rows = []
    for p in sorted((root / "library").rglob("*.json")):
        raw = p.read_bytes()
        e = json.loads(raw)
        rows.append({"vendor": e["vendor"], "product": e["product"], "material": e["material"],
                     "path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(),
                     "updated": e["updated"]})
    rows.sort(key=lambda r: r["path"])
    idx = {"schema_version": 1, "library_version": version, "generated": "2026-11-02", "count": len(rows),
           "entries": rows}
    (root / "index.json").write_text(json.dumps(idx, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                     newline="\n")


def edit(root: Path, rel: str, fn) -> None:
    p = root / rel
    e = json.loads(p.read_text(encoding="utf-8"))
    fn(e)
    p.write_text(dumps(e), encoding="utf-8", newline="\n")


class Served:
    def __init__(self, root: Path, url: str):
        self.root = root
        self.url = url
        self.requests: list[str] = []
        self.redirects: dict[str, str] = {}   # path prefix -> Location prefix


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "served"
    shutil.copytree(FIXTURE, root)
    holder: dict = {}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            holder["s"].requests.append(self.path)
            for prefix, target in holder["s"].redirects.items():
                if self.path.startswith(prefix):
                    self.send_response(302)
                    self.send_header("Location", target + self.path[len(prefix):])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            super().do_GET()

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    s = Served(root, f"http://127.0.0.1:{httpd.server_address[1]}/")
    holder["s"] = s
    yield s
    httpd.shutdown()
    httpd.server_close()


def versions_dir() -> Path:
    return config.paths().state / "library" / "versions"


def entry(**over) -> dict:
    e = {"schema_version": 1, "vendor": "SUNLU", "product": "PLA+ 2.0", "material": "PLA",
         "colors": ["Red"], "bambu_parent": "Bambu PLA Tough+",
         "fields": {"nozzle_temperature_range_low": ["205"], "nozzle_temperature_range_high": ["245"]},
         "published_ranges": {"bed_all_plates": "50-60"}, "conflicts": [], "source_quality": "official_page",
         "sources": ["https://www.sunlu.com/x"], "updated": "2026-11-01"}
    e.update(over)
    return e


# ---------- bundled snapshot ----------

def test_bundled_snapshot_is_valid_and_matches_index():
    idx = json.loads((BUNDLED / "index.json").read_text(encoding="utf-8"))
    assert idx["schema_version"] == 1
    assert (BUNDLED / "schema" / "entry.schema.json").is_file()
    files = {p.relative_to(BUNDLED).as_posix() for p in (BUNDLED / "library").rglob("*.json")}
    assert files == {r["path"] for r in idx["entries"]}
    assert len(files) == idx["count"] > 1000
    for r in idx["entries"]:
        raw = (BUNDLED / r["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == r["sha256"], r["path"]
        e = json.loads(raw)
        assert library.validate(e) == [], r["path"]
        assert library.rel_path(e) == r["path"]


def test_load_without_state_uses_bundled():
    lib = library.load()
    assert lib.source == "bundled"
    assert lib.version == _bundled_version()
    assert lib.local_count == 0


# ---------- validation ----------

def test_validate_port_matches_fl_rules():
    assert library.validate(entry()) == []
    assert any("temperature_vitrification" in p for p in
               library.validate(entry(fields={"temperature_vitrification": ["60"]})))
    assert any("@" in p for p in library.validate(entry(bambu_parent="Bambu PLA Basic @BBL X1C")))
    probs = library.validate(entry(fields={"nozzle_temperature_range_low": ["260"],
                                           "nozzle_temperature_range_high": ["240"]}))
    assert "nozzle range low 260 is above high 240" in probs
    assert "schema_version must be 1" in library.validate(entry(schema_version=2))
    local = entry()
    for k in ("sources", "source_quality", "conflicts", "colors", "updated", "published_ranges"):
        del local[k]
    assert library.validate(local, local=True) == []
    assert "missing required key 'sources'" in library.validate(local)
    # the relaxed rules still check what is there
    assert library.validate(dict(local, sources=["ftp://x"]), local=True) == ["source is not an http(s) URL: 'ftp://x'"]
    # odd shapes give problems, never an exception
    assert library.validate(entry(fields={"nozzle_temperature_range_low": [],
                                          "nozzle_temperature_range_high": 5}))
    assert library.validate(entry(updated="20261101")) == ["updated must be a YYYY-MM-DD date"]
    assert library.validate([]) == ["entry is not a JSON object"]


def test_slug_and_line_id():
    assert library.slug("PLA+ 2.0") == "pla-plus-2-0"
    assert library.slug("Bambu Lab") == "bambu-lab"
    assert library.slug("Black & White") == "black-and-white"
    assert library.line_id("SUNLU", "PLA+ 2.0") == "sunlu--pla-plus-2-0"
    assert library.rel_path(entry()) == "library/sunlu/pla-plus-2-0.json"


# ---------- update ----------

def test_update_to_fixture_copies_matching_files(served):
    r = library.update(served.url)
    assert r.error is None and r.changed is True and r.version == 3
    assert r.downloaded == 0          # all three files match the bundled bytes
    assert served.requests == ["/index.json"]
    lib = library.load()
    assert (lib.source, lib.version) == ("updated", 3)
    assert lib.lookup("SUNLU", "PLA+ 2.0").library["product"] == "PLA+ 2.0"
    assert lib.lookup("3DXTech", "3DXMAX ASA").library is None    # not in the new index
    assert library.status()["last_check"]["ok"] is True


def test_update_downloads_only_changed(served):
    assert library.update(served.url).error is None
    edit(served.root, "library/elegoo/petg-cf.json", lambda e: e["published_ranges"].update({"_test": "v4"}))
    reindex(served.root, 4)
    served.requests.clear()
    r = library.update(served.url)
    assert r.error is None
    assert (r.changed, r.version, r.downloaded) == (True, 4, 1)
    assert served.requests == ["/index.json", "/library/elegoo/petg-cf.json"]
    assert library.load().lookup("Elegoo", "PETG-CF").library["published_ranges"]["_test"] == "v4"


def test_update_unchanged_is_noop(served):
    assert library.update(served.url).changed is True
    before = sorted(p.name for p in versions_dir().iterdir())
    r = library.update(served.url)
    assert (r.changed, r.version, r.downloaded, r.error) == (False, 3, 0, None)
    assert sorted(p.name for p in versions_dir().iterdir()) == before


def _assert_kept(version: int):
    assert library.load().version == version
    assert not [p for p in versions_dir().iterdir() if p.name.endswith(".tmp")]
    st = library.status()
    assert st["version"] == version
    assert st["last_check"]["ok"] is False and st["last_check"]["error"]


def test_update_hash_mismatch_keeps_current(served):
    assert library.update(served.url).error is None
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "a"}))
    reindex(served.root, 4)
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "b"}))
    r = library.update(served.url)
    assert r.changed is False and "sha256" in r.error
    _assert_kept(3)


def test_update_invalid_entry_aborts_everything(served):
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "a"}))
    edit(served.root, "library/elegoo/petg-cf.json",
         lambda e: e["fields"].update({"temperature_vitrification": ["60"]}))
    edit(served.root, "library/bambu-lab/petg-hf.json", lambda e: e["published_ranges"].update({"_t": "c"}))
    reindex(served.root, 3)
    r = library.update(served.url)
    assert r.changed is False and "temperature_vitrification" in r.error
    assert library.load().source == "bundled"
    _assert_kept(_bundled_version())
    assert not (config.paths().state / "library" / "current.json").exists()


def test_update_entry_404_aborts(served):
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "a"}))
    reindex(served.root, 3)
    (served.root / "library/sunlu/pla-plus-2-0.json").unlink()
    r = library.update(served.url)
    assert "404" in r.error
    _assert_kept(_bundled_version())


def test_update_wrong_path_for_entry_aborts(served):
    src = served.root / "library/sunlu/pla-plus-2-0.json"
    src.rename(served.root / "library/sunlu/pla-plus.json")
    reindex(served.root, 3)
    r = library.update(served.url)
    assert r.error and "library/sunlu/pla-plus-2-0.json" in r.error
    _assert_kept(_bundled_version())


@pytest.mark.parametrize("mutate, text", [
    (lambda i: i.update(schema_version=2), "schema_version"),
    (lambda i: i.update(library_version="3"), "library_version"),
    (lambda i: i["entries"][0].update(path="../etc/passwd"), "path"),
    (lambda i: i["entries"][0].update(path="library/a/b.txt"), "path"),
    (lambda i: i["entries"][0].update(sha256="xyz"), "sha256"),
    (lambda i: i.update(entries={}), "entries"),
])
def test_update_bad_index_rejected(served, mutate, text):
    idx = json.loads((served.root / "index.json").read_text(encoding="utf-8"))
    mutate(idx)
    (served.root / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    r = library.update(served.url)
    assert r.changed is False and text in r.error
    _assert_kept(_bundled_version())


def test_update_refuses_older_version(served):
    reindex(served.root, 1)
    r = library.update(served.url)
    assert r.changed is False and "older" in r.error
    _assert_kept(_bundled_version())


def _raising_opener(code):
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "Not Found", {}, io.BytesIO(b""))
    return opener


@pytest.mark.parametrize("code", [401, 403, 404])
def test_update_404_says_private(code):
    r = library.update("https://example.invalid/lib/", opener=_raising_opener(code))
    assert str(code) in r.error
    assert "the library repository may be private; using version " + str(_bundled_version()) in r.error
    assert "example.invalid" not in r.error
    assert library.status()["last_check"]["ok"] is False


def test_update_500_is_not_private():
    r = library.update("https://example.invalid/", opener=_raising_opener(500))
    assert "500" in r.error and "private" not in r.error


@pytest.mark.parametrize("url", ["http://example.com/", "ftp://127.0.0.1/", "http://127.0.0.1/",
                                 "https://example.com/?token=abc", "https://user:pw@example.com/",
                                 "http://127.0.0.1.example.com:80/"])
def test_update_rejects_plain_http_remote(url):
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        raise AssertionError("must not be called")
    with pytest.raises(library.LibraryError) as ei:
        library.update(url, opener=opener)
    assert calls == []
    assert "abc" not in str(ei.value) and "pw" not in str(ei.value)


def test_update_index_too_large():
    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    r = library.update("https://example.invalid/", opener=lambda req, timeout=None: Resp(b" " * (8 * 2**20 + 1)))
    assert "too large" in r.error


def test_rollback_restores_previous(served):
    assert library.update(served.url).version == 3
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "v4"}))
    reindex(served.root, 4)
    assert library.update(served.url).version == 4
    assert library.load().lookup("SUNLU", "PLA+ 2.0").library["published_ranges"]["_t"] == "v4"
    assert library.rollback() == 3
    lib = library.load()
    assert lib.version == 3
    assert "_t" not in lib.lookup("SUNLU", "PLA+ 2.0").library["published_ranges"]
    # only the current and previous version directories are kept
    assert len(list(versions_dir().iterdir())) == 2


def test_rollback_to_bundled_and_nothing_to_roll_back(served):
    with pytest.raises(library.LibraryError):
        library.rollback()
    assert library.update(served.url).version == 3
    assert library.rollback() == _bundled_version()
    assert library.load().source == "bundled"


def test_rollback_after_failed_update_still_works(served):
    assert library.update(served.url).version == 3
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "v4"}))
    reindex(served.root, 4)
    assert library.update(served.url).version == 4
    edit(served.root, "library/elegoo/petg-cf.json", lambda e: e["published_ranges"].update({"_t": "v5"}))
    reindex(served.root, 5)
    (served.root / "library/elegoo/petg-cf.json").unlink()
    assert library.update(served.url).error
    assert library.load().version == 4
    assert library.rollback() == 3


# ---------- lookup / local additions ----------

def test_lookup_case_and_slug():
    lib = library.load()
    hit = lib.lookup("sunlu", "PLA+ 2.0")
    assert hit.library["vendor"] == "SUNLU" and hit.library["product"] == "PLA+ 2.0"
    assert hit.local is None
    assert lib.lookup("Sunlu", "pla-plus-2-0").library["product"] == "PLA+ 2.0"
    assert lib.lookup("SUNLU", "PLA+ 9.9") == library.Lookup(None, None)
    names = [e["product"] for e in lib.vendor_entries("SUNLU")]
    assert "PLA+ 2.0" in names
    assert lib.vendor_entries("sunlu") == lib.vendor_entries("SUNLU")
    assert lib.vendor_entries("No Such Brand") == []


def test_local_overrides_and_survives_update(served):
    local = entry(fields={"nozzle_temperature_range_low": ["210"], "nozzle_temperature_range_high": ["230"]})
    for k in ("sources", "source_quality", "conflicts", "colors", "updated", "published_ranges"):
        del local[k]
    del local["schema_version"]
    saved, line = library.add_local(json.dumps(dict(local, local=True)).encode())
    assert line == "sunlu--pla-plus-2-0"
    assert saved["schema_version"] == 1 and saved["updated"] == time.strftime("%Y-%m-%d")
    assert "local" not in saved
    f = config.paths().state / "library-local" / "sunlu" / "pla-plus-2-0.json"
    stored = json.loads(f.read_text(encoding="utf-8"))
    assert "local" not in stored and stored["fields"]["nozzle_temperature_range_low"] == ["210"]
    lib = library.load()
    assert lib.local_count == 1
    hit = lib.lookup("sunlu", "pla+ 2.0")
    assert hit.local["fields"]["nozzle_temperature_range_low"] == ["210"]
    assert hit.library["fields"]["nozzle_temperature_range_low"] == ["205"]
    sunlu = [e for e in lib.vendor_entries("SUNLU") if e["product"] == "PLA+ 2.0"]
    assert len(sunlu) == 1 and sunlu[0]["fields"]["nozzle_temperature_range_low"] == ["210"]
    before = f.read_bytes()
    assert library.update(served.url).changed is True
    assert f.read_bytes() == before
    assert library.load().lookup("SUNLU", "PLA+ 2.0").local is not None
    assert library.status()["local"] == 1


def test_local_new_vendor_listed():
    library.add_local(json.dumps({"vendor": "Acme Plastics", "product": "PLA Max", "material": "PLA",
                                  "fields": {}}).encode())
    lib = library.load()
    assert [e["product"] for e in lib.vendor_entries("acme plastics")] == ["PLA Max"]
    assert lib.lookup("Acme Plastics", "PLA Max").library is None


def test_add_local_invalid_lists_problems():
    bad = {"vendor": "SUNLU", "product": "PLA", "material": "",
           "fields": {"temperature_vitrification": ["60"], "filament_density": ["9"]}}
    with pytest.raises(ValueError) as ei:
        library.add_local(json.dumps(bad).encode())
    msg = str(ei.value)
    assert "'material' must be a non-empty string" in msg
    assert "temperature_vitrification" in msg
    assert "filament_density" in msg
    assert not (config.paths().state / "library-local").exists() or \
        not list((config.paths().state / "library-local").rglob("*.json"))
    for raw in (b"not json", b"[1]", b"\xff"):
        with pytest.raises(ValueError):
            library.add_local(raw)


# ---------- schedule / status ----------

def _ok_check_at(t: float):
    """Record a successful check at `t` (an unchanged update against the bundled index)."""
    raw = (BUNDLED / "index.json").read_bytes()

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
    r = library.update("https://example.invalid/", opener=lambda req, timeout=None: Resp(raw), now=t)
    assert (r.changed, r.error) == (False, None)


def test_due_schedule():
    t = 1_800_000_000.0
    daily = {"library": {"url": None, "schedule": "daily"}}
    weekly = {"library": {"url": None, "schedule": "weekly"}}
    off = {"library": {"url": None, "schedule": "off"}}
    assert library.due(daily, t) and library.due(weekly, t) and not library.due(off, t)
    _ok_check_at(t)
    assert not library.due(daily, t + 19 * 3600)
    assert library.due(daily, t + 20 * 3600 + 1)
    assert not library.due(weekly, t + 6 * 86400)
    assert library.due(weekly, t + 6.5 * 86400 + 1)
    assert not library.due(off, t + 100 * 86400)
    # a failed check does not reset the clock
    library.update("https://example.invalid/", opener=_raising_opener(404), now=t + 21 * 3600)
    assert library.due(daily, t + 21 * 3600 + 60)
    with pytest.raises(ValueError):
        library.due({"library": {"schedule": "hourly"}}, t)


def test_status_shape():
    st = library.status()
    assert st == {"version": _bundled_version(), "source": "bundled", "local": 0,
                  "url": library.DEFAULT_LIBRARY_URL, "last_check": None}
    library.update("https://example.invalid/", opener=_raising_opener(404), now=123.0)
    lc = library.status()["last_check"]
    assert set(lc) == {"at", "ok", "error"} and lc["at"] == 123.0 and lc["ok"] is False


def test_status_url_from_config():
    cfg = config.load()
    cfg["library"]["url"] = "https://mirror.example/lib/"
    config.save(cfg)
    assert library.status()["url"] == "https://mirror.example/lib/"


def test_corrupt_current_falls_back_to_bundled():
    d = config.paths().state / "library"
    d.mkdir(parents=True)
    (d / "current.json").write_text('{"dir": "../../etc"}', encoding="utf-8")
    assert library.load().source == "bundled"


# ---------- fix round 1 ----------

def _assert_no_tmp():
    vd = versions_dir()
    assert not vd.exists() or not [p for p in vd.iterdir() if p.name.endswith(".tmp")]


def test_redirect_to_other_http_host_refused(served):
    other = served.url.replace("127.0.0.1", "localhost")          # a different host, plain http
    served.redirects["/away/"] = other
    r = library.update(served.url + "away/")
    assert r.changed is False and "redirected" in r.error
    assert served.requests == ["/away/index.json"]                   # the redirect was never followed
    lc = library.status()["last_check"]
    assert lc["ok"] is False and "redirected" in lc["error"]
    _assert_no_tmp()


def test_redirect_same_local_host_followed(served):
    served.redirects["/old/"] = served.url
    r = library.update(served.url + "old/")
    assert r.error is None and r.version == 3


def test_redirect_rules():
    ok = library._redirect_allowed
    assert ok("https://a.example/", "https://b.example/x")
    assert not ok("https://a.example/", "http://a.example/x")
    assert not ok("https://a.example/", "ftp://a.example/x")
    assert not ok("https://a.example/", "https://u:p@a.example/x")
    assert ok("http://127.0.0.1:8000/", "http://127.0.0.1:8000/y")
    assert not ok("http://127.0.0.1:8000/", "http://127.0.0.1:8001/y")
    assert not ok("http://127.0.0.1:8000/", "http://localhost:8000/y")


def test_safe_opener_has_no_ftp_or_file():
    op = library._safe_opener()
    for url in ("ftp://127.0.0.1/x", "file:///etc/passwd", "data:text/plain,hi"):
        with pytest.raises(urllib.error.URLError) as ei:
            op(urllib.request.Request(url), timeout=1)
        assert "unknown url type" in str(ei.value)


def _set_row(root: Path, rel: str, raw: bytes) -> None:
    (root / rel).write_bytes(raw)
    idx = json.loads((root / "index.json").read_text(encoding="utf-8"))
    for row in idx["entries"]:
        if row["path"] == rel:
            row["sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "index.json").write_text(json.dumps(idx), encoding="utf-8")


def test_deeply_nested_entry_fails_cleanly(served):
    _set_row(served.root, "library/sunlu/pla-plus-2-0.json", b"[" * (256 * 1024))
    r = library.update(served.url)
    assert r.changed is False and r.error
    _assert_kept(_bundled_version())


def test_deeply_nested_index_fails_cleanly(served):
    (served.root / "index.json").write_bytes(b"[" * 200_000)
    r = library.update(served.url)
    assert r.changed is False and r.error
    _assert_kept(_bundled_version())


def test_unexpected_error_still_cleans_up(served, monkeypatch):
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "a"}))
    reindex(served.root, 3)

    def boom(entry, **k):
        raise KeyError("surprise")
    monkeypatch.setattr(library, "validate", boom)
    r = library.update(served.url)
    assert r.error == "update failed unexpectedly (KeyError)"
    _assert_kept(_bundled_version())


def test_update_deadline(served, monkeypatch):
    edit(served.root, "library/sunlu/pla-plus-2-0.json", lambda e: e["published_ranges"].update({"_t": "a"}))
    reindex(served.root, 3)
    ticks = iter(range(0, 100_000, 250))
    monkeypatch.setattr(library, "_clock", lambda: next(ticks))
    r = library.update(served.url)
    assert r.changed is False and "longer than" in r.error
    _assert_kept(_bundled_version())


def test_update_total_bytes_cap(served, monkeypatch):
    for rel in ("library/sunlu/pla-plus-2-0.json", "library/elegoo/petg-cf.json"):
        edit(served.root, rel, lambda e: e["published_ranges"].update({"_t": "a"}))
    reindex(served.root, 3)
    index_size = (served.root / "index.json").stat().st_size
    one = (served.root / "library/elegoo/petg-cf.json").stat().st_size
    monkeypatch.setattr(library, "TOTAL_LIMIT", index_size + one + 10)   # room for the index and one entry
    r = library.update(served.url)
    assert r.changed is False and "downloaded more than" in r.error
    _assert_kept(_bundled_version())


def test_http_status_field(served):
    assert library.update("https://example.invalid/", opener=_raising_opener(404)).http_status == 404
    assert library.update("https://example.invalid/", opener=_raising_opener(500)).http_status == 500
    edit(served.root, "library/elegoo/petg-cf.json", lambda e: e["published_ranges"].update({"_t": "a"}))
    assert library.update(served.url).http_status is None           # an index sha mismatch is not HTTP


def test_add_local_deeply_nested():
    with pytest.raises(ValueError):
        library.add_local(b"[" * 200_000)


def test_status_url_is_sanitized():
    cfg = config.load()
    cfg["library"]["url"] = "https://user:pw@mirror.example:8443/lib/?token=s3cret#frag"
    config.save(cfg)
    assert library.status()["url"] == "https://mirror.example:8443/lib/"
    assert library.display_url("not a url") == "(invalid url)"


# ---------- Task 3: optional orca_parent ----------

def test_orca_parent_is_optional_and_checked():
    assert library.validate(entry(orca_parent="SUNLU PLA+ 2.0")) == []
    assert library.validate(entry(orca_parent="SUNLU PLA+ 2.0"), local=True) == []
    assert library.validate(entry(orca_parent="")) == ["'orca_parent' must be a non-empty string"]
    assert library.validate(entry(orca_parent=5)) == ["'orca_parent' must be a non-empty string"]
    assert library.validate(entry(orca_parent="Generic PLA @System")) == \
        ["orca_parent must not carry an '@' suffix (give the base name, without ' @System')"]
    assert list(library.canonical(entry(orca_parent="X")))[5:7] == ["bambu_parent", "orca_parent"]


def test_schema_file_lists_orca_parent():
    schema = json.loads((BUNDLED / "schema" / "entry.schema.json").read_text(encoding="utf-8"))
    op = schema["properties"]["orca_parent"]
    assert op["type"] == "string" and op["pattern"] == "^[^@]+$"
    assert "orca_parent" not in schema["required"]


def test_local_entry_with_orca_parent_is_added():
    e, lid = library.add_local(json.dumps({"vendor": "Acme", "product": "PLA X", "material": "PLA",
                                           "fields": {}, "orca_parent": "Generic PLA"}).encode())
    assert e["orca_parent"] == "Generic PLA"
    assert library.load().lookup("Acme", "PLA X").local["orca_parent"] == "Generic PLA"
