"""profiles.preset_for for Klipper printers: the owner's Orca preset for a filament, printer and nozzle."""
import json
import os

import pytest

from filament_kit import config, profiles
from filament_kit.profiles import builds

import test_generate as TG
from test_builds import SUNLU, env, synced  # noqa: F401  (env is a fixture)

ORCA_NAME = "SUNLU PLA+ 2.0 @SV08 MAX 0.4 nozzle"


def _add_rows(stamp, rows):
    path = config.paths().state / "profiles" / "builds" / stamp / "BUILD.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    m["presets"].extend(rows)
    path.write_text(json.dumps(m), encoding="utf-8")
    cur = config.paths().state / "profiles" / "current.json"
    st = cur.stat()
    os.utime(cur, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


def _row(printer="Sovol SV08 MAX", nozzle="0.4", name=ORCA_NAME, **kw):
    return {"target": "orca", "name": name, "line_id": "sunlu--pla-plus-2-0", "printer": printer, "nozzle": nozzle,
            "filament_id": "GFL99", "filament_type": "PLA", "nozzle_temp_min": 200, "nozzle_temp_max": 230, **kw}


@pytest.fixture
def built(env, tmp_path, monkeypatch):
    # test_builds' env leaves FK_ETC unset; config.save must never reach the machine's /etc (nor state/opt)
    for name in ("etc", "opt"):
        (tmp_path / name).mkdir(exist_ok=True)
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    synced(env)
    r = builds.run_build(env, now=TG.NOW)
    assert r["ok"]
    return r["stamp"]


def test_orca_row_for_SV08(built):
    _add_rows(built, [_row()])
    got = profiles.preset_for(SUNLU[0], "SOVOL-SV08-MAX", 0.4, family="klipper", printer_name="SV08 MAX")
    assert got is not None
    assert (got.name, got.filament_type, got.nozzle_temp_min, got.nozzle_temp_max, got.setting_id) == (
        ORCA_NAME, "PLA", 200, 230, "")


def test_config_slicer_printers_names_the_row(built):
    # the owner's slicer_printers entry is called "My Sovol"; its compatible printers are the XML's Orca names
    cfg = config.load()
    cfg["slicer_printers"] = [{"name": "My Sovol", "slicer": "orca", "nozzles": ["0.4"], "label": "SV08 MAX",
                               "compatible_printers": {"0.4": "Sovol SV08 MAX"}}]
    config.save(cfg)
    _add_rows(built, [_row(printer="My Sovol", name="X @My Sovol 0.4")])
    got = profiles.preset_for(SUNLU[0], "SOVOL-SV08-MAX", 0.4, family="klipper", printer_name="SV08 MAX")
    assert got is not None and got.name == "X @My Sovol 0.4"


def test_bambu_unchanged(built):
    _add_rows(built, [_row()])
    got = profiles.preset_for(SUNLU[0], "O1D", 0.4)
    assert got is not None and got.name.endswith("@Bambu Lab H2D 0.4 nozzle")
    assert profiles.preset_for(SUNLU[0], "SOVOL-SV08-MAX", 0.4) is None     # a Klipper key is no Bambu model


def test_no_orca_row_none(built):
    assert profiles.preset_for(SUNLU[0], "SOVOL-SV08-MAX", 0.4, family="klipper", printer_name="SV08 MAX") is None
    _add_rows(built, [_row(nozzle="0.6")])
    assert profiles.preset_for(SUNLU[0], "SOVOL-SV08-MAX", 0.4, family="klipper", printer_name="SV08 MAX") is None


def test_orca_row_missing_temps_refused(built):
    _add_rows(built, [_row(nozzle_temp_min=None)])
    assert profiles.preset_for(SUNLU[0], "SOVOL-SV08-MAX", 0.4, family="klipper", printer_name="SV08 MAX") is None


def test_generic_model_has_no_orca_printer(built):
    _add_rows(built, [_row()])
    assert profiles.preset_for(SUNLU[0], "generic", 0.4, family="klipper", printer_name="Voron") is None
