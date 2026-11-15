"""The Devices section of the Hub page (design 09 S2.9, 03 section 7): AUT-5 with every card and the pairing dialog, and the
real controls pressed in a headless browser. Helpers and the example-data Hub are those of test_hub_page_audit.py. The same
skip rules: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time

import pytest

from filament_kit import pairing, setup_helper, station_requests, trusted
from filament_kit.web.slots import INTAKE_DEVICE

from test_hub_page_audit import CODE, ROOT, _missing, _node, _run, hub_app, hub_change  # noqa: F401

# ---------------------------------------------------------------- Devices (design 09 S2.9, 03 section 7)
# The Devices section pressed in a real headless browser (tests/page_drive.mjs): the requests the page sends are recorded by
# a wrapper of fetch, and a few replies are changed in the page (a new device appearing, a short expiry, a slow or failing
# answer) so each state of the pairing dialog, the requests asking to pair and the trusted computers is reached.


DRIVER = ROOT / "tests" / "page_drive.mjs"
TEXTS = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))


def _T(key: str, **v) -> str:
    """A catalogue text with its variables filled in (the plural form by `count`, as SW.t)."""
    text = TEXTS[key]
    if isinstance(text, dict):
        text = text["one" if v.get("count") == 1 else "other"]
    for name, value in v.items():
        text = text.replace("{" + name + "}", str(value))
    return text.replace("{product}", TEXTS["app_name"]).replace("{command}", TEXTS["command_name"])


def _page_drive(url: str, tmp_path, script: str, width: int = 1280) -> dict:
    node = _node()
    if not node:
        _missing("the page driver needs Node 22 or later")
    file = tmp_path / "drive.js"
    file.write_text(script.replace("__CODE__", CODE), encoding="utf-8")
    run = subprocess.run([node, str(DRIVER), "--url", url, "--script", str(file), "--width", str(width)],
                         capture_output=True, encoding="utf-8", timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("the page driver needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("page driver: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


DEVICES_PRELUDE = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
async function until(look, what, ms = 15000) {
  for (let t = 0; t < ms; t += 100) { const v = look(); if (v) return v; await sleep(100); }
  throw new Error("waited for " + what + "; the page shows: " + JSON.stringify([$("h1") && text($("h1")), text($(".page-head__meta")),
    $$(".result[data-state], .toast, dialog[open]").map((e) => [e.className, text(e).slice(0, 100)])]));
}
// what the page sends (the path after /setup/api/ and the body), and the replies this test changes
const sent = [];
const tweak = { delay: {}, fail: {}, refuse: {}, newDevice: null, expires: null };
const real = window.fetch;
window.fetch = async (u, o) => {
  const path = String(u).replace(/^.*\\/setup\\/api\\//, "");
  if (o && o.method === "POST") sent.push([path, JSON.parse(o.body || "{}")]);
  if (tweak.delay[path]) await sleep(tweak.delay[path]);
  if (tweak.fail[path] > 0) { tweak.fail[path]--; return new Response(JSON.stringify({ error: "the store is busy" }), { status: 503 }); }
  if (tweak.refuse[path] > 0) { tweak.refuse[path]--; return new Response(JSON.stringify({ error: "this is not the setup code", field: "code" }), { status: 403 }); }
  const r = await real(u, o);
  if (path === "state" && tweak.newDevice) {
    const d = await r.clone().json();
    d.devices.push(tweak.newDevice);
    return new Response(JSON.stringify(d), { status: r.status, headers: r.headers });
  }
  if (path === "pair" && tweak.expires != null) {
    const d = await r.clone().json();
    d.expires_in = tweak.expires;
    return new Response(JSON.stringify(d), { status: r.status, headers: r.headers });
  }
  return r;
};
const sentTo = (p) => sent.filter((s) => s[0] === p).map((s) => s[1]);
location.hash = "#devices";
await until(() => $('[data-action="pair-phone"]') && $(".coll--paired .coll__item"), "the section");
await until(() => !$(".chip--lock .skeleton__line") && !$('[aria-busy="true"]:not(button)'), "the first reads to settle");
const unlock = () => SW.setLock("unlocked", { code: "__CODE__" });
const card = (start) => $$("main .card").find((c) => text($("h2", c)).startsWith(start));
const dlg = () => $("dialog[open]");
const closed = () => !$("dialog");
const out = {};
"""


@pytest.fixture
def devices_hub(hub_change, monkeypatch):
    """The Hub page with trusted computers on and two of them listed. The in-process helper answers one request at a time,
    as the root helper does: the section reads the lists together, and on Windows the lockout file does not take two writers."""
    held, real = threading.Lock(), setup_helper.handle

    def one_at_a_time(req):
        with held:
            return real(req)
    monkeypatch.setattr(setup_helper, "handle", one_at_a_time)
    own = {"id": "d3", "name": INTAKE_DEVICE, "hash": "2" * 64, "paired": 1.0, "last_seen": 1.0, "expires": 0, "claimed": 1.0}
    pairing._write("devices.json", pairing._load_devices() + [own])      # the server's own pairing: built in, no Unpair
    trusted.set_enabled(True)
    trusted.add("Desk PC", "192.0.2.9")
    trusted.add("Shop laptop", "loopback")
    return hub_change


