"""Orca target: the upload zips, the client routes, the build zip's orca/ tree and the installer."""
import io
import json
import zipfile
from pathlib import Path

import pytest

import orca_fixture
import studio_fixture
from fksync import client, installer, zips
from fksync.store import AppDirs
from fksync.treehash import tree_hash

ORCA_INFO = {"sync_info": "", "user_id": orca_fixture.USER_ID, "setting_id": "", "base_id": "RcBNzytWgwRrwXXz",
             "updated_time": "1"}


def _orca_preset(name, **extra):
    d = {"name": name, "inherits": "Generic PLA @System", "from": "User", "filament_id": "Pabcdef1",
         "compatible_printers": ["Sovol SV08 MAX"], "filament_flow_ratio": ["0.98"], "nozzle_temperature": ["215"]}
    d.update(extra)
    return d


# --- upload zips ---------------------------------------------------------------------------------

def test_orca_system_zip_holds_bbl_json_and_library_index(tmp_path):
    orca = orca_fixture.make(tmp_path / "appdata", install=tmp_path / "pf" / "OrcaSlicer 2.5.0",
                             opc=orca_fixture.opc_blob(orca_fixture.LIBRARY))
    (orca.system_bbl / "notes.txt").write_text("x")                      # not a .json: not sent
    data, h = zips.orca_system(orca)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        index = json.loads(zf.read("OrcaFilamentLibrary/index.json"))
        bbl = json.loads(zf.read("BBL/filament/Bambu PLA Basic @BBL H2D.json"))
    assert names == sorted(names)
    assert set(names) == {"BBL/filament/Bambu PLA Basic @BBL H2D.json", "BBL/filament/Bambu PLA Basic @base.json",
                          "BBL/filament/SUNLU/SUNLU PLA+ @BBL H2D.json", "OrcaFilamentLibrary/index.json"}
    assert bbl["setting_id"] == "GFSA00_10"
    assert index["version"] == 1
    assert index["source"].startswith("OrcaFilamentLibrary.opc ")
    assert [p["name"] for p in index["presets"]] == ["Acme PLA+ @System", "Eolas ABS @System", "Generic PLA @System"]
    assert set(index["presets"][0]) == {"name", "setting_id", "filament_id", "filament_type", "inherits"}
    # the hash is the server's tree hash of the unpacked zip, and the zip is deterministic
    out = tmp_path / "unpacked"
    zipfile.ZipFile(io.BytesIO(data)).extractall(out)
    assert h == tree_hash(out)
    assert zips.orca_system(orca) == (data, h)


def test_orca_system_zip_without_packed_library(tmp_path):
    orca = orca_fixture.make(tmp_path / "appdata")
    data, _ = zips.orca_system(orca)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert "OrcaFilamentLibrary/index.json" not in zf.namelist()
        assert "BBL/filament/Bambu PLA Basic @BBL H2D.json" in zf.namelist()


def test_orca_system_zip_limits(tmp_path, monkeypatch):
    orca = orca_fixture.make(tmp_path / "appdata")
    monkeypatch.setattr(zips, "MAX_ENTRIES", 2)
    with pytest.raises(zips.TooLarge):
        zips.orca_system(orca)


# --- client routes -------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,partial,path", [
    ("orca_live", None, "/api/sync/live?target=orca"),
    ("orca_live", "20261102-010203", "/api/sync/live?target=orca&partial=20261102-010203"),   # Ruling O
    ("orca_system", None, "/api/sync/system?target=orca"),
    ("system", None, "/api/sync/system")])
def test_client_upload_routes(monkeypatch, kind, partial, path):
    c = client.Client({"host": "h", "fp": "a" * 64}, "tok")
    seen = []
    monkeypatch.setattr(c, "_request", lambda *a, **kw: seen.append(a) or {})
    c.upload(kind, b"zip", user_id="u1", partial=partial)
    assert seen == [("PUT", path, b"zip", "application/zip")]   # never the Bambu user id on an Orca upload


def test_client_rebuild_sends_orca_live_hash(monkeypatch):
    c = client.Client({"host": "h", "fp": "a" * 64}, "tok")
    seen = []
    monkeypatch.setattr(c, "_request", lambda *a, **kw: seen.append(json.loads(a[2])) or {})
    c.rebuild("a" * 64)
    c.rebuild("a" * 64, "b" * 64)
    assert seen == [{"live_hash": "a" * 64}, {"live_hash": "a" * 64, "orca_live_hash": "b" * 64}]


# --- build zip -----------------------------------------------------------------------------------

def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, d in entries.items():
            zf.writestr(n, d)
    return buf.getvalue()


