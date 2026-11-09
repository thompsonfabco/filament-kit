"""Secret prompts (Access Code, Anthropic key, web passphrase, tokens): one `*` per character typed, Backspace works.

At a terminal the line is read key by key with echo off (termios on Linux, msvcrt on Windows); the secret itself is
never echoed, printed or logged. Without a terminal (a pipe, a test) it falls back to getpass.getpass.
"""
from __future__ import annotations

import codecs
import getpass
import os
import sys

_ENTER = ("\r", "\n")
_BACKSPACE = ("\x7f", "\b")
_KILL = "\x15"          # Ctrl-U: clear the line
_EOF = "\x04"           # Ctrl-D
_INTR = "\x03"          # Ctrl-C (Windows: msvcrt hands it over as a character)
_ESC = "\x1b"


class Line:
    """The line being typed. `key(ch)` takes one character and returns what to echo for it; `done` is set by
    Enter (or Ctrl-D). Control characters other than the editing keys are ignored."""

    def __init__(self):
        self.chars: list[str] = []
        self.done = False

    def key(self, ch: str) -> str:
        if ch in _ENTER or (ch == _EOF):
            self.done = True
            return "\n"
        if ch == _INTR:
            raise KeyboardInterrupt
        if ch in _BACKSPACE:
            if self.chars:
                self.chars.pop()
                return "\b \b"
            return ""
        if ch == _KILL:
            n, self.chars = len(self.chars), []
            return "\b \b" * n
        if ch < " ":
            return ""
        self.chars.append(ch)
        return "*"

    @property
    def text(self) -> str:
        return "".join(self.chars)


def _isatty(stream) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def _out():
    """Where the prompt and the stars go: the terminal (stdout, or stderr when stdout is captured)."""
    return sys.stdout if _isatty(sys.stdout) else sys.stderr


def _posix(prompt: str, fd: int) -> str:
    import select
    import termios
    out = _out()
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    # no echo, no line editing by the terminal; ISIG stays on, so Ctrl-C still interrupts
    new[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN)
    new[6][termios.VMIN], new[6][termios.VTIME] = 1, 0
    line = Line()
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)    # drops what was typed so far: before the prompt, not after it
        out.write(prompt)
        out.flush()
        while not line.done:
            b = os.read(fd, 1)
            if not b:                      # the terminal went away
                break
            ch = dec.decode(b)
            if not ch:
                continue                   # the middle of a UTF-8 character
            if ch == _ESC:                 # a cursor or function key: skip its escape sequence
                while select.select([fd], [], [], 0.05)[0]:
                    c = os.read(fd, 1)
                    if not c or (0x40 <= c[0] <= 0x7E and c not in (b"[", b"O")):
                        break
                continue
            out.write(line.key(ch))
            out.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, old)
        if not line.done:
            out.write("\n")
            out.flush()
    return line.text


def _windows(prompt: str) -> str:
    import msvcrt
    out = _out()
    out.write(prompt)
    out.flush()
    line = Line()
    while not line.done:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):        # a cursor or function key: its second half follows
            msvcrt.getwch()
            continue
        out.write(line.key(ch))
        out.flush()
    return line.text


def ask(prompt: str) -> str:
    """Read a secret, echoing `*` per character. Returns it without the line end (getpass behaviour)."""
    stdin = sys.stdin
    if _isatty(stdin):
        try:
            fd = stdin.fileno()
        except (AttributeError, ValueError, OSError):
            fd = None
        if fd is not None:
            if os.name == "nt":
                return _windows(prompt)
            try:
                import termios  # noqa: F401
            except ImportError:
                pass
            else:
                return _posix(prompt, fd)
    return getpass.getpass(prompt)