def test_devices_texts_columns_and_states_locked_and_unlocked(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
out.head = [text($("h1")), text($(".page-head__meta")), $$(".page-head__actions .btn").map((b) => b.getAttribute("aria-label") || text(b))];
out.cards = $$("main .card > h2").map(text);
out.paired = $$(".coll--paired .coll__item").map((i) => $$(".coll__row:first-child .coll__cell", i).map(text));
out.pairedHead = $$(".coll--paired .coll__head [role=columnheader]").map(text);
out.unpair = $$(".coll--paired .coll__item").map((i) => [text($(".devices__name", i)), !!$('[data-action="unpair"]', i), text($(".coll__sub", i))]);
out.lockedRequests = text(card("Weigh"));
out.lockedTrust = text(card("Trusted"));
out.readers = $$(".coll--readers .coll__item").map((i) => $$(".coll__row:first-child .coll__cell", i).map(text));
out.web = text(card("The web app"));
out.webAlt = $$(".card img.qr").map((i) => i.alt);
unlock();
await until(() => $(".coll--trusted .coll__item"), "the trusted computers");
await until(() => text(card("Weigh")).includes("No Weigh Station"), "the requests");
out.unlockedHead = text($(".page-head__meta"));
out.trusted = $$(".coll--trusted .coll__item").map((i) => $$(".coll__row:first-child .coll__cell", i).map(text));
out.trustedHead = $$(".coll--trusted .coll__head [role=columnheader]").map(text);
out.requests = text(card("Weigh"));
out.badge = text($(".devices__badge"));
out.revokeAll = text($('[data-action="revoke-all"]'));
return out;
""")
    assert page["head"][0] == _T("nav_devices")
    assert page["head"][1] == f"{_T('devices_meta_paired', count=len(page['paired']))} · {_T('devices_meta_readers', count=2)}"
    assert page["head"][2] == [_T("devices_link_sync"), _T("common_more_actions"), _T("devices_pair_phone")]
    assert [re.sub(r"(On|Off)\Z", "", c).strip() for c in page["cards"]] == [
        _T("devices_paired_title"), _T("devices_requests_title"), _T("devices_webapp_title"), _T("devices_readers_title"), _T("devices_trusted_title")]
    assert page["pairedHead"][:3] == [_T("devices_col_device"), _T("devices_col_paired"), _T("devices_col_last_seen")]
    by_name = {n: (button, line) for n, button, line in page["unpair"]}
    assert by_name["Kitchen phone"] == (True, None) and by_name["Garage tablet"] == (True, None)
    built_in = [v for v in by_name.values() if v[1]]
    assert built_in and all(button is False and line == _T("devices_built_in_line") for button, line in built_in)   # a built-in pairing has no Unpair
    assert _T("devices_requests_locked") in page["lockedRequests"] and _T("common_unlock_to_show") in page["lockedRequests"]
    assert _T("common_list_locked") in page["lockedTrust"]
    assert [r[0] for r in page["readers"]] == ["Tag Reader for Workshop X1", "Tag Reader for Garage Voron"]
    assert _T("devices_webapp_hint") in page["web"] and _T("devices_webapp_keep") in page["web"]
    assert page["webAlt"] == [_T("devices_webapp_home_alt")]
    assert page["unlockedHead"].endswith(_T("devices_meta_trusted", count=2))
    assert [r[0] for r in page["trusted"]] == ["Desk PC", "Shop laptop"]
    assert page["trustedHead"][0] == _T("common_field_name") and page["trustedHead"][3] == _T("devices_trusted_col_expires")
    assert "192.0.2.9" in page["trusted"][0][2] and _T("devices_trusted_hub_itself") in page["trusted"][1][2]
    assert page["requests"].endswith(_T("devices_requests_none"))
    assert page["badge"] == _T("status_on") and page["revokeAll"] == _T("devices_trusted_revoke_all")


def test_pair_a_phone_link_slicer_sync_and_link_a_weigh_station_send_their_kind(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const info = () => ({ title: text($(".dialog__title", dlg())), say: text($(".pairing > p")), code: text($(".pairing__digits")), print: text($(".pairing__print")),
  blocks: $$(".pairing .code__caption", dlg()).map(text), copies: $$('.pairing [data-action="copy"]', dlg()).length,
  qr: $$(".pairing img.qr", dlg()).map((i) => [i.alt, i.complete && i.naturalWidth > 0, Math.round(i.getBoundingClientRect().width)]),
  bar: !!$('.pairing [role="progressbar"]', dlg()), expiry: text($(".pairing .progress + p")), waiting: text($(".pairing__wait")),
  foot: $$(".dialog__foot .btn", dlg()).map(text), hash: location.hash });
// Pair a phone, then Cancel: the code simply expires, nothing else is sent
$('[data-action="pair-phone"]').click();
await until(dlg, "the dialog for a phone");
await until(() => $$(".pairing img.qr", dlg()).every((i) => i.complete), "the QR image to load");
out.phone = info();
out.focusInside = dlg().contains(document.activeElement);
$('.dialog__foot [data-action="cancel"]').click();
await until(closed, "Cancel to close it");
out.hashAfter = location.hash;
out.focusBack = document.activeElement.dataset.action;
// Link Slicer Sync, closed by the close button
$('[data-action="link-sync"]').click();
await until(dlg, "the dialog for Slicer Sync");
out.sync = info();
$('.dialog__head [data-action="cancel"]').click();
await until(closed, "the close button");
// the overflow menu: Link a Weigh Station (the Weigh Station feature is off here: no item for the one on this Hub)
$('[data-action="pair-more"]').click();
await until(() => $(".menu__item"), "the overflow menu");
out.menu = $$(".menu__item").map(text);
$('[data-action="link-station"]').click();
await until(dlg, "the dialog for a Weigh Station");
out.station = info();
out.stationCommand = text($(".pairing pre.code__text", dlg()));
$('.dialog__foot [data-action="cancel"]').click();
await until(closed, "Cancel to close it");
out.focusBackStation = document.activeElement.dataset.action;
out.sent = sentTo("pair");
return out;
""")
    assert page["sent"] == [{"kind": "phone", "code": CODE}, {"kind": "pc", "code": CODE}, {"kind": "station", "code": CODE}]
    phone, sync, station = page["phone"], page["sync"], page["station"]
    assert phone["title"] == _T("devices_pair_phone") and phone["say"] == _T("devices_pair_instruction_phone")
    assert phone["hash"] == "#devices/pair" and page["hashAfter"] == "#devices" and page["focusInside"] is True
    assert re.fullmatch(r"\d{3} \d{3}", phone["code"]) and re.fullmatch(r"([0-9A-Fa-f]{4} ){3,}[0-9A-Fa-f]{4}", phone["print"]), phone
    assert phone["qr"] == [[_T("qr_alt_pair"), True, 224]] and phone["blocks"] == [] and phone["bar"] is True
    assert phone["expiry"] == _T("qr_expires", minutes=10) and phone["waiting"] == _T("devices_pair_waiting")
    assert phone["foot"] == [_T("common_cancel")] and page["focusBack"] == "pair-phone"
    assert sync["title"] == _T("devices_link_sync") and sync["say"] == _T("devices_pair_instruction_sync")
    assert sync["blocks"] == [_T("devices_pair_link")] and sync["copies"] == 1 and sync["qr"] == []
    assert page["menu"] == [_T("devices_link_station")]
    assert station["title"] == _T("devices_link_station") and station["say"] == _T("devices_pair_instruction_station").replace("`", "")
    assert station["blocks"] == [_T("devices_pair_command"), _T("devices_pair_link")] and station["copies"] == 2
    assert page["stationCommand"] == f"sudo {TEXTS['command_name']} weigh-station pair" and page["focusBackStation"] == "pair-more"


