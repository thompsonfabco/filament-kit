"""The storage list over HTTP (R79 section 4, SL2): the contract of GET api/storage (and the web app's twin), the Hub
page's P settings/storage with its preview, a container set's name as a spool's location, the reasons, and the readers
that moved off the five old keys. The contract tests pin every field name and its null-ness: the Hub page, the web app
and the Android app are built against them."""
from __future__ import annotations

import copy
import html
import json
import re
import threading
import time

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from test_setup_page import CODE, H, Helper, client, env, make, post  # noqa: F401

from filament_kit import config, inventory, pairing, placement, setup_helper, storage, storage_api
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman, SpoolmanError
from filament_kit.storage import ANY, BULK, CONTAINERS, MATERIALS, NONE, Location, Storage
from filament_kit.web import mcp_tools
from filament_kit.web.intake_app import IntakeApp

ROW_FIELDS = ["id", "name", "type", "limit", "count", "used", "free", "fill", "materials", "overflow",
              "default_overflow", "sealed", "position", "containers", "prefix"]
TOP_FIELDS = ["locations", "order_by_material", "everything_else", "notices"]


class FakeSm:
    def __init__(self, spools):
        self.spools = spools

    def get(self, path):
        assert path == "spool"
        return [dict(s) for s in self.spools]

    def patch(self, path, body):
        sid = int(path.split("/")[1])
        next(s for s in self.spools if s["id"] == sid).update(body)


def spools(*places):
    return [{"id": i, "location": p} for i, p in enumerate(places, 1)]


def listing() -> Storage:
    """Sealed stock, Rack 1 (2 spools, PLA), Rack 2 (PLA), Storage box (3 containers, any), Overflow (default)."""
    st = Storage([
        Location("Sealed stock", sealed=True),
        Location("Rack 1", limit=2, fill=MATERIALS, materials=["PLA"]),
        Location("Rack 2", fill=MATERIALS, materials=["PLA"]),
        Location("Storage box", CONTAINERS, count=3, prefix="Storage box ", fill=ANY),
        Location("Overflow", overflow=True, default_overflow=True)])
    return st


@pytest.fixture
def saved(env, monkeypatch):  # noqa: F811
    """The list above written to storage.xml (the setup page's environment: a config file, the setup code)."""
    storage.save(listing())
    return storage.current()


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir(exist_ok=True)
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))


def body_of(st_view: dict, mutate=None) -> dict:
    rows = copy.deepcopy(st_view["locations"])
    if mutate:
        mutate(rows)
    return {"locations": rows}


# ================================================================ the contract of GET api/storage

def test_get_api_storage_pins_every_field_and_its_null_ness(fk_env):
    storage.save(listing())
    sm = FakeSm(spools("Rack 1", "Storage box 02", "Storage box 02", "Sealed stock"))
    out = storage_api.current_view(sm)
    assert list(out) == TOP_FIELDS
    sealed, rack1, rack2, box, over = out["locations"]
    for row in out["locations"]:
        assert list(row) == ROW_FIELDS
    # bulk: containers and prefix null, count null, limit null or a number, free null without a limit
    assert (sealed["type"], sealed["limit"], sealed["count"], sealed["free"]) == (BULK, None, None, None)
    assert sealed["containers"] is None and sealed["prefix"] is None
    assert (rack1["limit"], rack1["used"], rack1["free"], rack1["fill"], rack1["materials"]) == (2, 1, 1, MATERIALS, ["PLA"])
    assert (rack2["limit"], rack2["free"]) == (None, None)
    # containers: count, containers [{name, number, taken}], prefix; limit null; used and free count the taken ones
    assert (box["type"], box["limit"], box["count"], box["used"], box["free"]) == (CONTAINERS, None, 3, 1, 2)
    assert box["prefix"] == "Storage box "
    assert box["containers"] == [{"name": "Storage box 01", "number": 1, "taken": False},
                                 {"name": "Storage box 02", "number": 2, "taken": True},
                                 {"name": "Storage box 03", "number": 3, "taken": False}]
    assert all(list(c) == ["name", "number", "taken"] for c in box["containers"])
    assert box["used"] == sum(c["taken"] for c in box["containers"]) and len(box["containers"]) == box["count"]
    assert (over["overflow"], over["default_overflow"], over["sealed"], sealed["sealed"]) == (True, True, False, True)
    assert [r["position"] for r in out["locations"]] == [1, 2, 3, 4, 5]
    assert [r["id"] for r in out["locations"]] == ["loc-1", "loc-2", "loc-3", "loc-4", "loc-5"]
    types = {k: type(v) for k, v in rack1.items()}
    assert types["used"] is int and types["overflow"] is bool and types["materials"] is list and types["position"] is int


