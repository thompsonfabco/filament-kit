"""The Features section and the shell of the Hub page, in a real headless browser: the four header cells of the features
collection sit on one line, and on a page taller than the window the navigation's background runs the full page height.
Served with the data of test_hub_page_audit.py. The same skip rules as the page audit."""
from __future__ import annotations

from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, hub  # noqa: F401

PRELUDE = """const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 100; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const $ = (s, root = document) => root.querySelector(s);
location.hash = "#features";
await until(() => $(".coll--features .coll__item, .coll--features [data-key]"), "the features");
"""


def test_the_four_header_cells_of_the_features_collection_share_one_line(hub, tmp_path):
    page = _drive(hub, tmp_path, PRELUDE + """
const tops = [...document.querySelectorAll('.coll--features .coll__head [role="columnheader"]')].slice(0, 4).map((c) => {
  const r = document.createRange(); r.selectNodeContents(c); const b = r.getBoundingClientRect(); return [c.textContent.trim(), b.top, b.bottom]; });
return tops;
""")
    assert [t[0] for t in page] == ["Feature", "State", "What it does", "Needs"]
    assert max(t[1] for t in page) - min(t[1] for t in page) <= 1 and max(t[2] for t in page) - min(t[2] for t in page) <= 1, page


def test_on_a_page_taller_than_the_window_the_navigation_background_runs_the_page_height(hub, tmp_path):
    page = _drive(hub, tmp_path, PRELUDE + """
const shell = $(".shell"), nav = $(".shell > .nav"), cs = getComputedStyle(shell);
return { tall: document.documentElement.scrollHeight > innerHeight * 1.2, doc: document.documentElement.scrollHeight, shell: shell.getBoundingClientRect().height,
  image: cs.backgroundImage, rail: nav.getBoundingClientRect().width };
""")
    assert page["tall"]
    assert "linear-gradient" in page["image"] and page["shell"] >= page["doc"] - 1, page
