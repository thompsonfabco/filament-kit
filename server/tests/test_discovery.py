import socket
import time

from filament_kit.bridge import discovery

NOTIFY = (
    "NOTIFY * HTTP/1.1\r\n"
    "HOST: 255.255.255.255:2021\r\n"
    "Server: Buildroot/2018.02-rc3 UPnP/1.0 ssdpd/1.8\r\n"
    "Location: 192.168.1.50\r\n"
    "NT: urn:bambulab-com:device:3dprinter:1\r\n"
    "USN: 01P00A123456789\r\n"
    "Cache-Control: max-age=1800\r\n"
    "DevModel.bambu.com: C11\r\n"
    "DevName.bambu.com: Office P1P\r\n"
    "DevSignal.bambu.com: -40\r\n"
    "DevConnect.bambu.com: lan\r\n"
    "DevBind.bambu.com: free\r\n"
    "\r\n"
)
EXPECTED = {"serial": "01P00A123456789", "ip": "192.168.1.50", "model": "C11",
            "name": "Office P1P", "connect": "lan"}


def test_parse_crlf():
    assert discovery.parse_notify(NOTIFY.encode()) == EXPECTED


def test_parse_lowercase_headers_and_lf():
    text = NOTIFY.replace("\r\n", "\n").replace("Location", "location").replace("USN", "usn") \
        .replace("DevModel.bambu.com", "devmodel.bambu.com").replace("DevName.bambu.com", "DEVNAME.BAMBU.COM") \
        .replace("DevConnect.bambu.com", "devconnect.bambu.com")
    assert discovery.parse_notify(text.encode()) == EXPECTED


def test_garbage_gives_none():
    assert discovery.parse_notify(b"") is None
    assert discovery.parse_notify(b"\xff\xfe\x00garbage") is None
    assert discovery.parse_notify(b"M-SEARCH * HTTP/1.1\r\nHOST: x\r\n\r\n") is None
    assert discovery.parse_notify(b"NOTIFY * HTTP/1.1\r\nUSN: only-serial\r\n\r\n") is None
    assert discovery.parse_notify(b"NOTIFY * HTTP/1.1\r\nNT: urn:other:thing\r\nUSN: a\r\nLocation: b\r\n\r\n") is None


def _send(port, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(payload, ("127.0.0.1", port))


def _wait(found, n=1):
    for _ in range(100):
        if len(found) >= n:
            break
        time.sleep(0.05)


def _local(ip="127.0.0.1"):
    return NOTIFY.replace("192.168.1.50", ip).encode()


def _listener(found):
    return discovery.Listener(found.append, port=0, host="127.0.0.1", multicast_port=0,
                              allow_loopback=True).start()


def test_listener_reports_found_and_survives_garbage():
    found = []
    lst = _listener(found)
    try:
        _send(lst.port, b"junk")
        _send(lst.port, _local())
        _wait(found)
    finally:
        lst.stop()
    assert found == [dict(EXPECTED, ip="127.0.0.1")]


def test_listener_hears_second_socket_too():
    found = []
    lst = _listener(found)
    try:
        assert lst.multicast_port and lst.multicast_port != lst.port
        _send(lst.multicast_port, _local())
        _wait(found)
    finally:
        lst.stop()
    assert len(found) == 1


def test_listener_drops_source_mismatch():
    found = []
    lst = _listener(found)
    try:
        _send(lst.port, _local("10.9.9.9"))   # source is 127.0.0.1, claims 10.9.9.9
        _send(lst.port, _local())              # genuine, proves the loop still runs
        _wait(found)
    finally:
        lst.stop()
    assert [f["ip"] for f in found] == ["127.0.0.1"]


def test_listener_drops_bad_location():
    found = []
    lst = _listener(found)
    try:
        for bad in ("not-an-ip", "::1", "0.0.0.0", "239.255.255.250", "255.255.255.255"):
            _send(lst.port, _local(bad))
        _send(lst.port, _local())
        _wait(found)
    finally:
        lst.stop()
    assert [f["ip"] for f in found] == ["127.0.0.1"]


def test_loopback_rejected_by_default():
    assert not discovery.valid_ip("127.0.0.1")
    assert discovery.valid_ip("127.0.0.1", allow_loopback=True)
    assert discovery.valid_ip("192.168.1.50")
