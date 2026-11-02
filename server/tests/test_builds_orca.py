"""Task 6: Orca presets beside Bambu Studio's in one build (two trees), and the family install unchanged.

The golden test pins the family install (no Orca store, no slicer_printers, presets_orca false): its build zip,
current.json and deleted.json must stay byte-identical to the ones made before the Orca target existed
(tests/data/golden/family/, written by the pre-change code with FK_WRITE_GOLDEN=1).
"""
import io
import json
import os
from pathlib import Path

import pytest

from filament_kit import config
from filament_kit.profiles import builds, lines as lines_mod

import test_builds as TB
import test_generate as TG
from test_builds import env  # noqa: F401  (the fixture)

GOLDEN = Path(__file__).parent / "data" / "golden" / "family"


@pytest.fixture
def fixed_ids(monkeypatch):
    """Deterministic generated filament ids (the real ones are random)."""
    seq = iter(f"P{i:07x}" for i in range(1, 10_000))
    monkeypatch.setattr(lines_mod, "new_filament_id", lambda used: next(seq))


def _family_build(env) -> str:
    """Upload, build, install, edit in the app, delete one preset in the app, build again; the second build's
    stamp. Times are fixed except the install/upload clock (not part of the compared files)."""
    TB.synced(env)
    b1 = builds.run_build(env, now=TG.NOW)["stamp"]
    builds.record_installed(b1, "a")
    TB.tick()
    name = TG.sunlu(TG.H2D, "0.4")
    gone = TG.sunlu(TG.H2D, "0.8")
    cfg = json.loads((TB.profiles_dir() / "builds" / b1 / "base" / f"{name}.json").read_text(encoding="utf-8"))
    flow = ["0.91"] * len(cfg["filament_flow_ratio"])
    notes = cfg["filament_notes"].replace("Spoolman filament ids", "dry 8 h first\nSpoolman filament ids")
    data = TB._live_zip_of(b1, edit={name: {"filament_flow_ratio": flow, "filament_notes": notes}})
    import zipfile
    src = zipfile.ZipFile(io.BytesIO(data))
    files = {n: src.read(n) for n in src.namelist() if not n.startswith(f"base/{gone}.")}
    builds.store_upload("live", io.BytesIO(TB.zip_of(files)), device_id="a", user_id="1")
    TB.tick()
    builds.request_rebuild("edits")
    r = builds.run_build(env, now=TG.NOW + 1)
    assert r["ok"] is True, r
    return r["stamp"]


def _family_files(stamp: str) -> dict[str, bytes]:
    return {"build.zip": builds.build_zip(stamp),
            "current.json": (TB.profiles_dir() / "current.json").read_bytes(),
            "deleted.json": (TB.profiles_dir() / "deleted.json").read_bytes()}


