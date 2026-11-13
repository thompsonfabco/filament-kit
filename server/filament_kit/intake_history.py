"""Intake history: the last N spool additions, their photos, what the AI read, and every later revision.

A record is made when a save succeeds (`record_save`, from the add paths: the API, the kit's phone web app, the intake
station, the CLI). A save that followed a label read names its `read_id`; the read's photos and result were set aside by
`stash_read` when the read succeeded (`pending/<read_id>`, kept PENDING_TTL), and move into the record.

    <state>/intake-history/<id>/record.json   the record (below)
    <state>/intake-history/<id>/photo<n>.jpg  the photos actually sent to the AI (n from 1)
    <state>/intake-history/pending/<read_id>/ a read not saved yet: read.json + photo<n>.jpg

record.json: {id, at, source, device, state, read_id, read: {items, hint} | null, weight, tag,
              saved: [{item, values, spool_ids, filament_id}], revisions: [...], proposals: {...}}

Revisions change Spoolman (`apply`) without ever editing a filament other spools share: identity fields (vendor, name,
material, colour) or any field of a shared filament re-link the record's spools to a filament with the new values
(found, else created); a filament only this record's spools use is edited in place. A filament left with no spools
is reported (`orphaned`), never deleted. The spools keep their tag, opened state, location and used weight. Every
revision can be undone, newest first (`undo`).

Photos are the owner's data: on this server only, in the backup with the rest of the state, sent only to the AI the
owner configured and only when the owner asks for a revision. The number kept is the setting `intake.history_keep`
(default KEEP_DEFAULT, 0 = keep none); the oldest go first, photos with their record."""
from __future__ import annotations

import datetime
import json
import logging
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from . import config
from .pairing import _write_atomic, make_state_dir

log = logging.getLogger(__name__)

HISTORY = "intake-history"
PENDING = "pending"
PENDING_TTL = 24 * 3600
KEEP_DEFAULT = 20
KEEP_MAX = 500
PROPOSAL_TTL = 3600
SOURCES = ("phone", "web", "station", "cli")
# The item fields a record keeps and a revision may change (the add's own item fields)
FIELDS = ("vendor", "name", "material", "color_hex", "net", "tare", "density", "nozzle", "bed", "nozzle_range",
          "bed_range", "price_per_kg", "line")
IDENTITY = ("vendor", "name", "material", "color_hex")
ID = re.compile(r"[0-9a-f]{12}")
READ_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_LOCK = threading.RLock()                   # the history folder: new records, pruning
_RECORD_LOCKS: dict[str, threading.Lock] = {}


def _record_lock(rid: str) -> threading.Lock:
    """One lock per record for a change (apply, undo, a proposal): a slow Spoolman holds only that record, never the
    list, a record's view or a photo (their files are written atomically, so a read needs no lock)."""
    with _LOCK:
        return _RECORD_LOCKS.setdefault(rid, threading.Lock())


class HistoryError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


# ---------------------------------------------------------------- storage

def _root() -> Path:
    return config.paths().state / HISTORY


def keep(cfg: dict | None = None) -> int:
    v = ((cfg if cfg is not None else config.load()).get("intake") or {}).get("history_keep")
    if isinstance(v, bool) or not isinstance(v, int):
        return KEEP_DEFAULT
    return max(0, min(KEEP_MAX, v))


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _dir(rid: str) -> Path:
    if not isinstance(rid, str) or not ID.fullmatch(rid):
        raise HistoryError(404, "not_found", "no such intake record")
    return _root() / rid


