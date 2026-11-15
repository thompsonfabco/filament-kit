"""The corrections waiting to be shared (V1.4): the Hub's pass-through to the reader's queue on the setup page, the phone
app's API and the phone web app, and the job that asks the reader to send, against the fake reader (1.1)."""
from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest
from fakes import local_reader_fake as lrf
from starlette.testclient import TestClient
from test_setup_page import BASE, CODE, H, HOSTNAME, Helper, client, env, make, post  # noqa: F401  (env is a fixture)

from filament_kit import api, cli, config, intake_history, local_reader, modules, output, pairing, reader_corrections
from filament_kit import setup_helper, share_queue
from filament_kit.spoolman import Spoolman

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
B = "/setup/api/label-reader/corrections"


@pytest.fixture
def hub(env, fake_reader, monkeypatch):  # noqa: F811
    """The setup page with the local reader on and pointing at the fake; (client, fake data, helper)."""
    url, data = fake_reader
    cfg = config.load()
    cfg["modules"]["local_intake"] = True
    cfg["local_intake"] = {"url": url}
    config.save(cfg)
    monkeypatch.setattr(local_reader, "CONNECT_TIMEOUT", 0.5)
    lrf.feedback_health(data)
    helper = Helper()
    started = []
    monkeypatch.setattr(setup_helper, "_start_job", lambda name, why="", checked=False: started.append(name))
    app = make(env, helper)
    return client(app), data, started


def add(data, record, brand="Polymaker"):
    """One waiting correction, as the reader would hold it."""
    n = data["next_id"]
    data["next_id"] += 1
    data["queue"].append({"id": f"fb-{n}", "created_at": "2026-11-15T12:00:00Z", "predicted": {"vendor": "Polymakr"},
                          "corrected": {"vendor": brand}, "note": "", "photos": 1, "jpegs": [JPEG],
                          "thumbnail_b64": base64.b64encode(JPEG[:16]).decode(), "record": record})
    return f"fb-{n}"


# ---------- the list ----------

def test_the_list_passes_the_entries_through_with_count_size_opt_in_and_capabilities(hub):
    c, data, _ = hub
    a, b = add(data, "r1"), add(data, "r2")
    r = c.get(B)
    assert r.status_code == 200
    out = r.json()
    assert [e["id"] for e in out["entries"]] == [a, b]
    assert out["entries"][0]["corrected"] == {"vendor": "Polymaker"} and out["entries"][0]["record"] == "r1"
    assert out["count"] == 2 and out["opt_in"] is True and out["bytes"] == round(out["bundle_mb"] * 1048576)
    assert out["capabilities"]["feedback"] is True and out["capabilities"]["known_from"] == "health"


def test_the_list_works_without_the_code_and_while_locked(hub):
    c, data, _ = hub
    add(data, "r1")
    assert c.get(B).status_code == 200 and c.get(B + "/package").status_code == 200


def test_an_empty_list(hub):
    c, _, _ = hub
    out = c.get(B).json()
    assert out["count"] == 0 and out["entries"] == [] and out["bytes"] == 0


def test_the_list_says_when_the_reader_is_off_missing_old_or_silent(hub, env, fake_reader):  # noqa: F811
    c, data, _ = hub
    cfg = config.load()
    # old reader: API 1.0, no queue
    data["health"] = {**data["health"], "api_version": "1.0"}
    data["health"].pop("capabilities", None)
    r = c.get(B)
    assert r.status_code == 409 and r.json()["reason"] == "no_feedback" and "too old" in r.json()["error"]
    # the module is off
    cfg["modules"]["local_intake"] = False
    config.save(cfg)
    r = c.get(B)
    assert r.status_code == 409 and r.json()["reason"] == "no_reader"
    # nothing answers at the address
    cfg["modules"]["local_intake"] = True
    cfg["local_intake"] = {"url": "http://127.0.0.1:9"}
    config.save(cfg)
    r = c.get(B)
    assert r.status_code == 503 and r.json()["reason"] == "unreachable" and "They are kept" in r.json()["error"]


