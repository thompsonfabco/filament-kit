import pytest

from filament_kit import tags


def test_format_uid():
    assert tags.format_uid(bytes.fromhex("0a0b0c0d0e0f01")) == "a:b:c:d:e:f:1"


@pytest.mark.parametrize("text", ["0A:0B:0C:0D:0E:0F:01", "0a0b0c 0d0e0f01", "a:b:c:d:e:f:1"])
def test_normalize_uid(text):
    assert tags.normalize_uid(text) == "a:b:c:d:e:f:1"


def test_normalize_short_forms():
    assert tags.normalize_uid("04a20f01") == "4:a2:f:1"
    assert tags.normalize_uid("4:a2:f:1") == "4:a2:f:1"


@pytest.mark.parametrize("text", ["0a0b0c", "zz:11:22:33", "", "04:7:7:9:0:1:fff"])
def test_normalize_rejects(text):
    with pytest.raises(ValueError):
        tags.normalize_uid(text)


def test_stored():
    assert tags.stored({"extra": {"nfc_id": "\"a:b:c:d:e:f:1\""}}) == "a:b:c:d:e:f:1"
    assert tags.stored({"extra": {"nfc_id": "\"\""}}) is None
    assert tags.stored({"extra": {"nfc_id": ""}}) is None
    assert tags.stored({"extra": {}}) is None
    assert tags.stored({}) is None


@pytest.mark.parametrize("raw", ["123", "[1, 2]", "true", "null"])
def test_stored_non_string_json_is_none(raw):
    assert tags.stored({"extra": {"nfc_id": raw}}) is None
