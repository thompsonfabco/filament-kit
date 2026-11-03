"""The module checklist as a full-screen menu: cursor keys move, Space switches a module on or off, Enter applies.

Built on the standard library's curses, without colours (the cursor row is drawn reversed), so it works over SSH
and on a plain Linux console. The dependency rules are those of modules.toggle/preset; this file only adds keys
and drawing. With no terminal (stdin not a tty, TERM unset or `dumb`), when curses cannot start, or in a terminal
too small for it, the numbered checklist (modules.run_checklist) runs instead.

When stdout is not a terminal (install.sh captures `modules menu --raw`), the screen is drawn on /dev/tty.
"""
from __future__ import annotations

import os
import sys
from typing import Callable

from . import modules

# curses' key codes, so the state machine needs no curses (and is tested without a terminal)
KEY_DOWN, KEY_UP, KEY_HOME, KEY_END = 258, 259, 262, 360
KEY_NPAGE, KEY_PPAGE, KEY_ENTER, KEY_RESIZE = 338, 339, 343, 410
ESC = 27

FALLBACK = "fallback"     # _curses_menu: the terminal is too small (or became so); the numbered list takes over
HELP = "Up/Down move  Space on/off  Enter apply  a/s/t all-in-one/server/station  q cancel"
MIN_WIDTH = 40
_HEAD, _FOOT = 2, 3       # title + blank line; the cursor row's needs, the status line, the key help


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


class Checklist:
    """The menu's state: the module set, the cursor row and the status line. `key(code)` returns "apply",
    "cancel" or None (keep going)."""

    def __init__(self, on):
        self.on = frozenset(on)
        self.names = list(modules.MODULES)
        self.cursor = 0
        self.top = 0              # first row shown (scrolling)
        self.status = "Space switches the module under the cursor on or off."

    def key(self, ch: int) -> str | None:
        last = len(self.names) - 1
        if ch in (KEY_UP, ord("k")):
            self.cursor = max(0, self.cursor - 1)
        elif ch in (KEY_DOWN, ord("j")):
            self.cursor = min(last, self.cursor + 1)
        elif ch == KEY_HOME:
            self.cursor = 0
        elif ch == KEY_END:
            self.cursor = last
        elif ch == KEY_PPAGE:
            self.cursor = max(0, self.cursor - 5)
        elif ch == KEY_NPAGE:
            self.cursor = min(last, self.cursor + 5)
        elif ch == ord(" "):
            self._toggle(self.names[self.cursor])
        elif ch in (10, 13, KEY_ENTER):
            return "apply"
        elif ch in (ord("q"), ord("Q"), ESC):
            return "cancel"
        elif 0 <= ch < 256 and chr(ch) in modules.PRESET_KEYS:
            mode = modules.PRESET_KEYS[chr(ch)]
            self.on, notes = modules.preset(self.on, mode)
            listed = ", ".join(n for n in self.names if n in self.on) or "nothing"
            self.status = f"preset {mode}: " + (" ".join(notes) if notes else listed)
        return None

    def _toggle(self, name: str) -> None:
        old = self.on
        self.on, _ = modules.toggle(old, name)
        if name in self.on:
            extra = [n for n in self.names if n in self.on and n not in old and n != name]
            self.status = (f"turned on {_and([name] + extra)}: {name} needs {'it' if len(extra) == 1 else 'them'}"
                           if extra else f"turned on {name}")
        else:
            gone = [n for n in self.names if n in old and n not in self.on and n != name]
            self.status = (f"turning off {name} also turns off {', '.join(gone)}: they need it"
                           if gone else f"turned off {name}")


def fits(height: int, width: int) -> bool:
    return width >= MIN_WIDTH and height >= _HEAD + _FOOT + 3


def _row(name: str, on, width: int) -> str:
    m = modules.MODULES[name]
    w = max(len(n) for n in modules.MODULES)
    text = f" [{'x' if name in on else ' '}] {name:<{w}}  {m.description}"
    needs = modules.needs_of(name)
    if needs:
        text += "  needs: " + ", ".join(needs)
    if m.optional_ai:
        text += "   OPTIONAL AI"
    return text[:width - 1]


