"""How the command line writes: one status vocabulary, glyphs and colour, tables that fit the width, results on
standard output, errors on standard error as `Error:` with a `Fix:` line, a progress line for every wait, the exit
codes (docs/design/06-command-line.md 6.1 to 6.7; 07-accessibility.md CLI-1 to CLI-10).

Every command writes through here. The choices (colour, plain, glyph set, width) are read when they are needed, from
the environment and from what `configure` was given, so a test that sets `NO_COLOR` or `COLUMNS` sees it at once.

    configure(color=, plain=, no_progress=)   what `--color`, `--plain` and `--no-progress` said (main reads them)
    out(text) / result(text)                  a line on standard output, wrapped at the width
    note(text) / error(what, fix=, cmd=)      standard error: `Note: ...`, `Error: ...` and its `Fix: ...` line
    need_sudo(cmd) -> 3                       the error of a command that needs root, and its exit code
    state(word) -> str                        a status word with its glyph and colour (`● OK`)
    status_row(word, text, fix) -> [str]      the lines of one status row (06 9.1)
    table(headers, rows, long=, right=)       a table as lines (06 6.3)
    wrap(text, indent=, first=) -> [str]      running text at the width
    wait(text)                                a progress line once 2 seconds pass with no other output (06 6.6);
                                              `paused()` holds it while the command asks a question
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import threading
import time

# 06 6.7
SUCCESS, FAILED, USAGE, NEEDS_SUDO, HUB_DOWN, CANCELLED, INTERRUPTED = 0, 1, 2, 3, 4, 5, 130

PROGRESS_AFTER = 2.0        # seconds without other output before a progress line shows
PLAIN_EVERY = 10.0          # --plain: one more whole line this often
STOP_HINT_AFTER = 5         # at a terminal the line adds "(Ctrl-C stops)" after this many seconds
STATE_WORD_WIDTH = 12       # 06 9.1: the state word is padded to this

_switches = {"color": "auto", "plain": False, "no_progress": False}


def configure(*, color: str | None = None, plain: bool | None = None, no_progress: bool | None = None) -> None:
    """What `--color always|never|auto`, `--plain` and `--no-progress` said for this run (None: unchanged)."""
    if color is not None:
        _switches["color"] = color
    if plain is not None:
        _switches["plain"] = plain
    if no_progress is not None:
        _switches["no_progress"] = no_progress


def reset() -> None:
    _switches.update(color="auto", plain=False, no_progress=False)


def extract_switches(argv: list[str]) -> tuple[list[str], dict]:
    """`argv` without `--color X`, `--color=X`, `--plain` and `--no-progress`, which every command accepts in any
    place before a bare `--`; and what they said, as `configure` takes it."""
    rest, got, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            rest += argv[i:]
            break
        if a == "--plain":
            got["plain"] = True
        elif a == "--no-progress":
            got["no_progress"] = True
        elif a == "--color" and i + 1 < len(argv):
            got["color"] = argv[i + 1]
            i += 1
        elif a.startswith("--color="):
            got["color"] = a.partition("=")[2]
        else:
            rest.append(a)
        i += 1
    return rest, got


def plain() -> bool:
    """The screen-reader mode: `--plain`, `SPOOLWARDEN_PLAIN=1`, or `TERM=dumb`."""
    return bool(_switches["plain"]) or os.environ.get("SPOOLWARDEN_PLAIN") == "1" or os.environ.get("TERM") == "dumb"


# ---------- glyphs and symbols (06 6.1, 6.2) ----------

# meaning -> (Unicode, ASCII, colour token)
_GLYPHS = {"good": ("●", "+", "ok"), "off": ("○", "o", "muted"), "offline": ("○", "o", "bad"),
           "look": ("▲", "!", "warn"), "error": ("×", "x", "bad"), "working": ("◐", "~", "accent"),
           "note": ("◆", "*", "info")}
_WORDS = {
    "good": ("OK", "connected", "on", "set", "done", "high", "confirmed"),
    "off": ("off", "not set", "not set up", "found, not added", "skipped", "not on label", "unknown"),
    "offline": ("offline",),
    "look": ("needs a look", "medium", "wrong Access Code", "certificate changed", "stopped without finishing"),
    "error": ("error", "failed", "low: check this"),
    "working": ("working",),
    "note": ("note", "entered by hand"),
}
MEANING = {w: m for m, ws in _WORDS.items() for w in ws}
_SGR = {"ok": 32, "warn": 33, "bad": 31, "info": 34, "accent": 36, "muted": 2, "bold": 1}
_SYMBOLS = {"arrow": ("→", "->"), "sep": (" · ", " - "), "ellipsis": ("…", "..."), "degree": (" °C", " C")}


def _utf8_locale() -> bool:
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        v = os.environ.get(var)
        if v:
            return bool(re.search(r"utf-?8", v, re.I))
    return False


def unicode_glyphs() -> bool:
    """The Unicode set when the locale's character set is UTF-8 (LC_ALL, then LC_CTYPE, then LANG), else ASCII;
    `SPOOLWARDEN_GLYPHS=unicode|ascii` decides when set. Plain mode is always ASCII."""
    if plain():
        return False
    want = os.environ.get("SPOOLWARDEN_GLYPHS", "").lower()
    if want in ("unicode", "ascii"):
        return want == "unicode"
    return _utf8_locale()


def sym(name: str) -> str:
    """`arrow`, `sep`, `ellipsis` or `degree` in the glyph set in use."""
    return _SYMBOLS[name][0 if unicode_glyphs() else 1]


# ---------- colour (06 6.2) ----------

def _is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def colour_on(stream) -> bool:
    """Decided for each stream, first rule that applies: `--color always|never`; `NO_COLOR` not empty; `TERM` dumb or
    unset; a terminal."""
    if plain():
        return False
    mode = _switches["color"]
    if mode in ("always", "never"):
        return mode == "always"
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "dumb") == "dumb":
        return False
    return _is_tty(stream)


def paint(text: str, token: str, stream) -> str:
    """`text` in the colour of `token` (ok, warn, bad, info, accent, muted, bold), reset before the line ends."""
    if not text or not colour_on(stream):
        return text
    return f"\x1b[{_SGR[token]}m{text}\x1b[0m"


def state(word: str, stream=None) -> str:
    """A status word with its glyph and colour (`● OK`); the word alone in plain mode. A word the vocabulary does
    not have is returned as it is."""
    stream = stream or sys.stdout
    kind = MEANING.get(word)
    if kind is None:
        return word
    uni, asc, token = _GLYPHS[kind]
    if plain():
        return word
    return paint(f"{uni if unicode_glyphs() else asc} {word}", token, stream)


# ---------- width, wrapping, tables (06 6.3) ----------

def width() -> int:
    """The terminal's width (`COLUMNS`, then the terminal size), 80 when unknown. A line is one less at most."""
    try:
        n = shutil.get_terminal_size((80, 24)).columns
    except (ValueError, OSError):
        n = 80
    return max(n, 20)


