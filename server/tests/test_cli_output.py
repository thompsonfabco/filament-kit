"""S5.1: how the command line writes (06 6.1 to 6.7, 07 CLI-1 to CLI-10). The first block is AUT-9 for `status` and a
failing command, run with COLUMNS=80: no line over 79 characters, no escape byte without colour, ASCII and no CR in
`--plain`, a failing command with an empty standard output and an error that starts "Error: ". The rest holds the
pieces: the glyph set, colour, tables, wrapping, the progress line and the exit codes."""
from __future__ import annotations

import io
import re
import time

import pytest

from filament_kit import cli, config, modules

DEAD = "http://192.0.2.77:9"
ESC, CR = "\x1b", "\r"


@pytest.fixture
def cfg(monkeypatch):
    """A server with one failing row of each kind of fix, long rows, and a certificate: example data only."""
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    c = config.load()
    c["server_name"] = "Workshop hub"
    c["spoolman_url"] = DEAD
    c["modules"] = {n: n in {"server", "library", "ai_intake"} for n in modules.MODULES}
    config.save(c)

    def down(self):
        raise cli.SpoolmanError("no answer from the Spoolman at that address, so nothing could be read from it")
    monkeypatch.setattr(cli.Spoolman, "ping", down)
    monkeypatch.setattr(cli.library, "status", lambda: {"source": "bundled", "version": 7, "local": 1,
                                                        "last_check": None})
    monkeypatch.setattr(cli.pairing, "fingerprint", lambda pem: "ab12" * 16)
    (config.paths().etc / "cert.pem").write_text("x", encoding="utf-8")
    return c


def run(capsys, *args, **kw):
    try:
        rc = cli.main(list(args), client_factory=lambda k: None, **kw)
    except SystemExit as e:             # argparse's way out of a wrong command or option
        rc = e.code
    got = capsys.readouterr()
    return rc, got.out, got.err


def lines_of(text: str) -> list[str]:
    return text.split("\n")


def check_width(*texts):
    """No line over 79 columns, but one word that is longer than that (the test machine's long temporary path) stays
    whole on its own line: a path or address cut in two cannot be used (06 6.3)."""
    for text in texts:
        for line in lines_of(text):
            assert len(line) <= 79 or " " not in line.strip(), line


# ---------- AUT-9: status ----------

def test_status_has_no_line_over_79_columns(cfg, capsys):
    rc, out, err = run(capsys, "status")
    assert rc == 1
    assert max(len(line) for line in lines_of(out)) > 60        # the long rows are really in it
    check_width(out, err)
    assert err == ""


def test_status_is_grouped_as_the_overview_with_a_header_and_a_summary(cfg, capsys):
    rc, out, _ = run(capsys, "status")
    lines = lines_of(out)
    assert re.fullmatch(r"filament-kit \S+ - Workshop hub - \S+", lines[0])
    assert lines[1] == ""
    headings = [x for x in lines if x and not x.startswith(" ") and x != lines[0]]
    assert headings[:-1] == ["Hub", "Spoolman", "Label Reader", "Devices", "Filament Catalog"]
    assert re.fullmatch(r"\d+ needs? a look - \d+ OK - \d+ notes?", headings[-1])
    assert headings[-1] == "2 need a look - 1 OK - 5 notes"
    assert lines[-3:] == ["", headings[-1], ""]


def test_a_row_is_glyph_word_text_and_a_fix_line_is_under_the_text(cfg, capsys):
    rc, out, _ = run(capsys, "status")
    lines = lines_of(out)
    row = next(i for i, x in enumerate(lines) if "Spoolman not reachable" in x)
    assert lines[row].startswith("  ! needs a look  Spoolman not reachable at " + DEAD)
    cont = row + 1
    while lines[cont].startswith(" " * 18) and "Fix:" not in lines[cont]:
        cont += 1                       # the wrapped rest of the text lines up with the text
    fix = lines[cont:cont + 2]          # the Fix line lines up with the text too, and wraps under its own words
    assert fix == [" " * 18 + "Fix: check that the remote Spoolman is running and", " " * 23 + "spoolman_url is right"]
    assert any(x.startswith("  + OK            certificate present, fingerprint ab12 ab12 ab12") for x in lines)
    assert any(x.startswith("  * note          display name: Workshop hub") for x in lines)


