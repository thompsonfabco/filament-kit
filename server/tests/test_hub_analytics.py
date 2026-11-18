"""The Analytics section of the Hub page (R84 section 5, 9.2, 9.3), in a real headless browser against a stub of the kit's
analytics (HD3's module is not in this tree): the six insight sentences in their order (and none when the Hub has none), one
SVG bar per month for twelve months with an empty one among them, the choice of printer, Show as table, the table per
material for the chosen month, the honest notes, "No usage yet", the wait and the failure with Try again, in all four looks at
1280 and 390 px (nothing wider than the page; Panes does not squeeze a label to a sliver). The section's own files are put in
the page by the driver (its --init script and a style sheet made in the page), as the registry that mounts them is HD7e's.
The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import date
from pathlib import Path

import httpx
import pytest

from filament_kit import setup_console
from filament_kit.setup_console import analytics_tab
from test_hub_page_audit import _missing, _node, _serve, hub_app  # noqa: F401
from test_hub_presets_ui import AsHttps
from test_hub_settings import PRELUDE

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tests" / "page_drive.mjs"
STATIC = ROOT / "server" / "filament_kit" / "setup_static"
LOOKS = ["console", "workbench", "palette", "panes"]
REAL_READ = analytics_tab.read


def month(back: int) -> str:
    today = date.today()
    y, m = today.year, today.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}"


P1, P2 = {"id": "p1", "name": "Workshop X1"}, {"id": "p2", "name": "Garage Voron"}


def row(back, grams, prints, **extra):
    return {"month": month(back), "grams": grams, "prints": prints, "unfinished_prints": 0, "unfinished_grams": 0,
            "logged_only_grams": 0, "no_weight_prints": 0, "by_printer": [], "by_material": [], **extra}


# the Hub's answer for all printers: this month, last month, a quiet month (back 2), the rest, and no entry at all for back 5
ALL = {
    "months": [
        row(0, 1840.0, 12, unfinished_prints=2, unfinished_grams=310.0, logged_only_grams=120.0, no_weight_prints=1, top_material="PLA",
            by_printer=[{**P1, "grams": 1100.0, "prints": 7}, {**P2, "grams": 740.0, "prints": 5}],
            by_material=[{"material": "PETG", "grams": 640.0}, {"material": "PLA", "grams": 1200.0}]),
        row(1, 1520.0, 10, top_material="PETG", by_printer=[{**P1, "grams": 1520.0, "prints": 10}], by_material=[{"material": "PETG", "grams": 1520.0}]),
        row(2, 640.0, 5, top_material="PA6", by_printer=[{**P2, "grams": 640.0, "prints": 5}], by_material=[{"material": "PA6", "grams": 640.0}]),
        row(3, 980.0, 8, top_material="PLA", by_printer=[{**P1, "grams": 980.0, "prints": 8}], by_material=[{"material": "PLA", "grams": 980.0}]),
        row(4, 410.0, 3, top_material="PLA", by_printer=[{**P1, "grams": 410.0, "prints": 3}], by_material=[{"material": "PLA", "grams": 410.0}]),
        row(6, 300.0, 2, top_material="ABS", by_material=[{"material": "ABS", "grams": 300.0}]),
        row(11, 90.0, 1, top_material="PLA", by_material=[{"material": "PLA", "grams": 90.0}]),
    ],
    # sent in the wrong order on purpose: the page keeps the order of R84 5.2
    "insights": [
        {"key": "spools_finished", "text": "You finished 3 spools this month."},
        {"key": "biggest_print", "text": "The biggest print this month was Benchy (210 g)."},
        {"key": "unfinished", "text": "2 of 12 prints did not finish this month (310 g)."},
        {"key": "busiest_printer", "text": "Workshop X1 did the most work this month (1.1 kg, 7 prints)."},
        {"key": "favourite_material", "text": "Your favourite material this month was PLA (1200 g)."},
        {"key": "total", "text": "Filament used this month: 1.84 kg (last month 1.52 kg)."},
    ],
    "notes": ["Includes 120 g the Hub logged but took off no spool.", "1 print has no weight."],
}
ONE = {"months": [row(0, 740.0, 5, top_material="PLA", by_printer=[{**P2, "grams": 740.0, "prints": 5}], by_material=[{"material": "PLA", "grams": 740.0}]),
                  row(1, 600.0, 4, top_material="PLA", by_printer=[{**P2, "grams": 600.0, "prints": 4}], by_material=[{"material": "PLA", "grams": 600.0}])],
       "insights": [{"key": "total", "text": "Filament used this month: 740 g (last month 600 g)."}], "notes": []}
QUIET = {"months": [], "insights": [], "notes": []}


@pytest.fixture
def stub(monkeypatch):
    """The kit's analytics, as a stub the test steers: what it answers (by printer), how long it waits, whether it fails."""
    st = {"answers": {None: ALL, "p2": ONE}, "delay": 0.0, "fail": 0, "calls": []}

    def read(months, printer):
        st["calls"].append((months, printer))
        time.sleep(st["delay"])
        if st["fail"] > 0:                       # the next `fail` reads fail
            st["fail"] -= 1
            raise RuntimeError("the stub is down")
        return json.loads(json.dumps(st["answers"].get(printer, QUIET)))

    monkeypatch.setattr(analytics_tab, "read", read)
    return st


