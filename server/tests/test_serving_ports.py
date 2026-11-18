"""The fake servers' port picking (tests/fakes/serving.py): the per-worker ranges and the skip of a port somebody listens on."""
import socket

import pytest

from fakes import serving


@pytest.mark.parametrize("low", [None, 49152, 45600, 32768, 30991, 20000, 1024, 100])
def test_range_layout_ends_below_the_ephemeral_range(low):
    start, size = serving.range_layout(low)
    assert size >= 1
    if low is not None and low > 1024 + serving.WORKER_SLOTS:
        assert start + serving.WORKER_SLOTS * size <= low


def test_range_layout_keeps_the_base_when_there_is_room():
    assert serving.range_layout(None) == (20000, 400)
    assert serving.range_layout(49152) == (20000, 400)
    assert serving.range_layout(32768) == (20000, (32768 - 20000) // 64)


def test_bind_stays_inside_the_workers_range(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    start, size = serving.range_layout(serving._ephemeral_low())
    with serving.bind() as sock:
        port = sock.getsockname()[1]
    assert start + 3 * size <= port < start + 4 * size


def test_bind_skips_a_port_another_address_listens_on(monkeypatch):
    """On Windows a bind to 127.0.0.1:P works while 0.0.0.0:P is held by another process; bind() must not return P."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw5")
    start, size = serving.range_layout(serving._ephemeral_low())
    first = start + 5 * size
    foreign = socket.socket()
    for port in range(first, first + size):
        try:
            foreign.bind(("0.0.0.0", port))
        except OSError:
            continue
        break
    else:
        pytest.skip("no free port in the range")
    foreign.listen()
    taken = foreign.getsockname()[1]
    monkeypatch.setattr(serving, "_next", [taken - first])
    try:
        with serving.bind() as sock:
            assert sock.getsockname()[1] != taken
    finally:
        foreign.close()


def test_processes_started_together_do_not_walk_the_same_ports():
    """Separate pytest processes (no xdist) are all worker 0: one starting every walk at the range's first port made
    one process's fake server answer at another's dead address (flaky test_read_spoolman_down_503_refunds_cap)."""
    import subprocess
    import sys
    from pathlib import Path
    code = "from fakes import serving; print(serving._next[0] % serving.range_layout(serving._ephemeral_low())[1])"
    tests = str(Path(__file__).resolve().parent)
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd=tests, stdout=subprocess.PIPE, text=True)
             for _ in range(4)]
    starts = [int(p.communicate(timeout=60)[0]) for p in procs]
    assert len(set(starts)) > 1, starts
