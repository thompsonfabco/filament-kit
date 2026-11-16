"""Shared parts the looks need (design 09 S6.4b, 02 2.3 and 6.1, R78): the 'Sort by' label in sortable collection heads
(hidden under Console's table, shown before sort chips in cards/tiles/rows) and the navigation's switched-off mark
(data-state='off', hidden ', switched off' suffix in all four looks, hollow-circle ::after in sidebar and list only)."""
from __future__ import annotations

import pytest

from filament_kit import api, cli, config, modules, setup_code, setup_helper
from filament_kit.spoolman import Spoolman
from fakes import serving
from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_setup_page import CODE, FakeManager, Helper


@pytest.fixture
def off_hub(tmp_path, monkeypatch, spoolman_url):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setenv("FK_SETUP_RUN", str(tmp_path / "run"))
    monkeypatch.setattr(cli.shutil, "chown", lambda *a, **k: None)
    monkeypatch.setattr(setup_helper, "_start_apply", lambda checked=False: None)
    cfg = config.load()
    cfg["modules"] = {n: False for n in modules.MODULES}
    cfg["web"] = {**cfg["web"], "lan": ["127.0.0.0/8"]}
    cfg["server_name"] = "Workshop hub"
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    setup_code.write(CODE)
    port = [0]
    app = api.create_app(
        Spoolman(spoolman_url), printers=FakeManager(), camera_hub=object(), mapper=object(),
        enabled_modules=frozenset(),
        setup={"helper": Helper(), "hosts": lambda: {"127.0.0.1", f"127.0.0.1:{port[0]}"}},
    )
    running = serving.start(app)
    port[0] = running.port
    try:
        yield f"http://127.0.0.1:{running.port}/setup"
    finally:
        running.stop()


SORT_LABEL = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s, root = d) => root.querySelector(s), cs = (el) => getComputedStyle(el);
location.hash = "#printers";
await until(() => $(".coll--printers .coll__item"), "the printers collection");
await sleep(200);
const measure = (look) => {
  r.setAttribute("data-look", look);
  const lbl = $(".coll--printers .coll__sortlabel"), chip = $(".coll--printers .coll__sort");
  const lb = lbl ? lbl.getBoundingClientRect() : null, cb = chip ? chip.getBoundingClientRect() : null;
  return {
    exists: !!lbl,
    text: lbl ? lbl.textContent.trim() : null,
    ariaHidden: lbl ? lbl.getAttribute("aria-hidden") : null,
    display: lbl ? cs(lbl).display : null,
    width: lb ? Math.round(lb.width) : 0,
    beforeChip: lb && cb ? lb.right <= cb.left + 1 : false,
  };
};
const out = { console: measure("console"), workbench: measure("workbench"), palette: measure("palette"), panes: measure("panes") };
location.hash = "#features";
await until(() => $(".coll--features .coll__item"), "the features collection");
out.featuresSortLabel = !!$(".coll--features .coll__sortlabel");
return out;
"""


def test_sort_by_label_hidden_in_console_and_shown_in_other_looks(hub, tmp_path):
    got = _drive(hub, tmp_path, SORT_LABEL, width=1280)
    assert got["console"]["exists"] is True and got["console"]["text"] == T("coll_sort_by")
    assert got["console"]["ariaHidden"] == "true"
    assert got["console"]["display"] == "none" and got["console"]["width"] == 0
    for look in ("workbench", "palette", "panes"):
        assert got[look]["display"] == "block" and got[look]["width"] > 0 and got[look]["beforeChip"] is True, look
    assert got["featuresSortLabel"] is False


NAV_OFF = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s, root = d) => root.querySelector(s), cs = (el, p) => getComputedStyle(el, p);
await until(() => $('.shell .nav__item[href="#presets"][data-state="off"]'), "switched-off nav item");
const check = (look) => {
  r.setAttribute("data-look", look);
  const item = (h) => $(`.shell .nav__item[href="#${h}"]`);
  const info = (h) => {
    const a = item(h), lbl = $(".nav__label", a), sr = lbl ? $(".sr", lbl) : null, aft = lbl ? cs(lbl, "::after") : null;
    return {
      state: a.getAttribute("data-state"),
      sr: sr ? sr.textContent : null,
      afterDisplay: aft ? aft.display : null,
      afterWidth: aft ? aft.width : null,
    };
  };
  return { overview: info("overview"), printers: info("printers"), presets: info("presets") };
};
return { console: check("console"), workbench: check("workbench"), palette: check("palette"), panes: check("panes") };
"""


def test_navigation_marks_switched_off_sections_with_hollow_circle_and_suffix(off_hub, tmp_path):
    got = _drive(off_hub, tmp_path, NAV_OFF, width=1280)
    for look in ("console", "workbench", "palette", "panes"):
        assert got[look]["overview"]["state"] is None and got[look]["overview"]["sr"] is None, look
        for sec in ("printers", "presets"):
            item = got[look][sec]
            assert item["state"] == "off" and item["sr"] == T("nav_off_suffix"), (look, sec, item)
            if look in ("workbench", "panes"):
                assert item["afterDisplay"] == "inline-block" and item["afterWidth"] == "16px", (look, sec, item)
            else:
                assert item["afterDisplay"] == "none", (look, sec, item)


def test_console_dims_switched_off_nav_without_ring_and_more_label_drops_suffix(off_hub, tmp_path):
    got = _drive(off_hub, tmp_path, """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, $ = (s) => d.querySelector(s), cs = (el, p) => getComputedStyle(el, p);
await until(() => $('.shell .nav__item[href="#presets"][data-state="off"]'), "presets off");
location.hash = "#presets";
await sleep(100);
const a = $('.shell .nav__item[href="#presets"]'), lbl = $(".nav__label", a);
return {
  state: a.getAttribute("data-state"),
  sr: $(".sr", lbl).textContent,
  color: cs(a).color,
  ringDisplay: cs(lbl, "::after").display,
  moreLabel: $(".nav__more").getAttribute("aria-label"),
};
""", width=320)
    assert got["state"] == "off" and got["sr"] == T("nav_off_suffix")
    assert got["ringDisplay"] == "none"
    assert T("nav_off_suffix") not in (got["moreLabel"] or "")
