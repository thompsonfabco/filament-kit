"""Bambu printer models: the codes printers report (SSDP `DevModel.bambu.com`, MQTT `project_name`) and what
camera each has.

Thin readers of `bambu_hardware.xml` (see `hardware.py`, which documents `ModelInfo`). Codes come from Bambu Studio
`resources/printers/<model_id>.json`; X1/X1 Carbon report their `printer_type` ("3DPrinter-X1",
"3DPrinter-X1-Carbon") over SSDP, the others the short code. Hand-typed names (`filament-kit config` → Printers)
work too, with or without "Bambu Lab ".
"""
from __future__ import annotations

from . import hardware
from .hardware import ModelInfo

HLS = "hls"      # RTSPS stream that the relay turns into HLS
MJPEG = "mjpeg"  # JPEG frames over TLS port 6000


def model(code: str | None) -> ModelInfo:
    """The model record for a reported code or a typed name; the generic record (`known=False`) when unknown."""
    return hardware.load().model(code)


def _known(code: str | None) -> ModelInfo | None:
    m = model(code)
    return m if m.known else None


def camera_kind(model: str | None) -> str | None:
    """"hls" (RTSPS camera, relayed as HLS), "mjpeg" (port-6000 JPEG stream) or None (unknown model; the app
    then offers no camera)."""
    m = _known(model)
    return m.camera if m else None


def printer_preset_name(model: str | None) -> str | None:
    """The Bambu Studio printer name ("Bambu Lab H2D", "Bambu Lab X1 Carbon") used in `compatible_printers`, or
    None for an unknown model."""
    m = _known(model)
    return m.preset_name if m else None


def chamber_max(model: str | None) -> int | None:
    """Highest chamber temperature (°C) the printer can hold, or None when it has no heated chamber or is
    unknown."""
    m = _known(model)
    return m.chamber_max if m else None
