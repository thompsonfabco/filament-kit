"""Menus, checklists and their prompts: one key map, two variants (docs/design/06-command-line.md 8.1 and 8.2).

A screen is data (`Screen`, its `Row`s); what a key or a typed line means is the same in both variants (`Keys`,
`parse_line`): numbers choose items, letters choose actions, `s` saves or applies, `q` (or Esc) leaves, `?` lists the
keys. The variants only differ in how they draw and read:

    CursesUi    full-screen (the standard library's curses, no colours: the cursor row is reversed and starts with
                `>`), when input and output are terminals, TERM is not `dumb`, the terminal is at least 40 x 8, and
                curses starts. Prompts appear on the footer's first line.
    NumberedUi  plain lines and a `Number:` prompt: otherwise, and always with `--numbered`, SPOOLWARDEN_MENU=numbered
                or `--plain`.

`open_ui` picks one. The screens' contents and what their events do belong to the caller (cli.py): `ui.choose(screen)`
returns an event, and the caller says what happened with `ui.say` / `ui.error` (a curses screen owns the terminal, so
nothing else may print while it is up; `ui.suspended()` hands the terminal back for a command that prints).

When stdout is not a terminal (install.sh captures `modules menu --raw`), the screen is drawn on /dev/tty.
"""
from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass
from typing import Callable

from . import output

# curses' key codes, so the state machine needs no curses (and is tested without a terminal)
KEY_DOWN, KEY_UP, KEY_HOME, KEY_END = 258, 259, 262, 360
KEY_NPAGE, KEY_PPAGE, KEY_ENTER, KEY_RESIZE, KEY_BACKSPACE = 338, 339, 343, 410, 263
ESC = 27

MIN_WIDTH, MIN_HEIGHT = 40, 8


@dataclass
class Row:
    label: str
    value: str = ""
    mark: str | None = None         # a checklist row: "x" on, " " off; None in a menu
    dim: bool = False               # a row that cannot be opened now (its value says why)
    before: tuple[str, ...] = ()    # heading lines drawn above the row (06 8.3 sub-headings)
    note: str = ""                  # the footer's first line while the cursor is on this row
    detail: str = ""                # said after the value in the numbered variant only (a checklist row's needs)


@dataclass
class Screen:
    id: str                         # the cursor of a screen is kept per id while the session lasts
    title: str                      # the header: `Settings > Storage locations`
    rows: list[Row]
    kind: str = "menu"              # "menu" or "checklist"
    actions: tuple[tuple[str, str], ...] = ()    # (letter, words): `("a", "add a printer")`
    save: str = ""                  # the word for `s` ("save", "apply"); empty: this screen has no `s`
    leave: str = "leave"            # the word for `q`: "leave" at the top, "back" below
    changes: int = 0                # staged changes: the header says so
    intro: tuple[str, ...] = ()     # lines before the list (numbered variant and the full-screen header's second line)
    after: tuple[str, ...] = ()     # lines after the list, before the keys (numbered)
    plan: str = ""                  # a checklist's plan line (the footer's second line, 8.5)
    hint: str = ""                  # numbered checklist: said again for an empty answer
    prompt: str = ""                # numbered: the prompt; default `Number: ` or `Number or letter: `
    empty_leaves: bool = False      # an empty answer leaves (a choice: Enter keeps the value)
    empty: str = ""                 # said instead of the rows when there are none

    def header(self) -> str:
        sep = output.sym("sep")
        n = self.changes
        return self.title + (f"{sep}{n} change{'' if n == 1 else 's'} not saved" if n else "")

    def prompt_text(self) -> str:
        return self.prompt or ("Number: " if self.rows else "Number or letter: ")


# ---------- the key map (8.2) ----------

# events: ("open", i), ("toggle", [i, ...]), ("save",), ("leave",), ("action", letter), ("help",), ("empty",),
#         ("unknown", text), ("eof",)

