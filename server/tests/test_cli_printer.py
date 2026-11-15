"""S5.5: the `printer` commands (06 5 and 9.2): naming a printer, `printer list` (AUT-9), `show`, `test`, `add`, `use`,
`dismiss`, `rename`, `address`, `access-code`, `api-key`, `lane-data`, `detect`, `scan`, `reports`, `forget-certificate`,
`forget`, `live`, `menu`, the old spellings, and the `--json` shapes of the Hub's own replies. The commands are run
through `cli.main` against a registry in a temporary folder; the Hub is never running unless a test gives it a fake
API. Example names, serials and addresses only."""
from __future__ import annotations

import builtins
import io
import json
import re
import sys

import pytest

from filament_kit import cli, config, output, setup_page
from filament_kit.bridge import registry, tlspin
from filament_kit.bridge.klipper import discovery

X1 = "00M00A000000001"
A1 = "03000A000000002"
ESC = "\x1b"


@pytest.fixture(autouse=True)
def kit(tmp_path, monkeypatch):
    for name, folder in (("FK_ETC", "etc"), ("FK_STATE", "state")):
        monkeypatch.setenv(name, str(tmp_path / folder))
        (tmp_path / folder).mkdir(exist_ok=True)
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(cli, "_server_api", lambda: None)       # no Hub running, unless a test gives one
    config.save({**config.load(), "modules": {"printers": True, "klipper": True}})       # Klipper is opt-in


def seed():
    """Two Bambu Lab printers, a Klipper printer added, and a Klipper printer found by a scan and not added."""
    registry.add_bambu(X1, "Workshop X1", "X1C", "192.0.2.40", "12345678")
    registry.add_bambu(A1, "Study A1 mini", "A1M", "192.0.2.41", "87654321")
    registry.add_klipper("Garage Voron", "voron.example", 7125)
    registry.detected_klipper("192.0.2.57", 7125, name="mainsailos", lookups=False)