def test_a_reader_that_wants_a_token_is_refused_in_the_hubs_words(hub):
    c, data, _ = hub
    data["token"] = "secret-token-1"
    data["health"] = {**data["health"], "auth_required": False}
    r = c.get(B)
    assert r.status_code == 502 and r.json()["reason"] == "unauthorized" and "secret-token-1" not in r.text


# ---------- remove ----------

def test_remove_takes_one_out_and_needs_the_code(hub):
    c, data, _ = hub
    a, b = add(data, "r1"), add(data, "r2")
    r = post(c, f"label-reader/corrections/{a}/remove", {}, code=None)
    assert r.status_code == 403 and len(data["queue"]) == 2
    r = post(c, f"label-reader/corrections/{a}/remove", {}, code="00000000")
    assert r.status_code == 403 and len(data["queue"]) == 2
    r = post(c, f"label-reader/corrections/{a}/remove")
    assert r.status_code == 200 and r.json() == {"ok": True, "removed": a}
    assert [e["id"] for e in data["queue"]] == [b]


def test_remove_of_one_that_is_gone_is_not_found(hub):
    c, _, _ = hub
    r = post(c, "label-reader/corrections/fb-99/remove")
    assert r.status_code == 404 and r.json()["reason"] == "not_found"


def test_remove_all_takes_every_one_out_and_needs_the_code(hub):
    c, data, _ = hub
    for i in range(3):
        add(data, f"r{i}")
    assert post(c, "label-reader/corrections/remove-all", {}, code=None).status_code == 403
    assert len(data["queue"]) == 3
    r = post(c, "label-reader/corrections/remove-all")
    assert r.status_code == 200 and r.json() == {"ok": True, "removed": 3} and data["queue"] == []


def test_remove_all_that_fails_part_way_says_how_many_went(hub):
    c, data, _ = hub
    for i in range(3):
        add(data, f"r{i}")
    real = local_reader.feedback_delete
    calls = []

    def flaky(cfg, eid):
        calls.append(eid)
        if len(calls) == 2:
            raise local_reader.LocalReaderError("unreachable", "gone")
        return real(cfg, eid)
    local_reader.feedback_delete = flaky
    try:
        r = post(c, "label-reader/corrections/remove-all")
    finally:
        local_reader.feedback_delete = real
    assert r.status_code == 503 and r.json()["removed"] == 1 and len(data["queue"]) == 2


# ---------- the package ----------

def test_the_package_is_the_readers_exact_zip_as_an_attachment(hub):
    c, data, _ = hub
    a = add(data, "r1")
    r = c.get(B + "/package")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith('attachment; filename="spoolwarden-corrections-')
    assert r.headers["content-disposition"].endswith('.zip"')
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert f"{a}_0.jpg" in z.namelist() and z.read(f"{a}_0.jpg") == JPEG
    assert r.content == local_reader.feedback_bundle(config.load())          # byte for byte what the reader gives


def test_the_package_of_nothing_is_refused_and_a_big_one_is_too_large(hub, monkeypatch):
    c, data, _ = hub
    r = c.get(B + "/package")
    assert r.status_code == 409 and r.json()["reason"] == "empty"
    add(data, "r1")
    monkeypatch.setattr(local_reader, "BUNDLE_CAP", 10)
    monkeypatch.setattr(local_reader.feedback_bundle, "__defaults__", (10,))
    r = c.get(B + "/package")
    assert r.status_code == 413 and r.json()["reason"] == "too_large" and "too big" in r.json()["error"]


# ---------- send (the job) ----------

def test_send_starts_the_job_and_needs_the_code(hub):
    c, data, started = hub
    add(data, "r1"), add(data, "r2")
    r = post(c, "label-reader/corrections/send", {}, code=None)
    assert r.status_code == 403 and started == []
    r = post(c, "label-reader/corrections/send", {}, code="00000000")
    assert r.status_code == 403 and started == []
    r = post(c, "label-reader/corrections/send")
    assert r.status_code == 200 and r.json() == {"ok": True, "name": "corrections_send", "count": 2}
    assert started == ["corrections_send"] and len(data["queue"]) == 2          # the route sends nothing itself
    assert data["submits"] == []


