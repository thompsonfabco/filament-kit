"""AUT-5 on the Hub page (design 09 S1.11, 07 section 15): the page audit (tests/page_audit.js) in every section of the
Hub page (/setup), Console light and dark, at 1280 px and 320 px, through tests/aut5_run.mjs in a headless Chrome, Edge
or Chromium already on the machine. The page is served with example data only (mockups/CONTENT-SPEC.md: "Workshop hub",
Workshop X1, Garage Voron, Kitchen phone, rd-01) and the printers and Klipper modules on, with fakes for the managers.

Findings of today's markup that a later step rebuilds are listed in tests/aut5_hub_allowlist.txt, one line per section; a
line nothing matches fails the run, and so does a finding that moved to another section. The same skip rules as test_web_app_audit.py: no Node 22 or no browser is a skip (a failure with
AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from filament_kit import api, cli, config, intake_history, library, modules, pairing, reader_tokens, setup_code, setup_helper
from filament_kit.bridge import registry
from filament_kit.spoolman import Spoolman

import test_builds as TB
import test_generate as TG
from fakes import serving
from test_setup_page import CODE, Helper, FakeManager

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests" / "aut5_run.mjs"
ALLOW = ROOT / "tests" / "aut5_hub_allowlist.txt"
SECTIONS = ["overview", "printers", "recent", "devices", "presets", "features", "settings", "flash", "updates", "logs"]
VIEWS = ",".join("#" + s for s in SECTIONS)
ITEM = {"vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black", "material": "PLA", "color_hex": "2B2B2E",
        "net": 1000, "tare": 200, "density": 1.24, "count": 1, "nozzle": 220, "bed": 55, "sealed": False}


@pytest.fixture
def hub_app(tmp_path, monkeypatch, spoolman_url):
    """The Hub page's app with a throwaway config and example data in each section; yields (app, the server's port
    holder): the page answers only the Host names that holder gives."""
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setenv("FK_SETUP_RUN", str(tmp_path / "run"))
    monkeypatch.setattr(cli.shutil, "chown", lambda *a, **k: None)
    monkeypatch.setattr(setup_helper, "_start_apply", lambda checked=False: None)
    monkeypatch.setattr(library, "load", lambda: TG.make_lib())
    cfg = config.load()
    cfg["modules"] = {n: n in modules.MODES["server"] for n in modules.MODULES}
    cfg["modules"].update(printers=True, klipper=True)
    cfg["web"] = {**cfg["web"], "lan": ["127.0.0.0/8"]}
    cfg["server_name"] = "Workshop hub"
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    setup_code.write(CODE)
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    with httpx.Client() as c:
        vendor = c.post(spoolman_url + "/api/v1/vendor", json={"name": "Polymaker"}).json()["id"]
        f = c.post(spoolman_url + "/api/v1/filament", json={"vendor_id": vendor, "name": "PolyTerra PLA Charcoal Black",
                   "material": "PLA", "color_hex": "2B2B2E", "density": 1.24, "diameter": 1.75, "weight": 1000,
                   "spool_weight": 200}).json()
        c.post(spoolman_url + "/api/v1/spool", json={"filament_id": f["id"], "location": "Rack 1", "remaining_weight": 620})
    pairing.make_cert("workshop-hub", ["192.0.2.5"], config.paths().etc)      # else Overview names the missing file's path
    # printers: one Bambu, one Klipper
    registry.upsert(registry.Printer("00M00A000000001", "Workshop X1", "X1C", "192.0.2.40", "12345678", True))
    registry.add_klipper("Garage Voron", "voron.example.com", 7125)
    # devices and Tag Readers
    TB.pair("a")
    pairing._write("devices.json", [
        {"id": "d1", "name": "Kitchen phone", "hash": "0" * 64, "paired": 1.0, "last_seen": 1.0, "expires": 0, "claimed": 1.0},
        {"id": "d2", "name": "Garage tablet", "hash": "1" * 64, "paired": 1.0, "last_seen": 1.0, "expires": 0, "claimed": 1.0}])
    store = reader_tokens.TokenStore()
    store.issue("Tag Reader for Workshop X1")
    store.issue("Tag Reader for Garage Voron")
    # a record in Recently added
    intake_history.stash_read("r1", [b"\xff\xd8\xff\xe0" + b"z" * 80], {"items": [ITEM]}, "", None)
    intake_history.record_save([{"values": dict(ITEM), "spool_ids": [187], "filament_id": 3}], source="phone", read_id="r1")
    # slicer presets: a first build the PC has installed, then a rebuild with an update waiting
    fake = TB.FakeSm(json.loads(json.dumps(TB.SUNLU)))
    from test_presets_updates import _first_install, _rebuild
    _first_install(fake)
    _rebuild(fake, 1.31, TG.NOW + 1)

    port = [0]
    yield (api.create_app(Spoolman(spoolman_url), printers=FakeManager(), camera_hub=object(), mapper=object(),
                          enabled_modules=modules.enabled(config.load()),
                          setup={"helper": Helper(), "hosts": lambda: {"127.0.0.1", f"127.0.0.1:{port[0]}"}}), port)


def _serve(app, port):
    running = serving.start(app)
    port[0] = running.port
    return running


@pytest.fixture
def hub(hub_app):
    running = _serve(*hub_app)
    try:
        yield running.url + "/setup"
    finally:
        running.stop()


class Plant:
    """ASGI wrapper that adds an unlabelled button to the page's HTML (the planted failure; shipped code is untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        page = scope["type"] == "http" and scope["path"] == "/setup"

        async def out(message):
            if page and message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message["headers"] if k.lower() != b"content-length"]
            elif page and message["type"] == "http.response.body":
                message["body"] = message["body"].replace(b"</body>", b"<button type='button'></button></body>")
            await send(message)
        await self.app(scope, receive, out)


