"""Bambu printer models: the codes printers report (SSDP `DevModel.bambu.com`, MQTT `project_name`) and what
camera each has.

Codes from Bambu Studio `resources/printers/<model_id>.json` (`model_id`, `printer_type`, `display_name`).
X1/X1 Carbon report their `printer_type` ("3DPrinter-X1", "3DPrinter-X1-Carbon") over SSDP; the others report
the short code. Camera kinds follow ha-bambulab's CAMERA_RTSP / CAMERA_IMAGE feature sets: RTSPS on 322 for
X1/X1E/H2/X2/P2S, a JPEG stream on TCP 6000 for P1/A1/A2L.
"""
from __future__ import annotations

# code (upper case) -> (display name, camera kind)
_MODELS: dict[str, tuple[str, str]] = {
    "BL-P001": ("X1 Carbon", "hls"),
    "3DPRINTER-X1-CARBON": ("X1 Carbon", "hls"),
    "BL-P002": ("X1", "hls"),
    "3DPRINTER-X1": ("X1", "hls"),
    "C13": ("X1E", "hls"),
    "O1D": ("H2D", "hls"),
    "O1E": ("H2D Pro", "hls"),
    "O1S": ("H2S", "hls"),
    "O1C": ("H2C", "hls"),
    "O1C2": ("H2C", "hls"),
    "N6": ("X2D", "hls"),
    "N7": ("P2S", "hls"),
    "C11": ("P1P", "mjpeg"),
    "C12": ("P1S", "mjpeg"),
    "N1": ("A1 mini", "mjpeg"),
    "N2S": ("A1", "mjpeg"),
    "N9": ("A2L", "mjpeg"),
}

# product names typed by hand (`filament-kit config` → Printers), with or without "Bambu Lab "
_BY_NAME: dict[str, str] = {}
for _code, (_name, _kind) in _MODELS.items():
    _BY_NAME.setdefault(_name.upper().replace(" ", ""), _kind)
_BY_NAME.update({"X1C": "hls", "X1CARBON": "hls", "A1MINI": "mjpeg", "H2DPRO": "hls"})


def camera_kind(model: str) -> str | None:
    """"hls" (RTSPS camera, relayed as HLS), "mjpeg" (port-6000 JPEG stream) or None (unknown model)."""
    m = (model or "").strip().upper()
    if m in _MODELS:
        return _MODELS[m][1]
    m = m.removeprefix("BAMBU LAB").replace(" ", "").replace("-", "")
    return _BY_NAME.get(m)
