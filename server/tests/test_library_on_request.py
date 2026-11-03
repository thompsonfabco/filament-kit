"""The library is downloaded on request: not in the wheel, tarball updates, upgrade safety, profiles without it."""
import hashlib
import importlib.util
import io
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

import pytest

import test_generate as tg
import test_library as tl
from test_library import served  # noqa: F401  (fixture)
from filament_kit import cli, library, modules

ROOT = Path(__file__).resolve().parents[2]
PACKAGED = Path(library.__file__).parent / "library_data"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    (tmp_path / "etc").mkdir()
    return tmp_path


@pytest.fixture
def fresh(monkeypatch, no_library):
    """A fresh install: only what the wheel carries."""
    monkeypatch.setattr(library, "BUNDLED", PACKAGED)


def tar_bytes(files: dict[str, bytes], *, prefix="", extra=()) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in files.items():
            ti = tarfile.TarInfo(prefix + name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        for ti in extra:
            t.addfile(ti)
    return buf.getvalue()


def fixture_files(root: Path = tl.FIXTURE) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.json")}


def put(served, name: str, data: bytes) -> str:
    (served.root / name).write_bytes(data)
    return served.url + name


def load_tool():
    spec = importlib.util.spec_from_file_location("bla", ROOT / "tools" / "build_library_asset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- what the wheel carries ----------

def test_wheel_carries_schema_and_an_empty_index_only():
    idx = json.loads((PACKAGED / "index.json").read_text(encoding="utf-8"))
    assert idx["library_version"] == 0 and idx["entries"] == [] and idx["count"] == 0
    assert (PACKAGED / "schema" / "entry.schema.json").is_file()
    assert not (PACKAGED / "library").exists()
    text = (ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8")
    assert "library_data/library" not in text


def test_fresh_install_has_no_library(fresh):
    lib = library.load()
    assert lib.source == "none" and lib.version == 0
    assert lib.lookup("SUNLU", "PLA+ 2.0").library is None
    assert lib.vendor_entries("SUNLU") == []
    assert library.status()["source"] == "none"


def test_library_module_is_off_for_new_installs():
    assert "library" not in modules.enabled({"modules": {}})
    assert "library" in modules.enabled({})                  # a config from before modules existed keeps it
    assert modules.mode_of(modules.enabled({})) == "server"
    cfg = modules.set_mode({}, "server", say=None)
    assert cfg["modules"]["library"] is True                 # a mode change on such a config keeps it
    assert modules.set_mode({}, "station", say=None)["modules"]["library"] is False
    assert modules.set_mode({"modules": {"server": True}}, "server", say=None)["modules"]["library"] is False
    assert "library" not in modules.MODES["server"]
    assert "library" not in modules.MODES["all-in-one"]
    assert "library" in modules.OPT_IN


def test_cli_status_says_not_downloaded(fresh, capsys):
    assert cli.main(["library", "status"]) == 0
    assert "library not downloaded (run: filament-kit library update)" in capsys.readouterr().out


# ---------- profiles without any library ----------

def test_profiles_build_without_a_library(fresh, tmp_path):
    lib = library.load()
    assert lib.source == "none"
    manifest = tg.build(tmp_path, tg.SUNLU, lib=lib)[0]
    assert tg.names(manifest)                       # presets are still generated (Spoolman values + parents)
    assert manifest["library_version"] == 0


# ---------- tarball update ----------

def test_update_from_tarball_then_load(fresh, served):
    url = put(served, "library.tar.gz", tar_bytes(fixture_files()))
    r = library.update(url)
    assert r.error is None and r.changed
    assert r.downloaded == len(fixture_files()) - 1
    lib = library.load()
    assert lib.source == "updated"
    assert lib.lookup("SUNLU", "PLA+ 2.0").library is not None
    assert served.requests == ["/library.tar.gz"]          # one request, not one per entry


def test_tarball_under_a_top_directory(fresh, served):
    url = put(served, "library.tgz", tar_bytes(fixture_files(), prefix="library-2026-11-02/"))
    assert library.update(url).error is None
    assert library.load().lookup("SUNLU", "PLA+ 2.0").library is not None


def test_tarball_with_a_bad_sha_changes_nothing(fresh, served):
    files = fixture_files()
    path = next(p for p in files if p != "index.json")
    files[path] = files[path] + b" "
    r = library.update(put(served, "library.tar.gz", tar_bytes(files)))
    assert "sha256 does not match" in r.error and not r.changed
    assert library.load().source == "none"
    assert not list(tl.versions_dir().glob("*"))


def test_tarball_missing_an_entry_is_refused(fresh, served):
    files = fixture_files()
    del files[next(p for p in files if p != "index.json")]
    r = library.update(put(served, "library.tar.gz", tar_bytes(files)))
    assert "missing from the archive" in r.error
    assert library.load().source == "none"


def test_tarball_with_a_link_is_refused(fresh, served):
    ti = tarfile.TarInfo("library/evil/x.json")
    ti.type = tarfile.SYMTYPE
    ti.linkname = "/etc/passwd"
    r = library.update(put(served, "library.tar.gz", tar_bytes(fixture_files(), extra=[ti])))
    assert "not a plain file" in r.error
    assert library.load().source == "none"


def test_tarball_traversal_name_is_ignored_and_nothing_escapes(fresh, served, env):
    files = fixture_files()
    files["../../escape.json"] = b"{}"
    files["library/../x.json"] = b"{}"
    r = library.update(put(served, "library.tar.gz", tar_bytes(files)))
    assert r.error is None
    assert not (env / "escape.json").exists() and not (env / "state" / "escape.json").exists()


def test_garbage_archive_is_an_error_not_a_crash(fresh, served):
    r = library.update(put(served, "library.tar.gz", b"this is not a tarball"))
    assert r.error and "cannot be read" in r.error
    assert library.load().source == "none"


def test_oversized_member_refused(fresh, served, monkeypatch):
    monkeypatch.setattr(library, "ENTRY_LIMIT", 10)
    r = library.update(put(served, "library.tar.gz", tar_bytes(fixture_files())))
    assert "too large" in r.error


def test_directory_url_still_works(fresh, served):
    r = library.update(served.url)
    assert r.error is None and library.load().source == "updated"


def test_default_url_is_a_release_asset():
    assert library.DEFAULT_LIBRARY_URL.endswith("/releases/latest/download/library.tar.gz")
    assert library._check_url(library.DEFAULT_LIBRARY_URL) == library.DEFAULT_LIBRARY_URL


# ---------- upgrades ----------

def test_upgrade_keeps_the_last_downloaded_copy(fresh, served):
    assert library.update(put(served, "library.tar.gz", tar_bytes(fixture_files()))).error is None
    version = library.load().version
    # the new program ships the same empty index: the downloaded copy is still the one in use
    assert library.load().source == "updated" and library.load().version == version
    assert library.rollback() == 0                  # nothing earlier: back to none
    assert library.load().source == "none"


def test_unreadable_packaged_index_still_loads(monkeypatch, tmp_path, no_library):
    monkeypatch.setattr(library, "BUNDLED", tmp_path / "nowhere")
    assert library.load().source == "none"


# ---------- token ----------

def test_token_never_echoed(fresh, env):
    (env / "etc" / "github_token").write_text("tok-123\n", encoding="utf-8")
    assert "tok-123" not in json.dumps(library.status())


def test_no_token_file_no_header(fresh):
    assert library._token() is None


def test_token_dropped_on_redirect_to_another_host():
    h = library._SafeRedirect()
    req = urllib.request.Request("https://github.com/x/releases/latest/download/library.tar.gz",
                                 headers={"Authorization": "Bearer tok"})
    same = h.redirect_request(req, None, 302, "Found", {}, "https://github.com/x/other.tar.gz")
    other = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/abc?sig=1")
    assert same.get_header("Authorization") == "Bearer tok"
    assert other.get_header("Authorization") is None


def test_bad_token_file_ignored(env):
    (env / "etc" / "github_token").write_text("two words\n", encoding="utf-8")
    assert library._token() is None


# ---------- release asset tool ----------

def test_build_library_asset_round_trip(tmp_path, fresh, served):
    bla = load_tool()
    src = tmp_path / "src"
    shutil.copytree(tl.FIXTURE, src)
    (src / "schema").mkdir()
    shutil.copy(PACKAGED / "schema" / "entry.schema.json", src / "schema" / "entry.schema.json")
    out = tmp_path / "dist" / "library-2026-11-02.tar.gz"
    n = bla.build(src, out)
    again = tmp_path / "again.tar.gz"
    bla.build(src, again)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == hashlib.sha256(again.read_bytes()).hexdigest()
    (served.root / "library.tar.gz").write_bytes(out.read_bytes())
    r = library.update(served.url + "library.tar.gz")
    assert r.error is None and r.downloaded == n


def test_build_library_asset_refuses_a_bad_checkout(tmp_path):
    bla = load_tool()
    src = tmp_path / "src"
    shutil.copytree(tl.FIXTURE, src)           # no schema/ dir
    with pytest.raises(SystemExit):
        bla.build(src, tmp_path / "o.tar.gz")
    assert not (tmp_path / "o.tar.gz").exists()


# ---------- review round 1 ----------

def test_auth_headers_only_for_github_hosts(env):
    (env / "etc" / "github_token").write_text("tok-123\n", encoding="utf-8")
    gh = library._auth_headers("https://github.com/o/r/releases/latest/download/library.tar.gz")
    assert gh["Authorization"] == "Bearer tok-123"
    assert library._auth_headers("https://objects.githubusercontent.com/x")["Authorization"] == "Bearer tok-123"
    assert library._auth_headers("https://api.github.com/repos/o/r/releases/assets/12")["Accept"] == \
        "application/octet-stream"
    for url in ("https://example.com/library.tar.gz", "https://github.com.evil.example/x.tar.gz",
                "https://evilgithub.com/x", "https://evil.com/github.com/x", "http://github.com/x",
                "http://127.0.0.1:8000/library.tar.gz"):
        assert library._auth_headers(url) == {}, url


def test_no_token_means_no_authorization_but_asset_api_gets_accept(env):
    h = library._auth_headers("https://api.github.com/repos/o/r/releases/assets/12")
    assert "Authorization" not in h and h["Accept"] == "application/octet-stream"
    assert library._auth_headers("https://github.com/o/r/releases/latest/download/library.tar.gz") == {}


def test_token_not_sent_to_a_non_github_server(fresh, served, env):
    (env / "etc" / "github_token").write_text("tok-123\n", encoding="utf-8")
    seen = []
    real = urllib.request.OpenerDirector.open

    def spy(self, req, *a, **k):
        seen.append(dict(req.header_items()))
        return real(self, req, *a, **k)

    urllib.request.OpenerDirector.open = spy
    try:
        r = library.update(put(served, "library.tar.gz", tar_bytes(fixture_files())))
    finally:
        urllib.request.OpenerDirector.open = real
    assert r.error is None
    assert "Authorization" not in seen[0]


def test_github_asset_api_url_is_an_archive():
    url = "https://api.github.com/repos/thompsonfabco/filament-kit/releases/assets/123456"
    assert library._is_archive(url)
    assert library._check_url(url) == url
    assert not library._is_archive("https://api.github.com/repos/o/r/releases/latest")
    assert not library._is_archive("https://example.com/repos/o/r/releases/assets/1")


def test_duplicate_member_names_refused(fresh, served):
    files = fixture_files()
    name = next(p for p in files if p != "index.json")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, d in list(files.items()) + [(name, files[name])]:
            i = tarfile.TarInfo(n)
            i.size = len(d)
            t.addfile(i, io.BytesIO(d))
    r = library.update(put(served, "library.tar.gz", buf.getvalue()))
    assert "twice" in r.error and library.load().source == "none"


def test_archive_read_checks_the_deadline(fresh):
    calls = []

    def check():
        calls.append(1)
        if len(calls) > 3:
            raise library._Abort("the update took too long; stopped")

    with pytest.raises(library._Abort):
        library._read_archive(tar_bytes(fixture_files()), check)


# adopting the library an older program bundled

def legacy_dir(tmp_path) -> Path:
    d = tmp_path / "old_library_data"
    shutil.copytree(tl.FIXTURE, d)
    return d


def test_adopt_keeps_the_old_bundled_library(fresh, tmp_path):
    v = library.adopt(legacy_dir(tmp_path))
    assert v == json.loads((tl.FIXTURE / "index.json").read_text(encoding="utf-8"))["library_version"]
    lib = library.load()
    assert lib.source == "updated" and lib.version == v
    assert lib.lookup("SUNLU", "PLA+ 2.0").library is not None
    assert library.adopt(legacy_dir(tmp_path)) is None          # already installed: left alone


def test_adopt_refuses_a_damaged_copy(fresh, tmp_path):
    d = legacy_dir(tmp_path)
    p = next(d.joinpath("library").rglob("*.json"))
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(library.LibraryError):
        library.adopt(d)
    assert library.load().source == "none"


def test_adopt_with_nothing_there(fresh, tmp_path):
    assert library.adopt(tmp_path / "nope") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "index.json").write_text(json.dumps({"schema_version": 1, "library_version": 0, "count": 0,
                                                  "entries": []}), encoding="utf-8")
    assert library.adopt(empty) is None


def test_cli_library_adopt(fresh, tmp_path, capsys):
    assert cli.main(["library", "adopt", str(legacy_dir(tmp_path))]) == 0
    assert "kept the library" in capsys.readouterr().out
    assert library.load().source == "updated"


def test_install_sh_hands_the_old_library_to_the_new_program():
    text = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    assert text.index("LEGACY_LIB=$(mktemp -d)") < text.index('rm -rf "$VENV"')      # copied before the venv goes
    assert text.index('rm -rf "$VENV"') < text.index('library adopt "$LEGACY_LIB"')
    assert "library on request" in text and "presets, library and backup" not in text


# switching the library on downloads it

def test_plan_downloads_when_library_on_and_missing(fresh):
    from filament_kit import apply
    cfg = modules.set_mode({}, "server", say=None)
    cfg["modules"]["library"] = True
    acts = apply.plan(cfg)
    kinds = [a.kind for a in acts]
    assert kinds.count("library_fetch") == 1
    assert kinds.index("library_fetch") > [a.arg for a in acts].index("filament-kit-library.timer")
    cfg["modules"]["library"] = False
    assert "library_fetch" not in [a.kind for a in apply.plan(cfg)]


def test_plan_does_not_download_when_a_copy_exists():
    from filament_kit import apply
    cfg = modules.set_mode({}, "server", say=None)
    cfg["modules"]["library"] = True
    assert library.load().source == "updated"
    assert "library_fetch" not in [a.kind for a in apply.plan(cfg)]


def test_library_fetch_failure_is_a_warning(capsys):
    import subprocess
    from filament_kit import apply
    ran = []

    def run(cmd):
        ran.append(cmd)
        raise subprocess.CalledProcessError(1, cmd)

    apply.execute([apply.Action("library_fetch", "")], run=run, resources=Path("."))
    out = capsys.readouterr().out
    assert ran[0][1:] == ["library", "update"]
    assert "warning: the library could not be downloaded" in out and "FAIL" not in out