def run(capsys, *argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    got = capsys.readouterr()
    return rc, got.out, got.err


def doc(out: str):
    assert ESC not in out and out.endswith("\n") and out.count("\n") == 1, out
    return json.loads(out)


def squash(text: str) -> str:
    return " ".join(text.split())


def unglyph(text: str) -> str:
    """A status row's words without its glyph (the test machine's locale decides which glyph set it is)."""
    return re.sub(r"^[+x~o!*●○▲×◐◆] ", "", squash(text))


class Hub:
    """The running Hub's API as the command line reads it: `GET /api/printers` and `GET /api/printers/<id>`."""

    def __init__(self, states, status=None):
        self.states, self.status, self.asked = states, status or {}, []

    def get(self, path):
        self.asked.append(path)
        if path == "/api/printers":
            return {"printers": [{"id": i, "state": s, "model_name": "Bambu Lab X1 Carbon"}
                                 for i, s in self.states.items()]}
        return {"status": self.status.get(path.rsplit("/", 1)[-1])}


SLOTS = [{"unit": 0, "label": "A", "slots": [
    {"label": "A1", "type": "PLA", "color_hex": "2b2b2e", "present": True,
     "spool": {"name": "Polymaker PolyTerra PLA Charcoal Black", "remaining_weight": 620.4}},
    {"label": "A2", "type": "PETG", "color_hex": "f2762e", "present": True, "spool": None},
    {"label": "A4", "type": "", "color_hex": "", "present": False, "spool": None}]}]


@pytest.fixture
def hub(monkeypatch):
    h = Hub({X1: "connected", A1: "offline", "garage-voron": "connected"}, {X1: {"ams": SLOTS}})
    monkeypatch.setattr(cli, "_server_api", lambda: h)
    return h


@pytest.fixture
def terminal(monkeypatch):
    """`terminal(True, "y")`: whether standard input is a terminal, and what it answers to each question."""
    asked: list[str] = []

    def setup(at_terminal: bool, *answers: str):
        left = list(answers)
        monkeypatch.setattr(output, "terminal", lambda: at_terminal)

        def fake_input(prompt=""):
            asked.append(prompt)
            print(prompt, end="")
            if not left:
                raise EOFError
            return left.pop(0)
        monkeypatch.setattr(builtins, "input", fake_input)

        def fake_ask(prompt):
            asked.append(prompt)
            return left.pop(0) if left else None
        monkeypatch.setattr(cli, "_ask", fake_ask)
        return asked
    return setup


def stdin(monkeypatch, text: str):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


# ---------- naming a printer (06 5) ----------

@pytest.mark.parametrize("arg, serial", [
    (X1, X1), (X1.lower(), X1), ("garage-voron", "garage-voron"), ("Workshop X1", X1), ("workshop x1", X1),
    ("study", A1), ("STUDY A1", A1), ("gar", "garage-voron"), ("main", "mainsailos")])
def test_a_printer_is_named_by_serial_id_name_or_the_start_of_its_name(capsys, arg, serial):
    seed()
    rc, out, err = run(capsys, "printer", "show", arg, "--json")
    assert rc == 0, err
    assert doc(out)["serial"] == serial


def test_an_exact_name_beats_a_longer_name_that_starts_the_same(capsys):
    registry.add_bambu(X1, "Shop", "X1C", "192.0.2.40", "12345678")
    registry.add_bambu(A1, "Shop 2", "A1M", "192.0.2.41", "87654321")
    assert doc(run(capsys, "printer", "show", "shop", "--json")[1])["serial"] == X1
    assert doc(run(capsys, "printer", "show", "shop 2", "--json")[1])["serial"] == A1


def test_an_exact_serial_beats_a_name(capsys):
    registry.add_bambu(X1, "Shop", "X1C", "192.0.2.40", "12345678")
    registry.add_bambu(A1, X1.lower(), "A1M", "192.0.2.41", "87654321")     # another printer is named like that serial
    assert doc(run(capsys, "printer", "show", X1, "--json")[1])["serial"] == X1


def test_the_start_of_two_names_is_exit_2_with_the_matches_listed_in_list_order(capsys):
    seed()
    registry.add_bambu("03000A000000003", "Study X", "A1M", "192.0.2.42", "11112222")
    rc, out, err = run(capsys, "printer", "show", "study")
    assert (rc, out) == (2, "")
    assert err == ('Error: "study" does not name one printer.\n'
                   "Fix: use a name, serial or id from spoolwarden printer list. Close matches:\n"
                   f"     Study A1 mini  {A1}\n     Study X  03000A000000003\n")


def test_close_matches_hold_the_argument_anywhere_and_are_at_most_five(capsys):
    seed()
    for n in range(1, 8):
        registry.add_bambu(f"03000A00000010{n}", f"Bench {n}", "A1M", f"192.0.2.{70 + n}", "11112222")
    rc, out, err = run(capsys, "printer", "test", "ench")
    assert rc == 2
    listed = [ln.strip() for ln in err.splitlines()[2:]]
    assert listed == [f"Bench {n}  03000A00000010{n}" for n in range(1, 6)]
    rc, out, err = run(capsys, "printer", "show", "a1")           # the middle of a name, and of a serial
    assert rc == 2 and f"Study A1 mini  {A1}" in err and "Workshop X1" not in err


def test_no_close_match_ends_the_fix_line(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "show", "zzz")
    assert (rc, out) == (2, "")
    assert err == ('Error: "zzz" does not name one printer.\n'
                   "Fix: use a name, serial or id from spoolwarden printer list.\n")


def test_an_empty_name_names_nothing(capsys):
    registry.add_bambu(X1, "Shop", "X1C", "192.0.2.40", "12345678")
    assert run(capsys, "printer", "show", " ")[0] == 2


def test_the_error_of_a_name_under_json_is_one_document(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "show", "zzz", "--json")
    assert rc == 2 and err.startswith("Error: ")
    assert doc(out) == {"ok": False, "error": '"zzz" does not name one printer.',
                        "fix": "use a name, serial or id from spoolwarden printer list."}


@pytest.mark.parametrize("argv", [["rename", "mainsail", "X"], ["address", "mainsail", "192.0.2.60"],
                                  ["api-key", "mainsail", "--api-key", "-"], ["lane-data", "mainsail", "on"],
                                  ["detect", "mainsail"], ["forget", "mainsail", "--yes"], ["live", "mainsail"],
                                  ["map", "mainsail", "--yes"], ["report", "mainsail"], ["reports", "mainsail"],
                                  ["forget-certificate", "mainsail", "--yes"]])
def test_a_found_printer_is_not_added_for_the_commands_that_need_it_added(capsys, argv):
    seed()
    rc, out, err = run(capsys, "printer", *argv)
    assert rc == 2 and out == ""
    assert err.startswith("Error: mainsailos is found on the network but not added yet.\n")
    assert err.splitlines()[1] in ("Fix: sudo spoolwarden printer use mainsailos",
                                   "Fix: sudo spoolwarden printer dismiss mainsailos")


def test_a_found_bambu_printer_points_to_add_with_its_address_not_use(capsys):
    registry.detected(X1, "192.0.2.77", "X1C")
    rc, out, err = run(capsys, "printer", "rename", X1, "Shed")
    assert rc == 2 and err.splitlines()[1] == "Fix: sudo spoolwarden printer add --address 192.0.2.77"


def test_forget_certificate_of_a_klipper_printer_uses_the_family_sentence(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "forget-certificate", "garage", "--yes")
    assert (rc, out, err) == (1, "", "Error: Garage Voron is a Klipper printer; it has no certificate to forget.\n")


def test_forgetting_a_found_printer_points_to_dismiss(capsys):
    seed()
    err = run(capsys, "printer", "forget", "mainsailos", "--yes")[2]
    assert err.splitlines()[1] == "Fix: sudo spoolwarden printer dismiss mainsailos"
    assert "mainsailos" in registry.load()


def test_the_names_a_found_printer_may_have_are_show_test_use_and_dismiss(capsys, monkeypatch):
    seed()
    assert run(capsys, "printer", "show", "mainsail")[0] == 0
    monkeypatch.setattr(setup_page.Moonraker, "info", lambda self: {"state": "ready"})
    assert run(capsys, "printer", "test", "mainsail")[0] == 0
    assert run(capsys, "printer", "use", "mainsail")[0] == 0
    registry.detected_klipper("192.0.2.58", 7125, name="found2", lookups=False)
    assert run(capsys, "printer", "dismiss", "found2", "--yes")[0] == 0


@pytest.mark.parametrize("argv, what, fix", [
    (["access-code", "garage"], "Garage Voron is a Klipper printer; it has no Access Code.",
     'Fix: sudo spoolwarden printer api-key "Garage Voron"'),
    (["api-key", "workshop"], "Workshop X1 is a Bambu Lab printer; it has no Moonraker API key.",
     'Fix: sudo spoolwarden printer access-code "Workshop X1"'),
    (["lane-data", "workshop", "on"], "Workshop X1 is a Bambu Lab printer; it has no lane data.", None),
    (["detect", "workshop"], "Workshop X1 is a Bambu Lab printer; it has no model to detect.", None),
    (["reports", "garage"], "Garage Voron is a Klipper printer; it has no printer reports.", None)])
def test_a_command_of_one_family_says_so_and_names_the_command_of_the_other(capsys, argv, what, fix):
    seed()
    rc, out, err = run(capsys, "printer", *argv)
    assert (rc, out) == (2, "")
    assert err.splitlines()[0] == "Error: " + what
    assert (err.splitlines()[1] if fix else None) == fix


# ---------- printer list (AUT-9) ----------

def test_list_piped_has_no_escape_and_lines_of_79_columns_at_most(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "list")
    assert rc == 0
    assert ESC not in out and ESC not in err
    assert all(len(ln) <= 79 for ln in out.splitlines())
    lines = out.splitlines()
    assert lines[0].split() == ["NAME", "TYPE", "ID", "ADDRESS", "STATE"]
    assert [ln.split()[0] for ln in lines[1:5]] == ["Workshop", "Study", "Garage", "mainsailos"]
    assert "voron.example:7125" in lines[3] and "192.0.2.40" in lines[1]
    assert lines[4].endswith("found, not added")
    assert err == "Note: the Hub is not running, so connection states are unknown.\n"
    assert lines[1].endswith("unknown")


def test_list_says_what_is_set_up_and_how_to_add_the_found_one(capsys):
    seed()
    out = run(capsys, "printer", "list")[1]
    assert "3 set up. 1 found on the network, not added.\n" in out
    assert out.splitlines()[-1] == "Add the found one: sudo spoolwarden printer use mainsailos"


def test_list_with_a_running_hub_gives_states_counts_and_what_needs_a_look(capsys, hub):
    seed()
    rc, out, err = run(capsys, "printer", "list")
    assert (rc, err) == (0, "")
    rows = {ln.split()[0]: ln for ln in out.splitlines() if ln.strip()}
    assert rows["Workshop"].endswith("connected") and rows["Study"].endswith("offline")
    assert "3 set up: 2 connected, 1 offline. 1 found on the network, not added." in out
    assert 'Study A1 mini needs a look: spoolwarden printer show "Study A1 mini"' in out
    assert hub.asked == ["/api/printers"]                               # one read for the whole list


def test_list_names_the_states_of_06_6_1(capsys, monkeypatch):
    seed()
    monkeypatch.setattr(cli, "_server_api", lambda: Hub({X1: "wrong_code", A1: "cert_changed", "garage-voron": "connecting"}))
    out = run(capsys, "printer", "list")[1]
    assert re.search(r"Workshop X1 .*wrong Access Code$", out, re.M)
    assert re.search(r"Study A1 mini .*certificate changed$", out, re.M)
    assert "1 connected" not in out and "3 set up: 0 connected, 1 offline, 2 need a look." in out


def test_list_plain_is_ascii_and_has_no_glyph_or_colour(capsys):
    seed()
    rc, out, err = run(capsys, "--plain", "printer", "list")
    assert rc == 0
    (out + err).encode("ascii")
    assert not re.search(r"[●○▲]", out)


def test_list_at_a_terminal_colours_the_state_and_keeps_the_columns(capsys, monkeypatch, hub):
    seed()
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    rc, out, err = run(capsys, "--color", "always", "printer", "list")
    assert rc == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)
    assert ESC in out and all(len(ln) <= 79 for ln in plain.splitlines())
    assert re.search(r"Workshop X1 +Bambu +00M00A000000001 +192\.0\.2\.40 +\x1b\[32m. connected\x1b\[0m\n", out)


