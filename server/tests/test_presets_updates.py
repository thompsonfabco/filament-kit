"""Presets already in the slicers are never replaced; each build lists new / same / update against the PC's live
upload, `profiles status` says "N updates available (M lines)", `GET /api/profiles/updates` lists them, and
`profiles apply-updates [--line <id>|--all] [--dry-run]` accepts them for the next PC sync (profiles.updates)."""
import io
import json

import pytest
from starlette.testclient import TestClient

from filament_kit import cli, config, library, pairing
from filament_kit.api import create_app
from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer
from filament_kit.profiles import builds, inapp, updates

import test_builds as TB
import test_generate as TG

LID = "sunlu--pla-plus-2-0"
N04, N06 = TG.sunlu(TG.H2D, "0.4"), TG.sunlu(TG.H2D, "0.6")


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):                 # never the real /etc/filament-kit
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    config.save({})
    monkeypatch.setattr(library, "load", lambda: TG.make_lib())
    registry.upsert(Printer("S1", "H2D", "O1D", "10.0.0.5", "", True))
    TB.pair("a")
    return TB.FakeSm(json.loads(json.dumps(TB.SUNLU)))       # a copy: the tests change densities


def _first_install(sm) -> str:
    """Build, then the PC installs it (every preset new: all written), re-uploads the live folder."""
    TB.synced(sm)
    b1 = builds.run_build(sm, now=TG.NOW)["stamp"]
    names = sorted(r["name"] for r in builds.manifest(b1)["presets"])
    builds.record_installed(b1, "a", ["base"], {"base": names})
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1)), device_id="a", user_id="1")
    return b1


def _rebuild(sm, density, now) -> str:
    for f in sm.filaments:
        f["density"] = density
    TB.tick()
    builds.request_rebuild("spoolman changed")
    r = builds.run_build(sm, now=now)
    assert r["ok"], r
    return r["stamp"]


def _slicer(stamp):
    return updates.slicer(TB.profiles_dir() / "builds" / stamp)["base"]


def test_first_build_against_an_empty_slicer_is_all_new(env):
    TB.synced(env)
    stamp = builds.run_build(env, now=TG.NOW)["stamp"]
    rows = _slicer(stamp)
    assert rows and all(r == {"status": "new"} for r in rows.values())
    assert builds.updates_view()["new"] == len(rows) and builds.updates_view()["count"] == 0
    # SLICER.json and held/ stay on the server: the build zip is exactly BUILD.json + base/
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(builds.build_zip(stamp))).namelist()
    assert all(n == "BUILD.json" or n.startswith("base/") for n in names)


