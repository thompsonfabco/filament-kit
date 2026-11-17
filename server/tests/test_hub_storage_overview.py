"""The Hub page's Overview shows the storage Checks row like any other failing check (group Hub, state fail, with its fix), and a
refused save in Settings > Storage locations shows the Hub's refusal text and leaves the list unsaved, in a real headless
browser. The Overview answer is the Hub's own with the row added by the page's fetch (the row is the server's, test_storage.py).
Same skip rules as the page audit."""
from __future__ import annotations

import pytest

from filament_kit import storage
from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_hub_settings import PRELUDE
from test_hub_storage_locations import _drive_storage, stock  # noqa: F401

LOOKS = ["console", "workbench", "palette", "panes"]
FIX = "Check that the Hub's user can write /var/lib/filament-kit, then save again."
TEXTS_OF_THE_ROW = [storage.SAVE_FAILED.format(reason="No space left on device"), storage.READ_FAILED.format(reason="Permission denied")]


def _overview(look: str, text: str) -> str:
    return PRELUDE + f"""
document.documentElement.setAttribute("data-look", "{look}");
location.hash = "#overview";
const realFetch = window.fetch;
window.fetch = async (url, init) => {{
  const r = await realFetch(url, init);
  if (!String(url).includes("/setup/api/overview")) return r;
  const data = await r.json();
  data.rows = [...data.rows, {{ state: "fail", group: "Hub", text: {text!r}, fix: {FIX!r}, action: null }}];
  return new Response(JSON.stringify(data), {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
}};
await until(() => $(".overview__checks .coll--checks") && !$('main [aria-busy="true"]:not(button)'), "the checks");
$(".page-head__actions .btn--ghost").click();
const item = await until(() => [...document.querySelectorAll(".coll--checks .coll__item:not(.coll__group)")].find((i) => i.textContent.includes("Storage locations could not")), "the storage row");
const cell = (c) => item.querySelector(`[data-col="${{c}}"]`);
return {{ state: item.dataset.state, status: text(cell("status")), title: text(cell("title")), fix: text(cell("fix")),
  shown: shown(item), group: text([...document.querySelectorAll(".coll--checks .coll__group")].find((g) => text(g) === "Hub")),
  badge: text($(".overview__head .status--warn")) }};
"""


@pytest.mark.parametrize("look", LOOKS)
@pytest.mark.parametrize("text", TEXTS_OF_THE_ROW)
def test_the_storage_row_is_a_failing_check_with_its_fix_in_every_look(hub, tmp_path, look, text):
    page = _drive(hub, tmp_path, _overview(look, text), width=1280)
    assert page["state"] == "fail" and page["shown"] and page["group"] == "Hub"
    assert page["title"] == text and page["fix"].endswith(FIX) and "Needs a look" in page["status"] and page["badge"]


def test_a_save_the_hub_cannot_write_says_so_in_the_result_and_the_list_stays_unsaved(hub, tmp_path, monkeypatch):
    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(storage, "_write", full)
    page = _drive_storage(hub, tmp_path, r"""
SW.setLock("unlocked", { code: "__CODE__" });
await sleep(800);
$('[aria-label^="Move Rack 1 "]:not([aria-disabled="true"])').click();
await until(() => $("#set-storage").dataset.state === "dirty", "the dirty state");
out.before = names();
$("#set-storage [type=submit]").click();
await until(() => text($("#set-storage .group__foot .result__text")), "the refusal");
await sleep(200);
out.result = text($("#set-storage .group__foot .result__text"));
out.state = $("#set-storage").dataset.state;
out.after = names();
""")
    # the Hub's own refusal, its Error and Fix lines, as the Hub words them (storage._not_saved)
    assert page["result"].startswith("Error: " + storage.NOT_SAVED.format(reason="No space left on device") + " Fix: Check that the Hub's user can write ")
    assert page["state"] == "dirty" and page["after"] == page["before"]
    assert [s.name for s in storage.load().locations] == ["Sealed stock", "Rack 1", "Rack 2", "Storage box (containers)", "Overflow", "Dry shelf"]