def test_the_pairing_dialog_says_paired_when_the_device_appears_and_expired_when_it_does_not(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const resultOf = () => text($(".dialog__result .result__text", dlg()));
// the device appears while the dialog is open: Paired, the bar and the code go, Done closes, the list has the device
$('[data-action="pair-phone"]').click();
await until(dlg, "the dialog");
out.before = $$(".coll--paired .coll__item").length;
tweak.newDevice = { id: "dNew", name: "Pixel phone", paired: "2026-11-13 09:00", last_seen: null, built_in: false };
await until(() => resultOf(), "the Paired result", 20000);
out.paired = { result: resultOf(), code: !!$(".pairing__digits", dlg()) || !!$('[role="progressbar"]', dlg()), foot: $$(".dialog__foot .btn", dlg()).map(text),
  focus: document.activeElement.dataset.action, rows: $$(".coll--paired .coll__item").length };
$('.dialog__foot [data-action="done"]').click();
await until(closed, "Done to close it");
out.list = $$(".coll--paired .coll__item").map((i) => text($(".devices__name", i)));
tweak.newDevice = null;
// the code runs out: Expired, with Make a new code, which asks again and shows the new code
tweak.expires = 2;
$('[data-action="link-sync"]').click();
await until(dlg, "the dialog for Slicer Sync");
await until(() => resultOf(), "the Expired result", 20000);
out.expired = { result: resultOf(), kind: $(".dialog__result", dlg()).dataset.state, code: !!$(".pairing__digits", dlg()) || !!$("pre.code__text", dlg()),
  foot: $$(".dialog__foot .btn", dlg()).map(text), focus: document.activeElement.dataset.action };
tweak.expires = null;
const before = sentTo("pair").length;
$('[data-action="new-code"]').click();
await until(() => $(".pairing__digits", dlg()), "the new code", 20000);
out.renewed = { sent: sentTo("pair").slice(before), result: resultOf(), foot: $$(".dialog__foot .btn", dlg()).map(text), expiry: text($(".pairing .progress + p", dlg())) };
$('.dialog__foot [data-action="cancel"]').click();
await until(closed, "Cancel");
return out;
""")
    assert page["paired"]["result"] == _T("qr_paired", name="Pixel phone") and page["paired"]["code"] is False
    assert page["paired"]["foot"] == [_T("devices_pair_done_button")] and page["paired"]["focus"] == "done"
    assert page["paired"]["rows"] == page["before"] + 1 and "Pixel phone" in page["list"]
    assert page["expired"]["result"] == _T("qr_expired") and page["expired"]["kind"] == "warn" and page["expired"]["code"] is False
    assert page["expired"]["foot"] == [_T("common_cancel"), _T("qr_new_code")] and page["expired"]["focus"] == "new-code"
    assert page["renewed"]["sent"] == [{"kind": "pc", "code": CODE}] and page["renewed"]["result"] is None
    assert page["renewed"]["foot"] == [_T("common_cancel")] and page["renewed"]["expiry"] == _T("qr_expires", minutes=10)


def test_a_pairing_asked_for_while_the_section_redraws_still_opens_one_dialog(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
tweak.delay.pair = 1500;
const button = $('[data-action="pair-phone"]');
button.focus();
button.click();
button.click();                     // pressed again while the first is out: nothing more is sent
await sleep(300);
await refresh();                    // the section is read and drawn again under the request
await until(dlg, "the dialog");
out.dialogs = $$("dialog[open]").length;
out.sent = sentTo("pair");
$('.dialog__foot [data-action="cancel"]').click();
await until(closed, "Cancel");
out.focus = document.activeElement.dataset.action;
out.buttons = $$('.page-head__actions [data-action="pair-phone"]').length;
return out;
""")
    assert page["dialogs"] == 1 and page["sent"] == [{"kind": "phone", "code": CODE}]
    assert page["focus"] == "pair-phone" and page["buttons"] == 1


