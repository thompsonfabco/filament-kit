"""Builds with last-good fallback, sync storage (uploads, owner), retention, tree hash parity."""
import hashlib
import importlib.util
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from filament_kit import config, library, pairing, profiles
from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer
from filament_kit.profiles import builds, errors, generate as G

import test_generate as TG

REPO = Path(__file__).resolve().parents[2]


# ---------- helpers ----------

class FakeSm:
    def __init__(self, filaments):
        self.filaments = filaments

    def get(self, path):
        assert path == "filament"
        return [dict(f) for f in self.filaments]


def zip_of(files: dict) -> bytes:
    """A zip with exactly these entry names (a backslash is stored as is, which zipfile itself would not do on
    Windows: such names are written with "|" and patched in the bytes)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name.replace("\\", "|"), data if isinstance(data, bytes) else data.encode("utf-8"))
    out = buf.getvalue()
    for name in files:
        if "\\" in name:
            out = out.replace(name.replace("\\", "|").encode(), name.encode())
    return out


def system_zip(presets=None) -> bytes:
    return zip_of({f"{n}.json": json.dumps(cfg) for n, cfg in (presets or TG.presets()).items()})


def pair(*ids):
    devs = [{"id": i, "name": "pc", "hash": hashlib.sha256(i.encode()).hexdigest(), "paired": 1.0,
             "last_seen": 1.0, "expires": 0, "claimed": 1.0} for i in ids]
    pairing._write("devices.json", devs)


def profiles_dir() -> Path:
    return config.paths().state / "profiles"


def tree_files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


SUNLU = [TG.fil(17, "PLA+ 2.0 Grey", extra={"line": json.dumps("PLA+ 2.0"), "nozzle_range": json.dumps("190-230")}),
         TG.fil(3, "PLA+ 2.0 Red", extra={"line": json.dumps("PLA+ 2.0"), "nozzle_range": json.dumps("190-230")})]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(library, "load", lambda: TG.make_lib())
    registry.upsert(Printer("S1", "H2D", "O1D", "10.0.0.5", "", True))
    pair("a")
    return FakeSm(SUNLU)


def synced(sm_env, presets=None):
    builds.store_upload("system", io.BytesIO(system_zip(presets)), device_id="a")


# ---------- tree hash ----------

def formula(root: Path, rels) -> str:
    h = hashlib.sha256()
    for rel in sorted(rels):
        h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256((root / rel).read_bytes()).digest())
    return h.hexdigest()


def test_tree_hash_contract(tmp_path):
    root = tmp_path / "t"
    files = {"a.json": b"{}", "base/b.info": b"x", "c.txt": b"y"}
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    assert builds.tree_hash(root) == formula(root, ["a.json", "base/b.info"])
    assert builds.tree_hash(tmp_path / "missing") == hashlib.sha256(b"").hexdigest()


def test_tree_hash_matches_pc_sync(tmp_path):
    spec = importlib.util.spec_from_file_location("fksync_treehash", REPO / "pc-sync" / "fksync" / "treehash.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = tmp_path / "t"
    for rel, data in {"Z.JSON": b"{\"a\": 1}", "base/b.info": b"setting_id = X\n", "base/a b.json": b"[]",
                      "x/y/ü.json": "{}".encode(), "skip.txt": b"no", "base/c.Info": b"q"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    assert builds.tree_hash(root) == mod.tree_hash(root)
    assert builds.tree_hash(tmp_path / "nope") == mod.tree_hash(tmp_path / "nope")


# ---------- uploads ----------

def test_upload_live_stores_and_hashes(env):
    data = zip_of({"base/x.json": "{}", "base/x.info": "setting_id = PFUS1\n"})
    h = builds.store_upload("live", io.BytesIO(data), device_id="a", user_id="123")
    live = profiles_dir() / "live" / "user"
    assert h == builds.tree_hash(live) and (live / "base" / "x.info").is_file()
    meta = json.loads((profiles_dir() / "live" / "meta.json").read_text(encoding="utf-8"))
    assert meta["live_hash"] == h and meta["user_id"] == "123" and meta["owner"] == "a"
    assert builds.owner() == "a"


@pytest.mark.parametrize("bad", ["../x.json", "/abs.json", "C:/x.json", "a\\b.json", "base/../../x.json",
                                 "notes.txt", "base/x.exe"])
def test_upload_rejects_zip_slip_and_keeps_previous(env, bad):
    builds.store_upload("live", io.BytesIO(zip_of({"base/ok.json": "{}"})), device_id="a", user_id="1")
    live = profiles_dir() / "live" / "user"
    before = tree_files(live)
    with pytest.raises(builds.BadZip) as e:
        builds.store_upload("live", io.BytesIO(zip_of({"base/new.json": "{}", bad: "{}"})), device_id="a",
                            user_id="1")
    assert e.value.status == 400 and e.value.code == "bad_zip"
    assert tree_files(live) == before
    assert not (profiles_dir().parent / "x.json").exists() and not (profiles_dir() / "x.json").exists()
    assert not [p for p in profiles_dir().iterdir() if p.name.endswith(".tmp")]


def test_upload_rejects_symlink_bad_json_and_non_zip(env):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("base/link.json")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "/etc/passwd")
    for data in (buf.getvalue(), zip_of({"base/x.json": "{not json"}), b"not a zip at all",
                 zip_of({"base/x.json": "{}", "BASE/X.json": "{}"})):
        with pytest.raises(builds.BadZip):
            builds.store_upload("live", io.BytesIO(data), device_id="a", user_id="1")
    assert not (profiles_dir() / "live" / "user").exists()


def test_upload_rejects_bomb_and_count(env):
    many = zip_of({f"base/{i}.json": "{}" for i in range(30_000)})
    with pytest.raises(builds.BadZip):
        builds.store_upload("system", io.BytesIO(many), device_id="a")
    zero = b"\0" * (4 << 20)
    bomb = zip_of({f"f{i}.info": zero for i in range(150)})      # 600 MiB uncompressed
    assert len(bomb) < builds.MAX_LIVE
    with pytest.raises(builds.BadZip):
        builds.store_upload("live", io.BytesIO(bomb), device_id="a", user_id="1")
    big_one = zip_of({"base/big.info": b"\0" * ((4 << 20) + 1)})
    with pytest.raises(builds.BadZip):
        builds.store_upload("live", io.BytesIO(big_one), device_id="a", user_id="1")
    live = profiles_dir() / "live"
    assert not (live / "user").exists() and not (live / "system").exists()
    leftovers = [p for p in profiles_dir().rglob("*") if p.is_file() and p.name not in ("meta.json",)
                 and not p.name.endswith(".lock")]
    assert leftovers == []


class CountingStream(io.RawIOBase):
    def __init__(self, size):
        self.size, self.read_total = size, 0

    def readable(self):
        return True

    def read(self, n=-1):
        n = self.size - self.read_total if n is None or n < 0 else min(n, self.size - self.read_total)
        self.read_total += n
        return b"\0" * n


def test_upload_too_large_stops_early(env):
    src = CountingStream(33 << 20)
    with pytest.raises(builds.TooLarge) as e:
        builds.store_upload("live", src, device_id="a", user_id="1")
    assert e.value.status == 413 and e.value.code == "too_large"
    assert src.read_total <= builds.MAX_LIVE + 1
    assert builds.MAX_SYSTEM == 64 << 20


def test_second_pc_refused(env):
    pair("a", "b")
    builds.store_upload("live", io.BytesIO(zip_of({"base/x.json": "{}"})), device_id="a", user_id="1")
    with pytest.raises(builds.OtherPc) as e:
        builds.store_upload("live", io.BytesIO(zip_of({"base/y.json": "{}"})), device_id="b", user_id="1")
    assert e.value.status == 409 and e.value.code == "other_pc"
    assert builds.state_view("b")["owner"] == "a" and builds.state_view("b")["you"] == "b"
    assert pairing.revoke("a")
    builds.store_upload("live", io.BytesIO(zip_of({"base/y.json": "{}"})), device_id="b", user_id="1")
    assert builds.owner() == "b"


# ---------- builds ----------

def test_no_system_presets_fails_cleanly(env):
    r = builds.run_build(env, now=TG.NOW)
    assert r["ok"] is False and r["stamp"] is None and r.get("waiting") is True
    assert "install and pair the PC sync" in r["error"]
    assert builds.current() is None
    st = builds.status()
    assert st["last_attempt"]["ok"] is False and "install and pair the PC sync" in st["last_attempt"]["error"]


def test_good_build(env):
    synced(env)
    r = builds.run_build(env, now=TG.NOW)
    assert r["ok"] is True and r["error"] is None and isinstance(r["problems"], list)
    cur = builds.current()
    assert cur["stamp"] == r["stamp"] == "20270115-080000"
    manifest = json.loads((profiles_dir() / "builds" / r["stamp"] / "BUILD.json").read_text(encoding="utf-8"))
    assert TG.sunlu(TG.H2D, "0.4") in {p["name"] for p in manifest["presets"]}
    assert manifest["filaments"] == {"3": "sunlu--pla-plus-2-0", "17": "sunlu--pla-plus-2-0"}
    view = builds.state_view("a")
    assert view["build"]["stamp"] == r["stamp"] and view["build"]["presets"] == len(manifest["presets"])
    assert view["last_attempt"]["ok"] is True
    st = builds.status()
    assert st["lines"] == 1 and st["presets"] == len(manifest["presets"])
    # the saved lines carry the build's filament_id
    lid = json.loads((profiles_dir() / "lines.json").read_text(encoding="utf-8"))["lines"][0]["filament_id"]
    assert manifest["lines"]["sunlu--pla-plus-2-0"]["filament_id"] == lid


def test_build_problems_include_store_problems(env):
    p = TG.presets()
    p["broken"] = {"inherits": "nowhere", "instantiation": "true", "filament_type": ["PLA"]}
    synced(env, p)
    r = builds.run_build(env, now=TG.NOW)
    assert r["ok"] is True
    assert any(x.startswith("broken: cannot resolve") for x in r["problems"])


def test_failed_build_keeps_last_good(env, monkeypatch):
    synced(env)
    good = builds.run_build(env, now=TG.NOW)

    def boom(**kw):
        raise RuntimeError("generator broke")
    monkeypatch.setattr(G, "build_all", boom)
    r = builds.run_build(env, now=TG.NOW + 60)
    assert r["ok"] is False and r["error"] == "RuntimeError: generator broke"
    assert builds.current()["stamp"] == good["stamp"]
    la = builds.state_view("a")["last_attempt"]
    assert la["ok"] is False and la["error"] == "RuntimeError: generator broke"
    assert not [p for p in (profiles_dir() / "builds").iterdir() if p.name.endswith(".tmp")]


def test_leftover_tmp_removed_on_next_run(env):
    synced(env)
    tmp = profiles_dir() / "builds" / "x.tmp"
    (tmp / "base").mkdir(parents=True)
    (tmp / "base" / "junk.json").write_text("{}")
    builds.run_build(env, now=TG.NOW)
    assert not tmp.exists()


def test_rerun_when_requested_during_build(env, monkeypatch):
    synced(env)
    real = G.build_all
    calls = []

    def patched(**kw):
        calls.append(1)
        if len(calls) == 1:
            time.sleep(0.02)
            builds.request_rebuild("test")
        return real(**kw)
    monkeypatch.setattr(G, "build_all", patched)
    r = builds.run_build(env, now=TG.NOW)
    assert len(calls) == 2 and r["ok"] is True
    assert builds.state_view("a")["rebuild_requested"] is None


def test_rerun_capped_at_three(env, monkeypatch):
    synced(env)
    real = G.build_all
    calls = []

    def patched(**kw):
        calls.append(1)
        time.sleep(0.02)
        builds.request_rebuild("again")
        return real(**kw)
    monkeypatch.setattr(G, "build_all", patched)
    builds.run_build(env, now=TG.NOW)
    assert len(calls) == 3
    assert builds.state_view("a")["rebuild_requested"] is not None   # still pending for the next run


def test_builder_never_writes_the_request_file(env):
    synced(env)
    builds.request_rebuild("x", live_hash="abc")
    req = profiles_dir() / "rebuild-request"
    before = (req.read_bytes(), req.stat().st_mtime_ns)
    view = builds.state_view("a")["rebuild_requested"]
    assert view["live_hash"] == "abc"
    builds.run_build(env, now=TG.NOW)
    assert (req.read_bytes(), req.stat().st_mtime_ns) == before
    assert builds.state_view("a")["rebuild_requested"] is None


def test_retention_keeps_5_and_installed(env):
    synced(env)
    stamps = [builds.run_build(env, now=TG.NOW + i)["stamp"] for i in range(2)]
    builds.record_installed(stamps[0], "a")
    stamps += [builds.run_build(env, now=TG.NOW + i)["stamp"] for i in range(2, 8)]
    left = sorted(p.name for p in (profiles_dir() / "builds").iterdir())
    assert len(left) == 6 and stamps[0] in left and stamps[1] not in left
    assert set(stamps[-5:]) <= set(left)
    # the installed build is the snapshot of the next build
    assert builds.state_view("a")["installed"]["stamp"] == stamps[0]


def test_stamp_suffix_when_taken(env):
    synced(env)
    a = builds.run_build(env, now=TG.NOW)["stamp"]
    b = builds.run_build(env, now=TG.NOW)["stamp"]
    c = builds.run_build(env, now=TG.NOW)["stamp"]
    assert (a, b, c) == ("20270115-080000", "20270115-080000-2", "20270115-080000-3")


def test_build_zip_and_installed(env):
    synced(env)
    stamp = builds.run_build(env, now=TG.NOW)["stamp"]
    with zipfile.ZipFile(io.BytesIO(builds.build_zip(stamp))) as zf:
        names = zf.namelist()
    assert "BUILD.json" in names
    assert all(n == "BUILD.json" or (n.startswith("base/") and n.endswith((".json", ".info"))) for n in names)
    assert f"base/{TG.sunlu(TG.H2D, '0.4')}.json" in names and f"base/{TG.sunlu(TG.H2D, '0.4')}.info" in names
    with pytest.raises(errors.ProfileError) as e:
        builds.record_installed("20990101-000000", "a")
    assert e.value.status == 404 and e.value.code == "not_found"
    with pytest.raises(errors.ProfileError) as e:
        builds.build_zip("../etc")
    assert e.value.status == 404
    got = builds.record_installed(stamp, "a")
    assert got["stamp"] == stamp and isinstance(got["at"], (int, float))
    pair("a", "b")
    with pytest.raises(builds.OtherPc):
        builds.record_installed(stamp, "b")


def test_restore_deleted_flag_consumed(env):
    synced(env)
    builds.restore_deleted_next()
    flag = profiles_dir() / "restore-deleted"
    assert flag.exists()
    builds.run_build(env, now=TG.NOW)
    assert not flag.exists()


def test_profiles_package_exports():
    assert profiles.errors is errors
    assert profiles.preset_for is profiles.index.preset_for


# ---------- fix round 1 (ruling S24) ----------

@pytest.mark.parametrize("files", [
    {"base/" + "a" * 300 + ".json": "{}"},                       # a part over 255 bytes
    {"base/x.json/y.json": "{}", "base/x.json": "{}"},           # a file where a directory was made
    {"base/x.json": "{}", "base/x.json/y.json": "{}"},           # a directory where a file was made
    {"base /x.json": "{}"}, {"base./x.json": "{}"},              # trailing space / dot in a part
    {"base/x.json ": "{}"}, {"base/x.json.": "{}"},
])
def test_upload_odd_names_are_bad_zip_not_500(env, files):
    builds.store_upload("live", io.BytesIO(zip_of({"base/ok.json": "{}"})), device_id="a", user_id="1")
    live = profiles_dir() / "live" / "user"
    before = tree_files(live)
    with pytest.raises(builds.BadZip):
        builds.store_upload("live", io.BytesIO(zip_of(files)), device_id="a", user_id="1")
    assert tree_files(live) == before
    assert not [p for p in profiles_dir().iterdir() if p.name.endswith(".tmp")]


def test_upload_dir_entry_with_trailing_space_refused(env):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("base /"), "")
        zf.writestr("base/x.json", "{}")
    with pytest.raises(builds.BadZip):
        builds.store_upload("live", io.BytesIO(buf.getvalue()), device_id="a", user_id="1")


def test_extract_os_errors_map_to_bad_zip_but_enospc_stays(env, monkeypatch, tmp_path):
    import errno
    zpath = tmp_path / "u.zip"
    zpath.write_bytes(zip_of({"base/x.json": "{}"}))
    real_open = open

    def failing(exc):
        def fake_open(path, mode="r", *a, **kw):
            if str(path).endswith("x.json") and "x" in mode:
                raise exc
            return real_open(path, mode, *a, **kw)
        return fake_open
    for exc in (IsADirectoryError(), PermissionError(), NotADirectoryError(), FileNotFoundError()):
        monkeypatch.setattr("builtins.open", failing(exc))
        with pytest.raises(builds.BadZip):
            builds._extract(zpath, tmp_path / f"t-{exc.__class__.__name__}")
    monkeypatch.setattr("builtins.open", failing(OSError(errno.ENOSPC, "No space left on device")))
    with pytest.raises(OSError) as e:
        builds._extract(zpath, tmp_path / "t-nospc")
    assert not isinstance(e.value, builds.BadZip) and e.value.errno == errno.ENOSPC


def test_old_upload_tmp_swept(env):
    root = profiles_dir()
    root.mkdir(parents=True, exist_ok=True)
    old, fresh = root / "upload-live-old.tmp", root / "upload-live-new.tmp"
    for d in (old, fresh):
        d.mkdir()
        (d / "upload.zip").write_bytes(b"x")
    past = time.time() - 2 * 3600
    os.utime(old, (past, past))
    builds.store_upload("live", io.BytesIO(zip_of({"base/x.json": "{}"})), device_id="a", user_id="1")
    assert not old.exists() and fresh.exists()
    os.utime(fresh, (past, past))
    builds.run_build(env, now=TG.NOW)
    assert not fresh.exists()


# ---------- Task 7c: one system store loader ----------

def test_system_store_none_before_an_upload():
    assert builds.system_store() is None


def test_system_store_is_hash_gated_not_folder_gated():
    """A system folder without a system_hash in meta.json is not an uploaded store (one definition everywhere)."""
    folder = profiles_dir() / "live" / "system"
    folder.mkdir(parents=True)
    for n, cfg in TG.presets().items():
        (folder / f"{n}.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert builds.system_store() is None


def test_system_store_cached_by_hash_and_reloaded_on_a_new_upload():
    pair("a")
    builds.store_upload("system", io.BytesIO(system_zip()), device_id="a")
    s1 = builds.system_store()
    assert s1 is not None and s1.names() == set(TG.presets())
    assert builds.system_store() is s1                      # same hash: the cached store
    fewer = dict(list(TG.presets().items())[:2])
    builds.store_upload("system", io.BytesIO(system_zip(fewer)), device_id="a")
    s2 = builds.system_store()
    assert s2 is not s1 and s2.names() == set(fewer)


def test_system_store_parses_outside_the_live_lock(monkeypatch):
    pair("a")
    builds.store_upload("system", io.BytesIO(system_zip()), device_id="a")
    from filament_kit.profiles import bbl
    held = []
    real = bbl.Store.parse

    def parse(cls, files):
        held.append(getattr(builds._held, "live_lock", 0))
        return real.__func__(cls, files)

    monkeypatch.setattr(bbl.Store, "parse", classmethod(parse))
    assert builds.system_store() is not None
    assert held == [0]


def test_meta_is_a_public_copy():
    pair("a")
    builds.store_upload("system", io.BytesIO(system_zip()), device_id="a")
    m = builds.meta()
    assert m["system_presets"] == len(TG.presets()) and m["owner"] == "a"
    m["owner"] = "x"
    assert builds.meta()["owner"] == "a"
