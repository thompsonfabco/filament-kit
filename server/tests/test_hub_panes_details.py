"""Panes details (design 09 S6.12, 02 6.2 and 6.4): one detail open at a time, Escape/Back returning focus to the row,
empty-pane state on desktop, row actions and hidden fields inside the detail, and Settings one group per pane."""
from __future__ import annotations

from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401


PANES_PRINTERS = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s, root = d) => root.querySelector(s), $$ = (s, root = d) => [...root.querySelectorAll(s)], cs = (el) => getComputedStyle(el);
r.setAttribute("data-look", "panes");
location.hash = "#printers";
await until(() => $$(".coll--printers .coll__expand").length >= 2, "two printers");
const empty = $(".coll--printers .coll__pane-empty");
const initial = { emptyVisible: cs(empty).display !== "none", emptyText: empty.textContent.trim(), rowActionsDisplay: cs($('.coll--printers .coll__cell[data-col="actions"]')).display };
const [e1, e2] = $$(".coll--printers .coll__expand");
e1.click();
await sleep(100);
const first = { openCount: $$(".coll--printers .detail:not([hidden])").length, current: e1.closest(".coll__item").getAttribute("aria-current"), emptyHidden: cs(empty).display === "none", testInDetail: cs($(".coll--printers .detail:not([hidden]) .panes-only")).display !== "none" };
e2.click();
await sleep(100);
const second = { openCount: $$(".coll--printers .detail:not([hidden])").length, c1: e1.closest(".coll__item").getAttribute("aria-current"), c2: e2.closest(".coll__item").getAttribute("aria-current") };
const dt = $(".coll--printers .detail:not([hidden]) .detail__title");
dt.focus();
dt.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
await sleep(100);
return { initial, first, second, afterEsc: { openCount: $$(".coll--printers .detail:not([hidden])").length, focusReturned: d.activeElement === e2 } };
"""


def test_panes_printers_empty_pane_single_open_escape_and_actions(hub, tmp_path):
    got = _drive(hub, tmp_path, PANES_PRINTERS, width=1280)
    assert got["initial"] == {"emptyVisible": True, "emptyText": T("printers_pane_empty"), "rowActionsDisplay": "none"}
    assert got["first"] == {"openCount": 1, "current": "true", "emptyHidden": True, "testInDetail": True}
    assert got["second"] == {"openCount": 1, "c1": None, "c2": "true"}
    assert got["afterEsc"] == {"openCount": 0, "focusReturned": True}


PANES_PRESETS_AND_BACK = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s, root = d) => root.querySelector(s), $$ = (s, root = d) => [...root.querySelectorAll(s)], cs = (el) => getComputedStyle(el);
r.setAttribute("data-look", "panes");
location.hash = "#presets";
const exp = await until(() => $(".coll--lines .coll__expand"), "presets expand");
exp.click();
await sleep(100);
const det = $(".coll--lines .detail:not([hidden])");
const out = {
  backVisible: cs($(".detail__back", det)).display !== "none",
  headVisible: cs($(".detail__head", det)).display !== "none",
  panesOnlyVisible: $$(".panes-only", det).every((el) => cs(el).display !== "none"),
};
$(".detail__back", det).click();
await sleep(100);
out.closedOnBack = !$(".coll--lines .detail:not([hidden])");
out.focusReturned = d.activeElement === exp;
return out;
"""


def test_panes_presets_detail_shows_hidden_fields_and_back_on_tablet(hub, tmp_path):
    got = _drive(hub, tmp_path, PANES_PRESETS_AND_BACK, width=768)
    assert got == {"backVisible": True, "headVisible": True, "panesOnlyVisible": True, "closedOnBack": True, "focusReturned": True}


PANES_SETTINGS = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s, root = d) => root.querySelector(s), $$ = (s, root = d) => [...root.querySelectorAll(s)], cs = (el) => getComputedStyle(el);
r.setAttribute("data-look", "panes");
location.hash = "#settings";
await until(() => $(".settings__list .settings__row"), "settings list");
await sleep(100);
const visibleGroups = () => $$(".settings__group").filter((g) => cs(g).display !== "none").map((g) => g.dataset.id);
const start = { listVisible: cs($(".settings__list")).display !== "none", subnavHidden: cs($(".settings .subnav")).display === "none", shown: visibleGroups() };
location.hash = "#settings/general";
await sleep(100);
return { start, after: { shown: visibleGroups() } };
"""


def test_panes_settings_shows_one_group_per_pane(hub, tmp_path):
    got = _drive(hub, tmp_path, PANES_SETTINGS, width=1280)
    assert got["start"]["listVisible"] is True and got["start"]["subnavHidden"] is True
    assert len(got["start"]["shown"]) == 1
    assert got["after"]["shown"] == ["general"]