def test_unpair_sends_the_revoke_and_its_result_survives_the_redraw(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const row = () => $$(".coll--paired .coll__item").find((i) => text($(".devices__name", i)) === "Kitchen phone");
out.label = $('[data-action="unpair"]', row()).getAttribute("aria-label");
$('[data-action="unpair"]', row()).click();
await until(dlg, "the Unpair dialog");
out.dialog = [text($(".dialog__title", dlg())), text($(".dialog__text", dlg())), $$(".dialog__foot .btn", dlg()).map(text)];
tweak.delay["devices/d1/revoke"] = 800;
$('.dialog__foot [data-action="confirm"]').click();
await sleep(200);
await refresh();                    // a redraw while the change is under way
await until(() => !row(), "the device to go");
out.toast = await until(() => text($(".toast")), "the result");
out.sent = sentTo("devices/d1/revoke");
out.count = text($(".page-head__meta"));
return out;
""")
    assert page["label"] == _T("devices_unpair_named", name="Kitchen phone")
    assert page["dialog"] == [_T("devices_unpair_title", name="Kitchen phone"), _T("devices_unpair_body"), [_T("common_cancel"), _T("devices_unpair")]]
    assert page["toast"] == _T("devices_unpaired", name="Kitchen phone") and page["sent"] == [{"code": CODE}]


def test_weigh_stations_asking_to_pair_refresh_by_themselves_and_send_their_answers(devices_hub, tmp_path, monkeypatch):
    asking = [{"id": "q1", "name": "Bench station", "address": "192.0.2.77", "code": "123456"}]
    answered = []
    started = time.monotonic()
    later = {"id": "q2", "name": "Shelf station", "address": "192.0.2.78", "code": "654321"}

    def decide(rid, approve):
        answered.append((rid, approve))
        asking[:] = [q for q in asking if q["id"] != rid]
        return {}
    # the second request arrives a few seconds after the page opened, with nothing pressed: the 5 s refresh shows it
    monkeypatch.setattr(station_requests, "pending", lambda: [dict(q) for q in asking] + ([later] if time.monotonic() - started > 4 and "q2" not in {a[0] for a in answered} else []))
    monkeypatch.setattr(station_requests, "decide", decide)
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const items = () => $$(".item", card("Weigh"));
await until(() => items().length >= 1, "the first request");
out.first = { line: text($("p", items()[0])), digits: text($(".devices__digits", items()[0])), hint: text($$("p", items()[0])[1]),
  buttons: $$(".btn", items()[0]).map((b) => b.getAttribute("aria-label")) };
const typed = items()[0].querySelector('[data-action="pair"]');
typed.focus();
await until(() => items().length === 2, "the second request to appear by itself", 20000);
out.second = items().map((i) => text($(".devices__digits", i)));
out.focusKept = document.activeElement.dataset.action;
items()[1].querySelector('[data-action="refuse"]').click();
out.refused = await until(() => text($(".toast")), "the Refused result");
await until(() => items().length === 1, "the refused request to go");
$('[data-action="pair"]', items()[0]).click();
out.paired = await until(() => $$(".toast").map(text).find((t) => t.startsWith("Paired")), "the Paired result");
await until(() => text(card("Weigh")).includes("No Weigh Station"), "the empty line");
out.sent = sent.filter((s) => s[0].startsWith("stations/requests/")).map((s) => [s[0], s[1].code]);
return out;
""")
    first = page["first"]
    assert first["digits"] == "123 456" and first["line"] == _T("devices_request_line", name="Bench station", address="192.0.2.77", code="123 456")
    assert first["hint"] == _T("devices_request_hint")
    assert first["buttons"] == [_T("devices_request_pair_named", name="Bench station"), _T("devices_request_refuse_named", name="Bench station")]
    assert page["second"] == ["123 456", "654 321"] and page["focusKept"] == "pair"
    assert page["refused"] == _T("devices_request_refused", name="Shelf station")
    assert page["paired"] == _T("devices_request_paired", name="Bench station")
    assert page["sent"] == [["stations/requests/q2/refuse", CODE], ["stations/requests/q1/pair", CODE]]
    assert answered == [("q2", False), ("q1", True)]


