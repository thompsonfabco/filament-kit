"""POST spools/{id} of the Hub page with Move > Automatic (`auto_location: true`), at the route, no browser: the page hands the placing
to the kit's `edit_spool`, so a sealed spool lands where sealed spools go and an opened one in the first place for its material
(R79), a dry run changes nothing, and a location together with auto_location is a 400 on `auto_location`."""
from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from filament_kit import inventory, setup_console, storage
from filament_kit.setup_console import spools_tab
from filament_kit.storage import MATERIALS, Location, Storage
from test_hub_page_audit import hub_app  # noqa: F401
from test_setup_page import CODE


@pytest.fixture(autouse=True)
def mounted(monkeypatch):
    real = setup_console.routes
    monkeypatch.setattr(setup_console, "routes", lambda page: real(page) + spools_tab.routes(page))


@pytest.fixture
def spools(hub_app, spoolman_url):  # noqa: F811
    storage.save(Storage([Location("Sealed stock", sealed=True), Location("Rack 1", fill=MATERIALS, materials=["PLA"]),
                          Location("Overflow", overflow=True, default_overflow=True)], converted=True))
    with httpx.Client() as c:
        fil = c.get(spoolman_url + "/api/v1/filament").json()[0]["id"]
        make = lambda **kw: c.post(spoolman_url + "/api/v1/spool", json={"filament_id": fil, "location": "Shelf", "remaining_weight": 800, **kw}).json()["id"]  # noqa: E731
        ids = {"sealed": make(comment=inventory.SEALED_COMMENT), "opened": make()}
    return ids


def post(hub_app, sid, body):  # noqa: F811
    c = TestClient(hub_app[0], base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    return c.post(f"/setup/api/spools/{sid}", json={"code": CODE, **body}, headers={"Origin": "https://127.0.0.1"})


def where(spoolman_url, sid):
    return httpx.get(f"{spoolman_url}/api/v1/spool/{sid}").json()["location"]


@pytest.mark.parametrize("kind,place", [("sealed", "Sealed stock"), ("opened", "Rack 1")])
def test_automatic_places_by_the_spools_own_state_and_a_dry_run_changes_nothing(hub_app, spools, spoolman_url, kind, place):  # noqa: F811
    sid = spools[kind]
    r = post(hub_app, sid, {"auto_location": True, "dry_run": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry"] is True and body["spool"]["location"] == place and body["before"]["location"] == "Shelf" and body["placed_text"]
    assert where(spoolman_url, sid) == "Shelf"                                  # the preview wrote nothing
    assert post(hub_app, sid, {"auto_location": True}).json()["dry"] is True     # dry_run is true unless sent as false
    assert where(spoolman_url, sid) == "Shelf"
    done = post(hub_app, sid, {"auto_location": True, "dry_run": False}).json()
    assert done["dry"] is False and done["spool"]["location"] == place and where(spoolman_url, sid) == place


def test_a_location_with_auto_location_is_a_400_on_auto_location(hub_app, spools, spoolman_url):  # noqa: F811
    r = post(hub_app, spools["sealed"], {"auto_location": True, "location": "Rack 1", "dry_run": False})
    assert r.status_code == 400 and r.json()["field"] == "auto_location"
    assert where(spoolman_url, spools["sealed"]) == "Shelf"
    r = post(hub_app, spools["sealed"], {"auto_location": "yes"})
    assert r.status_code == 400 and r.json()["field"] == "auto_location"
