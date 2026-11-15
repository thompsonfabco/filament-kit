"""The local reader's capabilities (health) and its 1.1 correction-queue client, against the fake reader service."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from fakes import local_reader_fake as lrf

from filament_kit import config, local_reader

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
PRED = {"vendor": "SUNLU", "name": "PLA+ Grey"}
CORR = {"vendor": "Polymaker", "name": "PolyLite PLA Grey"}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setattr(local_reader, "CONNECT_TIMEOUT", 0.5)


def cfg_of(url: str) -> dict:
    return {"local_intake": {"url": url}}


def caps_of(url: str) -> dict:
    return local_reader.health(cfg_of(url), timeout=2)["capabilities"]


def code_of(fn, *args, **kw) -> tuple[str, str]:
    with pytest.raises(local_reader.LocalReaderError) as e:
        fn(*args, **kw)
    return e.value.code, str(e.value)


# ---------- capabilities ----------

def test_capabilities_from_a_section_14_health(fake_reader):
    url, data = fake_reader
    data["queue"].append({"id": "x"})
    lrf.feedback_health(data)
    h = local_reader.health(cfg_of(url), timeout=2)
    assert h["ok"]
    assert h["capabilities"] == {"feedback": True, "opt_in": True, "endpoint_configured": True, "count": 1,
                                 "source_record": True, "accelerator": "cpu (fake)", "known_from": "health"}


def test_capabilities_say_feedback_false_and_hide_the_rest(fake_reader):
    url, data = fake_reader
    data["health"] = {**data["health"], "api_version": "1.1", "capabilities": {"feedback": False,
                                                                                "accelerator": "cuda:0"}}
    assert caps_of(url) == {"feedback": False, "opt_in": None, "endpoint_configured": None, "count": None,
                            "source_record": False, "accelerator": "cuda:0", "known_from": "health"}


def test_capabilities_without_source_and_record(fake_reader):
    url, data = fake_reader
    data["source_record"] = False
    lrf.feedback_health(data)
    assert caps_of(url)["source_record"] is False


def test_fallback_api_1_1_without_capabilities_means_the_queue_exists(fake_reader):
    url, data = fake_reader
    lrf.feedback_health(data, with_capabilities=False)
    assert caps_of(url) == {"feedback": True, "opt_in": None, "endpoint_configured": None, "count": None,
                            "source_record": False, "accelerator": None, "known_from": "api_version"}
    data["health"]["api_version"] = "1.2"
    assert caps_of(url)["feedback"] is True


def test_fallback_older_readers_have_none(fake_reader):
    url, data = fake_reader
    for v in ("1.0", 1, "1", None):
        data["health"]["api_version"] = v
        c = caps_of(url)
        assert c["feedback"] is False and c["known_from"] == "none", v


def test_the_accelerator_shows_even_without_capabilities(fake_reader):
    url, data = fake_reader
    data["health"]["accelerator"] = {"name": "CPU (AVX2)"}
    assert caps_of(url)["accelerator"] == "CPU (AVX2)"


@pytest.mark.parametrize("odd", ["yes", 7, [], {"feedback": "maybe"}, {"feedback": {"count": "many", "opt_in": 1}},
                                 {"feedback": {"enabled": False}}, {"accelerator": [1, 2]}])
def test_odd_capabilities_never_fail_the_status(fake_reader, odd):
    url, data = fake_reader
    data["health"] = {**data["health"], "api_version": "1.1", "capabilities": odd}
    h = local_reader.health(cfg_of(url), timeout=2)
    assert h["ok"] and h["error"] is None
    assert set(h["capabilities"]) == set(local_reader.capabilities(None))


def test_an_unreachable_reader_has_none():
    h = local_reader.health(cfg_of("http://127.0.0.1:9"), timeout=1)
    assert not h["ok"] and h["capabilities"]["feedback"] is False


@pytest.fixture
def dead_url():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    yield f"http://127.0.0.1:{s.getsockname()[1]}"
    s.close()


# ---------- the client ----------

@pytest.fixture
def rd(fake_reader):
    url, data = fake_reader
    lrf.feedback_health(data)
    return cfg_of(url), data


def test_list_of_an_empty_and_a_filled_queue(rd):
    cfg, data = rd
    assert local_reader.feedback_list(cfg) == {"opt_in": True, "endpoint_configured": True, "count": 0,
                                               "bundle_mb": 0.0, "entries": []}
    local_reader.feedback_add(cfg, [JPEG, JPEG], PRED, CORR, "grey not black")
    out = local_reader.feedback_list(cfg)
    assert out["count"] == 1 and out["bundle_mb"] > 0
    e = out["entries"][0]
    assert e["id"] == "fb-1" and e["predicted"] == PRED and e["corrected"] == CORR and e["note"] == "grey not black"
    assert e["photos"] == 2


def test_add_sends_the_photos_and_values_as_the_contract_says(rd):
    cfg, data = rd
    out = local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    assert out["ok"] and out["id"] == "fb-1"
    body = data["bodies"][-1]
    assert body["predicted"] == PRED and body["corrected"] == CORR and body["note"] == ""
    assert len(body["images_b64"]) == 1 and body["api_version"] == "1.0"
    assert "source" not in body and "record" not in body      # not asked for, not sent


def test_add_sends_source_and_record_only_when_the_reader_advertises_them(rd):
    cfg, data = rd
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR, source="cloud", record="rec-7")   # asks the health itself
    assert data["bodies"][-1]["source"] == "cloud" and data["bodies"][-1]["record"] == "rec-7"
    # a spool revised twice replaces its entry
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR, source="local", record="rec-7")
    assert local_reader.feedback_list(cfg)["count"] == 1
    data["source_record"] = False
    lrf.feedback_health(data)
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR, source="cloud", record="rec-8")
    assert "source" not in data["bodies"][-1] and "record" not in data["bodies"][-1]
    # an older reader without capabilities: neither
    lrf.feedback_health(data, with_capabilities=False)
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR, source="cloud", record="rec-9")
    assert "source" not in data["bodies"][-1]


def test_add_with_given_caps_makes_no_health_call(rd):
    cfg, data = rd
    data["health_status"] = 500                       # a health call would find the reader "not answering well"
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR, source="local", record="r", caps={"source_record": True})
    assert data["bodies"][-1]["record"] == "r"


def test_delete(rd):
    cfg, data = rd
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    out = local_reader.feedback_delete(cfg, "fb-1")
    assert out["ok"] and out["queued_count"] == 0 and data["queue"] == []
    assert code_of(local_reader.feedback_delete, cfg, "fb-1")[0] == "not_found"
    assert code_of(local_reader.feedback_delete, cfg, " ")[0] == "not_found"
    assert code_of(local_reader.feedback_delete, cfg, "../read")[0] == "not_found"


def test_bundle_is_the_readers_zip(rd):
    cfg, data = rd
    assert code_of(local_reader.feedback_bundle, cfg)[0] == "empty"
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    z = zipfile.ZipFile(io.BytesIO(local_reader.feedback_bundle(cfg)))
    assert sorted(z.namelist()) == ["fb-1_0.jpg", "pending_feedback.xml"]


def test_bundle_over_the_cap_is_refused(rd):
    cfg, data = rd
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    code, text = code_of(local_reader.feedback_bundle, cfg, cap=50)
    assert code == "too_large" and "not fetched" in text


def test_submit_clears_the_queue_and_sends_no_address(rd):
    cfg, data = rd
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    out = local_reader.feedback_submit(cfg)
    assert out["ok"] and out["sent"] == 1 and data["queue"] == []
    assert data["submits"] == [{"api_version": "1.0"}]


def test_submit_errors(rd):
    cfg, data = rd
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    data["submit"] = (502, "feedback_upload_failed")
    code, text = code_of(local_reader.feedback_submit, cfg)
    assert code == "upload_failed" and "still waiting" in text and len(data["queue"]) == 1
    data["opt_in"] = False
    assert code_of(local_reader.feedback_submit, cfg)[0] == "feedback_disabled"


def test_submit_has_the_long_timeout(rd, monkeypatch):
    cfg, data = rd
    seen = []
    real = local_reader._request
    monkeypatch.setattr(local_reader, "_request", lambda *a, **k: seen.append(k["timeout"]) or real(*a, **k))
    local_reader.feedback_list(cfg)
    with pytest.raises(local_reader.LocalReaderError):
        local_reader.feedback_submit(cfg)             # nothing queued: the fake says 400, the timeout was set
    assert seen == [local_reader.FEEDBACK_TIMEOUT, local_reader.SUBMIT_TIMEOUT] and local_reader.SUBMIT_TIMEOUT >= 300


def test_error_mapping(rd):
    cfg, data = rd
    data["opt_in"] = False
    code, text = code_of(local_reader.feedback_add, cfg, [JPEG], PRED, CORR)
    assert code == "feedback_disabled" and "switched off" in text
    data["opt_in"] = True
    data["max_add_bytes"] = 10
    assert code_of(local_reader.feedback_add, cfg, [JPEG], PRED, CORR)[0] == "too_large"
    data["errors"].append((409, "duplicate", None))
    code, text = code_of(local_reader.feedback_add, cfg, [JPEG], PRED, CORR)
    assert code == "conflict" and "already has" in text
    data["errors"].append((413, "", None))
    assert code_of(local_reader.feedback_add, cfg, [JPEG], PRED, CORR)[0] == "too_large"
    data["errors"].append((403, "", None))
    assert code_of(local_reader.feedback_list, cfg)[0] == "feedback_disabled"
    data["errors"].append((500, "feedback_failed", None))
    assert code_of(local_reader.feedback_list, cfg)[0] == "bad_answer"
    data["errors"].append((404, "not_found", None))
    assert code_of(local_reader.feedback_list, cfg)[0] == "not_found"


def test_the_token_goes_along_and_a_wrong_one_is_unauthorized(rd, tmp_path):
    cfg, data = rd
    data["token"] = "s3cret"
    assert code_of(local_reader.feedback_list, cfg)[0] == "unauthorized"
    local_reader.write_token("s3cret")
    assert local_reader.feedback_list(cfg)["count"] == 0
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    local_reader.feedback_bundle(cfg)
    local_reader.feedback_delete(cfg, "fb-1")
    assert data["feedback_auth"][-4:] == ["Bearer s3cret"] * 4
    assert config.paths().etc.joinpath("local_intake_token").exists()


def test_a_reader_that_is_down_is_unreachable(dead_url):
    cfg = cfg_of(dead_url)
    for fn, args in ((local_reader.feedback_list, ()), (local_reader.feedback_submit, ()),
                     (local_reader.feedback_bundle, ()), (local_reader.feedback_delete, ("fb-1",))):
        assert code_of(fn, cfg, *args)[0] == "unreachable"


def test_an_old_reader_without_the_routes(fake_reader):
    url, data = fake_reader                          # the 1.0 fake has the routes too: ask for an unknown id
    assert code_of(local_reader.feedback_delete, cfg_of(url), "nope")[0] == "not_found"


def test_the_kit_never_sends_an_address(rd):
    """Plan section 8: no endpoint, feedback_endpoint or URL in anything the Hub sends to the reader."""
    cfg, data = rd
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR, "note", source="local", record="r1")
    local_reader.feedback_list(cfg)
    local_reader.feedback_bundle(cfg)
    local_reader.feedback_submit(cfg)
    local_reader.feedback_add(cfg, [JPEG], PRED, CORR)
    local_reader.feedback_delete(cfg, "fb-2")
    sent = [b for b in data["bodies"] if b is not None]
    assert sent
    for body in sent:
        assert not set(map(str.lower, body)) & set(local_reader.FORBIDDEN_FIELDS)
        assert "http" not in json.dumps({k: v for k, v in body.items() if k != "images_b64"}).lower()
    with pytest.raises(ValueError):
        local_reader._check_body({"images_b64": [], "endpoint": "https://x.example/"})
    with pytest.raises(ValueError):
        local_reader._check_body({"Feedback_Endpoint": "x"})


# ---------- review R362 LOWs ----------

@pytest.mark.parametrize("url", ["http://127.0.0.1:99999", "http://127.0.0.1:abc"])
def test_a_bad_port_is_an_answer_not_an_exception(url):
    h = local_reader.health(cfg_of(url), timeout=1)
    assert h["ok"] is False and "port" in h["error"]
    assert "port" in local_reader.check_url(url)
    with pytest.raises(local_reader.LocalReaderError):
        local_reader.feedback_list(cfg_of(url))


def test_a_1_1_reader_whose_capabilities_name_no_feedback_still_has_the_queue(fake_reader):
    url, data = fake_reader
    data["health"] = {**data["health"], "api_version": "1.1", "capabilities": {"accelerator": "cpu"}}
    assert caps_of(url)["feedback"] is True


def test_the_address_guard_looks_inside_the_body():
    with pytest.raises(ValueError):
        local_reader._check_body({"corrected": {"endpoint": "x"}})