def test_tag_reader_tokens_are_made_shown_once_and_revoked(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const readers = () => card("Tag Readers");
out.empty = text(readers()).includes("Tag Reader for Workshop X1");
const name = $('input[name="name"]', readers());
out.field = [text($("label", name.closest(".field"))), name.placeholder];
name.value = "Bench reader";
$('[data-action="make-token"]').focus();
$('[data-action="make-token"]').click();      // pressed as a person does: the focus is on the button
await until(() => $(".result[data-state=ok] pre.code__text", readers()), "the new token");
const box = $(".result[data-state=ok]", readers());
out.made = { line: text($("p", box)), caption: text($(".code__caption", box)), token: text($("pre.code__text", box)).length > 20, copy: !!$('[data-action="copy"]', box),
  warn: text($(".banner", box)), field: $('input[name="name"]', readers()).value, rows: $$(".coll--readers .coll__item", readers()).length };
out.sentMake = sentTo("readers");
// the token goes with the section: leaving it clears the result
location.hash = "#overview";
await until(() => !$(".result[data-state=ok] pre.code__text"), "the token to be cleared");
location.hash = "#devices";
await until(() => $(".coll--readers"), "the section again");
out.afterLeave = !!$(".result[data-state=ok] pre.code__text");
const row = $$(".coll--readers .coll__item").find((i) => text(i).includes("Bench reader"));
const id = row.dataset.key;
$('[data-action="revoke-token"]', row).click();
await until(dlg, "the revoke dialog");
out.dialog = [text($(".dialog__title", dlg())), text($(".dialog__text", dlg())), $$(".dialog__foot .btn", dlg()).map(text)];
$('.dialog__foot [data-action="confirm"]').click();
out.toast = await until(() => text($(".toast")), "the revoked result");
out.id = id;
out.sentRevoke = sentTo(`readers/${id}/revoke`);
out.rowsAfter = $$(".coll--readers .coll__item").length;
return out;
""")
    assert page["field"] == [_T("common_field_name"), _T("devices_readers_name_placeholder")]
    assert page["made"]["line"].startswith("New Tag Reader token") and "Bench reader" in page["made"]["line"]
    assert page["made"]["caption"] == _T("devices_readers_token") and page["made"]["token"] and page["made"]["copy"] is True
    assert page["made"]["warn"].replace("`", "") == _T("devices_readers_once").replace("`", "") and page["made"]["field"] == ""
    assert page["made"]["rows"] == 3 and page["sentMake"] == [{"name": "Bench reader", "code": CODE}] and page["afterLeave"] is False
    assert page["dialog"] == [_T("devices_revoke_token_title", id=page["id"]), _T("devices_revoke_token_body"), [_T("common_cancel"), _T("devices_revoke_token_confirm")]]
    assert page["toast"] == _T("devices_token_revoked", id=page["id"]) and page["sentRevoke"] == [{"code": CODE}] and page["rowsAfter"] == 2


def test_trusted_computers_toggle_rename_revoke_and_revoke_all(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const trust = () => card("Trusted");
const rows = () => $$(".coll--trusted .coll__item", trust());
await until(() => rows().length === 2, "the list");
const desk = () => rows().find((i) => text($(".devices__name", i)) === "Desk PC");
// Rename: a text entry dialog, filled and selected
$('[data-action="rename"]', desk()).click();
await until(dlg, "the Rename dialog");
out.rename = { title: text($(".dialog__title", dlg())), value: $("input", dlg()).value, label: text($("label", dlg())), foot: $$(".dialog__foot .btn", dlg()).map(text) };
$("input", dlg()).value = "Office PC";
$('.dialog__foot [data-action="confirm"]').click();
await until(() => rows().some((i) => text($(".devices__name", i)) === "Office PC"), "the new name");
out.sentRename = sent.filter((s) => s[0].endsWith("/rename")).map((s) => s[1]);
// Revoke one
const office = () => rows().find((i) => text($(".devices__name", i)) === "Office PC");
$('[data-action="revoke"]', office()).click();
await until(dlg, "the Revoke dialog");
out.revoke = [text($(".dialog__title", dlg())), text($(".dialog__text", dlg())), $$(".dialog__foot .btn", dlg()).map(text)];
$('.dialog__foot [data-action="confirm"]').click();
out.revoked = await until(() => text($(".toast")), "the revoked result");
await until(() => rows().length === 1, "the row to go");
out.count = text($(".page-head__meta"));
// Revoke all
$('[data-action="revoke-all"]').click();
await until(dlg, "the Revoke all dialog");
out.all = [text($(".dialog__title", dlg())), text($(".dialog__text", dlg())), $$(".dialog__foot .btn", dlg()).map(text)];
$('.dialog__foot [data-action="confirm"]').click();
await until(() => text(trust()).includes("No computer is trusted"), "the empty list");
out.afterAll = { revokeAll: !!$('[data-action="revoke-all"]'), count: text($(".page-head__meta")) };
out.sentRevokes = sent.filter((s) => s[0].startsWith("trust/") && s[0] !== "trust/list").map((s) => s[0].replace(/trust\\/[0-9a-f]+\\//, "trust/ID/"));
// the switch: turning it off asks first and sends enabled false; its result stays, the list goes, the badge says Off
const sw = $('.toggle__input', trust());
sw.click();
await until(dlg, "the Turn off dialog");
out.off = [text($(".dialog__title", dlg())), text($(".dialog__text", dlg())), $$(".dialog__foot .btn", dlg()).map(text)];
$('.dialog__foot [data-action="confirm"]').click();
await until(() => $(".devices__badge", trust()) && text($(".devices__badge")) === "Off", "the Off badge");
await until(() => text($(".toggle .result__text", trust())), "the result of the switch");
out.offState = { result: text($(".toggle .result__text", trust())), line: text(trust()).includes("Trusted computers are off: every change needs the setup code."),
  list: !!$(".coll--trusted", trust()), checked: $(".toggle__input", trust()).checked, meta: text($(".page-head__meta")) };
// turning it on asks nothing
$('.toggle__input', trust()).click();
await until(() => text($(".devices__badge")) === "On", "the On badge");
await until(() => text(trust()).includes("No computer is trusted") && text($(".toggle .result__text", trust())) === "Trusted computers are on.", "the empty list and the result");
out.onState = { result: text($(".toggle .result__text", trust())), dialog: !!dlg() };
out.sentSwitch = sentTo("trust/enabled");
return out;
""")
    assert page["rename"] == {"title": _T("devices_rename_title", name="Desk PC"), "value": "Desk PC", "label": _T("common_field_name"),
                              "foot": [_T("common_cancel"), _T("common_rename")]}
    assert page["sentRename"] == [{"name": "Office PC", "code": CODE}]
    assert page["revoke"] == [_T("devices_revoke_one_title", name="Office PC"), _T("devices_revoke_one_body"), [_T("common_cancel"), _T("devices_revoke_one_confirm")]]
    assert page["revoked"] == _T("devices_trusted_revoked", name="Office PC") and page["count"].endswith(_T("devices_meta_trusted", count=1))
    assert page["all"] == [_T("devices_revoke_all_title"), _T("devices_revoke_all_body"), [_T("common_cancel"), _T("devices_trusted_revoke_all")]]
    assert page["afterAll"] == {"revokeAll": False, "count": page["afterAll"]["count"]} and page["afterAll"]["count"].endswith(_T("devices_meta_trusted", count=0))
    assert page["sentRevokes"] == ["trust/ID/rename", "trust/ID/revoke", "trust/revoke_all"]
    assert page["off"] == [_T("devices_off_title"), _T("devices_off_body"), [_T("common_cancel"), _T("common_turn_off")]]
    assert page["offState"]["result"] == _T("devices_trusted_off_done") and page["offState"]["line"] and page["offState"]["list"] is False
    assert page["offState"]["checked"] is False and _T("devices_meta_trusted", count=0) not in page["offState"]["meta"]
    assert page["onState"] == {"result": _T("devices_trusted_on_done"), "dialog": False}
    assert page["sentSwitch"] == [{"enabled": False, "code": CODE}, {"enabled": True, "code": CODE}]


