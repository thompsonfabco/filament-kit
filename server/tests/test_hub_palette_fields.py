"""Palette tiles in a collection with no detail (design R67 point 5): a collection with no expand column (the features, the
backups, the devices) shows its priority-2 fields in each tile, as Workbench cards do; one with a detail (the printers, the preset
lines) keeps the first-priority fields only; Console, Workbench and Panes are not changed by it."""
from __future__ import annotations

from test_hub_palette import PAL
from test_hub_workbench import CSS, SERVED_CSS
from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, hub  # noqa: F401


def test_the_palette_rule_for_collections_without_a_detail_is_in_the_served_stylesheet():
    for css in (CSS, SERVED_CSS):
        rule = [s for s in css.splitlines() if s.startswith(PAL + " .coll:not(:has(.coll__expand))")]
        assert len(rule) == 1 and '[data-prio="2"]' in rule[0] and "display:block" in rule[0], rule
        assert len(css.encode("utf-8")) < 60_000


FIELDS = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, cs = (el) => getComputedStyle(el);
const shown = (sel) => [...d.querySelectorAll(sel)].map((c) => cs(c).display !== "none");
const snap = (look) => { r.setAttribute("data-look", look);
  return { prio2: shown('.coll--features .coll__item .coll__cell[data-prio="2"]'), prio3: shown('.coll--features .coll__item .coll__cell[data-prio="3"]'),
    head2: shown('.coll--features .coll__head .coll__cell[data-prio="2"]') }; };
location.hash = "#features";
await until(() => d.querySelector(".coll--features .coll__item"), "the features list");
await sleep(300);
const out = { console: snap("console"), palette: snap("palette"), workbench: snap("workbench"), panes: snap("panes"), back: snap("console") };
location.hash = "#printers";
await until(() => d.querySelector(".coll--printers .coll__item"), "the printers list");
await sleep(300);
const printers = (look) => { r.setAttribute("data-look", look); return { expand: !!d.querySelector(".coll--printers .coll__expand"),
  shown: [...d.querySelectorAll('.coll--printers .coll__item .coll__cell[data-prio="2"], .coll--printers .coll__item .coll__cell[data-prio="3"]')].filter((c) => cs(c).display !== "none").length }; };
out.printers = { palette: printers("palette"), console: printers("console") };
return out;
"""


def test_palette_tiles_without_a_detail_show_their_second_priority_fields(hub, tmp_path):
    got = _drive(hub, tmp_path, FIELDS, width=1280)
    pal, con = got["palette"], got["console"]
    assert pal["prio2"] and all(pal["prio2"]), pal                                   # the features' tiles show what each does
    assert not any(pal["prio3"]) and not any(pal["head2"]), pal                      # third priority stays hidden; the header cells too
    assert got["back"] == con, "Console is not the same after Palette"
    assert got["workbench"]["prio2"] == con["prio2"] and got["panes"] == {"prio2": [False] * len(pal["prio2"]), "prio3": [False] * len(pal["prio3"]),
                                                                         "head2": got["panes"]["head2"]}, got
    assert got["printers"]["palette"]["expand"] and got["printers"]["palette"]["shown"] == 0, got["printers"]   # a collection with a detail keeps first priority only
