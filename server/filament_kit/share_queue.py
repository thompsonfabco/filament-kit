"""Queueing corrections for the Share corrections setting (plan 2026-11-14-2200 section 5, V1.3; design 03 6.x, 10.5.2).

When `label_reader.share_corrections` is on and the reader on this Hub keeps a correction queue (API 1.1), a record
whose saved values differ from what the label reader read is queued on the reader: the record's stored photos, the
reading as predicted, the values as saved now (corrected), where the reading came from (`local` or `cloud`) and the
record id (the last two only when the reader says it takes them). One entry per record item: the key is the record
id for the first item, `<id>.<n>` for the others; the reader replaces an entry of the same key.

`schedule(rid)` is called after a save by intake_history: `record_save` (a field changed before Add), `apply` (a hand
edit or an accepted suggestion) and `undo`. All three come to `sync`, which makes the record's entries match its
values: queue what differs, delete the entry of an item that no longer differs. It runs in a background thread and
never raises into the save.

The record keeps `share.json` beside record.json (so retention removes it with the record):
    {"entries": {key: reader entry id | None}, "failed": {"reason": str, "at": iso} | None}
and `state(rid)` is what a record's reply shows: {"state": "waiting" | "not_queued" | "none", "reason": str | None,
"entries": int}. "not_queued" is a failure to talk to the reader (it did not answer, refused, was too small ...);
the settings that make queueing not apply (off, no reader here, no feedback capability, no photo, nothing differs)
are "none", never an error. `retry(rid)` runs `sync` again at once and returns the new state.

No address is ever in a request body (local_reader._check_body)."""
from __future__ import annotations

import json
import logging
import threading

from . import config, local_reader

log = logging.getLogger(__name__)

FILE = "share.json"
INLINE = False                      # tests: run the queueing in the caller's thread
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _lock(rid: str) -> threading.Lock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(rid, threading.Lock())


def _path(rid: str):
    from . import intake_history
    return intake_history._dir(rid) / FILE


def _read(rid: str) -> dict:
    try:
        d = json.loads(_path(rid).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - no file, a bad id or a bad file: nothing waits
        return {"entries": {}, "failed": None}
    ent = d.get("entries") if isinstance(d, dict) and isinstance(d.get("entries"), dict) else {}
    failed = d.get("failed") if isinstance(d, dict) and isinstance(d.get("failed"), dict) else None
    return {"entries": ent, "failed": failed}


def _write(rid: str, st: dict) -> None:
    from .pairing import _write_atomic
    p = _path(rid)
    if not st["entries"] and not st["failed"]:
        p.unlink(missing_ok=True)
        return
    _write_atomic(p, json.dumps(st, indent=1).encode("utf-8"), 0o600, state_owned=True)


def state(rid: str) -> dict:
    """What a record shows: {"state": "waiting" | "not_queued" | "none", "reason", "entries"}. Never raises."""
    st = _read(rid)
    if st["failed"]:
        return {"state": "not_queued", "reason": str(st["failed"].get("reason") or "not queued"),
                "entries": len(st["entries"])}
    if st["entries"]:
        return {"state": "waiting", "reason": None, "entries": len(st["entries"])}
    return {"state": "none", "reason": None, "entries": 0}


def want(cfg: dict) -> bool:
    """Queueing applies: the setting is on, and the reader is the one the kit installed on this Hub."""
    from . import share_corrections
    return share_corrections.saved(cfg) and share_corrections.refusal(cfg) is None


# ---------------------------------------------------------------- what differs

def _norm(k: str, v):
    if v is None or v == "":
        return None
    if k == "color_hex":
        return str(v).lstrip("#").upper()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 3)
    return v.strip() if isinstance(v, str) else v


def _key(rid: str, n: int) -> str:
    return rid if n == 0 else f"{rid}.{n}"


def _wanted(rec: dict) -> dict:
    """{key: (predicted, corrected, source)} for each saved item whose values differ from the stored reading."""
    from .intake_history import FIELDS
    read = rec.get("read") if isinstance(rec.get("read"), dict) else None
    if not read:
        return {}
    items = [i for i in read.get("items") or [] if isinstance(i, dict)]
    eng = read.get("engine") if isinstance(read.get("engine"), dict) else {}
    source = "cloud" if eng.get("reader") == "cloud" else "local"
    out = {}
    for n, s in enumerate(rec.get("saved") or []):
        if n >= len(items) or not isinstance(s, dict) or not s.get("spool_ids"):
            continue
        pred = {k: items[n].get(k) for k in FIELDS}
        cur = {k: (s.get("values") or {}).get(k) for k in FIELDS}
        if any(_norm(k, pred[k]) != _norm(k, cur[k]) for k in FIELDS):
            out[_key(rec["id"], n)] = (pred, cur, source)
    return out


