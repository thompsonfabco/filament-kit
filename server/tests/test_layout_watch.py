"""P2: the layout fingerprint in the slot map, `stale` on a layout change, and the idle auto re-map."""
import copy

import pytest

from filament_kit import config
from filament_kit.bridge import ams, layout, mapping


def unit(uid, n=4):
    return {"id": str(uid), "tray": [{"id": str(i), "tray_type": "PLA"} for i in range(n)]}


def report(units=(0, 128), state="IDLE", **extra):
    return {"gcode_state": state, "ams": {"ams": [unit(u, 1 if u >= 128 else 4) for u in units]}, **extra}


class FakeManager:
    def __init__(self):
        self.st = "connected"

    def state(self, serial):
        return self.st

    def model(self, serial):
        return "O1D"


class FakeMapper:
    def __init__(self):
        self.started = []
        self.attempts = 0
        self.busy = False
        self.fail = None

    def in_progress(self, serial):
        return self.busy

    def start(self, serial, auto=False):
        self.attempts += 1
        if self.fail:
            raise self.fail
        self.started.append((serial, auto))
        return "job"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def rig(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mgr, mapper, clock = FakeManager(), FakeMapper(), Clock()
    w = mapping.LayoutWatch(mgr, mapper, clock=clock, settle=30, retry=600, sync=True)
    return w, mgr, mapper, clock


def mapped(serial="S1", rep=None, fp=True):
    m = ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}, calibrated=True, observe=False)
    if fp:
        m.fingerprint = layout.build(rep or report(), "O1D").fingerprint
    ams.save_map("S1", m)
    return m


def test_auto_remap_default_on():
    assert config.DEFAULTS["auto_remap"] is True


def test_unchanged_layout_does_nothing(rig):
    w, mgr, mapper, clock = rig
    mapped()
    for _ in range(3):
        w("S1", report(), False)
        clock.t += 100
    m = ams.load_map("S1")
    assert m.stale is False and m.calibrated and mapper.started == []


def test_old_map_without_fingerprint_adopts_the_current_layout(rig):
    w, mgr, mapper, clock = rig
    mapped(fp=False)
    w("S1", report(), False)
    m = ams.load_map("S1")
    assert m.fingerprint == layout.build(report(), "O1D").fingerprint and m.stale is False


def test_no_map_no_action(rig):
    w, mgr, mapper, clock = rig
    w("S1", report((0, 1, 128)), False)
    clock.t += 1000
    w("S1", report((0, 1, 128)), False)
    assert mapper.started == [] and ams.load_map("S1").slots == {}


def test_added_unit_marks_stale_then_remaps_when_idle_and_settled(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report((0, 1, 128), state="RUNNING"), False)    # an AMS added while printing
    m = ams.load_map("S1")
    assert m.stale is True and m.calibrated is True             # still usable for the units it knows
    clock.t += 60
    w("S1", report((0, 1, 128), state="RUNNING"), False)
    assert mapper.started == []                                # busy: wait
    w("S1", report((0, 1, 128), state="FINISH"), False)
    assert mapper.started == [("S1", True)]
    clock.t += 5
    w("S1", report((0, 1, 128), state="FINISH"), False)
    assert len(mapper.started) == 1                            # one attempt per retry window


def test_settle_time_before_remap(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report((0, 1, 128)), False)
    clock.t += 10
    w("S1", report((0, 1, 128)), False)
    assert mapper.started == []
    clock.t += 25
    w("S1", report((0, 1, 128)), False)
    assert mapper.started == [("S1", True)]


def test_layout_back_to_the_mapped_one_clears_stale(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report((0, 1, 128), state="RUNNING"), False)
    assert ams.load_map("S1").stale is True
    w("S1", report(state="RUNNING"), False)
    assert ams.load_map("S1").stale is False
    clock.t += 1000
    w("S1", report(), False)
    assert mapper.started == []


def test_auto_remap_off_marks_stale_only(rig, monkeypatch):
    w, mgr, mapper, clock = rig
    config.save({"auto_remap": False})
    mapped()
    w("S1", report((0, 1, 128)), False)
    clock.t += 1000
    w("S1", report((0, 1, 128)), False)
    assert ams.load_map("S1").stale is True and mapper.started == []


def test_offline_or_mapping_running_waits(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report((0, 1, 128)), False)
    clock.t += 100
    mgr.st = "offline"
    w("S1", report((0, 1, 128)), False)
    mapper.busy, mgr.st = True, "connected"
    w("S1", report((0, 1, 128)), False)
    assert mapper.started == []
    mapper.busy = False
    w("S1", report((0, 1, 128)), False)
    assert mapper.started == [("S1", True)]


