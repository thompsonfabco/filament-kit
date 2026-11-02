"""Bambu printer models: the codes printers report (SSDP `DevModel.bambu.com`, MQTT `project_name`) and what
camera each has.

Codes from Bambu Studio `resources/printers/<model_id>.json` (`model_id`, `printer_type`, `display_name`).
X1/X1 Carbon report their `printer_type` ("3DPrinter-X1", "3DPrinter-X1-Carbon") over SSDP; the others report
the short code. Camera kinds follow ha-bambulab's CAMERA_RTSP / CAMERA_IMAGE feature sets: RTSPS on 322 for
X1/X1E/H2/X2/P2S, a JPEG stream on TCP 6000 for P1/A1/A2L.
"""
from __future__ import annotations

HLS = "hls"      # RTSPS stream that the relay turns into HLS
MJPEG = "mjpeg"  # JPEG frames over TLS port 6000

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
_BY_NAME: dict[str, str] = {}  # normalized name -> display name
for _code, (_name, _kind) in _MODELS.items():
    _BY_NAME.setdefault(_name.upper().replace(" ", ""), _name)
_BY_NAME.update({"X1C": "X1 Carbon", "X1CARBON": "X1 Carbon", "A1MINI": "A1 mini", "H2DPRO": "H2D Pro"})
_KIND_BY_NAME: dict[str, str] = {name: kind for name, kind in _MODELS.values()}

# chamber heating limit in °C by display name; X2D assumed H2D-like until checked; others have no heated chamber
_CHAMBER_MAX: dict[str, int] = {"H2D": 65, "H2D Pro": 65, "H2S": 65, "H2C": 65, "X2D": 65, "X1E": 60}


def _display_name(model: str | None) -> str | None:
    """The product display name for a reported code or a typed name, or None."""
    m = (model or "").strip().upper()
    if m in _MODELS:
        return _MODELS[m][0]
    m = m.removeprefix("BAMBU LAB").replace(" ", "").replace("-", "")
    return _BY_NAME.get(m)


def camera_kind(model: str | None) -> str | None:
    """"hls" (RTSPS camera, relayed as HLS), "mjpeg" (port-6000 JPEG stream) or None (unknown model; the app
    then offers no camera)."""
    name = _display_name(model)
    return _KIND_BY_NAME.get(name) if name else None


def printer_preset_name(model: str | None) -> str | None:
    """The Bambu Studio printer name ("Bambu Lab H2D", "Bambu Lab X1 Carbon") used in `compatible_printers`, or
    None for an unknown model."""
    name = _display_name(model)
    return f"Bambu Lab {name}" if name else None


def chamber_max(model: str | None) -> int | None:
    """Highest chamber temperature (°C) the printer can hold, or None when it has no heated chamber or is
    unknown."""
    name = _display_name(model)
    return _CHAMBER_MAX.get(name) if name else None
