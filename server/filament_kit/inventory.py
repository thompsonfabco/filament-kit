"""Inventory writes: add spools, link NFC tags, update weights/locations, search."""
from __future__ import annotations

import datetime
import json
import threading
from dataclasses import dataclass, field

from . import placement, tags
from .spoolman import Spoolman, SpoolmanError

SEALED_COMMENT = "SEALED - tag when opened"

_LOCK = threading.Lock()  # serializes add + placement so two adds never pick the same box

_REQUIRED = ("vendor", "name", "material", "net", "tare", "density", "count")


@dataclass
class AddResult:
    spool_ids: list[int] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    dry: bool = False


@dataclass
class LinkResult:
    spool_id: int
    uid: str
    noop: bool = False
    dry: bool = False
    cleared: list[int] = field(default_factory=list)
    patch: dict = field(default_factory=dict)


class TagConflict(Exception):
    def __init__(self, other: dict, message: str | None = None):
        self.other = other
        super().__init__(message or f"tag is already linked to {describe(other)}")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(s: dict) -> str:
    f = s.get("filament") or {}
    return (f"spool {s['id']} {(f.get('vendor') or {}).get('name', '?')} {f.get('name', '?')} "
            f"@ {s.get('location')} ({s.get('remaining_weight')} g)")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate(items: list[dict]) -> None:
    if not isinstance(items, list) or not items:
        raise ValueError("no items to add")
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("each item must be an object")
        label = f"{it.get('vendor')} {it.get('name')}"
        for k in _REQUIRED:
            if it.get(k) in (None, ""):
                raise ValueError(f"{label}: missing {k}")
        if not _is_int(it["count"]) or it["count"] < 1:
            raise ValueError(f"{label}: count must be a whole number of at least 1")
        for k in ("net", "tare", "density"):
            if not _is_num(it[k]) or it[k] <= 0:
                raise ValueError(f"{label}: {k} must be a positive number")
        if it.get("gross") is not None:
            if not _is_num(it["gross"]) or it["count"] != 1 or it["gross"] <= it["tare"]:
                raise ValueError(f"{label}: gross {it['gross']} g needs count 1 and a weight above the spool")


def _used_locations(sm: Spoolman) -> set[str]:
    return {s["location"] for s in sm.get("spool") if s.get("location")}


def add_spools(sm: Spoolman, items: list[dict], rules: dict, dry: bool) -> AddResult:
    _validate(items)
    result = AddResult(dry=dry)
    with _LOCK:
        placed = placement.place(items, _used_locations(sm), rules)
        vendors = {v["name"].lower(): v for v in sm.get("vendor")}
        fils = {((f.get("vendor") or {}).get("name", "").lower(), f["name"].lower()): f for f in sm.get("filament")}
        for it in placed:
            vn = it["vendor"]
            v = vendors.get(vn.lower())
            if v is None:
                v = ({"id": None, "name": vn} if dry
                     else sm.post("vendor", {"name": vn, "empty_spool_weight": it["tare"]}))
                vendors[vn.lower()] = v
                result.lines.append(f"new vendor {vn}")
            key = (vn.lower(), it["name"].lower())
            f = fils.get(key)
            if f is None:
                f = _new_filament(sm, it, v, dry)
                fils[key] = f
                state = "new filament"
            else:
                state = "existing filament"
            tare = f.get("spool_weight") or it["tare"]
            remaining = round(it["gross"] - tare, 1) if it.get("gross") is not None else it["net"]
            opened = it.get("sealed") is False
            comment = " | ".join(x for x in (SEALED_COMMENT if not opened else "", it.get("spool_note")) if x)
            ids: list[int | None] = []
            for _ in range(it["count"]):
                body = {"filament_id": f["id"], "initial_weight": it["net"], "spool_weight": tare,
                        "remaining_weight": remaining, "location": it["location"], "comment": comment}
                if it.get("lot"):
                    body["lot_nr"] = it["lot"]
                if dry:
                    ids.append(None)
                    continue
                sid = sm.post("spool", body)["id"]
                _read_back(sm, sid)
                ids.append(sid)
                result.spool_ids.append(sid)
            gross_note = f" (gross {it['gross']} - tare {tare})" if it.get("gross") is not None else ""
            result.lines.append(
                f"F{f['id']} {vn} {it['name']} ({state}): {it['count']} spool(s) {ids} @ {it['location']}"
                f"{' (opened)' if opened else ''}, {remaining} g{gross_note}")
    return result


def _new_filament(sm: Spoolman, it: dict, vendor: dict, dry: bool) -> dict:
    extra = {k: json.dumps(it[k]) for k in ("nozzle_range", "bed_range") if it.get(k)}
    note = it.get("note") or ""
    if it.get("price_line"):
        note = (note + " | " if note else "") + it["price_line"]
    body = {"name": it["name"], "vendor_id": vendor["id"], "material": it["material"], "density": it["density"],
            "diameter": 1.75, "weight": it["net"], "spool_weight": it["tare"], "comment": note, "extra": extra}
    for src, dst in (("color_hex", "color_hex"), ("nozzle", "settings_extruder_temp"),
                     ("bed", "settings_bed_temp")):
        if it.get(src):
            body[dst] = it[src]
    if it.get("price_per_kg"):
        body["price"] = round(it["price_per_kg"] * it["net"] / 1000, 2)
    return {"id": None, **body} if dry else sm.post("filament", body)


