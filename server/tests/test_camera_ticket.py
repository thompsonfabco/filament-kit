"""The camera ticket and camera session (camera_ticket.py): R83 20:58 and 22:10."""
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


def open_session(printer="P1", clock=None):
    return ct.use_ticket(printer, ct.issue(printer, clock=clock)["ticket"], clock=clock)


def test_a_ticket_is_url_safe_and_long_enough():
    r = ct.issue("P1")
    assert set(r) == {"ticket", "expires_in"} and r["expires_in"] == 60
    assert len(r["ticket"]) >= 43 and all(c.isalnum() or c in "-_" for c in r["ticket"])     # 256 bits, url-safe


def test_the_first_use_spends_the_ticket_and_opens_a_session():
    clock = Clock()
    t = ct.issue("P1", clock=clock)["ticket"]
    sid = ct.use_ticket("P1", t, clock=clock)
    assert isinstance(sid, str) and len(sid) >= 43 and sid != t
    assert ct.use_ticket("P1", t, clock=clock) is None                  # a second use fails
    assert ct.verify_session("P1", sid, clock=clock) is True


def test_the_ticket_expires_at_60_seconds():
    clock = Clock()
    a, b = (ct.issue("P1", clock=clock)["ticket"] for _ in range(2))
    clock.t += 59.9
    assert ct.use_ticket("P1", a, clock=clock) is not None
    clock.t += 0.1
    assert ct.use_ticket("P1", b, clock=clock) is None


def test_a_ticket_of_another_printer_is_refused_and_not_spent():
    clock = Clock()
    t = ct.issue("P1", clock=clock)["ticket"]
    assert ct.use_ticket("P2", t, clock=clock) is None
    assert ct.use_ticket("P1", t, clock=clock) is not None


@pytest.mark.parametrize("bad", [None, "", "nope", 5, b"x", "x" * 500])
def test_an_unknown_or_malformed_ticket_or_session_is_refused(bad):
    ct.issue("P1")
    open_session()
    assert ct.use_ticket("P1", bad) is None and ct.verify_session("P1", bad) is False


def test_a_session_moves_forward_with_every_request_and_ends_after_10_idle_minutes():
    clock = Clock()
    sid = open_session(clock=clock)
    for _ in range(5):
        clock.t += 599
        assert ct.verify_session("P1", sid, clock=clock) is True         # each request starts the 10 minutes again
    clock.t += 600
    assert ct.verify_session("P1", sid, clock=clock) is False


def test_a_session_without_requests_ends_at_exactly_600_seconds():
    clock = Clock()
    sid = open_session(clock=clock)
    clock.t += 599.9
    assert ct.verify_session("P1", sid, clock=clock) is True
    clock.t += 600
    assert ct.verify_session("P1", sid, clock=clock) is False
    assert ct.purge(clock=clock) == 0


def test_a_session_is_only_for_its_printer():
    sid = open_session("P1")
    assert ct.verify_session("P2", sid) is False and ct.verify_session("P1", sid) is True
    assert ct.close_session("P2", sid) == {"closed": True}               # not its printer: left alone
    assert ct.verify_session("P1", sid) is True


def test_close_ends_the_session_and_closing_twice_is_fine():
    sid = open_session()
    assert ct.close_session("P1", sid) == {"closed": True}
    assert ct.verify_session("P1", sid) is False
    assert ct.close_session("P1", sid) == {"closed": True} and ct.close_session("P1", None) == {"closed": True}


def test_the_ninth_ticket_is_refused_with_the_exact_text():
    clock = Clock()
    for i in range(8):
        open_session(f"P{i}", clock)
    with pytest.raises(ct.TooManyViews) as e:
        ct.issue("P9", clock=clock)
    assert str(e.value) == "Too many camera views are open. Close one first."
    assert ct.sessions_open(clock=clock) == 8


