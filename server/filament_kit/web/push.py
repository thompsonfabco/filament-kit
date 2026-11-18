"""Web Push for the phone web app. Imported only when `web.push` is true (default false); with it off no code in this
module runs and the page shows no push control. It sends the Hub's alert events (R80): one notification per event, a
condition once while it lasts, and an alert that ends is replaced by the ending event's own quiet notification.

Needs internet egress from the web unit to the browsers' push services (Apple / Google / Mozilla / Windows): the
owner decides that; the kit changes no firewall rule. Subscriptions are kept in `FK_STATE/web/push.xml` (0600; the
phones of the old push.json are read into it once), only for endpoints on the allow-list below (the same as the h2d-filament-scanner remote's). Sending uses the optional
`pywebpush` package (extra `push`), imported when the first alert goes out; the VAPID key is made on first use
(`FK_STATE/web/vapid.pem`, 0600).
"""
from __future__ import annotations

import base64
import errno
import hashlib
import json
import logging
import os
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

from .. import config, events

log = logging.getLogger(__name__)

PUSH_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")
MAX_SUBS = 10
FEED_WAIT = 20.0        # seconds one wait on the Hub's events may last (the channel to the Hub times out at 30)
REPLACE_TTL = 3600      # seconds a replacement (the notification of an ended alert) may wait: a day-late ending is noise
FEED_RETRY = 10.0       # seconds before asking again after the Hub did not answer
TEST_EVERY = 30.0       # seconds between "test" alerts
TEST_BUDGET = 20.0      # seconds the test alert may take in all, however many subscriptions
REPLACED_BY_ENDING = ("print-paused", "device-down")   # the conditions whose ending is news (R80 20:48): not storage, not low
TAG_CONDITION, TAG_EVENT = "sw-condition-", "sw-event-"   # the notification tags alerts.js uses, so the page can tidy up
NO_TOPIC: set[str] = set()   # push services (host) that refused the Topic header: it is left out for them from then on
NOT_INSTALLED = "pywebpush is not installed on the server (pip install 'filament-kit[push]'); alerts cannot be sent"


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("pywebpush") is not None


def endpoint_ok(endpoint) -> bool:
    """https only, and a host that is one of the push services or a subdomain of one (never a look-alike)."""
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def state_dir() -> Path:
    return config.paths().web


