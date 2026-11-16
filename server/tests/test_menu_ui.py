"""The menus' one key map and its two variants (06 8.1, 8.2): the keys as a state machine, the numbered lines, the
full-screen drawing and its footer prompts on a stand-in for curses, which variant starts when, and the real screen in a
pty (Linux)."""
from __future__ import annotations

import contextlib
import io
import os
import select
import signal
import subprocess
import sys
import time
import types

import pytest

from filament_kit import cli, config, menu_ui, modules, output
from filament_kit.menu_ui import (ESC, KEY_DOWN, KEY_END, KEY_ENTER, KEY_HOME, KEY_NPAGE, KEY_PPAGE, KEY_UP, Keys, Row,
                                  Screen)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt", "bk"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    return tmp_path


def menu(n=4, **kw) -> Screen:
    return Screen("t", "Settings > Test", [Row(f"Item {i}", f"value {i}") for i in range(1, n + 1)], save="save", **kw)


def checklist(n=14, **kw) -> Screen:
    kw.setdefault("actions", (("h", "Hub setup"), ("w", "Weigh Station only"), ("b", "Hub with Weigh Station")))
    return Screen("c", "Features", [Row(f"Feature {i}", "", mark=" ") for i in range(1, n + 1)], kind="checklist",
                  save="apply", **kw)


def press(keys: Keys, text) -> list:
    """The events of typing `text` (a str of characters, or ints for the special keys)."""
    out = []
    for ch in text:
        ev = keys.key(ord(ch) if isinstance(ch, str) else ch)
        if ev:
            out.append(ev)
    return out


# ---------- 8.2: the key map, as a state machine ----------

def test_the_cursor_moves_with_arrows_jk_home_end_and_pages_and_stays_in_range():
    k = Keys(menu(20))
    press(k, [KEY_DOWN, KEY_DOWN])
    assert k.cursor == 2
    press(k, "kj")
    assert k.cursor == 2
    press(k, [KEY_UP] * 9)
    assert k.cursor == 0
    press(k, [KEY_NPAGE])
    assert k.cursor == 5
    press(k, [KEY_NPAGE] * 9)
    assert k.cursor == 19
    press(k, [KEY_PPAGE])
    assert k.cursor == 14
    press(k, [KEY_HOME])
    assert k.cursor == 0
    press(k, [KEY_END])
    assert k.cursor == 19


def test_enter_on_the_row_opens_it_in_a_menu_and_switches_it_in_a_checklist_and_never_applies():
    k = Keys(menu())
    assert press(k, [KEY_DOWN, 10]) == [("open", 1)]
    assert press(k, [13]) == [("open", 1)] and press(k, [KEY_ENTER]) == [("open", 1)]
    c = Keys(checklist())
    assert press(c, [KEY_DOWN, 10, KEY_ENTER, 13]) == [("toggle", [1])] * 3       # Enter switches; none of them applies
    assert press(c, " ") == [("toggle", [1])]                                     # Space does the same


def test_typing_a_number_opens_the_item_at_once_when_no_longer_number_starts_with_it():
    k = Keys(menu(4))
    assert press(k, "3") == [("open", 2)]
    big = Keys(menu(12))
    assert press(big, "3") == [("open", 2)]               # 30 > 12: nothing longer starts with 3
    assert press(big, "1") == [] and press(big, [10]) == [("open", 0)]      # 1 could be 10, 11, 12: Enter ends it
    assert press(big, "1") == [] and press(big, "1") == [("open", 10)]      # or one more digit
    assert press(big, "7") == [("open", 6)]
    assert press(big, "9") == [("open", 8)] and press(big, "x") == [("unknown", "x")]
    assert press(Keys(menu(4)), "9") == [("unknown", "9")]                # no such number