def test_list_json_is_the_hubs_printer_objects(capsys, hub):
    seed()
    rc, out, err = run(capsys, "printer", "list", "--json")
    assert rc == 0
    rows = doc(out)
    assert [r["serial"] for r in rows] == [X1, A1, "garage-voron", "mainsailos"]
    assert rows[0] == {"serial": X1, "name": "Workshop X1", "model": "X1C", "ip": "192.0.2.40", "configured": True,
                       "state": "connected", "pinned": False, "family": "bambu", "mapping": False, "report_why": None}
    assert rows[2]["host"] == "voron.example" and rows[2]["port"] == 7125 and rows[2]["lane_data"] == "auto"
    assert rows[2]["api_key"] is False and rows[3]["configured"] is False
    assert "12345678" not in out


def test_list_json_without_a_hub_has_unknown_states(capsys):
    seed()
    rows = doc(run(capsys, "printer", "list", "--json")[1])
    assert {r["state"] for r in rows if r["configured"]} == {"unknown"}


def test_an_empty_list_says_how_to_add_one(capsys):
    rc, out, err = run(capsys, "printer", "list")
    assert rc == 0
    assert squash(out) == ("No printer yet. Printers on the network appear here once they announce themselves. "
                           "Add one: sudo spoolwarden printer add")
    assert doc(run(capsys, "printer", "list", "--json")[1]) == []


# ---------- show ----------

def test_show_a_bambu_printer_with_its_slots(capsys, hub):
    seed()
    rc, out, err = run(capsys, "printer", "show", "workshop")
    assert (rc, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == "Workshop X1"
    assert lines[1].split(None, 1) == ["Model", "Bambu Lab X1 Carbon"]
    assert [ln.split()[0] for ln in lines[1:7]] == ["Model", "Address", "Serial", "State", "Certificate", "Slots"]
    assert "192.0.2.40" in lines[2] and X1 in lines[3] and lines[4].endswith("connected")
    assert lines[5].endswith("not pinned yet") and lines[6].endswith("not mapped")
    assert lines[8].split() == ["SLOT", "FILAMENT", "COLOUR", "LEFT"]
    assert lines[9].startswith("A1") and "Polymaker PolyTerra PLA Charcoal Black" in lines[9] and "#2B2B2E" in lines[9]
    assert lines[9].rstrip().endswith("620 g")
    assert lines[10].split()[:3] == ["A2", "PETG", "#F2762E"] and lines[11].split() == ["A4", "empty"]


def test_show_a_printer_that_is_offline_has_no_slot_data(capsys, hub):
    seed()
    out = run(capsys, "printer", "show", "study")[1]
    assert out.splitlines()[-1] == "No slot data while offline."


def test_show_without_a_hub_says_so(capsys):
    seed()
    out = run(capsys, "printer", "show", "workshop")[1]
    assert out.splitlines()[-1] == "No slot data while the Hub is not running."
    assert "unknown" in out.splitlines()[4]


def test_show_a_klipper_printer_has_its_key_and_lane_data(capsys, hub):
    seed()
    registry.set_api_key("garage-voron", "k3y")
    out = run(capsys, "printer", "show", "garage")[1]
    lines = out.splitlines()
    assert lines[0] == "Garage Voron" and [ln.split()[0] for ln in lines[1:7]] == [
        "Model", "Address", "ID", "State", "API", "Lane"]
    assert "voron.example:7125" in lines[2] and "garage-voron" in lines[3]
    assert lines[5].endswith("set") and lines[6].endswith("auto") and "k3y" not in out
    assert "Certificate" not in out


def test_show_json_is_the_one_printer_object(capsys, hub):
    seed()
    assert doc(run(capsys, "printer", "show", "garage", "--json")[1]) == next(
        r for r in cli._Hub(hub).rows() if r["serial"] == "garage-voron")


# ---------- test ----------

def test_test_a_bambu_printer_says_ok_and_gives_the_hubs_reply_under_json(capsys, hub, monkeypatch):
    seed()
    monkeypatch.setattr(tlspin, "leaf_fp", lambda ip, port: "ab" * 32)
    registry.pin(X1, "ab" * 32)
    rc, out, err = run(capsys, "printer", "test", "workshop")
    assert (rc, err) == (0, "")
    assert unglyph(out) == "OK 192.0.2.40 answers; its certificate matches the pinned one."
    rc, out, err = run(capsys, "printer", "test", "workshop", "--json")
    assert doc(out) == {"reachable": True, "state": "connected",
                        "text": "192.0.2.40 answers; its certificate matches the pinned one"}


def test_test_that_gets_no_answer_fails_with_exit_1(capsys, monkeypatch):
    seed()

    def nothing(ip, port):
        raise OSError("down")
    monkeypatch.setattr(tlspin, "leaf_fp", nothing)
    rc, out, err = run(capsys, "printer", "test", "study")
    assert rc == 1 and err == ""
    assert unglyph(out) == "failed No answer from 192.0.2.41:8883 (OSError): check that it is on."
    rc, out, err = run(capsys, "printer", "test", "study", "--json")
    assert rc == 1 and doc(out) == {"reachable": False, "state": "unknown",
                                    "text": "no answer from 192.0.2.41:8883 (OSError): check that it is on"}


def test_test_a_klipper_printer(capsys, monkeypatch):
    seed()
    monkeypatch.setattr(setup_page.Moonraker, "info", lambda self: {"state": "ready"})
    rc, out, err = run(capsys, "printer", "test", "garage")
    assert rc == 0 and unglyph(out) == "OK Moonraker at voron.example:7125 answers; Klipper is ready."


# ---------- add ----------

def test_add_a_bambu_printer_reads_the_access_code_from_standard_input(capsys, monkeypatch):
    stdin(monkeypatch, "24681357\n")
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip, timeout=5: X1)
    rc, out, err = run(capsys, "printer", "add", "--address", "192.168.50.40", "--access-code", "-", "--name", "Workshop X1")
    assert (rc, err) == (0, "")
    assert out == f"Added Workshop X1 (serial {X1}).\n"
    p = registry.load()[X1]
    assert (p.name, p.ip, p.access_code, p.configured, p.family) == ("Workshop X1", "192.168.50.40", "24681357", True, "bambu")


