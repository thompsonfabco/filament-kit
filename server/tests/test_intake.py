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


def test_cap_refund_gives_back_newest(tmp_path):
    f = tmp_path / "reads.json"
    f.write_text(json.dumps([time.time() - 100]))
    cap = ReadCap(f, 2)
    cap.take()
    cap.refund()
    stamps = json.loads(f.read_text())
    assert len(stamps) == 1 and stamps[0] < time.time() - 50
    cap.take()
    with pytest.raises(CapReached):
        cap.take()
    cap.refund()
    cap.refund()
    cap.refund()  # never below empty
    assert json.loads(f.read_text()) == []


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
