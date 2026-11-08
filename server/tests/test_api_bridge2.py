"""Bridge part 2 routes: slot mapping, loading / unloading, usage and undo (route-contract.md)."""
import copy
import json
import logging
import threading
import time

import pytest
from starlette.testclient import TestClient

from filament_kit import config, pairing, profiles
from filament_kit.api import create_app
from filament_kit.bridge import ams, calib3mf, loading, mapping, registry, slottest, usage
from filament_kit.bridge.calib3mf import CalibResult
from filament_kit.bridge.connection import PrinterOffline
from filament_kit.bridge.slottest import PrinterBusy, SlotTestResult
from filament_kit.spoolman import SpoolmanError

CODE = "86429753"
SERIAL = "0948AD111111111"
NAME = "Office H2D"
LOC_A1 = f"{NAME} – AMS A1"
REPORT = {
    "gcode_state": "IDLE", "nozzle_diameter": "0.4",
    "ams": {"ams": [{"id": "0", "tray": [
        {"id": "0", "tray_type": "PLA", "tray_color": "FF0000FF", "tray_info_idx": "Pa111111"},
        {"id": "1", "tray_type": "PETG", "tray_color": "1A1A1AFF", "tray_info_idx": "Pa222222"}]}]},
}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({})
    monkeypatch.setattr(loading, "CONFIRM_TIMEOUT", 0.2)
    registry.upsert(registry.Printer(SERIAL, NAME, "O1D", "10.0.0.5", CODE, True, cert_fp="cd" * 32))


class FakeManager:
    def __init__(self):
        self.st = "connected"
        self.report = copy.deepcopy(REPORT)
        self.writes = []
        self.reply = {"result": "success"}

    def sync(self):
        pass

    def state(self, serial):
        return self.st if serial == SERIAL else "not_configured"

    def wait_settled(self, serial, timeout):
        return self.state(serial)

    def summary(self, serial):
        return {"gcode_state": self.report["gcode_state"], "percent": 0, "remaining_min": 0, "job": None}

    def status(self, serial):
        return None

    def wait_report(self, serial, predicate, timeout):
        if self.st not in ("connected", "needs_developer_mode"):
            return None
        return self.report if predicate(self.report) else None

    def set_slot(self, serial, ams_id, tray_id, setting, kind=None):
        self.writes.append((ams_id, tray_id, dict(setting)))
        if self.reply.get("result") == "success":
            for u in self.report["ams"]["ams"]:
                if int(u["id"]) == ams_id:
                    for t in u["tray"]:
                        if int(t["id"]) == tray_id:
                            t.update({k: setting[k] for k in ("tray_info_idx", "tray_type", "tray_color")})
        return self.reply


class FakeSM:
    """Just enough of the Spoolman client for loading / usage."""

    def __init__(self):
        fil = {"id": 7, "name": "PLA+ Grey", "material": "PLA", "color_hex": "808080", "vendor": {"name": "SUNLU"}}
        self.spools = {
            1: {"id": 1, "location": "Rack 1", "filament": fil, "extra": {}},
            2: {"id": 2, "location": LOC_A1, "filament": fil, "extra": {}},
        }
        self.used = []

    def get(self, path):
        if path == "spool":
            return [copy.deepcopy(s) for s in self.spools.values()]
        sid = int(path.split("/")[1])
        if sid not in self.spools:
            raise SpoolmanError("not found", 404)
        return copy.deepcopy(self.spools[sid])

    def patch(self, path, body):
        sid = int(path.split("/")[1])
        self.spools[sid].update(body)
        return self.spools[sid]

    def use(self, spool_id, grams):
        self.used.append((spool_id, grams))


@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def sm():
    return FakeSM()


@pytest.fixture
def mapper(mgr):
    return mapping.Mapper(mgr)


@pytest.fixture
def client(mgr, sm, mapper):
    c = TestClient(create_app(sm, printers=mgr, mapper=mapper))
    c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
    return c