def test_add_a_bambu_printer_json(capsys, monkeypatch):
    stdin(monkeypatch, "24681357\n")
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip, timeout=5: X1)
    rc, out, err = run(capsys, "printer", "add", "--address", "192.168.50.40", "--access-code", "-", "--json")
    assert rc == 0 and doc(out) == {"ok": True, "serial": X1, "name": X1}
    assert "24681357" not in out


def test_add_asks_for_what_the_flags_leave_out_in_the_order_of_06_8_7(capsys, monkeypatch, terminal):
    asked = terminal(True, "192.168.50.40", "Workshop X1", "")
    monkeypatch.setattr(cli.secret_input, "ask", lambda prompt: asked.append(prompt) or "24681357")
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip, timeout=5: X1)
    rc, out, err = run(capsys, "printer", "add")
    assert rc == 0, err
    assert asked == ["IP address or name (e.g. 192.0.2.40 or printer.local): ",
                     "Access Code (on the printer: Settings > Network/LAN): ", "Name (optional): ",
                     "Serial (optional: read from the printer): "]
    assert registry.load()[X1].name == "Workshop X1"


def test_add_with_an_empty_access_code_adds_nothing(capsys, monkeypatch):
    stdin(monkeypatch, "\n")
    rc, out, err = run(capsys, "printer", "add", "--address", "192.168.50.40", "--access-code", "-")
    assert (rc, out, err) == (5, "No Access Code entered; nothing added.\n", "")
    assert registry.load() == {}


def test_add_with_no_terminal_and_no_address_stops_with_exit_2(capsys, terminal):
    terminal(False)
    rc, out, err = run(capsys, "printer", "add")
    assert (rc, out) == (2, "")
    assert err == "Error: printer add needs an address, and there is no terminal to ask.\nFix: give it with --address.\n"


def test_add_never_asks_under_json(capsys, terminal, monkeypatch):
    terminal(True, "192.168.50.40")
    rc, out, err = run(capsys, "printer", "add", "--json")
    assert rc == 2 and doc(out)["ok"] is False


def test_a_secret_is_never_a_command_line_value(capsys):
    rc, out, err = run(capsys, "printer", "add", "--address", "192.168.50.40", "--access-code", "24681357")
    assert rc == 2 and "a secret is never given on the command line" in err and registry.load() == {}


def test_the_hubs_refusal_is_printed_as_an_error(capsys, monkeypatch):
    stdin(monkeypatch, "bad code!\n")
    rc, out, err = run(capsys, "printer", "add", "--address", "192.168.50.40", "--access-code", "-")
    assert rc == 2 and out == "" and err.startswith("Error: the Access Code is")
    assert registry.load() == {}


def test_add_a_klipper_printer(capsys, monkeypatch):
    rc, out, err = run(capsys, "printer", "add", "--klipper", "--address", "127.0.0.1", "--port", "9", "--name", "Garage Voron")
    assert rc == 0
    assert out == "Added Garage Voron as garage-voron (127.0.0.1:9).\n"
    assert "Note: Moonraker at 127.0.0.1:9 is not answering" in err
    p = registry.load()["garage-voron"]
    assert (p.family, p.host, p.port, p.configured) == ("klipper", "127.0.0.1", 9, True)


def test_add_a_klipper_printer_says_what_it_found_under_json(capsys, moonraker):
    rc, out, err = run(capsys, "printer", "add", "--klipper", "--address", moonraker.host, "--port", str(moonraker.port),
                       "--name", "Box", "--json")
    d = doc(out)
    assert rc == 0 and d["ok"] is True and d["id"] == "box" and d["detect"]["ok"] is True and "slots" in d["detect"]


def test_add_a_klipper_printer_keeps_the_api_key_from_standard_input(capsys, monkeypatch):
    stdin(monkeypatch, "s3cretkey\n")
    rc, out, err = run(capsys, "printer", "add", "--klipper", "--address", "127.0.0.1", "--port", "9", "--api-key", "-")
    assert rc == 0 and registry.load()["127-0-0-1"].api_key == "s3cretkey" and "s3cretkey" not in out + err