def test_the_web_app_card_says_what_failed_and_tries_again(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
tweak.fail.webapp = 1;
render();                           // the section is drawn again: its first read of the address fails
const web = () => card("The web app");
await until(() => $(".error-state", web()), "the error");
out.error = [text($(".error-state__title", web())), text($(".error-state__text", web())), text($('[data-action="try-again"]', web()))];
$('[data-action="try-again"]', web()).click();
await until(() => $("img.qr", web()), "the address after Try again");
out.after = { error: !!$(".error-state", web()), url: text($(".code__text", web())), alt: $("img.qr", web()).alt };
return out;
""")
    assert page["error"] == [_T("devices_webapp_error", reason="").strip(), "The store is busy.", _T("common_try_again")]
    assert page["after"]["error"] is False and page["after"]["url"].endswith("/intake") and page["after"]["alt"] == _T("devices_webapp_home_alt")


def test_on_a_phone_the_pairing_dialog_is_a_sheet_and_the_tables_are_cards(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
await until(() => $(".coll--trusted .coll__item"), "the list");
out.cards = $$(".coll--paired .coll__item").map((i) => getComputedStyle(i).display);
out.keys = $$(".coll--paired .coll__item")[0].querySelectorAll(".coll__key").length;
$('[data-action="pair-phone"]').click();
await until(dlg, "the dialog");
await sleep(500);
const r = dlg().getBoundingClientRect();
out.sheet = { width: Math.round(r.width), bottom: Math.round(window.innerHeight - r.bottom), qr: Math.round($(".pairing img.qr").getBoundingClientRect().width), scroll: document.documentElement.scrollWidth };
out.qrCentred = Math.abs(($(".pairing img.qr").getBoundingClientRect().left + $(".pairing img.qr").getBoundingClientRect().width / 2) - window.innerWidth / 2) < 3;
return out;
""", width=320)
    assert set(page["cards"]) == {"block"} and page["keys"] >= 2
    assert page["sheet"]["width"] == 320 and page["sheet"]["bottom"] == 0 and page["sheet"]["qr"] <= 224 and page["sheet"]["scroll"] <= 320
    assert page["qrCentred"] is True