def test_letters_choose_actions_and_s_q_esc_question_mark_do_the_same_on_every_screen():
    for screen in (menu(), checklist()):
        k = Keys(screen)
        assert press(k, "s") == [("save",)]
        assert press(k, "q") == [("leave",)] and press(k, [ESC]) == [("leave",)]
        assert press(k, "?") == [("help",)]
    assert press(Keys(checklist()), "hwb") == [("action", "h"), ("action", "w"), ("action", "b")]
    assert press(Keys(menu()), "h") == [("unknown", "h")]                  # no setup letters on a menu
    no_save = Screen("n", "t", [Row("a")])
    assert press(Keys(no_save), "s") == [("unknown", "s")]


def test_a_screens_own_letters_come_before_j_and_k():
    sc = Screen("p", "Printers > A", [Row("a"), Row("b")], actions=(("k", "replace Access Code"), ("r", "rename")))
    k = Keys(sc)
    assert press(k, "kj") == [("action", "k")] and k.cursor == 1       # k is the action; j still moves


def test_a_checklist_switches_by_space_on_the_cursor_row_and_by_number():
    c = Keys(checklist())
    assert press(c, [KEY_DOWN, KEY_DOWN, " "]) == [("toggle", [2])]
    assert press(c, "5") == [("toggle", [4])]


# ---------- 8.1, 8.2: the numbered variant ----------

def test_parse_line_numbers_choose_letters_act_and_the_rest_is_unknown():
    m, c = menu(), checklist(actions=(("h", "Hub setup"),))
    assert menu_ui.parse_line(m, "3") == ("open", 2)
    assert menu_ui.parse_line(m, " 2 ") == ("open", 1)
    assert menu_ui.parse_line(m, "S") == ("save",) and menu_ui.parse_line(m, "q") == ("leave",)
    assert menu_ui.parse_line(m, "?") == ("help",) and menu_ui.parse_line(m, "") == ("empty",)
    assert menu_ui.parse_line(m, "0") == ("unknown", "0") and menu_ui.parse_line(m, "9") == ("unknown", "9")
    assert menu_ui.parse_line(m, "x") == ("unknown", "x") and menu_ui.parse_line(m, "1 2") == ("unknown", "2")
    assert menu_ui.parse_line(c, "2 5 7") == ("toggle", [1, 4, 6]) and menu_ui.parse_line(c, "2,5") == ("toggle", [1, 4])
    assert menu_ui.parse_line(c, "h") == ("action", "h") and menu_ui.parse_line(c, "15") == ("unknown", "15")
    assert menu_ui.parse_line(c, "2 h") == ("unknown", "h")


def _numbered(monkeypatch, text):
    answers = iter(text.splitlines())
    return menu_ui.NumberedUi(lambda prompt: print(prompt, end="") or next(answers, None))


def test_the_numbered_screen_has_the_header_the_numbered_rows_and_the_keys_line(capsys):
    sc = menu(3, changes=2)
    lines = menu_ui.numbered_lines(sc)
    assert lines[0] == "Settings > Test - 2 changes not saved"
    assert lines[2].startswith("   1  Item 1") and lines[2].endswith("value 1") and lines[4].startswith("   3  Item 3")
    assert lines[-1] == "  s save   q leave   ? help"
    assert "q back" in menu_ui.numbered_lines(menu(2, leave="back"))[-1]
    assert menu_ui.numbered_lines(menu(1, changes=1))[0].endswith("1 change not saved")


def test_a_checklist_in_numbers_shows_marks_then_its_own_line_of_keys():
    sc = checklist(3, after=("Changes: none", menu_ui.__doc__ and "Type numbers to switch."))
    lines = menu_ui.numbered_lines(sc)
    assert "   1  [ ] Feature 1" in lines and "Type numbers to switch." in lines and "Changes: none" in lines
    assert not any(ln.strip().startswith("s apply") for ln in lines)


def test_unknown_input_is_an_error_on_standard_error_and_asks_again(capsys, monkeypatch):
    ui = _numbered(monkeypatch, "x\n9\n2")
    assert ui.choose(menu()) == ("open", 1)
    cap = capsys.readouterr()
    assert cap.err.count('Error: "') == 2 and 'Error: "x" is not a number or letter on this screen.' in cap.err
    assert 'Error: "9" is not a number or letter on this screen.' in cap.err
    assert cap.out.count("Number: ") == 3 and "Error" not in cap.out