def test_add_a_klipper_printer_asks_in_the_order_of_06_8_7(capsys, monkeypatch, terminal):
    asked = terminal(True, "127.0.0.1", "9", "Box")
    monkeypatch.setattr(cli.secret_input, "ask", lambda prompt: asked.append(prompt) or "")
    rc, out, err = run(capsys, "printer", "add", "--klipper")
    assert rc == 0, err
    assert asked == ["Address: ", "Port [7125]: ", "Name (optional): ", "Moonraker API key (optional): "]


def test_add_a_klipper_printer_twice_is_exit_1(capsys):
    argv = ["printer", "add", "--klipper", "--address", "127.0.0.1", "--port", "9", "--name", "Box"]
    assert run(capsys, *argv)[0] == 0
    rc, out, err = run(capsys, *argv)
    assert rc == 1 and "Box is already at 127.0.0.1:9" in err        # the Hub's own words (409)


def test_add_a_klipper_printer_by_a_name_a_scan_found_converts_the_found_entry(capsys):
    registry.detected_klipper("127.0.0.1", 7125, name="mainsailos", lookups=False)
    rc, out, err = run(capsys, "printer", "add", "--klipper", "--address", "localhost", "--name", "Box")
    assert rc == 0, err
    klippers = [p for p in registry.load().values() if p.family == "klipper"]
    assert [(p.serial, p.configured) for p in klippers] == [("mainsailos", True)]       # the Hub's result: one printer
    assert klippers[0].host == "localhost" and registry.display_name(klippers[0]) == "Box"


def test_scan_of_a_public_network_is_refused_in_the_hubs_words(capsys, monkeypatch):
    monkeypatch.setattr(discovery, "scan", lambda net, **kw: pytest.fail("a public network was scanned"))
    rc, out, err = run(capsys, "printer", "scan", "--subnet", "8.8.8.0/24")
    assert (rc, out) == (2, "") and "scan your own network: a private IPv4 subnet" in err


def test_a_module_that_is_off_hides_its_printers_as_the_hub_does(capsys):
    seed()
    cfg = config.load()
    cfg["modules"] = {"printers": True, "klipper": False}
    config.save(cfg)
    rows = doc(run(capsys, "printer", "list", "--json")[1])
    assert [r["family"] for r in rows] == ["bambu", "bambu"]
    rc, out, err = run(capsys, "printer", "show", "garage")
    assert rc == 2 and "does not name one printer" in err
    rc, out, err = run(capsys, "printer", "add", "--klipper", "--address", "127.0.0.1", "--port", "9")
    assert rc == 1 and "the klipper module is off on this server" in err
    rc, out, err = run(capsys, "printer", "scan", "--subnet", "192.0.2.0/24")
    assert rc == 1 and "the klipper module is off on this server" in err


def test_a_module_that_is_off_says_how_to_turn_it_on(capsys):
    cfg = config.load()
    cfg["modules"] = {"printers": True, "klipper": False}
    config.save(cfg)
    for argv in (["add", "--klipper", "--address", "127.0.0.1", "--port", "9"], ["scan", "--subnet", "192.0.2.0/24"]):
        rc, out, err = run(capsys, "printer", *argv)
        assert rc == 1 and "the klipper module is off on this server" in err
        assert squash(err).endswith("Fix: sudo spoolwarden modules enable klipper")
    d = doc(run(capsys, "printer", "scan", "--json")[1])
    assert d["ok"] is False and d["fix"] == "sudo spoolwarden modules enable klipper"


@pytest.mark.parametrize("argv", [["list"], ["show", "garage"], ["detect", "garage"], ["add", "--klipper", "--address",
                                  "127.0.0.1", "--port", "9"], ["forget", "garage", "--yes"], ["scan", "--subnet", "192.0.2.0/24"],
                                  ["use", "mainsailos"], ["rename", "garage", "X"], ["reports", "workshop"], ["live", "garage"]])
def test_an_unreadable_config_stops_every_printer_command(capsys, argv):
    seed()
    (config.paths().etc / "config.json").write_text("{not json", encoding="utf-8")
    rc, out, err = run(capsys, "printer", *argv)
    assert (rc, out) == (1, "") and err.startswith("Error: ") and "Traceback" not in err
    assert "config.json cannot be read" in err and "\nFix: " in err
    rc, out, err = run(capsys, "printer", *argv, "--json")
    d = doc(out)
    assert rc == 1 and d["ok"] is False and "config.json cannot be read" in d["error"] and d["fix"]
    assert "Traceback" not in err


def test_scan_names_no_network_the_hub_refuses(capsys, monkeypatch):
    said = []
    monkeypatch.setattr(output, "wait", lambda text, *a, **kw: said.append(text) or pytest.fail("waited: " + text))
    monkeypatch.setattr(discovery, "scan", lambda net, **kw: pytest.fail("a public network was scanned"))
    for subnet in ("8.8.8.0/24", "10.0.0.0/16", "not a network"):
        rc, out, err = run(capsys, "printer", "scan", "--subnet", subnet)
        assert rc == 2 and "Looking for" not in out + err and err.startswith("Error: ")
    assert said == []


def test_list_at_80_columns_with_a_long_host_is_blocks_not_a_cut_address(capsys, monkeypatch):
    seed()
    host = "voron-with-a-rather-long-name-for-this-test.workshop.example"
    registry.add_klipper("Long Host", host, 7125)
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)
    out = run(capsys, "printer", "list")[1]
    assert all(len(ln) <= 79 for ln in out.splitlines())
    assert f"Address: {host}:7125" in out.splitlines() and "…" not in out and "..." not in out


def test_the_old_klipper_add_is_the_same_command(capsys):
    rc, out, err = run(capsys, "klipper", "add", "Garage Voron", "127.0.0.1", "--port", "9")
    assert rc == 0 and out == "Added Garage Voron as garage-voron (127.0.0.1:9).\n"


# ---------- use, dismiss, forget ----------

def test_use_puts_a_found_klipper_printer_into_use(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "use", "mainsail")
    assert (rc, out, err) == (0, "Added mainsailos (192.0.2.57:7125).\n", "")
    assert registry.load()["mainsailos"].configured is True


def test_use_keeps_the_api_key_from_standard_input(capsys, monkeypatch):
    seed()
    stdin(monkeypatch, "s3cretkey\n")
    assert run(capsys, "printer", "use", "mainsail", "--api-key", "-")[0] == 0
    assert registry.load()["mainsailos"].api_key == "s3cretkey"