def test_unpack_build_accepts_orca_tree(tmp_path):
    data = _zip({"BUILD.json": b"{}", "base/A.json": b"{}", "orca/A @SV08 MAX 0.4.json": b"{}",
                 "orca/A @SV08 MAX 0.4.info": b"x"})
    zips.unpack_build(data, tmp_path / "b")
    assert (tmp_path / "b" / "orca" / "A @SV08 MAX 0.4.json").is_file()


@pytest.mark.parametrize("bad", ["orca/sub/A.json", "orca/../A.json", "orca/A.txt", "orcas/A.json", "orca/.A.json"])
def test_unpack_build_refuses_bad_orca_entries(tmp_path, bad):
    with pytest.raises(ValueError):
        zips.unpack_build(_zip({"BUILD.json": b"{}", bad: b"{}"}), tmp_path / "b")


# --- installer -----------------------------------------------------------------------------------

def _write_tree(folder: Path, presets: dict, infos: dict | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in presets.items():
        with open(folder / f"{name}.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=4)
        info = (infos or {}).get(name, {"sync_info": "", "setting_id": "", "base_id": "RcBNzytWgwRrwXXz"})
        orca_fixture.write_info(folder / f"{name}.info", info)


class Env:
    def __init__(self, tmp_path, orca_live=None, bs_live=None, orca=True):
        self.tmp = tmp_path
        self.folders = studio_fixture.make(tmp_path / "appdata", base=bs_live or {})
        self.orca = orca_fixture.make(tmp_path / "appdata", presets=orca_live or {}) if orca else None
        self.dirs = AppDirs(tmp_path / "local" / "filament-kit-sync")
        self.dirs.ensure()
        self.n = 0

    def build(self, orca_presets, bs_presets=None, meta=None, infos=None) -> Path:
        self.n += 1
        b = self.tmp / f"build{self.n}"
        b.mkdir()
        (b / "BUILD.json").write_text(json.dumps({"stamp": f"2026110201000{self.n}", "live_hash": "x", **(meta or {})}))
        if bs_presets is not None:
            _write_tree(b / "base", bs_presets)
        if orca_presets is not None:
            _write_tree(b / "orca", orca_presets, infos)
        return b

    def snapshot(self, orca_presets, bs_presets=None):
        self.dirs.installed.mkdir(parents=True, exist_ok=True)
        (self.dirs.installed / "BUILD.json").write_text("{}")
        _write_tree(self.dirs.installed / "orca", orca_presets)
        if bs_presets:
            _write_tree(self.dirs.installed / "base", bs_presets)

    def install(self, build, running=lambda: False, orca_running=lambda: False, **kw):
        return installer.install(build, self.folders, self.dirs, running=running, stamp_now="20261102-010000",
                                 orca=self.orca, orca_running=orca_running, **kw)


N = "Acme PLA @SV08 MAX 0.4"


def test_installs_orca_tree_flat_with_backup_and_snapshot(tmp_path):
    e = Env(tmp_path, orca_live={N: (_orca_preset(N), dict(ORCA_INFO, setting_id="CLOUD123"))})
    live_before = (e.orca.user_filament / f"{N}.json").read_bytes()
    b = e.build({N: _orca_preset(N, nozzle_temperature=["220"]), "New PLA @SV08 MAX 0.4": _orca_preset("New")},
                {"Acme PLA @BBL H2D": {"name": "Acme PLA @BBL H2D", "from": "User"}})
    res = e.install(b, accept={"orca": [N]})          # the owner accepted its update
    assert json.loads((e.orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["220"]
    assert (e.orca.user_filament / "New PLA @SV08 MAX 0.4.json").is_file()
    assert not (e.orca.user_filament / "base" / f"{N}.json").exists()           # Orca's folder is flat
    assert installer.read_info(e.orca.user_filament / f"{N}.info")["setting_id"] == "CLOUD123"  # cloud id kept
    assert (e.folders.user_filament / "base" / "Acme PLA @BBL H2D.json").is_file()
    assert res.installed == ["Acme PLA @BBL H2D"] and res.installed_orca == ["Acme PLA @SV08 MAX 0.4",
                                                                             "New PLA @SV08 MAX 0.4"]
    assert res.backup_orca == e.dirs.orca_backups / res.backup.name
    assert (res.backup_orca / f"{N}.json").read_bytes() == live_before
    assert (e.dirs.installed / "orca" / f"{N}.json").is_file()
    assert not list(e.orca.user_filament.glob(".*fktmp"))


def test_orca_only_build_installs(tmp_path):
    e = Env(tmp_path)
    res = e.install(e.build({N: _orca_preset(N)}))
    assert res.installed == [] and res.installed_orca == [N]
    assert (e.orca.user_filament / f"{N}.json").is_file()


def test_no_presets_at_all_refused(tmp_path):
    e = Env(tmp_path)
    with pytest.raises(installer.Refused):
        e.install(e.build(None, None))


@pytest.mark.parametrize("live_gcode,ok", [(None, False), (["G1 X0 ; live"], True), (["other"], False)])
def test_orca_gcode_only_when_equal_to_live(tmp_path, live_gcode, ok):
    extra = {"filament_start_gcode": live_gcode} if live_gcode else {}
    e = Env(tmp_path, orca_live={N: (_orca_preset(N, **extra), ORCA_INFO)})
    before = (e.orca.user_filament / f"{N}.json").read_bytes()
    b = e.build({N: _orca_preset(N, filament_start_gcode=["G1 X0 ; live"], nozzle_temperature=["230"])})
    if ok:
        e.install(b)
        return
    with pytest.raises(installer.Refused) as ei:
        e.install(b)
    assert ei.value.code == "untrusted_gcode"
    assert "Orca Slicer" in ei.value.reason and N in ei.value.reason
    assert (e.orca.user_filament / f"{N}.json").read_bytes() == before


def test_orca_gcode_from_bambu_system_or_snapshot_is_not_trusted(tmp_path):
    # Bambu Studio's system G-code and the installed snapshot are trusted for Bambu presets only
    sys_gcode = ["M106 P3 S0\n; system start"]
    e = Env(tmp_path)
    studio_fixture._write_json(e.folders.system_filament / "G.json", {"name": "G", "filament_start_gcode": sys_gcode})
    e.snapshot({N: _orca_preset(N, filament_start_gcode=sys_gcode)})
    with pytest.raises(installer.Refused) as ei:
        e.install(e.build({N: _orca_preset(N, filament_start_gcode=sys_gcode)}))
    assert ei.value.code == "untrusted_gcode"


def test_orca_edit_or_delete_after_build_refuses(tmp_path):
    other = "Other PLA @SV08 MAX 0.4"
    e = Env(tmp_path, orca_live={N: (_orca_preset(N, filament_flow_ratio=["0.91"]), ORCA_INFO),
                                 other: (_orca_preset(other), ORCA_INFO)})
    e.snapshot({N: _orca_preset(N), other: _orca_preset(other)})
    with pytest.raises(installer.Refused) as ei:
        e.install(e.build({N: _orca_preset(N), other: _orca_preset(other)}))
    assert ei.value.code == "stale_build" and "Orca Slicer" in ei.value.reason and "filament_flow_ratio" in ei.value.reason
    # the build carried that edit: fine
    e.install(e.build({N: _orca_preset(N, filament_flow_ratio=["0.91"]), other: _orca_preset(other)}))
    # deleted in Orca after the build (a third preset keeps it below the reset rule)
    e2 = Env(tmp_path / "two", orca_live={other: (_orca_preset(other), ORCA_INFO),
                                          "C": (_orca_preset("C"), ORCA_INFO), "D": (_orca_preset("D"), ORCA_INFO),
                                          "E": (_orca_preset("E"), ORCA_INFO)})
    e2.snapshot({N: _orca_preset(N), other: _orca_preset(other), "C": _orca_preset("C"), "D": _orca_preset("D"),
                 "E": _orca_preset("E")})
    with pytest.raises(installer.Refused) as ei:
        e2.install(e2.build({N: _orca_preset(N), other: _orca_preset(other)}))
    assert ei.value.code == "stale_build" and "deleted in Orca Slicer" in ei.value.reason


def test_orca_inapp_record_and_restored(tmp_path):
    other = ["B", "C", "D", "E"]
    live = {N: (_orca_preset(N, filament_flow_ratio=["nil"]), ORCA_INFO)}
    live.update({o: (_orca_preset(o), ORCA_INFO) for o in other})
    e = Env(tmp_path, orca_live=live)
    e.snapshot({N: _orca_preset(N), "Gone": _orca_preset("Gone"), **{o: _orca_preset(o) for o in other}})
    presets = {N: _orca_preset(N), "Gone": _orca_preset("Gone")}
    # without the build's records: the "nil" is a late edit and "Gone" a deletion
    with pytest.raises(installer.Refused) as ei:
        e.install(e.build(presets))
    assert "Gone: deleted in Orca Slicer" in ei.value.reason and "filament_flow_ratio" in ei.value.reason
    meta = {"orca_inapp": {N: {"filament_flow_ratio": ["nil"]}}, "orca_restored": ["gone"]}
    res = e.install(e.build(presets, meta=meta), accept={"orca": [N]})
    assert res.installed_orca == [N, "Gone"]
    assert (e.orca.user_filament / "Gone.json").is_file()       # restored, not reported as deleted
    assert "Gone" not in res.stale_orca and res.stale_orca == ["B", "C", "D", "E"]  # not built: listed only


def test_failed_orca_backup_keeps_every_bambu_backup(tmp_path, monkeypatch):
    e = Env(tmp_path, orca_live={N: (_orca_preset(N), ORCA_INFO)})
    for i in range(installer.KEEP_BACKUPS):
        (e.dirs.backups / f"20261101-00000{i}").mkdir(parents=True)
    real = installer.shutil.copytree

    def fail_for_orca(src, dst, *a, **kw):
        if Path(src) == e.orca.user_filament:
            raise OSError(28, "No space left on device")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(installer.shutil, "copytree", fail_for_orca)
    with pytest.raises(installer.Refused):
        e.install(e.build({N: _orca_preset(N, nozzle_temperature=["230"])}))
    assert sorted(p.name for p in e.dirs.backups.iterdir()) == [f"20261101-00000{i}" for i in range(5)]


def test_orca_running_refuses_before_any_write(tmp_path):
    e = Env(tmp_path, orca_live={N: (_orca_preset(N), ORCA_INFO)})
    before = tree_hash(e.orca.user_filament)
    with pytest.raises(installer.Refused) as ei:
        e.install(e.build({N: _orca_preset(N, nozzle_temperature=["230"])}), orca_running=lambda: True)
    assert ei.value.code == "studio_running" and "Orca Slicer" in ei.value.reason
    assert tree_hash(e.orca.user_filament) == before
    assert not e.dirs.backups.exists() and not e.dirs.orca_backups.exists()
    # it starts between the checks and the first write: still nothing written
    calls = iter([False, True])
    with pytest.raises(installer.Refused):
        e.install(e.build({N: _orca_preset(N, nozzle_temperature=["230"])}), orca_running=lambda: next(calls))
    assert tree_hash(e.orca.user_filament) == before and not e.dirs.backups.exists()


def test_orca_absent_installs_bambu_only_and_snapshot_has_no_orca(tmp_path):
    e = Env(tmp_path, orca=False)
    b = e.build({N: _orca_preset(N)}, {"Acme PLA @BBL H2D": {"name": "Acme PLA @BBL H2D", "from": "User"}})
    res = e.install(b)
    assert res.installed == ["Acme PLA @BBL H2D"] and res.installed_orca == []
    assert (e.dirs.installed / "base").is_dir() and not (e.dirs.installed / "orca").exists()
    assert not e.dirs.orca_backups.exists()


def test_base_only_install_keeps_the_previous_orca_snapshot(tmp_path):
    """B-I1: a base/-only install must not drop the Orca snapshot of the last build whose orca/ went in: the server
    keeps that build as its Orca snapshot (Ruling AB), and changed_since_install diffs Orca edits against it."""
    e = Env(tmp_path, orca=False)
    e.snapshot({N: _orca_preset(N, nozzle_temperature=["210"])})
    b = e.build({N: _orca_preset(N, nozzle_temperature=["230"])},
                {"Acme PLA @BBL H2D": {"name": "Acme PLA @BBL H2D", "from": "User"}})
    e.install(b)
    assert (e.dirs.installed / "base" / "Acme PLA @BBL H2D.json").is_file()
    kept = json.loads((e.dirs.installed / "orca" / f"{N}.json").read_text())
    assert kept["nozzle_temperature"] == ["210"]                           # the old Orca snapshot, not the build's


def test_orca_stale_listed_never_deleted(tmp_path):
    old = "Old PLA @SV08 MAX 0.4"
    e = Env(tmp_path, orca_live={N: (_orca_preset(N), ORCA_INFO), old: (_orca_preset(old), ORCA_INFO)})
    e.snapshot({N: _orca_preset(N), old: _orca_preset(old)})
    res = e.install(e.build({N: _orca_preset(N)}))
    assert res.stale_orca == [old] and res.stale == []
    assert (e.orca.user_filament / f"{old}.json").is_file()


def test_backups_keep_five_per_target(tmp_path):
    e = Env(tmp_path, orca_live={N: (_orca_preset(N), ORCA_INFO)})
    for i in range(7):
        installer.install(e.build({N: _orca_preset(N, nozzle_temperature=[str(200 + i)])}), e.folders, e.dirs,
                          running=lambda: False, stamp_now=f"20261102-01000{i}", orca=e.orca,
                          orca_running=lambda: False)
    for folder in (e.dirs.orca_backups, e.dirs.backups):
        kept = sorted(p.name for p in folder.iterdir())
        assert len(kept) == installer.KEEP_BACKUPS
        assert kept[-1] == "20261102-010006"    # the newest stays; the oldest are the ones pruned
        assert "20261102-010000" not in kept