def test_send_of_nothing_starts_no_job(hub):
    c, _, started = hub
    r = post(c, "label-reader/corrections/send")
    assert r.status_code == 409 and r.json()["reason"] == "empty" and started == []


def test_send_with_the_reader_absent_or_old_starts_no_job(hub):
    c, data, started = hub
    cfg = config.load()
    cfg["modules"]["local_intake"] = False
    config.save(cfg)
    assert post(c, "label-reader/corrections/send").json()["reason"] == "no_reader"
    assert started == []


def test_the_job_is_on_the_closed_list_with_its_command_and_busy_text():
    assert setup_helper.JOBS["corrections_send"] == ("label-reader", "corrections", "send")
    assert "corrections_send" in setup_helper.BUSY


def test_the_job_command_sends_through_the_reader_with_steps_and_a_result(hub, capsys):
    _, data, _ = hub
    add(data, "r1"), add(data, "r2")
    assert cli.cmd_local_intake_corrections_send() == 0
    out = capsys.readouterr().out
    assert "==> step 1 of 2 " in out and "==> step 2 of 2 Sending 2 corrections." in out
    assert "Sent 2 corrections. Thank you." in out
    assert data["queue"] == []


def test_the_job_command_keeps_the_corrections_when_the_upload_fails(hub, capsys):
    _, data, _ = hub
    add(data, "r1")
    data["submit"] = (502, "feedback_upload_failed")
    assert cli.cmd_local_intake_corrections_send() == output.FAILED
    err = capsys.readouterr().err
    assert "still waiting" in err and err.startswith("Error: ")
    assert len(data["queue"]) == 1


def test_the_job_command_with_nothing_waiting_or_no_reader(hub, capsys):
    _, data, _ = hub
    assert cli.cmd_local_intake_corrections_send() == output.FAILED
    assert "No corrections are waiting." in capsys.readouterr().err
    cfg = config.load()
    cfg["modules"]["local_intake"] = False
    config.save(cfg)
    assert cli.cmd_local_intake_corrections_send() == output.FAILED
    assert "not on" in capsys.readouterr().err


def test_the_command_is_wired_in_the_parser(hub, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_local_intake_corrections_send", lambda: seen.append(1) or 0)
    assert cli.main(["label-reader", "corrections", "send"]) == 0 and seen == [1]


def test_reader_corrections_send_asks_the_reader_with_only_the_api_version(hub):
    _, data, _ = hub
    add(data, "r1")
    out = reader_corrections.send(config.load())
    assert out == {"ok": True, "sent": 1}
    assert data["submits"] == [{"api_version": "1.0"}]


# ---------- no address anywhere ----------

def test_nothing_the_hub_sends_to_the_reader_carries_an_address(hub, monkeypatch):
    c, data, _ = hub
    add(data, "r1"), add(data, "r2")
    c.get(B)
    c.get(B + "/package")
    post(c, "label-reader/corrections/fb-1/remove")
    post(c, "label-reader/corrections/remove-all")
    add(data, "r3")
    reader_corrections.send(config.load())
    seen = json.dumps([b for b in data["bodies"] if b is not None]).lower()
    for word in ("endpoint", "http://", "https://", "address", "url"):
        assert word not in seen
    assert FORBIDDEN_OK


FORBIDDEN_OK = all(w in local_reader.FORBIDDEN_FIELDS for w in ("endpoint", "feedback_endpoint", "url", "address"))


# ---------- the phone app's API and the phone web app ----------

@pytest.fixture
def phone(hub, env):  # noqa: F811
    c, data, _ = hub
    pairing.make_cert("fkhost", [], config.paths().etc)
    app = api.create_app(Spoolman("http://127.0.0.1:9"), printers=object(), camera_hub=object(), mapper=object(),
                         enabled_modules=modules.enabled(config.load()) - {"printers", "klipper"},
                         setup={"helper": Helper(), "hosts": lambda: {HOSTNAME}})
    pc = TestClient(app, base_url=BASE, client=("192.0.2.20", 50000))
    pc.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue("Pixel").code)
    return pc, data