def test_use_on_a_printer_already_added_is_exit_1_and_on_a_found_bambu_printer_points_to_add(capsys):
    seed()
    assert run(capsys, "printer", "use", "garage")[0] == 1
    registry.detected("03000A000000009", "192.0.2.90", "A1M", "Found A1")
    rc, out, err = run(capsys, "printer", "use", "found a1")
    assert rc == 2 and "Fix: sudo spoolwarden printer add --address 192.0.2.90" in err


def test_dismiss_asks_and_forgets_the_found_printer(capsys, terminal):
    seed()
    terminal(True, "y")
    rc, out, err = run(capsys, "printer", "dismiss", "mainsail")
    assert rc == 0 and squash(out).startswith("Dismiss mainsailos? It leaves this list. A new scan may find it again. [y/N]")
    assert out.endswith("Dismissed mainsailos.\n") and "mainsailos" not in registry.load()


def test_dismiss_an_added_printer_points_to_forget(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "dismiss", "garage", "--yes")
    assert rc == 2 and err.splitlines()[1] == 'Fix: sudo spoolwarden printer forget "Garage Voron"'


FORGET = [("printer forget workshop", f"Forget Workshop X1? filament-kit stops connecting to it and deletes its Access "
                                      "Code. To use it again, add it again. [y/N] ", "Forgot Workshop X1.", X1),
          ("printer forget garage", "Forget Garage Voron? filament-kit stops connecting to it and deletes its Moonraker "
                                    "API key, if one is saved. [y/N] ", "Forgot Garage Voron.", "garage-voron"),
          ("printer dismiss mainsailos", "Dismiss mainsailos? It leaves this list. A new scan may find it again. [y/N] ",
           "Dismissed mainsailos.", "mainsailos")]


@pytest.mark.parametrize("command, question, result, serial", FORGET, ids=[f[0] for f in FORGET])
def test_a_destructive_printer_command_asks_first(capsys, terminal, command, question, result, serial):
    seed()
    argv = command.split()
    terminal(False)                                           # piped, no --yes: exit 2, nothing done
    rc, out, err = run(capsys, *argv)
    assert (rc, out) == (2, "") and "needs a yes, and there is no terminal to ask." in squash(err)
    assert err.rstrip().endswith("--yes") and serial in registry.load()
    terminal(True, "n")                                       # no: exit 5
    rc, out, err = run(capsys, *argv)
    assert rc == 5 and squash(out) == squash(question) + " Nothing changed." and serial in registry.load()
    terminal(True, "YES")                                     # yes: done
    rc, out, err = run(capsys, *argv)
    assert rc == 0 and out.endswith(result + "\n") and serial not in registry.load()


@pytest.mark.parametrize("command, question, result, serial", FORGET, ids=[f[0] for f in FORGET])
def test_yes_answers_the_question_and_prints_the_result(capsys, terminal, command, question, result, serial):
    seed()
    asked = terminal(False)
    rc, out, err = run(capsys, *command.split(), "--yes")
    assert (rc, out, err) == (0, result + "\n", "") and asked == [] and serial not in registry.load()


def test_forget_json_needs_yes_and_gives_the_result(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "forget", "workshop", "--json")
    assert rc == 2 and doc(out)["ok"] is False and X1 in registry.load()
    rc, out, err = run(capsys, "printer", "forget", "workshop", "--json", "--yes")
    assert rc == 0 and doc(out) == {"ok": True, "serial": X1, "name": "Workshop X1"}


# ---------- changes that need no question ----------

def test_rename(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "rename", "workshop", "Workshop X1C")
    assert (rc, out, err) == (0, "Renamed Workshop X1 to Workshop X1C.\n", "")
    assert registry.load()[X1].name == "Workshop X1C"
    assert doc(run(capsys, "printer", "rename", X1, "Shop", "--json")[1]) == {"ok": True, "serial": X1, "name": "Shop"}


def test_rename_to_nothing_or_too_long_is_the_hubs_refusal(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "rename", "workshop", "x" * 65)
    assert rc == 2 and err.startswith("Error: name must be text") and registry.load()[X1].name == "Workshop X1"


def test_address_of_a_bambu_printer_asks_for_the_access_code(capsys, monkeypatch):
    seed()
    stdin(monkeypatch, "24681357\n")
    rc, out, err = run(capsys, "printer", "address", "workshop", "192.168.50.42", "--access-code", "-")
    assert rc == 0 and out == "Saved. Workshop X1 is at 192.168.50.42.\n"
    assert (registry.load()[X1].ip, registry.load()[X1].access_code) == ("192.168.50.42", "24681357")


def test_address_with_no_access_code_changes_nothing(capsys, monkeypatch):
    seed()
    stdin(monkeypatch, "\n")
    rc, out, err = run(capsys, "printer", "address", "workshop", "192.168.50.42", "--access-code", "-")
    assert (rc, out) == (5, "No Access Code entered; nothing changed.\n") and registry.load()[X1].ip == "192.0.2.40"


def test_address_of_a_klipper_printer_takes_a_port_and_asks_for_nothing(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "address", "garage", "192.0.2.60", "--port", "7126")
    assert rc == 0 and out == "Saved. Garage Voron is at 192.0.2.60:7126.\n"
    assert err.startswith("Note: 192.0.2.60 is outside the networks")        # the Hub's note
    p = registry.load()["garage-voron"]
    assert (p.host, p.port) == ("192.0.2.60", 7126)


def test_address_that_is_not_an_address_is_the_hubs_refusal(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "address", "garage", "192.0.2.999")
    assert rc == 2 and out == "" and err.startswith("Error: ") and registry.load()["garage-voron"].host == "voron.example"


def test_access_code(capsys, monkeypatch):
    seed()
    stdin(monkeypatch, "24681357\n")
    rc, out, err = run(capsys, "printer", "access-code", "workshop", "--access-code", "-")
    assert (rc, out, err) == (0, "Saved the Access Code of Workshop X1.\n", "")
    assert registry.load()[X1].access_code == "24681357"
    stdin(monkeypatch, "\n")                                    # an empty answer changes nothing
    assert run(capsys, "printer", "access-code", "workshop", "--access-code", "-")[1] == "Unchanged.\n"
    assert registry.load()[X1].access_code == "24681357"


