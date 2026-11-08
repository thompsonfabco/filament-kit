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
                         "present": True, "spool": {"id": 7, "name": "SUNLU PLA+ Grey"}}]},
                    {"unit": 129, "label": "HT-B", "kind": "ams_ht", "slots": [{"slot": 0, "label": "HT-B"}]},
                    {"unit": 254, "label": "Ext-L", "kind": "ext", "slots": [{"slot": 0, "label": "Ext-L"}]},
                    {"unit": 255, "label": "Ext-R", "kind": "ext", "slots": [{"slot": 0, "label": "Ext-R"}]}]}}

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
    tools.printer_set_slot(7, "EXT-R", dry_run=False)
    assert kit.loads[-1][0] == "/api/printers/SER1/slots/Ext-R/load"
    tools.printer_set_slot(7, "ext-l", dry_run=False, printer="H2D")
    assert kit.loads[-1][0] == "/api/printers/SER1/slots/Ext-L/load"
    with pytest.raises(Problem, match="unknown slot"):
        tools.printer_set_slot(7, "B1")                    # not on this printer
    with pytest.raises(Problem, match="printer"):
        tools.printer_set_slot(7, "A1", printer="OTHER")
    by = {s["slot"]: s for s in tools.printer_slots("SER1")["printers"][0]["slots"]}
    assert by["A1"]["present"] is True and by["Ext-L"]["kind"] == "ext" and by["HT-B"]["unit"] == "HT-B"


@pytest.mark.parametrize("old, labels, new", [
    ("1", ["A1", "A2"], "A1"), ("AMS slot 4", None, "A4"), ("HT1", ["A1", "HT-A"], "HT-A"),
    ("ht3", None, "HT-C"), ("AMS HT 2", None, "HT-B"), ("EXT-L", ["A1", "Ext-L", "Ext-R"], "Ext-L"),
    ("external right", ["Ext-L", "Ext-R"], "Ext-R"), ("EXT-L", ["A1", "Ext"], "Ext"), ("EXT", ["Ext"], "Ext"),
    ("ext-r", None, "Ext-R"), ("b3", ["A1", "B3"], "B3"), ("AA4", None, "AA4"), ("HT-AB", ["HT-AB"], "HT-AB")])
def test_kit_label_any_printer_and_h2d_compat(old, labels, new):
    assert slots.kit_label(old, labels) == new


@pytest.mark.parametrize("bad, labels", [("Z9", ["A1"]), ("EXT-L", ["A1"]), ("a b", None), ("x" * 17, None)])
def test_kit_label_refuses(bad, labels):
    with pytest.raises(Problem, match="unknown slot"):
        slots.kit_label(bad, labels)


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


def test_kit_api_pairs_once_and_an_unpair_is_loud_until_the_next_start(env, caplog):
    import logging
    import os
    import stat
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
        kit.ensure_paired()                                                    # at start
        tok_file = config.paths().web / "kit_token"
        first = tok_file.read_text(encoding="utf-8").strip()
        assert [d["name"] for d in pairing.devices()] == ["web (MCP)"]
        if os.name != "nt":
            assert stat.S_IMODE(tok_file.stat().st_mode) == 0o600
        assert kit.get("/api/printers") == {"printers": []}
        kit.ensure_paired()
        assert tok_file.read_text(encoding="utf-8").strip() == first          # reused, not re-paired
        assert len(pairing.devices()) == 1
        # the owner unpairs it: a clear error (logged and shown), no silent re-pair while running
        pairing.revoke(pairing.devices()[0]["id"])
        with caplog.at_level(logging.ERROR, logger="filament_kit"):
            with pytest.raises(Problem, match="unpaired"):
                kit.get("/api/printers")
        assert any("web (MCP)" in r.getMessage() and "modules apply" in r.getMessage() for r in caplog.records)
        with pytest.raises(Problem, match="unpaired"):
            kit.get("/api/printers")                                           # stays refused
        assert pairing.devices() == [] and not tok_file.exists()
        # the next start pairs again
        again = slots.KitApi(base_url=url)
        again.ensure_paired()
        assert again.get("/api/printers") == {"printers": []}
        assert [d["name"] for d in pairing.devices()] == ["web (MCP)"]
        assert tok_file.read_text(encoding="utf-8").strip() != first