def test_question_mark_lists_every_key_of_the_screen_and_returns_to_the_prompt(capsys, monkeypatch):
    ui = _numbered(monkeypatch, "?\nq")
    assert ui.choose(checklist(3)) == ("leave",)
    out = capsys.readouterr().out
    for word in ("h ", "w ", "b ", "s ", "q ", "?", "Ctrl-C", "several at once: 2 5 7", "Enter never applies"):
        assert word in out
    assert out.count("Number: ") == 2


def test_an_empty_answer_repeats_a_checklists_line_and_a_choice_leaves(capsys, monkeypatch):
    ui = _numbered(monkeypatch, "\nq")
    assert ui.choose(checklist(2, hint="Type numbers to switch.")) == ("leave",)
    assert capsys.readouterr().out.count("Type numbers to switch.") == 1
    assert _numbered(monkeypatch, "").choose(menu()) == ("eof",)
    assert _numbered(monkeypatch, "\n").choose(menu(empty_leaves=True)) == ("leave",)


# ---------- 8.2: the full-screen drawing ----------

@pytest.mark.parametrize("height,width", [(8, 40), (24, 80), (50, 120)])
def test_every_drawn_line_fits_inside_the_width_and_the_cursor_row_starts_with_a_marker(height, width):
    sc = checklist(30, plan="Turns on: Hub service (Label Reader: Cloud (Claude) needs it).")
    for r in sc.rows:
        r.value = "a long description that does not fit in forty columns at all, really"
    k = Keys(sc)
    k.cursor = 17
    drawn = menu_ui.layout(sc, k, height, width)
    assert all(len(text) < width for _, text, _ in drawn) and all(0 <= y < height for y, _, _ in drawn)
    cursor = [t for _, t, kind in drawn if kind == "cursor"]
    assert len(cursor) == 1 and cursor[0].startswith("> ") and "Feature 18" in cursor[0]
    foot = [(y, t) for y, t, kind in drawn if kind == "foot"]
    assert [y for y, _ in foot] == [height - 3, height - 2, height - 1]       # a checklist has three footer lines
    assert "Space on/off" in foot[-1][1] and "s apply" in foot[-1][1] and "q leave" in foot[-1][1]
    if height < 40:                                       # more rows than room: the header says which ones show
        assert "rows " in drawn[0][1] and "of 30" in drawn[0][1] or width == 40


def test_the_footers_first_line_explains_the_cursor_row_and_a_menu_has_two_footer_lines():
    sc = menu(3)
    sc.rows[1].note = "Enter to type a new value."
    k = Keys(sc)
    k.cursor = 1
    drawn = menu_ui.layout(sc, k, 24, 80)
    assert (22, "Enter to type a new value.", "foot") in drawn
    assert drawn[-1] == (23, "Enter open  s save  q leave  ? help", "foot")
    assert drawn[0][1] == "Settings > Test"
    assert menu_ui.layout(sc, k, 24, 80, status="Saved 1 change: Item 2.")[-2][1] == "Saved 1 change: Item 2."


def test_the_keys_line_leaves_a_screens_own_letters_out_when_they_do_not_fit_forty_columns():
    sc = checklist(3)
    assert menu_ui.foot_line(sc, 120).startswith("Space on/off  h Hub setup  w Weigh Station only")
    assert menu_ui.foot_line(sc, 40) == "Space on/off  s apply  q leave  ? help"


def test_headings_scroll_with_the_rows_and_are_not_selectable():
    rows = [Row("a", before=("Cloud (Claude)",)), Row("b"), Row("c", before=("On this Hub",))]
    sc = Screen("r", "Settings > Label Reader", rows)
    drawn = menu_ui.layout(sc, Keys(sc), 24, 80)
    assert [t for _, t, kind in drawn if kind == "title"] == ["  Cloud (Claude)", "  On this Hub"]
    assert [t.split() for _, t, kind in drawn if kind in ("cursor", "row")] == [[">", "1", "a"], ["2", "b"], ["3", "c"]]


# ---------- the full-screen variant on a stand-in for curses ----------

