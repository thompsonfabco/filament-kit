"""API routes for Klipper printers (bridge.family dispatch); Bambu routes keep their shape."""
import pytest
from starlette.testclient import TestClient

from filament_kit import config, hostaddr, pairing
from filament_kit.api import create_app
from filament_kit.bridge import family, registry
from filament_kit.bridge.klipper import discovery
from filament_kit.bridge.klipper.manager import KlipperFamily

ON = frozenset({"server", "printers", "klipper"})


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({})


class FakeBambu:
    def state(self, pid):
        return "connected"

    def summary(self, pid):
        return {"gcode_state": "IDLE", "percent": 0, "remaining_min": 0, "job": None}

    def status(self, pid):
        return {"ams": []}

    def sync(self):
        pass

    def wait_settled(self, pid, timeout):
        return "connected"


class FakeKlipper(FakeBambu):
    def __init__(self):
        self.loads, self.synced = [], 0

    def sync(self):
        self.synced += 1

    def verified(self, pid):
        return False

    def camera_kind(self, pid):
        return "mjpeg"

    def load(self, sm, pid, label, spool_id, dry, *, sealed_location):
        self.loads.append((pid, label, spool_id, dry))
        return {"slot": {"label": label, "location": f"SV08 MAX – {label}"}, "preset": None, "dry_run": dry,
                "problems": [], "spool": {"id": spool_id}, "confirmed": None if dry else True, "moved_back": []}

    def unload(self, sm, pid, label, dry, *, sealed_location):
        return {"spool": {"id": 1, "location": "Shelf"}, "slot": {"label": label}, "preset": None,
                "dry_run": dry, "moved_back": [{"id": 1, "location": "Shelf"}]}

    def scan(self, subnet=None):
        if subnet == "10.0.0.0/16":
            raise ValueError("scan at most a /24 (256 addresses)")
        return [{"id": "x", "host": "192.0.2.10", "port": 7125, "name": "x", "configured": False}]

    def usage(self, pid, days):
        return [{"id": "k-1", "source": "moonraker", "can_undo": False}]


def _client(klipper=FakeKlipper()):
    app = create_app(object(), printers=family.Printers(bambu=FakeBambu(), klipper=klipper), camera_hub=object(),
                     mapper=object(), enabled_modules=ON)
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
    return c


def test_api_list_has_family():
    registry.upsert(registry.Printer("S1", "H2D", "H2D", "10.0.0.5", "12345678", True))
    registry.add_klipper("SV08 MAX", "sv08.home.arpa")
    by = {p["id"]: p for p in _client().get("/api/printers").json()["printers"]}
    assert by["S1"]["family"] == "bambu" and "host" not in by["S1"]
    k = by["sv08-max"]
    assert (k["family"], k["host"], k["verified"], k["camera"]) == ("klipper", "sv08.home.arpa", False,
                                                                     {"kind": "mjpeg"})
    assert k["state"] == "connected"


def test_api_list_klipper_model_name():
    """model_name (the app session's field) comes from klipper_hardware.xml; generic falls back to the model text."""
    from filament_kit.bridge.klipper import hardware as kh

    class Named(FakeKlipper):
        key = "SOVOL-SV08-MAX"

        def model(self, pid):
            return kh.load().model(self.key), None, None

    registry.add_klipper("SV08 MAX", "sv08.home.arpa")
    named = Named()
    k = _client(named).get("/api/printers").json()["printers"][0]
    assert k["model_name"] == kh.load().model("SOVOL-SV08-MAX").name
    named.key = "generic"
    k = _client(named).get("/api/printers").json()["printers"][0]
    assert k["model_name"] == (registry.load()["sv08-max"].model or "")


def test_add_klipper_printer():
    kf = FakeKlipper()
    r = _client(kf).post("/api/printers", json={"family": "klipper", "host": "sv08.home.arpa",
                                                "name": "SV08 MAX"})
    assert r.status_code == 200, r.text
    p = r.json()["printer"]
    assert (p["id"], p["family"]) == ("sv08-max", "klipper")
    assert kf.synced == 1
    assert "api_key" not in r.text


@pytest.mark.parametrize("body", [{"family": "klipper"}, {"family": "klipper", "host": "a b"},
                                  {"family": "klipper", "host": "h", "port": 70000},
                                  {"family": "prusa", "host": "h"}])
def test_add_klipper_bad_body(body):
    assert _client().post("/api/printers", json=body).status_code == 400


def test_map_on_klipper_is_409_not_supported():
    registry.add_klipper("SV08 MAX", "h")
    c = _client()
    for r in (c.post("/api/printers/sv08-max/map"), c.get("/api/printers/sv08-max/map")):
        assert r.status_code == 409 and r.json()["error"] == "not_supported"


def test_load_routes_to_klipper():
    registry.add_klipper("SV08 MAX", "h")
    kf = FakeKlipper()
    r = _client(kf).post("/api/printers/sv08-max/slots/T0/load", json={"spool_id": 7, "dry_run": False})
    assert r.status_code == 200, r.text
    assert r.json()["confirmed"] is True
    assert kf.loads == [("sv08-max", "T0", 7, False)]


def test_unload_routes_to_klipper():
    registry.add_klipper("SV08 MAX", "h")
    r = _client().post("/api/printers/sv08-max/slots/T0/unload", json={"dry_run": False})
    assert r.status_code == 200 and r.json()["location"] == "Shelf"


def test_usage_routes_to_klipper():
    registry.add_klipper("SV08 MAX", "h")
    r = _client().get("/api/printers/sv08-max/usage")
    assert r.json()["entries"][0]["source"] == "moonraker"


def test_undo_klipper_entry_409():
    r = _client().post("/api/usage/k-123/undo")
    assert r.status_code == 409 and r.json()["error"] == "recorded_by_moonraker"


