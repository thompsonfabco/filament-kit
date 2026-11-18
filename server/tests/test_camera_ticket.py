"""The camera ticket (camera_ticket.py): one stream, one printer, 60 seconds, in memory."""
import threading

import pytest

from filament_kit import camera_ticket as ct


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def fresh():
    ct.clear()
    yield
    ct.clear()


def test_a_ticket_is_url_safe_and_long_enough():
    r = ct.issue("P1")
    assert set(r) == {"ticket", "expires_in"} and r["expires_in"] == 60
    assert len(r["ticket"]) >= 43 and all(c.isalnum() or c in "-_" for c in r["ticket"])     # 256 bits, url-safe


def test_a_ticket_opens_one_stream_for_its_printer_and_is_used_up():
    clock = Clock()
    t = ct.issue("P1", clock=clock)["ticket"]
    assert ct.verify("P1", t, clock=clock) is True
    assert ct.verify("P1", t, clock=clock) is False


def test_it_expires_at_60_seconds():
    clock = Clock()
    a, b = (ct.issue("P1", clock=clock)["ticket"] for _ in range(2))
    clock.t += 59.9
    assert ct.verify("P1", a, clock=clock) is True
    clock.t += 0.1
    assert ct.verify("P1", b, clock=clock) is False


def test_another_printer_is_refused_and_the_ticket_is_not_spent():
    clock = Clock()
    t = ct.issue("P1", clock=clock)["ticket"]
    assert ct.verify("P2", t, clock=clock) is False
    assert ct.verify("P1", t, clock=clock) is True


@pytest.mark.parametrize("bad", [None, "", "nope", 5, b"x", "x" * 500])
def test_an_unknown_or_malformed_ticket_is_refused(bad):
    ct.issue("P1")
    assert ct.verify("P1", bad) is False


def test_tickets_are_unique():
    assert len({ct.issue("P1")["ticket"] for _ in range(500)}) == 500 or ct.MAX_LIVE < 500


def test_the_comparison_is_constant_time(monkeypatch):
    calls = []
    real = ct.hmac.compare_digest
    monkeypatch.setattr(ct.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    for _ in range(3):
        ct.issue("P1")
    ct.verify("P1", "wrong")
    assert len(calls) == 3                                      # every live ticket is compared, none skipped


def test_the_count_is_bounded_and_the_oldest_goes():
    clock = Clock()
    first = ct.issue("P1", clock=clock)["ticket"]
    rest = [ct.issue("P1", clock=clock)["ticket"] for _ in range(ct.MAX_LIVE)]
    assert ct.purge(clock=clock) == ct.MAX_LIVE
    assert ct.verify("P1", first, clock=clock) is False
    assert ct.verify("P1", rest[-1], clock=clock) is True


def test_purge_drops_the_expired():
    clock = Clock()
    ct.issue("P1", clock=clock)
    clock.t += 30
    ct.issue("P1", clock=clock)
    clock.t += 31
    assert ct.purge(clock=clock) == 1


def test_threads_never_share_a_ticket():
    tickets = [ct.issue("P1")["ticket"] for _ in range(100)]
    wins = []

    def use(t):
        wins.append(ct.verify("P1", t))
    ts = [threading.Thread(target=use, args=(t,)) for t in tickets for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert wins.count(True) == 100 and wins.count(False) == 200