def _read_back(sm: Spoolman, sid: int) -> dict:
    try:
        s = sm.get(f"spool/{sid}")
    except SpoolmanError as e:
        raise RuntimeError(f"spool {sid} was not found after writing it") from e
    if not s or s.get("id") != sid:
        raise RuntimeError(f"spool {sid} was not found after writing it")
    return s


def _all_spools(sm: Spoolman) -> list[dict]:
    return sm.get("spool?allow_archived=true")


def by_tag(sm: Spoolman, uid: str) -> dict | None:
    uid = tags.normalize_uid(uid)
    return next((s for s in _all_spools(sm) if tags.stored(s) == uid), None)


def link_tag(sm: Spoolman, spool_id: int, uid: str, force: bool, dry: bool) -> LinkResult:
    uid = tags.normalize_uid(uid)
    target = sm.get(f"spool/{spool_id}")
    if tags.stored(target) == uid:
        return LinkResult(spool_id, uid, noop=True, dry=dry)
    others = [s for s in _all_spools(sm) if tags.stored(s) == uid and s["id"] != spool_id]
    if others and not force:
        raise TagConflict(others[0])
    if tags.stored(target) and not force:
        raise TagConflict(target, f"{describe(target)} already has tag {tags.stored(target)}; "
                                  f"tapped {uid} (force replaces it)")
    patch: dict = {}
    if not target.get("first_used"):
        patch["first_used"] = _now()
    comment = (target.get("comment") or "").replace(SEALED_COMMENT, "").strip(" |;.")
    if comment != (target.get("comment") or ""):
        patch["comment"] = comment
    result = LinkResult(spool_id, uid, dry=dry, cleared=[s["id"] for s in others], patch=patch)
    if dry:
        return result
    for s in others:
        sm.patch(f"spool/{s['id']}", {"extra": {**(s.get("extra") or {}), "nfc_id": json.dumps("")}})
    sm.patch(f"spool/{spool_id}",
             {**patch, "extra": {**(target.get("extra") or {}), "nfc_id": json.dumps(uid)}})
    if tags.stored(sm.get(f"spool/{spool_id}")) != uid:
        raise RuntimeError("tag did not land")
    return result


def add_and_link(sm: Spoolman, items: list[dict], rules: dict, dry: bool, uid: str | None) -> AddResult:
    if uid is not None:
        uid = tags.normalize_uid(uid)  # refuse before anything is written
    result = add_spools(sm, items, rules, dry)
    if uid is None:
        return result
    single_opened = (len(items) == 1 and items[0].get("count") == 1 and items[0].get("sealed") is False)
    if not single_opened:
        result.lines.append("tag not linked: it can only be linked when exactly one opened spool is added")
    elif dry:
        result.lines.append(f"would link tag {uid}")
    else:
        link_tag(sm, result.spool_ids[0], uid, force=False, dry=False)
        result.lines.append(f"linked tag {uid} to spool {result.spool_ids[0]}")
    return result


def update_spool(sm: Spoolman, spool_id: int, *, gross: float | None = None, remaining: float | None = None,
                 location: str | None = None, empty: bool = False, dry: bool) -> dict:
    spool = sm.get(f"spool/{spool_id}")
    if sum(x is not None for x in (gross, remaining)) + bool(empty) > 1:
        raise ValueError("give only one of gross, remaining or empty")
    patch: dict = {}
    if gross is not None:
        tare = spool.get("spool_weight") or (spool.get("filament") or {}).get("spool_weight") or 0
        if gross < tare:
            raise ValueError(f"gross {gross} g is below the spool tare {tare} g - check the weight")
        patch["remaining_weight"] = round(gross - tare, 1)
    elif remaining is not None:
        if remaining < 0:
            raise ValueError("remaining cannot be negative")
        patch["remaining_weight"] = remaining
    if empty:
        patch.update(remaining_weight=0, archived=True)
    if location is not None:
        patch["location"] = location
    if not patch:
        return spool
    if dry:
        return {**spool, **patch}
    return sm.patch(f"spool/{spool_id}", patch)


def find(sm: Spoolman, q: str, sealed_only: bool) -> list[dict]:
    words = q.lower().split()
    out = []
    for s in sm.get("spool"):
        if sealed_only and SEALED_COMMENT not in (s.get("comment") or ""):
            continue
        f = s.get("filament") or {}
        hay = " ".join([(f.get("vendor") or {}).get("name") or "", f.get("name") or "",
                        s.get("location") or "", tags.stored(s) or ""]).lower()
        if all(w in hay for w in words):
            out.append(s)
    return out
