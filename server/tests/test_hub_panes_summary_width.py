"""Panes, the middle pane of every Hub section (found in v0.6.1): a row's one-line summary ("7 locations", "Automatic: On this Hub
first, Cloud when it is unsure or fails", "Last: 2026-11-16 00:13") got a column a few characters wide and wrapped to a letter a
line. In a real headless browser, at 1280, 1776 and tablet widths (768, 1024), each section's rows in Panes keep every summary
at least 8em wide (unless it is one short line) and at most two lines, with the real text and with the long texts of the
report put in. The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import pytest

from test_hub_page_audit import SECTIONS, hub_app  # noqa: F401
from test_hub_presets_ui import _drive, hub  # noqa: F401

# every summary cell a middle pane draws: Settings' state text, and a collection row's cells other than its title and controls
MEASURE = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const d = document, r = d.documentElement, $$ = (s, el) => [...(el || d).querySelectorAll(s)];
r.setAttribute("data-look", "panes");
const LONG = ["Automatic: On this Hub first, Cloud when it is unsure or fails", "Last: 2026-11-16 00:13 - 14 files, 3 of them new", "7 locations"];
const CELLS = '.settings__state, .coll__item > .coll__row:first-child > .coll__cell:not([data-col="title"], [data-col="actions"], [data-col="expand"], [data-col="visual"], [data-col="select"], [data-col="go"], [aria-colspan])';
const out = {};
for (const section of __SECTIONS__) {
  location.hash = "#" + section;
  await sleep(1200);
  const found = [];
  const measure = (label) => {
    for (const el of $$(CELLS)) {
      if (!el.getClientRects().length || !el.textContent.trim() || el.closest("[hidden]")) continue;
      const cs = getComputedStyle(el), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4, row = el.closest(".settings__row, .coll__row");
      const w = el.getBoundingClientRect().width, h = el.getBoundingClientRect().height;
      found.push({ label, text: el.textContent.trim().slice(0, 40), w: Math.round(w), em: Math.round(w / parseFloat(cs.fontSize) * 10) / 10,
        lines: Math.round(h / lh), rowW: Math.round(row.getBoundingClientRect().width) });
    }
  };
  measure("real");
  let i = 0;
  for (const el of $$(CELLS)) { if (el.getClientRects().length && el.textContent.trim()) el.textContent = LONG[i++ % LONG.length]; }
  await sleep(200);
  measure("long");
  out[section] = found;
}
return { vw: r.clientWidth, out };
"""


@pytest.mark.parametrize("width", [1280, 1776, 1024, 768])
def test_every_section_row_summary_in_panes_stays_a_readable_block(hub, tmp_path, width):
    script = MEASURE.replace("__SECTIONS__", repr(list(SECTIONS)).replace("'", '"'))
    got = _drive(hub, tmp_path, script, width=width)
    seen = [(s, c) for s, cells in got["out"].items() for c in cells]
    assert any(c["label"] == "long" for _, c in seen), "no summary cell was found to measure"
    assert any(s == "settings" for s, _ in seen), "Settings' rows were not measured"
    bad = [(s, c["label"], c["text"], c["w"], c["lines"]) for s, c in seen if c["lines"] > 2 or (c["em"] < 8 and c["lines"] > 1)]
    assert not bad, (width, "a summary squeezed to a sliver or wrapped past two lines", bad)
