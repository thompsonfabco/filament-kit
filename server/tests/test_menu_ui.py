"""The cursor-key module menu (menu_ui): the key handling as a pure state machine, the fallback rules, and one run of
the real curses screen in a pty (Linux only)."""
import io
import os
import select
import signal
import subprocess
import sys
import time

import pytest

from filament_kit import menu_ui, modules

NAMES = list(modules.MODULES)
SPACE, ENTER, ESC = ord(" "), ord("\n"), 27


def _keys(st, *codes):
    out = None
    for c in codes:
        out = st.key(ord(c) if isinstance(c, str) else c)
        if out:
            break
    return out


def _at(name):
    return NAMES.index(name)


def test_cursor_moves_with_arrows_and_jk_and_stays_in_range():
    st = menu_ui.Checklist(modules.MODES["server"])
    assert st.cursor == 0
    _keys(st, menu_ui.KEY_UP)                       # top: stays
    assert st.cursor == 0
    _keys(st, menu_ui.KEY_DOWN, "j", "j")
    assert st.cursor == 3
    _keys(st, "k")
    assert st.cursor == 2
    _keys(st, *[menu_ui.KEY_DOWN] * 40)
    assert st.cursor == len(NAMES) - 1
    _keys(st, menu_ui.KEY_HOME)
    assert st.cursor == 0
    _keys(st, menu_ui.KEY_END)
    assert st.cursor == len(NAMES) - 1


def test_space_toggles_and_enter_applies():
    st = menu_ui.Checklist(modules.MODES["server"])
    st.cursor = _at("library")
    assert _keys(st, " ") is None
    assert "library" in st.on and st.status == "turned on library"
    _keys(st, " ")
    assert "library" not in st.on and st.status == "turned off library"
    st.cursor = _at("updates")
    assert _keys(st, " ", ENTER) == "apply"
    assert st.on == modules.MODES["server"] | {"updates"}


def test_turning_on_pulls_in_what_it_needs_and_says_so():
    st = menu_ui.Checklist({"spoolman"})
    st.cursor = _at("remote")
    _keys(st, " ")
    assert {"remote", "web", "server"} <= st.on
    assert st.status == "turned on remote, server and web: remote needs them"
    st2 = menu_ui.Checklist({"spoolman"})
    st2.cursor = _at("web")
    _keys(st2, " ")
    assert st2.status == "turned on web and server: web needs it"


def test_turning_off_drops_what_depends_on_it_and_says_so():
    on = modules.MODES["server"] | {"web", "ai_intake", "orders"}
    st = menu_ui.Checklist(on)
    st.cursor = _at("server")
    _keys(st, " ")
    assert not ({"server", "web", "ai_intake", "orders", "printers", "presets"} & st.on)
    assert st.status.startswith("turning off server also turns off ai_intake, printers, presets, web, orders")


def test_same_rules_as_the_numbered_checklist():
    """No second resolver: every toggle gives the set modules.toggle gives."""
    for name in NAMES:
        for start in (frozenset(), modules.MODES["server"], modules.MODES["all-in-one"] | {"web", "remote"}):
            st = menu_ui.Checklist(start)
            st.cursor = _at(name)
            _keys(st, " ")
            assert st.on == modules.toggle(start, name)[0], (name, start)


def test_presets_a_s_t():
    st = menu_ui.Checklist(modules.MODES["server"] | {"web"})
    _keys(st, "t")
    assert st.on == modules.preset(modules.MODES["server"] | {"web"}, "station")[0]
    assert st.status.startswith("preset station")
    _keys(st, "a")
    assert st.on == modules.MODES["all-in-one"]
    _keys(st, "s")
    assert st.on == modules.MODES["server"]
    assert st.status.startswith("preset server")


def test_q_and_esc_cancel_and_change_nothing():
    for k in ("q", ESC):
        st = menu_ui.Checklist(modules.MODES["server"])
        st.cursor = _at("library")
        assert _keys(st, " ", k) == "cancel"