class Store:
    """endpoint -> {"info": {endpoint, keys}, "created"}; kept in `push.xml` (the web unit's folder, 0600), written
    atomically through a new file, under a lock, never through a symbolic link (the same rules as events.py). The
    first time `push.xml` is missing the phones in the old `push.json` beside it are read, once, into it; the old
    file is never written, read again or removed."""

    def __init__(self, path: Path | str, legacy: Path | str | None = None):
        self.path = Path(path)
        self.legacy = Path(legacy) if legacy else None
        self.lock = threading.Lock()
        self._mem: dict | None = None    # the migrated list while push.xml could not be written
        self._bad = False                # push.xml exists and could not be read: a save keeps it aside

    def _read_xml(self) -> dict | None:
        """The subscriptions in push.xml; None when the file does not exist; ValueError when it cannot be used."""
        try:
            raw = events._read_bytes(self.path)
        except FileNotFoundError:
            return None
        except (OSError, events.EventError) as e:
            raise ValueError(str(e)) from None
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise ValueError(f"not valid XML ({e})") from None
        subs: dict = {}
        for el in root.findall("sub"):
            ep, p256dh, auth = el.get("endpoint"), el.get("p256dh"), el.get("auth")
            if endpoint_ok(ep) and p256dh and auth:
                try:
                    created = float(el.get("created") or 0)
                except ValueError:
                    created = 0.0
                subs[ep] = {"info": {"endpoint": ep, "keys": {"p256dh": p256dh, "auth": auth}}, "created": created}
        return subs

    def _read_legacy(self) -> dict:
        try:
            d = json.loads(self.legacy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        subs = d.get("subs") if isinstance(d, dict) else None
        out: dict = {}
        for ep, sub in (subs.items() if isinstance(subs, dict) else ()):
            try:
                info = check_subscription(sub["info"])
                created = float(sub.get("created") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            out[info["endpoint"]] = {"info": info, "created": created}
        return out

    def _load(self) -> dict:
        try:
            subs = self._read_xml()
        except ValueError as e:
            if not self._bad:
                log.warning("push.xml cannot be used (%s); no phone gets alerts until it is fixed or a phone "
                            "subscribes again (the file is kept as push.xml.unreadable)", e)
            self._bad = True
            return {}
        self._bad = False
        if subs is not None:
            self._mem = None
            return subs
        if self._mem is not None:
            return self._mem
        if self.legacy is None:
            return {}
        subs = self._read_legacy()          # the old file, read this once: from now on push.xml is the list
        if subs:
            try:
                self._save(subs)
            except (OSError, events.EventError) as e:
                log.warning("push.xml could not be written (%s); the phones of push.json are kept in memory", e)
                self._mem = subs
        return subs

    def _save(self, subs: dict) -> None:
        root = ET.Element("push", version="1")
        for ep, sub in subs.items():
            k = sub["info"]["keys"]
            ET.SubElement(root, "sub", endpoint=events._text(ep), p256dh=events._text(k["p256dh"]),
                          auth=events._text(k["auth"]), created=f"{sub.get('created') or 0:.0f}")
        data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        f = self.path
        f.parent.mkdir(parents=True, exist_ok=True)
        with events._FileLock(f.with_name("push.lock"), needed=True):
            events._refuse_link(f)
            if self._bad:
                os.replace(f, f.with_name(f.name + ".unreadable"))
                self._bad = False
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
        self._mem = None

    def subs(self) -> dict:
        with self.lock:
            return dict(self._load())

    def add(self, info: dict) -> None:
        with self.lock:
            d = self._load()
            if info["endpoint"] not in d and len(d) >= MAX_SUBS:
                raise ValueError(f"too many subscribed phones ({MAX_SUBS}); unsubscribe one first")
            d[info["endpoint"]] = {"info": {"endpoint": info["endpoint"], "keys": info["keys"]},
                                   "created": time.time()}
            self._save(d)

    def remove(self, *endpoints: str) -> None:
        with self.lock:
            d = self._load()
            for ep in endpoints:
                d.pop(ep, None)
            self._save(d)


def check_subscription(sub) -> dict:
    """The subscription object the browser made -> {endpoint, keys}; ValueError for anything else."""
    if not isinstance(sub, dict) or not endpoint_ok(sub.get("endpoint")):
        raise ValueError("unsupported push service")
    keys = sub.get("keys")
    if not isinstance(keys, dict) or not isinstance(keys.get("p256dh"), str) or not keys["p256dh"] \
            or not isinstance(keys.get("auth"), str) or not keys["auth"]:
        raise ValueError("subscription has no keys")
    return {"endpoint": sub["endpoint"], "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}


def vapid() -> tuple[str, str]:
    """(private key PEM path, applicationServerKey as base64url); generated on first use."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    path = state_dir() / "vapid.pem"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        tmp = path.with_name("vapid.pem.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        os.replace(tmp, path)
    key = serialization.load_pem_private_key(path.read_bytes(), None)
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return str(path), base64.urlsafe_b64encode(pub).rstrip(b"=").decode()


def topic_of(tag: str) -> str:
    """The Topic header for a tag: at most 32 characters of URL-safe base64 (a hash, so any tag fits). A push service
    that honours it replaces a message it still holds with the same Topic by the newer one."""
    return base64.urlsafe_b64encode(hashlib.sha256(tag.encode("utf-8")).digest()).rstrip(b"=").decode()[:32]


def webpush_sender(subject: str):
    """sender(info, payload, topic=None, ttl=None) -> HTTP status, through pywebpush (imported here, so a missing
    package only fails when an alert is sent)."""
    def send(info: dict, payload: str, topic: str | None = None, ttl: int | None = None) -> int:
        from pywebpush import WebPushException, webpush
        try:
            r = webpush(info, payload, vapid_private_key=vapid()[0], ttl=ttl or 6 * 3600, vapid_claims={"sub": subject},
                        headers={"Urgency": "high", **({"Topic": topic} if topic else {})}, timeout=10)
            return int(getattr(r, "status_code", 201))
        except WebPushException as e:
            return int(getattr(e.response, "status_code", 0) or 0)
    return send


def _topic_refused(code: int) -> bool:
    """A 4xx that may be the push service refusing the Topic header (not 'gone' 404/410, not 'slow down' 429)."""
    return 400 <= code < 500 and code not in (404, 410, 429)


def send_all(store: Store, title: str, body: str, tag: str, *, sender, url: str = "",
             budget: float | None = None, replace: bool = False) -> dict:
    """Send one alert to every subscription; the ones the push service says are gone (404 / 410) are dropped.
    {"sent": how many the push services took, "failed": [what went wrong, one line each], "removed": how many were
    dropped}. `budget` is the most seconds to spend, counted from when the subscriptions have been read: the
    subscriptions left after it are not tried, but the first one always is. `replace`: the notification of an ended
    alert: same tag, silent, no new alert sound (`renotify` false), a short TTL. Every push carries a Topic made from
    its tag; a service that answers 4xx to it gets the push once more without it and, when that is taken, is not sent
    the Topic again."""
    subs = store.subs()
    deadline = None if budget is None else time.monotonic() + budget
    payload = json.dumps({"title": title, "body": body, "tag": tag, "url": url,
                          **({"silent": True, "renotify": False} if replace else {})})
    topic, ttl = topic_of(tag), (REPLACE_TTL if replace else None)
    dead = []
    sent, failed = 0, []
    for n, (ep, sub) in enumerate(subs.items()):
        if n and deadline is not None and time.monotonic() > deadline:
            failed.append(f"{urlparse(ep).hostname} not tried: out of time")
            continue
        host = (urlparse(ep).hostname or "").lower()
        try:
            use = None if host in NO_TOPIC else topic
            code = sender(sub["info"], payload, topic=use, ttl=ttl)
            if use and _topic_refused(code):
                again = sender(sub["info"], payload, topic=None, ttl=ttl)
                if 0 < again < 400:
                    NO_TOPIC.add(host)
                    log.info("push service %s refused the Topic header: left out for it from now on", host)
                code = again
        except Exception as e:  # noqa: BLE001 - one dead service must not stop the rest
            log.warning("push to %s failed: %s", urlparse(ep).hostname, type(e).__name__)
            failed.append(f"cannot reach {urlparse(ep).hostname} ({type(e).__name__})")
            continue
        if code in (404, 410):
            dead.append(ep)
        elif code >= 400 or code == 0:
            log.warning("push to %s answered %s", urlparse(ep).hostname, code)
            failed.append(f"{urlparse(ep).hostname} answered {code}" if code else f"no answer from {urlparse(ep).hostname}")
        else:
            sent += 1
    if dead:
        store.remove(*dead)
    return {"sent": sent, "failed": failed, "removed": len(dead)}


def event_text(event: dict) -> tuple[str, str]:
    """(title, one body line) of an alert event. STUB until the batch: it reads the `title` and `text` the Hub's
    GET api/events builds for each event (EA3's function does it there); swap to EA3's own text function then."""
    title = event.get("title") or event.get("kind") or "Alert"
    return str(title), str(event.get("text") or "")


def event_url(base: str, event: dict) -> str:
    """The place that fixes it, as an address under the web app's `base`. STUB for the places the phone web app does
    not have (EA7 decides): the printer's page for `printer`, the app's home for any other."""
    action = event.get("action") or {}
    if action.get("place") == "printer" and action.get("id"):
        return f"{base}/#printers/{quote(str(action['id']), safe='')}"
    return base + "/"


class Feed(threading.Thread):
    """Waits on the Hub's events (GET api/events, through the web unit's channel to the Hub) and sends each alert to
    the subscriptions. It starts from the newest event the Hub has, kept in memory: history is never replayed."""

    def __init__(self, kit, store: Store, sender, url: str, wait: float = FEED_WAIT, retry: float = FEED_RETRY):
        super().__init__(name="push-feed", daemon=True)
        self.kit, self.store, self.sender, self.url, self.wait, self.retry = kit, store, sender, url, wait, retry
        self.last: int | None = None
        self.raised: dict[str, str] = {}    # condition key -> severity of the raise a phone was told about
        self.stop_flag = threading.Event()

    def newest(self) -> int:
        """The id of the newest event the Hub has (read in pages: the answer has no last-id field)."""
        since = 0
        while True:
            r = self.kit.get("/api/events?" + urlencode({"since": since, "limit": 1000}))
            nxt = r.get("next")
            if not r.get("events") or not isinstance(nxt, int) or nxt <= since:
                return since
            since = nxt

    def send(self, event: dict) -> None:
        """One notification for one alert event; a condition that is already raised at that severity sends nothing.
        A condition that ends sends the ending event's own notification in place of the alert's (print paused or
        runout, device down); nothing for any other ending, and no push that shows nothing."""
        cond = event.get("condition") or {}
        key = cond.get("key") if isinstance(cond, dict) else None
        if key and cond.get("state") != "raised":
            if self.raised.pop(key, None) is not None and key.split(":")[0] in REPLACED_BY_ENDING and event.get("title"):
                title, body = event_text(event)     # the ending's own notification takes the alert's place, quietly
                send_all(self.store, title, body, TAG_CONDITION + key, sender=self.sender,
                         url=event_url(self.url.rstrip("/"), event),
                         replace=True)
            return
        if event.get("alert") is not True:
            return
        if key:
            if self.raised.get(key) == event.get("severity"):
                return
            self.raised[key] = event.get("severity")
        title, body = event_text(event)
        send_all(self.store, title, body, TAG_CONDITION + key if key else f"{TAG_EVENT}{event.get('id')}", sender=self.sender,
                 url=event_url(self.url.rstrip("/"), event))

    def tick(self) -> None:
        if self.last is None:
            self.last = self.newest()
        t0 = time.monotonic()
        r = self.kit.get("/api/events?" + urlencode({"since": self.last, "wait": self.wait}))
        if not r.get("events") and time.monotonic() - t0 < 1.0:
            self.stop_flag.wait(1.0)        # an answer that came at once without news: do not spin
        for ev in r.get("events") or []:
            if not isinstance(ev, dict) or not isinstance(ev.get("id"), int) or ev["id"] <= self.last:
                continue
            try:
                self.send(ev)
            except Exception as e:  # noqa: BLE001 - one bad event must not stop the rest
                log.warning("push of event %s: %s: %s", ev.get("id"), type(e).__name__, e)
            self.last = ev["id"]

    def run(self) -> None:
        while not self.stop_flag.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the Hub is down or restarting: ask again soon
                log.warning("push feed: %s: %s", type(e).__name__, e)
                self.stop_flag.wait(self.retry)