class FakeScr:
    """What CursesUi needs of a curses window; `keys` are what get_wch returns, then Ctrl-C."""

    def __init__(self, keys, size=(24, 80), ctrl_c=False):
        self.keys, self.size, self.frames, self._cur = list(keys), size, [], []
        self.ctrl_c = ctrl_c            # out of keys: Ctrl-C, or (the default) one test fails instead of the whole run

    def getmaxyx(self):
        return self.size

    def erase(self):
        self._cur = []

    def addstr(self, y, x, text, attr=0):
        self._cur.append((y, x, text, attr))

    def refresh(self):
        self.frames.append(list(self._cur))

    def keypad(self, flag):
        pass

    def get_wch(self):
        if not self.keys:
            if self.ctrl_c:
                raise KeyboardInterrupt
            pytest.fail("the full-screen fake ran out of keys")
        return self.keys.pop(0)

    def text(self, frame=-1) -> str:
        return "\n".join(t for _, _, t, _ in self.frames[frame])


class Curses:
    A_REVERSE, A_BOLD, A_DIM = 1, 2, 4
    error = type("error", (Exception,), {})
    calls: list = []

    @classmethod
    def def_prog_mode(cls):
        cls.calls.append("def_prog_mode")

    @classmethod
    def endwin(cls):
        cls.calls.append("endwin")

    @classmethod
    def reset_prog_mode(cls):
        cls.calls.append("reset_prog_mode")


def typed(text: str) -> list:
    return list(text)


def test_the_cursor_row_is_drawn_reversed_and_a_dim_row_dim():
    scr = FakeScr(["q"])
    sc = menu(3)
    sc.rows[2].dim = True
    assert menu_ui.CursesUi(scr, Curses).choose(sc) == ("leave",)
    attrs = {t.split()[2] if len(t.split()) > 2 else t: a for _, _, t, a in scr.frames[0]}
    assert [(t, a) for _, _, t, a in scr.frames[0] if t.startswith(">")][0][1] == Curses.A_REVERSE
    assert [a for _, _, t, a in scr.frames[0] if "Item 3" in t] == [Curses.A_DIM]


def test_ctrl_c_in_the_full_screen_variant_is_a_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        menu_ui.CursesUi(FakeScr([], ctrl_c=True), Curses).choose(menu())


def test_the_cursor_of_a_screen_is_kept_when_it_is_drawn_again():
    ui = menu_ui.CursesUi(FakeScr([KEY_DOWN, KEY_DOWN, 10, KEY_ENTER]), Curses)
    sc = menu(5)
    assert ui.choose(sc) == ("open", 2)
    assert ui.choose(menu(5)) == ("open", 2)


def test_a_prompt_goes_on_the_footers_first_line_and_a_secret_shows_one_star_per_character():
    scr = FakeScr(typed("Shelf Z") + [KEY_ENTER] + typed("sk-ant-XYZ") + ["\x1b"] + typed("abc") + ["\x7f", "d", "\n"])
    ui = menu_ui.CursesUi(scr, Curses)
    ui._last = (menu(), Keys(menu()))
    assert ui.ask("PLA rack [Shelf A]: ") == "Shelf Z"
    assert "PLA rack [Shelf A]: Shelf Z" in scr.text(-1).splitlines()[-2]
    assert ui.ask("Anthropic API key (Enter keeps it): ", secret=True) == ""      # Esc: an empty answer
    assert all("sk-ant" not in scr.text(i) for i in range(len(scr.frames)))
    assert ui.ask("Name: ") == "abd"                                               # Backspace works


def test_a_wrong_values_error_stays_on_the_screen_above_the_prompt_that_asks_again():
    scr = FakeScr(typed("x") + ["\n"])
    ui = menu_ui.CursesUi(scr, Curses)
    ui._last = (menu(), Keys(menu()))
    ui.error("the number of storage boxes is a whole number, 0 or more.")
    assert ui.ask("Number of storage boxes [2]: ") == "x"
    assert [t for _, _, t, _ in scr.frames[-1]].count("Error: the number of storage boxes is a whole number, 0 or more.") == 1
    assert ui.status == ""


