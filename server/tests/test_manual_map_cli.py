"""`filament-kit printer map --manual`: Map by loading filament in a terminal, on the running server's session."""
from __future__ import annotations

import copy
import queue

import pytest

from filament_kit import cli
from filament_kit.bridge import ams, manual, mapping, registry
from filament_kit.web.slots import SlotError

SERIAL = "0948ZZ0A0000001"


def tray(tid):
    return {"id": str(tid), "tray_type": "PLA", "tray_color": "FF0000FF", "tray_info_idx": "Pa111111"}


BASE = {"gcode_state": "IDLE",
        "ams": {"tray_now": "255", "ams": [{"id": "0", "tray": [tray(0), tray(1), tray(2), tray(3)]}]},
        "vt_tray": {"id": "254", "tray_type": "PLA", "tray_color": "FFFFFFFF"}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(cli, "MANUAL_POLL", 0.01)
    registry.upsert(registry.Printer(SERIAL, "Shop X1C", "BL-P001", "10.0.0.6", "13572468", True))
    yield
    mapping.manual_end(SERIAL)


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(manual.time, "time", lambda: now["t"])
    return now


class Printer:
    def __init__(self, report):
        self.report = report

    def state(self, serial):
        return "connected"

    def wait_report(self, serial, predicate, timeout):
        return copy.deepcopy(self.report)


class ServerApi:
    """The server's manual-map routes over a real ManualMaps (what api.manual_call does), answering as KitApi."""

    def __init__(self, mm, clock, owner=None):
        self.mm, self.clock, self.owner, self.posts, self.last = mm, clock, owner, [], None

    def _do(self, fn):
        try:
            self.last = fn()
        except manual.ManualError as e:
            raise SlotError(str(e), code=e.code, http=e.status) from None
        return self.last

    def get(self, path):
        assert path == f"/api/printers/{SERIAL}/manual-map"
        if self.owner:
            self.owner(self)
        self.clock["t"] += 1.0
        return self._do(lambda: self.mm.view(SERIAL))

    def post(self, path, body):
        step, b = path.rsplit("/", 1)[-1], body
        self.posts.append(step)
        return self._do({
            "start": lambda: self.mm.start(SERIAL),
            "confirm": lambda: self.mm.confirm(SERIAL, b.get("session"), b.get("position"), b.get("reported"),
                                               b.get("nozzle"), b.get("by_hand") is True),
            "skip": lambda: self.mm.skip(SERIAL, b.get("session"), b.get("position")),
            "stop": lambda: self.mm.stop(SERIAL, b.get("session")),
            "offer": lambda: self.mm.answer_offer(SERIAL, b.get("share") is True),
        }[step])


class Owner:
    """At the terminal: types the line `script` gives for what the session asks now ("" = nothing yet)."""

    def __init__(self, api, script):
        self.api, self.script, self.typed = api, script, []

    def get(self, timeout):
        v = self.api.last or {}
        st = v.get("step")
        if not v.get("open", True):
            line = self.script.get("offer", "")
        elif st and st.get("ask"):
            line = self.script.get(st["position"]["label"], "y")
        elif st and not v.get("reports_loads"):
            line = self.script.get(st["position"]["label"], "1")
        else:
            line = self.script.get("wait:" + (st["position"]["label"] if st else ""), "")
        if line == "":
            raise queue.Empty
        self.typed.append(line)
        return line


def loads_what_it_is_told(printer):
    """The owner loads each named AMS position into the tray of that number (A1 -> tray 0 ...)."""
    def owner(api):
        st = (api.last or {}).get("step")
        if st and st["position"]["label"].startswith("A"):
            printer.report["ams"]["tray_now"] = str(int(st["position"]["label"][1:]) - 1)
    return owner


def test_the_terminal_flow_confirms_skips_and_answers_the_share_question(env, clock, capsys):
    printer = Printer(copy.deepcopy(BASE))
    api = ServerApi(manual.ManualMaps(printer), clock, loads_what_it_is_told(printer))
    lines = Owner(api, {"A1": "y", "A2": "A2", "A3": "s", "wait:A4": "s", "A4": "s", "wait:Ext": "q", "Ext": "q",
                        "offer": "n"})
    assert cli._manual_map_via_server(api, SERIAL, lines) == 0
    out = capsys.readouterr().out
    assert "Load A1 to the nozzle, then wait. (s skips, q stops)" in out
    assert "Is that the A1 you loaded?" in out and "Type y for yes" in out
    assert "  A1: confirmed (A1)" in out and "  A2: confirmed (A2)" in out and "  A3: skipped" in out
    assert "Noted: this map is not shared." in out
    m = ams.load_map(SERIAL)
    assert (m.slots["A1"]["tray_id"], m.slots["A2"]["tray_id"]) == (0, 1) and m.by_user["A1"]["by"] == "user"
    assert api.posts == ["start", "confirm", "confirm", "skip", "skip", "stop", "offer"]


def test_a_printer_that_reports_no_load_gets_the_numbered_form(env, clock, capsys):
    report = copy.deepcopy(BASE)
    del report["ams"]["tray_now"]
    api = ServerApi(manual.ManualMaps(Printer(report)), clock)
    lines = Owner(api, {"A1": "3", "A2": "q", "offer": "n"})
    assert cli._manual_map_via_server(api, SERIAL, lines) == 0
    out = capsys.readouterr().out
    assert "which slot is A1 in? (not checked by the printer)" in out and "    3) A3" in out
    assert "  A1: entered by hand (A3)" in out
    assert ams.load_map(SERIAL).by_user["A1"]["by"] == "user-unverified"


def test_an_answer_that_means_nothing_is_said_and_nothing_is_sent():
    v = {"open": True, "reports_loads": True, "dual_nozzle": True,
         "positions": [{"id": "A1", "label": "A1"}, {"id": "A2", "label": "A2"}],
         "step": {"position": {"id": "A1", "label": "A1"}, "say": "Load A1",
                  "ask": "The printer now reports A2 loaded. Is that the A1 you loaded?",
                  "seen": {"reported": {"ams_id": 0, "tray_id": 1}, "settled": True, "nozzle_reported": False}}}
    assert cli._manual_answer(v, "y") == "say which nozzle too: right or left"
    assert cli._manual_answer(v, "y left") == ("confirm", {"position": "A1", "reported": {"ams_id": 0, "tray_id": 1},
                                                          "nozzle": "left"})
    assert cli._manual_answer(v, "B9 right") == "no position B9 on this printer"
    assert cli._manual_answer(v, "a2 right")[1]["position"] == "A2"
    assert cli._manual_answer(v, "s") == ("skip", {"position": "A1"})
    assert cli._manual_answer(v, "Q") == ("stop", {})
    v["step"]["ask"] = None
    v["step"]["seen"] = None
    assert cli._manual_answer(v, "y").startswith("the printer has not reported a new load yet")


def test_no_terminal_input_stops_the_session_rather_than_waiting(env, clock):
    api = ServerApi(manual.ManualMaps(Printer(copy.deepcopy(BASE))), clock)
    q = queue.Queue()
    q.put(None)                                   # stdin closed at once
    assert cli._manual_map_via_server(api, SERIAL, q) == 1     # R107 note 1: stopped, not finished
    assert api.posts == ["start", "stop"]


def test_no_answer_to_the_share_question_is_not_a_no(env, clock, capsys, monkeypatch):
    """R107 note 2: after q the question waits SHARE_WAIT (not 5 minutes), and silence records nothing."""
    monkeypatch.setattr(cli, "SHARE_WAIT", 0.05)
    printer = Printer(copy.deepcopy(BASE))
    api = ServerApi(manual.ManualMaps(printer), clock, loads_what_it_is_told(printer))
    lines = Owner(api, {"A1": "y", "wait:A2": "q", "A2": "q"})      # no "offer" line: nobody answers
    assert cli._manual_map_via_server(api, SERIAL, lines) == 0
    assert "offer" not in api.posts and "No answer; the setup page and the apps ask again." in capsys.readouterr().out
    assert api.mm.view(SERIAL)["offer_report"] is True                 # still asked elsewhere


def test_a_refused_start_is_said(env, clock, capsys):
    printer = Printer(copy.deepcopy(BASE))
    printer.report["gcode_state"] = "RUNNING"
    api = ServerApi(manual.ManualMaps(printer), clock)
    assert cli._manual_map_via_server(api, SERIAL, queue.Queue()) == 1
    assert "The printer is busy" in capsys.readouterr().err


def test_manual_needs_the_running_server(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_server_api", lambda: None)
    assert cli.main(["printer", "map", "--manual", SERIAL]) == 1
    assert "needs the running kit server" in capsys.readouterr().err


def test_manual_goes_to_the_server_session(env, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_server_api", lambda: "API")
    monkeypatch.setattr(cli, "_manual_map_via_server", lambda api, serial: seen.append((api, serial)) or 0)
    assert cli.main(["printer", "map", "--manual", SERIAL]) == 0
    assert seen == [("API", SERIAL)]


def test_a_klipper_printer_is_refused_by_the_plain_map(env, monkeypatch, capsys):
    p = registry.add_klipper("Shop Box", "box.example")
    monkeypatch.setattr(cli, "_server_api", lambda: pytest.fail("the server must not be asked"))
    assert cli.main(["printer", "map", p.serial]) == 1
    err = capsys.readouterr().err
    assert "printer map --manual" in err and "Each slot" not in err