# the audit with the cards Unlocked and the pairing dialog open (each section's own states are in the tests above)
DEVICES_READY = """(async () => {
  const until = async (what, f, ms = 15000) => { for (let t = 0; t < ms && !f(); t += 100) await new Promise((r) => setTimeout(r, 100)); if (!f()) throw new Error("Devices: " + what); };
  await until("the first reads", () => !document.querySelector(".chip--lock .skeleton__line") && !document.querySelector('[aria-busy="true"]:not(button)'));
  SW.setLock("unlocked", { code: %r });
  await until("the trusted computers", () => document.querySelector(".coll--trusted .coll__item"));
  await until("the requests", () => /No Weigh Station/.test(document.body.innerText));
  %s
})()"""


def _devices_ready(extra: str = "") -> str:
    return DEVICES_READY % (CODE, extra)


def test_devices_pass_the_audit_unlocked_with_every_card(devices_hub):
    run = _run("--url", devices_hub, "--views", "#devices", "--ready", _devices_ready())
    assert run.returncode == 0, run.stdout + run.stderr      # no allow-list: nothing of Devices is allowed any more
    assert json.loads(run.stdout)["views"] == 4


@pytest.mark.parametrize("opener", ['document.querySelector(\'[data-action="pair-phone"]\').click();', 'document.querySelector(\'[data-action="link-sync"]\').click();',
                                    'document.querySelector(\'[data-action="pair-more"]\').click(); await until("menu", () => document.querySelector(".menu__item")); '
                                    'document.querySelector(\'[data-action="link-station"]\').click();'])
def test_devices_pass_the_audit_with_the_pairing_dialog_open(devices_hub, opener):
    run = _run("--url", devices_hub, "--views", "#devices", "--ready", _devices_ready(opener + 'await until("the dialog", () => document.querySelector("dialog[open] .pairing__digits"));'))
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)["views"] == 4


def test_devices_unlocked_with_the_dialog_open_do_not_scroll_sideways_at_320_px_in_a_wide_font(monkeypatch, devices_hub):
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")      # a CI runner's name: the web app address gets long
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else ["--wide-font"]
    opener = 'document.querySelector(\'[data-action="pair-more"]\').click(); await until("menu", () => document.querySelector(".menu__item")); ' \
             'document.querySelector(\'[data-action="link-station"]\').click(); await until("the dialog", () => document.querySelector("dialog[open] .pairing__digits"));'
    run = _run("--url", devices_hub, "--views", "#devices", "--widths", "320", "--ready", _devices_ready(opener), *fonts)
    assert run.returncode in (0, 1), run.stdout + run.stderr
    found = [(r["view"], r["scheme"], f["detail"]) for r in json.loads(run.stdout).get("report", []) for f in r["findings"] if f["check"] == "sideways scroll"]
    assert not found, found