class Keys:
    """The cursor and the number being typed on one screen. `key(code)` returns an event or None."""

    def __init__(self, screen: Screen, cursor: int = 0):
        self.screen = screen
        self.cursor = min(cursor, max(0, len(screen.rows) - 1))
        self.top = 0
        self.typed = ""

    def _letters(self) -> set[str]:
        return {a for a, _ in self.screen.actions}

    def _pick(self, i: int) -> tuple:
        return ("toggle", [i]) if self.screen.kind == "checklist" else ("open", i)

    def key(self, ch: int) -> tuple | None:
        sc, last = self.screen, len(self.screen.rows) - 1
        if 48 <= ch <= 57:                                  # a digit: the number of an item
            return self._digit(chr(ch))
        typed, self.typed = self.typed, ""
        if ch in (10, 13, KEY_ENTER):
            if typed:
                n = int(typed)
                return self._pick(n - 1) if 1 <= n <= last + 1 else ("unknown", typed)
            return self._pick(self.cursor) if last >= 0 else None
        if 0 <= ch < 256 and chr(ch) in self._letters():    # a screen's own letters come before j and k
            return ("action", chr(ch))
        if ch in (KEY_UP, ord("k")):
            self.cursor = max(0, self.cursor - 1)
        elif ch in (KEY_DOWN, ord("j")):
            self.cursor = min(last, self.cursor + 1)
        elif ch == KEY_HOME:
            self.cursor = 0
        elif ch == KEY_END:
            self.cursor = max(0, last)
        elif ch == KEY_PPAGE:
            self.cursor = max(0, self.cursor - 5)
        elif ch == KEY_NPAGE:
            self.cursor = min(last, self.cursor + 5)
        elif ch == ord(" "):
            if sc.kind == "checklist" and last >= 0:
                return ("toggle", [self.cursor])
        elif ch in (ord("q"), ord("Q"), ESC):
            return ("leave",)
        elif ch == ord("?"):
            return ("help",)
        elif ch in (ord("s"), ord("S")) and sc.save:
            return ("save",)
        elif 32 < ch < 127:
            return ("unknown", chr(ch))
        return None

    def _digit(self, d: str) -> tuple | None:
        """Typing a number: it goes at once when no longer number starts with it, otherwise Enter (or one more digit)."""
        count = len(self.screen.rows)
        self.typed += d
        n = int(self.typed)
        if n > count or n < 1:
            typed, self.typed = self.typed, ""
            return ("unknown", typed)           # `1` then `2` on 11 rows is 12: no such row, nothing else is opened
        if n * 10 > count:
            self.typed = ""
            return self._pick(n - 1)
        return None


def parse_line(screen: Screen, line: str) -> tuple:
    """What a line typed at the numbered prompt means: an event. Numbers choose (several at once in a checklist: `2 5 7`),
    letters act; anything else is `("unknown", token)`."""
    tokens = line.replace(",", " ").split()
    if not tokens:
        return ("empty",)
    count, letters = len(screen.rows), {a for a, _ in screen.actions}
    nums = [t for t in tokens if t.isdigit()]
    if len(nums) == len(tokens):
        picked = [int(t) for t in tokens]
        bad = next((t for t in tokens if not 1 <= int(t) <= count), None)
        if bad is not None:
            return ("unknown", bad)
        if screen.kind == "checklist":
            return ("toggle", [n - 1 for n in picked])
        return ("open", picked[0] - 1) if len(picked) == 1 else ("unknown", tokens[1])
    token = next(t for t in tokens if not t.isdigit())
    if len(tokens) > 1:
        return ("unknown", token)
    word = token.lower()
    if word in letters:
        return ("action", word)
    if word in ("q", "quit"):
        return ("leave",)
    if word == "?":
        return ("help",)
    if word == "s" and screen.save:
        return ("save",)
    return ("unknown", token)


def unknown_text(token: str) -> str:
    return f'"{token}" is not a number or letter on this screen.'


# ---------- what a screen says (both variants) ----------

def key_words(screen: Screen) -> list[tuple[str, str]]:
    """The letters of a screen with their words, in the order they are listed under it."""
    out = list(screen.actions)
    if screen.save:
        out.append(("s", screen.save))
    out += [("q", screen.leave), ("?", "help")]
    return out


