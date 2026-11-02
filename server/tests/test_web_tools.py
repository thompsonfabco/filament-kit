"""web.mcp_tools: each MCP tool's happy path against the fake Spoolman (and the fake reader / slot services),
plus the instructions text. The MCP wiring itself (handshake, tools/list) is in test_web_app.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from fakes import readers_fake  # noqa: E402

from conftest import free_port  # noqa: E402
from filament_kit import config, inventory, modules, pairing, tags, tagsources  # noqa: E402
from filament_kit.profiles import bbl, builds, lines as lines_mod  # noqa: E402
from filament_kit.spoolman import Spoolman  # noqa: E402
from filament_kit.web import mcp_tools, slots  # noqa: E402
from filament_kit.web.mcp_tools import Problem  # noqa: E402

BBL = Path(__file__).parent / "data" / "bbl"
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2,
         "overflow": "Overflow", "sealed_location": "Sealed stock"}
UID = "4:77:90:e:9:22:89"
UID2 = "4:77:8f:e:9:22:89"


def item(**kw):
    base = {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E", "net": 1000,
            "tare": 213, "density": 1.24, "count": 1}
    base.update(kw)
    return base


@pytest.fixture
def readers():
    data = readers_fake.new_data()
    with readers_fake.Served(readers_fake.app(data), free_port()) as url:
        yield data, url


@pytest.fixture
def env(tmp_path, monkeypatch, readers):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    tagsources._failed.clear()
    data, url = readers
    cfg = {"placement": RULES, "tag_sources": [{"name": "printer", "url": url + "/last-tag"}],
           "modules": {n: True for n in modules.MODES["server"]}}
    config.save(cfg)
    return tmp_path, data, url


@pytest.fixture
def sm(spoolman_url, env):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def tools(sm):
    return mcp_tools.Tools(sm)


def tap(data, uid=UID, age=10):
    data["tag"] = {"status": "ok", "nfc_id": uid, "read_at_unix": 1000, "age_seconds": age}


def add(sm, *items):
    return inventory.add_spools(sm, list(items), RULES, dry=False).spool_ids


# ---------- inventory tools ----------

def test_find_spools(tools, sm):
    a, b = add(sm, item(count=2))
    (c,) = add(sm, item(vendor="ELEGOO", name="PETG Black", material="PETG", tare=154, sealed=False,
                        location="Shelf 4"))
    out = tools.find_spools("sunlu pla")
    assert out["matches"] == 1 and out["truncated"] is False
    (f,) = out["filaments"]
    assert f["vendor"] == "SUNLU" and f["name"] == "PLA+ Grey" and f["net_g"] == 1000 and f["tare_g"] == 213
    assert [s["spool_id"] for s in f["spools"]] == [a, b]
    assert f["spools"][0] == {"spool_id": a, "location": "Sealed stock", "remaining_g": 1000, "sealed": True,
                              "lot": None, "tagged": False}
    assert tools.find_spools("petg")["filaments"][0]["spools"][0]["sealed"] is False
    assert tools.find_spools("", sealed_only=True)["matches"] == 1
    assert tools.find_spools("", location="shelf")["filaments"][0]["spools"][0]["spool_id"] == c
    assert tools.find_spools("nothing like this")["matches"] == 0


def test_add_spools_dry_then_real(tools, sm, spoolman_fake_store):
    dry = tools.add_spools([item(count=2)], dry_run=True)
    assert dry["dry"] is True and dry["spool_ids"] == [] and "2 spool(s)" in dry["output"]
    assert dry["exit_code"] == 0 and "dry run" in dry["output"]
    assert spoolman_fake_store["spools"] == {}
    real = tools.add_spools([item(count=2)], dry_run=False)
    assert real["dry"] is False and len(real["spool_ids"]) == 2
    assert {s["location"] for s in spoolman_fake_store["spools"].values()} == {"Sealed stock"}
    with pytest.raises(ValueError):
        tools.add_spools([item(net=-1)], dry_run=True)


def test_add_spools_links_tag_by_id(tools, sm, env):
    _, data, _ = env
    tap(data)
    res = tools.add_spools([item(material="PETG", name="PETG Red", sealed=False)], dry_run=False, link_tag=UID)
    (sid,) = res["spool_ids"]
    assert tags.stored(sm.get(f"spool/{sid}")) == UID and f"linked tag {UID}" in res["output"]
    # the reader's last tag moved on since the read: nothing is linked, the spool is still added
    tap(data, UID2)
    res = tools.add_spools([item(material="PETG", name="PETG Blue", sealed=False)], dry_run=False,
                           link_tag="4:1:2:3")
    assert tags.stored(sm.get(f"spool/{res['spool_ids'][0]}")) is None
    assert "not linked" in res["output"]


def test_tag_state(tools, sm, env):
    _, data, _ = env
    assert tools.tag_state()["nfc_id"] is None and "No tag" in tools.tag_state()["text"]
    (a,) = add(sm, item())
    (b,) = add(sm, item(name="PLA+ Blue"))
    inventory.link_tag(sm, a, UID2, force=False, dry=False)
    tap(data, UID, age=30)
    st = tools.tag_state()
    assert st["nfc_id"] == UID and st["reader"] == "printer" and st["age_seconds"] == 30
    assert st["spool"] is None and "not linked" in st["text"] and st["near"] == [a]
    inventory.link_tag(sm, b, UID, force=False, dry=False)
    st = tools.tag_state()
    assert st["spool"]["id"] == b and f"spool {b}" in st["text"]


def test_open_spool_by_filament_with_humidity(tools, sm, env):
    _, data, _ = env
    a, b = add(sm, item(material="PETG", name="PETG Grey", count=2))
    fid = sm.get(f"spool/{a}")["filament"]["id"]
    tap(data)
    dry = tools.open_spool(filament=fid, gross=1100, humidity=35, dry_run=True)
    assert dry["dry"] is True and dry["spool"]["id"] == a
    assert tags.stored(sm.get(f"spool/{a}")) is None
    out = tools.open_spool(filament=fid, gross=1100, humidity=35, dry_run=False)
    s = sm.get(f"spool/{a}")
    assert tags.stored(s) == UID and s["location"] == "Storage box 01" and s["remaining_weight"] == 887
    assert json.loads(s["extra"]["box_humidity"]) == 35 and "SEALED" not in (s["comment"] or "")
    assert out["spool"]["id"] == a and UID in out["output"]
    # the tag is on spool a now: opening b with it needs force
    with pytest.raises(inventory.TagConflict):
        tools.open_spool(spool=b, dry_run=False)
    tools.open_spool(spool=b, force=True, dry_run=False)
    assert tags.stored(sm.get(f"spool/{b}")) == UID and not tags.stored(sm.get(f"spool/{a}"))


def test_open_spool_refusals(tools, sm, env):
    _, data, _ = env
    (a,) = add(sm, item())
    with pytest.raises(Problem, match="exactly one"):
        tools.open_spool(spool=a, filament=1)
    with pytest.raises(Problem, match="exactly one"):
        tools.open_spool()
    with pytest.raises(Problem, match="No tag"):
        tools.open_spool(spool=a)
    tap(data)
    with pytest.raises(Problem, match="no sealed spool"):
        tools.open_spool(filament=999)


def test_open_spool_old_tap_note(tools, sm, env):
    _, data, _ = env
    (a,) = add(sm, item())
    tap(data, age=1200)
    assert "20 min" in tools.open_spool(spool=a, dry_run=True)["output"]


# ---------- preset tools ----------

@pytest.fixture
def store(monkeypatch):
    s = bbl.Store.load(BBL)
    monkeypatch.setattr(builds, "system_store", lambda: s)
    return s


def test_preset_status_lists_uncovered(tools, sm):
    add(sm, item(), item(vendor="ELEGOO", name="PETG Black", material="PETG", tare=154))
    lines_mod.ensure_saved("SUNLU", "PLA+", "PLA", bambu_parent=None, library=_lib(), store=None)
    st = tools.preset_status()
    names = {f["name"]: f for f in st["uncovered_filaments"]}
    assert set(names) == {"PLA+ Grey", "PETG Black"}
    assert names["PLA+ Grey"]["lines_for_vendor"] == ["SUNLU PLA+"]
    assert names["PETG Black"]["lines_for_vendor"] == []
    assert st["lines"] == 1 and st["last_build"] is None and st["waiting_for_desktop"] is False


def _lib():
    from filament_kit import library
    return library.load()


def test_list_and_add_filaments_to_line(tools, sm, spoolman_fake_store):
    (a,) = add(sm, item())
    fid = sm.get(f"spool/{a}")["filament"]["id"]
    lines_mod.ensure_saved("SUNLU", "PLA+", "PLA", bambu_parent=None, library=_lib(), store=None)
    out = tools.add_filaments_to_line("SUNLU PLA+", [fid])
    assert out["line_id"] == "sunlu--pla-plus" or fid in out["filament_ids"]
    (ln,) = tools.list_lines("sunlu")["lines"]
    assert ln["filament_ids"] == [fid] and ln["line"] == "SUNLU PLA+"
    assert json.loads(spoolman_fake_store["filaments"][fid]["extra"]["line"]) == "PLA+"
    assert tools.list_lines("elegoo")["lines"] == []
    with pytest.raises(Problem, match="already"):
        tools.add_filaments_to_line(ln["line_id"], [fid])
    with pytest.raises(Problem, match="no preset line"):
        tools.add_filaments_to_line("Nope Line", [fid])
    assert builds._request() is not None                         # a rebuild was requested


def test_add_line_and_find_parents(tools, sm, store):
    (a,) = add(sm, item(vendor="Acme", name="Silk Gold", material="PLA"))
    fid = sm.get(f"spool/{a}")["filament"]["id"]
    parents = tools.find_parents("pla basic")
    assert "Bambu PLA Basic" in parents["bs_templates"] and parents["synced"] is True
    assert all("pla" in p.lower() and "basic" in p.lower() for p in parents["bs_templates"])
    out = tools.add_line("Acme Silk", "Acme", [fid], "Generic PLA", "Bambu PLA Basic")
    ls = lines_mod.load()
    line = ls[out["line_id"]]
    assert line.product == "Silk" and line.bambu_parent == "Bambu PLA Basic" and line.parent_source == "user"
    assert line.filaments == [fid]
    with pytest.raises(Problem, match="exists"):
        tools.add_line("Acme Silk", "Acme", [fid], "Generic PLA", "Bambu PLA Basic")
    from filament_kit.profiles.errors import ProfileError
    with pytest.raises(ProfileError):
        tools.add_line("Acme Other", "Acme", [fid], "Generic PLA", "Not A Preset")


def test_generate_requests_a_build(tools):
    out = tools.generate()
    assert out["requested"] is True and builds._request() is not None


def test_preset_tools_need_the_presets_module(tools):
    cfg = config.load()
    cfg["modules"]["presets"] = False
    config.save(cfg)
    for call in (tools.preset_status, tools.generate, lambda: tools.list_lines(None)):
        with pytest.raises(Problem, match="presets module"):
            call()


# ---------- printer slots ----------

def _slot_service(env, tmp_path):
    _, data, url = env
    tok = tmp_path / "h2d_token"
    tok.write_text("sekrit\n", encoding="utf-8")
    cfg = config.load()
    cfg["slot_service"] = {"state_url": url + "/api/state", "set_url": url + "/set-slot", "token_file": str(tok)}
    config.save(cfg)
    return data


def test_printer_slots_via_slot_service(tools, sm, env, tmp_path, spoolman_fake_store):
    data = _slot_service(env, tmp_path)
    (a,) = add(sm, item())
    spoolman_fake_store["fields"]["spool"].append({"key": "active_tray", "name": "active_tray",
                                                   "field_type": "text", "entity_type": "spool", "order": 0})
    sm.patch(f"spool/{a}", {"extra": {"active_tray": json.dumps("H2D:ams0:tray1")}})
    data["slots"] = {"online": True, "state": "IDLE", "name": "job", "ams": [
        {"id": 0, "humidity": 20, "trays": [{"id": 1, "empty": False, "type": "PLA", "color": "FF0000FF",
                                              "preset_id": "GFA00", "active": True}]},
        {"id": 128, "trays": [{"id": 0, "empty": True}]},
        {"id": 254, "trays": [{"id": 0, "empty": False, "type": "TPU", "preset_id": ""}]}]}
    out = tools.printer_slots()
    assert out["printer_online"] is True and out["job"] == "job"
    by = {s["slot"]: s for s in out["slots"]}
    assert set(by) == {"AMS slot 2", "AMS HT 1", "External left"}
    assert by["AMS slot 2"]["preset"] == "Generic PLA" and by["AMS slot 2"]["feeding_now"] is True
    assert by["AMS HT 1"]["loaded"] is False and by["AMS HT 1"]["spool"] is None
    assert by["AMS slot 2"]["spool"]["spool_id"] == a and by["AMS slot 2"]["spool"]["name"] == "SUNLU PLA+ Grey"


def test_printer_set_slot_via_slot_service(tools, env, tmp_path):
    data = _slot_service(env, tmp_path)
    out = tools.printer_set_slot(5, "HT2", dry_run=True)
    assert data["set_calls"] == [{"body": {"spool_id": 5, "ams_id": 129, "tray_id": 0, "dry_run": True},
                                  "token": "sekrit"}]
    assert out["slot"] == "AMS HT 2" and "dry run" in out["note"]
    tools.printer_set_slot(5, "EXT-R", dry_run=False)
    assert data["set_calls"][-1]["body"] == {"spool_id": 5, "ams_id": 255, "tray_id": 0, "dry_run": False}
    tools.printer_set_slot(5, "3", dry_run=False)
    assert data["set_calls"][-1]["body"]["ams_id"] == 0 and data["set_calls"][-1]["body"]["tray_id"] == 2
    data["set_status"], data["set_reply"] = 409, {"ok": False, "status": "no_preset"}
    assert tools.printer_set_slot(5, "1", dry_run=False)["status"] == "no_preset"   # passed through
    with pytest.raises(Problem, match="unknown slot"):
        tools.printer_set_slot(5, "Z9")


@pytest.mark.parametrize("label, ams", [("1", (0, 0)), ("AMS slot 4", (0, 3)), ("ht3", (130, 0)),
                                        ("AMS HT 1", (128, 0)), ("EXT-L", (254, 0)),
                                        ("external right", (255, 0))])
def test_parse_slot(label, ams):
    assert slots.parse_slot(label) == ams


def test_printer_slots_neither_configured(tools):
    cfg = config.load()
    cfg["modules"]["printers"] = False
    config.save(cfg)
    with pytest.raises(Problem, match="slot_service"):
        tools.printer_slots()
    with pytest.raises(Problem, match="slot_service"):
        tools.printer_set_slot(1, "1")


class FakeKit:
    def __init__(self):
        self.loads = []

    def get(self, path):
        if path == "/api/printers":
            return {"printers": [{"id": "SER1", "name": "H2D", "configured": True, "state": "connected"}]}
        assert path == "/api/printers/SER1"
        return {"printer": {"id": "SER1", "name": "H2D", "state": "connected"},
                "status": {"gcode_state": "IDLE", "job": "", "ams": [
                    {"unit": 0, "label": "A", "kind": "ams", "slots": [
                        {"slot": 0, "label": "A1", "type": "PLA", "color_hex": "FFFFFF", "active": False,
                         "spool": {"id": 7, "name": "SUNLU PLA+ Grey"}}]}]}}

    def post(self, path, body):
        self.loads.append((path, body))
        return {"ok": True, "dry_run": body["dry_run"]}


def test_printer_tools_via_kit_bridge(sm):
    kit = FakeKit()
    tools = mcp_tools.Tools(sm, kit_api=kit)
    out = tools.printer_slots()
    (p,) = out["printers"]
    assert p["id"] == "SER1" and p["slots"][0]["slot"] == "A1" and p["slots"][0]["spool"]["id"] == 7
    tools.printer_set_slot(7, "1", dry_run=True)
    assert kit.loads == [("/api/printers/SER1/slots/A1/load", {"spool_id": 7, "dry_run": True})]
    tools.printer_set_slot(7, "HT2", dry_run=False)
    assert kit.loads[-1][0] == "/api/printers/SER1/slots/HT-B/load"
    with pytest.raises(Problem, match="printer"):
        tools.printer_set_slot(7, "A1", printer="OTHER")


# ---------- instructions ----------

def test_instructions_from_config():
    cfg = config._merge(config.DEFAULTS, {
        "locations": ["Sealed stock", "Bench Rack 2"],
        "placement": {"pla_location": "Rack 1", "box_prefix": "Cereal Box ", "box_count": 50,
                      "overflow": "Overflow bags", "sealed_location": "Sealed stock"},
        "intake": {"tare_hints": {"SUNLU": 213, "Bambu": 250}}})
    text = mcp_tools.instructions(cfg)
    for want in ("'Rack 1'", "'Cereal Box NN' (01-50)", "'Overflow bags'", "'Bench Rack 2'", "SUNLU 213",
                 "Bambu 250", "find_spools", "add_spools", "open_spool", "preset_status", "printer_slots"):
        assert want in text, want
    assert "SV08" not in text and "H2D" not in text
    cfg["web_instructions"] = "Owner text."
    assert mcp_tools.instructions(cfg) == "Owner text."


def test_instructions_without_boxes_or_hints():
    text = mcp_tools.instructions(config._merge(config.DEFAULTS, {}))
    assert "'Storage box NN'" not in text and "'Overflow'" in text and "200" in text


def test_kit_api_pairs_itself_once_and_renews_a_revoked_token(env):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    tmp_path, _, _ = env
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    seen = []

    async def printers(request):
        dev = pairing.check(request.headers.get("authorization", "").removeprefix("Bearer "))
        seen.append(dev)
        if dev is None:
            return JSONResponse({"error": "unauthorized", "message": "pair first"}, status_code=401)
        return JSONResponse({"printers": []})
    with readers_fake.Served(Starlette(routes=[Route("/api/printers", printers)]), free_port()) as url:
        kit = slots.KitApi(base_url=url)
        assert kit.get("/api/printers") == {"printers": []}
        tok_file = tmp_path / "state" / "web" / "kit_token"
        first = tok_file.read_text(encoding="utf-8").strip()
        assert [d["name"] for d in pairing.devices()] == ["web (MCP)"]
        kit.get("/api/printers")
        assert tok_file.read_text(encoding="utf-8").strip() == first          # reused, not re-paired
        pairing.revoke(pairing.devices()[0]["id"])
        assert kit.get("/api/printers") == {"printers": []}                    # 401 -> paired again once
        assert tok_file.read_text(encoding="utf-8").strip() != first
        assert seen[-2] is None and seen[-1] is not None