def test_the_apps_api_lists_and_removes_and_needs_a_paired_phone(phone):
    pc, data = phone
    a = add(data, "r1")
    out = pc.get("/api/label-reader/corrections").json()
    assert out["count"] == 1 and out["entries"][0]["id"] == a
    unpaired = TestClient(pc.app, base_url=BASE, client=("192.0.2.20", 50000))
    assert unpaired.get("/api/label-reader/corrections").status_code == 401
    assert unpaired.post(f"/api/label-reader/corrections/{a}/remove").status_code == 401
    assert len(data["queue"]) == 1
    r = pc.post(f"/api/label-reader/corrections/{a}/remove")
    assert r.status_code == 200 and r.json()["removed"] == a and data["queue"] == []
    r = pc.post(f"/api/label-reader/corrections/{a}/remove")
    assert r.status_code == 404 and r.json()["error"] == "not_found" and "message" in r.json()


def test_the_apps_api_has_no_send_package_or_remove_all(phone):
    pc, data = phone
    add(data, "r1")
    for method, path in (("POST", "send"), ("GET", "package"), ("POST", "remove-all")):
        assert pc.request(method, f"/api/label-reader/corrections/{path}").status_code in (404, 405)
    assert len(data["queue"]) == 1 and data["submits"] == []


def test_the_apps_api_says_when_the_reader_is_off(phone):
    pc, _ = phone
    cfg = config.load()
    cfg["modules"]["local_intake"] = False
    config.save(cfg)
    r = pc.get("/api/label-reader/corrections")
    assert r.status_code == 409 and r.json()["error"] == "no_reader"


def _web(public_url=None):
    from starlette.applications import Starlette
    from filament_kit.web.intake_app import IntakeApp

    class Tools:
        sm = None

        def cfg(self):
            return config.load()
    app = IntakeApp(Tools(), public_url=public_url, lan_cidrs=["192.0.2.0/24"], push=False, host_ok=lambda r: True)
    return TestClient(Starlette(routes=app.routes()), base_url=BASE, client=("192.0.2.20", 50000))


def test_the_web_app_lists_and_removes_on_the_kits_own_page(hub):
    _, data, _ = hub
    wc = _web()
    a = add(data, "r1")
    assert wc.get("/intake/api/label-reader/corrections").json()["entries"][0]["id"] == a
    for method, path in (("POST", "send"), ("GET", "package"), ("POST", "remove-all")):
        assert wc.request(method, f"/intake/api/label-reader/corrections/{path}", headers=H).status_code in (404, 405)
    r = wc.post(f"/intake/api/label-reader/corrections/{a}/remove", json={}, headers=H)
    assert r.status_code == 200 and data["queue"] == []
    r = wc.post(f"/intake/api/label-reader/corrections/{a}/remove", json={}, headers=H)
    assert r.status_code == 404 and r.json()["reason"] == "not_found"


def test_the_web_app_says_when_the_reader_is_off_and_the_public_page_has_no_routes(hub):
    _, data, _ = hub
    cfg = config.load()
    cfg["modules"]["local_intake"] = False
    config.save(cfg)
    r = _web().get("/intake/api/label-reader/corrections")
    assert r.status_code == 409 and r.json()["reason"] == "no_reader"
    assert _web("https://example.test/f").get("/intake/api/label-reader/corrections").status_code in (404, 405)


# ---------- review R365: the command line, the lock, a missing count, a conflict ----------

def test_the_list_and_package_work_while_the_page_is_locked_out_and_writes_do_not(hub):
    from filament_kit import setup_code
    c, data, _ = hub
    add(data, "r1")
    for _ in range(setup_code.LOCK_MAX):
        assert post(c, "label-reader/corrections/fb-1/remove", {}, code="00000000").status_code == 403
    assert post(c, "label-reader/corrections/fb-1/remove").status_code == 429       # even the right code now
    assert post(c, "label-reader/corrections/send").status_code == 429
    assert c.get(B).status_code == 200 and c.get(B + "/package").status_code == 200
    assert len(data["queue"]) == 1