def test_access_code_is_asked_with_its_prompt_and_never_printed(capsys, monkeypatch):
    seed()
    asked = []
    monkeypatch.setattr(cli.secret_input, "ask", lambda prompt: asked.append(prompt) or "24681357")
    rc, out, err = run(capsys, "printer", "access-code", "workshop")
    assert rc == 0 and asked == ["New Access Code for Workshop X1 (on the printer: Settings > Network/LAN): "]
    assert "24681357" not in out + err


def test_access_code_never_asks_under_json(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "access-code", "workshop", "--json")
    assert rc == 2 and doc(out)["ok"] is False and registry.load()[X1].access_code == "12345678"


def test_api_key(capsys, monkeypatch):
    seed()
    stdin(monkeypatch, "s3cretkey\n")
    rc, out, err = run(capsys, "printer", "api-key", "garage", "--api-key", "-")
    assert (rc, out, err) == (0, "Saved the API key of Garage Voron.\n", "")
    assert registry.load()["garage-voron"].api_key == "s3cretkey"
    stdin(monkeypatch, "\n")                                    # an empty answer no longer clears the key
    assert run(capsys, "printer", "api-key", "garage", "--api-key", "-")[1] == "Unchanged.\n"
    assert registry.load()["garage-voron"].api_key == "s3cretkey"


def test_api_key_with_a_space_is_the_hubs_refusal(capsys, monkeypatch):
    seed()
    stdin(monkeypatch, "two words\n")
    rc, out, err = run(capsys, "printer", "api-key", "garage", "--api-key", "-")
    assert rc == 2 and err.startswith("Error: a Moonraker API key has no spaces")


def test_api_key_clear_asks_first(capsys, terminal):
    seed()
    registry.set_api_key("garage-voron", "s3cretkey")
    question = ("Clear the Moonraker API key of Garage Voron? filament-kit then connects without a key. If Moonraker asks "
                "for one, the printer's test says so until a key is set. [y/N] ")
    terminal(False)
    rc, out, err = run(capsys, "printer", "api-key", "garage", "--clear")
    assert (rc, out) == (2, "") and registry.load()["garage-voron"].api_key == "s3cretkey"
    terminal(True, "n")
    rc, out, err = run(capsys, "printer", "api-key", "garage", "--clear")
    assert rc == 5 and squash(out) == squash(question) + " Nothing changed."
    assert registry.load()["garage-voron"].api_key == "s3cretkey"
    terminal(True, "y")
    rc, out, err = run(capsys, "printer", "api-key", "garage", "--clear")
    assert rc == 0 and out.endswith("Cleared the API key of Garage Voron.\n") and registry.load()["garage-voron"].api_key == ""
    registry.set_api_key("garage-voron", "s3cretkey")
    assert run(capsys, "printer", "api-key", "garage", "--clear", "--yes")[1] == "Cleared the API key of Garage Voron.\n"


def test_api_key_clear_and_a_key_do_not_go_together(capsys):
    seed()
    assert run(capsys, "printer", "api-key", "garage", "--clear", "--api-key", "-")[0] == 2


def test_the_old_klipper_api_key_is_the_same_command(capsys, monkeypatch):
    seed()
    monkeypatch.setattr(cli.secret_input, "ask", lambda prompt: "s3cretkey")
    rc, out, err = run(capsys, "klipper", "api-key", "garage")
    assert (rc, out) == (0, "Saved the API key of Garage Voron.\n") and registry.load()["garage-voron"].api_key == "s3cretkey"


def test_lane_data(capsys):
    seed()
    rc, out, err = run(capsys, "printer", "lane-data", "garage", "on")
    assert (rc, out, err) == (0, "Saved. Lane data: on.\n", "") and registry.load()["garage-voron"].lane_data == "on"
    assert run(capsys, "printer", "lane-data", "garage", "sometimes")[0] == 2
    assert run(capsys, "klipper", "set", "garage", "--lane-data", "off")[1] == "Saved. Lane data: off.\n"
    assert doc(run(capsys, "printer", "lane-data", "garage", "auto", "--json")[1]) == {
        "ok": True, "serial": "garage-voron", "name": "Garage Voron", "lane_data": "auto"}


def test_detect(capsys, moonraker):
    registry.add_klipper("Box", moonraker.host, moonraker.port)
    rc, out, err = run(capsys, "printer", "detect", "box")
    assert rc == 0 and out.startswith("Box: ") and ". Slots: " in out


def test_scan_lists_what_it_found_and_what_is_added(capsys, monkeypatch):
    seed()
    registry.add_klipper("Lathe", "192.0.2.60", 7125)
    monkeypatch.setattr(discovery, "scan", lambda net, **kw: [("192.0.2.60", 7125), ("192.0.2.99", 7125)])
    rc, out, err = run(capsys, "printer", "scan", "--subnet", "192.0.2.0/24")
    assert rc == 0, err
    found = next(p.serial for p in registry.load().values() if p.host == "192.0.2.99")
    assert squash(out) == (f"Found on 192.0.2.0/24: 192.0.2.60:7125 (added as Lathe) Found on 192.0.2.0/24: "
                           f"192.0.2.99:7125 (add it: sudo spoolwarden printer use {found})")
    d = doc(run(capsys, "printer", "scan", "--subnet", "192.0.2.0/24", "--json")[1])
    assert d["ok"] is True and d["subnet"] == "192.0.2.0/24" and [f["configured"] for f in d["found"]] == [True, False]
    assert {"serial", "host", "port", "configured"} <= set(d["found"][0])


def test_scan_that_finds_nothing(capsys, monkeypatch):
    monkeypatch.setattr(discovery, "scan", lambda net, **kw: [])
    rc, out, err = run(capsys, "printer", "scan", "--subnet", "192.0.2.0/24")
    assert (rc, out) == (0, "No Moonraker found on 192.0.2.0/24.\n")


def test_scan_of_too_big_a_network_is_exit_2(capsys):
    rc, out, err = run(capsys, "printer", "scan", "--subnet", "10.0.0.0/16")
    assert rc == 2 and "at most a /24" in err


