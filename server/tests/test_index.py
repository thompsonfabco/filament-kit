"""`profiles.preset_for`: the last good build's preset for a Spoolman filament on a printer model and nozzle."""
import io
import json
import os

import pytest

from filament_kit import config, profiles
from filament_kit.profiles import builds, index

import test_generate as TG
from test_builds import SUNLU, env, synced, zip_of  # noqa: F401  (env is a fixture)

NAME = "SUNLU PLA+ 2.0 @Bambu Lab H2D 0.4 nozzle"


@pytest.fixture
def built(env):
    synced(env)
    r = builds.run_build(env, now=TG.NOW)
    assert r["ok"]
    m = json.loads((config.paths().state / "profiles" / "builds" / r["stamp"] / "BUILD.json")
                   .read_text(encoding="utf-8"))
    return m["lines"]["sunlu--pla-plus-2-0"]["filament_id"], r["stamp"]


def test_preset_for_line(built):
    fid, _ = built
    got = profiles.preset_for(SUNLU[0], "O1D", 0.4)
    assert got == profiles.PresetRef(filament_id=fid, name=NAME, nozzle_temp_min=190, nozzle_temp_max=230,
                                     filament_type="PLA", setting_id="")
    assert isinstance(got.nozzle_temp_min, int) and isinstance(got.nozzle_temp_max, int)


def test_new_colour_same_line(built):
    new = TG.fil(99, "PLA+ 2.0 Sky Blue", extra={"line": json.dumps("PLA+ 2.0")})
    assert profiles.preset_for(new, "O1D", 0.4) == profiles.preset_for(SUNLU[0], "O1D", 0.4)


def test_filament_id_map_fallback(built):
    odd = dict(SUNLU[1], extra={})
    odd["name"] = "Something else entirely"
    got = profiles.preset_for(odd, "O1D", 0.4)
    assert got is not None and got.name == NAME


def test_none_cases(env, tmp_path):
    assert profiles.preset_for(SUNLU[0], "O1D", 0.4) is None          # no build yet
    synced(env)
    builds.run_build(env, now=TG.NOW)
    assert profiles.preset_for(SUNLU[0], "NOPE", 0.4) is None         # unknown model
    assert profiles.preset_for(SUNLU[0], "O1D", 1.0) is None          # no preset for that nozzle
    assert profiles.preset_for(SUNLU[0], "C12", 0.4) is None          # printer not in the registry: not built
    other = TG.fil(50, "PETG Basic", vendor="Nobody", material="PETG")
    assert profiles.preset_for(other, "O1D", 0.4) is None


def _tamper(stamp, change):
    path = config.paths().state / "profiles" / "builds" / stamp / "BUILD.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    for p in m["presets"]:
        if p["name"] == NAME:
            change(p)
    path.write_text(json.dumps(m), encoding="utf-8")
    cur = config.paths().state / "profiles" / "current.json"
    st = cur.stat()
    os.utime(cur, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))   # the cache keys on current.json


def test_tampered_system_id_refused(built):
    _, stamp = built
    assert profiles.preset_for(SUNLU[0], "O1D", 0.4) is not None
    _tamper(stamp, lambda p: p.update(filament_id="GFL99"))
    assert profiles.preset_for(SUNLU[0], "O1D", 0.4) is None


def test_missing_temps_refused(built):
    _, stamp = built
    _tamper(stamp, lambda p: p.update(nozzle_temp_min=None))
    assert profiles.preset_for(SUNLU[0], "O1D", 0.4) is None


def test_setting_id_from_live_info(built):
    builds.store_upload("live", io.BytesIO(zip_of({f"base/{NAME}.json": "{}",
                                                   f"base/{NAME}.info": "sync_info = \nsetting_id = PFUS1\n"})),
                        device_id="a", user_id="1")
    assert profiles.preset_for(SUNLU[0], "O1D", 0.4).setting_id == "PFUS1"


def test_cache_follows_current(built, monkeypatch):
    calls = []
    real = index._read_build

    def counting(*a):
        calls.append(1)
        return real(*a)
    monkeypatch.setattr(index, "_read_build", counting)
    index._cache.clear()
    profiles.preset_for(SUNLU[0], "O1D", 0.4)
    profiles.preset_for(SUNLU[0], "O1D", 0.4)
    assert len(calls) == 1