@pytest.fixture
def stubs(monkeypatch):
    cfg = {"gate": None, "calib": None}

    def st_run(manager, serial, on_step, should_stop=None):
        on_step("Reading the AMS slots")
        if cfg["gate"] is not None:
            cfg["gate"].wait(5)
        return SlotTestResult(confirmed={"A1": {"ams_id": 0, "tray_id": 0}, "A2": {"ams_id": 0, "tray_id": 1}})

    def calib_run(manager, serial, slotmap, should_stop=None):
        if cfg["calib"] is not None:
            return cfg["calib"]
        return CalibResult(decoding={"A1": 0, "A2": 1}, consistent=True)
    monkeypatch.setattr(slottest, "run", st_run)
    monkeypatch.setattr(calib3mf, "run", calib_run)
    return cfg


def err(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["error"] == code and isinstance(body["message"], str) and body["message"]


def preset(monkeypatch):
    monkeypatch.setattr(profiles, "preset_for", lambda fil, model, nozzle: profiles.PresetRef(
        "P7a1b2c3", "SUNLU PLA+ Grey @Bambu Lab H2D 0.4 nozzle", 200, 230, "PLA"))


# ---------------------------------------------------------------- auth

def test_new_routes_need_a_token(mgr, sm):
    c = TestClient(create_app(sm, printers=mgr))
    for r in (c.post(f"/api/printers/{SERIAL}/map"), c.get(f"/api/printers/{SERIAL}/map"),
              c.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1}),
              c.post(f"/api/printers/{SERIAL}/slots/A1/unload", json={}),
              c.get(f"/api/printers/{SERIAL}/usage"), c.post(f"/api/usage/{'a' * 32}/undo")):
        err(r, 401, "unauthorized")


# ---------------------------------------------------------------- map