@pytest.fixture
def planted(hub_app):
    app, port = hub_app
    running = _serve(Plant(app), port)
    try:
        yield running.url + "/setup"
    finally:
        running.stop()


class HttpsOrigin:
    """ASGI wrapper for a change made from this test's plain-http server: the Hub page answers a change only from its own
    https address (Origin check), so the Origin the browser sends is written as https (shipped code is untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope["headers"] = [(k, b"https://" + v[len(b"http://"):] if k == b"origin" and v.startswith(b"http://") else v)
                                for k, v in scope["headers"]]
        await self.app(scope, receive, send)


@pytest.fixture
def hub_change(hub_app):
    """The Hub page over plain http that accepts a change (the unlocked Logs pass reads a log with a POST)."""
    app, port = hub_app
    running = _serve(HttpsOrigin(app), port)
    try:
        yield running.url + "/setup"
    finally:
        running.stop()


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    major = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0]
    return node if major.isdigit() and int(major) >= 22 else None


def _missing(why: str):
    """No Node 22 or no browser: a skip, or a failure where the run is required (AUT5_REQUIRED=1, e.g. in CI)."""
    if os.environ.get("AUT5_REQUIRED") == "1":
        pytest.fail(f"AUT5_REQUIRED=1 but {why}")
    pytest.skip(why)


def _run(*args: str) -> subprocess.CompletedProcess:
    node = _node()
    if not node:
        _missing("AUT-5 needs Node 22 or later")
    run = subprocess.run([node, str(RUNNER), *args], capture_output=True, text=True, timeout=600)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("AUT-5 needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:          # a browser was found but cannot run headless on this machine (its error is shown)
        _missing("AUT-5: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    return run


def test_the_page_audit_passes_on_every_section(hub):
    run = _run("--url", hub, "--views", VIEWS, "--allow", str(ALLOW))
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == len(SECTIONS) * 2 * 2 and out["failing"] == 0      # ten sections, two widths, light and dark


def test_devices_and_flash_do_not_scroll_sideways_at_320_px_in_a_wide_font(monkeypatch, hub):
    """A Linux runner has no Segoe UI or Consolas and falls back to DejaVu, which is wider: the layout must hold there
    too, so these two sections (the ones a Linux CI run found wider than 320 px) run with the page's font tokens swapped for wide faces (the runner's --wide-font)."""
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")      # a CI runner's name: the web app address gets long
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else ["--wide-font"]      # DejaVu files, if a folder has them
    run = _run("--url", hub, "--views", "#devices,#flash", "--widths", "320", *fonts)      # no allow-list: only the scroll is asked about
    assert run.returncode in (0, 1), run.stdout + run.stderr
    found = [(r["view"], r["scheme"], f["detail"]) for r in json.loads(run.stdout).get("report", [])
             for f in r["findings"] if f["check"] == "sideways scroll"]
    assert not found, found


LOGS_PRELUDE = """
  const until = async (what, f, ms = 8000) => {
    for (let t = 0; t < ms && !f(); t += 100) await new Promise((r) => setTimeout(r, 100));
    if (!f()) throw new Error("Logs: " + what + " :: lock=" + SW.lock.state + " out=" + ((document.querySelector(".logs__out") || {}).innerText || "").slice(0, 150));
  };
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  const show = () => document.querySelector(".logs__controls .btn--primary");
  // the page reads the Hub's trust once after it opens and sets the lock from that answer: a code entered before the
  // answer arrives is dropped by it (the chip's loading line is gone when it has), so the test unlocks after it
  const unlocked = async () => {
    await until("the page did not finish its first reads", () => !document.querySelector(".chip--lock .skeleton__line")
      && !document.querySelector('[aria-busy="true"]:not(button)'));
    SW.setLock("unlocked", { code: %r });
    await until("no Show button", () => show());
  };