def _wanted_keys(rec: dict) -> list[str]:
    read = rec.get("read") if isinstance(rec.get("read"), dict) else {}
    return [_key(rec["id"], n) for n in range(min(len(read.get("items") or []), len(rec.get("saved") or [])))]


def _note(rec: dict) -> str:
    live = [r for r in rec.get("revisions") or [] if isinstance(r, dict) and not r.get("undone")]
    return str(live[-1].get("note") or "")[:500] if live else ""


# ---------------------------------------------------------------- the queue

def _find(cfg: dict, key: str) -> str | None:
    for e in local_reader.feedback_list(cfg)["entries"]:
        if e.get("record") == key and e.get("id") not in (None, ""):
            return str(e["id"])
    return None


def _forget(cfg: dict, key: str, eid) -> None:
    """Delete the reader's entry for `key`; an entry that is gone already is fine."""
    eid = eid or _find(cfg, key)
    if not eid:
        return
    try:
        local_reader.feedback_delete(cfg, str(eid))
    except local_reader.LocalReaderError as e:
        if e.code != "not_found":
            raise


def sync(rid: str, cfg: dict | None = None) -> dict:
    """Make the reader's entries for the record match its values now; returns `state(rid)`. Never raises."""
    try:
        with _lock(rid):
            return _sync(rid, cfg if cfg is not None else config.load())
    except Exception:  # noqa: BLE001 - queueing must never reach the save
        log.exception("share corrections: record %s", rid)
        return state(rid)


def _sync(rid: str, cfg: dict) -> dict:
    from . import intake_history as ih
    try:
        rec = ih._load(rid)
    except ih.HistoryError:
        return {"state": "none", "reason": None, "entries": 0}
    st = _read(rid)
    on = want(cfg)
    wanted = _wanted(rec) if on else {}
    if wanted and not ih._photos(ih._dir(rid)):
        wanted = {}                         # no photo, no entry
    # the Hub's map is lost (or never was): the reader's list knows the entries of a record that was revised
    lookup = (on and not wanted and not st["entries"] and not st["failed"] and bool(rec.get("revisions"))
              and bool(_wanted_keys(rec)))
    if not wanted and not st["entries"] and not st["failed"] and not lookup:
        return state(rid)
    if wanted or lookup:
        h = local_reader.health(cfg)
        caps = h["capabilities"]
        if not caps.get("feedback"):
            if lookup:
                return state(rid)           # nothing was queued that we know of, and the reader is not asked twice
            if h.get("ok") or caps.get("known_from") != "none":
                wanted = {}                 # a reader without the queue: nothing to do
            else:
                return _fail(rid, st, "the Label Reader did not answer: " + str(h.get("error") or "no answer"))
    try:
        if lookup and caps.get("source_record"):
            st["entries"] = {k: None for k in _wanted_keys(rec) if _find(cfg, k)}
        for key, eid in list(st["entries"].items()):
            if key not in wanted:           # no longer differs (Undo, or edited back): its entry goes
                _forget(cfg, key, eid)
                del st["entries"][key]
        if wanted:
            images = [p.read_bytes() for p in ih._photos(ih._dir(rid))]
            for key, (pred, cur, source) in wanted.items():
                if st["entries"].get(key) and not caps.get("source_record"):
                    _forget(cfg, key, st["entries"][key])       # a reader that cannot replace by record
                out = local_reader.feedback_add(cfg, images, pred, cur, _note(rec), source=source, record=key,
                                                caps=caps)
                eid = out.get("id") if isinstance(out, dict) else None
                st["entries"][key] = str(eid) if eid not in (None, "") else None
    except local_reader.LocalReaderError as e:
        return _fail(rid, st, str(e))
    st["failed"] = None
    _write(rid, st)
    return state(rid)


def _fail(rid: str, st: dict, reason: str) -> dict:
    import datetime
    log.warning("share corrections: record %s not queued: %s", rid, reason)
    st["failed"] = {"reason": reason[:300], "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        _write(rid, st)
    except Exception:  # noqa: BLE001
        log.exception("share corrections: cannot keep the state of record %s", rid)
    return state(rid)


def schedule(rid) -> None:
    """After a save: queue in the background when it applies. Never raises, never waits for the reader."""
    try:
        if not isinstance(rid, str):
            return
        if not (want(config.load()) or _read(rid)["entries"] or _read(rid)["failed"]):
            return
        if INLINE:
            sync(rid)
        else:
            threading.Thread(target=sync, args=(rid,), name="share-corrections", daemon=True).start()
    except Exception:  # noqa: BLE001
        log.exception("share corrections: cannot schedule record %s", rid)


def retry(rid: str) -> dict:
    """Try again now (V1.4's route calls this for a record shown as not queued); returns `state(rid)`."""
    return sync(rid)