def test_family_build_is_byte_identical_to_before_the_orca_target(env, fixed_ids):
    stamp = _family_build(env)
    got = _family_files(stamp)
    if os.environ.get("FK_WRITE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for n, b in got.items():
            (GOLDEN / n).write_bytes(b)
    want = {n: (GOLDEN / n).read_bytes() for n in got}
    m = builds.manifest(stamp)
    assert m["inapp"] and m["deleted"], "the scenario must exercise in-app edits and deletions"
    for n in got:
        assert got[n] == want[n], n
    view = builds.state_view("a")["build"]
    assert set(view) == {"stamp", "live_hash", "created", "presets", "problems"}


# ---------- two trees ----------

import importlib
import zipfile

import test_generate_orca as TGO
from filament_kit import profiles

SV08 = TGO.SV08
OUSER = "f790a1c6-1"


@pytest.fixture
def orca_cfg(env, monkeypatch, tmp_path):
    """The owner's setup: the SV08 MAX in Orca Slicer, and Orca presets for the Bambu printers too."""
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    config.save({"slicer_printers": [SV08], "presets_orca": True})
    return env


def orca_system_zip() -> bytes:
    files = {f"BBL/filament/{n}.json": json.dumps(cfg) for n, cfg in TGO.orca_bbl().items()}
    files["OrcaFilamentLibrary/index.json"] = TGO.ORCA_INDEX.read_bytes()
    return TB.zip_of(files)


def orca_synced(live=None):
    builds.store_upload("orca_system", io.BytesIO(orca_system_zip()), device_id="a")
    builds.store_upload("orca_live", io.BytesIO(TB.zip_of(live or {"keep.json": "{}"})), device_id="a",
                        user_id=OUSER)


def _orca_live_zip_of(stamp, *, edit=None, drop=()) -> bytes:
    tree = TB.profiles_dir() / "builds" / stamp / "orca"
    files = {}
    for p in sorted(tree.iterdir()):
        if p.stem in drop:
            continue
        data = p.read_bytes()
        if p.suffix == ".json" and edit and p.stem in edit:
            data = json.dumps({**json.loads(data), **edit[p.stem]}).encode()
        files[p.name] = data
    return TB.zip_of(files)


def load_pc_sync(name):
    import sys
    pkg = str(TB.REPO / "pc-sync")
    if pkg not in sys.path:
        sys.path.insert(0, pkg)
    return importlib.import_module(f"fksync.{name}")


def test_two_tree_build_zip_and_build_json(orca_cfg, tmp_path):
    TB.synced(orca_cfg)
    live = {"SUNLU PLA+ 2.0 @SV08 MAX 0.4.json": json.dumps({"name": "SUNLU PLA+ 2.0 @SV08 MAX 0.4"}),
            "SUNLU PLA+ 2.0 @SV08 MAX 0.4.info": "sync_info = \nsetting_id = PFUSsv08\nbase_id = x\n"}
    orca_synced(live=live)
    r = builds.run_build(orca_cfg, now=TG.NOW)
    assert r["ok"] is True, r
    m = builds.manifest(r["stamp"])
    meta = builds.meta()
    assert m["orca_live_hash"] == meta["orca_live_hash"] and m["orca_system_hash"] == meta["orca_system_hash"]
    assert m["orca_user_id"] == OUSER
    assert m["orca_inapp"] == {} and m["orca_restored"] == [] and m["orca_deleted"] == []
    targets = {p["name"]: p["target"] for p in m["presets"]}
    assert targets[TGO.sv08("0.4")] == targets[TGO.h2d("0.4")] == "orca"
    assert targets[TG.sunlu(TG.H2D, "0.4")] == "bambu_studio"
    with zipfile.ZipFile(io.BytesIO(builds.build_zip(r["stamp"]))) as zf:
        names = set(zf.namelist())
        info = zf.read(f"orca/{TGO.sv08('0.4')}.info").decode()
    assert {f"orca/{TGO.sv08('0.4')}.json", f"orca/{TGO.h2d('0.6')}.json",
            f"base/{TG.sunlu(TG.H2D, '0.4')}.json"} <= names
    assert all(n == "BUILD.json" or n.count("/") == 1 for n in names)              # orca/ is flat
    assert "setting_id = PFUSsv08" in info and f"user_id = {OUSER}" in info
    cur = builds.current()
    assert cur["orca_live_hash"] == meta["orca_live_hash"]
    assert builds.state_view("a")["build"]["orca_live_hash"] == meta["orca_live_hash"]
    deleted = json.loads((TB.profiles_dir() / "deleted.json").read_text(encoding="utf-8"))
    assert deleted == {"deleted_before": [], "orca_deleted_before": []}
    # pc-sync takes the zip as it is
    zips = load_pc_sync("zips")
    got = zips.unpack_build(builds.build_zip(r["stamp"]), tmp_path / "unpacked")
    assert got["orca_live_hash"] == meta["orca_live_hash"]
    assert (tmp_path / "unpacked" / "orca" / f"{TGO.sv08('1.0')}.json").is_file()
    # and installs it: no G-code refusal, the Orca tree flat into the Orca user folder
    installer, studio, pstore = load_pc_sync("installer"), load_pc_sync("studio"), load_pc_sync("store")
    bs = studio.StudioFolders(tmp_path / "bs", "BambuStudio", "1", tmp_path / "bs" / "user" / "filament",
                              tmp_path / "bs" / "system")
    (bs.user_filament / "base").mkdir(parents=True)
    bs.system_filament.mkdir(parents=True)
    of = studio.OrcaFolders(tmp_path / "orca", OUSER, tmp_path / "orca" / "filament", tmp_path / "orca" / "sys",
                            None, None)
    of.user_filament.mkdir(parents=True)
    res = installer.install(tmp_path / "unpacked", bs, pstore.AppDirs(tmp_path / "app"), running=lambda: False,
                            stamp_now="20270115-080000", orca=of, orca_running=lambda: False)
    assert TGO.sv08("0.4") in res.installed_orca and TG.sunlu(TG.H2D, "0.4") in res.installed
    assert (of.user_filament / f"{TGO.h2d('0.4')}.json").is_file()
    # the AMS lookup serves Bambu Studio presets only
    ref = profiles.preset_for(SUNLU_F, "O1D", 0.4)
    assert ref is not None and ref.name == TG.sunlu(TG.H2D, "0.4")


SUNLU_F = TB.SUNLU[0]


def test_orca_printers_without_an_orca_upload_build_bambu_only(orca_cfg):
    TB.synced(orca_cfg)
    r = builds.run_build(orca_cfg, now=TG.NOW)
    assert r["ok"] is True
    m = builds.manifest(r["stamp"])
    assert not [p for p in m["presets"] if p["target"] == "orca"]
    assert [p for p in m["presets"] if p["target"] == "bambu_studio"]
    assert any("no Orca Slicer system presets yet" in p for p in r["problems"])
    assert m["orca_live_hash"] is None


def test_orca_edits_and_deletions_from_a_fresh_orca_live_folder(orca_cfg):
    """Ruling Z: no Orca wait. After an install the build runs on the Bambu Studio live upload alone (the stale
    Orca folder is not diffed); a fresh Orca live upload's edits and deletions are then taken."""
    TB.synced(orca_cfg)
    orca_synced()
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    builds.record_installed(b1, "a", ["base", "orca"])
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")
    TB.tick()
    builds.request_rebuild("bambu live only")
    r = builds.run_build(orca_cfg, now=TG.NOW + 1)
    assert r["ok"] is True, r                                                # never waits for Orca
    assert builds.manifest(r["stamp"])["orca_inapp"] == {}
    TB.tick()
    gone = TGO.sv08("1.0")
    edit = {TGO.sv08("0.4"): {"nozzle_temperature": ["233"]}}
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b1, edit=edit, drop=(gone,))), device_id="a",
                        user_id=OUSER)
    builds.request_rebuild("pc sync: the build predates the Orca live presets")
    r = builds.run_build(orca_cfg, now=TG.NOW + 2)
    assert r["ok"] is True, r
    m = builds.manifest(r["stamp"])
    assert m["orca_inapp"] == {TGO.sv08("0.4"): {"nozzle_temperature": ["233"]}} and m["inapp"] == {}
    assert m["orca_deleted"] == [gone] and m["deleted"] == []
    saved = json.loads((TB.profiles_dir() / "deleted.json").read_text(encoding="utf-8"))
    assert saved["orca_deleted_before"] == [gone] and saved["deleted_before"] == []
    builds.restore_deleted_next()
    builds.request_rebuild("restore")
    r = builds.run_build(orca_cfg, now=TG.NOW + 3)
    assert builds.manifest(r["stamp"])["orca_restored"] == [gone]


