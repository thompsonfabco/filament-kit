"""The local label reader (local_intake module): the module entry, the reader order, the shared post-processing,
the daily cap only for cloud reads, and the HTTP client, against the fake reader service (never real models)."""
from __future__ import annotations

import base64
import socket

import anthropic
import pytest
from fakes import local_reader_fake as lrf
from fakes.claude_fake import FakeClaude
from starlette.testclient import TestClient

from filament_kit import config, intake, local_reader, modules, pairing
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
CLOUD = {"questions": [], "items": [{**lrf.ITEM, "vendor": "Polymaker", "name": "PolyLite PLA Grey",
                                     "color_hex": "808080"}]}
BOTH = {"spoolman": True, "server": True, "ai_intake": True, "local_intake": True}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    (tmp_path / "etc" / "anthropic_key").write_text("sk-test\n")
    monkeypatch.setattr(local_reader, "CONNECT_TIMEOUT", 0.5)   # a dead address is known fast


@pytest.fixture
def dead_url():
    """An address where nothing listens: a port bound here and never listened on (refused at once)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    yield f"http://127.0.0.1:{s.getsockname()[1]}"
    s.close()


@pytest.fixture
def sm(spoolman_fake_store, spoolman_url):
    st = spoolman_fake_store
    st["vendors"][1] = {"id": 1, "name": "SUNLU", "empty_spool_weight": 213}
    st["filaments"][1] = {"id": 1, "name": "PLA+ Grey", "vendor_id": 1, "material": "PLA", "weight": 1000,
                          "spool_weight": 213, "density": 1.24, "color_hex": "8A8C8E", "comment": "Price: $20/kg"}
    return Spoolman(spoolman_url)


def setup(url: str, mods=None, reader="auto") -> None:
    cfg = config.load()
    cfg["modules"] = dict(mods or BOTH)
    cfg["local_intake"] = {"url": url, "tier": "auto"}
    cfg["intake"] = {**cfg.get("intake", {}), "reader": reader}
    config.save(cfg)


class Cap:
    def __init__(self, full=False):
        self.taken, self.refunded, self.full = 0, 0, full

    def charge(self):
        if self.full:
            raise intake.CapReached()
        self.taken += 1
        return self.refund

    def refund(self):
        self.refunded += 1


# ---------- the module entry ----------

def test_the_module_is_opt_in_last_and_newer():
    assert list(modules.MODULES)[-1] == "local_intake" and list(modules.MODULES).index("klipper") == 12
    assert "local_intake" in modules.OPT_IN and modules.NEWER["local_intake"] == (0, 5, 3)
    assert all("local_intake" not in s for s in modules.MODES.values())
    assert modules.MODULES["local_intake"].optional_ai


def test_orders_works_with_either_reader():
    base = {"spoolman": True, "server": True, "orders": True}
    for reader in ("ai_intake", "local_intake"):
        modules.validate({"modules": {**base, reader: True}, "orders": {"file": "/x.json"}})
    with pytest.raises(modules.ModuleError, match="orders needs ai_intake or local_intake"):
        modules.validate({"modules": base, "orders": {"file": "/x.json"}})
    on = frozenset({"spoolman", "server", "ai_intake", "local_intake", "orders"})
    assert "orders" in modules.toggle(on, "ai_intake")[0]                    # the local reader still reads
    off, notes = modules.toggle(on - {"local_intake"}, "ai_intake")
    assert "orders" not in off and "orders" in notes[0]
    on2, _ = modules.toggle(frozenset({"spoolman", "server"}), "orders")      # neither on: ai_intake, as before
    assert "ai_intake" in on2
    on3, _ = modules.toggle(frozenset({"spoolman", "server", "local_intake"}), "orders")   # one reader is enough
    assert "ai_intake" not in on3
    assert modules.needs_of("orders")[0] == "ai_intake or local_intake"


# ---------- the reader order ----------

@pytest.mark.parametrize("mods,reader,order", [
    (BOTH, "auto", ["local", "cloud"]),
    (BOTH, "cloud-then-local", ["cloud", "local"]),
    (BOTH, "cloud", ["cloud"]),
    (BOTH, "nonsense", ["local", "cloud"]),
    ({**BOTH, "ai_intake": False}, "cloud", ["local"]),        # the named reader is off: the one that is on
    ({**BOTH, "local_intake": False}, "auto", ["cloud"]),
    ({"spoolman": True, "server": True}, "auto", []),
])
def test_reader_order(mods, reader, order):
    assert intake.reader_order({"modules": mods, "intake": {"reader": reader}}) == order


# ---------- reads ----------

def test_a_sure_local_read_is_free_and_post_processed_like_a_cloud_read(sm, fake_reader):
    url, data = fake_reader
    setup(url)
    data["read"] = lrf.reply(existing_filament_id=1, color_hex="#ff0000", tare=999)
    fake, cap = FakeClaude(CLOUD), Cap()
    out = intake.read_labels(sm, [JPEG], "grey one", None, fake, charge=cap.charge)
    it = out["items"][0]
    assert out["reader"] == "local" and out["confidence"] == 0.93 and out["tier"] == "cpu" and not out["unsure"]
    assert it["match"] == "existing filament F1" and it["tare"] == 213 and it["color_hex"] == "8A8C8E"
    assert "line" in it and "bambu_parent" in it
    assert it["confidence"] == 0.93 and it["field_confidence"]["vendor"] == 0.97        # for the result screen
    assert it["color_name"] == "Grey" and it["color_family"] == "grey"                    # shown on the result screen
    assert out["usage"]["ms"] == 240 and out["usage"]["input_tokens"] == 0
    assert not fake.calls and cap.taken == 0
    body = data["reads"][0]["body"]
    assert body["hint"] == "grey one" and body["api_version"] == "1.0" and body["tier"] == "auto"
    assert base64.b64decode(body["images_b64"][0]) == JPEG
    f = body["filaments"][0]
    assert f["vendor"]["name"] == "SUNLU" and "comment" not in f and "orders" not in body
    assert data["reads"][0]["auth"] is None                                               # no token file: none sent


def test_the_least_sure_item_decides(sm, fake_reader):
    url, data = fake_reader
    setup(url, {"spoolman": True, "server": True, "local_intake": True})
    data["read"] = {**lrf.reply(), "items": [{**lrf.ITEM, "confidence": 0.95}, {**lrf.ITEM, "confidence": 0.5}]}
    out = intake.read_labels(sm, [JPEG], "", None, None)
    assert out["confidence"] == 0.5 and out["unsure"]


def test_an_unsure_local_read_goes_to_the_cloud_and_takes_the_cap(sm, fake_reader):
    url, data = fake_reader
    setup(url)
    data["read"] = lrf.reply(confidence=0.4)
    fake, cap = FakeClaude(CLOUD), Cap()
    out = intake.read_labels(sm, [JPEG], "", None, fake, charge=cap.charge)
    assert out["reader"] == "cloud" and out["items"][0]["vendor"] == "Polymaker" and cap.taken == 1
    assert len(data["reads"]) == 1 and len(fake.calls) == 1


def test_an_unknown_brand_is_unsure_whatever_the_score(sm, fake_reader):
    url, data = fake_reader
    setup(url)
    data["read"] = lrf.reply(confidence=0.99, vendor="Unknown", note="BRAND UNKNOWN: no logo")
    out = intake.read_labels(sm, [JPEG], "", None, FakeClaude(CLOUD), charge=Cap().charge)
    assert out["reader"] == "cloud"


def test_an_unsure_local_read_is_kept_when_the_cap_is_used_up(sm, fake_reader):
    url, data = fake_reader
    setup(url)
    data["read"] = lrf.reply(confidence=0.4)
    out = intake.read_labels(sm, [JPEG], "", None, FakeClaude(CLOUD), charge=Cap(full=True).charge)
    assert out["reader"] == "local" and out["unsure"] and "used up" in out["note"]


def test_a_local_reader_that_is_down_gives_way_to_the_cloud(sm, dead_url):
    setup(dead_url)
    out = intake.read_labels(sm, [JPEG], "", None, FakeClaude(CLOUD), charge=Cap().charge)
    assert out["reader"] == "cloud" and "local reader" in out["note"] and "does not answer" in out["note"]


def test_local_only_and_down_is_a_clear_error_and_keeps_the_photos(sm, dead_url):
    setup(dead_url, {"spoolman": True, "server": True, "local_intake": True})
    with pytest.raises(intake.ReadError) as e:
        intake.read_labels(sm, [JPEG], "", None, None)
    assert e.value.code == "local_unreachable" and dead_url[7:] in str(e.value)
    assert intake.is_kept(e.value.read_id)


def test_cloud_then_local_falls_back_when_the_cloud_fails(sm, fake_reader):
    url, data = fake_reader
    setup(url, reader="cloud-then-local")
    cap = Cap()
    out = intake.read_labels(sm, [JPEG], "", None,
                             FakeClaude(raises=anthropic.APIConnectionError(request=None)), charge=cap.charge)
    assert out["reader"] == "local" and "cloud reader" in out["note"] and cap.taken == 1


def test_a_cloud_error_carries_its_refund(sm):
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True, "ai_intake": True}
    config.save(cfg)
    cap = Cap()
    with pytest.raises(intake.ReadError) as e:
        intake.read_labels(sm, [JPEG], "", None, FakeClaude(raises=anthropic.APIConnectionError(request=None)),
                           charge=cap.charge)
    assert e.value.code == "unreachable" and cap.taken == 1
    e.value.refund()
    assert cap.refunded == 1


def test_a_local_answer_gets_the_cloud_readers_item_shape(sm, fake_reader):
    url, data = fake_reader
    setup(url, {"spoolman": True, "server": True, "local_intake": True})
    data["read"] = {"items": [{"vendor": "SUNLU", "name": "PLA Matte Black", "material": "PLA", "confidence": 0.9}]}
    out = intake.read_labels(sm, [JPEG, JPEG], "", None, None)
    it = out["items"][0]
    assert set(intake.ITEM_PROPS) <= set(it) and out["confidence"] == 0.9
    assert it["tare"] == 213 and it["net"] == 1000 and it["density"] == 1.24 and it["photos"] == [0, 1]
    assert sorted(it["estimates"]) == ["density", "net", "tare"] and it["sealed_reason"] == "unsure"
    assert it["field_confidence"] == {} and it["color_name"] is None and it["color_family"] is None


@pytest.mark.parametrize("errors,code", [
    ([(400, "bad_image", None)], "local_refused"),
    ([(413, "too_large", None)], "local_refused"),
    ([(400, "unsupported_api_version", None)], "local_version"),
    ([(401, "unauthorized", None)], "local_unauthorized"),
    ([(503, "tier_unavailable", None)], "local_tier_unavailable"),
    ([(500, "read_failed", None)], "local_bad_answer"),
    ([(503, "busy", 0), (503, "busy", 0)], "local_busy"),            # retried once, then given up
])
def test_local_error_answers(sm, fake_reader, errors, code):
    url, data = fake_reader
    setup(url, {"spoolman": True, "server": True, "local_intake": True})
    data["errors"] = list(errors)
    with pytest.raises(intake.ReadError) as e:
        intake.read_labels(sm, [JPEG], "", None, None)
    assert e.value.code == code and "Traceback" not in str(e.value)


def test_busy_is_retried_once(sm, fake_reader):
    url, data = fake_reader
    setup(url, {"spoolman": True, "server": True, "local_intake": True})
    data["errors"] = [(503, "busy", 0)]
    assert intake.read_labels(sm, [JPEG], "", None, None)["reader"] == "local" and len(data["reads"]) == 2


@pytest.mark.parametrize("answer,code", [
    ({"items": "nope"}, "local_bad_answer"),
    ({"api_version": "2.0", "items": []}, "local_version"),
    ({"api_version": 9, "items": []}, "local_version"),
])
def test_bad_local_answers(sm, fake_reader, answer, code):
    url, data = fake_reader
    setup(url, {"spoolman": True, "server": True, "local_intake": True})
    data["read"] = answer
    with pytest.raises(intake.ReadError) as e:
        intake.read_labels(sm, [JPEG], "", None, None)
    assert e.value.code == code


def test_the_token_goes_with_reads_only(sm, fake_reader):
    url, data = fake_reader
    setup(url, {"spoolman": True, "server": True, "local_intake": True})
    (config.paths().etc / local_reader.TOKEN_FILE).write_text("tok-123\n")
    intake.read_labels(sm, [JPEG], "", None, None)
    assert data["reads"][0]["auth"] == "Bearer tok-123"


def test_health(fake_reader, dead_url):
    url, data = fake_reader
    h = local_reader_health(url)
    assert h["ok"] and not h["degraded"] and h["api_version"] == "1.0" and h["version"] == "0.1.0" and h["revise"]
    assert h["tiers"]["cpu"] == {"usable": True, "reason": None} and h["tiers"]["gpu"]["reason"] == "no CUDA device"
    data["health"] = {**data["health"], "status": "degraded"}
    h = local_reader_health(url)
    assert h["ok"] and h["degraded"] and "gpu: no CUDA device" in h["error"]
    data["health"] = {**data["health"], "status": "ok", "tiers": {"cpu": True, "gpu": False}, "api_version": 1}
    assert local_reader_health(url)["tiers"]["gpu"] == {"usable": False, "reason": None}      # the short form
    data["health"] = {**data["health"], "api_version": "2.1"}
    assert "update the kit" in local_reader_health(url)["error"]
    data["health"] = {**data["health"], "api_version": "1.4", "auth_required": True}
    assert "needs a token" in local_reader_health(url)["error"]
    data["health"], data["health_status"] = {"error": {"code": "starting", "message": "loading"}}, 503
    assert "HTTP 503" in local_reader_health(url)["error"]
    assert not local_reader_health(dead_url)["ok"]


def local_reader_health(url):
    return local_reader.health({"local_intake": {"url": url}}, timeout=2)


def test_revise(fake_reader):
    url, data = fake_reader
    cfg = {"local_intake": {"url": url}}
    out = local_reader.revise(cfg, [JPEG], dict(lrf.ITEM), "brand is Polymaker", [], [])
    assert out["items"][0]["vendor"] == "Polymaker"
    body = data["revises"][0]["body"]
    assert body["note"] == "brand is Polymaker" and body["previous"]["vendor"] == "SUNLU"
    data["revise"] = {"item": {**lrf.ITEM, "vendor": "eSUN", "confidence": 0.9}}        # the single-item form
    assert local_reader.revise(cfg, [JPEG], dict(lrf.ITEM), "eSUN", [], [])["items"][0]["vendor"] == "eSUN"


def test_revise_on_a_reader_without_it(dead_url):
    from fakes import readers_fake            # any server without /v1/revise answers 404
    from conftest import _serve
    for url in _serve(readers_fake.app(readers_fake.new_data())):
        with pytest.raises(local_reader.LocalReaderError) as e:
            local_reader.revise({"local_intake": {"url": url}}, [JPEG], dict(lrf.ITEM), "x", [], [])
        assert e.value.code == "revise_unsupported"


def test_check_url():
    assert local_reader.check_url("http://gpu-box.example:7915") is None
    assert local_reader.check_url("https://10.0.0.5:7915/") is None
    assert local_reader.check_url("gpu-box:7915") and local_reader.check_url("http://h:1/v1/read")


# ---------- the API: the cap only for cloud reads ----------

def _client(sm, claude=None):
    pairing.make_cert("fkhost", [], config.paths().etc)
    return TestClient(create_app(sm=sm, claude=claude)), {
        "Authorization": f"Bearer {pairing.redeem_code(pairing.issue('phone').code)}"}


def _read(c, h):
    return c.post("/api/intake/read", headers=h, files=[("photo", ("a.jpg", JPEG, "image/jpeg"))])


def test_api_reads_with_only_the_local_reader_and_uses_no_cap(sm, fake_reader):
    url, _ = fake_reader
    setup(url, {"spoolman": True, "server": True, "local_intake": True})
    c, h = _client(sm)
    r = _read(c, h)
    assert r.status_code == 200 and r.json()["reader"] == "local"
    assert intake.reads_today(config.paths().state / "reads.json") == 0


def test_api_counts_a_cloud_read(sm, fake_reader):
    url, data = fake_reader
    setup(url)
    data["read"] = lrf.reply(confidence=0.2)
    c, h = _client(sm, FakeClaude(CLOUD))
    assert _read(c, h).json()["reader"] == "cloud"
    assert intake.reads_today(config.paths().state / "reads.json") == 1


def test_api_with_no_reader_is_module_off(sm, dead_url):
    setup(dead_url, {"spoolman": True, "server": True})
    c, h = _client(sm)
    r = _read(c, h)
    assert r.status_code == 409 and r.json()["module"] == "ai_intake"


def test_a_mode_change_keeps_orders_on_the_local_reader():
    cfg = {"modules": {"spoolman": True, "server": True, "local_intake": True, "orders": True},
           "orders": {"file": "/x.json"}}
    assert {"orders", "local_intake"} <= modules.enabled(modules.set_mode(cfg, "all-in-one", say=None))
    assert modules.dependents("local_intake", frozenset(cfg["modules"])) == ["orders"]
    assert modules.dependents("local_intake", frozenset(cfg["modules"]) | {"ai_intake"}) == []
