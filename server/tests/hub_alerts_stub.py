"""A stub Hub for the Hub page's alert places (EA6 phase A): the real test Hub of test_hub_page_audit.py, with the routes of
docs 03 section 15 that the server step (EA3) has not made yet answered here (events, alerts, settings/alerts, alerts/test, spools/low,
storage-use), and with the new page modules loaded into the page the way phase B will load them (scripts, stylesheets, and a
page-side stand-in for the registry edits: server/tests/hub_alerts/harness.js). Everything else goes to the real Hub.

The browser steers the stub through POST /stub/set (a JSON patch of the state) and reads GET /stub/calls (what the page sent)."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qs

from filament_kit.setup_page import STATIC
from test_setup_page import CODE

SHARED = STATIC.parent / "shared_static"
HARNESS = Path(__file__).with_name("hub_alerts") / "harness.js"
SCRIPTS = ["setup_alertbar.js", "setup_overview_alerts.js", "setup_alerts.js"]
KEYS = ["runout", "paused", "failed", "printer_error", "finished", "storage", "running_low", "device_down"]
DEFAULT_ON = {"runout", "paused", "failed", "printer_error", "storage", "running_low"}


def alerts_state(**over):
    return {"types": [{"key": k, "title": k, "on": k in DEFAULT_ON} for k in KEYS], "last_spool_only": False, "running_low_g": 150,
            "storage_warn_percent": 85, "storage_bad_percent": 95, **over}


def spool(i, grams=80, **over):
    return {"id": i, "filament": f"PolyTerra PLA Charcoal {i}", "material": "PLA", "color": "2B2B2E", "remaining_g": grams,
            "location": "Rack 1", "in_stock": 2, "last_one": False, **over}


def storage_state(state="ok", percent=42.0):
    return {"filesystems": [{"path_label": "Hub state", "total": 100_000_000_000, "free": int(100_000_000_000 * (100 - percent) / 100),
                             "percent_used": percent, "state": state}],
            "items": [{"key": "backups", "title": "Backups", "bytes": 4_200_000_000}, {"key": "photos", "title": "Photos", "bytes": 310_000_000},
                      {"key": "label_reader", "title": "Label Reader", "bytes": 1_900_000_000}, {"key": "events", "title": "Events and logs", "bytes": 52_000_000}]}


def fresh():
    return {"events": [], "conditions": [], "test": None, "alerts": alerts_state(), "low": {"threshold_g": 150, "spools": []},
            "storage": storage_state(), "fail": {}, "delay": {}, "refuse": None, "calls": []}


ROUTES = {"events": "GET", "alerts": "GET", "settings/alerts": "POST", "alerts/test": "POST", "spools/low": "GET", "storage-use": "GET"}


class StubHub:
    """ASGI wrapper around the Hub's app. `state` is reset with POST /stub/set {"reset": true, ...patch}."""

    def __init__(self, app):
        self.app = app
        self.state = fresh()

    async def reply(self, send, status, body, ctype=b"application/json", raw=None):
        raw = raw if raw is not None else json.dumps(body).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", ctype), (b"content-length", str(len(raw)).encode()),
                                                                                  (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": raw})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        if path.startswith("/setup/_new/"):
            name = path.rsplit("/", 1)[-1]
            src = HARNESS if name == "harness.js" else (STATIC / name) if (STATIC / name).exists() else SHARED / name
            return await self.reply(send, 200, None, b"text/css" if name.endswith(".css") else b"text/javascript", src.read_bytes())
        if path.startswith("/stub/"):
            return await self.stub(path, receive, send)
        if path.startswith("/setup/api/") and ROUTES.get(path[len("/setup/api/"):]) == method:
            return await self.route(path[len("/setup/api/"):], method, scope, receive, send)
        if path == "/setup" and method == "GET":
            return await self.page(scope, receive, send)
        await self.app(scope, receive, send)

    async def body(self, receive):
        raw = b""
        while True:
            m = await receive()
            raw += m.get("body", b"")
            if not m.get("more_body"):
                return json.loads(raw or b"{}")

    async def stub(self, path, receive, send):
        if path == "/stub/set":
            patch = await self.body(receive)
            if patch.pop("reset", False):
                self.state = fresh()
            self.state.update(patch)
            return await self.reply(send, 200, {"ok": True})
        return await self.reply(send, 200, self.state["calls"])

    async def route(self, name, method, scope, receive, send):
        st = self.state
        body = await self.body(receive) if method == "POST" else None
        st["calls"].append({"name": name, "query": scope["query_string"].decode(), "body": body, "at": time.time()})
        if st["delay"].get(name):
            await asyncio.sleep(st["delay"][name])
        if name in st["fail"]:
            return await self.reply(send, st["fail"][name], {"error": "the stub says no"})
        if name == "events":
            q = parse_qs(scope["query_string"].decode())
            since = int(q["since"][0]) if "since" in q else 0
            test, st["test"] = st["test"], None
            top = max([e["id"] for e in st["events"]] + [since])
            return await self.reply(send, 200, {"events": [e for e in st["events"] if e["id"] > since], "next": top, "oldest": 1, "gap": False,
                                                "test": test, "conditions": st["conditions"]})
        if name == "alerts":
            return await self.reply(send, 200, st["alerts"])
        if name == "settings/alerts":
            if body.get("code") != CODE:
                return await self.reply(send, 403, {"error": "wrong code", "field": "code"})
            if st["refuse"]:
                return await self.reply(send, 400, st["refuse"])
            st["alerts"] = alerts_state(types=body["types"], last_spool_only=body["last_spool_only"], running_low_g=body["running_low_g"],
                                        storage_warn_percent=body["storage_warn_percent"])
            return await self.reply(send, 200, st["alerts"])
        if name == "alerts/test":
            st["test"] = {"title": "Test alert", "text": "This is a test from the Hub."}
            return await self.reply(send, 200, {"ok": True})
        return await self.reply(send, 200, st["low"] if name == "spools/low" else st["storage"])

    async def page(self, scope, receive, send):
        """The real page, with the new modules loaded after its own scripts (phase B adds them to setup_page.py)."""
        chunks, start = [], []

        async def grab(message):
            if message["type"] == "http.response.start":
                start.append(message)
            else:
                chunks.append(message.get("body", b""))
        await self.app(scope, receive, grab)
        html = b"".join(chunks).decode("utf-8")
        links = "<link rel=stylesheet href='/setup/_new/alerts.css'><link rel=stylesheet href='/setup/_new/setup_alerts.css'>"
        scripts = "<script defer src='/setup/_new/alerts.js'></script>" + "".join(f"<script src='/setup/_new/{n}'></script>" for n in [*SCRIPTS, "harness.js"])
        html = html.replace("<body>", links + "<body>", 1).replace("</body>", scripts + "</body>", 1)
        raw = html.encode("utf-8")
        head = start[0]
        head["headers"] = [(k, v) for k, v in head["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(raw)).encode())]
        await send(head)
        await send({"type": "http.response.body", "body": raw})


# ----- what the three test files share: the fixture, the driver and the page-side helpers -----
import pytest  # noqa: E402

from test_hub_page_audit import _serve, hub_app  # noqa: E402,F401
from test_hub_presets_ui import AsHttps, T, _drive  # noqa: E402,F401

PRELUDE = r"""
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 200; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what + "; the page shows: " + document.querySelector("main").innerText.slice(0, 300)); }
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const text = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : null);
const shown = (el) => !!el && el.getClientRects().length > 0;
const stub = (patch) => fetch("/stub/set", { method: "POST", body: JSON.stringify(patch) });
const calls = async (name) => (await (await fetch("/stub/calls")).json()).filter((c) => !name || c.name === name);
const ready = async () => {
  await until(() => $(".page-head__title") && $(".alert-host") && !$(".chip--lock .skeleton__line") && !$('main [aria-busy="true"]:not(button)'), "the page");
  await sleep(300);
};
const ev = (id, kind, o = {}) => ({ id, at: new Date().toISOString(), kind, severity: "warn", subject: { type: "printer", id: "00M00A000000001", name: "Workshop X1" },
  actor: null, data: { job: "gear.3mf", percent: 42 }, condition: null, alert: true, title: "", text: "", action: { place: "printer", id: "00M00A000000001" }, ...o });
const pageW = () => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth });
const look = async (name) => { document.documentElement.setAttribute("data-look", name); await sleep(250); };
const unlock = () => SW.setLock("unlocked", { code: "__CODE__" });
"""


@pytest.fixture
def hub_stub(hub_app):  # noqa: F811
    """(the stub Hub, the page's address): the real test Hub behind the stub routes of docs 03 section 15."""
    app = StubHub(AsHttps(hub_app[0]))
    running = _serve(app, hub_app[1])
    try:
        yield app, running.url + "/setup"
    finally:
        running.stop()


def drive(hub_stub, tmp_path, body, width=1280, query="", look="console"):
    """Runs `body` in the page (async, `return out`); the look is set once the page stands."""
    app, url = hub_stub
    script = PRELUDE + f'\nawait ready();\nawait look("{look}");\nconst out = {{}};\n' + body + "\nreturn out;\n"
    return _drive(url + query, tmp_path, script, width=width)
