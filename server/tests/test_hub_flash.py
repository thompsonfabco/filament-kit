"""S2.16 Flash a device on the Hub page (design 09 S2.16): the section's audits, and its browser walk (tests/flash_walk.mjs) with a fake
board and a fake Hub job. The fixtures and helpers are test_hub_page_audit.py's."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from filament_kit import config, pairing, setup_helper

from test_hub_page_audit import ROOT, _missing, _node, _run, _serve, hub, hub_app  # noqa: F401
from test_setup_page import CODE

WALK = ROOT / "tests" / "flash_walk.mjs"
SRC = Path(__file__).resolve().parents[1] / "filament_kit"
PAGE_JS = SRC / "setup_static" / "setup_flash.js"


def _python_steps() -> list[str]:
    """The step sentences of `reader setup` as the Python source writes them: step 1 in cli.py, steps 2 to 5 in reader_flash.setup."""
    first = re.findall(r'job\.next\("(Finding the board)"\)', (SRC / "cli.py").read_text(encoding="utf-8"))
    later = re.findall(r'\bstep\("([^"]+)"\)', (SRC / "reader_flash.py").read_text(encoding="utf-8"))
    return first + later


def test_the_pages_hub_step_names_are_the_ones_reader_setup_writes():
    js = PAGE_JS.read_text(encoding="utf-8")
    table = re.search(r"const HUB_STEPS = \{(.*?)\};", js, re.S).group(1)
    page = re.findall(r'"([^"]+)":', table)
    assert sorted(page) == sorted(set(_python_steps())), (page, _python_steps())
    assert len(_python_steps()) == 7      # one counted step each, and the two that keep their places


def test_flash_a_device_audits_clean_at_each_address_without_an_allow_list(hub):
    """S2.16 rebuilt the section on the shared components: no line of the allow-list is left for it, at its own address and at the
    two devices' addresses (03 1.2: #flash/tag-reader, #flash/display), light and dark, 1280 and 320 px. The title is the section's at
    each address, so each address is a run of its own (the audit asks the views of one run to have different titles)."""
    for view in ("#flash", "#flash/tag-reader", "#flash/display"):
        run = _run("--url", hub, "--views", view)
        assert run.returncode == 0, view + run.stdout + run.stderr
        out = json.loads(run.stdout)
        assert out["views"] == 2 * 2 and out["failing"] == 0, view


def test_flash_a_device_does_not_scroll_sideways_at_320_px_for_either_device(monkeypatch, hub):
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else ["--wide-font"]
    found = []
    for view in ("#flash/tag-reader", "#flash/display"):
        run = _run("--url", hub, "--views", view, "--widths", "320", *fonts)
        assert run.returncode in (0, 1), run.stdout + run.stderr
        found += [(r["view"], r["scheme"], f["detail"]) for r in json.loads(run.stdout).get("report", [])
                  for f in r["findings"] if f["check"] == "sideways scroll"]
    assert not found, found


def test_flash_a_device_walk_in_a_browser_with_a_fake_board_and_a_fake_hub_job(monkeypatch, hub_app, tmp_path):
    """tests/flash_walk.mjs: the Hub way sends the older buzzer as `low`, its job's own steps mark the failed step, the buttons are free
    after a job and after a redraw during a run; the browser way makes the token before it writes, revokes it on a failure and on Stop;
    and the page audit finds nothing in each state the walk reaches."""
    import threading
    import time

    from filament_kit import reader_flash, reader_setup
    import filament_kit.setup_page as sp
    ctl = tmp_path / "ctl.json"
    ctl.write_text(json.dumps({"boards": 0, "jobfail": False, "instant": False}))
    answers = []
    real_pending = reader_flash.write_pending
    monkeypatch.setattr(reader_flash, "write_pending", lambda a: (answers.append(a["buzzer"]), real_pending(a))[1])
    monkeypatch.setattr(reader_setup, "find_readers", lambda: [reader_setup.Reader(f"/dev/ttyACM{i}", None, "ESP32-C3")
                                                              for i in range(json.loads(ctl.read_text())["boards"])])
    # the walk's server is http: its Origin is accepted here, as the https one is on a Hub
    monkeypatch.setattr(sp.SetupPage, "_origin_ok", lambda self, r: r.headers.get("origin") == "http://" + r.headers.get("host", ""))
    cfg = config.load()
    cfg["web"] = {**cfg["web"], "public_url": "https://kit.example.net/filament"}
    config.save(cfg)
    sentences = _python_steps()
    flash_path = [s for s in sentences if s in ("Finding the board", "Writing the program", "Checking what was written", "Joining the Wi-Fi",
                                                "Reaching the Hub")]
    assert len(flash_path) == 5

    def job():          # the sentences `reader setup` writes (read from its source); a failed one stops at Joining the Wi-Fi
        log = setup_helper.job_log()
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(setup_helper.header("reader_setup") + "\n")
        fail, instant = (json.loads(ctl.read_text())[k] for k in ("jobfail", "instant"))
        if instant:         # a job that is over before the page looks
            with log.open("a") as f:
                f.write(f"==> step 1 of 5 {flash_path[0]}\n==> finished (exit 1)\n")
            return
        for i, text in enumerate(flash_path, 1):
            with log.open("a") as f:
                f.write(f"==> step {i} of 5 {text}\n")
            time.sleep(1.6)
            if fail and text == "Joining the Wi-Fi":
                break
        with log.open("a") as f:
            f.write(f"==> finished (exit {1 if fail else 0})\n")
    monkeypatch.setattr(setup_helper, "_start_job", lambda name, why="", checked=False: threading.Thread(target=job, daemon=True).start())
    node = _node()
    if not node:
        _missing("AUT-5 needs Node 22 or later")
    app, port = hub_app
    running = _serve(app, port)
    try:
        shots = [os.environ["S216_SHOTS"]] if os.environ.get("S216_SHOTS") else []
        run = subprocess.run([node, str(WALK), running.url + "/setup", str(ctl), CODE, *shots], capture_output=True, encoding="utf-8", timeout=900)
    finally:
        running.stop()
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("AUT-5 needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("AUT-5: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert not [c["what"] for c in out["checks"] if not c["ok"]], out["checks"]
    assert len(out["checks"]) >= 25
    assert not [(a["state"], a["findings"]) for a in out["audit"] if a["findings"]], out["audit"]
    assert len(out["audit"]) >= 14
    # the older module is `low` at the Hub, also after a redraw; the other Hub starts (failed job, instant job, one from elsewhere) are the default
    assert answers == ["low", "high", "high", "high", "high"]


def test_flash_a_device_with_no_firmware_is_the_empty_state_and_audits_clean(monkeypatch, hub):
    from filament_kit import reader_flash
    monkeypatch.setattr(reader_flash, "device_image", lambda device: None)
    run = _run("--url", hub, "--views", "#flash")
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)["failing"] == 0