def keys_lines(screen: Screen, width: int) -> list[str]:
    """`  s save   q leave   ? help` under a numbered list; a long list of actions goes on more lines, never cutting
    one in the middle."""
    lines, line = [], "  "
    for k, w in key_words(screen):
        item = f"{k} {w}"
        if line.strip() and len(line) + 3 + len(item) > width - 1:
            lines.append(line)
            line = "  "
        line += ("   " if line.strip() else "") + item
    return lines + [line]


def foot_line(screen: Screen, width: int = 80) -> str:
    """The full-screen footer's last line, short enough for 40 columns: `Enter open  s save  q leave  ? help`. The
    screen's own letters are left out when they do not fit (`?` lists them)."""
    first = "Space on/off" if screen.kind == "checklist" else "Enter open"
    tail = ([f"s {screen.save}"] if screen.save else []) + [f"q {screen.leave}", "? help"]
    text = "  ".join([first] + [f"{k} {w}" for k, w in screen.actions] + tail)
    return text if len(text) < width else "  ".join([first] + tail)


def help_lines(screen: Screen, fullscreen: bool) -> list[str]:
    lines = ["Keys on this screen:"]
    if fullscreen:
        lines.append("  Up / Down (or k / j), Home, End, PgUp / PgDn   move the cursor")
    if screen.kind == "checklist":
        lines.append("  Space or Enter on the row, or its number" if fullscreen
                     else "  1 2 ...        type the number of a row to switch it; several at once: 2 5 7")
        lines.append("  Enter never applies; only s does")
    else:
        lines.append("  Enter on the row, or its number" if fullscreen else "  1 2 ...        type a number, then Enter")
    for k, w in screen.actions:
        lines.append(f"  {k}              {w}")
    if screen.save:
        lines.append("  s              " + {"save": "save every change at once (leaving saves nothing)",
                                            "apply": "apply the switched rows (leaving applies nothing)"}.get(
                                                screen.save, screen.save))
    lines.append(f"  q              {screen.leave}" + (" (or Esc)" if fullscreen else ""))
    lines.append("  ?              this list")
    lines.append("  Ctrl-C         leave at once, saving nothing")
    return lines


def _cut(text: str, width: int) -> str:
    return text[:max(0, width - 1)]


def _label_width(screen: Screen) -> int:
    return max((len(r.label) for r in screen.rows), default=0)


def row_text(screen: Screen, i: int, width: int, *, cursor: bool = False) -> str:
    r = screen.rows[i]
    mark = f"[{r.mark}] " if r.mark is not None else ""
    head = f"{'>' if cursor else ' '} {i + 1:>2} {mark}"
    text = f"{head}{r.label:<{_label_width(screen)}}" + (f"  {r.value}" if r.value else "")
    return _cut(text.rstrip(), width)


def numbered_lines(screen: Screen) -> list[str]:
    """The screen as lines for the numbered variant: the header, the rows, the keys under them. Long rows wrap at
    spaces under their label; below 60 columns each row is a block (the number and label, then its value on the lines
    under it, 06 6.3) so the value keeps a readable width."""
    lines = [screen.header(), *screen.intro]
    if screen.rows or not screen.intro:
        lines.append("")
    lw = _label_width(screen)
    narrow = output.width() < 60
    if not screen.rows and screen.empty:
        lines += output.wrap(screen.empty, indent=2)
    for i, r in enumerate(screen.rows):
        for h in r.before:
            lines += ["", f"  {h}"] if h else [""]
        mark = f"[{r.mark}] " if r.mark is not None else ""
        head = f"{i + 1:>4}  {mark}"
        value = "  ".join(x for x in (r.value, r.detail) if x)
        if narrow:
            lines.append((head + r.label).rstrip())
            lines += output.wrap(value, indent=len(head)) if value else []
            continue
        text = (head + f"{r.label:<{lw}}" + (f"  {value}" if value else "")).rstrip()
        lead = len(text) - len(text.lstrip())              # wrap carries a line's leading spaces to the lines it wraps
        lines += output.wrap(text, indent=len(head) + lw + 2 - lead, first=0)
    if screen.after:
        lines += ["", *screen.after]
    if screen.kind != "checklist":              # a checklist's line under the rows already says its keys
        lines += ["", *keys_lines(screen, output.width())]
    return lines


