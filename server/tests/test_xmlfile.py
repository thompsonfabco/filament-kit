"""bridge.xmlfile: the shared data-file loader (parse, validate, override rules)."""
from dataclasses import dataclass, field

import pytest

from filament_kit.bridge import xmlfile

SCHEMA = xmlfile.E(attrs={"version": xmlfile.text}, required=("version",),
                   children={"items": xmlfile.E(children={"item": xmlfile.E(
                       attrs={"key": xmlfile.text, "n": xmlfile.pos}, required=("key",))})})
SECTIONS = {"items": ("item", "key", False)}


@dataclass
class Result:
    items: dict
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def with_errors(self, errors, warnings=None):
        return Result(self.items, list(errors), list(self.warnings if warnings is None else warnings))


def _parse(data, where):
    return xmlfile.parse(data, where, root_tag="t", schema=SCHEMA, major="1", max_bytes=10_000)


def _build(sections, where):
    return Result({k: el.get("n") for k, el in sections["items"].items()})


def _loader(bundled, override):
    return xmlfile.Cached(bundled, lambda: override, parse=_parse,
                          elements=lambda r, w: xmlfile.elements(r, SECTIONS, w), build=_build,
                          empty=lambda: Result({}), max_bytes=10_000)


def test_parse_rejects_dtd():
    with pytest.raises(xmlfile.XmlError):
        _parse(b'<!DOCTYPE t [<!ENTITY x "y">]><t version="1"/>', "f")


def test_unknown_element_is_warning():
    root, warnings = _parse(b'<t version="1"><items><item key="a"/><gizmo/></items></t>', "f")
    assert root.tag == "t"
    assert any("gizmo" in w for w in warnings)


def test_text_check_runs():
    spec = xmlfile.E(children={"g": xmlfile.E(text=True, text_check=lambda v: (_ for _ in ()).throw(
        ValueError("bad text")) if "\n" in v.strip() else v)})
    errors, warnings = [], []
    root = xmlfile.fromstring(b"<r><g>A\nB</g></r>")
    xmlfile.check(root, spec, "r", errors, warnings)
    assert errors and "bad text" in errors[0]


def test_cached_ignores_older_override(tmp_path):
    b = tmp_path / "b.xml"
    b.write_bytes(b'<t version="1.1"><items><item key="a" n="1"/></items></t>')
    o = tmp_path / "o.xml"
    o.write_bytes(b'<t version="1"><items><item key="a" n="2"/></items></t>')
    r = _loader(b, o).load()
    assert r.items == {"a": "1"}
    assert any("not newer" in w for w in r.warnings)


def test_cached_newer_override_wins_per_key(tmp_path):
    b = tmp_path / "b.xml"
    b.write_bytes(b'<t version="1"><items><item key="a" n="1"/><item key="b" n="1"/></items></t>')
    o = tmp_path / "o.xml"
    o.write_bytes(b'<t version="1.1"><items><item key="a" n="2"/></items></t>')
    assert _loader(b, o).load().items == {"a": "2", "b": "1"}


def test_cached_keeps_last_good_on_bad_override(tmp_path):
    b = tmp_path / "b.xml"
    b.write_bytes(b'<t version="1"><items><item key="a" n="1"/></items></t>')
    o = tmp_path / "o.xml"
    o.write_bytes(b'<t version="1.1"><items><item key="a" n="5"/></items></t>')
    ld = _loader(b, o)
    assert ld.load().items == {"a": "5"}
    o.write_bytes(b'<t version="1.1"><items><item key="a" n="0"/></items></t>')   # n must be positive
    r = ld.load()
    assert r.items == {"a": "5"}
    assert r.errors
