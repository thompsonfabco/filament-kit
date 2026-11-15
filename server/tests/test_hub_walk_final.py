"""What the final Hub walk found (design 03): the Trusted computers card, the pairing requests error text, the brand and the
setup command box at 320 px, the Updates title, the Logs select and the Devices card pairs. Real controls in a headless
browser (tests/page_drive.mjs) with the data of test_hub_page_audit.py; the same skip rules."""
from __future__ import annotations

from filament_kit import station_requests, trusted

from test_hub_devices import _page_drive
from test_hub_page_audit import hub_app, hub_change  # noqa: F401

PRELUDE = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
async function until(look, what, ms = 15000) { for (let t = 0; t < ms; t += 100) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const settle = () => until(() => !$(".chip--lock .skeleton__line") && !$('[aria-busy="true"]:not(button)'), "the reads to settle");
const open = async (name) => { location.hash = "#" + name; await sleep(300); await settle(); };
"""


def test_devices_trusted_card_has_no_null_line_and_a_full_size_switch_and_the_requests_error_has_no_class_name(hub_change, monkeypatch, tmp_path):
    trusted.set_enabled(True)

    def unreadable():
        raise FileNotFoundError("no certificate")
    monkeypatch.setattr(station_requests, "pending", unreadable)
    page = _page_drive(hub_change, tmp_path, PRELUDE + """
await open("devices");
SW.setLock("unlocked", { code: "__CODE__" });
const card = (start) => $$("main .card").find((c) => text($("h2", c)).startsWith(start));
await until(() => text(card("Weigh")).includes("Could not read"), "the requests error");
await until(() => text(card("Trusted")).includes("No computer is trusted"), "the trusted list");
await sleep(300);
const sw = $(".toggle__input", card("Trusted"));
return { nulls: $$("main *").filter((e) => e.children.length === 0 && e.textContent.trim() === "null").length, trusted: text(card("Trusted")),
  requests: text(card("Weigh")), width: sw.getBoundingClientRect().width,
  pair: [card("Weigh"), card("The web app")].map((c) => Math.round(c.getBoundingClientRect().height)) };
""")
    assert page["nulls"] == 0 and "null" not in page["trusted"].split()           # no literal null under "No computer is trusted."
    assert page["width"] >= 36                                                    # the switch keeps its own width (not a blob)
    assert "Error" not in page["requests"] and "certificate" in page["requests"]  # the Hub's reason, no Python class name
    assert page["pair"][0] == page["pair"][1]                                     # a pair of cards is as tall as the taller one


def test_brand_stays_on_one_line_at_320(hub_change, tmp_path):
    page = _page_drive(hub_change, tmp_path, PRELUDE + """
await open("overview");
SW.setLock("unlocked", { code: "__CODE__" });                                 // the wider "Unlocked" chip is what squeezes the brand
await sleep(500);
const n = $(".topbar__name");
return { height: n.getBoundingClientRect().height, line: parseFloat(getComputedStyle(n).lineHeight), whole: n.scrollWidth <= n.clientWidth };
""", width=320)
    assert page["height"] <= page["line"] + 1 and page["whole"]                  # "filament-kit" on one line, not cut


def test_the_setup_command_box_never_cuts_the_command_at_320(hub_change, tmp_path):
    page = _page_drive(hub_change, tmp_path, PRELUDE + """
await open("features");
const pre = await until(() => $$(".code__text").find((p) => p.textContent.includes("features setup")), "the command box");
return { cut: pre.scrollWidth > pre.clientWidth + 1, whiteSpace: getComputedStyle(pre).whiteSpace };
""", width=320)
    assert not page["cut"] and page["whiteSpace"] != "pre"                        # wrapped: the whole command is on show


def test_updates_title_is_at_the_top_of_its_header(hub_change, tmp_path):
    page = _page_drive(hub_change, tmp_path, PRELUDE + """
await open("updates");
SW.setLock("unlocked", { code: "__CODE__" });
await sleep(500); await settle();
const head = $(".page-head");
return { gap: $("h1").getBoundingClientRect().top - head.getBoundingClientRect().top, actions: !!$(".page-head__actions") };
""")
    assert page["actions"] and page["gap"] < 2                                    # not pushed down by the Check now button


def test_logs_service_select_ends_a_long_name_in_an_ellipsis(hub_change, tmp_path):
    page = _page_drive(hub_change, tmp_path, PRELUDE + """
await open("logs");
return { overflow: getComputedStyle($("main select")).textOverflow };
""", width=320)
    assert page["overflow"] == "ellipsis"