""" % CODE

# It waits on the outcome of Show (the log block, or the error state in its block), not on a fixed time.
LOGS_UNLOCKED = """(async () => {""" + LOGS_PRELUDE + """
  await unlocked();
  show().click();
  await until("no outcome after Show", () => document.querySelector(".logs__out .code"), 20000);
  if (document.querySelector(".logs__out .error-state")) throw new Error("Logs: the read failed: " + document.querySelector(".logs__out").innerText);
  if (!document.querySelector('.logs__out .code [data-action="copy"]')) throw new Error("Logs: no Copy button");
  if (document.querySelectorAll(".logs__controls .segmented__input").length !== 3) throw new Error("Logs: Lines is not 50 | 100 | 200");
  if (!document.querySelector(".logs__out .code__text").textContent.includes("backup started")) throw new Error("Logs: the log text is not shown");
})()"""

# a read still on its way when the page locks is dropped: the log is not written back onto the locked page
LOGS_LOCKED_MIDWAY = """(async () => {""" + LOGS_PRELUDE + """
  const real = window.fetch;
  let release = null;
  window.fetch = (u, o) => (String(u).endsWith("/api/logs") && o && o.method === "POST"
    ? real(u, o).then((r) => new Promise((res) => { release = () => res(r); })) : real(u, o));
  await unlocked();
  show().click();
  await until("the read was not sent", () => release, 20000);
  SW.setLock("locked");
  release();
  await until("no locked line", () => document.querySelector(".logs .banner"));      // the locked page is drawn
  await pause(1000);
  if (document.querySelector(".logs__out .code")) throw new Error("Logs: the reply was written onto the locked page");
})()"""


def test_the_logs_section_passes_the_audit_unlocked_with_a_log_shown(hub_change, monkeypatch):
    """AUT-5 on Logs, Unlocked (the Locked pass is in the test above): the controls, the log's code block and Copy."""
    monkeypatch.setattr(setup_helper, "_no_systemd", lambda: False)
    real = subprocess.run      # the same module runs the audit's Node: only journalctl is faked

    def journal(cmd, **kw):
        if cmd[0] != "journalctl":
            return real(cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"2026-11-12T03:00:02 backup started\n", stderr=b"")
    monkeypatch.setattr(setup_helper.subprocess, "run", journal)
    run = _run("--url", hub_change, "--views", "#logs", "--ready", LOGS_UNLOCKED)
    assert run.returncode == 0, run.stdout + run.stderr      # no allow-list: nothing of Logs is allowed any more
    assert json.loads(run.stdout)["views"] == 4


def test_a_log_that_arrives_after_the_page_locked_is_not_shown(hub_change, monkeypatch):
    monkeypatch.setattr(setup_helper, "_no_systemd", lambda: False)
    real = subprocess.run

    def journal(cmd, **kw):
        if cmd[0] != "journalctl":
            return real(cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"2026-11-12T03:00:02 backup started" + bytes([10]), stderr=b"")
    monkeypatch.setattr(setup_helper.subprocess, "run", journal)
    run = _run("--url", hub_change, "--views", "#logs", "--ready", LOGS_LOCKED_MIDWAY)
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_page_audit_passes_on_slicer_presets_switched_off(hub_app):
    cfg = config.load()
    cfg["modules"]["presets"] = False
    config.save(cfg)
    running = _serve(*hub_app)
    try:
        run = _run("--url", running.url + "/setup", "--views", "#presets")       # no allow-list: nothing of this section is allowed
        assert run.returncode == 0, run.stdout + run.stderr
        assert json.loads(run.stdout)["views"] == 4 and json.loads(run.stdout)["failing"] == 0      # two widths, light and dark
    finally:
        running.stop()


def test_an_unlabelled_button_added_to_the_served_page_fails_the_audit(planted):
    run = _run("--url", planted, "--views", VIEWS, "--allow", str(ALLOW))      # with the whole allow-list on
    assert run.returncode == 1, run.stdout + run.stderr
    found = [f for r in json.loads(run.stdout)["report"] for f in r["findings"]]
    assert any(f["check"] == "focusable element without a name" and f["where"].endswith("button") for f in found), found


def test_the_allow_list_names_a_later_step_and_a_count_on_every_line():
    for line in ALLOW.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("# "):
            view, check, where, count, reason = (x.strip() for x in line.split("|"))
            assert view in ["#" + s for s in SECTIONS] and check and where, line
            assert count.isdigit() and int(count) > 0 and "removed by S2." in reason, line
