"""intake.read_context: orders, station state and a fresh unknown tag for a label read, used by both the kit
server's /api/intake/read and the web process's /intake/api/read."""
from __future__ import annotations

import json

import pytest
from fakes import readers_fake
from fakes.claude_fake import FakeClaude
from starlette.testclient import TestClient

from conftest import free_port
from filament_kit import config, intake, modules, pairing, tagsources
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman
from filament_kit.station_client import StationClient

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
ORDERS = [{"order": "111-1", "date": "2026-10-01", "asin": "B0TEST", "title": "SUNLU PLA 1kg", "qty": 1,
           "unit_price": 18.99, "seller": "SUNLU"}]
READ = {"questions": [], "items": [{
    "photos": [0], "existing_filament_id": None, "vendor": "SUNLU", "name": "PLA Grey", "material": "PLA",
    "color_hex": "888888", "net": 1000, "tare": 213, "density": 1.24, "count": 1, "nozzle": 210, "bed": 60,
    "nozzle_range": "200-220", "bed_range": "50-70", "lot": None, "note": "", "estimates": [],
    "sealed": True, "sealed_reason": "in bag", "line": "PLA", "order": None, "price_per_kg": None,
    "price_line": None}]}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    tagsources._failed.clear()


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def readers():
    data = readers_fake.new_data()
    with readers_fake.Served(readers_fake.app(data)) as url:
        yield data, url


def _cfg(tmp_path, url, *, orders_on=True, orders_file=True) -> dict:
    f = tmp_path / "orders.json"
    if orders_file:
        f.write_text(json.dumps({"items": ORDERS}), encoding="utf-8")
    mods = {n: True for n in modules.MODES["server"] | {"ai_intake"}}  # orders needs ai_intake
    mods["orders"] = orders_on
    return {"modules": mods, "orders": {"file": str(f)}, "station": {"url": url},
            "tag_sources": [{"name": "printer", "url": url + "/last-tag"}]}


def test_context_orders_station_and_fresh_tag(tmp_path, sm, readers):
    data, url = readers
    data["tag"] = {"status": "ok", "nfc_id": "4:a1:b2:c3", "read_at_unix": 1, "age_seconds": 12}
    data["state"] = {"tag": None, "last_weight": {"grams": 1100, "age_seconds": 5, "held": False}}
    ctx = intake.read_context(_cfg(tmp_path, url), sm, StationClient(url))
    assert ctx["orders"] == ORDERS
    assert ctx["station_state"]["last_weight"]["grams"] == 1100
    assert ctx["fresh_tag"]["nfc_id"] == "4:a1:b2:c3" and ctx["fresh_tag"]["age_seconds"] == 12


def test_context_orders_only_when_on_and_file_exists(tmp_path, sm, readers):
    _, url = readers
    assert intake.read_context(_cfg(tmp_path, url, orders_on=False), sm, None)["orders"] is None
    (tmp_path / "other").mkdir()
    assert intake.read_context(_cfg(tmp_path / "other", url, orders_file=False), sm, None)["orders"] is None


def test_context_dead_station_and_no_tag(tmp_path, sm):
    dead = f"http://127.0.0.1:{free_port()}"
    ctx = intake.read_context(_cfg(tmp_path, dead), sm, StationClient(dead))
    assert ctx["station_state"] is None and ctx["fresh_tag"] is None
    assert intake.read_context({}, sm, None) == {"orders": None, "station_state": None, "fresh_tag": None}


def test_context_skips_the_reader_when_the_app_sent_a_tag(tmp_path, sm, readers):
    data, url = readers
    data["tag"] = {"status": "ok", "nfc_id": "4:a1:b2:c3", "read_at_unix": 1, "age_seconds": 12}
    assert intake.read_context(_cfg(tmp_path, url), sm, None, app_tag=True)["fresh_tag"] is None


def test_api_read_passes_the_context(tmp_path, sm, readers):
    data, url = readers
    data["tag"] = {"status": "ok", "nfc_id": "4:a1:b2:c3", "read_at_unix": 1, "age_seconds": 12}
    data["state"] = {"tag": None, "last_weight": {"grams": 1100, "age_seconds": 5, "held": False}}
    config.save(_cfg(tmp_path, url))
    fake = FakeClaude(READ)
    c = TestClient(create_app(sm=sm, claude=fake))
    tok = pairing.redeem_code(pairing.issue().code)
    r = c.post("/api/intake/read", headers={"Authorization": f"Bearer {tok}"},
               files=[("photo", ("a.jpg", JPEG, "image/jpeg"))])
    assert r.status_code == 200, r.text
    out = r.json()
    it = out["items"][0]
    assert it["sealed"] is False and it["gross"] == 1100                 # fresh tag + station weight
    assert out["tag"]["nfc_id"] == "4:a1:b2:c3" and out["scale"]["grams"] == 1100
    text = json.dumps(fake.calls[0]["messages"])
    assert "B0TEST" in text                                               # the orders block
    # the Android app's own tag still wins over the reader
    r = c.post("/api/intake/read", headers={"Authorization": f"Bearer {tok}"},
               files=[("photo", ("a.jpg", JPEG, "image/jpeg"))], data={"tag": "4:1:2:3"})
    assert r.json()["tag"] == {"nfc_id": "4:1:2:3"}