def _visible(s: str) -> int:
    return len(re.sub(r"\x1b\[[0-9;]*m", "", s))


_HELD = "\x00"        # a space that wrap does not break at (a fix that is a command); it goes back to a space


def _words(para: str) -> list[str]:
    """`para` split at its spaces, except those inside a `backtick span`: a command stays whole on a line."""
    words, cur, inside = [], "", False
    for ch in para:
        if ch == "`":
            inside = not inside
        if ch == " " and not inside:
            words.append(cur)
            cur = ""
        else:
            cur += ch
    return words + [cur]


def wrap(text: str, *, indent: int = 0, first: int | None = None) -> list[str]:
    """`text` as lines of at most width - 1 characters, wrapped at spaces outside backtick spans. The first line starts
    at column `first` (default `indent`), the others at `indent`, so a continuation lines up with where the text began.
    Newlines in `text` start a new line. A word, number, address, path or backtick span longer than a line stays whole
    on a line of its own (06 6.3): a command or address cut in two cannot be copied."""
    limit = width() - 1
    first = indent if first is None else first
    lines: list[str] = []
    for para in text.split("\n"):
        lead = len(para) - len(para.lstrip(" "))          # spaces a line starts with stay, and carry to its wrap
        para = para[lead:]
        cur, col = "", (first if not lines else indent) + lead
        for word in _words(para):
            if cur and col + len(cur) + 1 + len(word) > limit:
                lines.append(" " * col + cur)
                cur, col = "", indent + lead
            cur = f"{cur} {word}" if cur else word
        lines.append(" " * col + cur)
    return [x.replace(_HELD, " ") for x in lines]


