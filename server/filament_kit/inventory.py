"""Inventory writes: add spools, link NFC tags, update weights/locations, search.

An add may name each item's product `line` and its Bambu Studio parent (`bambu_parent`), both text of at most
100 characters without `@`. A new filament gets `extra.line`. Once a store of Bambu system presets is uploaded,
a `bambu_parent` that is not a usable system preset is refused (400 `unknown_parent`, as PATCH lines does) before
anything is written. After a real add, each item's line is created or updated in lines.json and a profile
rebuild is requested (also when linking the tag fails after the spools were added, or Spoolman fails part-way:
then for the items that got a spool); a failure there is logged and never fails the add. An item for an existing
filament whose `line` names another line than the filament's own (it was edited in the app) sets that filament's
`extra.line` in the same add, so the filament really joins that line.

Adds, placement and tag links are serialized by `_LOCK`, a lock across threads and processes
(`FK_STATE/inventory.lock`): the `server` and `web` processes both add spools, and two adds must never pick the
same storage box.
"""
from __future__ import annotations

import datetime
import json
import logging
import math
from dataclasses import dataclass, field

from . import config, library, locks, placement, tags
from .profiles import builds, lines as lines_mod
from .spoolman import Spoolman, SpoolmanError

log = logging.getLogger(__name__)

SEALED_COMMENT = "SEALED - tag when opened"

# serializes add + placement (in this process and the other one) so two adds never pick the same box
_LOCK = locks.ProcessLock(lambda: config.paths().state / "inventory.lock")

_REQUIRED = ("vendor", "name", "material", "net", "tare", "density", "count")


@dataclass
class AddResult:
    spool_ids: list[int] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    dry: bool = False
    added: list[dict] = field(default_factory=list, repr=False)   # items that got at least one spool


@dataclass
class LinkResult:
    spool_id: int
    uid: str
    noop: bool = False
    dry: bool = False
    cleared: list[int] = field(default_factory=list)
    patch: dict = field(default_factory=dict)


class AddFailed(Exception):
    """Spoolman failed part-way through an add; `partial` lists what was already created."""

    def __init__(self, message: str, partial: AddResult):
        super().__init__(message)
        self.partial = partial