def screen(st: Checklist, height: int, width: int) -> list[tuple[int, str, str]]:
    """What to draw: (line, text, kind) with kind "title", "row", "cursor" or "foot". Scrolls `st.top` so the
    cursor row is shown. Every text is shorter than `width` (curses cannot write the last column of the last line)."""
    rows = height - _HEAD - _FOOT
    if st.cursor < st.top:
        st.top = st.cursor
    elif st.cursor >= st.top + rows:
        st.top = st.cursor - rows + 1
    st.top = max(0, min(st.top, len(st.names) - rows)) if len(st.names) > rows else 0
    cut = width - 1
    out = [(0, f"filament-kit modules (mode: {modules.mode_of(st.on)})"[:cut], "title")]
    shown = st.names[st.top:st.top + rows]
    for i, name in enumerate(shown):
        out.append((_HEAD + i, _row(name, st.on, width), "cursor" if st.top + i == st.cursor else "row"))
    if st.top > 0 or st.top + rows < len(st.names):
        out[0] = (0, (out[0][1] + f"   rows {st.top + 1}-{st.top + len(shown)} of {len(st.names)}")[:cut], "title")
    name = st.names[st.cursor]
    needs = modules.needs_of(name)
    detail = f"{name}: needs " + ", ".join(needs) if needs else f"{name}: needs nothing else"
    if modules.MODULES[name].optional_ai:
        detail += "   OPTIONAL AI"
    out += [(height - 3, detail[:cut], "foot"), (height - 2, st.status[:cut], "foot"),
            (height - 1, HELP[:cut], "foot")]
    return out


def _draw(stdscr, st: Checklist) -> None:
    import curses
    h, w = stdscr.getmaxyx()
    stdscr.erase()
    for y, text, kind in screen(st, h, w):
        attr = curses.A_REVERSE if kind == "cursor" else curses.A_BOLD if kind == "title" else curses.A_NORMAL
        try:
            stdscr.addstr(y, 0, text, attr)
        except curses.error:
            pass
    stdscr.refresh()


def _loop(stdscr, st: Checklist) -> str:
    import curses
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    while True:
        h, w = stdscr.getmaxyx()
        if not fits(h, w):
            return FALLBACK
        _draw(stdscr, st)
        ch = stdscr.getch()
        if ch == KEY_RESIZE:
            continue
        result = st.key(ch)
        if result:
            return result


def _curses_menu(st: Checklist) -> str:
    """Run the screen; "apply", "cancel" or FALLBACK. Raises curses.error/OSError when curses cannot start.
    curses.wrapper puts the terminal back on every way out (Ctrl-C included)."""
    import curses
    os.environ.setdefault("ESCDELAY", "25")       # Esc cancels at once, not after ncurses' default second
    swapped = None
    if not os.isatty(1):
        tty = os.open("/dev/tty", os.O_RDWR)      # stdout is captured (install.sh): draw on the terminal
        sys.stdout.flush()
        sys.__stdout__.flush()
        swapped = os.dup(1)
        os.dup2(tty, 1)
        os.close(tty)
    try:
        return curses.wrapper(_loop, st)
    finally:
        if swapped is not None:
            os.dup2(swapped, 1)
            os.close(swapped)


def _stdin_tty() -> bool:
    """sys.stdin and fd 0 (what curses reads) are both a terminal."""
    try:
        return sys.stdin.isatty() and os.isatty(0)
    except (AttributeError, ValueError, OSError):
        return False


def _usable() -> bool:
    return os.environ.get("TERM", "") not in ("", "dumb") and _stdin_tty()


def run_menu(on, ask: Callable[[str], str | None], say: Callable[[str], None] = print) -> frozenset[str] | None:
    """The module menu: the chosen set, or None when cancelled (q, Esc, Ctrl-C). Falls back to the numbered
    checklist (`ask`/`say`) without a usable terminal."""
    st = Checklist(on)
    if _usable():
        try:
            result = _curses_menu(st)
        except KeyboardInterrupt:
            return None
        except Exception:                         # noqa: BLE001 - curses.error, no /dev/tty: use the list
            result = FALLBACK
        if result == "apply":
            return st.on
        if result == "cancel":
            return None
    return modules.run_checklist(st.on, ask, say)
