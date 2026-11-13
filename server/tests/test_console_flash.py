"""The setup page's "Flash a device" tab (setup_console/flash_tab.py, setup_static/setup_flash.js): the kit's own images
for the browser, the Printer Station's token for the browser way, and the server way through the root helper's op
reader_usb and the job reader_setup (`reader setup --pending`)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from test_setup_page import AWAY, BASE, CODE, H, HOME, Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, config, reader_flash as rf, reader_setup as rs, reader_tokens, setup_helper

STATIC = Path(cli.__file__).parent / "setup_static"
ROOT = Path(cli.__file__).resolve().parents[2]
PUBLIC = "https://kit.example.net/filament"
BOARD = rs.Reader("/dev/ttyACM0", "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_AA:BB:CC:DD:EE:FF-if00",
                  "USB JTAG/serial debug unit")


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture
def app(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(rs, "find_readers", lambda: [BOARD])
    return make(env, Helper(), Mgr())


def _public(url=PUBLIC):
    cfg = config.load()
    cfg["web"] = {**cfg["web"], "public_url": url}
    config.save(cfg)


# ---------- the images ----------

def test_the_listing_names_both_images_and_the_server_boards_without_their_serial(app):
    r = client(app).get("/setup/api/firmware")
    assert r.status_code == 200
    d = r.json()
    devs = {x["id"]: x for x in d["devices"]}
    station = rf.bundled_image()
    assert devs["printer-station"]["bundled"] and devs["printer-station"]["version"] == str(station[1])
    assert devs["printer-station"]["settings"] and not devs["intake-panel"]["settings"]
    assert devs["intake-panel"]["version"] == rf.panel_image()[1]
    assert d["server_boards"] == [{"port": "/dev/ttyACM0", "product": "USB JTAG/serial debug unit"}]
    assert "AA:BB" not in r.text
    assert d["settings_ok"] is False and "public_url" in d["settings_why"]
    _public()
    assert client(app).get("/setup/api/firmware").json()["settings_ok"] is True


def test_an_image_is_served_whole_from_the_kit_and_only_to_the_home_network(app):
    for dev in ("printer-station", "intake-panel"):
        r = client(app).get(f"/setup/api/firmware/{dev}.bin")
        assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
        assert r.content == rf.device_image(dev)[0].read_bytes()
    assert client(app).get("/setup/api/firmware/other.bin").status_code == 404
    assert client(app).get("/setup/api/firmware/printer-station").status_code == 404
    assert client(app, AWAY).get("/setup/api/firmware/printer-station.bin").status_code == 403


def test_the_installed_images_win_over_a_checkouts(env, tmp_path):  # noqa: F811
    panel = config.paths().opt / "resources" / "panel"
    panel.mkdir(parents=True)
    (panel / "intake-panel.bin").write_bytes(b"\xe9panel")
    (panel / "VERSION").write_text("99\n")
    assert rf.device_image("intake-panel") == (panel / "intake-panel.bin", "99")
    assert rf.device_image("nothing") is None


# ---------- the browser way: the Printer Station's token ----------

def test_provision_needs_the_code_and_gives_the_token_and_the_address(app):
    _public()
    assert post(client(app), "flash/provision", {}, code=None).status_code in (401, 403)
    assert reader_tokens.TokenStore().list() == []
    r = post(client(app), "flash/provision", {"name": "bench"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["base"] == PUBLIC + "/reader" and len(d["token"]) >= 16
    assert [(t["id"], t["name"]) for t in reader_tokens.TokenStore().list()] == [(d["id"], "bench")]
    # a failed run takes it back with the route the Devices tab has
    assert post(client(app), f"readers/{d['id']}/revoke", {}).status_code == 200
    assert reader_tokens.TokenStore().list() == []


def test_provision_without_a_public_address_makes_no_token(app):
    r = post(client(app), "flash/provision", {})
    assert r.status_code == 409 and "public_url" in r.json()["error"]
    assert reader_tokens.TokenStore().list() == []


# ---------- the server way: op reader_usb, job reader_setup ----------

ANSWERS = {"ssid": "Home", "pass": "wifi-secret-1", "buzzer": "low"}


def test_the_server_way_leaves_the_answers_root_only_and_starts_the_job(app, monkeypatch):
    started = []
    monkeypatch.setattr(setup_helper, "_start_job", lambda name, why="": started.append(name))
    assert post(client(app), "flash/server", ANSWERS, code=None).status_code in (401, 403)
    assert not rf.pending_path().exists()
    r = post(client(app), "flash/server", ANSWERS)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "reader_setup" and started == ["reader_setup"]
    p = rf.pending_path()
    assert json.loads(p.read_text()) == {**ANSWERS, "port": "/dev/ttyACM0", "name": "printer-station"}
    if os.name == "posix":
        assert p.stat().st_mode & 0o777 == 0o600
    assert "wifi-secret-1" not in r.text


def test_a_job_that_does_not_start_leaves_no_answers(app, monkeypatch):
    def refuse(name, why=""):
        raise setup_helper.Refused(500, "the job did not start")
    monkeypatch.setattr(setup_helper, "_start_job", refuse)
    assert post(client(app), "flash/server", ANSWERS).status_code == 500
    assert not rf.pending_path().exists()


@pytest.mark.parametrize("body, status, words", [
    ({"ssid": "", "pass": "p"}, 400, "Wi-Fi name"),
    ({"ssid": "Home", "pass": "p" * 64}, 400, "password"),
    ({"ssid": "Home", "pass": "p", "buzzer": "loud"}, 400, "buzzer"),
    ({"ssid": "Home", "pass": "p", "name": "a/b"}, 400, "name"),
    ({"ssid": "Home", "pass": "p", "port": "/dev/ttyACM9"}, 409, "no longer plugged in"),
    ({"pass": "p"}, 400, "Wi-Fi name"),
])
def test_bad_answers_are_refused_and_nothing_is_left(app, monkeypatch, body, status, words):
    monkeypatch.setattr(setup_helper, "_start_job", lambda name, why="": None)
    r = post(client(app), "flash/server", body)
    assert r.status_code == status and words in r.json()["error"]
    assert not rf.pending_path().exists()


def test_no_board_or_several_without_a_pick_are_refused(app, monkeypatch):
    monkeypatch.setattr(setup_helper, "_start_job", lambda name, why="": None)
    monkeypatch.setattr(rs, "find_readers", lambda: [])
    assert "no ESP32 board" in post(client(app), "flash/server", ANSWERS).json()["error"]
    monkeypatch.setattr(rs, "find_readers", lambda: [BOARD, rs.Reader("/dev/ttyACM1", None, "x")])
    assert "several" in post(client(app), "flash/server", ANSWERS).json()["error"]
    assert post(client(app), "flash/server", {**ANSWERS, "port": "/dev/ttyACM1"}).status_code == 200
    assert json.loads(rf.pending_path().read_text())["port"] == "/dev/ttyACM1"


def test_the_job_is_not_started_by_name_alone(app):
    r = post(client(app), "job", {"name": "reader_setup"})
    assert r.status_code == 400 and "Flash a device" in r.json()["error"]


def test_the_job_runs_reader_setup_pending(monkeypatch):
    assert setup_helper.JOBS["reader_setup"] == ("reader", "setup", "--pending")
    assert "reader_setup" in setup_helper.BUSY
    seen = []
    monkeypatch.setattr(cli, "cmd_reader_setup", lambda a: seen.append(a.pending) or 0)
    assert cli._main(["reader", "setup", "--pending"]) == 0 and seen == [True]


# ---------- the job's side: `reader setup --pending` ----------

def _args(**kw):
    base = dict(name=None, ssid=None, source=None, port=None, out=None, ota_pubkey=None, token_file=None,
                base="https://kit.example.net/filament/reader", secrets=None, buzzer=None, reflash=False, pending=True)
    base.update(kw)
    return __import__("argparse").Namespace(**base)


@pytest.fixture
def usb(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(rs, "find_readers", lambda: [BOARD, rs.Reader("/dev/ttyACM1", None, "x")])
    got = {}

    def setup(port, settings, reflash=False, run=None, step=None):
        got.update(port=port, settings=settings)
        return got.get("result", rf.Result(True, "Done. The Printer Station joined 'Home' and reached the kit."))
    monkeypatch.setattr(rf, "setup", setup)
    return got


def _no_ask(prompt=""):
    raise EOFError


def _run(cmd, **kw):
    return subprocess.CompletedProcess(cmd, 3, b"", b"")


def test_pending_takes_the_answers_once_asks_nothing_and_prints_no_secret(usb, capsys):
    rf.write_pending({**ANSWERS, "port": "/dev/ttyACM1", "name": "bench"})
    assert cli._reader_setup_usb(_args(), _no_ask, _no_ask, run=_run) == 0
    assert not rf.pending_path().exists()
    s = usb["settings"]
    assert (usb["port"], s["ssid"], s["pass"], s["buzzer_low"]) == ("/dev/ttyACM1", "Home", "wifi-secret-1", True)
    assert [t["name"] for t in reader_tokens.TokenStore().list()] == ["bench"]
    out = capsys.readouterr()
    assert "wifi-secret-1" not in out.out + out.err and s["token"] not in out.out + out.err
    # once: a second run has nothing to take
    assert cli._reader_setup_usb(_args(), _no_ask, _no_ask, run=_run) == 1
    assert "no answers from the setup page" in capsys.readouterr().err


def test_pending_without_a_port_and_several_boards_asks_nothing(usb, capsys):
    rf.write_pending(ANSWERS)
    assert cli._reader_setup_usb(_args(), _no_ask, _no_ask, run=_run) == 1
    assert "pick the Printer Station's port on the setup page" in capsys.readouterr().err
    assert reader_tokens.TokenStore().list() == [] and not rf.pending_path().exists()


def test_old_answers_are_dropped(usb, capsys):
    rf.write_pending({**ANSWERS, "port": "/dev/ttyACM0"})
    old = time.time() - rf.PENDING_MAX_AGE - 5
    os.utime(rf.pending_path(), (old, old))
    assert cli._reader_setup_usb(_args(), _no_ask, _no_ask, run=_run) == 1
    assert not rf.pending_path().exists() and "older than 15 minutes" in capsys.readouterr().err


def test_a_failed_job_removes_its_token(usb, capsys):
    usb["result"] = rf.Result(False, "the reader could not join the Wi-Fi network 'Home'")
    rf.write_pending({**ANSWERS, "port": "/dev/ttyACM0"})
    assert cli._reader_setup_usb(_args(), _no_ask, _no_ask, run=_run) == 1
    assert reader_tokens.TokenStore().list() == []


# ---------- the page ----------

def test_the_tab_and_its_assets_are_served(app):
    page = client(app).get("/setup").text
    assert "/setup/setup_flash.js" in page and "esptool.bundle.js" not in page      # loaded only to write a board
    for name in ("setup_flash.js", "esptool.bundle.js"):
        r = client(app).get("/setup/" + name)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    js = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert 'flash: ["nav_flash_device", "flash", () => [flashTab]]' in js
    # the job strip titles the station setup job from the catalogue (02 8.4)
    assert '"reader_setup"' in (ROOT / "web-shared" / "components-jobs.js").read_text(encoding="utf-8")
    assert '"job_title_reader_setup": "Setting up a Tag Reader"' in (ROOT / "strings" / "en.json").read_text(encoding="utf-8")


def test_the_vendored_esptool_js_is_the_published_bundle():
    """THIRD-PARTY.md names its SHA-256; the file is esptool-js 0.7.0's bundle.js as published, byte for byte."""
    digest = hashlib.sha256((STATIC / "esptool.bundle.js").read_bytes()).hexdigest()
    third = (ROOT / "THIRD-PARTY.md").read_text(encoding="utf-8")
    assert digest == "00ebe6fb0b202976d3e2a3c6b9a6bd438c26a81d2af6739c95ac276a64c1a84e" and digest in third
    lic = (STATIC / "esptool.bundle.LICENSES.txt").read_text(encoding="utf-8")
    assert "Apache License" in lic and "pako 2.1.0" in lic and "atob-lite 2.0.0" in lic