class TagConflict(Exception):
    """reason "tag_on_other_spool": `other` is the spool holding the tag.
    reason "spool_has_other_tag": the target spool has a different tag; `other` is None."""

    def __init__(self, other: dict | None, message: str, reason: str = "tag_on_other_spool"):
        self.other = other
        self.reason = reason
        super().__init__(message)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(s: dict) -> str:
    f = s.get("filament") or {}
    return (f"spool {s['id']} {(f.get('vendor') or {}).get('name', '?')} {f.get('name', '?')} "
            f"@ {s.get('location')} ({s.get('remaining_weight')} g)")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    """A real, finite number (not a bool; NaN and infinity would slip past every < and > check)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


_OPT_NUM = ("nozzle", "bed", "price_per_kg", "gross")
_OPT_STR = ("location", "color_hex", "lot", "note", "price_line", "nozzle_range", "bed_range", "spool_note",
            "line", "bambu_parent")
MAX_LINE_TEXT = lines_mod.MAX_TEXT


def check_line_text(label: str, key: str, value) -> None:
    """`line` / `bambu_parent`: None or text as `lines.text_problem` allows (at most 100 characters, no `@`)."""
    if value is None:
        return
    problem = lines_mod.text_problem(value)
    if problem:
        raise ValueError(f"{label}: {key} {problem}")


def _validate(items: list[dict]) -> None:
    if not isinstance(items, list) or not items:
        raise ValueError("no items to add")
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("each item must be an object")
        label = f"{it.get('vendor')} {it.get('name')}"
        for k in ("vendor", "name", "material"):
            if not isinstance(it.get(k), str) or not it[k].strip():
                raise ValueError(f"{label}: {k} must be a non-empty string")
        for k in ("net", "tare", "density", "count"):
            if it.get(k) is None:
                raise ValueError(f"{label}: missing {k}")
        if not _is_int(it["count"]) or it["count"] < 1:
            raise ValueError(f"{label}: count must be a whole number of at least 1")
        for k in ("net", "tare", "density"):
            if not _is_num(it[k]) or it[k] <= 0:
                raise ValueError(f"{label}: {k} must be a positive number")
        for k in _OPT_NUM:
            if it.get(k) is not None and not _is_num(it[k]):
                raise ValueError(f"{label}: {k} must be a number")
        for k in _OPT_STR:
            if it.get(k) is not None and not isinstance(it[k], str):
                raise ValueError(f"{label}: {k} must be text")
        if it.get("sealed") is not None and not isinstance(it["sealed"], bool):
            raise ValueError(f"{label}: sealed must be true or false")
        if it.get("gross") is not None and (it["count"] != 1 or it["gross"] <= it["tare"]):
            raise ValueError(f"{label}: gross {it['gross']} g needs count 1 and a weight above the spool")
        for k in ("line", "bambu_parent"):
            check_line_text(label, k, it.get(k))


def _parent(it: dict) -> str | None:
    p = it.get("bambu_parent")
    return p.strip() if isinstance(p, str) and p.strip() else None


def _check_parents(items: list[dict]) -> None:
    wanted = [p for p in (_parent(it) for it in items) if p is not None]
    if not wanted:
        return
    store = builds.system_store()
    for p in wanted:
        lines_mod.check_parent(p, store)


def _used_locations(sm: Spoolman) -> set[str]:
    return {s["location"] for s in sm.get("spool") if s.get("location")}


def add_spools(sm: Spoolman, items: list[dict], rules: dict, dry: bool, *, parents_checked: bool = False) -> AddResult:
    _validate(items)
    if not parents_checked:
        _check_parents(items)                   # before _LOCK: it may wait on the build's live.lock
    result = AddResult(dry=dry)
    with _LOCK:
        placed = placement.place(items, _used_locations(sm), rules)
        vendors = {v["name"].lower(): v for v in sm.get("vendor")}
        fils = {((f.get("vendor") or {}).get("name", "").lower(), f["name"].lower()): f for f in sm.get("filament")}
        # re-check gross against the tare that will really be used (an existing filament's, else the item's)
        tares = {k: f.get("spool_weight") for k, f in fils.items()}
        for it in placed:
            key = (it["vendor"].lower(), it["name"].lower())
            tares.setdefault(key, it["tare"])
            tare = tares[key] or it["tare"]
            if it.get("gross") is not None and it["gross"] <= tare:
                raise ValueError(f"{it['vendor']} {it['name']}: gross {it['gross']} g is not above the spool "
                                 f"weight {tare} g used for this filament")
        try:
            _write_items(sm, placed, vendors, fils, result, dry)
        except (SpoolmanError, RuntimeError) as e:  # RuntimeError: a written spool did not read back
            raise AddFailed(f"spoolman failed part-way: {e}", result) from e
    return result


def _write_items(sm, placed, vendors, fils, result, dry) -> None:
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
            _join_line(sm, f, it, result, dry)
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
            result.spool_ids.append(sid)
            if not ids:
                result.added.append(it)
            _read_back(sm, sid)
            ids.append(sid)
        gross_note = f" (gross {it['gross']} - tare {tare})" if it.get("gross") is not None else ""
        fid = f"F{f['id']} " if f.get("id") is not None else ""
        id_note = f" {ids}" if not dry else ""
        result.lines.append(
            f"{fid}{vn} {it['name']} ({state}): {it['count']} spool(s){id_note} @ {it['location']}"
            f"{' (opened)' if opened else ''}, {remaining} g{gross_note}")


def _join_line(sm: Spoolman, f: dict, it: dict, result: AddResult, dry: bool) -> None:
    """The item's `line` names another line than the existing filament's own (`extra.line`, else the product
    derived from its name): it was edited in the app (the label read always sends the filament's own line), so
    set the filament's `extra.line` (other extra fields kept) and the filament moves to that line at the next
    grouping. The same line, no line, or no library to derive the filament's line from, writes nothing."""
    want = it.get("line").strip() if isinstance(it.get("line"), str) else ""
    if not want:
        return
    vendor = it["vendor"]
    try:
        have = lines_mod.product_of({**f, "vendor": {"name": vendor}}, library.load())
    except Exception:  # noqa: BLE001 - no library: only a set extra.line is known; else the line is unknown
        have = lines_mod._extra_line(f)
        if not have:
            return
    if lines_mod.line_id_for(vendor, want) == lines_mod.line_id_for(vendor, have):
        return
    fid = f"F{f['id']} " if f.get("id") is not None else ""
    if dry:
        result.lines.append(f"{fid}{vendor} {it['name']}: would set line to {want} (now {have})")
        return
    extra = {**(f.get("extra") or {}), "line": json.dumps(want)}
    sm.patch(f"filament/{f['id']}", {"extra": extra})
    f["extra"] = extra
    result.lines.append(f"{fid}{vendor} {it['name']}: line set to {want} (was {have})")


def _new_filament(sm: Spoolman, it: dict, vendor: dict, dry: bool) -> dict:
    extra = {k: json.dumps(it[k]) for k in ("nozzle_range", "bed_range") if it.get(k)}
    if isinstance(it.get("line"), str) and it["line"].strip():
        extra["line"] = json.dumps(it["line"].strip())
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
    with _LOCK:
        target = sm.get(f"spool/{spool_id}")
        if tags.stored(target) == uid:
            return LinkResult(spool_id, uid, noop=True, dry=dry)
        others = [s for s in _all_spools(sm) if tags.stored(s) == uid and s["id"] != spool_id]
        if others and not force:
            raise TagConflict(others[0], f"tag {uid} is already linked to {describe(others[0])}")
        if tags.stored(target) and not force:
            raise TagConflict(None, f"{describe(target)} already has tag {tags.stored(target)}; "
                                    f"tapped {uid} (force replaces it)", reason="spool_has_other_tag")
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
    """Add the spools (and link the tag of a single opened one). The Bambu parents are checked before _LOCK is
    taken and the lines recorded after it is released: both may wait for a build (live.lock, the lines lock), and
    a spool load needs _LOCK meanwhile (final review I6)."""
    if uid is not None:
        uid = tags.normalize_uid(uid)  # refuse before anything is written
    single_opened = (isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict)
                     and items[0].get("count") == 1 and items[0].get("sealed") is False)
    _validate(items)
    _check_parents(items)
    record: list[dict] = []
    try:
        with _LOCK:
            if uid is not None and single_opened:
                other = by_tag(sm, uid)
                if other is not None:  # refuse before writing, so a retry cannot duplicate the spool
                    raise TagConflict(other, f"tag {uid} is already linked to {describe(other)}")
            try:
                result = add_spools(sm, items, rules, dry, parents_checked=True)
            except AddFailed as e:  # Spoolman failed part-way: the items that got a spool still join their lines
                if not dry:
                    record = e.partial.added
                raise
            if uid is None:
                if not dry:
                    record = result.added
                return result
            if not single_opened:
                result.lines.append("tag not linked: it can only be linked when exactly one opened spool is added")
            elif dry:
                result.lines.append(f"would link tag {uid}")
            else:
                try:
                    link_tag(sm, result.spool_ids[0], uid, force=False, dry=False)
                except (SpoolmanError, RuntimeError) as e:  # the spool exists; report it so a retry doesn't
                    record = result.added                  # duplicate it, and it joins its line all the same
                    raise AddFailed(f"spool {result.spool_ids[0]} was added but linking tag {uid} failed: {e}",
                                    result) from e
                result.lines.append(f"linked tag {uid} to spool {result.spool_ids[0]}")
            if not dry:
                record = result.added
        return result
    finally:
        if record:                              # after _LOCK is released
            _record_lines(record)