def test_a_ticket_issued_before_the_limit_is_kept_when_the_ninth_use_is_refused():
    clock = Clock()
    t = ct.issue("P9", clock=clock)["ticket"]                            # asked while there was room
    for i in range(8):
        open_session(f"P{i}", clock)
    with pytest.raises(ct.TooManyViews, match="Close one first"):
        ct.use_ticket("P9", t, clock=clock)
    sid = next(iter(ct._sessions))
    ct.close_session(ct._sessions[sid][0], sid, clock=clock)             # a view is closed ...
    assert ct.use_ticket("P9", t, clock=clock) is not None               # ... and the same ticket now works


def test_drop_printer_ends_its_tickets_and_sessions_only():
    keep = open_session("P2")
    gone = open_session("P1")
    ticket = ct.issue("P1")["ticket"]
    other = ct.issue("P2")["ticket"]
    assert ct.drop_printer("P1") == 2
    assert ct.verify_session("P1", gone) is False and ct.use_ticket("P1", ticket) is None
    assert ct.verify_session("P2", keep) is True and ct.use_ticket("P2", other) is not None


def test_a_restart_is_a_new_module_state():
    import importlib
    sid = open_session()
    importlib.reload(ct)
    assert ct.verify_session("P1", sid) is False and ct.sessions_open() == 0


def test_the_cookie_is_a_session_cookie_as_ruled():
    c = ct.session_cookie("P 1/x", "abc")
    assert c == {"name": "fk_setup_camera", "value": "abc", "path": "/setup/api/printers/P%201%2Fx/camera",
                 "http_only": True, "secure": True, "same_site": "Strict"}
    h = ct.set_cookie_header("P1", "abc")
    assert h == "fk_setup_camera=abc; Path=/setup/api/printers/P1/camera; HttpOnly; Secure; SameSite=Strict"
    assert "max-age" not in h.lower() and "expires" not in h.lower() and "max_age" not in c and "expires" not in c
    assert ct.set_cookie_header("P1", "abc", closing=True) == (
        "fk_setup_camera=; Path=/setup/api/printers/P1/camera; Max-Age=0; HttpOnly; Secure; SameSite=Strict")


def test_a_view_kept_alive_for_25_minutes_is_still_valid_and_ends_10_idle_minutes_after_the_last_request():
    clock = Clock()
    sid = open_session(clock=clock)
    for _ in range(25):
        clock.t += 60
        assert ct.verify_session("P1", sid, clock=clock) is True
    clock.t += 599
    assert ct.verify_session("P1", sid, clock=clock) is True             # still inside 10 idle minutes (and renewed)
    clock.t += 600
    assert ct.verify_session("P1", sid, clock=clock) is False


def test_tickets_and_sessions_are_unique_and_the_comparison_is_constant_time(monkeypatch):
    assert len({ct.issue("P1")["ticket"] for _ in range(200)}) == 200
    ct.clear()
    calls = []
    real = ct.hmac.compare_digest
    monkeypatch.setattr(ct.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    for _ in range(3):
        ct.issue("P1")
    ct.use_ticket("P1", "wrong")
    assert len(calls) == 3                                               # every live ticket is compared


def test_the_ticket_count_is_bounded_and_the_oldest_goes():
    clock = Clock()
    first = ct.issue("P1", clock=clock)["ticket"]
    rest = [ct.issue("P1", clock=clock)["ticket"] for _ in range(ct.MAX_LIVE)]
    assert ct.purge(clock=clock) == ct.MAX_LIVE
    assert ct.use_ticket("P1", first, clock=clock) is None
    assert ct.use_ticket("P1", rest[-1], clock=clock) is not None


def test_threads_never_share_a_ticket():
    tickets = [ct.issue("P1")["ticket"] for _ in range(100)]
    wins = []

    def use(t):
        try:
            wins.append(ct.use_ticket("P1", t) is not None)
        except ct.TooManyViews:
            wins.append(False)
    ts = [threading.Thread(target=use, args=(t,)) for t in tickets for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert wins.count(True) == ct.MAX_SESSIONS and ct.sessions_open() == ct.MAX_SESSIONS