def test_changed_values_are_listed_as_updates_then_accepted_and_cleared(env, capsys):
    b1 = _first_install(env)
    b2 = _rebuild(env, 1.31, TG.NOW + 1)
    rows = _slicer(b2)
    assert {r["status"] for r in rows.values()} == {"update"}
    assert all("filament_density" in r["keys"] for r in rows.values())
    # the slicer's own copy is held for the next build's in-app snapshot
    held = TB.profiles_dir() / "builds" / b2 / "held" / "base" / f"{N04}.json"
    assert held.read_bytes() == (TB.profiles_dir() / "builds" / b1 / "base" / f"{N04}.json").read_bytes()
    view = builds.updates_view()
    assert view["count"] == len(rows) and view["lines"] == 1 and view["accepted"] == 0
    assert {u["line_id"] for u in view["updates"]} == {LID}
    assert builds.state_view("a")["accepted_updates"] == {"stamp": b2, "base": [], "orca": []}

    assert cli.main(["profiles", "status"]) == 0
    assert f"{len(rows)} updates available (1 line)" in capsys.readouterr().out

    # dry run: listed, nothing saved
    assert cli.main(["profiles", "apply-updates", "--all", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and N04 in out
    assert updates.accepted(TB.profiles_dir()) == {"base": set(), "orca": set()}
    assert builds.state_view("a")["accepted_updates"]["base"] == []

    # an unknown line: nothing accepted
    assert cli.main(["profiles", "apply-updates", "--line", "nope"]) == 1
    assert cli.main(["profiles", "apply-updates", "--line", LID]) == 0
    assert "accepted" in capsys.readouterr().out
    acc = builds.state_view("a")["accepted_updates"]
    assert acc["stamp"] == b2 and acc["base"] == sorted(rows)
    assert builds.status()["updates"]["accepted"] == len(rows)

    # the PC writes one of them: it is cleared, the rest stay accepted
    builds.record_installed(b2, "a", ["base"], {"base": [N04]})
    acc = builds.state_view("a")["accepted_updates"]
    assert N04 not in acc["base"] and N06 in acc["base"]
    assert N04 not in {u["name"] for u in builds.updates_view()["updates"]}
    # the next report of the same build adds to what was written
    builds.record_installed(b2, "a", ["base"], {"base": [N06]})
    inst = builds._read_obj(TB.profiles_dir() / "installed.json")
    assert {N04, N06} <= set(inst["written"])


def test_neither_or_both_line_and_all_is_an_error(env):
    with pytest.raises(ValueError):
        builds.apply_updates()
    with pytest.raises(ValueError):
        builds.apply_updates(line_id=LID, all_=True)
    with pytest.raises(SystemExit):
        cli.main(["profiles", "apply-updates"])


def test_kept_presets_are_no_in_app_edits_and_accepted_updates_keep_the_owners_edits(env):
    b1 = _first_install(env)
    b2 = _rebuild(env, 1.31, TG.NOW + 1)
    builds.record_installed(b2, "a", ["base"], {"base": []})        # all kept: the slicer still holds b1's values
    TB.tick()
    cfg = json.loads((TB.profiles_dir() / "builds" / b1 / "base" / f"{N04}.json").read_text(encoding="utf-8"))
    flow = ["0.91"] * len(cfg["filament_flow_ratio"])
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1, edit={N04: {"filament_flow_ratio": flow}})),
                        device_id="a", user_id="1")
    b3 = _rebuild(env, 1.31, TG.NOW + 2)
    m3 = builds.manifest(b3)
    # the kept b1 values are not edits (density 1.24 is not "his"); his flow edit is
    assert m3["inapp"] == {N04: {"filament_flow_ratio": flow}}, m3["inapp"]
    out = json.loads((TB.profiles_dir() / "builds" / b3 / "base" / f"{N04}.json").read_text(encoding="utf-8"))
    assert out["filament_density"] == ["1.31"] and out["filament_flow_ratio"] == flow
    # so the update the owner may accept carries his value
    assert "filament_flow_ratio" not in _slicer(b3)[N04]["keys"]


def test_owner_note_lines_on_a_kept_preset_stay_theirs(env):
    b1 = _first_install(env)
    cfg = json.loads((TB.profiles_dir() / "builds" / b1 / "base" / f"{N04}.json").read_text(encoding="utf-8"))
    notes = cfg["filament_notes"].replace(inapp.IDS_PREFIX, "dry 8 h first\n" + inapp.IDS_PREFIX)
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1, edit={N04: {"filament_notes": notes}})),
                        device_id="a", user_id="1")
    b2 = _rebuild(env, 1.24, TG.NOW + 1)
    builds.record_installed(b2, "a", ["base"], {"base": []})        # kept (the note line was only moved)
    TB.tick()
    builds.store_upload("live", io.BytesIO(TB._live_zip_of(b1, edit={N04: {"filament_notes": notes}})),
                        device_id="a", user_id="1")
    b3 = _rebuild(env, 1.31, TG.NOW + 2)
    out = json.loads((TB.profiles_dir() / "builds" / b3 / "base" / f"{N04}.json").read_text(encoding="utf-8"))
    assert out["filament_notes"].splitlines()[-2:] == ["dry 8 h first", out["filament_notes"].splitlines()[-1]]
    assert inapp.MARK in out["filament_notes"]