def test_klipper_load_with_module_off_is_409():
    registry.add_klipper("SV08 MAX", "h")
    r = _client(klipper=None).post("/api/printers/sv08-max/slots/T0/load", json={"spool_id": 7})
    assert r.status_code == 409 and r.json()["error"] == "module_off"


def test_klipper_routes_without_printers_module():
    """Klipper on, the Bambu module off: the printer routes still answer for Klipper printers."""
    registry.add_klipper("SV08 MAX", "h")
    app = create_app(object(), printers=family.Printers(bambu=None, klipper=FakeKlipper()), camera_hub=object(),
                     mapper=object(), enabled_modules=frozenset({"server", "klipper"}))
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
    r = c.get("/api/printers")
    assert r.status_code == 200 and r.json()["printers"][0]["family"] == "klipper"


def test_scan_route():
    c = _client()
    r = c.post("/api/printers/scan", json={})
    assert r.status_code == 200 and r.json()["found"][0]["host"] == "192.0.2.10"
    assert c.post("/api/printers/scan", json={"subnet": "10.0.0.0/16"}).status_code == 400
    assert _client(klipper=None).post("/api/printers/scan", json={}).json()["error"] == "module_off"


@pytest.mark.parametrize("host", ["voron.local", "Voron-2.local", "printer.home.arpa", "printer", "192.0.2.20"])
def test_add_klipper_takes_a_name_or_an_address_and_stores_it_as_typed(host):
    """DNS and mDNS names as well as IPs: resolved when used, so a changed address doesn't strand the printer. A Klipper
    printer never needs an Access Code."""
    r = _client().post("/api/printers", json={"family": "klipper", "host": host})
    assert r.status_code == 200, r.text
    assert registry.load()[r.json()["printer"]["id"]].host == host


def test_scan_route_refuses_a_public_range_on_the_real_family():
    kf = KlipperFamily(None)
    r = _client(kf).post("/api/printers/scan", json={"subnet": "1.1.1.0/24"})
    assert r.status_code == 400 and "private" in r.text


def test_printer_get_reports_a_refused_klipper_override(tmp_path):
    from filament_kit.bridge.klipper import hardware as kh
    kh._reset_cache()
    try:
        c = _client()
        pid = c.post("/api/printers", json={"family": "klipper", "host": "voron.home.arpa"}).json()["printer"]["id"]
        assert not c.get(f"/api/printers/{pid}").json()["hardware"]["errors"]
        (tmp_path / "etc" / "klipper_hardware.xml").write_text("<klipper-hardware version='9'><nope", "utf-8")
        errors = c.get(f"/api/printers/{pid}").json()["hardware"]["errors"]
        assert errors and "klipper_hardware.xml" in " ".join(errors)
    finally:
        kh._reset_cache()


def test_add_klipper_refuses_the_address_of_a_printer_added_by_name(monkeypatch):
    table = {"voron.local": {"192.0.2.20"}, "192.0.2.20": {"192.0.2.20"}}
    monkeypatch.setattr(hostaddr, "addresses", lambda host, **kw: table.get(host, set()))
    c = _client()
    assert c.post("/api/printers", json={"family": "klipper", "host": "voron.local", "name": "Voron"}).status_code == 200
    r = c.post("/api/printers", json={"family": "klipper", "host": "192.0.2.20"})
    assert r.status_code == 400 and "already added as Voron" in r.text


def test_add_klipper_refuses_an_address_a_found_entry_holds_for_a_printer_added_by_name(monkeypatch):
    table = {"voron.local": {"192.0.2.20"}, "192.0.2.20": {"192.0.2.20"}}
    monkeypatch.setattr(hostaddr, "addresses", lambda host, **kw: table.get(host, set()))
    c = _client()
    assert c.post("/api/printers", json={"family": "klipper", "host": "voron.local", "name": "Voron"}).status_code == 200
    registry.detected_klipper("192.0.2.20", 7125, lookups=False)
    r = c.post("/api/printers", json={"family": "klipper", "host": "192.0.2.20"})
    assert r.status_code == 400 and "already added as Voron" in r.text
    assert sum(p.configured for p in registry.load().values()) == 1


def test_add_klipper_twice_is_refused_and_says_which():
    c = _client()
    body = {"family": "klipper", "host": "voron.home.arpa", "name": "Voron"}
    assert c.post("/api/printers", json=body).status_code == 200
    r = c.post("/api/printers", json={**body, "name": "Again"})
    assert r.status_code == 400 and "Voron" in r.text


def test_manual_map_on_klipper_is_the_klipper_session():
    """Map by loading filament: a Klipper printer has its own session behind the same routes (was 409)."""
    from filament_kit.bridge.klipper import manual as kmanual
    from test_klipper_manual_map import StubFamily
    registry.add_klipper("SV08 MAX", "h")
    k = FakeKlipper()
    k.manual = kmanual.KlipperManualMaps(StubFamily(labels=("T0", "T1")))
    c = _client(k)
    r = c.post("/api/printers/sv08-max/manual-map/start", json={})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["step"]["position"]["label"] == "T0" and s["reports_loads"] is True
    assert c.get("/api/printers/sv08-max/manual-map").json()["session"] == s["session"]
    r = c.post("/api/printers/sv08-max/manual-map/confirm",
               json={"session": s["session"], "position": "T0", "reported": {"label": "T1"}})
    assert r.status_code == 409 and r.json()["error"] == "stale"          # the printer showed nothing active
    r = c.post("/api/printers/sv08-max/manual-map/stop", json={"session": s["session"]})
    assert r.status_code == 200 and r.json()["open"] is False
    assert c.post("/api/printers/sv08-max/map").status_code == 409        # the automatic job stays Bambu's