def _record_lines(items: list[dict]) -> None:
    """Create or update each added item's line (with its bambu_parent) and request a rebuild. Never raises: the
    spools are in Spoolman already, and the next build groups them into lines anyway."""
    if not items:
        return
    try:
        lib = library.load()
        store = builds.system_store()
        with lines_mod.transaction() as ls:
            for it in items:
                vendor = it["vendor"].strip()
                product = (it.get("line") or "").strip() or lines_mod.product_of(
                    {"name": it["name"], "vendor": {"name": vendor}, "extra": {}}, lib) or it["material"].strip()
                lines_mod.ensure(ls, vendor, product, it["material"], bambu_parent=_parent(it), library=lib,
                                 store=store, used_fids=set())
        builds.request_rebuild("intake")
    except Exception as e:  # noqa: BLE001 - the add itself succeeded; a line problem shows at the next build
        log.warning("spools added, but recording their product lines failed: %s: %s", e.__class__.__name__, e)


def open_spool(sm: Spoolman, spool_id: int, uid: str, rules: dict, *, gross: float | None = None,
               location: str | None = None, force: bool = False, dry: bool,
               humidity: float | None = None, remaining: float | None = None) -> dict:
    """Link the tag and mark the spool opened: first_used, SEALED comment dropped, moved out of sealed stock.
    `gross` (scale weight with the spool) or `remaining` (filament grams) sets the weight; `humidity` (the box
    hygrometer, %) is kept as `extra.box_humidity` with `extra.humidity_checked` = now (UTC), as ops did."""
    uid = tags.normalize_uid(uid)
    if gross is not None and remaining is not None:
        raise ValueError("give only one of gross or remaining")
    if remaining is not None and (not _is_num(remaining) or remaining < 0):
        raise ValueError("remaining must be a number of grams, not negative")
    if gross is not None and not _is_num(gross):
        raise ValueError("gross must be a number of grams")
    if humidity is not None and (not _is_num(humidity) or not 0 <= humidity <= 100):
        raise ValueError("humidity must be a percentage (0-100)")
    with _LOCK:
        spool = sm.get(f"spool/{spool_id}")
        patch: dict = {}
        if gross is not None:
            tare = spool.get("spool_weight") or (spool.get("filament") or {}).get("spool_weight") or 0
            if gross < tare:
                raise ValueError(f"gross {gross} g is below the spool tare {tare} g - check the weight")
            patch["remaining_weight"] = round(gross - tare, 1)
        elif remaining is not None:
            patch["remaining_weight"] = remaining
        link = link_tag(sm, spool_id, uid, force=force, dry=dry)  # raises TagConflict before any other write
        if location is None and spool.get("location") in (None, "", rules["sealed_location"]):
            used = {s["location"] for s in sm.get("spool") if s.get("location") and s["id"] != spool_id}
            material = (spool.get("filament") or {}).get("material") or ""
            location = placement.place([{"material": material, "sealed": False, "count": 1}], used, rules)[0][
                "location"]
        if location is not None and location != spool.get("location"):
            patch["location"] = location
        moist = {} if humidity is None else {"box_humidity": json.dumps(humidity),
                                             "humidity_checked": json.dumps(_now())}
        if dry:
            return {**spool, **link.patch, **patch,
                    "extra": {**(spool.get("extra") or {}), "nfc_id": json.dumps(uid), **moist}}
        fresh = sm.get(f"spool/{spool_id}")
        if not fresh.get("first_used"):
            patch["first_used"] = _now()
        comment = (fresh.get("comment") or "").replace(SEALED_COMMENT, "").strip(" |;.")
        if comment != (fresh.get("comment") or ""):
            patch["comment"] = comment
        if moist:  # on top of the fresh extra, which now holds the linked tag
            patch["extra"] = {**(fresh.get("extra") or {}), **moist}
        if patch:
            sm.patch(f"spool/{spool_id}", patch)
        return sm.get(f"spool/{spool_id}")