def test_a_preset_the_owner_made_before_is_an_update_never_new(env):
    """The owner's own preset of a generated name (same file name, or another file holding that `name`)."""
    TB.synced(env)
    b0 = builds.run_build(env, now=TG.NOW)["stamp"]
    mine = json.loads((TB.profiles_dir() / "builds" / b0 / "base" / f"{N04}.json").read_text(encoding="utf-8"))
    mine["nozzle_temperature"] = ["205"] * len(mine["nozzle_temperature"])
    other = dict(mine, name=N06)
    files = {f"base/{N04}.json": json.dumps(mine), "base/my sovol copy.json": json.dumps(other)}
    builds.store_upload("live", io.BytesIO(TB.zip_of(files)), device_id="a", user_id="1")
    TB.tick()
    builds.request_rebuild("live")
    b1 = builds.run_build(env, now=TG.NOW + 1)["stamp"]
    rows = _slicer(b1)
    assert rows[N04]["status"] == "update" and "nozzle_temperature" in rows[N04]["keys"]
    assert rows[N06]["status"] == "update" and rows[N06]["file"] == "my sovol copy"
    assert {r["status"] for n, r in rows.items() if n not in (N04, N06)} == {"new"}
    items = {u["name"]: u for u in builds.updates_view()["updates"]}
    assert items[N06]["file"] == "my sovol copy"
    # installed with nothing over them: the next build's snapshot has the owner's copy, none for the other file
    builds.record_installed(b1, "a", ["base"], {"base": [n for n in rows if n not in (N04, N06)]})
    view = updates.view(TB.profiles_dir() / "builds" / b1, "base",
                        builds._written(builds._installed(), "written"), TB.profiles_dir() / "v.tmp")
    assert json.loads((view / "base" / f"{N04}.json").read_text())["nozzle_temperature"] == mine["nozzle_temperature"]
    assert not (view / "base" / f"{N06}.json").exists()


def test_older_pc_report_without_written_keeps_the_build_as_snapshot(env):
    b1 = _first_install(env)
    b2 = _rebuild(env, 1.31, TG.NOW + 1)
    builds.record_installed(b2, "a")                                # an older PC sync wrote every preset
    assert "written" not in builds._read_obj(TB.profiles_dir() / "installed.json")
    folder = TB.profiles_dir() / "builds" / b2
    assert updates.view(folder, "base", builds._written(builds._installed(), "written"), folder / "x") == folder
    assert builds.updates_view()["count"] == len(_slicer(b2))       # nothing reported written: still listed
    assert b1


def test_bad_written_is_400(env):
    b1 = _first_install(env)
    for bad in ({"base": "x"}, {"other": []}, {"base": [1]}, ["base"]):
        with pytest.raises(builds.ProfileError) as e:
            builds.record_installed(b1, "a", ["base"], bad)
        assert e.value.status == 400


def test_an_accepted_update_that_is_no_longer_one_is_dropped(env):
    _first_install(env)
    _rebuild(env, 1.31, TG.NOW + 1)
    builds.apply_updates(all_=True)
    assert builds.status()["updates"]["accepted"] > 0
    _rebuild(env, 1.24, TG.NOW + 2)                                 # back to what the slicer holds: no update
    assert builds.updates_view()["count"] == 0
    assert updates.accepted(TB.profiles_dir()) == {"base": set(), "orca": set()}
    _rebuild(env, 1.35, TG.NOW + 3)                                 # a new update is not accepted on its own
    assert builds.status()["updates"]["accepted"] == 0


def test_updates_api(env):
    pairing.make_cert("fkhost", [], config.paths().etc)
    c = TestClient(create_app(sm=env))
    tok = pairing.redeem_code(pairing.issue().code)
    _first_install(env)
    b2 = _rebuild(env, 1.31, TG.NOW + 1)
    r = c.get("/api/profiles/updates", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert body["stamp"] == b2 and body["count"] == len(body["updates"]) > 0 and body["lines"] == 1
    assert set(body["updates"][0]) >= {"name", "target", "line_id", "keys", "accepted"}
    st = c.get("/api/profiles/status", headers={"Authorization": f"Bearer {tok}"}).json()
    assert st["updates"]["count"] == body["count"]