def test_a_missing_count_falls_back_to_the_entries(hub):
    c, data, started = hub
    add(data, "r1"), add(data, "r2")
    real = local_reader._request

    def no_count(url, **kw):
        out = real(url, **kw)
        if isinstance(out, dict):
            out.pop("count", None)
        return out
    local_reader._request = no_count
    try:
        assert c.get(B).json()["count"] == 2
        assert post(c, "label-reader/corrections/send").status_code == 200 and started == ["corrections_send"]
    finally:
        local_reader._request = real


def test_a_conflict_is_the_hubs_own_refusal(hub):
    c, data, _ = hub
    add(data, "r1")
    data["errors"].append((409, "conflict", None))
    data["errors"].append((409, "conflict", None))          # the health check does not use the queue: both go to list
    r = c.get(B)
    assert r.status_code == 409 and r.json()["reason"] == "conflict" and "already has" in r.json()["error"]


def test_cli_list_remove_package(hub, capsys, tmp_path):
    _, data, _ = hub
    assert cli.main(["label-reader", "corrections", "list"]) == 0
    assert "No corrections waiting." in capsys.readouterr().out
    a, b = add(data, "r1"), add(data, "r2")
    assert cli.main(["label-reader", "corrections"]) == 0
    out = capsys.readouterr().out
    assert "Corrections waiting: 2" in out and a in out and b in out and "Polymaker" in out
    assert cli.main(["label-reader", "corrections", "package", str(tmp_path)]) == 0
    saved = next(tmp_path.glob("spoolwarden-corrections-*.zip"))
    assert saved.read_bytes() == local_reader.feedback_bundle(config.load())
    capsys.readouterr()
    assert cli.main(["label-reader", "corrections", "remove", a, "fb-99"]) == output.FAILED
    cap = capsys.readouterr()
    assert f"Removed {a}. Nothing was sent." in cap.out and "fb-99: That correction is not waiting" in cap.err
    assert [e["id"] for e in data["queue"]] == [b] and data["submits"] == []


def test_cli_refusals_are_the_routes_texts(hub, capsys, tmp_path):
    _, data, _ = hub
    assert cli.main(["label-reader", "corrections", "package", str(tmp_path / "x.zip")]) == output.FAILED
    err = capsys.readouterr().err
    assert err.startswith("Error: ") and reader_corrections.EMPTY in " ".join(err.split())
    cfg = config.load()
    cfg["modules"]["local_intake"] = False
    config.save(cfg)
    for args in (["list"], ["remove", "fb-1"], ["package", str(tmp_path)], ["send"]):
        assert cli.main(["label-reader", "corrections", *args]) == output.FAILED
        assert reader_corrections.NO_READER in " ".join(capsys.readouterr().err.split())


def test_cli_corrections_need_root_exit_3_with_the_sudo_fix(hub, capsys, monkeypatch):
    _, data, _ = hub
    add(data, "r1")
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    for args in (["list"], ["remove", "fb-1"], ["package", "x.zip"], ["send"]):
        assert cli.main(["label-reader", "corrections", *args]) == output.NEEDS_SUDO == 3
        err = capsys.readouterr().err
        assert "Error: this needs administrator rights." in err and "sudo filament-kit label-reader corrections" in err
    assert len(data["queue"]) == 1 and data["submits"] == []