@pytest.fixture
def hub(stub, monkeypatch):
    """The Hub page with this section's route mounted (the mount is HD7e's, so the test adds it before the app is made:
    list this fixture before hub_app)."""
    mounted = setup_console.routes
    monkeypatch.setattr(setup_console, "routes", lambda page: mounted(page) + analytics_tab.routes(page))


@pytest.fixture
def url(hub, hub_app):  # noqa: F811
    running = _serve(AsHttps(hub_app[0]), hub_app[1])
    try:
        yield running.url + "/setup"
    finally:
        running.stop()


def _drive(url, tmp_path, script, width=1280, look="console"):
    node = _node()
    if not node:
        _missing("the page driver needs Node 22 or later")
    (tmp_path / "init.js").write_text((STATIC / "setup_analytics.js").read_text(encoding="utf-8"), encoding="utf-8")
    css = json.dumps((STATIC / "setup_analytics.css").read_text(encoding="utf-8"))
    (tmp_path / "drive.js").write_text(
        PRELUDE.replace('location.hash = "#settings";\n', "") + HELPERS.replace("__CSS__", css).replace("__LOOK__", look) + script, encoding="utf-8")
    run = subprocess.run([node, str(DRIVER), "--url", url, "--script", str(tmp_path / "drive.js"), "--init", str(tmp_path / "init.js"), "--width", str(width)],
                         capture_output=True, encoding="utf-8", timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("the page driver needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("page driver: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


HELPERS = r"""
const sheet = new CSSStyleSheet();
sheet.replaceSync(__CSS__);
document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
document.documentElement.setAttribute("data-look", "__LOOK__");
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const busy = () => $('.an [aria-busy="true"]');
const ready = async () => {
  await until(() => typeof S !== "undefined" && S && $("main"), "the Hub's state");
  TABS.analytics = ["nav_updates", "updates", () => [analyticsTab]];      // the registry (HD7e) adds this entry
  location.hash = "#analytics";
  await until(() => $(".an"), "the section");
};
const settled = () => until(() => ($(".an__main") && !$(".an__main").hidden || $(".an .error-state")) && !busy(), "the answer");
const bars = () => $$(".an-bar").map((li) => ({ month: li.dataset.month, grams: text($(".an-bar__grams", li)), label: text($(".an-bar__month", li)),
  level: li.style.getPropertyValue("--level"), empty: li.dataset.empty === "true", svg: !!$("svg.an-bar__svg rect", li), hidden: $("svg", li).getAttribute("aria-hidden") }));
const tableRows = (el) => $$("tbody tr", el).map((tr) => $$("th, td", tr).map(text));
const insightList = () => $$(".an__insights li").map((li) => [li.dataset.key, text(li)]);
const choose = (field, value) => { const c = $("select", field); c.value = value; c.dispatchEvent(new Event("change", { bubbles: true })); };
const fields = () => ({ printer: $('.an__controls select[name="printer"]').closest(".field"), month: $('.an__by-material select[name="month"]').closest(".field") });
const overflow = () => ({ page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  cards: Math.max(0, ...$$(".an__main > .card").map((c) => Math.round(c.getBoundingClientRect().right - document.documentElement.clientWidth))) });
const lines = (el) => { const cs = getComputedStyle(el), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4; return Math.round(el.getBoundingClientRect().height / lh); };
await ready();
"""


def months_expected():
    return [month(back) for back in range(11, -1, -1)]


@pytest.mark.parametrize("look", LOOKS)
@pytest.mark.parametrize("width", [1280, 390])
def test_insights_bars_notes_and_material_table_in_every_look(url, stub, tmp_path, look, width):
    page = _drive(url, tmp_path, r"""
await settled();
const out = {};
out.insights = insightList();
out.bars = bars();
out.label = $(".an-chart").getAttribute("aria-label");
out.notes = $$(".an__notes li").map(text);
out.titles = $$(".an__main h2").map(text);
out.printers = $$("select[name=printer] option").map((o) => [o.value, text(o)]);
const f = fields();
out.monthOptions = $$("option", f.month).length;
out.month = $("select", f.month).value;
out.materials = tableRows($(".an__materials"));
out.materialHead = $$(".an__materials thead th").map(text);
out.overflow = overflow();
out.narrow = getComputedStyle($(".an-bar")).gridTemplateAreas !== "none";
out.grams = $$(".an-bar__grams").map((e) => [e.getBoundingClientRect().width > 0, lines(e)]);
out.fieldWidths = [f.printer, f.month].map((e) => Math.round(e.getBoundingClientRect().width));
out.vw = document.documentElement.clientWidth;
return out;
""", width=width, look=look)
    # R84 5.2: the six sentences in their order, whatever order the Hub sent them in
    assert [k for k, _ in page["insights"]] == ["total", "favourite_material", "busiest_printer", "unfinished", "biggest_print", "spools_finished"]
    assert page["insights"][0][1] == "Filament used this month: 1.84 kg (last month 1.52 kg)."
    # twelve bars, oldest first, each an SVG the screen reader skips (the table is the text way), the empty month among them
    assert [b["month"] for b in page["bars"]] == months_expected()
    assert all(b["svg"] and b["hidden"] == "true" for b in page["bars"])
    by = {b["month"]: b for b in page["bars"]}
    assert by[month(0)]["grams"] == "1.84 kg" and by[month(0)]["level"] == "1"
    assert by[month(2)]["grams"] == "640 g" and by[month(5)]["grams"] == "0 g" and by[month(5)]["empty"] and by[month(5)]["level"] == "0"
    assert by[month(1)]["level"] == str(1520 / 1840) or abs(float(by[month(1)]["level"]) - 1520 / 1840) < 1e-9
    assert page["label"] == "Filament used per month in the last 12 months"
    # R84 5.5: the Hub's two honest notes
    assert page["notes"] == ALL["notes"]
    assert page["titles"] == ["Highlights", "Filament used per month", "Filament used by material"]
    assert page["printers"] == [["", "All printers"], ["p1", "Workshop X1"], ["p2", "Garage Voron"]]
    # the material table is for the newest month with filament in it, the larger material first, with its share
    assert page["monthOptions"] == 12 and page["month"] == month(0)
    assert page["materialHead"] == ["Material", "Filament used", "Share"]
    assert page["materials"] == [["PLA", "1.20 kg", "65%"], ["PETG", "640 g", "35%"]]
    # nothing wider than the page; no label of a bar or a field squeezed to a sliver or wrapped past two lines
    assert page["overflow"]["page"] == 0 and page["overflow"]["cards"] <= 0
    assert page["narrow"] is True or width == 1280
    assert all(shown and n <= 2 for shown, n in page["grams"])
    assert all(w >= 160 for w in page["fieldWidths"]), page["fieldWidths"]


def test_wide_room_draws_the_bars_upright_and_a_narrow_one_lengthwise(url, stub, tmp_path):
    wide = _drive(url, tmp_path, "await settled(); return { narrow: getComputedStyle($('.an-bar')).gridTemplateAreas !== 'none', box: Math.round($('.an-chartbox').getBoundingClientRect().width) };", width=1776)
    narrow = _drive(url, tmp_path, "await settled(); return { narrow: getComputedStyle($('.an-bar')).gridTemplateAreas !== 'none', box: Math.round($('.an-chartbox').getBoundingClientRect().width) };", width=390)
    assert wide["narrow"] is False and wide["box"] > 800, wide
    assert narrow["narrow"] is True and narrow["box"] < 800, narrow


def test_choosing_a_printer_reads_again_for_that_printer_and_keeps_the_choice_list(url, stub, tmp_path):
    page = _drive(url, tmp_path, r"""
await settled();
const out = {};
const f = fields();
choose(f.printer, "p2");
await sleep(100);
await settled();
out.bars = bars().filter((b) => !b.empty).map((b) => [b.month, b.grams]);
out.insights = insightList();
out.notes = $$(".an__notes li").map(text);
out.options = $$("select[name=printer] option").map((o) => o.value);
out.chosen = $("select[name=printer]").value;
choose(fields().printer, "");
await sleep(100);
await settled();
out.back = bars().filter((b) => !b.empty).length;
return out;
""")
    assert stub["calls"] == [(12, None), (12, "p2"), (12, None)]
    assert page["bars"] == [[month(1), "600 g"], [month(0), "740 g"]]
    assert page["insights"] == [["total", "Filament used this month: 740 g (last month 600 g)."]]
    assert page["notes"] == []
    assert page["options"] == ["", "p1", "p2"] and page["chosen"] == "p2" and page["back"] == 7


def test_show_as_table_gives_month_grams_prints_unfinished_and_most_used_material(url, stub, tmp_path):
    page = _drive(url, tmp_path, r"""
await settled();
const out = {};
out.label = text($(".an__controls .check"));
$(".an__controls .check input").click();
await sleep(100);
out.chart = !!$(".an-chart");
out.head = $$(".an__chart thead th").map(text);
out.caption = text($(".an__chart caption"));
out.rows = tableRows($(".an__chart"));
out.notes = $$(".an__notes li").map(text);
$(".an__controls .check input").click();
await sleep(100);
out.back = !!$(".an-chart") && !$(".an__chart table");
return out;
""")
    assert page["label"] == "Show as table" and page["chart"] is False and page["back"] is True
    assert page["head"] == ["Month", "Filament used", "Prints", "Did not finish", "Most used material"]
    assert page["caption"] == "Filament used per month"
    assert len(page["rows"]) == 12 and page["rows"][0][1:] == ["1.84 kg", "12", "2 (310 g)", "PLA"] and page["rows"][1][1:] == ["1.52 kg", "10", "0", "PETG"]
    assert page["rows"][5][1:] == ["0 g", "0", "0", "None"]                      # back 5: no entry at all
    assert page["notes"] == ALL["notes"]


def test_the_material_table_follows_the_chosen_month(url, stub, tmp_path):
    page = _drive(url, tmp_path, r"""
await settled();
const out = {};
choose(fields().month, "__M2__");
await sleep(100);
out.two = tableRows($(".an__materials"));
choose(fields().month, "__M5__");
await sleep(100);
out.five = { text: text($(".an__materials")), table: !!$(".an__materials table") };
return out;
""".replace("__M2__", month(2)).replace("__M5__", month(5)))
    assert page["two"] == [["PA6", "640 g", "100%"]]
    assert page["five"]["table"] is False and page["five"]["text"].startswith("No filament was used in ")


def test_without_insights_the_highlights_are_not_shown(url, stub, tmp_path):
    stub["answers"][None] = {**ALL, "insights": [ALL["insights"][-1]]}
    page = _drive(url, tmp_path, "await settled(); return { items: insightList(), title: $$('.an__main h2').map(text) };")
    assert page["items"] == [["total", "Filament used this month: 1.84 kg (last month 1.52 kg)."]]
    stub["answers"][None] = {**ALL, "insights": []}
    page = _drive(url, tmp_path, "await settled(); return { shown: shown($('.an__insights')), title: $$('.an__main h2').filter(shown).map(text) };")
    assert page["shown"] is False and page["title"] == ["Filament used per month", "Filament used by material"]


def test_notes_are_drawn_from_the_months_when_the_hub_sends_none(url, stub, tmp_path):
    stub["answers"][None] = {**ALL, "notes": []}
    page = _drive(url, tmp_path, "await settled(); return $$('.an__notes li').map(text);")
    assert page == ["Includes 120 g the Hub logged but took off no spool.", "1 print has no weight."]


@pytest.mark.parametrize("look", LOOKS)
def test_no_usage_yet(url, stub, tmp_path, look):
    stub["answers"][None] = QUIET
    page = _drive(url, tmp_path, r"""
await settled();
return { title: text($(".an .empty__title")), text: text($(".an .empty__text")), bars: $$(".an-bar").length, material: shown($(".an__by-material")),
  check: shown($(".an__controls .check")), overflow: overflow() };
""", look=look, width=390)
    assert page["title"] == "No usage yet" and page["text"] and page["bars"] == 0 and page["material"] is False and page["check"] is False
    assert page["overflow"]["page"] == 0 and page["overflow"]["cards"] <= 0


def test_the_wait_shows_a_loading_state_and_the_section_then_fills(url, stub, tmp_path):
    stub["delay"] = 2.5
    page = _drive(url, tmp_path, r"""
const out = {};
out.loading = await until(() => $(".an .skeleton") && { busy: !!busy(), sr: text($(".an .skeleton .sr")), main: shown($(".an__main")) }, "the loading state");
await settled();
out.after = { skeleton: !!$(".an .skeleton"), bars: $$(".an-bar").length };
return out;
""")
    assert page["loading"] == {"busy": True, "sr": "Loading Analytics…", "main": False}
    assert page["after"] == {"skeleton": False, "bars": 12}


def test_a_failed_read_is_an_error_state_with_try_again(url, stub, tmp_path):
    stub["fail"] = 99
    script = r"""
const out = {};
await settled();
out.error = { title: text($(".an .error-state__title")), text: text($(".an .error-state__text")), main: shown($(".an__main")) };
return out;
"""
    page = _drive(url, tmp_path, script)
    assert page["error"]["title"] == "Could not read the analytics" and page["error"]["text"] and page["error"]["main"] is False


def test_try_again_reads_once_the_hub_answers(url, stub, tmp_path):
    stub["fail"] = 1                                       # the first read fails, the next finds the Hub up
    page = _drive(url, tmp_path, r"""
await settled();
const out = { first: !!$(".an .error-state") };
$(".an .error-state [data-action=try-again]").click();
await until(() => $(".an__main") && !$(".an__main").hidden, "the section after Try again");
out.bars = $$(".an-bar").length;
return out;
""")
    assert page == {"first": True, "bars": 12}


def test_the_route_answers_as_the_kit_route_and_refuses_a_bad_months(hub, hub_app, stub):  # noqa: F811
    running = _serve(AsHttps(hub_app[0]), hub_app[1])
    try:
        with httpx.Client(base_url=running.url + "/setup/api") as c:
            got = c.get("/analytics")
            assert got.status_code == 200 and got.json()["months"][0]["month"] == month(0) and stub["calls"] == [(12, None)]
            assert c.get("/analytics", params={"months": 3, "printer": "p2"}).json() == ONE and stub["calls"][-1] == (3, "p2")
            assert c.get("/analytics", params={"months": 13}).status_code == 200
            for bad in ("0", "14", "x"):
                assert c.get("/analytics", params={"months": bad}).status_code == 400, bad
            assert len(stub["calls"]) == 3
    finally:
        running.stop()


def test_without_the_kits_analytics_the_route_answers_the_ruled_shape_with_nothing_in_it(monkeypatch, hub, hub_app):  # noqa: F811
    monkeypatch.setattr(analytics_tab, "read", REAL_READ)
    monkeypatch.setattr(analytics_tab, "_analytics", None)
    running = _serve(AsHttps(hub_app[0]), hub_app[1])
    try:
        assert httpx.get(running.url + "/setup/api/analytics").json() == {"months": [], "insights": [], "notes": []}
    finally:
        running.stop()
