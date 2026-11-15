"""The Updates section of the Hub page (03 12.1, 12.2) in a real headless browser: Check now and Update to <latest> are the
section header's buttons (as Overview and Slicer presets have theirs), and the Features pointer in the Checking row is an
inline text link. Served with the data of test_hub_page_audit.py. The same skip rules as the page audit."""
from __future__ import annotations

from filament_kit import updates

from test_hub_page_audit import UPDATES, hub_app  # noqa: F401
from test_hub_presets_ui import _drive, hub  # noqa: F401

SCRIPT = """const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 100; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const $ = (s, root = document) => root.querySelector(s);
location.hash = "#updates";
await until(() => $(".updates__cards .kv"), "the Version list");
const label = (b) => [...b.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("");
const link = $('.updates__cards .kv__value a[href="#features"]');
return { head: [...document.querySelectorAll(".page-head > .page-head__actions > .btn")].map((b) => [label(b), b.classList.contains("btn--primary")]),
  strays: document.querySelectorAll("main .page-head__actions").length, cards: !!$(".updates__cards .page-head__actions"),
  link: link ? { classes: link.className, inline: getComputedStyle(link).display, inText: link.parentElement.matches(".kv__value > span") && link.parentElement.textContent.includes("switched off") } : null };
"""


def test_check_now_and_update_are_the_section_header_buttons_and_features_is_an_inline_link(hub, monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "view", lambda cfg: {**UPDATES, "module_on": False})
    page = _drive(hub, tmp_path, SCRIPT)
    assert page["head"] == [["Check now", False], ["Update to 0.5.3", True]]
    assert page["strays"] == 1 and not page["cards"]                         # one actions row, in the header
    link = page["link"]
    assert link and link["classes"] == "" and link["inline"] == "inline"      # a link, not a button, and in the text line
    assert link["inText"]                                                     # in the same run of text, not an item of its own
