"""The PN532 restart lock-up: a stop closes nfcpy first, and an open that times out sets a chip left at a higher
UART speed back to 115200 (station/nfc.py, station/__main__.py). Serial ports and nfcpy are faked."""
import errno
import sys
import threading
import types

import pytest

from filament_kit.station import nfc as station_nfc


@pytest.fixture(autouse=True)
def _fresh_events():
    station_nfc.nfc_stop.clear()
    station_nfc.nfc_idle.set()
    yield
    station_nfc.nfc_stop.clear()
    station_nfc.nfc_idle.set()


class _SerialError(Exception):
    pass


def _fake_serial(answers_at, log):
    """A pyserial stand-in whose PN532 answers SetSerialBaudRate only at `answers_at` baud."""
    class Port:
        def __init__(self, dev, baud, timeout=None):
            self.baud, self.sent = baud, b""
            log.append(("open", dev, baud))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            self.sent += data
            log.append(("write", self.baud, bytes(data)))

        def reset_input_buffer(self):
            pass

        def flush(self):
            pass

        def read(self, n):
            if self.baud == answers_at and station_nfc.PN532_SET_115200 in self.sent:
                return station_nfc.PN532_ACK + station_nfc.PN532_SET_115200_RSP
            return b""

    return types.SimpleNamespace(Serial=Port, SerialException=_SerialError)


def test_tty_of_maps_nfcpy_paths():
    assert station_nfc.tty_of("tty:USB0:pn532") == "/dev/ttyUSB0"
    assert station_nfc.tty_of("tty:ACM1") == "/dev/ttyACM1"
    assert station_nfc.tty_of("usb:054c:06c3") is None
    assert station_nfc.tty_of(None) is None


def test_unwedge_finds_a_chip_left_at_921600_and_acks_its_answer(monkeypatch):
    log = []
    monkeypatch.setitem(sys.modules, "serial", _fake_serial(921600, log))
    assert station_nfc.pn532_unwedge("/dev/ttyUSB0") == 921600
    writes = [w for w in log if w[0] == "write"]
    assert writes[-1] == ("write", 921600, station_nfc.PN532_ACK)  # the closing ACK makes the chip switch speed
    assert [o[2] for o in log if o[0] == "open"] == [921600]


def test_unwedge_tries_each_speed_and_returns_none_when_nothing_answers(monkeypatch):
    log = []
    monkeypatch.setitem(sys.modules, "serial", _fake_serial(None, log))
    assert station_nfc.pn532_unwedge("/dev/ttyUSB0") is None
    assert [o[2] for o in log if o[0] == "open"] == [921600, 460800, 230400, 115200]


def test_unwedge_skips_a_speed_the_port_refuses(monkeypatch):
    log = []
    fake = _fake_serial(115200, log)
    real_port = fake.Serial

    def port(dev, baud, timeout=None):
        if baud == 921600:
            raise _SerialError("speed not supported")
        return real_port(dev, baud, timeout)
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=port, SerialException=_SerialError))
    assert station_nfc.pn532_unwedge("/dev/ttyUSB0") == 115200


def _fake_nfc(monkeypatch, frontend):
    clf_mod = types.SimpleNamespace(RemoteTarget=lambda kind: kind)
    mod = types.SimpleNamespace(ContactlessFrontend=frontend, clf=clf_mod)
    monkeypatch.setitem(sys.modules, "nfc", mod)
    monkeypatch.setitem(sys.modules, "nfc.clf", clf_mod)
    monkeypatch.setattr(station_nfc, "nfc_path", lambda: "tty:USB0:pn532")