def test_order_by_material_and_everything_else_are_the_places_in_the_order_they_are_tried(fk_env):
    storage.save(listing())
    out = storage_api.current_view(FakeSm([]))
    assert out["order_by_material"] == [{"material": "PLA", "locations": ["Rack 1", "Rack 2", "Overflow"]}]
    assert list(out["order_by_material"][0]) == ["material", "locations"]
    assert out["everything_else"] == ["Storage box", "Overflow"]


def test_order_by_material_follows_the_longest_name_and_puts_other_overflow_places_after_the_default(fk_env):
    st = listing()
    st.locations.insert(2, Location("Rack PLA+", fill=MATERIALS, materials=["pla+", "PETG"]))
    st.locations.append(Location("Garage", limit=5, overflow=True))
    storage.save(st)
    out = storage_api.current_view(FakeSm([]))
    assert out["order_by_material"] == [
        {"material": "PLA", "locations": ["Rack 1", "Rack 2", "Overflow", "Garage"]},
        {"material": "pla+", "locations": ["Rack PLA+", "Overflow", "Garage"]},
        {"material": "PETG", "locations": ["Rack PLA+", "Overflow", "Garage"]}]
    assert out["everything_else"] == ["Storage box", "Overflow", "Garage"]


def test_notices_are_the_converted_line_and_the_default_overflow_without_a_limit(fk_env):
    st = listing()
    assert storage_api.notices(st) == []
    st.locations.append(Location("Garage", overflow=True))
    assert storage_api.notices(st) == [{"code": "default_overflow_no_limit", "text": storage.DEFAULT_OVERFLOW_NOTE}]
    st.locations[4].limit = 10
    st.converted = True
    assert storage_api.notices(st) == [{"code": "converted", "text": storage.NOTICE}]
    assert storage.DEFAULT_OVERFLOW_NOTE == ("The default overflow has no limit, so the other overflow places are never "
                                             "used. Give it a spool limit to let them fill.")


def _app_client(sm):
    return TestClient(create_app(sm=sm))