def pick_sealed(sm: Spoolman, filament_id: int) -> int | None:
    """The spool to open for a filament: its lowest-id spool still carrying the SEALED marker, else None."""
    ids = [s["id"] for s in sm.get("spool")
           if (s.get("filament") or {}).get("id") == filament_id and SEALED_COMMENT in (s.get("comment") or "")]
    return min(ids, default=None)


def _one_byte_apart(a: str, b: str) -> bool:
    pa, pb = a.split(":"), b.split(":")
    return len(pa) == len(pb) > 1 and sum(x != y for x, y in zip(pa, pb)) == 1


def tag_neighbours(sm: Spoolman, nfc_id: str) -> list[int]:
    """Spools whose tag differs from `nfc_id` in exactly one byte: tags cut from one roll have UIDs like that
    (4:77:8f:... vs 4:77:90:...), so a tap may have picked up the wrong one of a batch."""
    uid = tags.normalize_uid(nfc_id)
    out = []
    for s in _all_spools(sm):
        t = tags.stored(s)
        try:
            t = tags.normalize_uid(t) if t else None
        except ValueError:
            continue
        if t and _one_byte_apart(t, uid):
            out.append(s["id"])
    return sorted(out)


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


def filaments(sm: Spoolman, q: str = "") -> list[dict]:
    """Spoolman's filaments matching every word of `q` (vendor, name, material), with or without spools, for a
    manual add's picker. Fields carry an add item's names (net, tare, nozzle, bed), so a client copies them; `tare`
    is the filament's spool weight, else its vendor's empty spool weight. A filament without a vendor is listed with
    vendor ""."""
    words = (q or "").lower().split()
    counts: dict = {}
    for s in sm.get("spool"):
        fid = (s.get("filament") or {}).get("id")
        counts[fid] = counts.get(fid, 0) + 1
    out = []
    for f in sm.get("filament"):
        v = f.get("vendor") or {}
        vendor = v.get("name") or ""
        if any(w not in f"{vendor} {f.get('name') or ''} {f.get('material') or ''}".lower() for w in words):
            continue
        tare = f.get("spool_weight")
        out.append({"id": f["id"], "vendor": vendor, "name": f.get("name"), "material": f.get("material"),
                    "density": f.get("density"), "net": f.get("weight"),
                    "tare": tare if tare is not None else v.get("empty_spool_weight"),
                    "color_hex": f.get("color_hex"), "nozzle": f.get("settings_extruder_temp"),
                    "bed": f.get("settings_bed_temp"), "spools": counts.get(f["id"], 0)})
    return sorted(out, key=lambda f: (f["vendor"].lower(), (f["name"] or "").lower()))


def vendors(sm: Spoolman) -> list[dict]:
    """Spoolman's vendors (name and empty spool weight as `tare`), for a manual add's vendor choice."""
    return sorted(({"id": v["id"], "name": v.get("name") or "", "tare": v.get("empty_spool_weight")}
                   for v in sm.get("vendor")), key=lambda v: v["name"].lower())