def test_a_secret_is_starred_in_every_frame_and_never_drawn():
    scr = FakeScr(typed("sk-ant-XYZ") + ["\n"])
    ui = menu_ui.CursesUi(scr, Curses)
    ui._last = (menu(), Keys(menu()))
    assert ui.ask("Key: ", secret=True) == "sk-ant-XYZ"
    assert all("sk-ant" not in scr.text(i) for i in range(len(scr.frames)))
    assert "Key: **********" in scr.text(-1)


def test_ctrl_d_in_the_full_screen_variant_is_the_end_of_input():
    assert menu_ui.CursesUi(FakeScr(["\x04"]), Curses).choose(menu()) == ("eof",)
    ui = menu_ui.CursesUi(FakeScr(typed("ab") + ["\x04"] + ["\x04"]), Curses)
    ui._last = (menu(), Keys(menu()))
    assert ui.ask("Name: ") is None and ui.yesno("Sure?") is None


def test_config_full_screen_ctrl_d_ends_the_input_with_5_when_changes_are_staged(fullscreen, capsys):
    code, _ = fullscreen(["3", "2"] + typed("Shelf Z") + ["\n", "\x04"])
    assert code == 5 and capsys.readouterr().out.strip() == "Input ended: 1 change not saved."
    code, _ = fullscreen(["\x04"])
    assert code == 0 and capsys.readouterr().out == ""


def test_ctrl_c_while_the_terminal_is_handed_back_leaves_without_asking_to_press_enter(monkeypatch):
    Curses.calls = []
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("Ctrl-C leaves without asking"))
    with pytest.raises(KeyboardInterrupt):
        with menu_ui.CursesUi(FakeScr([]), Curses).suspended():
            raise KeyboardInterrupt
    assert Curses.calls[-1] == "reset_prog_mode"


def test_two_digits_that_are_no_row_open_nothing_and_do_not_drop_the_first():
    k = Keys(menu(11))
    assert press(k, "1") == [] and press(k, "2") == [("unknown", "12")]      # 12 is no row of 11: not item 2
    assert press(k, "2") == [("open", 1)]                                    # and nothing is left typed
    assert press(k, "1") == [] and press(k, "1") == [("open", 10)]
    assert press(Keys(menu(11)), "0") == [("unknown", "0")]


def test_suspended_hands_the_terminal_back_and_takes_it_again(monkeypatch):
    Curses.calls = []
    scr = FakeScr([])
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    with menu_ui.CursesUi(scr, Curses).suspended():
        assert Curses.calls == ["def_prog_mode", "endwin"]
    assert Curses.calls[-1] == "reset_prog_mode"


# ---------- which variant starts (8.1) ----------

def _terminal(monkeypatch, *, stdin=True, stdout=True, term="xterm"):
    monkeypatch.setenv("TERM", term)
    monkeypatch.setattr(menu_ui, "_stdin_tty", lambda: stdin)
    monkeypatch.setattr(menu_ui, "_stdout_tty", lambda: stdout)


@pytest.mark.parametrize("kw,want", [({}, True), ({"stdin": False}, False), ({"stdout": False}, False),
                                     ({"term": "dumb"}, False), ({"term": ""}, False)])
def test_full_screen_needs_two_terminals_and_a_terminal_type_that_is_not_dumb(monkeypatch, kw, want):
    _terminal(monkeypatch, **kw)
    assert menu_ui.fullscreen_wanted() is want


def test_the_installers_captured_output_may_still_draw_on_the_terminal(monkeypatch):
    _terminal(monkeypatch, stdout=False)
    assert menu_ui.fullscreen_wanted() is False and menu_ui.fullscreen_wanted(raw=True) is True


def test_numbered_switches_and_plain_win_over_a_terminal(monkeypatch):
    _terminal(monkeypatch)
    output.configure(numbered=True)
    assert menu_ui.fullscreen_wanted() is False
    output.reset()
    monkeypatch.setenv("SPOOLWARDEN_MENU", "numbered")
    assert menu_ui.fullscreen_wanted() is False
    monkeypatch.delenv("SPOOLWARDEN_MENU")
    output.configure(plain=True)
    assert output.numbered() is True and menu_ui.fullscreen_wanted() is False


