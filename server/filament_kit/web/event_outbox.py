"""The web unit's hand-over of its spool events to the Hub (R80 E1, EA4b).

The phone web app and the connector's tools change spools in this process (`inventory` reports each change to
`event_sink`). The Hub's event store is written by the Hub only, so this unit's sink (`OutboxSink`) appends each
`spool.*` event to an outbox, `events-outbox.xml` in the web unit's folder (0600, atomic, under a lock, never through a
symbolic link: the rules of push.xml), and a background `Sender` posts them to the Hub's `POST api/events/web` through
the unit's channel to the Hub (`slots.KitApi`).

At least once: an item leaves the outbox only after the Hub accepted it, and a resent item is not written twice (the
Hub holds an event with the same time, kind, subject, actor and values once). The `at` is made when the change is
made, so a resend carries the same one. The Hub validates a batch all or none and names the item ("event 2 of 3"): that
item is moved to `events-outbox-rejected.xml` (kept for the owner, capped) and the rest is sent. While the Hub does not
answer the sender retries with a growing wait. An item is dropped, with a log line, after MAX_AGE or when the outbox
holds more than MAX_ITEMS. Nothing here raises into the request that changed the spool.
"""
from __future__ import annotations

import errno
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import config, event_sink, events
from .slots import SlotError

log = logging.getLogger(__name__)

PATH = "/api/events/web"
MAX_ITEMS = 500             # items kept (R80 E1); over it the oldest are dropped
MAX_AGE = 7 * 86400         # seconds an item is kept while the Hub does not take it
MAX_REJECTED = 100          # items kept in the rejected file
BATCH = 100                 # items per call (the Hub takes 500)
IDLE = 60.0                 # seconds the sender sleeps with nothing to do (an add wakes it)
BACKOFF = (5.0, 300.0)      # first and longest wait after a failed call
ACTOR_PHONE = {"type": "device", "id": "web-app", "name": "phone web app"}   # who the Hub records for the phone's changes
_WHICH = re.compile(r"event (\d+) of (\d+)")