def wait_state(client, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/api/printers/{SERIAL}/map").json()
        if body["state"] != "running":
            return body
        time.sleep(0.01)
    raise AssertionError("still running")


def test_map_none_before_any_job(client):
    r = client.get(f"/api/printers/{SERIAL}/map")
    assert r.status_code == 200
    assert r.json() == {"state": "none", "step": "", "slots": [], "calibrated": False, "observe": True,
                        "problems": [], "notes": [], "scheme_unsettled": False, "problems_old": False, "finished": None, "stale": False,
                        "remapping": False, "scheme": None, "suspect": False}


def test_map_job_runs_and_reports(client, stubs, caplog):
    gate = threading.Event()
    stubs["gate"] = gate
    with caplog.at_level(logging.INFO, logger="filament_kit"):
        r = client.post(f"/api/printers/{SERIAL}/map")
        assert r.status_code == 202
        job = r.json()["job_id"]
        assert isinstance(job, str) and job
        running = client.get(f"/api/printers/{SERIAL}/map").json()
        assert running["state"] == "running" and running["step"] == "Reading the AMS slots"
        err(client.post(f"/api/printers/{SERIAL}/map"), 409, "already_running")
        gate.set()
        body = wait_state(client)
    assert body["state"] == "done" and body["calibrated"] is True and body["observe"] is False
    assert body["problems"] == []
    assert sorted(body["slots"], key=lambda s: s["label"]) == [
        {"label": "A1", "ams_id": 0, "tray_id": 0, "global": 0},
        {"label": "A2", "ams_id": 0, "tray_id": 1, "global": 1}]
    assert set(body) == {"state", "step", "slots", "calibrated", "observe", "problems", "notes", "scheme_unsettled", "problems_old",
                         "finished", "stale", "remapping",
                         "scheme", "suspect"}
    audit = [rec.getMessage() for rec in caplog.records if "slot mapping" in rec.getMessage()]
    assert any(f"serial={SERIAL}" in a and "device_id=" in a for a in audit)


def test_map_observe_mode_on_inconsistent_calibration(client, stubs):
    stubs["calib"] = CalibResult(decoding={"A1": 0, "A2": 3}, consistent=False,
                                 problems=["A2: sent slot 1, the printer reported 3"])
    assert client.post(f"/api/printers/{SERIAL}/map").status_code == 202
    body = wait_state(client)
    assert body["calibrated"] is False and body["observe"] is True
    assert "A2: sent slot 1, the printer reported 3" in body["problems"]


def test_map_refusals(client, mgr, stubs):
    mgr.report["gcode_state"] = "RUNNING"
    err(client.post(f"/api/printers/{SERIAL}/map"), 409, "printer_busy")
    mgr.report["gcode_state"] = "IDLE"
    mgr.st = "offline"
    err(client.post(f"/api/printers/{SERIAL}/map"), 409, "printer_offline")
    mgr.st = "cert_changed"
    err(client.post(f"/api/printers/{SERIAL}/map"), 409, "cert_changed")
    err(client.post("/api/printers/NOPE/map"), 404, "not_found")
    err(client.get("/api/printers/NOPE/map"), 404, "not_found")


# ---------------------------------------------------------------- load / unload

def test_load_dry_run_shape(client, mgr, sm, monkeypatch):
    preset(monkeypatch)
    r = client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": True})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["slot"]["label"] == "A1" and b["slot"]["ams_id"] == 0 and b["slot"]["tray_id"] == 0
    assert b["preset"]["filament_id"] == "P7a1b2c3" and b["preset"]["name"].startswith("SUNLU")
    assert b["nozzle_mm"] == 0.4 and b["nozzle_assumed"] is False
    assert b["confirmed"] is False and b["problems"] == []              # never null on a dry run
    assert b["moved_back"] == [{"id": 2, "location": "Sealed stock"}]    # spool 2 would leave A1
    assert b["spool"]["id"] == 1 and b["spool"]["location"] == LOC_A1   # what would happen
    assert mgr.writes == [] and sm.spools[1]["location"] == "Rack 1"


def test_load_default_is_a_dry_run(client, mgr, monkeypatch):
    preset(monkeypatch)
    r = client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1})
    assert r.status_code == 200 and r.json()["confirmed"] is False and mgr.writes == []


def test_load_for_real(client, mgr, sm, monkeypatch, caplog):
    preset(monkeypatch)
    with caplog.at_level(logging.INFO, logger="filament_kit"):
        r = client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["confirmed"] is True and b["problems"] == []
    assert b["moved_back"] == [{"id": 2, "location": "Sealed stock"}]
    assert mgr.writes and mgr.writes[0][2]["tray_info_idx"] == "P7a1b2c3"
    assert sm.spools[1]["location"] == LOC_A1 and sm.spools[2]["location"] == "Sealed stock"
    assert any("load" in rec.getMessage() and f"serial={SERIAL}" in rec.getMessage() and "spool=1" in
               rec.getMessage() for rec in caplog.records)


def test_load_no_preset(client, mgr):
    err(client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False}),
        409, "no_preset")
    assert mgr.writes == []


def test_load_busy_offline_cert_changed(client, mgr, monkeypatch):
    preset(monkeypatch)
    url = f"/api/printers/{SERIAL}/slots/A1/load"
    # Ruling BK: mid-print, only the slot that feeds the job is refused (slot_in_use); another slot goes through
    mgr.report["gcode_state"] = "PREPARE"
    mgr.report["ams"]["tray_now"] = "0"                  # A1 feeds the job
    err(client.post(url, json={"spool_id": 1, "dry_run": False}), 409, "slot_in_use")
    assert mgr.writes == []
    mgr.report["ams"]["tray_now"] = "1"                  # A2 feeds it: A1 is free
    mgr.report["mapping"] = [1]                          # the job uses A2 only (dual nozzle, no snow: Ruling BM)
    assert client.post(url, json={"spool_id": 1, "dry_run": True}).status_code == 200
    mgr.report["gcode_state"] = "IDLE"
    mgr.st = "offline"
    err(client.post(url, json={"spool_id": 1, "dry_run": False}), 409, "printer_offline")
    mgr.st = "cert_changed"
    err(client.post(url, json={"spool_id": 1, "dry_run": False}), 409, "cert_changed")
    assert mgr.writes == []


