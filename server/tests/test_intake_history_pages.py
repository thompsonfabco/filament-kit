"""The intake history on the setup page (Intake tab) and in the kit's own phone web app (History tab)."""
from __future__ import annotations

import pytest

from filament_kit import api, config, intake_history, inventory, modules
from filament_kit.spoolman import Spoolman
from test_setup_page import BASE, CODE, H, HOSTNAME, Helper, client, env, post  # noqa: F401  (env is a fixture)

JPEG = b"\xff\xd8\xff\xe0" + b"z" * 80
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2,
         "overflow": "Overflow", "sealed_location": "Sealed stock"}
ITEM = {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E", "net": 1000, "tare": 213,
        "density": 1.24, "count": 1, "nozzle": 220, "bed": 55, "sealed": True}


@pytest.fixture
def setup(env, spoolman_url):  # noqa: F811
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    app = api.create_app(sm, printers=object(), camera_hub=object(), mapper=object(),
                         enabled_modules=modules.enabled(config.load()) - {"printers", "klipper"},
                         setup={"helper": Helper(), "hosts": lambda: {HOSTNAME}})
    intake_history.stash_read("r1", [JPEG], {"items": [ITEM]}, "", None)
    r = inventory.add_and_link(sm, [dict(ITEM)], RULES, False, None)
    hid = intake_history.record_save(r.saved, source="phone", read_id="r1")
    return app, sm, hid, r.spool_ids[0]


def test_the_setup_page_lists_shows_edits_and_undoes(setup):
    app, sm, hid, sid = setup
    c = client(app)
    lst = c.get("/setup/api/intake/history").json()
    assert lst["records"][0]["id"] == hid and lst["records"][0]["photos"] == 1
    assert c.get(f"/setup/api/intake/history/{hid}/photos/1").content == JPEG
    assert c.get(f"/setup/api/intake/history/{hid}").json()["saved"][0]["spool_ids"] == [sid]
    r = post(c, f"intake/history/{hid}/apply", {"item": 0, "values": {"nozzle": 230}})
    assert r.status_code == 200 and r.json()["revisions"][0]["device"] == "setup page"
    assert sm.get(f"spool/{sid}")["filament"]["settings_extruder_temp"] == 230
    assert post(c, f"intake/history/{hid}/undo", {}).json()["state"] == "detected"


def test_a_setup_page_change_needs_the_code(setup):
    app, sm, hid, sid = setup
    c = client(app)
    r = post(c, f"intake/history/{hid}/apply", {"item": 0, "values": {"nozzle": 230}}, code=None)
    assert r.status_code == 403
    assert sm.get(f"spool/{sid}")["filament"]["settings_extruder_temp"] == 220


def test_the_setup_page_refuses_a_revision_when_ai_is_off(setup):
    app, sm, hid, sid = setup
    cfg = config.load()
    cfg.setdefault("modules", {})["ai_intake"] = False
    config.save(cfg)
    r = post(client(app), f"intake/history/{hid}/revise", {"note": "brand is X"})
    assert r.status_code == 409


def test_the_setup_page_has_the_intake_tab(setup):
    app, *_ = setup
    page = client(app).get("/setup").text
    assert "/setup/setup_intake.js" in page and client(app).get("/setup/setup_intake.js").status_code == 200


def test_the_kits_phone_web_app_has_the_history(setup):
    app, sm, hid, sid = setup
    c = client(app)
    assert "data-history='1'" in c.get("/intake").text
    assert c.get("/intake/api/history").json()["records"][0]["id"] == hid
    assert c.get(f"/intake/api/history/{hid}/photos/1").content == JPEG
    r = c.post(f"/intake/api/history/{hid}/apply", json={"item": 0, "values": {"vendor": "Polymaker"}}, headers=H)
    assert r.status_code == 200 and r.json()["state"] == "edited"
    assert sm.get(f"spool/{sid}")["filament"]["vendor"]["name"] == "Polymaker"
    assert c.post(f"/intake/api/history/{hid}/undo", json={}, headers=H).json()["state"] == "detected"
    assert c.post(f"/intake/api/history/{hid}/apply", json={"item": 0, "values": {"x": 1}}, headers=H).status_code == 400
    assert c.post(f"/intake/api/history/{hid}/undo", json={}).status_code == 403          # no Origin
    assert client(app, who=("203.0.113.9", 4000)).get("/intake/api/history").status_code == 403


def test_the_web_modules_page_has_no_history():
    from filament_kit.web.intake_app import IntakeApp

    class Tools:
        sm = None

        def cfg(self):
            return {"placement": {}, "locations": []}
    app = IntakeApp(Tools(), public_url="https://example.test/f", lan_cidrs=[])
    assert app.history is False and not [r for r in app.routes() if "/history" in getattr(r, "path", "")]