class Outbox:
    """The items waiting for the Hub, in order. The list in memory is the truth while this process runs; every change
    is written through to `path` (a failed write is logged and the list stays in memory)."""

    def __init__(self, path: Path | str | None = None, rejected: Path | str | None = None, *,
                 max_items: int = MAX_ITEMS, max_age: float = MAX_AGE, clock=time.time):
        self.path = Path(path) if path else config.paths().web / "events-outbox.xml"
        self.rejected = Path(rejected) if rejected else self.path.with_name("events-outbox-rejected.xml")
        self.max_items, self.max_age, self.clock = max_items, max_age, clock
        self.lock = threading.Lock()
        self._items: list[dict] | None = None
        self._next = 1

    # ---- the file
    def _read(self, f: Path) -> tuple[list[dict], int]:
        try:
            raw = events._read_bytes(f)
        except FileNotFoundError:
            return [], 1
        except (OSError, events.EventError) as e:
            raise ValueError(str(e)) from None
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise ValueError(f"not valid XML ({e})") from None
        items, top = [], 0
        for el in root.findall("event"):
            try:
                n, queued = int(el.get("n")), float(el.get("queued"))
            except (TypeError, ValueError):
                continue
            sub, act, data = el.find("subject"), el.find("actor"), el.find("data")
            if not el.get("kind") or not el.get("at"):
                continue
            items.append({"n": n, "queued": queued, "kind": el.get("kind"), "at": el.get("at"),
                          "subject": dict(sub.attrib) if sub is not None else {},
                          "actor": dict(act.attrib) if act is not None else {},
                          "data": {v.get("name"): v.text or "" for v in data.findall("v")} if data is not None else {}})
            top = max(top, n)
        try:
            nxt = int(root.get("next") or 0)
        except ValueError:
            nxt = 0
        return items, max(nxt, top + 1)

    def _write(self, f: Path, items: list[dict], nxt: int) -> None:
        root = ET.Element("outbox", version="1", next=str(nxt))
        for it in items:
            el = ET.SubElement(root, "event", n=str(it["n"]), queued=f"{it['queued']:.0f}", kind=events._text(it["kind"]),
                               at=events._text(it["at"]))
            ET.SubElement(el, "subject", {k: events._text(v) for k, v in it["subject"].items()})
            ET.SubElement(el, "actor", {k: events._text(v) for k, v in it["actor"].items()})
            d = ET.SubElement(el, "data")
            for k, v in it["data"].items():
                ET.SubElement(d, "v", name=events._text(k)).text = events._text(v)
        data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        f.parent.mkdir(parents=True, exist_ok=True)
        with events._FileLock(f.with_name("events-outbox.lock"), needed=True):
            events._refuse_link(f)
            for _ in range(20):
                tmp = events._tmp_name(f)
                try:
                    fd = events._open(tmp, events._NEW, 0o600)
                    break
                except FileExistsError:
                    continue
            else:
                raise OSError(errno.EEXIST, "no free name for the temporary file")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                events._replace(tmp, f)
                events._sync_dir(f.parent)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def _load(self) -> list[dict]:
        if self._items is None:
            try:
                self._items, self._next = self._read(self.path)
            except ValueError as e:         # not ours to guess at: keep it aside for the owner and start empty
                log.warning("the event outbox cannot be used (%s); it is kept as %s.unreadable", e, self.path.name)
                try:
                    os.replace(self.path, self.path.with_name(self.path.name + ".unreadable"))
                except OSError:
                    pass
                self._items, self._next = [], 1
        return self._items

    def _save(self) -> None:
        try:
            self._write(self.path, self._items, self._next)
        except (OSError, events.EventError) as e:
            log.warning("the event outbox could not be written (%s); its items are kept in memory", e)

    def _prune(self) -> bool:
        items = self._items
        before = len(items)
        old = self.clock() - self.max_age
        for it in [i for i in items if i["queued"] < old]:
            log.warning("event %s of %s dropped: the Hub did not take it within %d days", it["kind"], it["at"],
                        round(self.max_age / 86400))
            items.remove(it)
        while len(items) > self.max_items:
            it = items.pop(0)
            log.warning("event %s of %s dropped: more than %d events wait for the Hub", it["kind"], it["at"],
                        self.max_items)
        return len(items) != before

    # ---- the use
    def add(self, kind: str, subject: dict, actor: dict | None, data: dict, at: str) -> None:
        with self.lock:
            items = self._load()
            items.append({"n": self._next, "queued": self.clock(), "kind": kind, "at": at,
                          "subject": {k: str(v) for k, v in (subject or {}).items() if v is not None},
                          "actor": {k: str(v) for k, v in (actor or {}).items() if v is not None},
                          "data": {k: str(v) for k, v in (data or {}).items() if v is not None}})
            self._next += 1
            self._prune()
            self._save()

    def pending(self, limit: int = BATCH) -> list[dict]:
        """The first `limit` items (copies), after dropping the ones too old."""
        with self.lock:
            items = self._load()
            if self._prune():
                self._save()
            return [dict(i) for i in items[:limit]]

    def __len__(self) -> int:
        with self.lock:
            return len(self._load())

    def done(self, ns) -> None:
        """The Hub took these items."""
        ns = set(ns)
        with self.lock:
            self._items = [i for i in self._load() if i["n"] not in ns]
            self._save()

    def reject(self, item: dict, why: str) -> None:
        """The Hub refused this item for good: out of the queue, into the rejected file (the newest MAX_REJECTED)."""
        log.warning("event %s of %s refused by the Hub and set aside in %s: %s", item["kind"], item["at"],
                    self.rejected.name, why)
        with self.lock:
            try:
                old, nxt = self._read(self.rejected)
                self._write(self.rejected, (old + [item])[-MAX_REJECTED:], nxt)
            except (ValueError, OSError, events.EventError) as e:
                log.warning("the rejected event could not be kept (%s)", e)
            self._items = [i for i in self._load() if i["n"] != item["n"]]
            self._save()

    @staticmethod
    def body(item: dict) -> dict:
        out = {"kind": item["kind"], "at": item["at"], "subject": item["subject"], "data": item["data"]}
        if item["actor"].get("type") in ("device", "connector"):    # no actor: the Hub names the unit's own pairing
            out["actor"] = item["actor"]
        return out