def test_open_ui_gives_the_numbered_variant_without_a_terminal(monkeypatch):
    _terminal(monkeypatch, stdin=False)
    with menu_ui.open_ui(lambda p: None) as ui:
        assert isinstance(ui, menu_ui.NumberedUi)


def _fake_curses_module(size, started):
    class Win(FakeScr):
        def __init__(self):
            super().__init__([], size)

    mod = types.ModuleType("curses")
    mod.error = Curses.error
    mod.A_REVERSE, mod.A_BOLD, mod.A_DIM = 1, 2, 4
    mod.initscr = lambda: started.append("initscr") or Win()
    for name in ("noecho", "cbreak", "nocbreak", "echo", "endwin"):
        setattr(mod, name, lambda n=name: started.append(n))
    mod.curs_set = lambda n: None
    return mod


def test_a_terminal_smaller_than_40_by_8_gets_the_numbered_list_and_one_line_that_says_why(monkeypatch, capsys):
    _terminal(monkeypatch)
    started = []
    monkeypatch.setitem(sys.modules, "curses", _fake_curses_module((7, 80), started))
    with menu_ui.open_ui(lambda p: None) as ui:
        assert isinstance(ui, menu_ui.NumberedUi)
    err = " ".join(capsys.readouterr().err.split())
    assert err == "Note: this terminal is smaller than 40 x 8, so the list is numbered instead of full-screen."
    assert started[-1] == "endwin"


def test_a_terminal_of_40_by_8_gets_the_full_screen_and_it_is_put_back_on_the_way_out(monkeypatch):
    _terminal(monkeypatch)
    started = []
    monkeypatch.setitem(sys.modules, "curses", _fake_curses_module((8, 40), started))
    with pytest.raises(KeyboardInterrupt):
        with menu_ui.open_ui(lambda p: None) as ui:
            assert isinstance(ui, menu_ui.CursesUi)
            raise KeyboardInterrupt
    assert started[-1] == "endwin" and "cbreak" in started and os.environ.get("ESCDELAY") is None


def test_curses_that_cannot_start_falls_back_to_the_numbered_list(monkeypatch):
    _terminal(monkeypatch)
    mod = _fake_curses_module((24, 80), [])
    mod.initscr = lambda: (_ for _ in ()).throw(Curses.error("no terminal"))
    monkeypatch.setitem(sys.modules, "curses", mod)
    with menu_ui.open_ui(lambda p: None) as ui:
        assert isinstance(ui, menu_ui.NumberedUi)


def test_other_errors_in_the_screen_code_are_not_hidden(monkeypatch):
    _terminal(monkeypatch)
    mod = _fake_curses_module((24, 80), [])
    mod.initscr = lambda: (_ for _ in ()).throw(ZeroDivisionError("a bug"))
    monkeypatch.setitem(sys.modules, "curses", mod)
    with pytest.raises(ZeroDivisionError):
        with menu_ui.open_ui(lambda p: None):
            pass


# ---------- `config` full-screen, on the stand-in ----------

@pytest.fixture
def fullscreen(monkeypatch):
    """`run(keys)`: cli.main(["config"]) with the full-screen variant on a stand-in window; (code, window)."""
    monkeypatch.setattr(menu_ui, "_stdin_tty", lambda: True)

    def run(keys, *args, ctrl_c=False):
        scr = FakeScr(keys, ctrl_c=ctrl_c)
        ui = menu_ui.CursesUi(scr, Curses)

        @contextlib.contextmanager
        def open_ui(ask, secret=None, *, raw=False):
            yield ui
        monkeypatch.setattr(menu_ui, "open_ui", open_ui)
        return cli.main(["config", *args]), scr
    return run


