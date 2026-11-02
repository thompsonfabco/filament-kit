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