class OutboxSink(event_sink.NullSink):
    """The web unit's event sink: `spool.*` events into the outbox; anything else is not the web unit's to hand over."""

    def __init__(self, outbox: Outbox, wake=None):
        self.outbox, self.wake = outbox, wake

    def write(self, kind, subject, actor=None, data=None, **kw):
        try:
            if not str(kind).startswith("spool."):
                return None
            if isinstance(subject, str):
                subject = {"type": subject}
            at = events._utc(kw.get("now")).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.outbox.add(kind, subject or {"type": "spool"}, actor if isinstance(actor, dict) else None, data or {}, at)
            if self.wake is not None:
                self.wake.set()
        except Exception:  # noqa: BLE001 - a spool change must not fail because its history could not be queued
            log.exception("event %s not queued", kind)
        return None


class Sender(threading.Thread):
    """Posts the outbox to the Hub: batches of up to `batch`, in order, until it is empty; then it sleeps until an add
    (or `idle`). A call that fails is retried after a wait that doubles up to the longest."""

    def __init__(self, outbox: Outbox, kit, *, batch: int = BATCH, idle: float = IDLE, backoff=BACKOFF):
        super().__init__(name="event-outbox", daemon=True)
        self.outbox, self.kit, self.batch, self.idle, self.backoff = outbox, kit, batch, idle, backoff
        self.wake = threading.Event()
        self.stop_flag = threading.Event()

    def _post(self, items: list[dict]) -> None:
        kit = self.kit() if callable(self.kit) else self.kit
        kit.post(PATH, {"events": [Outbox.body(i) for i in items]})

    def flush(self) -> bool:
        """Send everything waiting; False when the Hub did not take it (the rest stays). Never raises."""
        try:
            while not self.stop_flag.is_set():
                items = self.outbox.pending(self.batch)
                if not items:
                    return True
                try:
                    self._post(items)
                except SlotError as e:
                    if e.http != 400:
                        log.warning("event outbox: the Hub did not take %d events: %s", len(items), e)
                        return False
                    if not self._quarantine(items, e):
                        return False
                    continue
                self.outbox.done(i["n"] for i in items)
            return False
        except Exception as e:  # noqa: BLE001 - the sender never dies and never reaches a request
            log.warning("event outbox: %s: %s", type(e).__name__, e)
            return False

    def _quarantine(self, items: list[dict], err: SlotError) -> bool:
        """The Hub refused the batch (400, all or none). It names the bad item ("event 2 of 3"): that one is set
        aside. When it does not (or names nothing in this batch) each item is sent alone to find the bad ones."""
        m = _WHICH.search(str(err))
        if m and int(m.group(2)) == len(items) and 1 <= int(m.group(1)) <= len(items):
            self.outbox.reject(items[int(m.group(1)) - 1], str(err))
            return True
        for it in items:
            try:
                self._post([it])
            except SlotError as e:
                if e.http != 400:
                    log.warning("event outbox: the Hub did not take an event: %s", e)
                    return False
                self.outbox.reject(it, str(e))
            else:
                self.outbox.done([it["n"]])
        return True

    def run(self) -> None:
        wait = self.backoff[0]
        while not self.stop_flag.is_set():
            if self.flush():
                wait = self.backoff[0]
                self.wake.wait(self.idle)
                self.wake.clear()
            else:
                self.stop_flag.wait(wait)
                wait = min(wait * 2, self.backoff[1])

    def stop(self) -> None:
        self.stop_flag.set()
        self.wake.set()


class Handover:
    """What the web app runs: the outbox, its sink and its sender, started and stopped with the app."""

    def __init__(self, kit=None, outbox: Outbox | None = None, **sender_kw):
        self.outbox = outbox if outbox is not None else Outbox()
        self.kit = kit
        self.sender_kw = sender_kw
        self.sender: Sender | None = None
        self._before = None

    def _kit(self):
        if self.kit is None:
            from .slots import KitApi
            self.kit = KitApi()
        return self.kit

    def start(self) -> None:
        self.sender = Sender(self.outbox, self._kit, **self.sender_kw)
        self._before = event_sink.sink()
        event_sink.set_sink(OutboxSink(self.outbox, self.sender.wake))
        self.sender.start()

    def stop(self) -> None:
        if self.sender is not None:
            self.sender.stop()
            self.sender.join(5)
        event_sink.set_sink(self._before)
