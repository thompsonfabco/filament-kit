"""Palette sheets (design 09 S6.11, 02 6.2): Printers and Slicer presets open and close details through the shared
opener, so Palette draws them in #detail-host (full-height sheet), focuses the title, returns focus to the row on
close, keeps #printers/<id> working, and collapses non-current steps in .sheet--detail."""
from __future__ import annotations

from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, hub  # noqa: F401


PRINTERS_SHEET = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s, root = d) => root.querySelector(s);
r.setAttribute("data-look", "palette");
location.hash = "#printers";
const expand = await until(() => $(".coll--printers .coll__expand"), "printers expand button");
expand.focus();
expand.click();
const dlg = await until(() => $("#detail-host[open]"), "detail-host open");
await sleep(100);
const opened = {
  inHost: !!$(".detail", dlg),
  titleFocused: d.activeElement === $(".detail__title", dlg),
  expanded: expand.getAttribute("aria-expanded"),
  hash: location.hash,
};
$(".detail__close", dlg).click();
await until(() => !dlg.open, "detail-host closed");
await sleep(100);
const closed = {
  returned: !$(".detail", dlg) && !!$(".coll--printers .detail"),
  expanded: expand.getAttribute("aria-expanded"),
  focusReturned: d.activeElement === expand,
  hash: location.hash,
};
return { opened, closed };
"""


def test_printers_detail_opens_in_palette_sheet_and_returns_focus(hub, tmp_path):
    got = _drive(hub, tmp_path, PRINTERS_SHEET, width=1280)
    assert got["opened"]["inHost"] is True and got["opened"]["titleFocused"] is True
    assert got["opened"]["expanded"] == "true"
    assert got["closed"]["returned"] is True and got["closed"]["expanded"] == "false"
    assert got["closed"]["focusReturned"] is True and got["closed"]["hash"] == "#printers"


PRESETS_SHEET = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s, root = d) => root.querySelector(s);
r.setAttribute("data-look", "palette");
location.hash = "#presets";
const expand = await until(() => $(".coll--lines .coll__expand"), "presets expand button");
expand.focus();
expand.click();
const dlg = await until(() => $("#detail-host[open]"), "detail-host open");
await sleep(100);
const opened = {
  inHost: !!$(".detail", dlg),
  headVisible: getComputedStyle($(".detail__head", dlg)).display !== "none",
  titleFocused: d.activeElement === $(".detail__title", dlg),
};
$(".detail__close", dlg).click();
await until(() => !dlg.open, "detail-host closed");
await sleep(100);
return { opened, focusReturned: d.activeElement === expand };
"""


def test_presets_detail_opens_in_palette_sheet_and_returns_focus(hub, tmp_path):
    got = _drive(hub, tmp_path, PRESETS_SHEET, width=1280)
    assert got["opened"] == {"inHost": True, "headVisible": True, "titleFocused": True}
    assert got["focusReturned"] is True


STEPS_COLLAPSE = """
const d = document, r = d.documentElement, cs = (el) => getComputedStyle(el);
const dlg = d.createElement("dialog");
dlg.className = "sheet sheet--detail";
dlg.innerHTML = `<section class="detail"><ol class="steps">
  <li class="steps__step" data-state="done"><span class="steps__num">1</span><div class="steps__body"><h4 class="steps__title">One</h4><p class="p1">Body 1</p></div></li>
  <li class="steps__step" aria-current="step"><span class="steps__num">2</span><div class="steps__body"><h4 class="steps__title">Two</h4><p class="p2">Body 2</p></div></li>
  <li class="steps__step" data-state="later"><span class="steps__num">3</span><div class="steps__body"><h4 class="steps__title">Three</h4><p class="p3">Body 3</p></div></li>
</ol></section>`;
d.body.append(dlg);
dlg.showModal();
const measure = (look) => {
  r.setAttribute("data-look", look);
  return { p1: cs(dlg.querySelector(".p1")).display, p2: cs(dlg.querySelector(".p2")).display, p3: cs(dlg.querySelector(".p3")).display };
};
const out = { palette: measure("palette"), console: measure("console") };
dlg.close(); dlg.remove();
return out;
"""


def test_one_step_at_a_time_collapses_non_current_steps_in_palette_sheet(hub, tmp_path):
    got = _drive(hub, tmp_path, STEPS_COLLAPSE, width=1280)
    assert got["palette"] == {"p1": "none", "p2": "block", "p3": "none"}
    assert got["console"] == {"p1": "block", "p2": "block", "p3": "block"}