def test_the_app_route_answers_the_same_data_and_needs_the_token(fk_env, tmp_path):
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    storage.save(listing())
    sm = FakeSm(spools("Rack 1"))
    c = _app_client(sm)
    assert c.get("/api/storage").status_code == 401
    tok = pairing.redeem_code(pairing.issue().code)
    r = c.get("/api/storage", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json() == storage_api.current_view(sm)
    assert list(r.json()) == TOP_FIELDS


def test_api_locations_keeps_todays_answer_a_list_of_names(fk_env, tmp_path):
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    storage.save(listing())
    c = _app_client(FakeSm(spools("Rack 1", "Storage box 02", "Shelf by hand")))
    tok = pairing.redeem_code(pairing.issue().code)
    r = c.get("/api/locations", headers={"Authorization": f"Bearer {tok}"})
    assert r.json() == {"locations": ["Sealed stock", "Rack 1", "Rack 2", "Storage box", "Overflow",
                                      "Shelf by hand", "Storage box 02"]}


def test_the_web_app_twin_gives_the_same_data_under_its_own_base(fk_env):
    storage.save(listing())
    sm = FakeSm(spools("Rack 1", "Storage box 01"))
    tools = mcp_tools.Tools(sm)
    routes = IntakeApp(tools, public_url=None, lan_cidrs=["192.168.1.0/24"], push=False, host_ok=lambda r: True).routes()
    c = TestClient(Starlette(routes=routes), base_url="https://hub.local:8710", client=("192.168.1.20", 50000))
    r = c.get("/intake/api/storage")
    assert r.status_code == 200 and r.json() == storage_api.view(storage.current(), inventory._used_locations(sm))
    assert TestClient(Starlette(routes=routes), base_url="https://hub.local:8710",
                      client=("203.0.113.9", 50000)).get("/intake/api/storage").status_code == 403


# ================================================================ P settings/storage

@pytest.fixture
def hub(env, saved, spoolman_url):  # noqa: F811
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    return client(make(env, Helper()))


def current_body(hub_client, mutate=None):
    out = hub_client.get("/setup/api/settings/storage").json()
    return body_of(out, mutate)


def test_get_settings_storage_is_the_saved_list_with_how_full(hub):
    r = hub.get("/setup/api/settings/storage")
    assert r.status_code == 200 and list(r.json()) == TOP_FIELDS
    assert [x["name"] for x in r.json()["locations"]] == ["Sealed stock", "Rack 1", "Rack 2", "Storage box", "Overflow"]


def test_save_needs_the_code_and_the_preview_does_not(hub):
    body = current_body(hub)
    assert hub.post("/setup/api/settings/storage", json=body, headers=H).status_code == 403
    assert post(hub, "settings/storage", body, code="00000000").status_code == 403
    assert hub.post("/setup/api/settings/storage/preview", json=body, headers=H).status_code == 200


def test_save_the_list_unchanged_answers_the_saved_list(hub):
    r = post(hub, "settings/storage", current_body(hub))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True and out["saved"] is True and out["text"] == "" and out["updated"] == 0
    assert list(out["locations"][0]) == ROW_FIELDS
    assert [x.id for x in storage.current().locations] == ["loc-1", "loc-2", "loc-3", "loc-4", "loc-5"]


def test_saving_the_list_spends_the_converted_notice(hub):
    st = storage.current()
    st.converted = True
    storage.save(st)
    assert hub.get("/setup/api/settings/storage").json()["notices"] == [{"code": "converted", "text": storage.NOTICE}]
    out = post(hub, "settings/storage", current_body(hub)).json()
    assert out["notices"] == [] and storage.current().converted is False


def test_add_gives_a_new_row_an_id_and_goes_where_the_list_puts_it(hub):
    def add(rows):
        rows.insert(2, {"name": "Rack 1b", "type": "bulk", "limit": 5, "fill": "materials", "materials": ["PETG"]})
        rows.append({"id": None, "name": "Drawers", "type": "containers", "count": 2, "fill": "none"})
    out = post(hub, "settings/storage", current_body(hub, add)).json()
    assert [x["name"] for x in out["locations"]] == ["Sealed stock", "Rack 1", "Rack 1b", "Rack 2", "Storage box",
                                                     "Overflow", "Drawers"]
    assert out["locations"][2]["id"] == "loc-6" and out["locations"][6]["id"] == "loc-7"       # never reused
    drawers = storage.current().by_name("Drawers")
    assert drawers.prefix == "Drawers " and drawers.count == 2
    assert out["locations"][6]["containers"][0] == {"name": "Drawers 01", "number": 1, "taken": False}
    assert {"material": "PETG", "locations": ["Rack 1b", "Overflow"]} in out["order_by_material"]


def test_edit_keeps_the_id_and_changes_the_fields(hub):
    def edit(rows):
        rows[1].update(limit=10, materials=["PLA", "PETG"])
        rows[2].update(overflow=True, fill="none")
    out = post(hub, "settings/storage", current_body(hub, edit)).json()
    assert out["locations"][1]["id"] == "loc-2" and out["locations"][1]["limit"] == 10
    assert storage.current().by_name("Rack 1").materials == ["PLA", "PETG"]
    assert storage.current().by_name("Rack 2").overflow is True


def test_move_is_the_new_order(hub):
    out = post(hub, "settings/storage", current_body(hub, lambda rows: rows.insert(1, rows.pop(2)))).json()
    assert [x["name"] for x in out["locations"]][:3] == ["Sealed stock", "Rack 2", "Rack 1"]
    assert [x["position"] for x in out["locations"]] == [1, 2, 3, 4, 5]


def test_rename_renames_the_spools_stored_there_and_says_so(hub, spoolman_url, spoolman_fake_store):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    inventory.add_spools(sm, [_item(count=2, location="Rack 1"), _item(name="B", location="Storage box 02")],
                         storage.current(), dry=False)

    def rename(rows):
        rows[1]["name"] = "PLA rack 1"
        rows[3]["name"] = "Dry box"
    out = post(hub, "settings/storage", current_body(hub, rename)).json()
    assert out["saved"] is True and out["updated"] == 3
    assert out["text"] == "Renamed Rack 1 to PLA rack 1, Storage box to Dry box. 3 spools updated."
    assert sorted(s["location"] for s in spoolman_fake_store["spools"].values()) == [
        "Dry box 02", "PLA rack 1", "PLA rack 1"]
    assert storage.current().by_name("Dry box").prefix == "Dry box "
    assert out["locations"][1]["used"] == 2 and out["locations"][3]["containers"][1]["taken"] is True


def _item(**kw):
    base = {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E", "net": 1000,
            "tare": 213, "density": 1.27, "nozzle": 220, "bed": 55, "nozzle_range": "200-260",
            "lot": "L1", "count": 1, "price_per_kg": 12.5}
    base.update(kw)
    return base


def test_a_rename_of_more_than_20_spools_is_a_job_with_steps(hub, monkeypatch):
    sm = FakeSm([{"id": i, "location": "Rack 1"} for i in range(1, 46)])
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    gate = threading.Event()
    real = sm.patch

    def slow(path, body):
        gate.wait(5)
        real(path, body)
    sm.patch = slow
    out = post(hub, "settings/storage", current_body(hub, lambda rows: rows[1].update(name="PLA rack 1"))).json()
    assert out == {"ok": True, "saved": False, "job": {"steps": 3}}
    assert storage.current().by_name("PLA rack 1") is None          # not saved until the spools are renamed
    state = hub.get("/setup/api/settings/storage/job").json()
    assert state["state"] == "running" and list(state) == ["state", "step", "progress", "text", "error", "steps"]
    busy = post(hub, "settings/storage", current_body(hub))
    assert busy.status_code == 409 and "still running" in busy.json()["error"]
    gate.set()
    for _ in range(100):
        state = hub.get("/setup/api/settings/storage/job").json()
        if state["state"] != "running":
            break
        time.sleep(0.05)
    assert state["state"] == "done" and state["progress"] == 1.0
    assert state["text"] == "Renamed Rack 1 to PLA rack 1. 45 spools updated."
    assert state["step"] == {"index": 3, "count": 3, "text": "Updating spools 41 to 45 of 45"}
    assert storage.current().by_name("PLA rack 1") and all(s["location"] == "PLA rack 1" for s in sm.spools)


def _failing_once(sm, monkeypatch, after=1):
    """Patching the spool number `after`+1 fails once with a Spoolman error; later calls work."""
    real, calls = sm.patch, [0]

    def flaky(path, body):
        calls[0] += 1
        if calls[0] == after + 1:
            raise SpoolmanError("down", 500)
        real(path, body)
    sm.patch = flaky


def test_a_failed_rename_sent_again_resumes_the_recorded_plan(hub, monkeypatch):
    sm = FakeSm(spools("Rack 1", "Rack 1", "Rack 1"))
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    _failing_once(sm, monkeypatch, after=1)
    body = current_body(hub, lambda rows: rows[1].update(name="PLA rack 1"))
    r = post(hub, "settings/storage", body)
    assert r.status_code == 502
    assert [s["location"] for s in sm.spools] == ["PLA rack 1", "Rack 1", "Rack 1"]
    assert storage.current().by_name("Rack 1")                       # the list is not written until the spools are
    assert hub.get("/setup/api/settings/storage/job").json()["state"] == "failed"
    out = post(hub, "settings/storage", body).json()                 # the same save again
    assert out["saved"] is True and out["updated"] == 3
    assert [s["location"] for s in sm.spools] == ["PLA rack 1"] * 3
    assert storage.current().by_name("PLA rack 1") and inventory.pending_rename() is None
    assert hub.get("/setup/api/settings/storage/job").json()["state"] == "none"


def test_an_unrelated_save_after_a_half_done_rename_finishes_the_rename_first(hub, monkeypatch):
    sm = FakeSm(spools("Rack 1", "Rack 1", "Rack 2"))
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    _failing_once(sm, monkeypatch, after=1)
    assert post(hub, "settings/storage", current_body(hub, lambda rows: rows[1].update(name="PLA rack 1"))).status_code == 502
    shown = hub.get("/setup/api/settings/storage").json()
    assert [x["name"] for x in shown["locations"]][1] == "PLA rack 1"       # the page shows the list the save was making
    out = post(hub, "settings/storage", current_body(hub, lambda rows: rows[2].update(limit=5))).json()
    assert out["saved"] is True and out["text"] == "Renamed Rack 1 to PLA rack 1. 2 spools updated."
    assert [s["location"] for s in sm.spools] == ["PLA rack 1", "PLA rack 1", "Rack 2"]
    st = storage.current()
    assert st.by_name("PLA rack 1") and st.by_name("Rack 1") is None and st.by_name("Rack 2").limit == 5
    assert inventory.pending_rename() is None


def test_a_swap_resumed_and_a_new_rename_in_the_same_save_say_both(hub, monkeypatch):
    sm = FakeSm(spools("Rack 1", "Rack 2", "Rack 2", "Storage box 01"))
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    _failing_once(sm, monkeypatch, after=1)

    def swap(rows):
        rows[1]["name"], rows[2]["name"] = "Rack 2", "Rack 1"
    assert post(hub, "settings/storage", current_body(hub, swap)).status_code == 502

    def more(rows):
        rows[3]["name"] = "Dry box"
    out = post(hub, "settings/storage", current_body(hub, more)).json()
    assert out["saved"] is True and out["updated"] == 4
    assert out["text"] == ("Renamed Rack 1 to Rack 2, Rack 2 to Rack 1. 3 spools updated. "
                           "Renamed Storage box to Dry box. 1 spool updated.")
    assert [s["location"] for s in sm.spools] == ["Rack 2", "Rack 1", "Rack 1", "Dry box 01"]
    assert [x.name for x in storage.current().locations][1:4] == ["Rack 2", "Rack 1", "Dry box"]


def test_a_failed_resume_keeps_the_plan_and_refuses_the_save_with_error_and_fix(hub, monkeypatch):
    sm = FakeSm(spools("Rack 1", "Rack 1", "Rack 2"))
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    _failing_once(sm, monkeypatch, after=1)
    assert post(hub, "settings/storage", current_body(hub, lambda rows: rows[1].update(name="PLA rack 1"))).status_code == 502
    plan = inventory.pending_rename()
    real = sm.patch

    def down(path, body):
        raise SpoolmanError("down", 500)
    sm.patch = down
    r = post(hub, "settings/storage", current_body(hub, lambda rows: rows[2].update(limit=5)))
    assert r.status_code == 502 and r.json()["error"].startswith("Error:") and "Fix:" in r.json()["error"]
    assert inventory.pending_rename() == plan and storage.current().by_name("Rack 2").limit is None
    sm.patch = real                                                    # Spoolman is back: the next save finishes it
    out = post(hub, "settings/storage", current_body(hub, lambda rows: rows[2].update(limit=5))).json()
    assert out["saved"] is True and storage.current().by_name("Rack 2").limit == 5
    assert [s["location"] for s in sm.spools] == ["PLA rack 1", "PLA rack 1", "Rack 2"]


def test_after_a_restart_the_next_save_finishes_the_recorded_rename(hub, monkeypatch):
    sm = FakeSm(spools("Rack 1", "Rack 1"))
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    _failing_once(sm, monkeypatch, after=1)
    post(hub, "settings/storage", current_body(hub, lambda rows: rows[1].update(name="PLA rack 1")))
    monkeypatch.setattr(storage_api, "_job", None)                    # the Hub restarted: only the plan is left
    state = hub.get("/setup/api/settings/storage/job").json()
    assert state["state"] == "failed" and state["error"].startswith("Error:") and "save" in state["error"]
    out = post(hub, "settings/storage", current_body(hub)).json()
    assert out["saved"] is True and out["text"] == "Renamed Rack 1 to PLA rack 1. 2 spools updated."
    assert hub.get("/setup/api/settings/storage/job").json()["state"] == "none"


def test_a_resume_of_more_than_20_spools_is_a_job_and_a_save_during_it_is_refused(hub, monkeypatch):
    sm = FakeSm([{"id": i, "location": "Rack 1"} for i in range(1, 46)])
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    _failing_once(sm, monkeypatch, after=0)
    body = current_body(hub, lambda rows: rows[1].update(name="PLA rack 1"))
    assert post(hub, "settings/storage", body).json()["saved"] is False       # a job; it fails at the first spool
    for _ in range(100):
        if hub.get("/setup/api/settings/storage/job").json()["state"] != "running":
            break
        time.sleep(0.05)
    assert hub.get("/setup/api/settings/storage/job").json()["state"] == "failed"
    gate = threading.Event()
    real = sm.patch

    def slow(path, body):
        gate.wait(5)
        real(path, body)
    sm.patch = slow
    assert post(hub, "settings/storage", current_body(hub)).json() == {"ok": True, "saved": False, "job": {"steps": 3}}
    busy = post(hub, "settings/storage", current_body(hub))
    assert busy.status_code == 409 and "still running" in busy.json()["error"]
    gate.set()
    for _ in range(100):
        state = hub.get("/setup/api/settings/storage/job").json()
        if state["state"] != "running":
            break
        time.sleep(0.05)
    assert state["state"] == "done" and state["text"] == "Renamed Rack 1 to PLA rack 1. 45 spools updated."


def test_a_swap_of_two_names_through_the_route_moves_each_spool_once(hub, monkeypatch):
    sm = FakeSm(spools("Rack 1", "Rack 2", "Rack 2"))
    monkeypatch.setattr("filament_kit.setup_console.storage_tab.Spoolman", lambda url: sm)
    _failing_once(sm, monkeypatch, after=2)

    def swap(rows):
        rows[1]["name"], rows[2]["name"] = "Rack 2", "Rack 1"
    body = current_body(hub, swap)
    assert post(hub, "settings/storage", body).status_code == 502
    out = post(hub, "settings/storage", body).json()                   # the same save again: nothing differs
    assert out["saved"] is True
    assert [s["location"] for s in sm.spools] == ["Rack 2", "Rack 1", "Rack 1"]


def errors_of(r):
    assert r.status_code == 400, r.text
    out = r.json()
    assert out["error"].endswith("Nothing was saved.")
    return out["errors"]


def test_a_refusal_lists_errors_per_row_and_field_and_saves_nothing(hub):
    before = (config.paths().etc / "storage.xml").read_text(encoding="utf-8")

    def bad(rows):
        rows[1]["name"] = ""
        rows[2].update(name="rack 2 ", limit=0)
        rows[3]["name"] = "RACK 2"
    errs = errors_of(post(hub, "settings/storage", current_body(hub, bad)))
    assert all(list(e) == ["row", "id", "name", "field", "error", "fix"] for e in errs)
    got = {(e["row"], e["field"]): e["error"] for e in errs}
    assert got[(1, "name")] == "Enter a name for the location."
    assert got[(2, "limit")] == "Enter a whole number, 1 or more."
    assert got[(3, "name")] == "There is already a location called RACK 2."
    assert [e for e in errs if e["row"] == 1][0]["id"] == "loc-2"
    assert (config.paths().etc / "storage.xml").read_text(encoding="utf-8") == before


def test_fewer_containers_than_the_highest_in_use_is_refused_at_the_field(hub, spoolman_url):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    inventory.add_spools(sm, [_item(location="Storage box 02", name="A"), _item(location="Storage box 03", name="B")],
                         storage.current(), dry=False)
    errs = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows[3].update(count=1))))
    assert errs[0]["row"] == 3 and errs[0]["field"] == "count"
    assert errs[0]["error"] == "Storage box 02 and Storage box 03 hold spools. Move them first, or keep at least 3."
    assert post(hub, "settings/storage", current_body(hub, lambda rows: rows[3].update(count=3))).status_code == 200
    one = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows[3].update(count=2))))
    assert one[0]["error"] == "Storage box 03 holds spools. Move it first, or keep at least 3."