def layout(screen: Screen, keys: Keys, height: int, width: int, status: str = "") -> list[tuple[int, str, str]]:
    """What the full-screen variant draws: (line, text, kind) with kind "head", "row", "cursor", "dim", "title" (a
    sub-heading) or "foot". Scrolls `keys.top` so the cursor row shows. Every text is shorter than `width` (curses
    cannot write the last column of the last line)."""
    foot = 3 if screen.plan else 2
    room = max(1, height - 1 - foot)
    items: list[tuple[int | None, str]] = [(None, f"  {t}") for t in screen.intro]
    if not screen.rows and screen.empty:
        items.append((None, f"  {screen.empty}"))
    for i, r in enumerate(screen.rows):
        items += [(None, f"  {h}") for h in r.before if h]
        items.append((i, ""))
    at = next((n for n, (i, _) in enumerate(items) if i == keys.cursor), 0)
    if at < keys.top:
        keys.top = at
    elif at >= keys.top + room:
        keys.top = at - room + 1
    keys.top = max(0, min(keys.top, len(items) - room)) if len(items) > room else 0
    shown = items[keys.top:keys.top + room]
    head = screen.header()
    if len(items) > room:
        rows = [i for i, _ in shown if i is not None]
        if rows:
            head += f"   rows {rows[0] + 1}-{rows[-1] + 1} of {len(screen.rows)}"
    out = [(0, _cut(head, width), "head")]
    for n, (i, text) in enumerate(shown):
        if i is None:
            out.append((1 + n, _cut(text, width), "title"))
        else:
            kind = "cursor" if i == keys.cursor else "dim" if screen.rows[i].dim else "row"
            out.append((1 + n, row_text(screen, i, width, cursor=i == keys.cursor), kind))
    note = status or (screen.rows[keys.cursor].note if screen.rows else "")
    base = height - foot
    out.append((base, _cut(note, width), "foot"))
    if screen.plan:
        out.append((base + 1, _cut(screen.plan, width), "foot"))
    out.append((height - 1, _cut(foot_line(screen, width), width), "foot"))
    return out


# ---------- the numbered variant ----------

class NumberedUi:
    """Plain lines, `Number:` prompts. `ask(prompt)` returns the line typed (None at the end of input)."""

    variant = "numbered"

    def __init__(self, ask: Callable[[str], str | None], secret: Callable[[str], str] | None = None):
        self._ask = ask
        self._secret = secret

    def choose(self, screen: Screen, show: bool = True) -> tuple:
        if show:
            with output.shown():        # the screen is the context of the question: seen even under --quiet
                output.out_lines(numbered_lines(screen))
        while True:
            line = self._ask(screen.prompt_text())
            if line is None:
                return ("eof",)
            ev = parse_line(screen, line)
            if ev[0] == "help":
                with output.shown():
                    output.out_lines(help_lines(screen, False))
            elif ev[0] == "empty":
                if screen.empty_leaves:
                    return ("leave",)
                if screen.hint:
                    with output.shown():
                        output.out(screen.hint)
            elif ev[0] == "unknown":
                output.error(unknown_text(ev[1]))
            else:
                return ev

    def ask(self, prompt: str, *, secret: bool = False) -> str | None:
        if secret and self._secret is not None:
            try:
                return self._secret(prompt)
            except (EOFError, OSError):
                return None
        return self._ask(prompt)

    def say(self, text: str) -> None:
        with output.shown():
            output.out(text)

    def error(self, text: str) -> None:
        output.error(text)

    def yesno(self, question: str) -> bool | None:
        """True after yes; False after anything else; None at the end of input."""
        answer = self._ask(question + " [y/N] ")
        if answer is None:
            return None
        return answer.strip().lower() in ("y", "yes")

    @contextlib.contextmanager
    def suspended(self):
        yield


