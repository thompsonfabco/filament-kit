"""The catalogue of event kinds (ruling R80 section 2, docs/design 03).

A published contract from the first release that has it: kinds and value names are added, never renamed or removed
(the Home Assistant integration and `--json` readers rely on it; test_event_kinds.py pins every name). The catalogue
holds no texts: titles and sentences are built by each interface from the kind and the values (EA3).

A kind may carry a condition (R80 section 3): `raises` a lasting state, or `clears` one. The key of a condition is
its `base`, plus ":<subject id>" when the kind is `keyed` (print-paused:<printer id>, spool-low:<spool id>); the
`check` kinds take the row key instead of the subject id.
"""
from __future__ import annotations

from dataclasses import dataclass

SEVERITIES = ("info", "ok", "warn", "bad")
SUBJECT_TYPES = ("printer", "spool", "device", "location", "hub")
ACTOR_TYPES = ("hub", "device", "page", "cli", "connector")
RAISES, CLEARS = "raises", "clears"


@dataclass(frozen=True)
class Kind:
    name: str
    severities: tuple[str, ...]          # the allowed ones; the first is the default
    values: tuple[str, ...] = ()         # the names a `data` value may have (all optional)
    condition: str | None = None         # RAISES, CLEARS or None
    base: str | None = None              # the condition key's base
    keyed: bool = True                   # the condition key ends in ":<subject id>"
    emitted: bool = True                 # False = "Later": the name is reserved, nothing may write it yet

    @property
    def severity(self) -> str:
        return self.severities[0]


# What a person or the Hub changes about a spool: the spool, and the before and after of what changed.
_SPOOL_CHANGE = ("spool", "before_location", "after_location", "before_grams", "after_grams",
                 "before_slot", "after_slot")


def _kinds() -> dict[str, Kind]:
    out: dict[str, Kind] = {}

    def add(name, severities, values=(), condition=None, base=None, keyed=True, emitted=True):
        out[name] = Kind(name, (severities,) if isinstance(severities, str) else tuple(severities), tuple(values),
                         condition, base, keyed, emitted)

    add("print.started", "info", ("job", "printer"))
    add("print.paused", "warn", ("job", "percent", "reason", "stage"), RAISES, "print-paused")
    add("print.runout", "warn", ("job", "percent", "slot"), RAISES, "print-paused")
    add("print.resumed", "ok", ("job",), CLEARS, "print-paused")
    add("print.finished", "ok", ("job", "minutes"), CLEARS, "print-paused")
    add("print.failed", "bad", ("job", "percent", "reason", "error"), CLEARS, "print-paused")
    add("printer.error", "bad", ("code", "text"))
    add("printer.offline", "warn", (), RAISES, "printer-offline")
    add("printer.online", "ok", (), CLEARS, "printer-offline")
    add("usage.recorded", "info", ("printer", "job", "spool", "material", "grams"))
    add("spool.low", "warn", ("spool", "filament", "material", "grams", "in_stock"), RAISES, "spool-low")
    add("spool.ok", "ok", ("spool",), CLEARS, "spool-low")
    for name in ("added", "opened", "weighed", "moved", "emptied", "loaded", "unloaded"):
        add(f"spool.{name}", "info", _SPOOL_CHANGE)
    add("storage.low", ("warn", "bad"), ("free", "total", "percent"), RAISES, "storage-low", keyed=False)
    add("storage.ok", "ok", ("free", "total"), CLEARS, "storage-low", keyed=False)
    add("device.down", "warn", (), RAISES, "device-down")
    add("device.up", "ok", (), CLEARS, "device-down")
    add("check.failed", "warn", ("text",), RAISES, "check")
    add("check.ok", "ok", ("text",), CLEARS, "check")
    for name in ("hub.started", "hub.updated", "backup.finished", "backup.failed", "device.paired", "device.removed",
                 "settings.changed"):
        add(name, "info", emitted=False)           # Later (phase 4): the values are added when the phase emits it
    return out


KINDS: dict[str, Kind] = _kinds()


def get(name: str) -> Kind | None:
    return KINDS.get(name)


def condition_key(kind: Kind, subject_id: str = "", key: str | None = None) -> str | None:
    """The key of the condition a kind raises or clears, None for a moment. `key` (the check row's key) stands in
    for the subject id."""
    if kind.condition is None:
        return None
    if not kind.keyed:
        return kind.base
    return f"{kind.base}:{key if key is not None else subject_id}"