def test_orca_partial_install_values_are_not_edits(orca_cfg):
    TB.synced(orca_cfg)
    orca_synced()
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    builds.record_installed(b1, "a", ["base", "orca"])
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b1)), device_id="a", user_id=OUSER)
    orca_cfg.filaments = [dict(f, density=1.31) for f in TB.SUNLU]
    builds.request_rebuild("density")
    b2 = builds.run_build(orca_cfg, now=TG.NOW + 1)["stamp"]
    TB.tick()
    # b2's install stopped part-way: Orca holds b2's values, the PC says so with partial=b2
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b2)), device_id="a", user_id=OUSER, partial=b2)
    builds.request_rebuild("after the partial install")
    r = builds.run_build(orca_cfg, now=TG.NOW + 2)
    assert r["ok"] is True, r
    assert builds.manifest(r["stamp"])["orca_inapp"] == {}


def test_new_sync_pc_keeps_the_owners_orca_edits(orca_cfg):
    TB.synced(orca_cfg)
    orca_synced()
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    builds.record_installed(b1, "a", ["base", "orca"])
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")
    edit = {TGO.sv08("0.4"): {"nozzle_temperature": ["233"]}}
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b1, edit=edit)), device_id="a", user_id=OUSER)
    b2 = builds.run_build(orca_cfg, now=TG.NOW + 1)["stamp"]
    builds.record_installed(b2, "a", ["base", "orca"])
    TB.tick()
    TB.pair("b")
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b1)), device_id="b", user_id=OUSER)
    r = builds.run_build(orca_cfg, now=TG.NOW + 2)
    assert r["ok"] is True, r
    assert builds.manifest(r["stamp"])["orca_inapp"] == {TGO.sv08("0.4"): {"nozzle_temperature": ["233"]}}


# ---------- fix round 1 ----------