# ---------- the full-screen variant ----------

class CursesUi:
    """The screen on a curses window. `stdscr` needs keypad, getmaxyx, erase, addstr, refresh and get_wch; `curses`
    is the module (or a stand-in with its A_REVERSE, A_BOLD, A_DIM and error)."""

    variant = "full-screen"

    def __init__(self, stdscr, curses):
        self.scr, self.cur = stdscr, curses
        self.status = ""
        self.cursors: dict[str, int] = {}
        self._last: tuple[Screen, Keys] | None = None

    # drawing
    def _attr(self, kind: str) -> int:
        c = self.cur
        return {"cursor": c.A_REVERSE, "head": c.A_BOLD, "dim": c.A_DIM, "title": c.A_BOLD}.get(kind, 0)

    def _draw(self, screen: Screen, keys: Keys, line: str | None = None, above: str = "") -> None:
        """One frame. While a prompt holds the footer's first line (`line`), what was said before it (a wrong value's
        error) stays visible on the line above the footer (`above`)."""
        h, w = self.scr.getmaxyx()
        self.scr.erase()
        drawn = layout(screen, keys, h, w, self.status if line is None else line)
        if above:
            foot = 3 if screen.plan else 2
            drawn.append((max(0, h - foot - 1), _cut(above, w), "foot"))
        for y, text, kind in drawn:
            try:
                self.scr.addstr(y, 0, text, self._attr(kind))
            except self.cur.error:
                pass
        self.scr.refresh()

    def _getkey(self):
        k = self.scr.get_wch()
        return k

    # the interface
    def choose(self, screen: Screen, show: bool = True) -> tuple:
        keys = Keys(screen, self.cursors.get(screen.id, 0))
        while True:
            self._last = (screen, keys)
            self._draw(screen, keys)
            k = self._getkey()
            if k == KEY_RESIZE:
                continue
            ch = ord(k) if isinstance(k, str) else k
            if isinstance(k, str) and ch >= 256:
                continue
            if ch == 4:                     # Ctrl-D: the input ended (8.2)
                return ("eof",)
            self.status = ""
            ev = keys.key(ch)
            self.cursors[screen.id] = keys.cursor
            if ev is None:
                continue
            if ev[0] == "help":
                self._help(screen)
            elif ev[0] == "unknown":
                self.status = "Error: " + unknown_text(ev[1])
            else:
                return ev

    def _help(self, screen: Screen) -> None:
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        lines = help_lines(screen, True) + ["", "Any key goes back."]
        for y, text in enumerate(lines[:h]):
            try:
                self.scr.addstr(y, 0, _cut(text, w))
            except self.cur.error:
                pass
        self.scr.refresh()
        self._getkey()

    def ask(self, prompt: str, *, secret: bool = False) -> str | None:
        """The prompt on the footer's first line. Enter ends it; Esc gives an empty answer; Backspace works."""
        buf: list[str] = []
        screen, keys = self._last
        said, self.status = self.status, ""
        while True:
            shown = "*" * len(buf) if secret else "".join(buf)
            self._draw(screen, keys, prompt + shown, said)
            k = self._getkey()
            if k in ("\n", "\r") or k == KEY_ENTER:
                return "".join(buf)
            if k == "\x1b":
                return ""
            if k == "\x04":                  # Ctrl-D: the input ended (8.2)
                return None
            if k in ("\x7f", "\b") or k == KEY_BACKSPACE:
                if buf:
                    buf.pop()
            elif k == "\x15":
                buf.clear()
            elif isinstance(k, str) and k.isprintable():
                buf.append(k)

    def say(self, text: str) -> None:
        self.status = text

    def error(self, text: str) -> None:
        self.status = "Error: " + text

    def yesno(self, question: str) -> bool | None:
        answer = self.ask(question + " [y/N] ")
        return None if answer is None else answer.strip().lower() in ("y", "yes")

    @contextlib.contextmanager
    def suspended(self):
        """Hand the terminal back for a command that prints and asks; the screen returns after Enter. Ctrl-C leaves
        without asking (8.2)."""
        self.cur.def_prog_mode()
        self.cur.endwin()
        try:
            yield
        except BaseException:
            self.cur.reset_prog_mode()
            raise
        try:
            input("\nPress Enter to go back to the menu. ")
        except EOFError:
            pass
        self.cur.reset_prog_mode()
        self.scr.refresh()


