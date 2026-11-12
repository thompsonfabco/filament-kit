"""Publish a printer's slots to Moonraker's `lane_data` database namespace (multi-tool Spool Sync, spec §6).

OrcaSlicer's "Sync filaments" and the kit's Spool Sync plugin read `lane_data` (`laneN = {lane: "<tool index>",
material, color, nozzle_temp, bed_temp, ...}`). The kit writes it after a confirmed load, an unload or a follow
change, only the lanes that changed. Per printer (`registry.Printer.lane_data`): `auto` = the adapter's default (on
for toolchangers, off for single extruders), `on`, `off`. Never for AFC or lane_data printers: AFC owns the namespace.
Writing lane_data is a write to the printer.
"""
from __future__ import annotations

NAMESPACE = "lane_data"
NEVER = ("afc", "lanedata")
SOURCE = "filament-kit"      # every lane the kit writes says so: its own lane_data is not a lane_data printer


def kit_written(db) -> bool:
    """The lane_data namespace holds only lanes the kit published (so detection must not pick the lanedata adapter
    for the printer the kit publishes them for)."""
    lanes_ = [v for v in (db or {}).values() if isinstance(v, dict)]
    return bool(lanes_) and all(v.get("source") == SOURCE for v in lanes_)


def should_publish(printer, adapter) -> bool:
    if adapter.name in NEVER:
        return False
    mode = getattr(printer, "lane_data", "auto")
    if mode == "off":
        return False
    if mode == "on":
        return True
    return bool(adapter.publishes_lane_data)


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def payload(units, spools_by_id: dict, presets: dict) -> dict[str, dict]:
    out, n = {}, 0
    for u in units:
        for s in u.slots:
            sp = spools_by_id.get(s.spool_id) if s.spool_id is not None else None
            f = (sp or {}).get("filament") or {}
            hexv = str(f.get("color_hex") or "").strip().lstrip("#")[:6]
            out[f"lane{n}"] = {
                "lane": str(n), "material": str(f.get("material") or ""), "color": f"#{hexv.upper()}" if hexv else "",
                "nozzle_temp": _int(f.get("settings_extruder_temp")), "bed_temp": _int(f.get("settings_bed_temp")),
                "spool_id": s.spool_id if sp else None, "vendor": str((f.get("vendor") or {}).get("name") or ""),
                "name": str(f.get("name") or ""), "preset": presets.get(s.label), "source": SOURCE}
            n += 1
    return out


def publish(client, pl: dict, last: dict) -> list[str]:
    """Post the lanes whose value changed since `last` (updated in place); returns the keys written."""
    wrote = []
    for key, value in pl.items():
        if last.get(key) == value:
            continue
        client.db_post(NAMESPACE, key, value)
        last[key] = value
        wrote.append(key)
    return wrote


def retract(client, pl: dict, last: dict, db: dict | None = None) -> list[str]:
    """Delete the kit's own lanes that `pl` no longer holds (a unit lost slots; `pl` empty = publishing is off):
    those it wrote this run (`last`, updated in place) and, when `db` (the namespace as read) is given, those it wrote
    earlier. A lane without the kit's source is never touched. Returns the keys deleted."""
    mine = set(last) | {k for k, v in (db or {}).items() if isinstance(v, dict) and v.get("source") == SOURCE}
    gone = sorted(k for k in mine if k not in pl)
    for key in gone:
        client.db_delete(NAMESPACE, key)
        last.pop(key, None)
    return gone