def table(headers: list[str], rows: list[list], *, long: int = 0, right: tuple[int, ...] = (), whole: bool = False,
          stream=None) -> list[str]:
    """A table as lines. Header in upper case (bold with colour), columns two spaces apart, text left, numbers right
    (`right` lists those columns), the `long` column taking the spare room. At a terminal narrower than 60 columns and
    always in plain mode it is blocks: a `Label: value` line per field, a blank line between rows. At a terminal the
    long column is cut with an ellipsis when the line would be too long, unless `whole` (it holds what the person types
    next, a file name): then the table is blocks instead of cutting it. Not at a terminal nothing is cut."""
    stream = stream or sys.stdout
    head = [h.upper() for h in headers]
    cols = [max([len(head[i])] + [len(str(r[i])) for r in rows]) for i in range(len(head))]
    too_wide = _is_tty(stream) and sum(cols) + 2 * (len(cols) - 1) > width() - 1
    if plain() or (_is_tty(stream) and width() < 60) or (whole and too_wide):
        lines: list[str] = []
        for r in rows:
            lines += ([""] if lines else []) + [f"{h}: {v}" for h, v in zip(headers, r)]
        return lines
    cut = _is_tty(stream)
    if cut:
        spare = (width() - 1) - (sum(cols) + 2 * (len(cols) - 1))
        if spare < 0:
            cols[long] = max(len(head[long]), cols[long] + spare)
    ell = sym("ellipsis")

    def cell(i: int, v) -> str:
        v = str(v)
        if cut and len(v) > cols[i]:
            v = v[:max(0, cols[i] - len(ell))] + ell
        return v.rjust(cols[i]) if i in right else v.ljust(cols[i])

    lines = [paint("  ".join(cell(i, h) for i, h in enumerate(head)).rstrip(), "bold", stream)]
    return lines + ["  ".join(cell(i, v) for i, v in enumerate(r)).rstrip() for r in rows]


# ---------- writing (06 6.5) ----------

_lock = threading.RLock()
_waits: list["wait"] = []
_midline = [False]          # the last text written to the terminal did not end its line: no progress line yet


def _other_output() -> None:
    with _lock:
        for w in _waits:
            w._other_output()


class _Guard:
    """Stands in for standard output and error while a wait is on, so that anything written to them, a plain `print`
    of the code that waits included, first takes the progress line off and starts the 2 seconds again."""

    def __init__(self, real):
        self.real = real

    def write(self, text):
        with _lock:
            if text:
                _other_output()
            n = self.real.write(text)
            if text:
                _midline[0] = not text.endswith("\n")
            return n

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    @property
    def buffer(self):
        """The byte stream under the text one: written to, it takes the line off like `write` (no buffer, no attribute)."""
        return _GuardBytes(self.real.buffer)

    def __getattr__(self, name):
        return getattr(self.real, name)


class _GuardBytes:
    """The `.buffer` of a guarded stream: a write of bytes first takes the progress line off, like the text one."""

    def __init__(self, real):
        self.real = real

    def write(self, data):
        with _lock:
            if data:
                _other_output()
            n = self.real.write(data)
            if data:
                _midline[0] = not bytes(data).endswith(b"\n")
            return n

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        return getattr(self.real, name)


