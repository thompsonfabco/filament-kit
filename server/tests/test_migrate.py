"""filament-kit migrate-ops: a fixture filament-ops bundle into a kit install (spec 4.5, plan Task 8)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import time
from pathlib import Path

import pytest

from filament_kit import cli, config, library, migrate
from filament_kit.profiles import generate, lines as lines_mod
from filament_kit.spoolman import Spoolman

LIB = Path(__file__).parent / "data" / "library"
H2D = "Bambu Lab H2D"
V3 = ["Direct Drive Standard", "Direct Drive High Flow", "Direct Drive E3D High Flow"]

LINES_PY = '''"""ops lines (fixture)"""

G = "Generic"

LINES = [
    ("SUNLU PLA+ 2.0", "SUNLU", [1, 2], "SUNLU PLA+ 2.0", "Bambu PLA Tough+", ["base:SUNLU PLA 2"]),
    ("SUNLU High Speed PLA+ 2.0", "SUNLU", [5], "SUNLU PLA+ 2.0", "Bambu PLA Tough+", []),
    ("DEEPLEE Silk PLA", "DEEPLEE", [3], G, "Generic PLA Silk", []),
    ("Bambu Lab PETG HF", "Bambu Lab", [4], "Bambu PETG HF", "Bambu PETG HF|0.4", []),
]

ORCA_TYPE = {"TPU-GF": "TPU"}
'''

FILAMENTS = [  # id, vendor, name, material
    (1, "SUNLU", "PLA+ 2.0 Black", "PLA"),
    (2, "SUNLU", "PLA+ 2.0 White", "PLA"),
    (3, "DEEPLEE", "Silk PLA Gold", "PLA"),
    (4, "Bambu Lab", "PETG HF Black", "PETG"),
    (5, "SUNLU", "High Speed PLA+ 2.0 Grey", "PLA"),
]
SPOOLS = [(1, 1), (2, 1), (3, 2), (4, 3), (5, 4), (6, 5)]


def _bs(name, fid, flow="0.98", notes="One profile."):
    return {"name": name, "inherits": "", "from": "User", "filament_id": fid, "version": "2.8.0.6",
            "filament_extruder_variant": list(V3), "filament_flow_ratio": [flow, flow, flow],
            "filament_max_volumetric_speed": ["25", "60", "21"], "nozzle_temperature": ["220", "240", "220"],
            "nozzle_temperature_initial_layer": ["220", "240", "220"], "hot_plate_temp": ["55"],
            "textured_plate_temp": ["55"], "slow_down_layer_time": ["4"], "filament_notes": notes,
            "compatible_printers": [f"{H2D} 0.4 nozzle"]}


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    path.with_suffix(".info").write_text("sync_info = \nsetting_id = PS123\n", encoding="utf-8")


def make_bundle(root: Path, *, secrets: bool = True, revision: str | None = migrate.SPOOLMAN_REVISION) -> Path:
    b = root / "ops-bundle"
    b.mkdir(parents=True)
    (b / "lines.py").write_text(LINES_PY, encoding="utf-8")
    (b / "server.json").write_text(json.dumps({"public_url": "https://mcp.example.test/filament", "host": "127.0.0.1",
                                               "port": 8101, "behind_proxy": True, "lan": ["192.168.1.0/24"]}))
    (b / "regen_config.json").write_text(json.dumps({"role": "vm", "data": "/srv/filament"}))
    (b / "instructions.txt").write_text("ops instructions\n")
    (b / "filament_orders.json").write_text(json.dumps({"updated": "x", "items": [{"order": "1", "asin": "B0"}]}))
    db = sqlite3.connect(b / "spoolman.db")
    db.executescript("create table vendor (id integer primary key, name text, empty_spool_weight real);"
                     "create table filament (id integer primary key, name text, vendor_id integer, material text);"
                     "create table spool (id integer primary key, filament_id integer);"
                     "create table filament_field (filament_id integer, key text, value text);")
    if revision is not None:
        db.executescript(f"create table alembic_version (version_num text not null);"
                         f"insert into alembic_version values ('{revision}');")
    vendors = {v: i + 1 for i, v in enumerate(dict.fromkeys(f[1] for f in FILAMENTS))}
    db.executemany("insert into vendor (id, name) values (?, ?)", [(i, v) for v, i in vendors.items()])
    db.executemany("insert into filament values (?, ?, ?, ?)", [(i, n, vendors[v], m) for i, v, n, m in FILAMENTS])
    db.executemany("insert into spool values (?, ?)", SPOOLS)
    db.execute("insert into filament_field values (1, 'nozzle_range', '\"205-245\"')")
    db.commit()
    db.close()
    inst, live = b / "presets" / "installed", b / "presets" / "live"
    sunlu = f"SUNLU PLA+ 2.0 @{H2D} 0.4 nozzle"
    _write(inst / "bs" / "base" / f"{sunlu}.json", _bs(sunlu, "Pabc1234"))
    # the owner calibrated the flow in the app after the last install and wrote a note
    _write(live / "bs" / "base" / f"{sunlu}.json",
           _bs(sunlu, "Pabc1234", flow="0.95",
               notes="One profile.\nYour notes (kept when the profiles are regenerated):\ndry 8 h first"))
    for nz, fid in (("0.4", "Pbbb0002"), ("0.6", "Pbbb0002"), ("0.8", "Pbbb0003")):
        n = f"Bambu Lab PETG HF @{H2D} {nz} nozzle"
        for tree in (inst, live):
            _write(tree / "bs" / "base" / f"{n}.json", _bs(n, fid))
    n = f"DEEPLEE Silk PLA @{H2D} 0.4 nozzle"
    for tree in (inst, live):
        _write(tree / "bs" / "base" / f"{n}.json", _bs(n, "Pdee0001"))
    sv = {"name": "SUNLU PLA+ 2.0 @SV08 MAX 0.4", "inherits": "SUNLU PLA+ 2.0 @System", "from": "User",
          "filament_extruder_variant": ["Direct Drive Standard"], "filament_flow_ratio": ["0.965"],
          "pressure_advance": ["0.035"], "enable_pressure_advance": ["1"], "filament_max_volumetric_speed": ["45"],
          "nozzle_temperature": ["240"], "compatible_printers": ["Sovol SV08 MAX"], "version": "2.4.0.16"}
    oh = {"name": "SUNLU PLA+ 2.0 @H2D 0.4", "inherits": "Bambu PLA Tough+ @BBL H2D", "from": "User",
          "filament_extruder_variant": list(V3), "filament_flow_ratio": ["0.98", "0.97", "0.96"],
          "nozzle_temperature": ["220", "260", "220"], "version": "2.8.0.16",
          "compatible_printers": [f"{H2D} 0.4 nozzle"]}
    for tree in (inst, live):
        _write(tree / "orca" / f"{sv['name']}.json", sv)
        _write(tree / "orca" / f"{oh['name']}.json", oh)
    _write(live / "orca" / "My own preset @SV08 MAX 0.4.json", {"name": "My own preset @SV08 MAX 0.4",
                                                                 "filament_flow_ratio": ["0.9"]})
    (inst / "deleted.json").write_text(json.dumps({"orca": ["deeplee silk pla @sv08 max 1.0"], "bs": []}))
    (inst / "BUILD.json").write_text(json.dumps({"stamp": "20261102-031005"}))
    if secrets:
        (b / "secrets").mkdir()
        (b / "secrets" / "web_passphrase").write_text("00ff" * 8 + " " + "ab" * 32 + "\n")
        (b / "secrets" / "oauth.json").write_text(json.dumps(
            {"clients": {"c1": {"client_id": "c1"}}, "codes": {}, "access": {}, "refresh": {}, "used": {},
             "sessions": {}}))
        (b / "secrets" / "anthropic_key").write_text("sk-test-not-real\n")
    (b / "MANIFEST.json").write_text(json.dumps(
        {"format": 1, "created": 1793647251, "host": "spoolman", "secrets": secrets,
         "spoolman": {"version": "0.27.0", "spool": len(SPOOLS), "filament": len(FILAMENTS), "vendor": 3},
         "orders_file": "/var/lib/filament-mcp/filament_orders.json", "missing": [], "presets": {}}))
    return b


def tar_bundle(b: Path) -> Path:
    out = b.parent / "ops-bundle.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(b, arcname="ops-bundle")
    return out


@pytest.fixture
def env(tmp_path, monkeypatch, spoolman_url, spoolman_fake_store):
    for var, sub in (("FK_ETC", "etc"), ("FK_STATE", "state"), ("FK_BACKUPS", "backups"),
                     ("FK_SPOOLMAN_DATA", "spoolman")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    (tmp_path / "etc" / "config.json").write_text(json.dumps({"spoolman_url": spoolman_url}))
    sm = Spoolman(spoolman_url)
    vendors = {}
    for i, v, n, m in FILAMENTS:
        if v not in vendors:
            vendors[v] = sm.post("vendor", {"name": v})["id"]
        assert sm.post("filament", {"name": n, "vendor_id": vendors[v], "material": m, "density": 1.24,
                                    "diameter": 1.75})["id"] == i
    return tmp_path


@pytest.fixture
def lib():
    idx = json.loads((LIB / "index.json").read_text(encoding="utf-8"))
    return library.Library(LIB, idx, "bundled", [])


def snapshot(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def kit_files(env: Path) -> dict[str, str]:
    return {k: v for k, v in snapshot(env).items() if not k.startswith(("bundle", "ops-bundle"))}


def run(bundle, lib, *, apply=False, **kw):
    lines_out: list[str] = []
    code = migrate.run(bundle, apply=apply, library=lib, out=lines_out.append, **kw)
    return code, "\n".join(lines_out)


# ---------- dry run, idempotence ----------

def test_dry_run_writes_nothing(env, lib):
    b = make_bundle(env / "bundle")
    before = kit_files(env)
    code, text = run(b, lib)
    assert code == 0, text
    assert kit_files(env) == before
    assert "dry run" in text.lower() and "would" in text
    for step in ("spoolman", "lines", "presets", "web", "config"):
        assert f"[{step}]" in text


def test_dry_run_on_a_tar_bundle_writes_nothing_and_cleans_up(env, lib, tmp_path):
    t = tar_bundle(make_bundle(env / "bundle"))
    before = kit_files(env)
    code, text = run(t, lib)
    assert code == 0, text
    assert kit_files(env) == before


def test_second_apply_changes_nothing(env, lib, spoolman_fake_store):
    b = make_bundle(env / "bundle")
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    first = kit_files(env)
    fake = json.dumps(spoolman_fake_store, sort_keys=True, default=str)
    time.sleep(1.1)                     # a later second: nothing (not even the step record) is rewritten
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    assert kit_files(env) == first
    assert json.dumps(spoolman_fake_store, sort_keys=True, default=str) == fake
    assert "already" in text or "unchanged" in text


# ---------- step 1: Spoolman ----------

def test_spoolman_db_copied_and_counted(env, lib):
    b = make_bundle(env / "bundle")
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    db = sqlite3.connect(env / "spoolman" / "spoolman.db")
    assert db.execute("select count(*) from spool").fetchone()[0] == len(SPOOLS)
    assert db.execute("select count(*) from filament").fetchone()[0] == len(FILAMENTS)
    assert "6 spools, 5 filaments" in text


def test_spoolman_with_data_is_not_replaced_without_the_flag(env, lib):
    b = make_bundle(env / "bundle")
    other = sqlite3.connect(env / "spoolman" / "spoolman.db")
    other.executescript("create table spool (id integer primary key); create table filament (id integer primary key);"
                        "insert into spool values (99);")
    other.commit()
    other.close()
    before = (env / "spoolman" / "spoolman.db").read_bytes()
    code, text = run(b, lib, apply=True)
    assert code == 1
    assert "already holds 1 spool" in text and "--replace-spoolman" in text
    assert (env / "spoolman" / "spoolman.db").read_bytes() == before
    code, text = run(b, lib, apply=True, replace_spoolman=True)
    assert code == 0, text
    backups = list((env / "backups").rglob("spoolman.db"))
    assert len(backups) == 1 and backups[0].read_bytes() == before


def test_spoolman_version_mismatch_is_refused(env, lib):
    b = make_bundle(env / "bundle")
    m = json.loads((b / "MANIFEST.json").read_text())
    m["spoolman"]["version"] = "0.22.1"
    (b / "MANIFEST.json").write_text(json.dumps(m))
    code, text = run(b, lib, apply=True)
    assert code == 1 and "0.22.1" in text
    assert not (env / "spoolman" / "spoolman.db").exists()


# ---------- step 2: lines ----------

def test_lines_from_lines_py_adopt_the_bs_filament_ids(env, lib):
    b = make_bundle(env / "bundle")
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    ls = lines_mod.load()
    assert len(ls) == 4
    sunlu = ls[lines_mod.line_id_for("SUNLU", "PLA+ 2.0")]
    assert (sunlu.vendor, sunlu.product, sunlu.material) == ("SUNLU", "PLA+ 2.0", "PLA")
    assert (sunlu.bambu_parent, sunlu.parent_source) == ("Bambu PLA Tough+", "user")
    assert (sunlu.orca_parent, sunlu.orca_parent_source) == ("SUNLU PLA+ 2.0", "user")
    assert sunlu.filament_id == "Pabc1234" and sunlu.filaments == [1, 2]
    petg = ls[lines_mod.line_id_for("Bambu Lab", "PETG HF")]
    assert petg.bambu_parent == "Bambu PETG HF"                  # the "|0.4" hint is dropped
    assert petg.filament_id == "Pbbb0002"                         # the most common id of its presets
    assert "Pbbb0003" in text                                     # the odd one is reported
    hs = ls[lines_mod.line_id_for("SUNLU", "High Speed PLA+ 2.0")]
    assert hs.filaments == [5] and hs.filament_id.startswith("P")  # no BS preset: a new id


def test_lines_keep_an_existing_line_created_date(env, lib):
    b = make_bundle(env / "bundle")
    with lines_mod.transaction() as ls:
        lines_mod.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=lib, store=None, used_fids=set())
        ls[lines_mod.line_id_for("SUNLU", "PLA+ 2.0")].created = "2026-01-01T00:00:00Z"
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    line = lines_mod.load()[lines_mod.line_id_for("SUNLU", "PLA+ 2.0")]
    assert line.created == "2026-01-01T00:00:00Z" and line.filament_id == "Pabc1234"


def test_extra_line_set_where_the_kit_would_group_elsewhere(env, lib, spoolman_fake_store):
    b = make_bundle(env / "bundle")
    code, text = run(b, lib)
    assert "would set extra.line on 2 filaments" in text
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    extra = {i: f.get("extra", {}).get("line") for i, f in spoolman_fake_store["filaments"].items()}
    assert json.loads(extra[3]) == "Silk PLA"                      # DEEPLEE: no library entry
    assert json.loads(extra[5]) == "High Speed PLA+ 2.0"           # the library would say PLA+ 2.0... or the name
    assert extra[1] is None and extra[2] is None and extra[4] is None


def test_grouping_after_migration_keeps_every_filament_in_its_ops_line(env, lib, spoolman_url):
    b = make_bundle(env / "bundle")
    assert run(b, lib, apply=True)[0] == 0
    fils = Spoolman(spoolman_url).get("filament")
    ls = lines_mod.load()
    groups = lines_mod.group(fils, ls, library=lib, store=None, used_fids=set())
    assert len(ls) == 4                                           # no twin lines
    assert sorted(i for fs in groups.values() for i in (f["id"] for f in fs)) == [1, 2, 3, 4, 5]
    assert {f["id"] for f in groups[lines_mod.line_id_for("DEEPLEE", "Silk PLA")]} == {3}


# ---------- step 3: presets (owner edits) ----------

def test_calibrated_keys_carried_as_owner_edits(env, lib):
    b = make_bundle(env / "bundle")
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    oe = json.loads((env / "state" / "profiles" / "owner-edits.json").read_text())
    sunlu = oe["inapp"][f"SUNLU PLA+ 2.0 @{H2D} 0.4 nozzle"]
    assert sunlu["filament_flow_ratio"] == ["0.95", "0.95", "0.95"]           # the live (calibrated) value
    assert sunlu["filament_max_volumetric_speed"] == ["25", "60", "21"]
    assert sunlu["nozzle_temperature"] == ["220", "240", "220"]
    assert sunlu["hot_plate_temp"] == ["55"] and sunlu["textured_plate_temp"] == ["55"]
    assert "slow_down_layer_time" not in sunlu                                 # not calibrated, not edited
    assert oe["notes"][f"SUNLU PLA+ 2.0 @{H2D} 0.4 nozzle"] == ["dry 8 h first"]
    sv = oe["orca_inapp"]["SUNLU PLA+ 2.0 @SV08 MAX 0.4"]
    assert sv == {"filament_flow_ratio": ["0.965"], "pressure_advance": ["0.035"], "enable_pressure_advance": ["1"],
                  "filament_max_volumetric_speed": ["45"], "nozzle_temperature": ["240"]}
    assert oe["orca_inapp"]["SUNLU PLA+ 2.0 @H2D 0.4"]["filament_flow_ratio"] == ["0.98", "0.97", "0.96"]
    assert "My own preset @SV08 MAX 0.4" not in oe["orca_inapp"]               # not an ops line's preset
    deleted = json.loads((env / "state" / "profiles" / "deleted.json").read_text())
    assert deleted["orca_deleted_before"] == ["deeplee silk pla @sv08 max 1.0"]
    assert deleted["deleted_before"] == []


def test_owner_edits_not_seeded_once_the_kit_has_built(env, lib):
    b = make_bundle(env / "bundle")
    prof = env / "state" / "profiles"
    prof.mkdir(parents=True)
    (prof / "current.json").write_text(json.dumps({"stamp": "20261103-010101"}))
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    assert not (prof / "owner-edits.json").exists()
    assert "not seeded" in text


def test_carried_variant_values_fit_the_kit_variants_by_name():
    cfg = {"name": "X @H2D 0.4", "filament_flow_ratio": ["0.98", "0.97", "0.96"], "hot_plate_temp": ["55"]}
    mine = dict(cfg)
    log: list[str] = []
    generate._fit_variants(cfg, mine, ["Direct Drive Standard", "Direct Drive High Flow"], V3, log)
    assert cfg["filament_flow_ratio"] == ["0.98", "0.97"] and mine["filament_flow_ratio"] == ["0.98", "0.97"]
    assert cfg["hot_plate_temp"] == ["55"]
    assert log and "3 to 2" in log[0]
    # no live variant names that line up with the value: left as the owner wrote it (an in-app ["2", "nil"])
    cfg = {"nozzle_temperature": ["220", "260", "230"], "filament_wipe_distance": ["2", "nil"]}
    generate._fit_variants(cfg, dict(cfg), ["A", "B"], None, [])
    generate._fit_variants(cfg, dict(cfg), ["Direct Drive Standard"], ["Direct Drive Standard"], [])
    assert cfg == {"nozzle_temperature": ["220", "260", "230"], "filament_wipe_distance": ["2", "nil"]}
    # a variant the old preset did not have takes the first value
    cfg = {"nozzle_temperature": ["220", "260", "230"]}
    generate._fit_variants(cfg, dict(cfg), ["Direct Drive High Flow", "Bowden"], V3, [])
    assert cfg["nozzle_temperature"] == ["260", "220"]


# ---------- step 4: web ----------

def test_web_secrets_imported_with_modes(env, lib):
    b = make_bundle(env / "bundle")
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    oauth = env / "state" / "web" / "oauth.json"
    assert json.loads(oauth.read_text())["clients"] == {"c1": {"client_id": "c1"}}
    assert (env / "etc" / "web_passphrase").read_text() == (b / "secrets" / "web_passphrase").read_text()
    assert (env / "etc" / "anthropic_key").read_text().strip() == "sk-test-not-real"
    if os.name != "nt":
        assert oauth.stat().st_mode & 0o777 == 0o600
        assert (env / "etc" / "web_passphrase").stat().st_mode & 0o777 == 0o640
    assert "sk-test" not in text and "ab" * 32 not in text                      # never printed


def test_web_step_skipped_for_a_no_secrets_bundle(env, lib):
    b = make_bundle(env / "bundle", secrets=False)
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    assert not (env / "state" / "web" / "oauth.json").exists()
    assert "no secrets" in text


def test_web_secrets_never_overwrite_newer_kit_state(env, lib):
    b = make_bundle(env / "bundle")
    oauth = env / "state" / "web" / "oauth.json"
    oauth.parent.mkdir(parents=True)
    oauth.write_text('{"clients": {"newer": {}}}')
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    assert json.loads(oauth.read_text()) == {"clients": {"newer": {}}}
    assert "kept" in text


def test_ops_oauth_json_loads_in_the_web_store(env, lib):
    auth = pytest.importorskip("filament_kit.web.auth")
    b = make_bundle(env / "bundle")
    assert run(b, lib, apply=True)[0] == 0
    store = auth.Store(env / "state" / "web" / "oauth.json")
    assert "c1" in store.d["clients"]


# ---------- step 5: config ----------

def test_config_gets_the_owner_values(env, lib):
    b = make_bundle(env / "bundle")
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    cfg = config.load()
    assert cfg["web"]["public_url"] == "https://mcp.example.test/filament"
    assert cfg["web"]["lan"] == ["192.168.1.0/24"] and cfg["web"]["port"] == 8101
    assert cfg["remote"]["hostname"] == "mcp.example.test"
    assert cfg["remote"]["acme_window"] == "03:10 America/New_York"
    assert cfg["slicer_printers"] == [{"name": "Sovol SV08 MAX", "slicer": "orca", "nozzles": ["0.4", "0.6", "1.0"],
                                       "label": "SV08 MAX", "compatible_printers": {
                                           "0.4": "Sovol SV08 MAX", "0.6": "Sovol SV08 MAX 0.6",
                                           "1.0": "Sovol SV08 MAX 1.0"}}]
    assert cfg["presets_orca"] is True and cfg["presets_orca_nozzles"] == ["0.4", "0.6", "0.8"]
    assert cfg["placement"] == {"pla_location": "Rack 1", "box_prefix": "Storage Cabinet A - Cereal Box ",
                                "box_count": 50, "overflow": "Overflow bags", "sealed_location": "Sealed stock"}
    assert cfg["locations"][0] == "Sealed stock" and "Upper storage (unverified)" in cfg["locations"]
    assert cfg["intake"]["tare_hints"]["SUNLU"] == 213
    assert cfg["tag_sources"] == [{"name": "printer", "url": migrate.OPS_LASTTAG}]
    assert cfg["station"]["url"] == migrate.OPS_STATION
    assert cfg["slot_service"] == {"state_url": "http://127.0.0.1:8105/api/state",
                                   "set_url": "http://127.0.0.1:8104/set-slot",
                                   "token_file": str(env / "etc" / "h2d_token")}
    assert cfg["orders"]["file"] == str(env / "state" / "filament_orders.json")
    assert json.loads((env / "state" / "filament_orders.json").read_text())["items"][0]["asin"] == "B0"
    assert cfg["spoolman_url"].startswith("http://127.0.0.1:")                    # untouched
    assert list((env / "backups").rglob("config.json"))                            # backed up first


def test_config_keeps_a_value_the_owner_set(env, lib):
    b = make_bundle(env / "bundle")
    cfg = json.loads((env / "etc" / "config.json").read_text())
    cfg["placement"] = {"box_count": 12}
    (env / "etc" / "config.json").write_text(json.dumps(cfg))
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    pl = config.load()["placement"]
    assert pl["box_count"] == 12 and pl["box_prefix"] == "Storage Cabinet A - Cereal Box "
    assert "placement.box_count" in text and "kept" in text


# ---------- CLI ----------

def test_cli_dry_run(env, lib, monkeypatch, capsys):
    b = make_bundle(env / "bundle")
    monkeypatch.setattr(migrate.library_mod, "load", lambda: lib)
    before = kit_files(env)
    assert cli.main(["migrate-ops", str(b)]) == 0
    assert "--apply" in capsys.readouterr().out
    assert kit_files(env) == before


def test_cli_apply_needs_root(env, monkeypatch, capsys):
    b = make_bundle(env / "bundle")
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.main(["migrate-ops", str(b), "--apply"]) == 1
    assert "root" in capsys.readouterr().err


# ---------- tools/export_ops.sh (Linux: the ops VM) ----------

@pytest.mark.skipif(os.name == "nt", reason="the export runs on the Linux VM (bash + python3)")
@pytest.mark.parametrize("secrets", [False, True])
def test_export_script_bundle_opens_and_leaves_secrets_out(tmp_path, secrets):
    import subprocess
    src = make_bundle(tmp_path / "src")
    etc, state, opt, data = (tmp_path / n for n in ("etc", "state", "opt", "data"))
    for d in (etc, state / "presets", opt, data):
        d.mkdir(parents=True)
    (state / "presets" / "lines.py").write_text(LINES_PY)
    (opt / "regen_config.json").write_text(json.dumps({"data": str(data), "state": str(state / "presets")}))
    (etc / "server.json").write_text((src / "server.json").read_text())
    (etc / "passphrase").write_text((src / "secrets" / "web_passphrase").read_text())
    (etc / "anthropic_key").write_text("sk-test-not-real\n")
    (etc / "h2d_token").write_text("never-exported\n")
    (state / "oauth.json").write_text((src / "secrets" / "oauth.json").read_text())
    (state / "filament_orders.json").write_text((src / "filament_orders.json").read_text())
    import shutil
    shutil.copytree(src / "presets" / "installed", data / "installed")
    shutil.copytree(src / "presets" / "live", data / "live")
    out = tmp_path / "bundle.tar.gz"
    script = Path(__file__).resolve().parents[2] / "tools" / "export_ops.sh"
    env = {**os.environ, "OPS_ETC": str(etc), "OPS_STATE": str(state), "OPS_OPT": str(opt), "OPS_DATA": str(data),
           "OPS_EXPORT_NOT_ROOT": "1"}
    before = snapshot(tmp_path)
    args = ["bash", str(script)] + ([] if secrets else ["--no-secrets"]) + ["--spoolman-db", str(src / "spoolman.db"),
                                                                            str(out)]
    r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    after = snapshot(tmp_path)
    after.pop("bundle.tar.gz")
    assert after == before                                       # read-only apart from the bundle itself
    assert out.stat().st_mode & 0o777 == 0o600
    with tarfile.open(out) as tar:
        names = set(tar.getnames())
        blob = b"".join(tar.extractfile(m).read() for m in tar.getmembers() if m.isfile())
    assert b"never-exported" not in blob                         # the H2D token is never exported
    assert ("ops-bundle/secrets/oauth.json" in names) is secrets
    assert (b"sk-test-not-real" in blob) is secrets
    assert "ops-bundle/presets/live/bs/base/SUNLU PLA+ 2.0 @Bambu Lab H2D 0.4 nozzle.json" in names
    with migrate.open_bundle(out) as b:
        assert b.manifest["secrets"] is secrets
        assert b.counts() == {"spool": len(SPOOLS), "filament": len(FILAMENTS), "vendor": 3}
        assert len(b.lines()) == 4


def test_h2d_listed_model_only_so_its_presets_are_built(env, lib):
    from filament_kit.bridge import models, registry
    b = make_bundle(env / "bundle")
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    ps = registry.load()
    assert list(ps) == ["ops-h2d"]
    p = ps["ops-h2d"]
    assert models.printer_preset_name(p.model) == "Bambu Lab H2D"
    assert (p.ip, p.access_code, p.configured) == ("", "", False)        # never connected to
    registry.upsert(registry.Printer(serial="0948AB", name="H2D", model="O1D"))
    registry.remove("ops-h2d")
    code, text = run(b, lib, apply=True)
    assert list(registry.load()) == ["0948AB"]                              # one H2D is enough


def test_a_filament_the_kit_grouped_elsewhere_moves_to_its_ops_line(env, lib):
    b = make_bundle(env / "bundle")
    with lines_mod.transaction() as ls:
        other = lines_mod.ensure(ls, "SUNLU", "PLA+ 2.0 Black", "PLA", bambu_parent=None, library=lib, store=None,
                                 used_fids=set())
        other.filaments = [1]
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    ls = lines_mod.load()
    assert ls[lines_mod.line_id_for("SUNLU", "PLA+ 2.0")].filaments == [1, 2]
    assert ls[other.line_id].filaments == []                     # lines are never deleted, only emptied
    assert f"filaments [1] moved from {other.line_id}" in text


# ---------- fix round 1: version guard, failures ----------

def test_spoolman_version_comes_from_the_database_when_the_manifest_has_none(env, lib):
    b = make_bundle(env / "bundle")
    m = json.loads((b / "MANIFEST.json").read_text())
    m["spoolman"]["version"] = None                         # exported with Spoolman stopped
    (b / "MANIFEST.json").write_text(json.dumps(m))
    code, text = run(b, lib, apply=True)
    assert code == 0, text
    assert (env / "spoolman" / "spoolman.db").exists()


def test_spoolman_other_schema_revision_is_refused(env, lib):
    b = make_bundle(env / "bundle", revision="0123456789ab")
    m = json.loads((b / "MANIFEST.json").read_text())
    m["spoolman"]["version"] = None
    (b / "MANIFEST.json").write_text(json.dumps(m))
    code, text = run(b, lib, apply=True)
    assert code == 1 and "0123456789ab" in text
    assert not (env / "spoolman" / "spoolman.db").exists()


def test_spoolman_without_a_revision_needs_the_override(env, lib):
    b = make_bundle(env / "bundle", revision=None)
    code, text = run(b, lib, apply=True)
    assert code == 1 and "--allow-unknown-spoolman" in text
    assert not (env / "spoolman" / "spoolman.db").exists()
    code, text = run(b, lib, apply=True, allow_unknown_spoolman=True)
    assert code == 0, text
    assert (env / "spoolman" / "spoolman.db").exists()


def test_manifest_and_database_counts_must_agree(env, lib):
    b = make_bundle(env / "bundle")
    m = json.loads((b / "MANIFEST.json").read_text())
    m["spoolman"]["spool"] = 999
    (b / "MANIFEST.json").write_text(json.dumps(m))
    code, text = run(b, lib, apply=True)
    assert code == 1 and "999" in text and "export again" in text
    assert not (env / "spoolman" / "spoolman.db").exists()


def test_one_failing_step_does_not_stop_the_others(env, lib):
    b = make_bundle(env / "bundle", revision="0123456789ab")
    code, text = run(b, lib, apply=True)
    assert code == 1 and "[spoolman] ERROR" in text
    assert len(lines_mod.load()) == 4                       # lines, presets, web and config still ran
    assert (env / "state" / "profiles" / "owner-edits.json").exists()
    assert (env / "state" / "web" / "oauth.json").exists()
    assert config.load()["presets_orca"] is True
    assert "step(s) failed" in text


class _Units:
    """systemctl stand-in: every kit unit is active; records stop/start."""

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def method(self):
        def systemctl(ctx, *args):
            self.calls.append(args)
            return 0
        return systemctl

    def started(self) -> list[str]:
        return [a[1] for a in self.calls if a[0] == "start"]


@pytest.fixture
def units(monkeypatch):
    u = _Units()
    monkeypatch.setattr(migrate, "_no_systemd", lambda: False)
    monkeypatch.setattr(migrate._Ctx, "systemctl", u.method())
    monkeypatch.setattr(migrate, "_wait_spoolman", lambda sm, seconds=120: True)
    return u


def _broken_copy(b, dest):
    Path(dest).write_bytes(b"half a database")
    raise OSError("disk full")


def test_failed_copy_puts_the_previous_database_back_and_restarts(env, lib, units, monkeypatch):
    b = make_bundle(env / "bundle")
    prev = env / "spoolman" / "spoolman.db"
    sqlite3.connect(prev).close()
    before = prev.read_bytes()
    monkeypatch.setattr(migrate, "_copy_db", _broken_copy)
    code, text = run(b, lib, apply=True)
    assert code == 1 and "put back" in text
    assert prev.read_bytes() == before
    assert not list((env / "spoolman").glob("*.tmp"))
    assert "spoolman" in units.started()                     # on the database it had before
    assert ("stop", "spoolman") in units.calls


def test_restored_database_files_go_back_to_spoolman(env, lib, units, monkeypatch):
    b = make_bundle(env / "bundle")
    prev = env / "spoolman" / "spoolman.db"
    sqlite3.connect(prev).close()
    (env / "spoolman" / "spoolman.db-wal").write_bytes(b"wal")
    monkeypatch.setattr(migrate, "_db_counts", lambda p: (0, 0))      # no sqlite open: it would drop the stray -wal
    owners: dict[str, tuple] = {}
    monkeypatch.setattr(migrate, "_chown", lambda p, u, g: owners.__setitem__(Path(p).name, (u, g)))
    monkeypatch.setattr(migrate, "_copy_db", _broken_copy)
    code, text = run(b, lib, apply=True)
    assert code == 1 and "put back" in text
    # the backup copies belong to root; Spoolman (user spoolman) must own what it starts on again
    assert owners.get("spoolman.db") == ("spoolman", "spoolman")
    assert owners.get("spoolman.db-wal") == ("spoolman", "spoolman")


def test_failed_copy_with_no_previous_database_leaves_spoolman_stopped(env, lib, units, monkeypatch):
    b = make_bundle(env / "bundle")
    monkeypatch.setattr(migrate, "_copy_db", _broken_copy)
    code, text = run(b, lib, apply=True)
    assert code == 1 and "left stopped" in text and "sudo systemctl start spoolman" in text
    assert not (env / "spoolman" / "spoolman.db").exists()
    assert "spoolman" not in units.started()
    assert {"filament-kit", "filament-kit-web"} <= set(units.started())   # the rest comes back


def test_count_mismatch_after_the_copy_is_a_failure_too(env, lib, units, monkeypatch):
    b = make_bundle(env / "bundle")
    real = migrate._db_counts
    monkeypatch.setattr(migrate, "_db_counts", lambda p: (0, 0) if Path(p).exists() else real(p))
    code, text = run(b, lib, apply=True)
    assert code == 1 and "does not hold the bundle's counts" in text
    assert "spoolman" not in units.started()


def test_cli_passes_the_spoolman_flags(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(migrate, "run", lambda bundle, **kw: seen.update(kw) or 0)
    assert cli.main(["migrate-ops", "x.tar.gz", "--apply", "--replace-spoolman", "--allow-unknown-spoolman"]) == 0
    assert seen == {"apply": True, "replace_spoolman": True, "allow_unknown_spoolman": True}


@pytest.mark.skipif(os.name == "nt", reason="the export runs on the Linux VM (bash + python3)")
def test_export_reads_a_wal_database_left_by_a_killed_spoolman(tmp_path):
    import signal
    import subprocess
    src = make_bundle(tmp_path / "src")
    data = tmp_path / "db"
    data.mkdir()
    db = data / "spoolman.db"
    child = subprocess.Popen([sys.executable, "-c", f"""