def test_failed_start_retries_later_and_gives_up_after_three(rig):
    w, mgr, mapper, clock = rig
    mapped()
    mapper.fail = mapping.AlreadyRunning("S1")
    w("S1", report((0, 1, 128)), False)
    for _ in range(10):
        clock.t += 601
        w("S1", report((0, 1, 128)), False)
    mapper.fail = None
    clock.t += 601
    w("S1", report((0, 1, 128)), False)
    assert mapper.started == [] and mapper.attempts == 3        # three tries, then it gave up


def test_remap_done_stops_retrying(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report((0, 1, 128)), False)
    clock.t += 100
    w("S1", report((0, 1, 128)), False)
    assert len(mapper.started) == 1
    m = ams.load_map("S1")                                     # the job saved a fresh map
    m.fingerprint, m.stale = layout.build(report((0, 1, 128)), "O1D").fingerprint, False
    ams.save_map("S1", m)
    clock.t += 700
    w("S1", report((0, 1, 128)), False)
    assert len(mapper.started) == 1


def test_module_code_arriving_is_not_a_change_and_is_remembered(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report(fk_modules={"0": "N3F05"}), False)
    m = ams.load_map("S1")
    assert m.stale is False and m.fingerprint[0][1] == "ams_2pro"
    w("S1", report(), False)                                     # codes not (yet) known after a reconnect
    assert ams.load_map("S1").fingerprint[0][1] == "ams_2pro"
    w("S1", report(fk_modules={"0": "N3F07"}), False)            # another module on the same id
    assert ams.load_map("S1").stale is True


def test_reports_without_ams_are_ignored(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", {"gcode_state": "IDLE"}, False)
    w("S1", {"ams": {"tray_now": "1"}}, False)
    assert ams.load_map("S1").stale is False


def test_view_shows_stale_and_remapping(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    m = mapped()
    m.stale = True
    ams.save_map("S1", m)
    v = mapping.Mapper(FakeManager()).view("S1")
    assert v["stale"] is True and v["remapping"] is False



def test_saved_label_missing_from_the_layout_marks_stale(rig):
    w, mgr, mapper, clock = rig
    m = mapped()
    m.slots["Q9"] = {"ams_id": 16, "tray_id": 8, "global_id": 72}      # a label the layout does not have
    ams.save_map("S1", m)
    w("S1", report(), False)
    assert ams.load_map("S1").stale is True


def test_old_ext_key_is_not_missing_on_the_h2d(rig):
    from filament_kit.bridge import registry
    w, mgr, mapper, clock = rig
    registry.upsert(registry.Printer("S1", "Lab", "O1D", "10.0.0.5", "13572468", True))
    rep = report(vt_tray={"id": "254", "tray_type": "PLA"})
    m = mapped(rep=rep)
    m.slots["Ext"] = {"ams_id": 254, "tray_id": 0, "global_id": 254}
    ams.save_map("S1", m)
    w("S1", rep, False)
    m = ams.load_map("S1")
    assert m.stale is False and "Ext-L" in m.slots


# ---------------------------------------------------------------- suspect map (P3): re-map when idle


def test_suspect_map_remaps_when_idle_without_a_layout_change(rig):
    """Usage marks the map suspect (two prints disagreed with it) and asks for a re-map: the same watcher runs it
    once the printer is idle, no layout change needed."""
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report(), False)
    clock.t += 100
    w("S1", report(), False)
    assert mapper.started == []
    m = ams.load_map("S1")
    m.suspect, m.observe = True, True
    ams.save_map("S1", m)
    mapping.request_remap("S1")
    w("S1", report(state="RUNNING"), False)
    assert mapper.started == []                                 # busy: wait
    w("S1", report(state="FINISH"), False)
    assert mapper.started == [("S1", True)]
    clock.t += 5
    w("S1", report(), False)
    assert len(mapper.started) == 1                             # one attempt per retry window


def test_suspect_map_found_at_start_is_remapped(rig):
    w, mgr, mapper, clock = rig
    m = mapped()
    m.suspect = True
    ams.save_map("S1", m)
    w("S1", report(), True)                                     # the first report after a (re)start
    clock.t += 31
    w("S1", report(), False)
    assert mapper.started == [("S1", True)]
    assert ams.load_map("S1").stale is False                    # suspect is not a layout change


def test_remap_request_without_a_suspect_map_does_nothing(rig):
    w, mgr, mapper, clock = rig
    mapped()
    w("S1", report(), False)
    mapping.request_remap("S1")
    clock.t += 100
    w("S1", report(), False)
    assert mapper.started == []


def test_view_shows_scheme_and_suspect(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    m = mapped()
    m.scheme, m.suspect = "shift8", True
    ams.save_map("S1", m)
    v = mapping.Mapper(FakeManager()).view("S1")
    assert v["scheme"] == "shift8" and v["suspect"] is True