def test_the_type_is_fixed_while_spools_are_in_the_location(hub, spoolman_url):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    inventory.add_spools(sm, [_item(location="Rack 2")], storage.current(), dry=False)
    errs = errors_of(post(hub, "settings/storage", current_body(
        hub, lambda rows: rows[2].update(type="containers", count=2))))
    assert (errs[0]["row"], errs[0]["field"], errs[0]["error"]) == (2, "type", "Move the spools out to change the type.")
    ok = post(hub, "settings/storage", current_body(hub, lambda rows: rows[1].update(type="containers", count=2)))
    assert ok.status_code == 200 and storage.current().by_name("Rack 1").type == CONTAINERS     # empty: allowed


def test_removing_the_default_overflow_or_the_sealed_location_is_refused(hub):
    errs = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows.pop(4))))
    assert [(e["row"], e["field"], e["error"]) for e in errs] == [
        (None, "default_overflow", "Make another location the default overflow first.")]
    errs = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows.pop(0))))
    assert [(e["row"], e["field"], e["error"]) for e in errs] == [
        (None, "sealed", "Choose another location for sealed spools first.")]
    def move_role(rows):
        rows[1]["sealed"] = True
        rows[0]["sealed"] = False
        rows.pop(0)
    assert post(hub, "settings/storage", current_body(hub, move_role)).status_code == 200      # the role moved first