def test_load_and_unload_refused_during_mapping(client, mgr, sm, stubs, monkeypatch):
    preset(monkeypatch)
    gate = threading.Event()
    stubs["gate"] = gate
    assert client.post(f"/api/printers/{SERIAL}/map").status_code == 202
    try:
        for url, body in ((f"/api/printers/{SERIAL}/slots/A1/load", {"spool_id": 1, "dry_run": False}),
                          (f"/api/printers/{SERIAL}/slots/A1/load", {"spool_id": 1, "dry_run": True}),
                          (f"/api/printers/{SERIAL}/slots/A1/unload", {"dry_run": False})):
            r = client.post(url, json=body)
            err(r, 409, "already_running")
            assert "mapping" in r.json()["message"]
    finally:
        gate.set()
        wait_state(client)
    assert mgr.writes == [] and sm.spools[2]["location"] == LOC_A1


def test_load_and_unload_refused_while_another_process_maps(client, mapper, sm, monkeypatch):
    """`filament-kit printer map` in another process: the lock file says so (Mapper.in_progress)."""
    preset(monkeypatch)
    monkeypatch.setattr(mapping._ProcessLock, "held_elsewhere", staticmethod(lambda serial: serial == SERIAL))
    assert mapper.in_progress(SERIAL) is True
    err(client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False}),
        409, "already_running")
    err(client.post(f"/api/printers/{SERIAL}/slots/A1/unload", json={"dry_run": False}), 409, "already_running")
    assert sm.spools[2]["location"] == LOC_A1


def test_load_write_refused(client, mgr, monkeypatch):
    preset(monkeypatch)
    mgr.reply = {"result": "fail", "reason": "slot locked"}
    err(client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False}),
        409, "write_refused")


def test_load_write_refused_needs_developer_mode(client, mgr, monkeypatch):
    preset(monkeypatch)
    mgr.reply = {"result": "fail", "reason": "mqtt message verify failed", "err_code": 84033543}

    def refuse(serial, ams_id, tray_id, setting, kind=None):
        mgr.st = "needs_developer_mode"      # the Manager flags it on such a reply
        return mgr.reply
    mgr.set_slot = refuse
    err(client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False}),
        409, "needs_developer_mode")


def test_load_not_found(client, monkeypatch):
    preset(monkeypatch)
    err(client.post(f"/api/printers/{SERIAL}/slots/D4/load", json={"spool_id": 1}), 404, "not_found")
    err(client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 99}), 404, "not_found")
    err(client.post("/api/printers/NOPE/slots/A1/load", json={"spool_id": 1}), 404, "not_found")


@pytest.mark.parametrize("body", [{}, {"spool_id": "1"}, {"spool_id": True}, {"spool_id": 1.5},
                                  {"spool_id": 1, "dry_run": "no"}])
def test_load_bad_request(client, body):
    err(client.post(f"/api/printers/{SERIAL}/slots/A1/load", json=body), 400, "bad_request")


def test_unload(client, sm, caplog):
    with caplog.at_level(logging.INFO, logger="filament_kit"):
        r = client.post(f"/api/printers/{SERIAL}/slots/A1/unload", json={"dry_run": False})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["location"] == "Sealed stock" and b["spool"]["id"] == 2 and b["slot"]["label"] == "A1"
    assert b["moved_back"] == [{"id": 2, "location": "Sealed stock"}]
    assert sm.spools[2]["location"] == "Sealed stock"
    assert any("unload" in rec.getMessage() and f"serial={SERIAL}" in rec.getMessage() for rec in caplog.records)


