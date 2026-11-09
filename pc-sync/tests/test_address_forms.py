"""The server's address when pairing by hand: a name, an IPv4 or an IPv6 address, with or without a port; kept as typed."""
import pytest

from fksync import client
from fksync.__main__ import _parse_address


@pytest.mark.parametrize("text, host, port", [
    ("kit.local", "kit.local", client.DEFAULT_PORT), ("kit.example.com:9000", "kit.example.com", 9000),
    ("192.0.2.10", "192.0.2.10", client.DEFAULT_PORT), ("192.0.2.10:9000", "192.0.2.10", 9000),
    ("2001:db8::1", "2001:db8::1", client.DEFAULT_PORT), ("[2001:db8::1]", "2001:db8::1", client.DEFAULT_PORT),
    ("[2001:db8::1]:9000", "2001:db8::1", 9000), ("https://[2001:db8::1]:9000/", "2001:db8::1", 9000),
    ("https://kit.local/", "kit.local", client.DEFAULT_PORT), ("Kit.Example.COM", "Kit.Example.COM", client.DEFAULT_PORT)])
def test_good_addresses(text, host, port):
    assert _parse_address(text) == (host, port)


@pytest.mark.parametrize("text", ["", "not an address", "a:b:c", "[2001:db8::1]:x", "[nope]", "kit.local:0", "kit.local:99999"])
def test_bad_addresses(text):
    with pytest.raises(ValueError):
        _parse_address(text)
