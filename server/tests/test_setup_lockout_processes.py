"""Several processes share one lockout file: none raises and no wrong code is lost (Windows has no flock)."""
from __future__ import annotations

import multiprocessing as mp

from filament_kit import setup_code

PROCS, TRIES = 6, 30


def _worker(path: str, n: int, q) -> None:
    try:
        lock = setup_code.Lockout(path, max_fails=10 ** 6, global_max=10 ** 6)
        for _ in range(TRIES):
            assert lock.attempt(f"client-{n}") is not None
            lock.standing(f"client-{n}")
        q.put(None)
    except BaseException as exc:  # reported to the parent
        q.put(f"{type(exc).__name__}: {exc}")


def test_concurrent_processes_lose_no_attempt(tmp_path):
    path = tmp_path / "setup_lockout.xml"
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(str(path), n, q)) for n in range(PROCS)]
    for p in procs:
        p.start()
    errors = [q.get(timeout=120) for _ in procs]
    for p in procs:
        p.join(60)
    assert [e for e in errors if e] == []
    st = setup_code.Lockout._parse(path.read_bytes())
    assert len(st["fails"]) == PROCS * TRIES
