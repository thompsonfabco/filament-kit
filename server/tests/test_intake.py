import json
import os
import time
from pathlib import Path

import anthropic
import httpx
import pytest
from fakes.claude_fake import FakeClaude

from filament_kit.intake import (RULES, SCHEMA, CapReached, PhotoError, ReadCap, ReadError, check_photos,
                                 read_labels, retry)
from filament_kit import intake
from filament_kit.spoolman import Spoolman

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
DATA = Path(__file__).parent / "data" / "read_response.json"


def recorded() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "anthropic_key").write_text("sk-test\n")


@pytest.fixture
def sm(spoolman_fake_store, spoolman_url):
    st = spoolman_fake_store
    st["vendors"][1] = {"id": 1, "name": "SUNLU", "empty_spool_weight": 213}
    st["filaments"][1] = {"id": 1, "name": "PETG Grey", "vendor_id": 1, "material": "PETG", "weight": 1000,
                          "spool_weight": 213, "density": 1.27, "color_hex": "8A8D8F"}
    return Spoolman(spoolman_url)


def test_rejects_png_and_large():
    with pytest.raises(PhotoError, match="label.png"):
        check_photos([("label.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50)])
    with pytest.raises(PhotoError, match="3 MB") as e:
        check_photos([("big.jpg", JPEG + b"0" * (3 * 1024 * 1024))])
    assert "big.jpg" in str(e.value)
    with pytest.raises(PhotoError):
        check_photos([(f"p{i}.jpg", JPEG) for i in range(9)])
    with pytest.raises(PhotoError):
        check_photos([])
    assert check_photos([("a.jpg", JPEG)]) == [JPEG]


def test_cap_persists(tmp_path):
    f = tmp_path / "state" / "reads.json"
    cap = ReadCap(f, 2)
    cap.take()
    cap.take()
    with pytest.raises(CapReached):
        ReadCap(f, 2).take()


def test_cap_expires_after_a_day(tmp_path):
    f = tmp_path / "reads.json"
    f.write_text(json.dumps([time.time() - 90000, time.time() - 86500]))
    ReadCap(f, 2).take()


def test_read_maps_existing_filament(sm):
    fake = FakeClaude(recorded())
    out = read_labels(sm, [JPEG, JPEG], "", None, client=fake)
    it = out["items"][0]
    assert it["existing_filament_id"] == 1
    assert (it["vendor"], it["name"]) == ("SUNLU", "PETG Grey")
    assert it["match"] == "existing filament F1"
    assert it["color_hex"] == "8A8D8F"
    assert it["count"] == 1
    assert out["tag"] is None
    assert out["usage"]["model"] == "claude-opus-5-5"
    assert out["usage"]["input_tokens"] == 1700 and out["usage"]["output_tokens"] == 300
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 16000
    assert kw["system"] == RULES
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["schema"] == SCHEMA
    content = kw["messages"][0]["content"]
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "F1 | SUNLU | PETG Grey" in content[0]["text"]
    assert sum(1 for b in content if b["type"] == "image") == 2
    assert content[-1]["text"] == "User's note: (none)"


def test_new_filament_and_vendor(sm):
    r = recorded()
    r["items"][0].update(existing_filament_id=None, vendor="Acme", color_hex="zzz", count=0)
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert it["match"] == "new filament and new vendor"
    assert it["color_hex"] is None and it["count"] == 1


def test_single_item_with_tag_is_opened(sm):
    fake = FakeClaude(recorded())
    out = read_labels(sm, [JPEG], "my note", "4:a1:b2", client=fake)
    it = out["items"][0]
    assert it["sealed"] is False and "4:a1:b2" in it["sealed_reason"]
    assert out["tag"]["nfc_id"] == "4:a1:b2"
    text = " ".join(b.get("text", "") for b in fake.calls[0]["messages"][0]["content"])
    assert "4:a1:b2" in text and "User's note: my note" in text


def _status_error(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize("exc, code", [
    (lambda: _status_error(anthropic.AuthenticationError, 401), "bad_key"),
    (lambda: _status_error(anthropic.RateLimitError, 429), "rate_limited"),
    (lambda: _status_error(anthropic.InternalServerError, 500), "api_error"),
    (lambda: anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "unreachable"),
])
def test_error_codes(sm, exc, code):
    with pytest.raises(ReadError) as e:
        read_labels(sm, [JPEG], "", None, client=FakeClaude(raises=exc()))
    assert e.value.code == code


def test_bad_key_maps_to_code(sm):
    with pytest.raises(ReadError) as e:
        read_labels(sm, [JPEG], "", None, client=FakeClaude(raises=_status_error(anthropic.AuthenticationError, 401)))
    assert e.value.code == "bad_key"


@pytest.mark.parametrize("stop, code", [("refusal", "refused"), ("max_tokens", "truncated")])
def test_stop_reasons(sm, stop, code):
    with pytest.raises(ReadError) as e:
        read_labels(sm, [JPEG], "", None, client=FakeClaude(recorded(), stop_reason=stop))
    assert e.value.code == code


def test_missing_key_is_bad_key(sm, tmp_path):
    (tmp_path / "etc" / "anthropic_key").unlink()
    with pytest.raises(ReadError) as e:
        read_labels(sm, [JPEG], "", None)
    assert e.value.code == "bad_key"


def test_failed_read_kept_and_retry(sm, tmp_path):
    bad = FakeClaude(raises=_status_error(anthropic.RateLimitError, 429))
    with pytest.raises(ReadError) as e:
        read_labels(sm, [JPEG, JPEG + b"2"], "n", None, client=bad)
    rid = e.value.read_id
    d = tmp_path / "state" / "failed" / rid
    assert (d / "photo0.jpg").read_bytes() == JPEG and (d / "photo1.jpg").exists()
    out = retry(rid, sm, client=FakeClaude(recorded()))
    assert out["items"][0]["existing_filament_id"] == 1
    assert out["read_id"] == rid
    assert not d.exists()  # kept only while unread


def test_success_has_read_id_and_keeps_nothing(sm, tmp_path):
    out = read_labels(sm, [JPEG], "", None, client=FakeClaude(recorded()))
    assert out["read_id"]
    assert not (tmp_path / "state" / "failed" / out["read_id"]).exists()


def test_old_failed_reads_are_deleted(sm, tmp_path):
    old = tmp_path / "state" / "failed" / "oldone"
    old.mkdir(parents=True)
    (old / "photo0.jpg").write_bytes(JPEG)
    t = time.time() - 25 * 3600
    os.utime(old / "photo0.jpg", (t, t))
    os.utime(old, (t, t))
    with pytest.raises(ReadError):
        retry("oldone", sm, client=FakeClaude(recorded()))
    assert not old.exists()


def test_is_kept(tmp_path):
    from filament_kit.intake import is_kept
    root = tmp_path / "state" / "failed"
    (root / "fresh").mkdir(parents=True)
    old = root / "old"
    old.mkdir()
    t = time.time() - 25 * 3600
    os.utime(old, (t, t))
    assert is_kept("fresh")
    assert not is_kept("old") and not old.exists()  # swept before the check
    assert not is_kept("nope") and not is_kept("../failed") and not is_kept("")


def test_retry_unknown_id(sm):
    with pytest.raises(ReadError) as e:
        retry("nope", sm, client=FakeClaude(recorded()))
    assert e.value.code == "not_found"


def test_rules_mention_no_orders():
    assert "Amazon" not in RULES and "order" not in RULES.lower()
    props = SCHEMA["properties"]["items"]["items"]["properties"]
    assert not {"order", "price_per_kg", "price_line"} & set(props)
    assert SCHEMA["properties"]["items"]["items"]["required"] == list(props)


def test_cap_refund_gives_back_exactly_the_taken_read(tmp_path):
    f = tmp_path / "reads.json"
    f.write_text(json.dumps([time.time() - 100]))   # the old format: bare stamps, no tickets
    cap = ReadCap(f, 2)
    t = cap.take("phone-1")
    cap.refund(t, "phone-1")
    stamps = json.loads(f.read_text())
    assert len(stamps) == 1 and stamps[0] < time.time() - 50
    cap.take("phone-1")
    with pytest.raises(CapReached):
        cap.take("phone-1")


def test_cap_reads_the_old_format(tmp_path):
    f = tmp_path / "reads.json"
    f.write_text(json.dumps([time.time() - 100, time.time() - 200]))
    cap = ReadCap(f, 3)
    cap.take("d")
    with pytest.raises(CapReached):
        cap.take("d")
    assert intake.reads_today(f) == 3


def test_cap_refund_without_a_take_is_refused(tmp_path):
    f = tmp_path / "reads.json"
    cap = ReadCap(f, 2)
    cap.take("d")
    with pytest.raises(intake.RefundRefused):
        cap.refund("made-up", "d")
    with pytest.raises(intake.RefundRefused):
        cap.refund(None, "d")
    assert intake.reads_today(f) == 1


def test_cap_refund_twice_is_refused_the_second_time(tmp_path):
    f = tmp_path / "reads.json"
    cap = ReadCap(f, 2)
    cap.take("d")
    t = cap.take("d")
    cap.refund(t, "d")
    with pytest.raises(intake.RefundRefused):
        cap.refund(t, "d")
    assert intake.reads_today(f) == 1


def test_cap_refund_of_an_expired_ticket_is_refused(tmp_path, monkeypatch):
    f = tmp_path / "reads.json"
    cap = ReadCap(f, 2)
    t = cap.take("d")
    later = time.time() + intake.TICKET_TTL + 1
    monkeypatch.setattr(intake.time, "time", lambda: later)
    with pytest.raises(intake.RefundRefused):
        cap.refund(t, "d")
    assert intake.reads_today(f) == 1


@pytest.mark.parametrize("after, ok", [(600, True), (901, False)])
def test_cap_refund_covers_the_claude_clients_slowest_failure(tmp_path, monkeypatch, after, ok):
    """The station refunds on the errors that come after the Anthropic client's timeout and retries (up to
    CLAUDE_TIMEOUT x (CLAUDE_RETRIES + 1)), so a ticket lives 15 minutes."""
    f = tmp_path / "reads.json"
    cap = ReadCap(f, 2)
    start = time.time()
    monkeypatch.setattr(intake.time, "time", lambda: start)
    t = cap.take("d")
    monkeypatch.setattr(intake.time, "time", lambda: start + after)
    if ok:
        cap.refund(t, "d")
        assert intake.reads_today(f) == 0
    else:
        with pytest.raises(intake.RefundRefused):
            cap.refund(t, "d")
        assert intake.reads_today(f) == 1


def test_ticket_ttl_is_tied_to_the_claude_client():
    assert intake.TICKET_TTL == 900
    assert intake.TICKET_TTL >= intake.CLAUDE_TIMEOUT * (intake.CLAUDE_RETRIES + 1)


def test_cap_refund_of_another_devices_ticket_is_refused(tmp_path):
    f = tmp_path / "reads.json"
    cap = ReadCap(f, 2)
    t = cap.take("phone-1")
    with pytest.raises(intake.RefundRefused):
        cap.refund(t, "web (MCP)")
    assert intake.reads_today(f) == 1
    cap.refund(t, "phone-1")         # the refused try did not use the ticket up
    assert intake.reads_today(f) == 0


def test_cap_looping_refunds_never_go_below_the_real_count(tmp_path):
    f = tmp_path / "reads.json"
    f.write_text(json.dumps([time.time() - 100]))
    cap = ReadCap(f, 3)
    t1, t2 = cap.take("d"), cap.take("d")
    cap.refund(t1, "d")
    for _ in range(5):
        for t in (t1, "x", None):
            with pytest.raises(intake.RefundRefused):
                cap.refund(t, "d")
    assert intake.reads_today(f) == 2      # the old read and t2's: both reached Claude
    assert t2 not in f.read_text()         # tickets are kept hashed


# ---------- Task 7b: product line at intake ----------

def test_schema_and_rules_ask_for_line():
    from filament_kit.intake import ITEM_PROPS
    assert ITEM_PROPS["line"] == {"type": "string"}
    assert "line" in SCHEMA["properties"]["items"]["items"]["required"]
    assert "line: the product line as printed, without the colour (e.g. 'PLA+ 2.0', 'PETG HF')" in RULES
    assert "for an existing filament copy its line from the catalog" in RULES


def test_read_without_line_gets_derived_line_and_parent(sm):
    r = recorded()
    assert "line" not in r["items"][0]
    fake = FakeClaude(r)
    it = read_labels(sm, [JPEG], "", None, client=fake)["items"][0]
    # existing filament F1 "PETG Grey" has no extra.line: the longest SUNLU library product prefixing its name
    assert it["line"] == "PETG"
    assert (it["bambu_parent"], it["parent_source"], it["line_exists"]) == ("SUNLU PETG", "library", False)
    assert "F1 | SUNLU | PETG Grey | PETG | net 1000 | tare 213 | density 1.27 | 8A8D8F | line -" \
        in fake.calls[0]["messages"][0]["content"][0]["text"]


def test_new_filament_line_from_claude_and_existing_line(sm):
    from filament_kit import library
    from filament_kit.profiles import lines
    lines.ensure_saved("ELEGOO", "PETG HF", "PETG", bambu_parent="Generic PETG", library=library.load(),
                       store=None)
    r = recorded()
    r["items"][0].update(existing_filament_id=None, vendor="ELEGOO", name="PETG HF Black", line="PETG HF")
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert (it["line"], it["bambu_parent"], it["parent_source"], it["line_exists"]) == \
        ("PETG HF", "Generic PETG", "user", True)


def test_existing_filament_takes_its_extra_line(sm, spoolman_fake_store):
    spoolman_fake_store["filaments"][1]["extra"] = {"line": json.dumps("PETG 2.0")}
    r = recorded()
    r["items"][0]["line"] = "Something Else"
    fake = FakeClaude(r)
    it = read_labels(sm, [JPEG], "", None, client=fake)["items"][0]
    assert it["line"] == "PETG 2.0" and it["line_exists"] is False
    assert "| line PETG 2.0" in fake.calls[0]["messages"][0]["content"][0]["text"]


def test_new_filament_empty_line_is_derived(sm):
    r = recorded()
    r["items"][0].update(existing_filament_id=None, vendor="SUNLU", name="PLA+ 2.0 Grey", line=" ")
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert it["line"] == "PLA+ 2.0" and it["parent_source"] == "library"


def test_line_kept_within_add_limits(sm):
    r = recorded()
    r["items"][0].update(existing_filament_id=None, vendor="ELEGOO", name="PETG HF Black",
                         line="PETG HF @BBL H2D " + "x" * 200)
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert it["line"] == "PETG HF"


def test_fallback_line_drops_the_colour(sm, monkeypatch):
    """Task 7c: when the proposal fails, the line falls back to the product (name without colour), not the name."""
    from filament_kit.profiles import lines

    def boom():
        raise lines.LineStoreError("lines.json is unusable")

    monkeypatch.setattr(lines, "load", boom)
    r = recorded()
    r["items"][0].update(existing_filament_id=None, vendor="SUNLU", name="PLA+ 2.0 Grey", line=" ")
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert it["line"] == "PLA+ 2.0" and it["parent_source"] == "none" and it["bambu_parent"] is None


def test_fallback_line_empty_when_no_product_is_known(sm, monkeypatch):
    from filament_kit import library
    from filament_kit.profiles import lines

    def boom():
        raise OSError("library unreadable")

    monkeypatch.setattr(library, "load", boom)
    r = recorded()
    r["items"][0].update(existing_filament_id=None, vendor="NoName", name="Silk Rainbow", line="")
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert it["line"] == "" and it["parent_source"] == "none"


def test_fallback_line_empty_when_the_library_has_no_prefix(sm, monkeypatch):
    from filament_kit.profiles import lines

    def boom():
        raise lines.LineStoreError("lines.json is unusable")

    monkeypatch.setattr(lines, "load", boom)
    r = recorded()
    r["items"][0].update(existing_filament_id=None, vendor="NoName", name="Silk Rainbow", line="")
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert it["line"] == ""


def _add_read_item(sm, it):
    from filament_kit import inventory
    rules = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2, "overflow": "Overflow",
             "sealed_location": "Sealed stock"}
    keep = {k: it[k] for k in ("vendor", "name", "material", "net", "tare", "density", "count", "line")}
    return inventory.add_and_link(sm, [keep], rules, dry=False, uid=None)


def test_existing_filament_read_line_is_ignored_and_add_sends_no_patch(sm, spoolman_fake_store, monkeypatch):
    """Fix round 1: an existing filament with no extra.line takes its derived line, never Claude's read line, so
    an unedited add can't move it."""
    r = recorded()
    r["items"][0]["line"] = "PETG Something Else"
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    assert it["existing_filament_id"] == 1 and it["line"] == "PETG"
    patches = []
    real = sm.patch
    monkeypatch.setattr(sm, "patch", lambda path, body: patches.append(path) or real(path, body))
    _add_read_item(sm, it)
    assert not [p for p in patches if p.startswith("filament/")]
    assert "line" not in (spoolman_fake_store["filaments"][1].get("extra") or {})


def test_existing_filament_no_patch_when_the_library_fails(sm, spoolman_fake_store, monkeypatch):
    """The library-failure branch: with no extra.line the filament's line is unknown, so nothing is written."""
    from filament_kit import library
    r = recorded()
    r["items"][0]["line"] = "PETG Something Else"
    it = read_labels(sm, [JPEG], "", None, client=FakeClaude(r))["items"][0]
    it["line"] = "PETG Something Else"            # as if edited in the app
    real_load = library.load

    def boom():
        raise OSError("library unreadable")

    monkeypatch.setattr(library, "load", boom)
    patches = []
    real = sm.patch
    monkeypatch.setattr(sm, "patch", lambda path, body: patches.append(path) or real(path, body))
    _add_read_item(sm, it)
    assert not [p for p in patches if p.startswith("filament/")]
    assert "line" not in (spoolman_fake_store["filaments"][1].get("extra") or {})
    monkeypatch.setattr(library, "load", real_load)


# ---------- merge-ops: orders, tare hints, station weight -> gross, fresh tag ----------

from filament_kit import intake as intake_mod  # noqa: E402

ORDERS = [
    {"order": "111-1", "date": "2026-10-01", "asin": "B0OLD", "title": "SUNLU PETG 1kg Grey", "qty": 1,
     "unit_price": 18.99, "seller": "SUNLU"},
    {"order": "111-2", "date": "2026-10-20", "asin": "B0NEW", "title": "ELEGOO PLA 1kg Black", "qty": 2,
     "unit_price": 15.99, "seller": "ELEGOO"},
    {"order": "111-3", "date": "2026-10-10", "asin": "B0BUN", "title": "SUNLU PLA 4 Pack Bundle 4kg", "qty": 1,
     "unit_price": 49.99, "seller": "SUNLU"},
]


def _ordered(r):
    for it in r["items"]:
        it.update(order="111-2", price_per_kg=7.99512, price_line="Price: $8.00/kg - Amazon order 111-2 "
                  "(2026-10-20): $15.99 / 2 kg, ASIN B0NEW")
    return r


def test_no_orders_keeps_rules_schema_and_block(sm):
    fake = FakeClaude(recorded())
    out = read_labels(sm, [JPEG], "", None, client=fake)
    kw = fake.calls[0]
    assert kw["system"] == RULES and kw["output_config"]["format"]["schema"] == SCHEMA
    assert "Amazon" not in kw["messages"][0]["content"][0]["text"]
    assert "order" not in out["items"][0] and out["scale"] is None


def test_orders_block_rules_schema_and_filter(sm, spoolman_fake_store):
    # B0OLD is already in a filament's price line (inventoried): dropped; the bundle B0BUN stays even though known
    spoolman_fake_store["filaments"][1]["comment"] = "Price: $18.99/kg - Amazon order 111-1 (2026-10-01): " \
                                                     "$18.99 / 1 kg, ASIN B0OLD | also B0BUN"
    fake = FakeClaude(_ordered(recorded()))
    out = read_labels(sm, [JPEG], "", None, client=fake, orders=ORDERS)
    kw = fake.calls[0]
    assert kw["system"].startswith(RULES) and kw["system"] != RULES
    assert ("price_line = 'Price: $<price_per_kg>/kg - Amazon order <order> (<date>): $<unit price> / <kg> kg, "
            "ASIN <asin>'") in kw["system"]
    schema = kw["output_config"]["format"]["schema"]["properties"]["items"]["items"]
    assert {"order", "price_per_kg", "price_line"} <= set(schema["required"])
    assert SCHEMA["properties"]["items"]["items"]["required"] == list(intake_mod.ITEM_PROPS)  # base untouched
    block = kw["messages"][0]["content"][0]
    assert block["cache_control"] == {"type": "ephemeral"}
    text = block["text"]
    assert "B0OLD" not in text.split("Amazon filament orders")[1]
    assert text.index("111-2") < text.index("111-3")            # newest first
    assert "2026-10-20 | 111-2 | B0NEW | qty 2 | $15.99 | ELEGOO | ELEGOO PLA 1kg Black" in text
    it = out["items"][0]
    assert it["order"] == "111-2" and it["price_per_kg"] == 8.0 and it["price_line"].startswith("Price: $8.00/kg")


def test_orders_empty_list_says_unavailable(sm):
    fake = FakeClaude(_ordered(recorded()))
    read_labels(sm, [JPEG], "", None, client=fake, orders=[])
    assert "(order history unavailable)" in fake.calls[0]["messages"][0]["content"][0]["text"]


def test_filter_orders_multi_pattern():
    fils = [{"comment": "ASIN A1 ASIN A2 ASIN A3 ASIN A4"}]
    rows = [{"date": "1", "order": "o", "asin": a, "title": t} for a, t in
            (("A1", "PLA 2-pack"), ("A2", "PETG 1kg"), ("A3", "PLA 2.5kg spool"), ("A4", "Rainbow 10 colors"))
            ] + [{"date": "2", "order": "p", "asin": None, "title": "no asin"}]
    kept = [o["asin"] for o in intake_mod.filter_orders(rows, fils)]
    assert kept == [None, "A1", "A3", "A4"]


def test_tare_hints_from_config_reach_the_prompt(sm, tmp_path):
    (tmp_path / "etc" / "config.json").write_text(json.dumps({"intake": {"tare_hints": {"Acme": 177,
                                                                                         "SUNLU": 213}}}))
    fake = FakeClaude(recorded())
    read_labels(sm, [JPEG], "", None, client=fake)
    text = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert "Acme 177 g" in text and "SUNLU 213 g" in text


def _opened(r):
    r["items"][0].update(sealed=False, sealed_reason="bare spool")
    return r


@pytest.mark.parametrize("weight, gross", [
    ({"grams": 1100.5, "age_seconds": 20, "held": False}, 1100.5),
    ({"grams": 1100.5, "age_seconds": 400, "held": False}, None),     # stale
    ({"grams": 1100.5, "age_seconds": 400, "held": True}, 1100.5),    # held on the panel
    ({"grams": 150, "age_seconds": 5, "held": False}, None),          # not above the tare (213)
])
def test_station_weight_becomes_gross(sm, weight, gross):
    out = read_labels(sm, [JPEG], "", None, client=FakeClaude(_opened(recorded())),
                      station_state={"tag": None, "last_weight": weight})
    assert out["items"][0].get("gross") == gross
    assert out["scale"] == (weight if weight["age_seconds"] <= 300 or weight["held"] else None)


def test_station_weight_needs_one_opened_single_spool(sm):
    st = {"last_weight": {"grams": 1100, "age_seconds": 5, "held": False}}
    sealed = read_labels(sm, [JPEG], "", None, client=FakeClaude(recorded()), station_state=st)
    assert "gross" not in sealed["items"][0]
    r = _opened(recorded())
    r["items"][0]["count"] = 2
    assert "gross" not in read_labels(sm, [JPEG], "", None, client=FakeClaude(r), station_state=st)["items"][0]
    r = _opened(recorded())
    r["items"].append(dict(r["items"][0]))
    out = read_labels(sm, [JPEG], "", None, client=FakeClaude(r), station_state=st)
    assert all("gross" not in it for it in out["items"])


def test_fresh_tag_forces_opened_and_then_gross(sm):
    fake = FakeClaude(recorded())                                   # Claude says sealed: true
    tag = {"nfc_id": "4:a1:b2:c3", "age_seconds": 12, "reader": "station", "held": False}
    out = read_labels(sm, [JPEG], "", None, client=fake, fresh_tag=tag,
                      station_state={"last_weight": {"grams": 1050, "age_seconds": 12, "held": False}})
    it = out["items"][0]
    assert it["sealed"] is False and "4:a1:b2:c3" in it["sealed_reason"] and "12 s" in it["sealed_reason"]
    assert it["gross"] == 1050
    assert out["tag"]["nfc_id"] == "4:a1:b2:c3" and out["tag"]["reader"] == "station"
    text = " ".join(b.get("text", "") for b in fake.calls[0]["messages"][0]["content"])
    assert "12 s before sending these photos" in text


def test_fresh_tag_with_two_items_changes_nothing(sm):
    r = recorded()
    r["items"].append(dict(r["items"][0]))
    out = read_labels(sm, [JPEG], "", None, client=FakeClaude(r),
                      fresh_tag={"nfc_id": "4:a1:b2:c3", "age_seconds": 3, "reader": "printer"})
    assert all(it["sealed"] is True for it in out["items"])


def test_load_orders(tmp_path):
    f = tmp_path / "orders.json"
    cfg = {"modules": {"ai_intake": True, "orders": True}, "orders": {"file": str(f)}}
    assert intake_mod.load_orders({"modules": {"orders": True}, "orders": {"file": None}}) is None
    assert intake_mod.load_orders({"orders": {"file": str(f)}}) is None   # module off (server mode)
    assert intake_mod.load_orders(cfg) == []                         # on, but the file is missing
    f.write_text(json.dumps({"updated": "x", "items": ORDERS}))
    assert intake_mod.load_orders(cfg) == ORDERS