def test_a_remove_keeps_the_spools_where_they_are(hub, spoolman_url, spoolman_fake_store):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    inventory.add_spools(sm, [_item(location="Rack 2")], storage.current(), dry=False)
    assert post(hub, "settings/storage", current_body(hub, lambda rows: rows.pop(2))).status_code == 200
    assert [s["location"] for s in spoolman_fake_store["spools"].values()] == ["Rack 2"]


def test_name_clash_with_a_container_name_is_refused_both_ways(hub):
    errs = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows[2].update(name="Storage box 04"))))
    assert {(e["row"], e["field"]) for e in errs} == {(2, "name"), (3, "name")}
    assert errs[0]["error"] == "Storage box 04 is the name of a container in Storage box. Choose another name."
    errs = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows.insert(
        1, {"name": "Storage box 01", "type": "bulk"}))))
    assert {e["row"] for e in errs} == {1, 4}


def test_any_material_on_an_overflow_location_is_refused(hub):
    errs = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows[4].update(fill="any"))))
    assert (errs[0]["row"], errs[0]["field"], errs[0]["error"]) == (
        4, "fill", "An overflow location cannot take any material automatically.")


def test_a_row_that_is_not_ready_is_an_error_and_a_bad_shape_too(hub):
    errs = errors_of(post(hub, "settings/storage", {"locations": [{"name": "x", "limit": "many"}, "row"]}))
    assert {(e["row"], e["field"]) for e in errs} >= {(0, "limit"), (1, "row"), (None, "default_overflow"), (None, "sealed")}
    assert errors_of(post(hub, "settings/storage", {"locations": "no"}))[0]["field"] == "locations"
    unknown = errors_of(post(hub, "settings/storage", current_body(hub, lambda rows: rows[1].update(id="loc-99"))))
    assert (unknown[0]["row"], unknown[0]["field"]) == (1, "id")


