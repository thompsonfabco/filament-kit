"""The storage locations' one Checks row (group Hub, needs a look): the same row in `spoolwarden status`, in
`status --json` and in the Hub's Overview answer (`GET /setup/api/overview`), only while the list could not be saved or
read, and gone after a good save. One function makes it (`status.storage_rows` from `storage.checks_row`)."""
from __future__ import annotations

import json

import pytest
from test_console_core import app, helper, owned  # noqa: F401
from test_setup_page import client, env  # noqa: F401

from filament_kit import cli, config, redact, status, storage
from filament_kit.storage import ANY, CONTAINERS, MATERIALS, Location, Storage

SAVE = "Storage locations could not be saved"
READ = "Storage locations could not be read"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    from filament_kit import setup_console
    monkeypatch.setattr(setup_console.Cached, "get", lambda self, stamp, fn: fn())      # no 5 s memory in a test
    monkeypatch.setattr(storage, "_logged", set())
    monkeypatch.setattr(storage, "_save_failed", None)
    monkeypatch.setattr(storage, "_cache", None)


def listing() -> Storage:
    return Storage([Location("Sealed stock", sealed=True),
                    Location("Rack 1", limit=20, fill=MATERIALS, materials=["PLA"]),
                    Location("Storage box", CONTAINERS, count=3, prefix="Storage box ", fill=ANY),
                    Location("Overflow", overflow=True, default_overflow=True)])


def overview_rows(app) -> list[dict]:
    r = client(app).get("/setup/api/overview")
    assert r.status_code == 200
    return [x for x in r.json()["rows"] if x["text"].startswith("Storage locations")]


def redacted(row: dict) -> dict:
    """What the Overview's GET (no setup code) shows of a row: the same redaction it applies. It hides addresses, serials
    and a user folder in a path ("/home/user/.cache" becomes "/home/user/<hidden>"), so a state folder under such a path
    reads differently there; `status` and the whole POST answer show the path as it is."""
    known = redact.known_values()
    return {**row, "text": redact.text(row["text"], known), "fix": redact.text(row["fix"], known)}


def status_json(capsys) -> dict:
    cli.main(["status", "--json"])
    return json.loads(capsys.readouterr().out)


def break_the_write(monkeypatch):
    def refuse(*a, **k):
        raise OSError(30, "Read-only file system")
    monkeypatch.setattr(storage, "_write", refuse)


def test_a_healthy_list_adds_no_row(app, owned, capsys):
    storage.migrate_at_start()
    assert overview_rows(app) == []
    assert not [r for r in status_json(capsys)["rows"] if r["text"].startswith("Storage locations")]


def test_a_failed_save_shows_the_row_in_the_overview_and_in_status_and_recovers_after_a_good_save(
        app, owned, capsys, monkeypatch):
    real = storage._write
    (config.paths().state / "storage.xml").unlink()             # the Hub started once already (the app); start again
    break_the_write(monkeypatch)
    storage.migrate_at_start()                                  # the state folder cannot be written: the Hub starts
    want = {"state": "fail", "text": f"{SAVE} (Read-only file system).", "action": "", "group": "Hub"}
    rows = overview_rows(app)
    assert len(rows) == 1 and {k: rows[0][k] for k in want} == want
    assert rows[0]["fix"].startswith("Check that the Hub's user can write ") and rows[0]["fix"].endswith(
        ", then restart the Hub.")
    doc = status_json(capsys)
    mine = [r for r in doc["rows"] if r["text"].startswith("Storage locations")]
    assert [redacted(r) for r in mine] == rows and doc["summary"]["needs_a_look"] >= 1
    assert str(config.paths().state) in mine[0]["fix"]          # status shows the folder as it is
    cli.main(["status"])
    out = capsys.readouterr().out
    assert f"{SAVE} (Read-only file system)." in out and "needs a look" in out and "Fix: Check that the Hub's user" in out
    monkeypatch.setattr(storage, "_write", real)                # the next save works: the row goes
    storage.save(listing())
    assert overview_rows(app) == []
    assert not [r for r in status_json(capsys)["rows"] if r["text"].startswith("Storage locations")]


@pytest.mark.parametrize("text", ["<storage", "", '<storage version="2"/>'])
def test_an_unreadable_file_shows_the_row_everywhere_and_a_save_clears_it(app, owned, capsys, text):
    state = config.paths().state
    state.mkdir(parents=True, exist_ok=True)
    (state / "storage.xml").write_text(text, encoding="utf-8")
    rows = overview_rows(app)
    assert len(rows) == 1 and rows[0]["text"].startswith(READ + " (") and rows[0]["state"] == "fail"
    assert rows[0]["group"] == "Hub" and rows[0]["fix"].startswith("Restore ")
    mine = [r for r in status_json(capsys)["rows"] if r["text"].startswith("Storage locations")]
    assert len(mine) == 1 and mine[0]["text"].startswith(READ + " (")
    assert redacted(mine[0]) == rows[0]                         # the GET is the redacted form of the status row
    assert str(state / "storage.xml") in mine[0]["fix"]         # status shows the file's path as it is
    storage.save(listing())                                     # keeps the old file as storage.xml.unreadable
    assert overview_rows(app) == [] and (state / "storage.xml.unreadable").exists()


def test_a_process_that_does_not_know_the_reason_says_the_file_is_missing_while_the_hub_runs(owned):
    assert storage.checks_row() is None                         # no file, nobody failed: nothing to say before a start
    row = storage.checks_row(hub_running=True)
    assert row["text"].startswith(SAVE + " (storage.xml is not in ") and row["state"] == "Needs a look"
    assert list(status.storage_rows(True))[0].state == "fail" and list(status.storage_rows(False)) == []