def test_a_reader_token_is_made_once_per_press_even_when_pressed_twice_or_enter_is_held(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
tweak.delay.readers = 700;
const readers = () => card("Tag Readers");
const before = $$(".coll--readers .coll__item", readers()).length;
const name = $('input[name="name"]', readers());
name.value = "Twice";
const make = $('[data-action="make-token"]', readers());
make.focus();
make.click();
await sleep(100);
make.click();                                   // a second press 100 ms later
for (let i = 0; i < 3; i++) name.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", repeat: true, bubbles: true, cancelable: true }));   // Enter held
await until(() => $(".result[data-state=ok] pre.code__text", readers()), "the new token");
await sleep(900);
out.sent = sentTo("readers");
out.rows = $$(".coll--readers .coll__item", readers()).length - before;
// the press after the request has come back makes the next token
tweak.delay.readers = 0;
$('input[name="name"]', readers()).value = "Again";
$('[data-action="make-token"]', readers()).focus();
$('[data-action="make-token"]', readers()).click();
await until(() => sentTo("readers").length === 2, "the next press");
out.sentAfter = sentTo("readers");
return out;
""")
    assert page["sent"] == [{"name": "Twice", "code": CODE}] and page["rows"] == 1
    assert [s["name"] for s in page["sentAfter"]] == ["Twice", "Again"]


def test_pair_pressed_twice_on_a_weigh_station_request_sends_one_answer(devices_hub, tmp_path, monkeypatch):
    asking = [{"id": "q1", "name": "Bench station", "address": "192.0.2.77", "code": "123456"}]
    answered = []

    def decide(rid, approve):
        answered.append((rid, approve))
        asking[:] = [q for q in asking if q["id"] != rid]
        return {}
    monkeypatch.setattr(station_requests, "pending", lambda: [dict(q) for q in asking])
    monkeypatch.setattr(station_requests, "decide", decide)
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const items = () => $$(".item", card("Weigh"));
await until(() => items().length === 1, "the request");
tweak.delay["stations/requests/q1/pair"] = 800;
const pair = $('[data-action="pair"]', items()[0]);
pair.focus();
pair.click();
await sleep(150);
pair.click();                                   // pressed again while the answer is out
await until(() => $$(".toast").map(text).some((t) => t.startsWith("Paired")), "the Paired result");
await sleep(600);
out.sent = sent.filter((s) => s[0].startsWith("stations/requests/") && s[0] !== "stations/requests").map((s) => s[0]);
return out;
""")
    assert page["sent"] == ["stations/requests/q1/pair"] and answered == [("q1", True)]


def test_a_lock_closes_the_pairing_dialog_and_clears_a_new_reader_token(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
const readers = () => card("Tag Readers");
$('input[name="name"]', readers()).value = "Shown once";
$('[data-action="make-token"]', readers()).focus();
$('[data-action="make-token"]', readers()).click();
await until(() => $(".result[data-state=ok] pre.code__text", readers()), "the new token");
$('[data-action="pair-phone"]').click();
await until(dlg, "the dialog");
out.dialogCode = !!$(".pairing__digits", dlg());
SW.setLock("locked");                           // Lock now
await until(closed, "the dialog to close");
await sleep(300);
out.after = { dialogs: $$("dialog").length, digits: $$(".pairing__digits").length, token: $$("pre.code__text", readers()).length, result: $$(".result[data-state]", readers()).length,
  focus: document.activeElement.dataset.action, hash: location.hash };
return out;
""")
    assert page["dialogCode"] is True
    assert page["after"] == {"dialogs": 0, "digits": 0, "token": 0, "result": 0, "focus": "pair-phone", "hash": "#devices"}


def test_try_again_on_the_requests_card_locks_the_page_when_the_code_is_refused(devices_hub, tmp_path):
    page = _page_drive(devices_hub, tmp_path, DEVICES_PRELUDE + """
unlock();
await until(() => text(card("Weigh")).includes("No Weigh Station"), "the requests");
tweak.fail["stations/requests"] = 1;
render();                                       // drawn again: its first read fails
await until(() => $('[data-action="try-again"]', card("Weigh")), "the error and Try again");
tweak.refuse["stations/requests"] = 1;          // the Hub now refuses the code
$('[data-action="try-again"]', card("Weigh")).click();
await until(() => SW.lock.state === "locked", "the page to lock");
await sleep(300);
out.state = SW.lock.state;
out.locked = text(card("Weigh")).includes(LOCKED_TEXT);
return out;
""".replace("LOCKED_TEXT", json.dumps(_T("devices_requests_locked"))))
    assert page["state"] == "locked" and page["locked"] is True