def test_the_preview_answers_the_unsaved_list_and_writes_nothing(hub):
    before = (config.paths().etc / "storage.xml").read_text(encoding="utf-8")

    def edit(rows):
        rows[1]["name"] = "PLA shelf"
        rows.append({"name": "Attic", "type": "bulk", "overflow": True, "limit": 3})
        rows[2].update(fill="materials", materials=["PETG", "PLA"])
    out = hub.post("/setup/api/settings/storage/preview", json=current_body(hub, edit), headers=H).json()
    assert out["ok"] is True and out["errors"] == [] and out["dry_run"] is True
    assert [x["name"] for x in out["locations"]][-1] == "Attic" and out["locations"][-1]["id"] is None
    assert out["order_by_material"][0] == {"material": "PLA", "locations": ["PLA shelf", "Rack 2", "Overflow", "Attic"]}
    assert out["order_by_material"][1] == {"material": "PETG", "locations": ["Rack 2", "Overflow", "Attic"]}
    assert out["renames"] == [{"from": "Rack 1", "to": "PLA shelf"}]
    assert (config.paths().etc / "storage.xml").read_text(encoding="utf-8") == before


def test_the_preview_of_a_list_with_errors_still_answers_the_data_and_the_errors(hub):
    out = hub.post("/setup/api/settings/storage/preview", headers=H, json=current_body(
        hub, lambda rows: (rows.append({"name": "", "type": "bulk"}), rows[4].update(default_overflow=False)))).json()
    assert out["ok"] is False and out["locations"][-1]["name"] == ""
    assert {(e["row"], e["field"]) for e in out["errors"]} == {(5, "name"), (None, "default_overflow")}
    assert list(out["order_by_material"][0]) == ["material", "locations"]