def _raw(stream):
    return stream.real if isinstance(stream, _Guard) else stream


def _guard_streams() -> None:
    for name in ("stdout", "stderr"):
        if not isinstance(getattr(sys, name), _Guard):
            setattr(sys, name, _Guard(getattr(sys, name)))


def _unguard_streams() -> None:
    for name in ("stdout", "stderr"):
        if isinstance(getattr(sys, name), _Guard):
            setattr(sys, name, _raw(getattr(sys, name)))
    _midline[0] = False


def _write(stream, lines: list[str]) -> None:
    with _lock:
        _other_output()
        stream.write("".join(line + "\n" for line in lines))
        stream.flush()


def out(text: str = "") -> None:
    """A line on standard output; running text wraps at the width."""
    _write(sys.stdout, wrap(text))


def out_lines(lines: list[str]) -> None:
    """Lines that are already laid out (rows, tables), written to standard output as they are."""
    _write(sys.stdout, lines)


result = out        # a result is one line in the past tense on standard output (06 6.5)


def note(text: str) -> None:
    """A note that is not a result: on standard error, `Note: ` first."""
    _write(sys.stderr, wrap("Note: " + text, indent=6, first=0))


def error(what: str, fix: str | None = None, *, cmd: str | None = None) -> None:
    """`Error: <what>` on standard error and, when something can be done about it, `Fix: <fix>`. `cmd`, the exact
    command that does it, goes on its own line, indented five spaces, so it can be copied whole. A `what` that holds
    its own second line `fix: ...` (the texts the module code returns) is split there."""
    if fix is None and "\nfix: " in what:
        what, _, fix = what.partition("\nfix: ")
    lines = wrap("Error: " + what, indent=7, first=0)
    lines[0] = paint("Error:", "bad", sys.stderr) + lines[0][6:]
    if fix:
        lines += wrap("Fix: " + fix, indent=5, first=0)
    if cmd:
        lines.append(" " * 5 + cmd if fix else "Fix: " + cmd)
    _write(sys.stderr, lines)


def need_sudo(cmd: str) -> int:
    """The error of a command that needs root, with the full command to run; the exit code to return (3)."""
    error("this needs administrator rights.", "run it with sudo:", cmd=cmd)
    return NEEDS_SUDO


# ---------- status rows (06 9.1) ----------

def status_row(word: str, text: str, fix: str = "", stream=None) -> list[str]:
    """The lines of one row: two spaces, the glyph, the state word padded to 12, two spaces, the text. A word
    longer than 12 is not cut: on that row alone the text starts two spaces after it. `Fix:` and detail lines (an
    empty `word`) stay at the usual column. Plain mode: the word alone, no glyph (CLI-2), the text two spaces after it."""
    stream = stream or sys.stdout
    if plain():
        col = 2
        lead = word + "  " if word else "  "
        start = len(lead)
    else:
        col = 2 + 2 + STATE_WORD_WIDTH + 2
        if word:
            shown = 4 + len(word)                         # two spaces, the glyph and its space, the word
            lead = "  " + state(word, stream)
            start = max(col, shown + 2)
            lead += " " * (start - shown)
        else:
            lead, start = " " * col, col
    body = wrap(text, indent=col if not plain() else start, first=start)
    lines = [lead + body[0][start:]] + body[1:]
    if fix:
        indent = col if not plain() else start
        if fix.startswith("sudo "):                       # a fix that is a command is never cut (06 6.3)
            fix = fix.replace(" ", _HELD)
        lines += wrap("Fix: " + fix, indent=indent + 5, first=indent)
    return lines


# ---------- waits (06 6.6) ----------