def test_reports(capsys, monkeypatch):
    seed()
    from filament_kit.bridge import printer_report
    assert run(capsys, "printer", "reports", "workshop")[1] == "No report kept for this printer yet.\n"
    kept = [{"name": "printer-report-1.xml", "size": 4096, "at": 1762000000.0}]
    monkeypatch.setattr(printer_report, "saved", lambda serial: kept)
    rc, out, err = run(capsys, "printer", "reports", "workshop")
    lines = out.splitlines()
    assert rc == 0 and lines[0].split() == ["MADE", "SIZE", "NAME"] and lines[1].split()[2:] == ["4", "KiB", "printer-report-1.xml"]
    assert lines[2].startswith("Kept in")
    d = doc(run(capsys, "printer", "reports", "workshop", "--json")[1])
    assert d["reports"] == [{"name": "printer-report-1.xml", "size": 4096, "at": d["reports"][0]["at"]}]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", d["reports"][0]["at"]) and d["never"]


# ---------- forget-certificate (once unpin), map, report: what they did, on the printer a name stands for ----------

def test_forget_certificate_asks_and_takes_the_access_code_from_standard_input(capsys, monkeypatch, terminal):
    seed()
    registry.pin(X1, "ab" * 32)
    stdin(monkeypatch, "24681357\n")
    terminal(True, "y")
    rc, out, err = run(capsys, "printer", "forget-certificate", "workshop", "--access-code", "-")
    assert rc == 0, err
    assert squash(out).startswith("Forget the certificate of Workshop X1? The next connection trusts whatever "
                                  "certificate answers at 192.0.2.40 and remembers it. Do this only after the printer was "
                                  "reset or replaced. [y/N]")
    assert squash(out).endswith("Forgot the certificate of Workshop X1; the next connection pins the one it presents.")
    assert registry.load()[X1].cert_fp == "" and registry.load()[X1].access_code == "24681357"


def test_forget_certificate_with_an_empty_access_code_changes_nothing(capsys, monkeypatch):
    seed()
    registry.pin(X1, "ab" * 32)
    stdin(monkeypatch, "\n")
    rc, out, err = run(capsys, "printer", "forget-certificate", "workshop", "--access-code", "-", "--yes")
    assert (rc, out) == (5, "No Access Code entered; nothing changed.\n") and registry.load()[X1].cert_fp == "ab" * 32


def test_forget_certificate_asks_for_the_code_with_the_prompt_of_06_8_7(capsys, monkeypatch):
    seed()
    asked = []
    monkeypatch.setattr(cli.secret_input, "ask", lambda prompt: asked.append(prompt) or "24681357")
    assert run(capsys, "printer", "unpin", "workshop", "--yes")[0] == 0
    assert asked == ["Access Code of Workshop X1 (on the printer: Settings > Network/LAN): "]


def test_forget_certificate_under_json_needs_the_code_on_standard_input(capsys, monkeypatch):
    seed()
    rc, out, err = run(capsys, "printer", "forget-certificate", "workshop", "--yes", "--json")
    assert rc == 2 and doc(out)["ok"] is False
    stdin(monkeypatch, "24681357\n")
    rc, out, err = run(capsys, "printer", "forget-certificate", "workshop", "--yes", "--json", "--access-code", "-")
    assert rc == 0 and doc(out) == {"ok": True, "serial": X1, "name": "Workshop X1"}


def test_map_and_report_take_the_name_and_run_as_before(capsys, monkeypatch):
    seed()
    seen = []
    monkeypatch.setattr(cli, "cmd_printer_map", lambda serial, mf, manual=False, yes=False: seen.append(("map", serial, manual, yes)) or 0)
    monkeypatch.setattr(cli, "cmd_printer_report", lambda serial, mf: seen.append(("report", serial)) or 0)
    assert run(capsys, "printer", "map", "workshop", "--yes")[0] == 0
    assert run(capsys, "printer", "map", "garage", "--by-loading")[0] == 0
    assert run(capsys, "printer", "map", "garage", "--manual")[0] == 0              # the old spelling
    assert run(capsys, "printer", "report", "study")[0] == 0
    assert seen == [("map", X1, False, True), ("map", "garage-voron", True, False), ("map", "garage-voron", True, False),
                    ("report", A1)]


# ---------- live, menu, add-on ----------

def test_live_says_where_the_camera_is(capsys, monkeypatch):
    seed()
    monkeypatch.setattr(cli.pairing, "local_ips", lambda: ["192.0.2.10"])
    rc, out, err = run(capsys, "printer", "live", "workshop")
    assert rc == 0 and squash(out) == "Camera and controls are in the web app: https://192.0.2.10:8710/intake#printers"
    assert doc(run(capsys, "printer", "live", "workshop", "--json")[1]) == {
        "available": False, "where": "web app", "url": "https://192.0.2.10:8710/intake#printers"}


def test_menu_opens_the_printers_screen_and_refuses_json(capsys, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "_printers_screen", lambda ui: opened.append(1))
    monkeypatch.setattr(cli.menu_ui, "_stdin_tty", lambda: True)
    monkeypatch.setattr(cli.menu_ui, "open_ui", lambda *a, **k: __import__("contextlib").nullcontext(object()))
    assert run(capsys, "printer", "menu")[0] == 0 and opened == [1]
    rc, out, err = run(capsys, "printer", "menu", "--json")
    assert rc == 2 and opened == [1]
    assert doc(out) == {"ok": False, "error": "printer menu is a menu.", "fix": "use spoolwarden printer list --json"}


def test_the_klipper_add_on_has_both_spellings(capsys, monkeypatch):
    from filament_kit import klipper_cli
    monkeypatch.setattr(klipper_cli, "pack", lambda *a, **k: print("the add-on") or 0)
    assert run(capsys, "klipper", "add-on")[1] == "the add-on\n"
    assert run(capsys, "klipper", "pack")[1] == "the add-on\n"


# ---------- --quiet ----------

def test_quiet_drops_the_result_line_and_keeps_the_list_and_the_errors(capsys):
    seed()
    assert run(capsys, "--quiet", "printer", "rename", "workshop", "Shop") == (0, "", "")
    assert run(capsys, "-q", "printer", "lane-data", "garage", "on")[1] == ""
    assert run(capsys, "-q", "printer", "list")[1].startswith("NAME ")
    rc, out, err = run(capsys, "-q", "printer", "rename", "mainsail", "X")
    assert rc == 2 and err.startswith("Error: mainsailos is found")
