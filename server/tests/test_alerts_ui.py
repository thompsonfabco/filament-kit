"""EA5 of R80: the shared alert banner, the Alerts list, the events poller and the browser-notification helper
(web-shared/alerts.js, alerts.css), pressed in a real headless browser through tests/page_drive.mjs and audited through
tests/aut5_run.mjs. The Hub is a stub: a fake GET api/events in the shape of DECISIONS R80 section 8, served by the page
(server/tests/alerts_ui/alerts-page.js); no server code is involved. The same skip rules as the page audit: no Node 22 or no
browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import functools
import http.server
import json
import subprocess
import threading
from pathlib import Path

import pytest

from test_hub_page_audit import _missing, _node

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tests" / "page_drive.mjs"
RUNNER = ROOT / "tests" / "aut5_run.mjs"
DRIVE_JS = Path(__file__).with_name("alerts_ui") / "alerts-drive.js"
PAGE = "/server/tests/alerts_ui/page.html"
LOOKS = ["console", "workbench", "palette", "panes"]
WIDTHS = [1280, 1776, 1024, 768, 390]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".css": "text/css",
                      ".svg": "image/svg+xml", ".json": "application/json", "": "application/octet-stream"}

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _run(cmd: list[str], what: str):
    run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing(f"{what} needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing(f"{what}: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    return run


def _drive(site: str, scenario: str, tmp_path: Path, page: str = "scenario=blank&manual=1", width: int = 1280, look: str = "console") -> dict:
    node = _node()
    if not node:
        _missing("the page driver needs Node 22 or later")
    script = tmp_path / f"{scenario}.js"
    script.write_text(DRIVE_JS.read_text(encoding="utf-8").replace("__SCENARIO__", scenario), encoding="utf-8")
    init = tmp_path / "init.js"
    init.write_text(f'try {{ localStorage.setItem("spoolwarden.look", "{look}"); }} catch (e) {{}}', encoding="utf-8")
    run = _run([node, str(DRIVER), "--url", site + PAGE + "?" + page, "--script", str(script), "--width", str(width), "--init", str(init)], "the page driver")
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


def test_banners_show_content_and_limits(site, tmp_path):
    out = _drive(site, "content", tmp_path, "scenario=layout")
    first = out["first"]
    # at most two, the most serious first, then the newest; a bad moment and a bad moment before the bad condition
    assert [b["title"] for b in first] == ["Print stopped on Study A1 mini", "Workshop X1 reports a problem"]
    assert [b["kind"] for b in first] == ["bad", "bad"]
    assert first[0]["text"].startswith("Print stopped on Study A1 mini gear.3mf stopped at 12 %. It was cancelled.")
    assert first[0]["time"] == "3 minutes ago" and first[1]["time"] == "8 minutes ago"
    assert first[1]["text"].endswith("The nozzle temperature is abnormal and the printer stopped. 8 minutes ago")
    assert all(b["action"] == "Open the printer" and b["href"] == "#printers" and b["dismiss"] for b in first)
    assert out["moreFirst"] == "3 more alerts"
    assert [b["role"] for b in first] == [None, None]          # present when the page opened: plain content
    assert out["toastsAtOpen"] == []                             # what was already there is history, not an arrival
    # dismissing one lets the next take its place
    assert out["afterDismiss"] == ["Workshop X1 reports a problem", "Storage on the Hub is full"] and out["moreAfter"] == "2 more alerts"
    assert out["hostKids"] == 3


def test_one_two_and_three_alerts(site, tmp_path):
    out = _drive(site, "limits", tmp_path)
    assert out["one"] == [1, None] and out["two"] == [2, None]
    assert out["three"] == [["Bench scale stopped answering", "Workshop X1 is paused"], "1 more alert"]     # the newest two
    assert out["threeText"][0].startswith("Bench scale stopped answering Last answer ") and out["threeText"][1].startswith("Workshop X1 is paused a.3mf is paused at 5 %.")


def test_dismiss_is_per_device_and_comes_back_if_worse_or_raised_again(site, tmp_path):
    out = _drive(site, "dismiss_rules", tmp_path)
    assert out["shown"] == [["Storage on the Hub is almost full", True]]
    assert out["afterDismiss"] == 0 and out["stored"] is not None            # kept in this browser's own storage
    assert out["stillHidden"] == 0 and out["stillHiddenLater"] == 0
    assert out["worse"] == [["bad", "Storage on the Hub is full"]]           # warn to bad: back
    assert out["afterSecond"] == 0
    assert out["cleared"] == 0 and out["keyAfterClear"] is None              # a cleared condition forgets the dismissal
    assert out["raisedAgain"] == ["Storage on the Hub is almost full"]       # raised again later: back


def test_conditions_clear_and_moments_stay_until_dismissed_for_24_hours(site, tmp_path):
    out = _drive(site, "conditions_and_moments", tmp_path)
    assert [t for t, _ in out["both"]] == ["Print stopped on Study A1 mini", "Filament ran out on Workshop X1"]   # bad before warn
    assert out["both"][0][1] == "30 minutes ago" and out["both"][1][1].startswith("since ")
    assert out["condLeft"] == ["Print stopped on Study A1 mini"]             # the condition left by itself when it cleared
    assert out["at23h"] == 1 and out["at25h"] == 0                           # a moment lasts at most 24 hours
    assert out["errorShown"][0][0] == "Workshop X1 reports a problem" and "The chamber door is open." in out["errorShown"][0][1]
    assert out["errorStays"] == 1 and out["errorDismissed"] == 0 and out["errorKey"] == 1
    assert out["switchedOff"] == 0                                           # an alert type that is off shows no banner


def test_alerts_list_order_age_and_empty_text(site, tmp_path):
    out = _drive(site, "list", tmp_path, "scenario=layout")
    lay = out["layout"]
    assert lay["title"] == "Alerts" and lay["headings"] == ["Happening now", "Last 7 days"]
    titles = [r["title"] for r in lay["rows"]]
    # raised conditions first (bad, then warn newest first), then the events of the last 7 days, newest first, none older, none off
    assert titles == ["Storage on the Hub is full", "Running low: Polymaker PLA Teal", "Filament ran out on Workshop X1",
                      "Print stopped on Study A1 mini", "Workshop X1 reports a problem", "Print finished on Garage P1S"]
    assert lay["rows"][1]["text"] == "Spool 214 has 92 g left. 2 more in stock."
    assert lay["rows"][0]["text"] == "3.2 GB free of 64.0 GB. Backups and new photos may fail."
    assert [r["action"] for r in lay["rows"]] == ["Show storage use", "Show running low", "Open the printer", "Open the printer", "Open the printer", "Open the printer"]
    assert [r["time"] for r in lay["rows"]][3:] == ["3 minutes ago", "8 minutes ago", "5 hours ago"]
    assert out["closed"] and out["focusBack"]
    assert out["empty"]["rows"] == [] and out["empty"]["empty"] == "No alerts in the last 7 days."


def test_poller_cursor_dedupe_rhythm_and_failure(site, tmp_path):
    out = _drive(site, "poller", tmp_path)
    cid = out["client"]
    assert cid and len(cid) >= 8                                             # the page's own id, kept in this browser
    assert out["firstUrl"].startswith("api/events?since_at=") and out["firstUrl"].endswith(f"&limit=200&alert=1&wait=0&client={cid}")   # first call: last 7 days by time
    assert out["secondUrl"] == f"api/events?since=0&alert=1&wait=0&client={cid}"
    assert out["thirdUrl"] == f"api/events?since=2&alert=1&wait=0&client={cid}" and out["cursor"] == 2
    assert out["stored"] == 2 and out["banners"] == 2 and out["toasts"] == 2   # polled three times, each event counted once
    assert out["timerPolls"] >= 3 and out["timerArrived"] == ["Workshop X1 reports a problem"]
    assert out["failedKept"] == 1 and out["recovered"] == 2
    assert out["stopped"] is True


def test_arrival_toast_once_per_alert(site, tmp_path):
    out = _drive(site, "arrivals", tmp_path)
    assert out["historyToasts"] == 0
    assert out["arrived"] == ["Print stopped on Study A1 mini"] and out["toastAction"] == "Open the printer"
    assert out["raised"] == 2 and out["againWhileLasting"] == 2              # a condition: when raised, not again while it lasts
    assert out["clearedAndOff"] == 2                                          # clearing, or an alert type that is off: nothing
    assert out["raisedAfterClear"] == 3
    assert ["bad", "alert"] in out["roles"] or ["warn", "status"] in out["roles"]
    assert out["rolesLater"] == [None] * len(out["rolesLater"])


def test_gap_resyncs_and_test_alert_arrives_once(site, tmp_path):
    out = _drive(site, "gap_and_test", tmp_path)
    assert out["before"] == 1 and out["gapToasts"] == out["toastsBefore"] == 1 and out["afterGap"] == ["Print stopped on Workshop X1"]
    assert out["testToasts"] == ["Test alert"] and out["testOnce"] == 1


def test_late_banners_are_announced_and_early_ones_are_plain(site, tmp_path):
    out = _drive(site, "late_roles", tmp_path, "scenario=blank")
    assert out["atOpen"] == []
    roles = {title: (kind, role) for title, kind, role in out["later"]}
    assert roles["Late one reports a problem"] == ("bad", "alert") and roles["Storage on the Hub is almost full"] == ("warn", "status")


def test_notification_helper_states_and_one_per_event(site, tmp_path):
    out = _drive(site, "notifications", tmp_path)
    assert out["real"] in ("default", "denied", "granted")
    assert out["initial"] == ["default", False, None]
    assert out["setOn"] == "granted" and out["asked"] == 1 and out["onAfter"] is True
    assert out["one"] == [["Print stopped on Study A1 mini", "gear.3mf stopped at 12 %. It was cancelled.", "sw-event-1"]]   # polled three times: one
    assert out["afterRaise"] == 2 and out["afterAgain"] == 2 and out["afterOff"] == 2                           # a condition once; an alert type off: none
    assert out["offState"] == [False, "granted"] and out["afterSwitchOff"] == 2
    perm, say, answer, on, asked = out["denied"]
    assert perm == "denied" and say["text"] == "Blocked in this browser's settings" and "site settings" in say["hint"]
    assert answer == "denied" and on is False and asked == 0 and out["deniedMade"] == 0
    perm, say, answer, on = out["unsupported"]
    assert perm == "unsupported" and say["text"] == "This browser cannot show notifications" and "public address" in say["hint"]
    assert answer == "unsupported" and on is False
    assert out["refused"][:2] == ["denied", False] and out["refused"][2]["text"] == "Blocked in this browser's settings"


def _audit(site: str, look: str, page: str, ready: str, widths=WIDTHS):
    node = _node()
    if not node:
        _missing("AUT-5 needs Node 22 or later")
    run = _run([node, str(RUNNER), "--url", site + PAGE + "?" + page, "--views", "#overview", "--widths", ",".join(map(str, widths)),
                "--look", look, "--ready", ready], "AUT-5")
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["failing"] == 0 and not out.get("allowed")
    for p in out["passes"]:          # each view really ran at its width
        assert (p["innerWidth"], p["dark"], p["coarse"]) == (p["width"], p["scheme"] == "dark", p["width"] <= 600), p
    assert {(p["width"], p["scheme"]) for p in out["passes"]} == {(w, s) for w in widths for s in ("light", "dark")}


# the page is set up and what the audit looks at is checked to be there (a throw fails the run): the banners and the "more" line, or the open list
READY_BANNERS = ("window.__ready.then(() => new Promise((r) => setTimeout(r, 150))).then(() => { const n = document.querySelectorAll('.alert-host .banner').length, "
                 "m = document.querySelector('.alert-more'); if (n !== 2 || !m || m.textContent.trim() !== '3 more alerts') throw new Error('banners: ' + n); })")
READY_LIST = ("window.__ready.then(() => { document.querySelector('.alert-more button').click(); return new Promise((r) => setTimeout(r, 300)); })"
              ".then(() => { const n = document.querySelectorAll('dialog[open] .alert-row').length; if (n !== 5) throw new Error('list rows: ' + n); })")


@pytest.mark.parametrize("look", LOOKS)
def test_banners_in_every_look_and_width(site, look):
    """Two banners and the "n more alerts" line: the page audit (names, roles, targets, no sideways scroll) at five widths, light and dark."""
    _audit(site, look, "scenario=layout", READY_BANNERS)


@pytest.mark.parametrize("look", LOOKS)
def test_alerts_list_in_every_look_and_width(site, look):
    _audit(site, look, "scenario=layout", READY_LIST)


@pytest.mark.parametrize("mode", ["interstitial", "flag"])
def test_assumption_1_notifications_on_the_hubs_self_signed_page(mode, tmp_path):
    """R80 section 10, assumption 1: a page served with the Hub's own certificate, accepted through the browser's warning (or with
    its ignore flag), is a secure context and can show a notification once the permission is granted. Headless has no prompt:
    Browser.grantPermissions stands in for the person's "Allow" (alerts_ui/https_notify.mjs says what that does not prove)."""
    from filament_kit import pairing
    node = _node()
    if not node:
        _missing("the notification check needs Node 22 or later")
    pairing.make_cert("localhost", ["127.0.0.1"], tmp_path / "cert")
    run = _run([node, str(Path(__file__).with_name("alerts_ui") / "https_notify.mjs"), "--cert", str(tmp_path / "cert" / "cert.pem"),
                "--key", str(tmp_path / "cert" / "key.pem"), "--mode", mode], "the notification check")
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    if mode == "interstitial":
        assert out["warning"] == "Privacy error"          # the certificate warning was there, and the page is behind it
    assert out["page"] == "hub | https" and out["secureContext"] is True and out["hasNotification"] is True
    assert out["permissionAtStart"] == "default" and out["grant"] == "ok"
    assert out["permissionAfterGrant"] == "granted" and out["shown"] == "show"