def _load(rid: str) -> dict:
    d = _dir(rid)
    try:
        rec = json.loads((d / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HistoryError(404, "not_found", "no such intake record") from None
    if not isinstance(rec, dict):
        raise HistoryError(404, "not_found", "no such intake record")
    return rec


def _save(rec: dict) -> None:
    d = _dir(rec["id"])
    make_state_dir(d)
    _write_atomic(d / "record.json", json.dumps(rec, indent=1).encode("utf-8"), 0o600, state_owned=True)


def _photos(d: Path) -> list[Path]:
    return sorted(d.glob("photo*.jpg"), key=lambda p: int(p.stem[5:]) if p.stem[5:].isdigit() else 0)


def _ids_newest_first() -> list[str]:
    root = _root()
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if d.is_dir() and ID.fullmatch(d.name) and (d / "record.json").is_file():
            out.append((d.stat().st_mtime if not (d / "made").is_file() else float((d / "made").read_text() or 0),
                        d.name))
    return [rid for _, rid in sorted(out, reverse=True)]


def prune(cfg: dict | None = None) -> list[str]:
    """Delete the oldest records past the setting; returns the ids deleted."""
    n = keep(cfg)
    with _LOCK:
        gone = _ids_newest_first()[n:]
        for rid in gone:
            shutil.rmtree(_root() / rid, ignore_errors=True)
    if gone:
        log.info("intake history: %d old record(s) deleted (keeping %d)", len(gone), n)
    return gone


# ---------------------------------------------------------------- the read, set aside until it is saved

def _pending(read_id: str) -> Path:
    return _root() / PENDING / read_id


def _sweep_pending() -> None:
    root = _root() / PENDING
    if not root.is_dir():
        return
    cutoff = time.time() - PENDING_TTL
    for d in root.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def stash_read(read_id: str, images: list[bytes], result: dict, hint: str = "", tag: str | None = None) -> None:
    """Set a successful read's photos and result aside until a save names it. Never raises (a read must not fail
    because its history could not be kept); with retention 0 nothing is kept."""
    try:
        if keep() == 0 or not isinstance(read_id, str) or not READ_ID.fullmatch(read_id):
            return
        with _LOCK:
            _sweep_pending()
            d = _pending(read_id)
            make_state_dir(d)
            for i, data in enumerate(images, 1):
                _write_atomic(d / f"photo{i}.jpg", data, 0o600, state_owned=True)
            body = {"items": [{k: it.get(k) for k in (*FIELDS, "count", "sealed", "match")}
                              for it in (result.get("items") or []) if isinstance(it, dict)],
                    "hint": hint or "", "tag": tag}
            _write_atomic(d / "read.json", json.dumps(body).encode("utf-8"), 0o600, state_owned=True)
    except Exception:  # noqa: BLE001 - history is a convenience; the read itself succeeded
        log.exception("intake history: cannot keep read %s", read_id)


# ---------------------------------------------------------------- a save becomes a record

def record_save(saved: list[dict], *, source: str, device: str | None = None, read_id: str | None = None,
                tag: str | None = None, weight: float | None = None) -> str | None:
    """A record for a save that wrote spools. `saved`: [{values: <the item as added>, spool_ids, filament_id}] in the
    add's order (inventory.AddResult.saved). None when retention is 0 or nothing was written. Never raises."""
    try:
        saved = [s for s in saved if isinstance(s, dict) and s.get("spool_ids")]
        if not saved or keep() == 0:
            return None
        rid = secrets.token_hex(6)
        with _LOCK:
            d = _dir(rid)
            make_state_dir(d)
            read = None
            if isinstance(read_id, str) and READ_ID.fullmatch(read_id) and _pending(read_id).is_dir():
                p = _pending(read_id)
                for i, ph in enumerate(_photos(p), 1):
                    shutil.move(str(ph), str(d / f"photo{i}.jpg"))
                try:
                    read = json.loads((p / "read.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    read = None
                shutil.rmtree(p, ignore_errors=True)
            rec = {"id": rid, "at": _now(), "source": source if source in SOURCES else "phone",
                   "device": (device or "")[:80], "state": "detected", "read_id": read_id if read else None,
                   "read": ({"items": read.get("items") or [], "hint": read.get("hint") or ""} if read else None),
                   "weight": weight if isinstance(weight, (int, float)) and not isinstance(weight, bool) else None,
                   "tag": tag or (read or {}).get("tag") or None,
                   "saved": [{"item": i, "values": {k: s["values"].get(k) for k in FIELDS},
                              "spool_ids": [int(x) for x in s["spool_ids"]], "filament_id": s.get("filament_id")}
                             for i, s in enumerate(saved)],
                   "revisions": [], "proposals": {}}
            _save(rec)
            (d / "made").write_text(str(time.time()))
        prune()
        log.info("intake history: record %s (%s, %d spool(s))", rid, rec["source"],
                 sum(len(s["spool_ids"]) for s in rec["saved"]))
        return rid
    except Exception:  # noqa: BLE001 - the spools were written; a missing record must not fail the save
        log.exception("intake history: cannot record a save")
        return None


# ---------------------------------------------------------------- reading

def _summary(rec: dict) -> dict:
    d = _dir(rec["id"])
    spools = []
    for s in rec.get("saved") or []:
        v = s.get("values") or {}
        for sid in s.get("spool_ids") or []:
            spools.append({"spool_id": sid, "filament_id": s.get("filament_id"), "vendor": v.get("vendor"),
                           "name": v.get("name"), "material": v.get("material"), "color_hex": v.get("color_hex")})
    return {"id": rec["id"], "at": rec.get("at"), "source": rec.get("source"), "state": rec.get("state"),
            "photos": len(_photos(d)), "undoable": any(not r.get("undone") for r in rec.get("revisions") or []),
            "spools": spools}


def _size() -> int:
    total = 0
    for p in _root().glob("*/photo*.jpg") if _root().is_dir() else []:
        try:
            total += p.stat().st_size
        except OSError:                 # pruned meanwhile
            pass
    return total


def list_records(ai: bool) -> dict:
    recs = []
    for rid in _ids_newest_first():
        try:
            recs.append(_summary(_load(rid)))
        except (HistoryError, OSError):
            continue
    size = _size()
    return {"keep": keep(), "count": len(recs), "photo_bytes": size, "ai": bool(ai), "records": recs}


def newest_spool() -> tuple[int, str] | None:
    """(spool id, time saved) of the newest saved record that made a spool, or None."""
    for rid in _ids_newest_first():
        try:
            rec = _load(rid)
            spools = _summary(rec)["spools"]
        except (HistoryError, OSError):
            continue
        if spools:
            return spools[0]["spool_id"], rec.get("at")
    return None


def get(rid: str) -> dict:
    rec = _load(rid)
    out = _summary(rec)
    out.update({k: rec.get(k) for k in ("read", "weight", "tag", "device")})
    # an item whose spools all moved to a split-off item (a change to some of them) is not shown
    out["saved"] = [{"item": s["item"], "values": s["values"], "spool_ids": s["spool_ids"],
                     "filament_id": s.get("filament_id")} for s in rec.get("saved") or [] if s.get("spool_ids")]
    out["revisions"] = rec.get("revisions") or []
    return out


def photo(rid: str, n: int) -> bytes:
    ps = _photos(_dir(rid))
    if not isinstance(n, int) or not 1 <= n <= len(ps):
        raise HistoryError(404, "not_found", "no such photo")
    return ps[n - 1].read_bytes()


def photo_paths(rid: str) -> list[str]:
    return [str(p) for p in _photos(_dir(rid))]


# ---------------------------------------------------------------- values

def _check_values(values: dict) -> dict:
    if not isinstance(values, dict) or not values:
        raise HistoryError(400, "bad_request", "give at least one field to change")
    bad = sorted(set(values) - set(FIELDS))
    if bad:
        raise HistoryError(400, "bad_request", "unknown field: " + ", ".join(bad) + " (fields: " + ", ".join(FIELDS) + ")")
    out = {}
    for k, v in values.items():
        if k in ("vendor", "name", "material"):
            if not isinstance(v, str) or not v.strip() or len(v) > 100 or not v.isprintable():
                raise HistoryError(400, "bad_request", f"{k} must be text (1-100 characters)")
            v = v.strip()
        elif k in ("line", "nozzle_range", "bed_range"):
            if v is not None and (not isinstance(v, str) or len(v) > 100 or not v.isprintable()):
                raise HistoryError(400, "bad_request", f"{k} must be text (at most 100 characters)")
            v = (v or "").strip() or None
        elif k == "color_hex":
            if v is not None:
                v = str(v).lstrip("#").upper()
                if not re.fullmatch(r"[0-9A-F]{6}", v):
                    raise HistoryError(400, "bad_request", "color_hex must be 6 hex digits")
        elif k in ("nozzle", "bed"):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 500):
                raise HistoryError(400, "bad_request", f"{k} must be a whole number of degrees")
        else:   # net tare density price_per_kg
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
                raise HistoryError(400, "bad_request", f"{k} must be a positive number")
        out[k] = v
    return out


# Spoolman filament fields for the item fields (the rest: extra.line, the ranges, the price from net)
_FIL = {"name": "name", "material": "material", "color_hex": "color_hex", "net": "weight", "tare": "spool_weight",
        "density": "density", "nozzle": "settings_extruder_temp", "bed": "settings_bed_temp"}


def _filament_patch(values: dict, changed: list[str]) -> dict:
    body: dict = {}
    for k in changed:
        if k in _FIL:
            body[_FIL[k]] = values.get(k)
    extra = {}
    for k in ("line", "nozzle_range", "bed_range"):
        if k in changed:
            extra[k] = json.dumps(values.get(k) or "")
    if extra:
        body["extra"] = extra
    if ("price_per_kg" in changed or "net" in changed) and values.get("price_per_kg") and values.get("net"):
        body["price"] = round(values["price_per_kg"] * values["net"] / 1000, 2)
    return body


def _spools_on(sm, fid: int) -> list[int]:
    return [s["id"] for s in sm.get("spool?allow_archived=true")
            if ((s.get("filament") or {}).get("id")) == fid]


def _vendor(sm, name: str, tare) -> dict:
    for v in sm.get("vendor"):
        if (v.get("name") or "").lower() == name.lower():
            return v
    return sm.post("vendor", {"name": name, **({"empty_spool_weight": tare} if tare else {})})


def _find_filament(sm, values: dict, not_id: int | None = None) -> dict | None:
    """A filament with these identity values other than `not_id` (the spools' current one)."""
    want = (values["vendor"].lower(), values["name"].lower(), (values.get("material") or "").lower(),
            (values.get("color_hex") or "").upper())
    for f in sm.get("filament"):
        if f.get("id") == not_id:
            continue
        have = (((f.get("vendor") or {}).get("name") or "").lower(), (f.get("name") or "").lower(),
                (f.get("material") or "").lower(), (f.get("color_hex") or "").upper())
        if have == want:
            return f
    return None


def _new_filament(sm, values: dict) -> dict:
    from .inventory import _new_filament as make
    it = {"name": values["name"], "material": values.get("material") or "PLA",
          "density": values.get("density") or 1.24, "net": values.get("net") or 1000, "tare": values.get("tare") or 0,
          "color_hex": values.get("color_hex"), "nozzle": values.get("nozzle"), "bed": values.get("bed"),
          "nozzle_range": values.get("nozzle_range"), "bed_range": values.get("bed_range"),
          "price_per_kg": values.get("price_per_kg"), "line": values.get("line"),
          "note": "corrected in the intake history"}
    return make(sm, it, _vendor(sm, values["vendor"], values.get("tare")), False)


def _rebuild(changed: list[str]) -> None:
    try:
        from .profiles import builds
        builds.request_rebuild("intake history revision")
    except Exception:  # noqa: BLE001 - the spools are right; presets follow at the next build
        log.exception("intake history: cannot request a preset build")


# ---------------------------------------------------------------- revising

def _item(rec: dict, item) -> dict:
    saved = rec.get("saved") or []
    if item is None:
        item = next((x["item"] for x in saved if x.get("spool_ids")), 0)
    if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < len(saved) \
            or not saved[item].get("spool_ids"):
        raise HistoryError(400, "bad_request", "no such item in this record")
    return saved[item]


def revise(sm, rid: str, note: str, item=None, *, client=None, ai_on: bool = True, charge=None) -> dict:
    """Ask the label reader again with the record's photos, its saved values and the owner's note; writes nothing
    but the proposal (kept PROPOSAL_TTL), which `apply(proposal=...)` accepts. The reader setting decides who
    answers (`intake._call`): the local reader through its revise call, Claude through the prompt below; `charge`
    takes the daily cap only for Claude. A record with no photo can only be revised by Claude."""
    from . import config, intake
    if not ai_on:
        raise HistoryError(409, "ai_off", "label reading (ai_intake or local_intake) is off on this server: edit "
                                          "the values by hand")
    if not isinstance(note, str) or not note.strip() or len(note) > 500:
        raise HistoryError(400, "bad_request", "write what is wrong (at most 500 characters)")
    rec = _load(rid)
    it = _item(rec, item)
    images = [p.read_bytes() for p in _photos(_dir(rid))]
    n_rev = len(rec.get("revisions") or [])
    hint = (f"Correction from the owner: {note.strip()}\nThe values saved from the first reading of this spool "
            f"were: {json.dumps(it['values'])}\nRead the photos again with the correction and give this one item "
            "with every value that follows from it corrected (temperatures, density, spool weight, line).")
    readers = intake.reader_order(config.load()) or ["cloud"]
    if not images:
        readers = [r for r in readers if r != "local"]
        if not readers:
            raise HistoryError(409, "no_photo", "this record has no photo, and the local reader needs one: edit the "
                                                "values by hand")
    out = intake._call(sm, images, hint, None, client, readers=readers, charge=charge,
                       revise=(dict(it["values"]), note.strip()))
    got = (out.get("items") or [None])[0]
    if not isinstance(got, dict):
        raise HistoryError(502, "api_error", "the AI gave no item back; try again")
    before = dict(it["values"])
    after = dict(before)
    for k in FIELDS:                    # a field the AI left out (or emptied) keeps its value
        if got.get(k) not in (None, ""):
            after[k] = got[k]
    try:                                # the proposal passes the same checks as an edit by hand
        diff = {k: after[k] for k in FIELDS if after.get(k) != before.get(k)}
        after.update(_check_values(diff) if diff else {})
    except HistoryError as e:
        raise HistoryError(502, "api_error", f"the AI's answer was not usable ({e}); try again or edit by hand") from None
    changes = [k for k in FIELDS if after.get(k) != before.get(k)]
    pid = "p-" + secrets.token_hex(3)
    with _record_lock(rid):
        rec = _load(rid)
        props = {k: v for k, v in (rec.get("proposals") or {}).items()
                 if isinstance(v, dict) and v.get("t", 0) > time.time() - PROPOSAL_TTL}
        props[pid] = {"t": time.time(), "item": it["item"], "after": after, "note": note.strip(), "base": n_rev}
        rec["proposals"] = props
        _save(rec)
    return {"proposal": pid, "item": it["item"], "before": before, "after": after, "changes": changes,
            "no_photo": not images, "reader": out.get("reader"), "confidence": out.get("confidence"),
            "note": out.get("note")}


def _changed_fields(rev: dict) -> set:
    return {c["field"] for c in rev.get("changes") or []}


def apply(sm, rid: str, *, proposal: str | None = None, item=None, values: dict | None = None,
          spool_ids: list | None = None, device: str | None = None) -> dict:
    """Write a change to the record's spools in Spoolman (see the module docstring) and add it as a revision. A change
    to some of an item's spools splits them into an item of their own, so the record says what each spool is."""
    if proposal is not None and not isinstance(proposal, str):
        raise HistoryError(400, "bad_request", "proposal must be the id a revision gave")
    with _record_lock(rid):
        rec = _load(rid)
        by, note = "hand", ""
        if proposal is not None:
            p = (rec.get("proposals") or {}).get(proposal)
            if not isinstance(p, dict) or p.get("t", 0) < time.time() - PROPOSAL_TTL:
                raise HistoryError(404, "not_found", "no such proposal (they last an hour): revise again")
            if p.get("base") != len(rec.get("revisions") or []):
                raise HistoryError(409, "stale", "the record changed since this proposal: revise again")
            it = _item(rec, p["item"])
            diff = {k: v for k, v in p["after"].items() if k in FIELDS and v != it["values"].get(k)}
            new = {**it["values"], **(_check_values(diff) if diff else {})}
            by, note = "ai", p.get("note") or ""
        else:
            it = _item(rec, item)
            new = {**it["values"], **_check_values(values or {})}
        old = dict(it["values"])
        changed = [k for k in FIELDS if new.get(k) != old.get(k)]
        if not changed:
            raise HistoryError(400, "bad_request", "nothing to change: the values are the same")
        if any(not new.get(k) for k in ("vendor", "name")):
            raise HistoryError(400, "bad_request", "vendor and name are needed")
        targets = list(it["spool_ids"])
        if spool_ids is not None:
            if (not isinstance(spool_ids, list) or not spool_ids
                    or any(isinstance(s, bool) or s not in targets for s in spool_ids)):
                raise HistoryError(400, "bad_request", f"spool_ids must be some of {targets}")
            targets = [s for s in it["spool_ids"] if s in spool_ids]
        spools = {s: sm.get(f"spool/{s}") for s in targets}
        fids = {((sp.get("filament") or {}).get("id")) for sp in spools.values()}
        if len(fids) != 1 or None in fids:
            raise HistoryError(409, "stale", "these spools no longer share one filament: edit them one at a time")
        (fid,) = fids
        users = _spools_on(sm, fid)
        shared = any(u not in targets for u in users)
        rev = {"n": len(rec.get("revisions") or []) + 1, "at": _now(), "by": by, "device": (device or "")[:80],
               "note": note, "item": it["item"], "spool_ids": targets, "state_before": rec.get("state"),
               "values_before": old, "split_from": None,
               "spool_weights": {str(s): sp.get("spool_weight") for s, sp in spools.items()},
               "changes": [],
               "filaments": {"from": fid, "to": fid, "created": False, "edited": {}, "orphaned": []},
               "undone": False}
        if shared or any(k in IDENTITY for k in changed):
            # a new identity joins the filament that has it (its values win, as on an add); the same identity on a
            # shared filament gets its own copy with the new values, so the other spools keep theirs
            f = _find_filament(sm, new, fid) if any(k in IDENTITY for k in changed) else None
            created = f is None
            if created:
                f = _new_filament(sm, new)
            for s in targets:
                patch = {"filament_id": f["id"]}
                if "tare" in changed and new.get("tare"):
                    patch["spool_weight"] = new["tare"]
                sm.patch(f"spool/{s}", patch)
            rev["filaments"].update(to=f["id"], created=created)
            if not created:                 # the existing filament's values are the spools' values now
                for k, fk in _FIL.items():
                    if f.get(fk) is not None and k != "name":
                        new[k] = f[fk]
            if not _spools_on(sm, fid):
                rev["filaments"]["orphaned"] = [fid]
        else:
            body = _filament_patch(new, changed)
            cur = sm.get(f"filament/{fid}")
            rev["filaments"]["edited"] = {k: (cur.get("extra") or {}) if k == "extra" else cur.get(k) for k in body}
            if body:
                sm.patch(f"filament/{fid}", body)
            if "tare" in changed and new.get("tare"):
                for s in targets:
                    sm.patch(f"spool/{s}", {"spool_weight": new["tare"]})
        rev["changes"] = [{"spool_id": s, "field": k, "old": old.get(k), "new": new.get(k)}
                          for s in targets for k in FIELDS if new.get(k) != old.get(k)]
        if len(targets) < len(it["spool_ids"]):         # some of the item's spools: they become an item of their own
            part = {"item": len(rec["saved"]), "values": new, "spool_ids": targets,
                    "filament_id": rev["filaments"]["to"]}
            it["spool_ids"] = [s for s in it["spool_ids"] if s not in targets]
            rec["saved"].append(part)
            rev["split_from"], rev["item"] = it["item"], part["item"]
        else:
            it["values"] = new
            it["filament_id"] = rev["filaments"]["to"]
        rec.setdefault("revisions", []).append(rev)
        rec["state"] = "revised_ai" if by == "ai" else "edited"
        rec["proposals"] = {}
        _save(rec)
        log.info("intake history: record %s revision %d by %s (%s; filament %s -> %s%s)", rid, rev["n"], by,
                 ",".join(changed), fid, rev["filaments"]["to"],
                 f"; {len(targets)} of {len(targets) + len(it['spool_ids'])} spools" if rev["split_from"] is not None
                 else "")
    _rebuild(changed)
    return get(rid)


def undo(sm, rid: str, revision) -> dict:
    """Undo the newest revision that is not undone yet. A filament the revision edited in place that other spools use
    by now is not edited back: these spools get a copy with the earlier values (the module's rule for a shared
    filament). The spool weight is put back only when the revision changed it."""
    with _record_lock(rid):
        rec = _load(rid)
        live = [r for r in rec.get("revisions") or [] if not r.get("undone")]
        if not live:
            raise HistoryError(409, "not_latest", "nothing to undo")
        rev = live[-1]
        if revision is not None and revision != rev["n"]:
            raise HistoryError(409, "not_latest", f"only the newest revision ({rev['n']}) can be undone")
        fl = rev["filaments"]
        tare = "tare" in _changed_fields(rev)
        weights = rev.get("spool_weights") or {}
        targets = rev["spool_ids"]

        def put_weight(patch: dict, s) -> dict:
            if tare and weights.get(str(s)) is not None:
                patch["spool_weight"] = weights[str(s)]
            elif tare and rev["values_before"].get("tare"):
                patch["spool_weight"] = rev["values_before"]["tare"]
            return patch
        if fl["to"] != fl["from"]:
            for s in targets:
                sm.patch(f"spool/{s}", put_weight({"filament_id": fl["from"]}, s))
            if not _spools_on(sm, fl["to"]):
                fl["orphaned_by_undo"] = [fl["to"]]
        elif fl.get("edited"):
            others = [u for u in _spools_on(sm, fl["from"]) if u not in targets]
            if others:                  # shared by now: a copy with the earlier values for these spools only
                f = _new_filament(sm, rev["values_before"])
                for s in targets:
                    sm.patch(f"spool/{s}", put_weight({"filament_id": f["id"]}, s))
                fl["undo_to"] = f["id"]
            else:
                sm.patch(f"filament/{fl['from']}", fl["edited"])
                for s in targets:
                    p = put_weight({}, s)
                    if p:
                        sm.patch(f"spool/{s}", p)
        back_to = fl.get("undo_to") or fl["from"]
        if rev.get("split_from") is not None:           # the split-off spools go back to the item they came from
            src = rec["saved"][rev["split_from"]]
            part = rec["saved"][rev["item"]]
            if back_to == src.get("filament_id"):
                src["spool_ids"] = src["spool_ids"] + part["spool_ids"]
                part["spool_ids"] = []
            else:                       # on a copy of the filament now: an item of their own, with the earlier values
                part["values"], part["filament_id"] = dict(rev["values_before"]), back_to
        else:
            it = rec["saved"][rev["item"]]
            it["values"] = dict(rev["values_before"])
            it["filament_id"] = back_to
        rev["undone"] = True
        rec["state"] = rev.get("state_before") or "detected"
        rec["proposals"] = {}
        _save(rec)
        log.info("intake history: record %s revision %d undone", rid, rev["n"])
    _rebuild([])
    return get(rid)
