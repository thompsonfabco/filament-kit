"""QR codes drawn by the Hub itself (segno, vendored in _vendor/, so nothing has to be installed): an SVG image for
the Hub page and the web app reply, and block-character text for the command line. Level L, as qrencode drew them."""
import io

from . import _vendor  # noqa: F401  (puts the vendored folder on the import path)

import segno  # noqa: E402

QUIET = 4          # modules of quiet zone on every side: what QR readers expect


def _code(payload: str):
    return segno.make(payload, encoding="utf-8", error="L", boost_error=False, micro=False)


def svg(payload: str) -> str | None:
    """The link as an SVG QR code (dark on a white quiet zone), or None when it does not fit one."""
    try:
        buf = io.BytesIO()
        _code(payload).save(buf, kind="svg", scale=4, border=QUIET, dark="#000", light="#fff")
    except (segno.DataOverflowError, ValueError):
        return None
    return buf.getvalue().decode("utf-8")


def text(payload: str) -> str | None:
    """The link as terminal text: two modules per character row (half blocks), black on white, with the quiet zone;
    None when it does not fit one."""
    try:
        rows = [[bool(m & 1) for m in r] for r in _code(payload).matrix_iter(border=QUIET)]
    except (segno.DataOverflowError, ValueError):
        return None
    if len(rows) % 2:
        rows.append([False] * len(rows[0]))
    glyph = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
    # explicit colours (black on white), so a dark terminal theme does not invert the code
    return "".join("\x1b[30;47m" + "".join(glyph[(a, b)] for a, b in zip(top, bottom)) + "\x1b[0m\n"
                   for top, bottom in zip(rows[0::2], rows[1::2]))