def test_new_sync_pc_without_orca_is_never_waited_for(orca_cfg):
    """I1: a new sync PC that has no Orca Slicer: the old PC's Orca live upload is forgotten, builds go on."""
    TB.synced(orca_cfg)
    orca_synced()
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    builds.record_installed(b1, "a", ["base", "orca"])
    TB.tick()
    TB.pair("b")
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="b", user_id="1")
    meta = builds.meta()
    assert not {"orca_live_at", "orca_live_hash", "orca_user_id"} & set(meta)
    b2 = builds.run_build(orca_cfg, now=TG.NOW + 1)["stamp"]
    assert b2 and TB.profiles_dir().joinpath("builds", b2, "orca").is_dir()
    builds.record_installed(b2, "b", ["base", "orca"])
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b2)), device_id="b", user_id="1")
    builds.request_rebuild("after the install")
    r = builds.run_build(orca_cfg, now=TG.NOW + 2)
    assert r["ok"] is True, r


def test_failing_orca_upload_never_strands_a_request_and_its_stale_folder_is_not_diffed(orca_cfg):
    """Ruling Z: the Orca live folder predates the install (the Orca upload keeps failing) and differs from the
    installed build. A pending request waits for the Bambu Studio live folder only; that upload alone renews it
    (no manual request) and the build runs: the stale Orca values are no in-app edits, no Orca preset counts as
    deleted, the installed build's Orca record and restores are carried unchanged."""
    TB.synced(orca_cfg)
    orca_synced()
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    m1 = builds.manifest(b1)
    gone = TGO.sv08("1.0")
    old = {TGO.sv08("0.4"): {"nozzle_temperature": ["199"]}}                     # values from before b1
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b1, edit=old, drop=(gone,))), device_id="a",
                        user_id=OUSER)
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")   # pre-install
    TB.tick()
    builds.record_installed(b1, "a", ["base", "orca"])
    TB.tick()
    builds.request_rebuild("spoolman changed")
    TB.tick()
    r = builds.run_build(orca_cfg, now=TG.NOW + 1)
    assert r["waiting"] is True and r["error"] == builds.WAIT_LIVE                # Bambu Studio's S32, as before
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")   # Orca's fails
    assert builds.state_view("a")["rebuild_requested"] is not None                # renewed by that upload alone
    TB.tick()
    r = builds.run_build(orca_cfg, now=TG.NOW + 2)
    assert r["ok"] is True, r
    m = builds.manifest(r["stamp"])
    assert m["orca_inapp"] == m1["orca_inapp"] == {}
    assert m["orca_deleted"] == [] and m["orca_restored"] == []
    assert gone in {p["name"] for p in m["presets"]}
    cfg = json.loads((TB.profiles_dir() / "builds" / r["stamp"] / "orca" / f"{TGO.sv08('0.4')}.json")
                     .read_text(encoding="utf-8"))
    assert cfg.get("nozzle_temperature") != ["199"]
    assert builds.state_view("a")["rebuild_requested"] is None


def test_orca_store_alone_leaves_the_family_build_and_lines_unchanged(env, fixed_ids):
    """M1 (Ruling X): an uploaded Orca store without presets_orca / slicer_printers changes nothing."""
    builds.store_upload("orca_system", io.BytesIO(orca_system_zip()), device_id="a")
    stamp = _family_build(env)
    got = _family_files(stamp)
    for n in got:
        assert got[n] == (GOLDEN / n).read_bytes(), n
    row = json.loads((TB.profiles_dir() / "lines.json").read_text(encoding="utf-8"))["lines"][0]
    assert (row["orca_parent"], row["orca_parent_source"]) == ("Generic PLA", "material")     # not re-chosen


def test_counts_are_bambu_studio_presets(orca_cfg):
    """M2: per-line and build preset counts count Bambu Studio presets; Orca's are counted apart."""
    from filament_kit import profiles_api
    TB.synced(orca_cfg)
    orca_synced()
    r = builds.run_build(orca_cfg, now=TG.NOW)
    m = builds.manifest(r["stamp"])
    bs = [p for p in m["presets"] if p["target"] == "bambu_studio"]
    orc = [p for p in m["presets"] if p["target"] == "orca"]
    assert bs and orc
    cur = builds.current()
    assert cur["presets"] == len(bs) and cur["orca_presets"] == len(orc)
    assert builds.state_view("a")["build"]["presets"] == len(bs)
    assert builds.status()["presets"] == len(bs)
    assert profiles_api._preset_counts() == {"sunlu--pla-plus-2-0": len(bs)}