# ---------- choosing the variant ----------

def _stdin_tty() -> bool:
    """sys.stdin and fd 0 (what curses reads) are both a terminal."""
    try:
        return sys.stdin.isatty() and os.isatty(0)
    except (AttributeError, ValueError, OSError):
        return False


def _stdout_tty() -> bool:
    try:
        return sys.stdout.isatty() and os.isatty(1)
    except (AttributeError, ValueError, OSError):
        return False


def fullscreen_wanted(raw: bool = False) -> bool:
    """06 8.1: not `--numbered` / `--plain`, TERM set and not `dumb`, input and output both terminals (with `raw`, the
    output is captured and the screen goes to /dev/tty)."""
    if output.numbered():
        return False
    if os.environ.get("TERM", "") in ("", "dumb"):
        return False
    return _stdin_tty() and (raw or _stdout_tty())


def fits(height: int, width: int) -> bool:
    return width >= MIN_WIDTH and height >= MIN_HEIGHT


def _start_errors() -> tuple[type[BaseException], ...]:
    """What starting curses raises: no curses module, a terminal curses does not know, no /dev/tty. Anything else is a
    bug and is not hidden behind the numbered list."""
    try:
        import curses
    except ImportError:
        return (ImportError, OSError)
    return (curses.error, ImportError, OSError)


@contextlib.contextmanager
def open_ui(ask: Callable[[str], str | None], secret: Callable[[str], str] | None = None, *, raw: bool = False):
    """The screens' interface: full-screen when 06 8.1 allows it, otherwise numbered (`ask` reads its lines). When only
    the size says no, one `Note:` line says why. The terminal is put back on every way out (Ctrl-C included)."""
    if not fullscreen_wanted(raw):
        yield NumberedUi(ask, secret)
        return
    ui, undo = _start_curses(raw)
    if ui is None:
        yield NumberedUi(ask, secret)
        return
    try:
        yield ui
    finally:
        undo()


def _start_curses(raw: bool):
    """(CursesUi, undo) or (None, None) when curses cannot start or the terminal is too small."""
    swapped = None
    if not _stdout_tty():
        try:
            tty = os.open("/dev/tty", os.O_RDWR)      # stdout is captured (install.sh): draw on the terminal
        except OSError:
            return None, None
        sys.stdout.flush()
        sys.__stdout__.flush()
        swapped = os.dup(1)
        os.dup2(tty, 1)
        os.close(tty)
    escdelay = os.environ.get("ESCDELAY")
    os.environ["ESCDELAY"] = "25"                     # Esc leaves at once, not after ncurses' default second
    scr = None
    cur = None

    def undo() -> None:
        if scr is not None:
            try:
                scr.keypad(False)
                cur.nocbreak()
                cur.echo()
                cur.endwin()
            except Exception:  # noqa: BLE001 - putting the terminal back must not hide what ended the screen
                pass
        if escdelay is None:
            os.environ.pop("ESCDELAY", None)
        else:
            os.environ["ESCDELAY"] = escdelay
        if swapped is not None:
            os.dup2(swapped, 1)
            os.close(swapped)

    try:
        import curses as cur
        scr = cur.initscr()
        cur.noecho()
        cur.cbreak()
        scr.keypad(True)
        try:
            cur.curs_set(0)
        except cur.error:
            pass
        h, w = scr.getmaxyx()
    except _start_errors():
        undo()
        return None, None
    except BaseException:
        undo()
        raise
    if not fits(h, w):
        undo()
        times = "×" if output.unicode_glyphs() else "x"
        output.note(f"this terminal is smaller than {MIN_WIDTH} {times} {MIN_HEIGHT}, so the list is numbered "
                    "instead of full-screen.")
        return None, None
    return CursesUi(scr, cur), undo
