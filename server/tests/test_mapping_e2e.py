"""T7: the mapping job end to end over the fake paho printer and the fake FTPS server, with the real slot test and
calibration (no stubs): a success saves a calibrated map; a job stopped mid slot test puts every slot back and
leaves no slot snapshot behind."""
import pytest

from fakes.fake_ftps import FakeFtps
from fakes.fake_paho import LEAF, FakeClient, FakePrinter
from filament_kit.bridge import ams, calib3mf, connection, ftps, mapping, registry, slottest, snapshot
from filament_kit.bridge.connection import Manager
from filament_kit.bridge.registry import Printer
from test_slottest import REPORT, assert_back_to_original, no_test_colour_left

SERIAL = "0948ZZ0A0000001"
CODE = "13572468"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 2.0)
    monkeypatch.setattr(slottest, "CONFIRM_TIMEOUT", 3.0)


@pytest.fixture
def sd(tmp_path, monkeypatch):
    f = FakeFtps(LEAF, tmp_path / "sd", CODE)       # one leaf on every port, as on the H2D
    monkeypatch.setattr(ftps, "PORT", f.port)
    yield f
    f.close()


@pytest.fixture
def rig(sd):
    clients = []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c
    registry.upsert(Printer(SERIAL, "Office H2D", "O1D", "127.0.0.1", CODE, True))
    m = Manager(client_factory=factory)
    m.sync()
    printer = FakePrinter(clients[0], REPORT)
    clients[0].connected(0)
    assert m.wait_report(SERIAL, lambda r: "vt_tray" in r, 2) is not None
    yield m, printer
    m.stop()


def test_mapping_end_to_end_saves_a_calibrated_map(rig, sd):
    m, printer = rig
    printer.native = "shift8"                       # the owner's H2D numbers slots by shift8 (P3)
    steps = []
    v = mapping.Mapper(m).run(SERIAL, on_step=steps.append)
    assert v["state"] == "done", v["problems"]
    assert v["calibrated"] is True and v["observe"] is False and v["scheme"] == "shift8"
    # A4 is empty: numbered by the proven scheme
    assert {s["label"]: s["global"] for s in v["slots"]} == {"A1": 0, "A2": 1, "A3": 2, "A4": 3, "HT-A": 32768,
                                                             "Ext-L": 254}
    saved = ams.load_map(SERIAL)
    assert saved.calibrated and not saved.observe
    # the layout the map was made for (P2): ids, types (no module codes reported: None), slot counts
    assert saved.fingerprint == [[0, None, 4], [128, None, 1], [254, "ext", 1]] and saved.stale is False
    assert v["stale"] is False and v["remapping"] is False
    job = printer.jobs[0]
    # A4 is empty and an external holder is never part of the job (it keeps its own id, see the map above)
    assert job["command"] == "project_file" and job["ams_mapping"] == [0, 1, 2, 128]
    assert job["ams_mapping2"][3] == {"ams_id": 128, "slot_id": 0} and len(job["ams_mapping2"]) == 4
    assert [j["command"] for j in printer.jobs] == ["project_file"]
    assert not (sd.root / "cache" / f"{calib3mf.job_name(SERIAL)}.gcode.3mf").exists()
    assert no_test_colour_left(printer)
    assert_back_to_original(printer)
    assert not snapshot.pending(SERIAL)
    assert any(s.startswith("Testing slot") for s in steps)


def test_mapping_stopped_mid_slot_test_restores_and_clears_the_snapshot(rig, sd):
    m, printer = rig
    mp = mapping.Mapper(m)
    seen = {}

    def step(text):
        if text.startswith("Testing slot A3"):
            seen["pending"] = snapshot.pending(SERIAL)      # saved before the first write
            mp.abort(SERIAL)
    v = mp.run(SERIAL, on_step=step)
    assert seen["pending"] is True
    assert v["state"] == "failed" and v["calibrated"] is False and v["observe"] is True
    assert any("stopped" in p for p in v["problems"])
    assert printer.jobs == []                               # no calibration job
    assert no_test_colour_left(printer)
    assert_back_to_original(printer)
    assert not snapshot.pending(SERIAL)