@pytest.mark.parametrize("how", ["no_color", "color_never", "piped"])
def test_no_escape_byte_without_colour(cfg, capsys, monkeypatch, how):
    args = ["status"]
    if how == "no_color":
        monkeypatch.setenv("NO_COLOR", "1")
    elif how == "color_never":
        args = ["--color", "never", "status"]
    rc, out, err = run(capsys, *args)
    assert ESC not in out + err


def test_colour_paints_the_glyph_and_word_and_resets_each_line(cfg, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")                      # --color always comes first (06 6.2 rule 1)
    rc, out, _ = run(capsys, "status", "--color", "always")
    assert f"{ESC}[33m! needs a look{ESC}[0m" in out
    assert f"{ESC}[32m+ OK{ESC}[0m" in out
    assert f"{ESC}[1mHub{ESC}[0m" in out
    for line in lines_of(out):
        assert line.count(f"{ESC}[") == 2 * line.count(f"{ESC}[0m")      # every span is closed on its line


def test_colour_follows_a_terminal_unless_told_otherwise(cfg, capsys, monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr("sys.stdout", Tty())
    monkeypatch.setattr("sys.stderr", Tty())
    cli.main(["status"], client_factory=lambda k: None)
    import sys
    assert ESC in sys.stdout.getvalue()
    monkeypatch.setenv("TERM", "dumb")                       # a dumb terminal: no colour, and plain mode
    sys.stdout = Tty()
    cli.main(["status"], client_factory=lambda k: None)
    assert ESC not in sys.stdout.getvalue()


@pytest.mark.parametrize("how", ["flag", "env", "dumb"])
def test_plain_is_ascii_without_glyphs_escapes_or_carriage_returns(cfg, capsys, monkeypatch, how):
    args = ["status"]
    if how == "flag":
        args = ["--plain", "status"]
    elif how == "env":
        monkeypatch.setenv("SPOOLWARDEN_PLAIN", "1")
    else:
        monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")      # plain wins: ASCII all the same
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    rc, out, err = run(capsys, *args)
    assert ESC not in out + err and CR not in out + err
    assert out.isascii() and err.isascii()
    check_width(out, err)
    lines = lines_of(out)
    assert any(x.startswith("needs a look  Spoolman not reachable") for x in lines)
    assert any(x.startswith("OK  certificate present") for x in lines)
    assert not any(re.match(r"\s*[+!*o]\s", x) for x in lines)          # no glyph, only the word (CLI-2)


def test_the_glyph_set_follows_the_locale_and_the_override(cfg, capsys, monkeypatch):
    monkeypatch.delenv("SPOOLWARDEN_GLYPHS")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    out = run(capsys, "status")[1]
    assert "  ▲ needs a look  Spoolman" in out and "  ● OK  " in out and "  ◆ note  " in out
    assert " · " in out                                               # the summary's separator
    monkeypatch.setenv("LC_ALL", "C")                                 # LC_ALL first: not UTF-8
    out = run(capsys, "status")[1]
    assert "  ! needs a look" in out and " - " in out and "●" not in out
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")               # the override wins over the locale
    assert "  ● OK" in run(capsys, "status")[1]


def test_status_exit_code_is_0_when_nothing_needs_a_look(cfg, capsys, monkeypatch):
    monkeypatch.setattr(cli.Spoolman, "ping", lambda self: "1.2.3")
    cfg["modules"]["ai_intake"] = False
    config.save(cfg)
    rc, out, _ = run(capsys, "status")
    assert rc == 0 and "needs a look" not in out
    assert re.fullmatch(r"\d+ OK - \d+ notes?", lines_of(out)[-2])


# ---------- AUT-9: a failing command ----------

FAILING = [("unpair", "nobody"), ("no-such-command",), ("printer", "map")]


@pytest.mark.parametrize("args", FAILING)
@pytest.mark.parametrize("how", ["plain", "no_color", "piped", "color_never"])
def test_a_failing_command_writes_only_standard_error_and_starts_error(cfg, capsys, monkeypatch, args, how):
    if how == "plain":
        args = ("--plain", *args)
    elif how == "no_color":
        monkeypatch.setenv("NO_COLOR", "1")
    elif how == "color_never":
        args = ("--color", "never", *args)
    rc, out, err = run(capsys, *args)
    assert out == ""
    assert err.startswith("Error: ")
    assert ESC not in err and CR not in err
    check_width(err)
    assert rc == 2


def test_exit_codes_of_06_6_7(cfg, capsys, monkeypatch):
    assert run(capsys, "unpair", "nobody")[0] == 2                        # no such device
    assert run(capsys, "--color", "sometimes", "status")[0] == 2          # a bad value
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    rc, out, err = run(capsys, "backup", "create")
    assert (rc, out) == (3, "")                                           # needs sudo
    assert err == ("Error: this needs administrator rights.\n"
                   "Fix: run it with sudo:\n"
                   "     sudo filament-kit backup create\n")
    monkeypatch.setattr(cli, "_server_api", lambda: None)
    p = type("P", (), dict(configured=True, family="bambu"))()
    monkeypatch.setattr(cli.registry, "load", lambda: {"S1": p})
    rc, out, err = run(capsys, "printer", "map", "S1", "--manual")
    assert (rc, out) == (4, "")                                           # the Hub is not running
    assert "Fix: sudo systemctl start filament-kit" in err


def test_ctrl_c_ends_with_stopped_and_130(cfg, capsys, monkeypatch):
    def stop(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "cmd_cert", stop)
    assert run(capsys, "cert") == (130, "Stopped.\n", "")


def test_a_permission_error_is_one_error_with_the_command_to_run_with_sudo(cfg, capsys, monkeypatch):
    def denied(*a, **k):
        raise PermissionError(13, "denied", "/etc/filament-kit/config.json")
    monkeypatch.setattr(cli, "cmd_cert", denied)
    rc, out, err = run(capsys, "cert")
    assert (rc, out) == (3, "")
    assert err.splitlines()[0] == "Error: /etc/filament-kit/config.json: permission denied."
    assert err.splitlines()[-1] == "     sudo filament-kit cert"


def test_notes_go_to_standard_error_with_the_word_note(cfg, capsys):
    from filament_kit import output
    output.note("the old name still works.")
    got = capsys.readouterr()
    assert (got.out, got.err) == ("", "Note: the old name still works.\n")


# ---------- the pieces ----------

def test_error_with_a_fix_and_a_command(capsys):
    from filament_kit import output
    output.error("Study A1 mini did not answer at 192.0.2.41:8883.",
                 "check that it is switched on and on the network, then test it:",
                 cmd='sudo spoolwarden printer test "Study A1 mini"')
    assert capsys.readouterr().err == (
        "Error: Study A1 mini did not answer at 192.0.2.41:8883.\n"
        "Fix: check that it is switched on and on the network, then test it:\n"
        '     sudo spoolwarden printer test "Study A1 mini"\n')


def test_error_splits_a_fix_line_the_code_wrote_into_its_text(capsys):
    from filament_kit import output
    output.error("pc needs spoolman\nfix: enable spoolman first")
    assert capsys.readouterr().err == "Error: pc needs spoolman\nFix: enable spoolman first\n"


def test_a_long_error_wraps_at_spaces_and_lines_up(capsys):
    from filament_kit import output
    output.error("word " * 30 + "end", "word " * 30 + "end")
    err = capsys.readouterr().err
    check_width(err)
    first, *rest = err.splitlines()
    assert first.startswith("Error: word") and rest[0].startswith("       word")
    assert any(x.startswith("Fix: word") for x in rest) and rest[-1].startswith("     ")


def test_wrap_never_cuts_a_word_and_keeps_one_too_long_whole_on_its_own_line(monkeypatch):
    from filament_kit import output
    assert output.wrap("a " * 50, indent=4, first=0)[1].startswith("    a")
    address = "https://192.0.2.10:8710/some/long/path"
    got = output.wrap("Answering at " + address, indent=18, first=0)
    assert all(len(x) <= 79 for x in got)
    assert address in " ".join(x.strip() for x in got)
    assert output.wrap("x" * 200, indent=2) == ["  " + "x" * 200]
    path = "/var/lib/filament-kit/releases/0.5.2/some/deeper/folder/than/a/line/holds/uninstall.sh"
    assert output.wrap("cannot read " + path + " now", indent=7, first=0) == ["cannot read", "       " + path,
                                                                            "       now"]


def test_wrap_breaks_only_at_spaces_outside_backtick_spans():
    from filament_kit import output
    text = ("this host has no pairing yet, and the next step cannot go on until it has one: run `sudo filament-kit "
            "station pair` here, then run `sudo filament-kit status` again")
    got = output.wrap(text, indent=5, first=0)
    assert len(got) > 1 and all(len(x) <= 79 for x in got)
    for line in got:
        assert line.count("`") % 2 == 0, line               # no command is split over two lines
    assert "`sudo filament-kit station pair`" in " ".join(got) and any("`sudo filament-kit status`" in x for x in got)
    long_span = "run `" + "sudo filament-kit " * 6 + "end` now"
    assert [x.strip() for x in output.wrap(long_span, indent=2)] == ["run", long_span[4:-4], "now"]


def test_the_no_terminal_error_of_station_pair_keeps_its_command_whole(capsys):
    from filament_kit import output
    output.error("`sudo filament-kit station pair` needs a terminal: it asks for the link and for you to compare the "
                 "fingerprint. Nothing was saved.")
    err = capsys.readouterr().err
    check_width(err)
    assert all(x.count("`") % 2 == 0 for x in err.splitlines())
    assert "`sudo filament-kit station pair`" in err


def test_the_local_pair_error_keeps_both_its_commands_whole(capsys):
    from filament_kit import output
    output.error("--local pairs a station with the kit server on the same machine, and the server module is off "
                 "here.\nfix: run `sudo filament-kit pair --station` on the kit server, then `sudo filament-kit station "
                 "pair` here")              # the text of cli.py cmd_station_pair_local: its spans are mid-text
    err = capsys.readouterr().err
    check_width(err)
    assert all(x.count("`") % 2 == 0 for x in err.splitlines())
    assert "`sudo filament-kit pair --station`" in err and "`sudo filament-kit station pair`" in err


def test_long_state_word_pushes_its_own_row_only(monkeypatch):
    from filament_kit import output
    rows = output.status_row("certificate changed", "Study A1 mini", "run it again") + \
        output.status_row("OK", "next")
    assert rows == ["  ! certificate changed  Study A1 mini",
                    " " * 18 + "Fix: run it again",
                    "  + OK            next"]


def test_a_detail_line_is_aligned_with_the_text_and_fix_has_its_own_word(cfg, capsys, monkeypatch):
    from filament_kit import status
    status.print_rows([status.Row("fail", "Scale not seen", group="Weigh Station"),
                       status.Row("detail", "fix: check the scale's USB cable", group="Weigh Station")])
    assert capsys.readouterr().out == ("Weigh Station\n"
                                       "  ! needs a look  Scale not seen\n"
                                       "                  Fix: check the scale's USB cable\n")


def test_table_at_a_terminal_cuts_the_long_column_and_right_aligns_numbers(monkeypatch):
    from filament_kit import output

    class Tty(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setenv("COLUMNS", "64")
    monkeypatch.setenv("NO_COLOR", "1")
    rows = [["2026-11-12 14:05", "manual", "4,812 KiB", "filament-kit-backup-2026-11-12-1405.zip"],
            ["2026-11-11 03:00", "daily", "62 KiB", "short.zip"]]
    got = output.table(["When", "Kind", "Size", "Name"], rows, long=3, right=(2,), stream=Tty())
    assert got[0].split() == ["WHEN", "KIND", "SIZE", "NAME"]
    assert all(len(x) <= 63 for x in got)
    assert got[1].endswith("...") and got[2].endswith("short.zip")
    assert "4,812 KiB" in got[1] and "   62 KiB" in got[2]


def test_table_not_at_a_terminal_cuts_nothing_and_never_turns_into_blocks(monkeypatch):
    from filament_kit import output
    monkeypatch.setenv("COLUMNS", "30")
    rows = [["a", "x" * 70]]
    got = output.table(["Name", "Path"], rows, long=1, stream=io.StringIO())
    assert got == ["NAME  PATH", "a     " + "x" * 70]


def test_table_is_blocks_in_plain_mode_and_below_60_columns(monkeypatch):
    from filament_kit import output

    class Tty(io.StringIO):
        def isatty(self):
            return True
    rows = [["a", "1"], ["b", "2"]]
    expected = ["Name: a", "Size: 1", "", "Name: b", "Size: 2"]
    output.configure(plain=True)
    assert output.table(["Name", "Size"], rows) == expected
    output.reset()
    monkeypatch.setenv("COLUMNS", "59")
    assert output.table(["Name", "Size"], rows, stream=Tty()) == expected


def test_unpair_list_and_backup_list_are_tables(cfg, capsys, monkeypatch):
    monkeypatch.setattr(cli.pairing, "devices", lambda: [
        {"id": "d1", "name": "Bench phone", "paired": 1790000000, "last_seen": None}])
    rc, out, _ = run(capsys, "unpair")
    lines = lines_of(out)
    assert rc == 0 and lines[0].split() == ["ID", "NAME", "PAIRED", "LAST", "SEEN"]
    assert lines[1].startswith("d1  Bench phone  ") and lines[1].endswith("never")
    monkeypatch.setattr(cli.pairing, "devices", lambda: [])
    assert run(capsys, "unpair")[1] == "No paired devices.\n"


def test_switches_are_taken_out_of_any_place_before_a_bare_dash_dash():
    from filament_kit import output
    assert output.extract_switches(["--plain", "status", "--color", "never", "--no-progress"]) == (
        ["status"], {"plain": True, "color": "never", "no_progress": True})
    assert output.extract_switches(["x", "--color=always", "--", "--plain"]) == (
        ["x", "--", "--plain"], {"color": "always"})


def test_plain_mode_asks_for_the_numbered_menu_not_the_full_screen_one(monkeypatch):
    from filament_kit import menu_ui, output
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(menu_ui, "_stdin_tty", lambda: True)
    assert menu_ui._usable() is True
    output.configure(plain=True)
    assert menu_ui._usable() is False


# ---------- waits (06 6.6) ----------

class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def quick(monkeypatch):
    from filament_kit import output
    monkeypatch.setattr(output, "PROGRESS_AFTER", 0.15)
    return output


def test_a_short_wait_shows_nothing(quick, capsys):
    with quick.wait("Checking…"):
        pass
    got = capsys.readouterr()
    assert (got.out, got.err) == ("", "")


def test_a_long_wait_prints_one_line_once_on_standard_error_when_not_a_terminal(quick, capsys):
    with quick.wait("Testing Workshop X1…"):
        time.sleep(0.6)
    got = capsys.readouterr()
    assert got.out == "" and got.err == "~ Testing Workshop X1...\n"      # no counter, ASCII glyph and dots


def test_no_progress_is_the_same_whole_line_even_at_a_terminal(quick, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("sys.stderr", Tty())
    quick.configure(no_progress=True)
    with quick.wait("Backing up…"):
        time.sleep(0.6)
    import sys
    assert sys.stderr.getvalue() == "~ Backing up...\n"


def test_at_a_terminal_the_line_is_rewritten_with_the_seconds_and_taken_off_at_the_end(quick, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("sys.stderr", Tty())
    monkeypatch.setattr(quick, "STOP_HINT_AFTER", 1)
    t = quick.wait("Updating…")
    with t:
        time.sleep(2.0)
    import sys
    text = sys.stderr.getvalue()
    assert text.startswith("\r~ Updating... 0 s") or text.startswith("\r~ Updating... 1 s")
    assert "(Ctrl-C stops)" in text
    assert text.endswith("\r")                                      # blanked, so the result line starts clean


def test_other_output_takes_the_line_off_and_starts_the_two_seconds_again(quick, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("sys.stderr", Tty())
    with quick.wait("Updating…"):
        time.sleep(0.5)
        quick.note("a line from the step")
    import sys
    text = sys.stderr.getvalue()
    assert text.index("Note: a line from the step\n") > text.index("\r" + " " * 10)


def test_plain_has_no_glyph_no_rewrite_and_a_line_every_ten_seconds(quick, capsys, monkeypatch):
    monkeypatch.setattr(quick, "PLAIN_EVERY", 0.4)
    quick.configure(plain=True)
    with quick.wait("Connecting to Workshop X1 at 192.0.2.40…"):
        time.sleep(1.1)
    err = capsys.readouterr().err
    first, *more = err.splitlines()
    assert first == "Connecting to Workshop X1 at 192.0.2.40..."
    assert more and all(re.fullmatch(r"Connecting to Workshop X1 at 192\.0\.2\.40\.\.\. \d+ s", x) for x in more)
    assert CR not in err and ESC not in err


def test_steps_say_step_k_of_n(quick, capsys):
    with quick.wait("Mapping the slots of Workshop X1…", steps=(2, 4)):
        time.sleep(0.5)
    assert capsys.readouterr().err == "~ Mapping the slots of Workshop X1... step 2 of 4\n"


def test_status_shows_the_checking_line_on_standard_error_only(cfg, capsys, monkeypatch):
    from filament_kit import output
    monkeypatch.setattr(output, "PROGRESS_AFTER", 0.1)

    def slow(self):
        time.sleep(0.5)
        return "1.2.3"
    monkeypatch.setattr(cli.Spoolman, "ping", slow)
    rc, out, err = run(capsys, "status")
    assert err == "~ Checking...\n" and "Checking" not in out


# ---------- a wait never draws over what is written, or over a question ----------

def screen(text: str) -> list[str]:
    """What a terminal shows after `text`: a carriage return goes back to the start of the row, later text overwrites."""
    rows: list[str] = []
    cur: list[str] = []
    col = 0
    for ch in text:
        if ch == "\n":
            rows.append("".join(cur).rstrip())
            cur, col = [], 0
        elif ch == "\r":
            col = 0
        else:
            if col < len(cur):
                cur[col] = ch
            else:
                cur.append(ch)
            col += 1
    if cur:
        rows.append("".join(cur).rstrip())
    return rows


@pytest.fixture
def terminal(monkeypatch):
    """Called in the test (the capture of the run puts its own streams back before it): standard output and error
    become one terminal, with no colour so the text can be compared."""
    def use() -> Tty:
        monkeypatch.setenv("NO_COLOR", "1")
        t = Tty()
        monkeypatch.setattr("sys.stdout", t)
        monkeypatch.setattr("sys.stderr", t)
        return t
    return use


def test_a_plain_print_during_a_wait_starts_on_its_own_line(quick, terminal):
    terminal = terminal()
    with quick.wait("Updating…"):
        time.sleep(0.5)
        print("==> step 3 of 3 done", flush=True)
        time.sleep(0.05)
    assert "~ Updating... 0 s" in terminal.getvalue()          # the line was up before the print
    assert screen(terminal.getvalue()) == ["==> step 3 of 3 done"]


def test_a_print_restarts_the_two_seconds(quick, terminal):
    terminal = terminal()
    with quick.wait("Updating…"):
        for _ in range(6):                  # six prints 0.05 s apart: never 0.15 s of quiet
            time.sleep(0.05)
            print("tick", flush=True)
    assert "Updating" not in terminal.getvalue()


def test_the_line_is_not_drawn_after_text_that_has_not_ended_its_line(quick, terminal):
    terminal = terminal()
    with quick.wait("Updating…"):
        print("half a line", end="", flush=True)
        time.sleep(0.5)
    assert "Updating" not in terminal.getvalue()


def test_the_streams_are_the_same_objects_again_after_the_wait(quick, terminal):
    terminal = terminal()
    import sys
    with quick.wait("Updating…"):
        assert sys.stdout is not terminal and sys.stderr is not terminal
    assert sys.stdout is terminal and sys.stderr is terminal


def test_restore_asks_before_its_wait_starts_and_its_lines_start_clean(quick, terminal, monkeypatch, tmp_path):
    terminal = terminal()
    import sys
    from filament_kit import backup
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    zip_path = tmp_path / "b.zip"
    zip_path.write_bytes(b"x")
    seen: list[str] = []

    def answer(prompt):                     # the real input() writes its prompt below Python's streams
        terminal.write(prompt)
        time.sleep(0.6)
        seen.append(terminal.getvalue())
        terminal.write("restore\n")
        return "restore"

    def fake_restore(path, *, yes, ask, step):
        print("Backup of Workshop made today.")
        assert ask("Type restore to go on: ") == "restore"
        time.sleep(0.4)
        print("==> step 3 of 3 Putting the backup in place", flush=True)
        return 0
    monkeypatch.setattr(backup, "restore", fake_restore)
    monkeypatch.setattr("builtins.input", answer)
    assert cli.cmd_restore(str(zip_path)) == 0
    assert seen[0].endswith("Type restore to go on: ") and "Restoring" not in seen[0]
    assert "Restoring" in terminal.getvalue()              # the wait did start, after the answer
    assert "\r" not in terminal.getvalue()                 # restore runs programs: a whole line, never in place
    assert screen(terminal.getvalue())[:4] == ["Backup of Workshop made today.", "Type restore to go on: restore",
                                              "~ Restoring...", "==> step 3 of 3 Putting the backup in place"]


def test_the_line_at_a_terminal_is_cut_to_the_width_and_keeps_its_counter(quick, terminal, monkeypatch):
    terminal = terminal()
    monkeypatch.setenv("COLUMNS", "30")
    with quick.wait("Mapping the slots of Workshop X1 in the back room…"):
        time.sleep(0.5)
    frames = terminal.getvalue().split("\r")
    assert max(len(f) for f in frames) <= 29
    assert any(f.rstrip().endswith("... 0 s") for f in frames)


def test_colour_needs_a_terminal_and_a_terminal_type_that_can_show_it(monkeypatch):
    from filament_kit import output
    monkeypatch.delenv("TERM")
    assert output.colour_on(Tty()) is False                 # TERM unset: no colour even at a terminal
    monkeypatch.setenv("TERM", "dumb")
    assert output.colour_on(Tty()) is False
    monkeypatch.setenv("TERM", "xterm-256color")
    assert output.colour_on(Tty()) is True
    assert output.colour_on(io.StringIO()) is False         # not a terminal
    monkeypatch.setenv("NO_COLOR", "1")
    assert output.colour_on(Tty()) is False
    assert output.colour_on(Tty()) is False


def test_old_rows_gives_back_the_old_lines_and_refuses_one_it_does_not_know():
    from conftest import old_rows
    shown = ("filament-kit 0.5.2 - Workshop hub - 2026-11-14\n\nHub\n  + OK            service active\n"
             "  ! needs a look  Spoolman not reachable\n                  Fix: start it\n  * note          a note\n\n"
             "1 needs a look - 1 OK - 1 note\n")
    assert old_rows(shown) == ["OK   service active", "FAIL Spoolman not reachable", "     fix: start it", "--   a note"]
    for stray in ("an unexpected line\n", "  o off           a row with a word old_rows has no old line for\n",
                  "Not a group\n"):
        with pytest.raises(AssertionError):
            old_rows(shown + stray)


class FileTty(io.TextIOWrapper):
    """A terminal that is a real file, so a child process can write to it too."""
    def __init__(self, path):
        super().__init__(open(path, "ab", buffering=0), encoding="utf-8", write_through=True)

    def isatty(self):
        return True


def _child_line(delay: float) -> list[str]:
    import sys
    return [sys.executable, "-I", "-c", f"import time; time.sleep({delay}); print('child output', flush=True)"]


def _run_wait_with_child(quick, monkeypatch, tmp_path, **kw):
    import subprocess
    monkeypatch.setenv("NO_COLOR", "1")
    path = tmp_path / "tty.txt"
    term = FileTty(path)
    monkeypatch.setattr("sys.stdout", term)
    monkeypatch.setattr("sys.stderr", term)
    with quick.wait("Applying…", **kw):
        subprocess.run(_child_line(0.6), stdout=term.fileno(), check=True)
    term.flush()
    return path.read_bytes().decode().replace("\r\n", "\n")      # Windows ends a printed line with CR LF


def test_a_wait_that_runs_programs_never_draws_over_a_child_s_output(quick, monkeypatch, tmp_path):
    got = _run_wait_with_child(quick, monkeypatch, tmp_path, programs=True)
    assert "\r" not in got and "child output\n" in got
    assert got in ("~ Applying...\nchild output\n", "child output\n~ Applying...\n")


def test_a_wait_without_programs_still_draws_in_place(quick, monkeypatch, tmp_path):
    got = _run_wait_with_child(quick, monkeypatch, tmp_path)
    assert "\r~ Applying... 0 s" in got


def test_bytes_written_to_the_buffer_take_the_line_off_first(quick, monkeypatch):
    import sys
    monkeypatch.setenv("NO_COLOR", "1")
    term = Tty()
    seen: list[str] = []

    class Raw(io.BytesIO):
        def write(self, data):
            seen.append(term.getvalue())             # what the screen held when the bytes arrived
            return super().write(data)
    term.buffer = Raw()
    monkeypatch.setattr("sys.stderr", term)
    with quick.wait("Updating…"):
        time.sleep(0.5)
        sys.stderr.buffer.write(b"raw bytes\n")
    assert "~ Updating... 0 s" in seen[0] and screen(seen[0]) == [""]       # up, then taken off before the bytes
    assert term.buffer.getvalue() == b"raw bytes\n"


def test_the_waits_that_run_programs_say_so(cfg, capsys, monkeypatch, tmp_path):
    from filament_kit import backup, output
    seen: dict[str, bool] = {}
    real = output.wait

    def spy(text, **kw):
        seen[text] = kw.get("programs", False)
        return real(text, **kw)
    monkeypatch.setattr(output, "wait", spy)
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(backup, "create", lambda *a, **k: tmp_path / "b.zip")
    monkeypatch.setattr(backup, "restore", lambda *a, **k: 0)
    monkeypatch.setattr(backup, "restore_steps", lambda: 1)
    zip_path = tmp_path / "b.zip"
    zip_path.write_bytes(b"x")
    run(capsys, "backup", "create")
    run(capsys, "restore", str(zip_path), "--yes")
    run(capsys, "status")
    assert seen == {"Backing up…": True, "Restoring…": True, "Checking…": True}


def test_the_apply_and_catalog_waits_run_programs_and_say_so(cfg, capsys, monkeypatch):
    from filament_kit import apply, library, output
    seen: dict[str, bool] = {}
    real = output.wait

    def spy(text, **kw):
        seen[text] = kw.get("programs", False)
        return real(text, **kw)
    monkeypatch.setattr(output, "wait", spy)
    monkeypatch.setattr(cli, "_require_root", lambda: True)
    monkeypatch.setattr(apply, "plan", lambda c: [])
    monkeypatch.setattr(apply, "step_names", lambda actions: [])
    monkeypatch.setattr(apply, "execute", lambda actions, step=None: None)
    monkeypatch.setattr(apply, "finish", lambda c, pairing=True: None)
    monkeypatch.setattr(library, "update", lambda *a, **k: library.UpdateResult(False, 7, 0, None))
    cli._run_apply(pairing=False)
    run(capsys, "library", "update")
    assert seen == {"Applying the changes…": True, "Updating the Filament Catalog…": True}