def test_dry_run_with_the_code_is_the_same_preview(hub):
    out = post(hub, "settings/storage", {**current_body(hub), "dry_run": True}).json()
    assert out["dry_run"] is True and out["ok"] is True


def test_the_five_old_keys_are_no_longer_a_hub_setting(hub):
    for key in ("locations", "placement.pla_location", "placement.box_prefix", "placement.box_count",
                "placement.overflow"):
        assert key not in setup_helper.GENERAL
        assert post(hub, "settings/general", {"key": key, "value": "x"}).status_code == 400
        assert key not in hub.get("/setup/api/settings/general").json()["values"]


# ================================================================ a set's name as a spool's location, and the reasons

def test_a_location_text_matches_a_set_name_before_a_container_name(fk_env):
    """The client note of GET api/storage: a spool's location text is matched against `name` of the locations first,
    and only when none has that name is it a container's own name (`containers[].name`) or any other text. Only a
    clash a list already had can make the two meet (a new one is refused both ways)."""
    st = Storage([Location("Box 02", CONTAINERS, count=2, prefix="Box 02 ", fill=ANY),
                  Location("Box", CONTAINERS, count=3, prefix="Box ", fill=ANY),
                  Location("Overflow", overflow=True, default_overflow=True)])
    assert [c["name"] for c in storage_api.view(st, {})["locations"][1]["containers"]] == ["Box 01", "Box 02", "Box 03"]
    assert placement.resolve(st, "Box 02", storage.counts_of({})) == "Box 02 01"       # the set named "Box 02"
    assert placement.resolve(st, "Box 03", storage.counts_of({})) == "Box 03"          # no set has this name: as given


def test_a_containers_location_name_as_the_location_means_the_lowest_free_container(fk_env, spoolman_url):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    st = listing()
    r = inventory.add_spools(sm, [_item(count=2, location="Storage box")], st, dry=False)
    assert [p["location"] for p in r.items[0]["placements"]] == ["Storage box 01", "Storage box 02"]
    assert all(p["placed_by"] is None for p in r.items[0]["placements"])             # a place the person chose: no reason
    r = inventory.add_spools(sm, [_item(name="C", location="storage box")], st, dry=False)
    assert r.items[0]["location"] == "Storage box 03"
    with pytest.raises(inventory.ItemsInvalid) as e:
        inventory.add_spools(sm, [_item(name="D", location="Storage box")], st, dry=False)
    assert e.value.problems == [{"item": 0, "field": "location",
                                 "message": "Every container in Storage box is taken. Choose another location."}]
    r = inventory.add_spools(sm, [_item(name="E", location="Storage box 02")], st, dry=True)       # a container's own name
    assert r.items[0]["location"] == "Storage box 02"
    r = inventory.add_spools(sm, [_item(name="F", location="Rack 1")], st, dry=True)               # bulk: as given
    assert r.items[0]["location"] == "Rack 1"