class wait:
    """`with output.wait("Checking…"):` shows `◐ Checking… 3 s` on standard error once 2 seconds pass with no other
    output: at a terminal rewritten in place each second, with `(Ctrl-C stops)` after 5. Not at a terminal, or with
    `--no-progress`, one whole line, once. A wait that runs other programs (`programs=True`: their output goes straight
    to the terminal, past the guard below) never draws in place either: one whole line, as when piped. In plain mode the line has no glyph and comes
    again every 10 seconds with the time so far. `step(k, n)` adds `step k of n` in place of the seconds. Never on standard output.

    While it is on, standard output and error are guarded: any write, from anywhere, takes the line off first and
    restarts the 2 seconds, and the line is never drawn after text that has not ended its line. A command that asks a
    question does it inside `with t.paused():`, so its wait begins after the answer."""

    def __init__(self, text: str, *, steps: tuple[int, int] | None = None, programs: bool = False):
        self.text = text
        self.steps = steps
        self.programs = programs
        self._stop = threading.Event()
        self._started = self._since = time.monotonic()
        self._printed = False           # a line is on the screen (in place) or was written (once)
        self._inplace = False
        self._held = False
        self._cols = 0
        self._thread: threading.Thread | None = None

    def step(self, k: int, n: int, text: str | None = None) -> None:
        with _lock:
            self.steps = (k, n)
            self.text = text or self.text

    def __enter__(self):
        with _lock:
            _guard_streams()
            _waits.append(self)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        with _lock:
            self._erase()
            if self in _waits:
                _waits.remove(self)
            if not _waits:
                _unguard_streams()
        return False

    @contextlib.contextmanager
    def paused(self):
        """A question is asked inside this: no progress line meanwhile, and the wait counts from the answer."""
        with _lock:
            self._held = True
            self._erase()
        try:
            yield
        finally:
            with _lock:
                self._held = False
                self._since = self._started = time.monotonic()

    def _erase(self) -> None:
        if self._inplace and self._printed:
            err = _raw(sys.stderr)
            err.write("\r" + " " * self._cols + "\r")
            err.flush()
            self._printed = False

    def _other_output(self) -> None:
        self._erase()
        self._since = time.monotonic()

    def _line(self, seconds: int | None) -> str:
        s = self.text.rstrip().replace("…", "…" if unicode_glyphs() else "...")
        tail = ""
        if self.steps:
            tail = f" step {self.steps[0]} of {self.steps[1]}"
        elif seconds is not None:
            tail = f" {seconds} s"
        if seconds is not None and self._inplace and seconds >= STOP_HINT_AFTER:
            tail += " (Ctrl-C stops)"
        if self._inplace:                  # rewritten in place: one line at most, or the \r cannot take it off
            room = width() - 1 - (0 if plain() else 2)
            if len(s) + len(tail) > room:
                ell = sym("ellipsis")
                s = s[:max(0, room - len(tail) - len(ell))] + ell
                tail = tail[:max(0, room - len(s))]
        s += tail
        if plain():
            return s
        return paint(f"{_GLYPHS['working'][0 if unicode_glyphs() else 1]} {s}", "accent", sys.stderr)

    def _run(self) -> None:
        last_plain = None
        while not self._stop.wait(0.1):
            pause = False
            with _lock:
                err, now = _raw(sys.stderr), time.monotonic()
                if self._held or _midline[0] or now - self._since < PROGRESS_AFTER:
                    continue
                if _switches["no_progress"] or (not plain() and (self.programs or not _is_tty(err))):
                    if not self._printed:                      # once, whole, without the counter
                        err.write(self._line(None) + "\n")
                        err.flush()
                        self._printed = True
                elif plain():
                    if last_plain is None or now - last_plain >= PLAIN_EVERY:
                        err.write(self._line(None if last_plain is None else int(now - self._started)) + "\n")
                        err.flush()
                        last_plain = now
                else:
                    self._inplace = True
                    text = self._line(int(now - self._started))
                    self._cols = max(self._cols, _visible(text))
                    err.write("\r" + text + " " * (self._cols - _visible(text)))
                    err.flush()
                    self._printed = True
                    pause = True
            if pause and self._stop.wait(0.9):
                return
