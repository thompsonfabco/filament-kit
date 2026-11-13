"""Web Push for the Printers tab. Imported only when `web.push` is true (default false); with it off no code in this
module runs and the page shows no push control.

Needs internet egress from the web unit to the browsers' push services (Apple / Google / Mozilla / Windows): the
owner decides that; the kit changes no firewall rule. Subscriptions are kept in `FK_STATE/web/push.json` (0600),
only for endpoints on the allow-list below (the same as the h2d-filament-scanner remote's). Sending uses the optional
`pywebpush` package (extra `push`), imported when the first alert goes out; the VAPID key is made on first use
(`FK_STATE/web/vapid.pem`, 0600).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from .. import config

log = logging.getLogger(__name__)

PUSH_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")
LIVE = ("RUNNING", "PAUSE", "PREPARE")
MAX_SUBS = 10
TEST_EVERY = 30.0       # seconds between "test" alerts
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
    """endpoint -> {"info": {endpoint, keys}, "created"}; written atomically, 0600."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) and isinstance(d.get("subs"), dict) else {"subs": {}}
        except (OSError, ValueError):
            return {"subs": {}}

    def _save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def subs(self) -> dict:
        with self.lock:
            return dict(self._load()["subs"])

    def add(self, info: dict) -> None:
        with self.lock:
            d = self._load()
            if info["endpoint"] not in d["subs"] and len(d["subs"]) >= MAX_SUBS:
                raise ValueError(f"too many subscribed phones ({MAX_SUBS}); unsubscribe one first")
            d["subs"][info["endpoint"]] = {"info": {"endpoint": info["endpoint"], "keys": info["keys"]},
                                           "created": time.time()}
            self._save(d)

    def remove(self, *endpoints: str) -> None:
        with self.lock:
            d = self._load()
            for ep in endpoints:
                d["subs"].pop(ep, None)
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


def brief(printer: dict, status: dict) -> dict:
    return {"gcode_state": status.get("gcode_state"), "job": status.get("job") or printer.get("name") or "print",
            "percent": status.get("percent") or 0, "stage": status.get("stage") or "",
            "print_error": status.get("print_error") or "",
            "hms": [h.get("code") for h in status.get("hms") or [] if isinstance(h, dict)]}


def transitions(prev: dict | None, cur: dict, *, mapping: bool = False) -> list[tuple[str, str, str]]:
    """(title, body, tag) alerts for one printer between two `brief`s. Nothing on the first sight of a printer.
    `mapping`: the kit is running its slot-mapping (calibration) jobs on it, so job-state changes are not alerts."""
    if prev is None:
        return []
    out = []
    old, new, name = prev.get("gcode_state"), cur.get("gcode_state"), cur.get("job") or "print"
    if new != old and old in LIVE and not mapping:
        if new == "FINISH":
            out.append(("Print finished", name, "job"))
        elif new == "FAILED":
            out.append(("Print stopped", f"{name} at {cur.get('percent', 0)}%", "job"))
        elif new == "PAUSE" and old == "RUNNING":
            out.append(("Print paused", cur.get("stage") or name, "job"))
    seen = {(h["code"] if isinstance(h, dict) else h) for h in prev.get("hms") or []}
    for h in cur.get("hms") or []:
        code = h["code"] if isinstance(h, dict) else h
        if code not in seen:
            out.append(("Printer alert", f"HMS {code}", "hms-" + str(code)))
    err = cur.get("print_error") or ""
    if err and err != (prev.get("print_error") or ""):
        out.append(("Print error", f"Error {err} - {cur.get('stage') or name}", "perr"))
    return out


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


def webpush_sender(subject: str):
    """sender(info, payload) -> HTTP status, through pywebpush (imported here, so a missing package only fails
    when an alert is sent)."""
    def send(info: dict, payload: str) -> int:
        from pywebpush import WebPushException, webpush
        try:
            r = webpush(info, payload, vapid_private_key=vapid()[0], ttl=6 * 3600, vapid_claims={"sub": subject},
                        headers={"Urgency": "high"}, timeout=10)
            return int(getattr(r, "status_code", 201))
        except WebPushException as e:
            return int(getattr(e.response, "status_code", 0) or 0)
    return send


def send_all(store: Store, title: str, body: str, tag: str, *, sender, url: str = "") -> None:
    """Send one alert to every subscription; the ones the push service says are gone (404 / 410) are dropped."""
    payload = json.dumps({"title": title, "body": body, "tag": tag, "url": url})
    dead = []
    for ep, sub in store.subs().items():
        try:
            code = sender(sub["info"], payload)
        except Exception as e:  # noqa: BLE001 - one dead service must not stop the rest
            log.warning("push to %s failed: %s", urlparse(ep).hostname, type(e).__name__)
            continue
        if code in (404, 410):
            dead.append(ep)
        elif code >= 400 or code == 0:
            log.warning("push to %s answered %s", urlparse(ep).hostname, code)
    if dead:
        store.remove(*dead)


class Watcher(threading.Thread):
    """Polls the kit for each configured printer (only while someone is subscribed) and sends the alerts."""

    def __init__(self, kit, store: Store, sender, url: str, interval: float = 10.0):
        super().__init__(name="push-watch", daemon=True)
        self.kit, self.store, self.sender, self.url, self.interval = kit, store, sender, url, interval
        self.prev: dict[str, dict] = {}
        self.stop_flag = threading.Event()

    def tick(self) -> None:
        if not self.store.subs():
            self.prev.clear()
            return
        for p in self.kit.get("/api/printers").get("printers", []):
            if not p.get("configured"):
                continue
            try:
                st = self.kit.get(f"/api/printers/{p['id']}").get("status") or {}
            except Exception:  # noqa: BLE001 - one unreachable printer
                continue
            cur = brief(p, st)
            if cur["gcode_state"] in (None, "", "UNKNOWN"):
                continue  # not online: judge the next tick against the last live state, not against this gap
            try:
                mapping = (self.kit.get(f"/api/printers/{p['id']}/map") or {}).get("state") == "running"
            except Exception:  # noqa: BLE001 - unknown: treat as not mapping
                mapping = False
            for title, body, tag in transitions(self.prev.get(p["id"]), cur, mapping=mapping):
                send_all(self.store, title, body, tag, sender=self.sender, url=self.url)
            self.prev[p["id"]] = cur

    def run(self) -> None:
        while not self.stop_flag.wait(self.interval):
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                log.warning("push watch: %s: %s", type(e).__name__, e)