def test_open_and_move_accept_the_set_name_too(fk_env, spoolman_url, spoolman_fake_store):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    st = listing()
    ids = inventory.add_spools(sm, [_item(count=2, location="Storage box 01")], st, dry=False).spool_ids
    moved = inventory.update_spool(sm, ids[1], location="Storage box", dry=False, rules=st)
    assert moved["location"] == "Storage box 02"
    again = inventory.update_spool(sm, ids[0], location="Rack 2", dry=False, rules=st)
    assert again["location"] == "Rack 2"
    assert inventory.update_spool(sm, ids[0], location="Storage box", dry=True, rules=st)["location"] == "Storage box 01"
    opened = inventory.open_spool(sm, ids[0], "a:b:c:d:e:f:1", st, location="Storage box", dry=True)
    assert opened["location"] == "Storage box 01"
    st2 = Storage(listing().locations)
    for n in (1, 3):
        inventory.add_spools(sm, [_item(name=f"X{n}", location=f"Storage box 0{n}")], st2, dry=False)
    with pytest.raises(inventory.SpoolEditError, match="Every container in Storage box is taken"):
        inventory.update_spool(sm, ids[0], location="Storage box", dry=True, rules=st)


def test_the_placed_by_codes_are_material_any_overflow_overflow_none_and_sealed(fk_env):
    st = listing()
    st.locations[1].limit = 1
    st.locations[2].limit = 1
    taken = {"Rack 1": 1, "Rack 2": 1}
    out = placement.place([{"material": "PLA", "sealed": False}, {"material": "PETG", "sealed": False},
                           {"material": "PETG", "sealed": True}], {}, st)
    assert [(p["location"], p["placed_by"]) for p in out] == [
        ("Rack 1", "material"), ("Storage box 01", "any"), ("Sealed stock", "sealed")]
    out = placement.place([{"material": "PLA", "sealed": False}], taken, st)
    assert (out[0]["location"], out[0]["placed_by"]) == ("Overflow", "overflow")         # both PLA places are full
    st.locations[3].fill = NONE                                       # no place takes PETG automatically any more
    out = placement.place([{"material": "PETG", "sealed": False}], {}, st)
    assert (out[0]["location"], out[0]["placed_by"]) == ("Overflow", "overflow_none")
    assert set(inventory.PLACED_BY) == {"sealed", "material", "any", "overflow", "overflow_none"}


# ================================================================ the readers that left the old keys

def test_the_web_app_page_attributes_come_from_the_storage_list(fk_env):
    storage.save(listing())
    tools = mcp_tools.Tools(FakeSm([]))
    routes = IntakeApp(tools, public_url=None, lan_cidrs=["192.168.1.0/24"], push=False, host_ok=lambda r: True).routes()
    c = TestClient(Starlette(routes=routes), base_url="https://hub.local:8710", client=("192.168.1.20", 50000))
    attrs = {k: html.unescape(v) for k, v in re.findall(
        r"data-([a-z-]+)='([^']*)'", re.search(r"<body ([^>]*)>", c.get("/intake").text).group(1))}
    assert json.loads(attrs["locations"]) == ["Sealed stock", "Rack 1", "Rack 2", "Storage box", "Overflow"]
    assert attrs["sealed"] == "Sealed stock"
    assert json.loads(attrs["picks"]) == ["Rack 1", "Rack 2"]
    assert attrs["auto"] == ("PLA goes to 'Rack 1', then 'Rack 2', then 'Overflow'; other materials go to "
                             "'Storage box NN' (01-03), then 'Overflow'")


def test_the_connector_instructions_describe_the_storage_list(fk_env):
    st = listing()
    text = mcp_tools.instructions(config.load(), st)
    for want in ("'Sealed stock', 'Rack 1', 'Rack 2', 'Storage box', 'Overflow'", "('Sealed stock' is the default",
                 "PLA goes to 'Rack 1', then 'Rack 2', then 'Overflow'", "'Storage box NN' (01-03)"):
        assert want in text, want


def test_a_hub_without_storage_xml_still_reads_from_the_old_keys_in_memory(fk_env):
    cfg = config.load()
    cfg["placement"]["box_count"] = 4
    config.save(cfg)
    assert not (config.paths().etc / "storage.xml").exists()
    tools = mcp_tools.Tools(FakeSm([]))
    st = tools.storage_list()
    assert [x.name for x in st.locations] == ["Sealed stock", "Rack 1", "Storage box", "Overflow"]
    assert st.by_name("Storage box").type == CONTAINERS
    assert not (config.paths().etc / "storage.xml").exists()          # the web unit never writes it