def test_unload_dry_run_and_sealed_location_from_config(client, sm):
    cfg = config.load()
    cfg["placement"]["sealed_location"] = "Sealed shelf"
    config.save(cfg)
    r = client.post(f"/api/printers/{SERIAL}/slots/A1/unload", json={"dry_run": True})
    assert r.status_code == 200 and r.json()["location"] == "Sealed shelf"
    assert sm.spools[2]["location"] == LOC_A1          # dry run: nothing changed
    r = client.post(f"/api/printers/{SERIAL}/slots/A1/unload", json={"dry_run": False})
    assert r.json()["location"] == "Sealed shelf" and sm.spools[2]["location"] == "Sealed shelf"


def test_unload_prev_location_wins(client, sm):
    sm.spools[2]["extra"] = {"prev_location": json.dumps("Rack 1")}
    assert client.post(f"/api/printers/{SERIAL}/slots/A1/unload",
                       json={"dry_run": False}).json()["location"] == "Rack 1"


def test_unload_empty_slot_is_404(client):
    err(client.post(f"/api/printers/{SERIAL}/slots/A2/unload", json={"dry_run": False}), 404, "not_found")
    err(client.post("/api/printers/NOPE/slots/A1/unload", json={}), 404, "not_found")


# ---------------------------------------------------------------- usage / undo

def entry(**kw):
    e = {"job": "bracket", "grams": 12.5, "spool_id": 2, "slot": "A1", "observe": False}
    e.update(kw)
    return usage.append(SERIAL, e)


def test_usage_newest_first(client):
    a = entry(job="first")
    b = entry(job="second", observe=True, spool_id=None)
    c = entry(job="broken", grams=None, spool_id=None, slot=None, error="file_not_found")
    r = client.get(f"/api/printers/{SERIAL}/usage?days=7")
    assert r.status_code == 200
    es = r.json()["entries"]
    assert [e["id"] for e in es] == [c["id"], b["id"], a["id"]]
    assert es[2] == {"id": a["id"], "at": a["at"], "job": "first", "grams": 12.5, "spool_id": 2, "slot": "A1",
                     "observe": False, "undone": False}
    assert es[0]["error"] == "file_not_found" and "error" not in es[1]


@pytest.mark.parametrize("code", ["file_not_found", "no_slice_info", "plate_not_found", "printer_unreachable",
                                  "cert_changed", "spoolman_unreachable", "spoolman_failed", "ambiguous_spool"])
def test_usage_error_codes_pass_through(client, code):
    entry(error=code)
    assert client.get(f"/api/printers/{SERIAL}/usage").json()["entries"][0]["error"] == code


def test_usage_days_filter_and_default(client, monkeypatch):
    now = time.time()
    monkeypatch.setattr(usage, "_now", lambda: now - 3 * 86400)
    old = entry(job="old")
    monkeypatch.setattr(usage, "_now", lambda: now)
    new = entry(job="new")
    assert [e["id"] for e in client.get(f"/api/printers/{SERIAL}/usage?days=1").json()["entries"]] == [new["id"]]
    assert len(client.get(f"/api/printers/{SERIAL}/usage").json()["entries"]) == 2
    assert old


@pytest.mark.parametrize("q", ["days=x", "days=-1", "days=nan", "days=inf", "days=100000"])
def test_usage_bad_days(client, q):
    err(client.get(f"/api/printers/{SERIAL}/usage?{q}"), 400, "bad_request")


def test_usage_unknown_printer(client):
    err(client.get("/api/printers/NOPE/usage"), 404, "not_found")


