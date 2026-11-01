"""Printer model -> camera stream kind. Models arrive as SSDP product codes (`BL-P001`, `C12`, `O1D`) or as
display names ("X1 Carbon", "P1S"); both are understood."""
from __future__ import annotations

import re

HLS = "hls"      # X1 series, H2 series, X2 series: RTSPS stream that a relay turns into HLS
MJPEG = "mjpeg"  # P1 and A1 series: JPEG frames over TLS port 6000

_HLS_CODES = {"bl-p001", "bl-p002", "c13", "o1d", "o1s", "o1c", "o1c2", "o2d"}
_MJPEG_CODES = {"c11", "c12", "n1", "n2s"}
_HLS_NAME = re.compile(r"\b(x1|h2|x2)", re.I)
_MJPEG_NAME = re.compile(r"\b(p1|a1)", re.I)


def camera_kind(model: str | None) -> str | None:
    """'hls', 'mjpeg', or None when the model is unknown."""
    m = (model or "").strip().lower().replace("3dprinter-", "").replace("_", " ").replace("-", " ")
    code = (model or "").strip().lower()
    if not m:
        return None
    if code in _HLS_CODES:
        return HLS
    if code in _MJPEG_CODES:
        return MJPEG
    if _HLS_NAME.search(m):
        return HLS
    if _MJPEG_NAME.search(m):
        return MJPEG
    return None