# ---------- Orca parents (Task 3's data model) ----------

def _orca_store(monkeypatch):
    from filament_kit.profiles.orca import OrcaStore
    s = OrcaStore(library={"Generic PLA @System": {"filament_type": "PLA"},
                           "Generic PLA Silk @System": {"filament_type": "PLA"},
                           "Generic PETG @System": {"filament_type": "PETG"}})
    monkeypatch.setattr(builds, "orca_store", lambda: s)
    return s


def test_find_parents_lists_orca_library(tools, store, monkeypatch):
    _orca_store(monkeypatch)
    out = tools.find_parents("pla")
    assert out["orca_parents"] == ["Generic PLA", "Generic PLA Silk"]
    assert tools.find_parents("silk")["orca_parents"] == ["Generic PLA Silk"]


def test_add_line_sets_the_orca_parent(tools, sm, store, monkeypatch):
    _orca_store(monkeypatch)
    (a,) = add(sm, item(vendor="Acme", name="Silk Gold", material="PLA"))
    fid = sm.get(f"spool/{a}")["filament"]["id"]
    out = tools.add_line("Acme Silk", "Acme", [fid], "Generic PLA Silk", "Bambu PLA Basic")
    line = lines_mod.load()[out["line_id"]]
    assert line.orca_parent == "Generic PLA Silk" and line.orca_parent_source == "user"
    assert out["orca_parent"] == "Generic PLA Silk"
    (ln,) = tools.list_lines("acme")["lines"]
    assert ln["orca_parent"] == "Generic PLA Silk"
    from filament_kit.profiles.errors import ProfileError
    (b,) = add(sm, item(vendor="Acme", name="Matte Red", material="PLA"))
    fid2 = sm.get(f"spool/{b}")["filament"]["id"]
    with pytest.raises(ProfileError):
        tools.add_line("Acme Matte", "Acme", [fid2], "Not In Orca", "Bambu PLA Basic")
    assert "acme--matte" not in lines_mod.load()                       # refused before anything was saved


def test_add_line_without_orca_parent_keeps_the_chosen_one(tools, sm, store, monkeypatch):
    _orca_store(monkeypatch)
    (a,) = add(sm, item(vendor="Acme", name="Basic White", material="PLA"))
    fid = sm.get(f"spool/{a}")["filament"]["id"]
    out = tools.add_line("Acme Basic", "Acme", [fid], "", "Bambu PLA Basic")
    line = lines_mod.load()[out["line_id"]]
    assert line.orca_parent == "Generic PLA" and line.orca_parent_source != "user"


# ---------- fix round 1 ----------

def _mcp_call(tools, name, args):
    import anyio
    from mcp.server.mcpserver import MCPServer
    m = MCPServer("t")
    mcp_tools.register(m, tools)

    async def run():
        return await m.call_tool(name, args)
    return anyio.run(run)


def test_mcp_add_of_an_existing_filament_keeps_its_line(tools, sm, spoolman_fake_store):
    # Ruling AC: Claude filling `line` on a routine add must not move a reused filament to another line
    (a,) = add(sm, item(line="PLA+"))
    fid = sm.get(f"spool/{a}")["filament"]["id"]
    sm.patch(f"filament/{fid}", {"extra": {"line": json.dumps("PLA+")}})
    body = {"items": [{**item(), "line": "Something Else", "bambu_parent": "Bambu PLA Basic"}], "dry_run": False}
    _mcp_call(tools, "add_spools", body)
    f = spoolman_fake_store["filaments"][fid]
    assert json.loads(f["extra"]["line"]) == "PLA+"
    assert len([s for s in spoolman_fake_store["spools"].values() if s["filament_id"] == fid]) == 2
    # a new filament keeps its line
    _mcp_call(tools, "add_spools", {"items": [{**item(name="PLA+ Red"), "line": "PLA+"}], "dry_run": False})
    new = next(f for f in spoolman_fake_store["filaments"].values() if f["name"] == "PLA+ Red")
    assert json.loads(new["extra"]["line"]) == "PLA+"