def test_other_keys_do_nothing():
    st = menu_ui.Checklist(modules.MODES["server"])
    assert _keys(st, "z", "9", menu_ui.KEY_RESIZE) is None
    assert st.on == modules.MODES["server"]


def test_screen_rows_scroll_to_keep_the_cursor_visible():
    st = menu_ui.Checklist(modules.MODES["server"])
    st.cursor = len(NAMES) - 1
    rows = menu_ui.screen(st, height=10, width=80)
    texts = [t for _, t, _ in rows]
    last = NAMES[-1]                                 # the registry's last module (klipper since the Klipper work)
    assert any(t.lstrip().startswith(f"[ ] {last}") for t in texts)
    cur = [t for _, t, a in rows if a == "cursor"]
    assert len(cur) == 1 and last in cur[0]
    assert all(len(t) < 80 for t in texts)
    assert texts[-1].startswith("Up/Down")          # the key help is always on the last line
    st.cursor = 0
    texts = [t for _, t, _ in menu_ui.screen(st, height=10, width=80)]
    assert any("spoolman" in t for t in texts) and not any(f"[ ] {last}" in t for t in texts[:-3])


def test_screen_shows_the_needs_and_optional_ai_of_the_row():
    st = menu_ui.Checklist(frozenset())
    st.cursor = _at("ai_intake")
    texts = [t for _, t, _ in menu_ui.screen(st, height=30, width=200)]
    assert any("needs: server, an Anthropic API key" in t and "OPTIONAL AI" in t for t in texts)


def test_too_small_terminal_is_reported():
    st = menu_ui.Checklist(frozenset())
    assert menu_ui.fits(24, 80) and not menu_ui.fits(24, 30) and not menu_ui.fits(5, 80)


def test_fallback_without_a_tty(monkeypatch):
    s = io.StringIO("2\n\n")
    s.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", s)
    monkeypatch.setenv("TERM", "xterm")
    said = []
    got = menu_ui.run_menu(modules.MODES["server"], lambda p: s.readline().rstrip("\n"), said.append)
    assert "server" not in got and any("[x]" in line for line in said)   # the numbered list ran


@pytest.mark.parametrize("term", ["", "dumb"])
def test_fallback_on_a_dumb_terminal(monkeypatch, term):
    s = io.StringIO("")
    s.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", s)
    monkeypatch.setattr(menu_ui, "_stdin_tty", lambda: True)
    monkeypatch.setenv("TERM", term)
    called = []
    monkeypatch.setattr(menu_ui, "_curses_menu", lambda st: called.append(1))
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: None, lambda t: None) is None   # EOF: cancel
    assert called == []


