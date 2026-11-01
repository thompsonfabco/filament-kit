import pytest

from filament_kit import tags


def test_format_uid():
    assert tags.format_uid(bytes.fromhex("0477900e092289")) == "4:77:90:e:9:22:89"


@pytest.mark.parametrize("text", ["04:77:90:0E:09:22:89", "047790 0e092289", "4:77:90:e:9:22:89"])
def test_normalize_uid(text):
    assert tags.normalize_uid(text) == "4:77:90:e:9:22:89"


def test_normalize_short_forms():
    assert tags.normalize_uid("04a20f01") == "4:a2:f:1"
    assert tags.normalize_uid("4:a2:f:1") == "4:a2:f:1"


@pytest.mark.parametrize("text", ["047790", "zz:11:22:33", "", "04:7:7:9:0:1:fff"])
def test_normalize_rejects(text):
    with pytest.raises(ValueError):
        tags.normalize_uid(text)


def test_stored():
    assert tags.stored({"extra": {"nfc_id": "\"4:77:90:e:9:22:89\""}}) == "4:77:90:e:9:22:89"
    assert tags.stored({"extra": {"nfc_id": "\"\""}}) is None
    assert tags.stored({"extra": {"nfc_id": ""}}) is None
    assert tags.stored({"extra": {}}) is None
    assert tags.stored({}) is None


@pytest.mark.parametrize("raw", ["123", "[1, 2]", "true", "null"])
def test_stored_non_string_json_is_none(raw):
    assert tags.stored({"extra": {"nfc_id": raw}}) is None