def test_stop_closes_nfcpy_and_the_loop_does_not_reopen(monkeypatch):
    events = []

    class Frontend:
        def __init__(self, path):
            events.append("open")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            events.append("close")  # nfcpy's close(): back to 115200
            return False

        def connect(self, rdwr, terminate):
            while not terminate():
                threading.Event().wait(0.01)
            return None
    _fake_nfc(monkeypatch, Frontend)
    t = threading.Thread(target=station_nfc.nfc_loop, daemon=True)
    t.start()
    for _ in range(200):
        if not station_nfc.nfc_idle.is_set():
            break
        threading.Event().wait(0.01)
    assert not station_nfc.nfc_idle.is_set()  # nfcpy holds the reader
    assert station_nfc.stop(timeout=3) is True
    t.join(3)
    assert not t.is_alive()
    assert events == ["open", "close"]


def test_a_timed_out_open_unwedges_and_retries_at_once(monkeypatch):
    opens, unwedged = [], []

    class Frontend:
        def __init__(self, path):
            opens.append(path)
            if len(opens) == 1:
                raise OSError(errno.ETIMEDOUT, "Connection timed out")

        def __enter__(self):
            station_nfc.nfc_stop.set()  # second open worked: end the test
            return self

        def __exit__(self, *a):
            return False

        def connect(self, rdwr, terminate):
            return None
    _fake_nfc(monkeypatch, Frontend)
    monkeypatch.setattr(station_nfc, "pn532_unwedge", lambda dev: unwedged.append(dev) or 921600)
    monkeypatch.setattr(station_nfc.nfc_stop, "wait", lambda t=None: opens.append(("wait", t)))
    station_nfc.nfc_loop()
    assert unwedged == ["/dev/ttyUSB0"]
    assert opens[:2] == ["tty:USB0:pn532", "tty:USB0:pn532"]  # no 5 s pause before the retry


def test_other_open_errors_do_not_try_to_unwedge(monkeypatch):
    class Frontend:
        def __init__(self, path):
            station_nfc.nfc_stop.set()
            raise OSError(errno.ENOENT, "No such file")
    _fake_nfc(monkeypatch, Frontend)
    monkeypatch.setattr(station_nfc, "pn532_unwedge", lambda dev: pytest.fail("must not unwedge"))
    station_nfc.nfc_loop()


def test_sigterm_handler_stops_the_reader_then_exits(monkeypatch):
    from filament_kit.station import __main__ as station_main
    calls = []
    monkeypatch.setattr(station_main.nfc, "stop", lambda: calls.append("stop") or True)
    with pytest.raises(SystemExit) as e:
        station_main.stop_service(15, None)
    assert e.value.code == 0
    assert calls == ["stop"]


def test_a_healthy_chip_at_115200_does_not_skip_the_wait(monkeypatch):
    """The open keeps failing for another reason while the chip answers at 115200: no tight reopen loop."""
    opens = []

    class Frontend:
        def __init__(self, path):
            opens.append(path)
            raise OSError(errno.ENODEV, "No such device")
    _fake_nfc(monkeypatch, Frontend)
    monkeypatch.setattr(station_nfc, "pn532_unwedge", lambda dev: 115200)
    waits = []

    def wait(t=None):
        waits.append(t)
        if len(waits) == 3:
            station_nfc.nfc_stop.set()
    monkeypatch.setattr(station_nfc.nfc_stop, "wait", wait)
    station_nfc.nfc_loop()
    assert waits == [5, 5, 5]
    assert len(opens) == 3


def test_a_stop_during_the_port_lookup_never_opens_the_reader(monkeypatch):
    class Frontend:
        def __init__(self, path):
            pytest.fail("opened after the stop")
    _fake_nfc(monkeypatch, Frontend)
    seen = []

    def path():
        seen.append(station_nfc.nfc_idle.is_set())  # the pass is already marked busy
        station_nfc.nfc_stop.set()
        return "tty:USB0:pn532"
    monkeypatch.setattr(station_nfc, "nfc_path", path)
    station_nfc.nfc_stop.clear()
    t = threading.Thread(target=station_nfc.nfc_loop, daemon=True)
    t.start()
    t.join(3)
    assert seen == [False]
    assert not t.is_alive()
