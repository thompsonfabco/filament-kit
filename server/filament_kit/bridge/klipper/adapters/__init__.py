"""Filament-system adapters by the `adapter` name klipper_hardware.xml gives a `<system>`."""
from __future__ import annotations

from .afc import Afc
from .base import Adapter
from .happyhare import HappyHare
from .lanedata import LaneData
from .single import Single
from .toolchanger import Toolchanger

_ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Single(), Toolchanger(), Afc(), HappyHare(), LaneData())}


def get(name: str) -> Adapter:
    return _ADAPTERS[name]
