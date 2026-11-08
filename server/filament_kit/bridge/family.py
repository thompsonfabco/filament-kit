"""Printer families: one interface for Bambu and Klipper printers, and the dispatcher that routes by the registry.

`Printers(bambu, klipper)` is what `api.create_app(printers=...)` receives. Every call the API makes about one printer
(`state`, `summary`, `status`, `command`, `wait_settled`) goes to the family named by that printer's registry entry
(`registry.Printer.family`, default "bambu"); `sync`, `start` and `stop` reach both. Anything else (`wait_report`,
`set_slot`, `add_listener` ...) is the Bambu Manager's own: `loading`, `usage.Tracker`, `mapping` and `LayoutWatch`
keep receiving the real Bambu Manager, unchanged. A family whose module is off is `None`: its printers read as
`not_configured` and actions raise `ModuleOff`.

`PrinterFamily` is the interface a family offers the API (the Klipper family implements all of it; the Bambu
`Manager` covers the per-printer reads, and its loads, usage and mapping stay in `loading`, `usage` and `mapping`).
Klipper usage entries have ids starting with `KLIPPER_ENTRY` ("k-"): Moonraker recorded them, the kit cannot undo them.
"""
from __future__ import annotations

from typing import Protocol

from . import registry

KLIPPER_ENTRY = "k-"


class ModuleOff(Exception):
    """The printer's family module is switched off."""

    def __init__(self, family: str):
        super().__init__(f"the {family} module is off")
        self.family = family


class PrinterFamily(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def sync(self) -> None: ...
    def state(self, pid: str) -> str: ...
    def summary(self, pid: str) -> dict | None: ...
    def status(self, pid: str) -> dict | None: ...
    def command(self, pid: str, action: str) -> dict: ...
    def wait_settled(self, pid: str, timeout: float) -> str: ...
    def load(self, sm, pid: str, label: str, spool_id: int, dry: bool, *, sealed_location: str) -> dict: ...
    def unload(self, sm, pid: str, label: str, dry: bool, *, sealed_location: str) -> dict: ...
    def usage(self, pid: str, days: float) -> list[dict]: ...
    def camera_kind(self, pid: str) -> str | None: ...
    def camera_url(self, pid: str) -> str | None: ...
    def verified(self, pid: str) -> bool: ...


def is_klipper_entry(entry_id: str) -> bool:
    return isinstance(entry_id, str) and entry_id.startswith(KLIPPER_ENTRY)


class Printers:
    def __init__(self, bambu=None, klipper=None):
        self.bambu, self.klipper = bambu, klipper

    def family_of(self, pid: str) -> str:
        p = registry.load().get(pid)
        return p.family if p is not None and p.family in registry.FAMILIES else "bambu"

    def _of(self, pid: str):
        fam = self.family_of(pid)
        return fam, (self.klipper if fam == "klipper" else self.bambu)

    def state(self, pid: str) -> str:
        _, f = self._of(pid)
        return "not_configured" if f is None else f.state(pid)

    def summary(self, pid: str):
        _, f = self._of(pid)
        return None if f is None else f.summary(pid)

    def status(self, pid: str):
        _, f = self._of(pid)
        return None if f is None else f.status(pid)

    def command(self, pid: str, action: str) -> dict:
        fam, f = self._of(pid)
        if f is None:
            raise ModuleOff(fam)
        return f.command(pid, action)

    def wait_settled(self, pid: str, timeout: float) -> str:
        fam, f = self._of(pid)
        return "not_configured" if f is None else f.wait_settled(pid, timeout)

    def _each(self, name: str) -> None:
        for f in (self.bambu, self.klipper):
            if f is not None and hasattr(f, name):
                getattr(f, name)()

    def sync(self) -> None:
        self._each("sync")

    def start(self) -> None:
        self._each("start")

    def stop(self) -> None:
        self._each("stop")

    def __getattr__(self, name: str):
        # only reached for names this class does not define: the Bambu Manager's own API
        bambu = self.__dict__.get("bambu")
        if bambu is None:
            raise AttributeError(name)
        return getattr(bambu, name)


class NotSupported(Exception):
    """The action exists for another printer family only (slot mapping is Bambu's)."""


class RecordedByMoonraker(Exception):
    """A Klipper usage entry: Moonraker deducted it in Spoolman; the kit cannot undo it."""