def test_curses_result_is_used_and_a_fallback_keeps_the_choices(monkeypatch):
    s = io.StringIO("\n")
    s.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", s)
    monkeypatch.setattr(menu_ui, "_stdin_tty", lambda: True)
    monkeypatch.setenv("TERM", "xterm")

    def ui(st):
        st.on = st.on | {"library"}
        return "apply"
    monkeypatch.setattr(menu_ui, "_curses_menu", ui)
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: None, lambda t: None) == \
        modules.MODES["server"] | {"library"}
    monkeypatch.setattr(menu_ui, "_curses_menu", lambda st: "cancel")
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: None, lambda t: None) is None

    def small(st):
        st.on = st.on | {"updates"}
        return menu_ui.FALLBACK                     # the terminal was too small: the list starts from the choices
    monkeypatch.setattr(menu_ui, "_curses_menu", small)
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: "", lambda t: None) == \
        modules.MODES["server"] | {"updates"}

    def interrupted(st):
        raise KeyboardInterrupt
    monkeypatch.setattr(menu_ui, "_curses_menu", interrupted)
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: None, lambda t: None) is None


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
    """`filament-kit modules menu --raw` with the pty as its terminal and stdout on a pipe (as install.sh runs it):
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
        screen = _read_until(master, b"Up/Down")
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
    code, out, screen = _run_in_pty(tmp_path, [down] * to_library + [b" "] + [b"j"] * to_updates + [b" ", b"\r"])
    assert b"[x] spoolman" in screen and b"Up/Down" in screen
    assert code == 0, screen[-2000:]
    assert out.splitlines() == ["spoolman,server,printers,presets,library,backup,updates"]


@pytest.mark.skipif(sys.platform == "win32" or not _curses_ok(), reason="needs a pty and curses (Linux)")
def test_real_curses_menu_cancel_in_a_pty(tmp_path):
    code, out, _ = _run_in_pty(tmp_path, [b" ", b"q"])
    assert code == 1 and out == ""


# ---------- fix round 1: which failures fall back, ESCDELAY, Ctrl-C ----------

class _FakeCurses:
    """Stands in for the curses module: `wrapper` runs `behave`."""

    class error(Exception):
        pass

    def __init__(self, behave):
        self.behave = behave

    def wrapper(self, fn, *args):
        return self.behave()


def _tty_stdin(monkeypatch):
    s = io.StringIO("\n")
    s.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", s)
    monkeypatch.setattr(menu_ui, "_stdin_tty", lambda: True)
    monkeypatch.setenv("TERM", "xterm")


def test_curses_init_failure_falls_back_to_the_list(monkeypatch):
    _tty_stdin(monkeypatch)
    fake = _FakeCurses(lambda: (_ for _ in ()).throw(_FakeCurses.error("setupterm: could not find terminal")))
    monkeypatch.setitem(sys.modules, "curses", fake)
    monkeypatch.setattr(menu_ui.os, "isatty", lambda fd: True)
    said = []
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: "", said.append) == modules.MODES["server"]
    assert any("[x]" in line for line in said)


def test_no_dev_tty_falls_back_to_the_list(monkeypatch):
    _tty_stdin(monkeypatch)
    ran = []
    monkeypatch.setitem(sys.modules, "curses", _FakeCurses(lambda: ran.append(1) or "apply"))
    monkeypatch.setattr(menu_ui.os, "isatty", lambda fd: False)     # stdout captured

    def no_tty(path, flags, *a):
        raise OSError(6, "No such device or address", path)
    monkeypatch.setattr(menu_ui.os, "open", no_tty)
    said = []
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: "", said.append) == modules.MODES["server"]
    assert ran == [] and any("[x]" in line for line in said)


def test_other_errors_in_the_screen_code_are_not_hidden(monkeypatch):
    _tty_stdin(monkeypatch)
    monkeypatch.setitem(sys.modules, "curses", _FakeCurses(lambda: 1 / 0))
    monkeypatch.setattr(menu_ui.os, "isatty", lambda fd: True)
    with pytest.raises(ZeroDivisionError):
        menu_ui.run_menu(modules.MODES["server"], lambda p: "", lambda t: None)


@pytest.mark.parametrize("before", [None, "1000"])
def test_escdelay_is_set_only_while_the_screen_runs(monkeypatch, before):
    _tty_stdin(monkeypatch)
    if before is None:
        monkeypatch.delenv("ESCDELAY", raising=False)
    else:
        monkeypatch.setenv("ESCDELAY", before)
    seen = []
    monkeypatch.setitem(sys.modules, "curses", _FakeCurses(lambda: seen.append(os.environ.get("ESCDELAY")) or "cancel"))
    monkeypatch.setattr(menu_ui.os, "isatty", lambda fd: True)
    assert menu_ui.run_menu(modules.MODES["server"], lambda p: "", lambda t: None) is None
    assert seen == ["25"] and os.environ.get("ESCDELAY") == before


@pytest.mark.skipif(sys.platform == "win32" or not _curses_ok(), reason="needs a pty and curses (Linux)")
def test_real_curses_menu_ctrl_c_restores_the_terminal(tmp_path):
    code, out, screen = _run_in_pty(tmp_path, [b" ", b"\x03"])
    assert code == 1 and out == ""
    assert b"\x1b[?1049l" in screen                  # left the alternate screen: the terminal is back