def test_config_full_screen_changes_a_value_by_number_saves_with_s_and_leaves_with_q(fullscreen):
    # 3 Storage locations; 2 PLA rack: the prompt is on the footer; Enter; s saves; q back; q leave
    code, scr = fullscreen(["3", "2"] + typed("Shelf Z") + ["\n", "s", "q", "q"])
    assert code == 0 and config.load()["placement"]["pla_location"] == "Shelf Z"
    shown = "\n".join(scr.text(i) for i in range(len(scr.frames)))
    assert "PLA rack [Rack 1]: Shelf Z" in shown and "Saved 1 change: PLA rack." in shown
    assert "Settings > Storage locations" in shown and "1 change not saved" in shown


def test_config_full_screen_opens_a_row_with_enter_after_moving_the_cursor(fullscreen):
    code, scr = fullscreen([KEY_DOWN, 10, "1"] + typed("my-kit") + ["\n", "s", "q", "q"])
    assert code == 0 and config.load()["server_name"] == "my-kit"           # row 2 = General, its first item the name


def test_config_full_screen_q_with_changes_asks_and_yes_ends_with_5_and_nothing_saved(fullscreen, capsys):
    before = config.load()["placement"]["pla_location"]
    code, scr = fullscreen(["3", "2"] + typed("Shelf Z") + ["\n", "q", "q"] + typed("y") + ["\n"])
    assert code == 5 and config.load()["placement"]["pla_location"] == before
    assert "Leave without saving 1 change (PLA rack)? [y/N] y" in scr.text(-1)
    assert capsys.readouterr().out.strip() == "Nothing saved."


def test_config_full_screen_ctrl_c_leaves_at_once_saying_what_was_not_saved(fullscreen, capsys):
    code, scr = fullscreen(["3", "2"] + typed("Shelf Z") + ["\n"], ctrl_c=True)          # then the window raises Ctrl-C
    assert code == 130 and capsys.readouterr().out.strip() == "Left without saving 1 change."
    code, _ = fullscreen([], ctrl_c=True)
    assert code == 130 and capsys.readouterr().out == ""                    # nothing staged: it just ends


def test_config_full_screen_secret_is_starred_and_never_drawn(fullscreen, capsys, monkeypatch):
    code, scr = fullscreen(["4", "2"] + typed("sk-ant-TOPSECRET") + ["\n", "s", "q", "q"])
    shown = "\n".join(scr.text(i) for i in range(len(scr.frames)))
    assert "sk-ant" not in shown and "Anthropic API key (Enter keeps it): ****************" in shown
    assert code == 0 and (config.paths().etc / "anthropic_key").read_text().strip() == "sk-ant-TOPSECRET"
    cap = capsys.readouterr()
    assert "sk-ant" not in cap.out + cap.err


# ---------- the real screen, in a pty ----------

def _curses_ok():
    try:
        import curses  # noqa: F401
        return hasattr(os, "fork")
    except ImportError:
        return False


def _read_until(fd, needle: bytes, timeout=15.0) -> bytes:
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            if needle in buf:
                return buf
    return buf


def _run_in_pty(tmp_path, keys: list[bytes]):
    """`spoolwarden modules menu --raw` with the pty as its terminal and stdout on a pipe (as install.sh runs it):
    the screen must be drawn on /dev/tty. Returns (exit code, stdout, screen bytes)."""
    import pty
    env = dict(os.environ, TERM="xterm", FK_ETC=str(tmp_path / "etc"), FK_STATE=str(tmp_path / "state"),
               FK_BACKUPS=str(tmp_path / "bk"), FK_OPT=str(tmp_path / "opt"), FK_NO_SYSTEMD="1",
               LINES="30", COLUMNS="120")
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "state").mkdir(exist_ok=True)
    rd, wr = os.pipe()
    pid, master = pty.fork()
    if pid == 0:                                    # child: stdout to the pipe, stdin/tty the pty
        try:
            os.close(rd)
            os.dup2(wr, 1)
            os.execve(sys.executable, [sys.executable, "-c", "import sys; from filament_kit import cli; "
                                       "sys.exit(cli.main(['modules', 'menu', '--raw']))"], env)
        finally:
            os._exit(127)                           # exec failed: never fall back into the parent's pytest run
    os.close(wr)
    status = None
    try:
        screen = _read_until(master, b"? help")
        for k in keys:
            os.write(master, k)
            time.sleep(0.15)
            screen += _read_until(master, b"\xff", timeout=0.3)
        deadline = time.time() + 15
        out = b""
        while time.time() < deadline:
            r, _, _ = select.select([rd, master], [], [], 0.2)
            if rd in r:
                chunk = os.read(rd, 65536)
                if not chunk:
                    break
                out += chunk
            if master in r:
                try:
                    screen += os.read(master, 65536)
                except OSError:
                    pass
        # the child may be stuck (a lost key): give it a moment, then kill it, so the run never hangs here
        end = time.time() + 5
        while status is None:
            done, st = os.waitpid(pid, os.WNOHANG)
            if done:
                status = st
            elif time.time() >= end:
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
                pytest.fail("the menu did not exit in time; screen: " + repr(screen[-2000:]))
            else:
                time.sleep(0.05)
    finally:
        if status is None:                          # an error above: the forked child must not outlive the test
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass
        os.close(rd)
        os.close(master)
    return os.waitstatus_to_exitcode(status), out.decode(), screen