def test_the_page_says_what_to_do_without_web_serial():
    js = (STATIC / "setup_flash.js").read_text(encoding="utf-8")
    assert 'const webSerialOk = () => "serial" in navigator && window.isSecureContext;' in js
    assert "Use one of those, or plug the device into the server." in js
    assert 'import("/setup/esptool.bundle.js")' in js
    assert "innerHTML" not in js


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_tab_script_parses_and_reads_the_readers_answer():
    js = (STATIC / "setup_flash.js").read_text(encoding="utf-8")
    subprocess.run([shutil.which("node"), "--check", str(STATIC / "setup_flash.js")], check=True, timeout=30)
    fn = js.split("function parseHello(line) {")[1].split("\n}\n")[0]
    probe = ["FK-READER 1794501335 configured=1 wifi=ok server=unauth", "FK-READER x", "HELLO intake-panel 11"]
    code = f"function parseHello(line) {{{fn}\n}}\nconsole.log(JSON.stringify({json.dumps(probe)}.map(parseHello)));"
    out = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == [{"build": 1794501335, "configured": True, "wifi": "ok", "server": "unauth"}, None, None]


# A fake Web Serial board for the tab's own provisioning code: it speaks the firmware's lines (settings.h), restarts
# after FK-OK (the port goes away, then comes back) and then reports its first start.
FAKE_SERIAL = r"""
const vm = require("vm");
const src = require("fs").readFileSync(process.argv[2], "utf8");
const scenario = JSON.parse(process.argv[3]);
const board = { settings: null, gone: false, lines: [], opens: 0 };
function makePort() {
  let ctl = null;
  const enc = new TextEncoder();
  let buf = "";
  const say = (t) => { if (ctl) ctl.enqueue(enc.encode(t)); };
  return {
    getInfo: () => ({ usbVendorId: 0x303a, usbProductId: 0x1001 }),
    async open() { if (board.gone) throw new Error("not there"); board.opens++;
      this.readable = new ReadableStream({ start(c) { ctl = c; } });
      this.writable = new WritableStream({ write(chunk) {
        buf += new TextDecoder().decode(chunk);
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i); buf = buf.slice(i + 1); board.lines.push(line.slice(0, 7));
          if (line === "FK?") {
            const done = board.settings !== null;
            say(`FK-READER 1794501335 configured=${done ? 1 : 0} wifi=${done ? scenario.wifi : "-"} server=${done ? scenario.server : "-"}\n`);
          } else if (line.startsWith("FK-SET ")) {
            if (scenario.refuse) { say(`FK-ERR ${scenario.refuse}\n`); continue; }
            board.settings = JSON.parse(line.slice(7));
            say("FK-OK\n");
            setTimeout(() => { board.gone = true; try { ctl.close(); } catch {} setTimeout(() => { board.gone = false; }, 800); }, 50);
          }
        }
      } });
    },
    async setSignals() {},
    async close() {},
  };
}
const ctx = { navigator: { serial: { getPorts: async () => [makePort()] } }, window: { isSecureContext: true },
  TextEncoder, TextDecoder, setTimeout, clearTimeout, console, Date, JSON, Promise, Math };
vm.createContext(ctx);
vm.runInContext(src, ctx);
const settings = { ssid: "Home", pass: "pw", base: "https://kit.example.net/filament/reader", token: "t".repeat(43), buzzer_low: false };
ctx.provisionOverSerial({ usbVendorId: 0x303a, usbProductId: 0x1001 }, settings, () => {}).then((r) => {
  console.log(JSON.stringify({ ...r, settings: board.settings, sent: board.lines.filter((l) => l !== "FK?") }));
});
"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("scenario, ok, words", [
    ({"wifi": "ok", "server": "ok"}, True, "Done. The Printer Station joined \"Home\" and reached the kit."),
    ({"wifi": "fail", "server": "-"}, False, "could not join the Wi-Fi network \"Home\""),
    ({"wifi": "ok", "server": "unauth"}, False, "did not accept its token"),
    ({"wifi": "ok", "server": "fail"}, False, "could not reach the kit at https://kit.example.net/filament/reader"),
    ({"wifi": "ok", "server": "ok", "refuse": "not a JSON object"}, False, "refused the settings: not a JSON object"),
])
def test_the_browser_provisioning_against_a_fake_board(tmp_path, scenario, ok, words):
    script = tmp_path / "fake.js"
    script.write_text(FAKE_SERIAL, encoding="utf-8")
    out = subprocess.run([shutil.which("node"), str(script), str(STATIC / "setup_flash.js"), json.dumps(scenario)],
                         capture_output=True, text=True, timeout=120, check=True).stdout
    r = json.loads(out)
    assert r["ok"] is ok and words in r["message"], r
    if not scenario.get("refuse"):
        assert r["settings"]["token"] == "t" * 43 and r["sent"] == ["FK-SET "]