def test_presets_orca_nozzles_config(orca_cfg):
    """I2 (Ruling W): Orca presets for Bambu printers skip 0.2 unless presets_orca_nozzles says otherwise."""
    TB.synced(orca_cfg)
    orca_synced()
    r = builds.run_build(orca_cfg, now=TG.NOW)
    names = {p["name"] for p in builds.manifest(r["stamp"])["presets"]}
    assert TGO.h2d("0.4") in names and TGO.h2d("0.2") not in names
    cfg = config.load()
    cfg["presets_orca_nozzles"] = ["0.2", "0.4"]
    config.save(cfg)
    builds.request_rebuild("nozzles")
    r = builds.run_build(orca_cfg, now=TG.NOW + 1)
    names = {p["name"] for p in builds.manifest(r["stamp"])["presets"] if p["target"] == "orca"}
    assert {TGO.h2d("0.2"), TGO.h2d("0.4")} <= names and TGO.h2d("0.6") not in names


# ---------- fix round 3 (Ruling AB): the Orca snapshot is the build whose orca/ went in ----------

PETG = TG.fil(60, "PETG Basic Blue", vendor="SUNLU", material="PETG",
              extra={"line": json.dumps("PETG Basic")})


def test_base_only_install_keeps_the_orca_snapshot(orca_cfg):
    """b1 goes in with its orca/ tree; b2 (other density, a new line with new Orca presets) goes in base/ only.
    The Orca folder still holds b1's presets: a fresh Orca upload is diffed against b1, so b2's density is no
    in-app edit and b2's new Orca presets are not deletions; the owner's real edit is taken."""
    TB.synced(orca_cfg)
    orca_synced()
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    builds.record_installed(b1, "a", ["base", "orca"])
    inst = json.loads((TB.profiles_dir() / "installed.json").read_text(encoding="utf-8"))
    assert inst["orca_stamp"] == b1 and inst["orca_at"] == inst["at"]
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")
    orca_cfg.filaments = [dict(f, density=1.31) for f in TB.SUNLU] + [PETG]
    builds.request_rebuild("density + a new line")
    b2 = builds.run_build(orca_cfg, now=TG.NOW + 1)["stamp"]
    new_orca = {p["name"] for p in builds.manifest(b2)["presets"]
                if p["target"] == "orca" and p["line_id"] != "sunlu--pla-plus-2-0"}
    assert new_orca
    TB.tick()
    builds.record_installed(b2, "a")                       # an older PC sync: no trees = ["base"]
    inst = json.loads((TB.profiles_dir() / "installed.json").read_text(encoding="utf-8"))
    assert inst["stamp"] == b2 and inst["orca_stamp"] == b1
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b2)), device_id="a", user_id="1")
    edit = {TGO.sv08("0.4"): {"nozzle_temperature": ["233"]}}
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b1, edit=edit)), device_id="a", user_id=OUSER)
    builds.request_rebuild("orca edit")
    r = builds.run_build(orca_cfg, now=TG.NOW + 2)
    assert r["ok"] is True, r
    m = builds.manifest(r["stamp"])
    assert m["orca_inapp"] == {TGO.sv08("0.4"): {"nozzle_temperature": ["233"]}}       # not the density
    assert m["orca_deleted"] == [] and not new_orca - {p["name"] for p in m["presets"]}
    assert not any("app reset" in p for p in m["problems"])


def test_no_orca_install_yet_means_the_orca_folder_is_never_diffed(orca_cfg):
    TB.synced(orca_cfg)
    orca_synced()
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    builds.record_installed(b1, "a")                       # base/ only
    assert "orca_stamp" not in json.loads((TB.profiles_dir() / "installed.json").read_text(encoding="utf-8"))
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")
    edit = {TGO.sv08("0.4"): {"nozzle_temperature": ["233"]}}
    builds.store_upload("orca_live", io.BytesIO(_orca_live_zip_of(b1, edit=edit, drop=(TGO.sv08("1.0"),))),
                        device_id="a", user_id=OUSER)
    r = builds.run_build(orca_cfg, now=TG.NOW + 1)
    m = builds.manifest(r["stamp"])
    assert m["orca_inapp"] == {} and m["orca_deleted"] == []


def test_install_report_trees_are_checked(orca_cfg):
    from filament_kit.profiles import errors
    TB.synced(orca_cfg)
    b1 = builds.run_build(orca_cfg, now=TG.NOW)["stamp"]
    for bad in (["orca"], ["base", "cura"], "base", []):
        with pytest.raises(errors.ProfileError) as e:
            builds.record_installed(b1, "a", bad)
        assert e.value.status == 400