def test_the_global_json_switch_gives_each_commands_document(hub, capsys, tmp_path):
    _, data, _ = hub
    a = add(data, "r1")
    assert cli.main(["--json", "label-reader", "corrections", "list"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True and doc["count"] == 1 and doc["entries"][0]["id"] == a and doc["not_queued"] == []
    assert cli.main(["--json", "label-reader", "corrections", "package", str(tmp_path)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True and doc["bytes"] > 0 and doc["file"].endswith(".zip")
    assert cli.main(["--json", "label-reader", "corrections", "remove", a, "fb-99"]) == output.FAILED
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False and doc["removed"] == [a] and doc["failed"][0]["reason"] == "not_found"
    assert cli.main(["--json", "label-reader", "corrections", "send"]) == output.FAILED
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False and doc["reason"] == "empty" and "error" in doc
    add(data, "r2")
    assert cli.main(["--json", "label-reader", "corrections", "send"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "sent": 1}


# ---------- V1.3: the not-queued records and Try again ----------

def a_record(failed: str | None = None) -> str:
    rid = "r1" if failed else "r2"
    intake_history.stash_read(rid, [JPEG], {"items": [{"vendor": "SUNLU", "name": "PLA+ Grey"}]}, "", None)
    hid = intake_history.record_save([{"values": {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA"},
                                       "spool_ids": [7], "filament_id": 3}], source="phone", read_id=rid)
    if failed:
        share_queue._write(hid, {"entries": {}, "failed": {"reason": failed, "at": "2026-11-15T12:00:00+00:00"}})
    return hid


def test_the_list_shows_the_records_the_reader_did_not_take_and_does_not_count_them(hub):
    c, data, _ = hub
    rid = a_record("the Label Reader did not answer: down")
    add(data, "x")
    out = c.get(B).json()
    assert out["count"] == 1 and [e["id"] for e in out["entries"]] == ["fb-1"]
    assert out["not_queued"] == [{"record": rid, "at": out["not_queued"][0]["at"], "name": "SUNLU PLA+ Grey",
                                  "reason": "the Label Reader did not answer: down"}]
    a_record()                                                      # a record that is fine is not listed
    assert len(c.get(B).json()["not_queued"]) == 1


def test_try_again_needs_the_code_and_answers_the_records_new_state(hub):
    c, data, _ = hub
    rid = a_record("the Label Reader did not answer: down")
    assert post(c, f"label-reader/corrections/{rid}/retry", {}, code=None).status_code == 403
    assert c.get(B).json()["not_queued"][0]["record"] == rid
    r = post(c, f"label-reader/corrections/{rid}/retry")
    assert r.status_code == 200 and r.json() == share_queue.state(rid) and "reason" in r.json()
    assert data["submits"] == []


def test_try_again_of_a_record_that_is_gone_is_not_found(hub):
    c, _, _ = hub
    r = post(c, "label-reader/corrections/0123456789ab/retry")
    assert r.status_code == 404 and r.json()["reason"] == "not_found"


def test_the_apps_api_has_no_try_again(phone):
    pc, _ = phone
    assert pc.post("/api/label-reader/corrections/abc/retry").status_code in (404, 405)


def test_cli_retry_queues_again_with_the_conventions(hub, capsys, monkeypatch):
    _, data, _ = hub
    rid = a_record("the Label Reader did not answer: down")
    assert cli.main(["--json", "label-reader", "corrections", "retry", rid, "0123456789ab"]) == output.FAILED
    cap = capsys.readouterr()
    doc = json.loads(cap.out)
    assert doc["ok"] is False and doc["retried"] == [{"record": rid, "state": "none", "reason": None}]
    assert doc["failed"][0]["record"] == "0123456789ab" and doc["failed"][0]["reason"] == "not_found"
    assert "0123456789ab: That record is no longer kept." in cap.err
    rid2 = a_record("again down")
    assert cli.main(["label-reader", "corrections", "retry", rid2]) == 0
    assert f"{rid2}: nothing to share for this record." in capsys.readouterr().out
    assert data["submits"] == []


def test_cli_retry_that_fails_again_exits_1(hub, capsys, monkeypatch):
    _, _, _ = hub
    rid = a_record("down")
    monkeypatch.setattr(share_queue, "retry", lambda r: {"state": "not_queued", "reason": "still down", "entries": 0})
    assert cli.main(["--json", "label-reader", "corrections", "retry", rid]) == output.FAILED
    cap = capsys.readouterr()
    assert json.loads(cap.out)["retried"][0] == {"record": rid, "state": "not_queued", "reason": "still down"}
    assert "the reader did not take this correction. still down" in cap.err


def test_cli_retry_needs_root(hub, capsys, monkeypatch):
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    assert cli.main(["label-reader", "corrections", "retry", "abc"]) == output.NEEDS_SUDO
    assert "sudo filament-kit label-reader corrections retry abc" in capsys.readouterr().err