def test_tool_texts_round_1():
    from filament_kit.web.mcp_tools import SpoolItem
    assert "only for a new filament" in SpoolItem.model_fields["line"].description
    assert "only for a new filament" in SpoolItem.model_fields["bambu_parent"].description
    assert "only for a new filament" in mcp_tools.instructions(config._merge(config.DEFAULTS, {}))
    import anyio
    from mcp.server.mcpserver import MCPServer
    m = MCPServer("t")
    mcp_tools.register(m, mcp_tools.Tools(None))
    tools = {t.name: t for t in anyio.run(m.list_tools)}
    d = tools["add_filaments_to_line"].description
    assert "Refuses duplicates" not in d and "moves" in d and "extra.line" in d
    # P4: the old H2D names (EXT-L ...) work with both backends now, so the description no longer limits them
    assert "EXT-L" in json.dumps(tools["h2d_set_slot"].input_schema) and "Ext-L" in mcp_tools.SLOT_ARG
    assert "slot_service" not in tools["h2d_set_slot"].description


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_numbers_refused(tools, sm, bad):
    with pytest.raises(ValueError):
        tools.add_spools([item(net=bad)], dry_run=True)
    (a,) = add(sm, item())
    with pytest.raises(ValueError):
        inventory.open_spool(sm, a, UID, RULES, remaining=bad, dry=True)


def test_error_text_only_for_deliberate_refusals():
    assert mcp_tools.error_text(Problem("x")) == "x"
    assert mcp_tools.error_text(ValueError("bad value")) == "bad value"
    assert mcp_tools.error_text(KeyError("line")) is None
    assert mcp_tools.error_text(TypeError("boom")) is None
    assert mcp_tools.error_text(RuntimeError("boom")) is None


def test_half_configured_slot_service_refuses(tools, caplog):
    import logging
    cfg = config.load()
    cfg["slot_service"] = {"state_url": "http://x/api/state"}          # no set_url
    config.save(cfg)
    with caplog.at_level(logging.ERROR, logger="filament_kit"):
        with pytest.raises(Problem, match="slot_service"):
            tools.printer_slots()
    assert any("slot_service" in r.getMessage() for r in caplog.records)
    with pytest.raises(Problem, match="slot_service"):
        tools.printer_set_slot(1, "1")


def test_bridge_set_slot_quotes_a_hash_label():
    """final review M4: a clash-suffixed label ("A1#5") is quoted, never cut at '#' into a fragment."""
    kit = FakeKit()
    real = kit.get

    def get(path):
        out = real(path)
        if path != "/api/printers":
            out["status"]["ams"].append({"unit": 5, "label": "A1#5", "kind": "ams",
                                         "slots": [{"slot": 0, "label": "A1#5"}]})
        return out
    kit.get = get
    slots.bridge_set_slot(kit, 7, "A1#5", True)
    assert kit.loads == [("/api/printers/SER1/slots/A1%235/load", {"spool_id": 7, "dry_run": True})]


def test_preset_status_says_the_pc_sync_waits(tools, sm, monkeypatch):
    """PCBOTH R3: the phone / MCP status reads the same source as `filament-kit status`."""
    real = builds.status

    def waiting():
        st = real()
        st["pc"] = {"device_id": "d1", "last_upload": None,
                    "waiting": {"since": 1_793_700_000.0, "app": "Bambu Studio", "at": 1_793_703_600.0}}
        return st
    monkeypatch.setattr(builds, "status", waiting)
    st = tools.preset_status()
    assert st["pc_waiting"].startswith("PC sync waiting for Bambu Studio to close since 2026-11-0")
    monkeypatch.setattr(builds, "status", real)
    assert tools.preset_status()["pc_waiting"] is None