import sqlite3, shutil, time
shutil.copyfile({str(src / 'spoolman.db')!r}, {str(db)!r})
c = sqlite3.connect({str(db)!r}); c.execute("pragma journal_mode=wal"); c.execute("pragma wal_autocheckpoint=0")
c.executemany("insert into spool values (?, 1)", [(i,) for i in range(100, 140)]); c.commit()
print("ready", flush=True); time.sleep(60)
"""], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "ready"
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    assert (data / "spoolman.db-wal").stat().st_size > 0
    before = snapshot(data)
    for d in ("etc", "state", "opt", "srv"):
        (tmp_path / d).mkdir()
    out = tmp_path / "b.tar.gz"
    env = {**os.environ, "OPS_ETC": str(tmp_path / "etc"), "OPS_STATE": str(tmp_path / "state"),
           "OPS_OPT": str(tmp_path / "opt"), "OPS_DATA": str(tmp_path / "srv"), "OPS_EXPORT_NOT_ROOT": "1"}
    script = Path(__file__).resolve().parents[2] / "tools" / "export_ops.sh"
    # with --spoolman-db there is no unit to check, so a WAL database needs --force (the owner says it is stopped)
    r = subprocess.run(["bash", str(script), "--no-secrets", "--spoolman-db", str(db), str(out)], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "--force" in r.stderr and not out.exists()
    assert snapshot(data) == before
    r = subprocess.run(["bash", str(script), "--no-secrets", "--force", "--spoolman-db", str(db), str(out)], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert snapshot(data) == before                            # db, -wal and -shm untouched
    with migrate.open_bundle(out) as b:
        assert b.counts()["spool"] == len(SPOOLS) + 40         # the frames in the -wal are in the bundle
        assert b.manifest["spoolman"]["spool"] == len(SPOOLS) + 40
        assert b.revision() == migrate.SPOOLMAN_REVISION


def test_variant_source_never_takes_a_stale_live_preset_over_the_installed_one():
    live, inst = {"filament_extruder_variant": V3}, {"filament_extruder_variant": V3[:2]}
    assert generate._variant_source(live, inst, True) == V3
    assert generate._variant_source(live, inst, False) == V3[:2]          # Ruling Z: stale live not used
    assert generate._variant_source(live, None, False) == V3              # first install after migrate-ops
    assert generate._variant_source(None, None, True) is None


# ---------- C-M6: the kit's Spoolman fields, once, right after the database copy ----------

def test_apply_ensures_the_kits_fields_once_after_the_database_copy(env, lib, monkeypatch):
    from filament_kit import spoolman as spoolman_mod
    order = []
    real_ensure = spoolman_mod.Spoolman.ensure_fields
    real_copy = migrate._copy_db
    monkeypatch.setattr(spoolman_mod.Spoolman, "ensure_fields",
                        lambda self: order.append("ensure_fields") or real_ensure(self))
    monkeypatch.setattr(migrate, "_copy_db", lambda b, tmp: order.append("copy") or real_copy(b, tmp))
    # not only when the lines step has extra.line values to set (the fields are the kit's, whatever the lines)
    monkeypatch.setattr(migrate, "step_lines", lambda b, ctx: None)
    code, text = run(make_bundle(env / "bundle"), lib, apply=True, replace_spoolman=True)
    assert code == 0, text
    assert order == ["copy", "ensure_fields"]
    code, text = run(make_bundle(env / "bundle2"), lib)              # a dry run never writes Spoolman
    assert order == ["copy", "ensure_fields"]