@pytest.mark.skipif(sys.platform == "win32" or not _curses_ok(), reason="needs a pty and curses (Linux)")
def test_real_curses_menu_in_a_pty(tmp_path):
    down = b"\x1bOB"                                # xterm's Down key in keypad mode
    names = list(modules.MODULES)                   # the keys walk the registry: down to library, then j on to updates
    to_library = names.index("library")
    to_updates = names.index("updates") - to_library
    code, out, screen = _run_in_pty(tmp_path, [down] * to_library + [b" "] + [b"j"] * to_updates + [b" ", b"s", b"\r"])   # s hands the terminal back to show the plan; Enter ends it
    assert b"[x] Spoolman" in screen and b"? help" in screen
    assert code == 0, screen[-2000:]
    assert out.splitlines() == ["spoolman,server,printers,presets,library,backup,updates"]


@pytest.mark.skipif(sys.platform == "win32" or not _curses_ok(), reason="needs a pty and curses (Linux)")
def test_real_curses_menu_leaving_with_switched_rows_asks_and_exits_5_in_a_pty(tmp_path):
    code, out, screen = _run_in_pty(tmp_path, [b" ", b"q", b"y", b"\r"])
    assert code == 5 and out == "" and b"Leave without applying 1 change" in screen


@pytest.mark.skipif(sys.platform == "win32" or not _curses_ok(), reason="needs a pty and curses (Linux)")
def test_real_curses_menu_q_without_changes_exits_1_in_a_pty(tmp_path):
    code, out, _ = _run_in_pty(tmp_path, [b"q"])
    assert code == 1 and out == ""


@pytest.mark.skipif(sys.platform == "win32" or not _curses_ok(), reason="needs a pty and curses (Linux)")
def test_real_curses_menu_ctrl_c_restores_the_terminal(tmp_path):
    code, out, screen = _run_in_pty(tmp_path, [b"\x03"])
    assert code == 130 and out == ""
    assert b"\x1b[?1049l" in screen or b"\x1b[?1049l" in screen.replace(b"\x1b[?1049l", b"\x1b[?1049l")


def test_below_60_columns_each_row_is_a_block_and_an_empty_list_says_why(monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    lines = menu_ui.numbered_lines(menu(2))
    assert lines[2:6] == ["   1  Item 1", "      value 1", "   2  Item 2", "      value 2"]
    assert all(len(ln) < 40 for ln in lines)
    empty = Screen("e", "Printers", [], actions=(("a", "add a printer"),), empty="No printers yet.")
    out = menu_ui.numbered_lines(empty)
    assert out[:3] == ["Printers", "", "  No printers yet."] and out[-1].strip().startswith("a add a printer")
    assert [ln for ln in out].count("") == 2


def test_a_full_screen_fake_out_of_keys_fails_one_test_and_does_not_abort_the_run():
    with pytest.raises(pytest.fail.Exception, match="ran out of keys"):
        FakeScr([]).get_wch()