def test_undo(client, sm, caplog):
    e = entry()
    with caplog.at_level(logging.INFO, logger="filament_kit"):
        r = client.post(f"/api/usage/{e['id']}/undo")
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["id"] == e["id"] and r.json()["entry"]["undone"] is True
    assert sm.used == [(2, -12.5)]
    assert any("usage undo" in rec.getMessage() and e["id"] in rec.getMessage() for rec in caplog.records)
    err(client.post(f"/api/usage/{e['id']}/undo"), 409, "already_undone")
    assert sm.used == [(2, -12.5)]


def test_undo_errors(client, monkeypatch):
    obs = entry(observe=True)
    err(client.post(f"/api/usage/{obs['id']}/undo"), 409, "nothing_to_undo")
    err(client.post(f"/api/usage/{'f' * 32}/undo"), 404, "not_found")
    err(client.post("/api/usage/not-an-id/undo"), 404, "not_found")
    old = entry()
    real = time.time()
    monkeypatch.setattr(usage, "_now", lambda: real + 8 * 86400)
    err(client.post(f"/api/usage/{old['id']}/undo"), 409, "too_old")


def test_undo_spoolman_down(client, sm):
    e = entry()

    def down(spool_id, grams):
        raise SpoolmanError("connection refused")
    sm.use = down
    err(client.post(f"/api/usage/{e['id']}/undo"), 503, "spoolman_unreachable")
    sm.use = lambda spool_id, grams: None
    assert client.post(f"/api/usage/{e['id']}/undo").status_code == 200   # nothing was recorded the first time


# ---------------------------------------------------------------- the Access Code never leaves

def _walk(v):
    if isinstance(v, dict):
        for k, x in v.items():
            yield str(k)
            yield from _walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x)
    else:
        yield str(v)


def test_no_route_returns_the_access_code(client, mgr, stubs, monkeypatch):
    preset(monkeypatch)
    e = entry()
    responses = [
        client.get(f"/api/printers/{SERIAL}/map"),
        client.post(f"/api/printers/{SERIAL}/map"),
    ]
    wait_state(client)
    responses += [
        client.get(f"/api/printers/{SERIAL}/map"),
        client.post(f"/api/printers/{SERIAL}/map"),
    ]
    wait_state(client)
    responses += [
        client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": True}),
        client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False}),
        client.post(f"/api/printers/{SERIAL}/slots/A1/unload", json={"dry_run": True}),
        client.post(f"/api/printers/{SERIAL}/slots/A1/unload", json={"dry_run": False}),
        client.get(f"/api/printers/{SERIAL}/usage"),
        client.post(f"/api/usage/{e['id']}/undo"),
        client.post(f"/api/usage/{e['id']}/undo"),                   # an error body too
    ]
    mgr.st = "cert_changed"
    responses.append(client.post(f"/api/printers/{SERIAL}/map"))
    responses.append(client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False}))
    for r in responses:
        assert r.status_code < 500, r.text
        assert CODE not in r.text
        for s in _walk(r.json()):
            assert CODE not in s
            assert "access_code" not in s


def test_load_refused_before_the_first_status_report(client, mgr, monkeypatch):
    """M1: connected, but no gcode_state reported yet: not known to be idle."""
    preset(monkeypatch)
    mgr.report["gcode_state"] = "UNKNOWN"
    r = client.post(f"/api/printers/{SERIAL}/slots/A1/load", json={"spool_id": 1, "dry_run": False})
    err(r, 409, "printer_offline")
    assert "no status from the printer yet" in r.json()["message"]
    assert mgr.writes == []


def test_map_refused_while_a_load_writes(client, mgr, monkeypatch):
    """I1: a load's write phase holds the printer; POST /map is 409 already_running with a load message."""
    from filament_kit.bridge import mapping as mp
    with mp.load_guard(SERIAL):
        r = client.post(f"/api/printers/{SERIAL}/map")
    err(r, 409, "already_running")
    assert "loaded" in r.json()["message"]


def test_cert_changed_message_says_what_to_do():
    from filament_kit import api
    assert "reset the printer" in api.CERT_CHANGED and "IP" in api.CERT_CHANGED
