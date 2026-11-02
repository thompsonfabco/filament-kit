"""Cross-process locks: inventory add/placement (FK_STATE/inventory.lock) and the label-read cap (reads.lock).

The two-process tests need fcntl (Linux); on Windows only the in-process behaviour is checked. Run them on WSL.
"""
import json
import multiprocessing as mp
import os
import threading
import time

import pytest

from filament_kit import intake, inventory, locks

try:
    import fcntl  # noqa: F401
    HAVE_FCNTL = True
except ImportError:
    HAVE_FCNTL = False

needs_fcntl = pytest.mark.skipif(not HAVE_FCNTL, reason="fcntl missing (Windows): the file lock is a no-op here")
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 5,
         "overflow": "Overflow", "sealed_location": "Sealed stock"}


def test_inventory_lock_lives_in_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "st"))
    with inventory._LOCK:
        if HAVE_FCNTL:
            assert (tmp_path / "st" / "inventory.lock").exists()
    assert inventory._LOCK.path().name == "inventory.lock"


def test_lock_is_reentrant_and_acquire_timeout(tmp_path):
    lk = locks.ProcessLock(lambda: tmp_path / "x.lock")
    with lk:
        with lk:            # same thread: re-entrant (add_and_link -> add_spools -> link_tag)
            pass
        got = []
        t = threading.Thread(target=lambda: got.append(lk.acquire(timeout=0.2)))
        t.start()
        t.join()
        assert got == [False]   # another thread waits
    assert lk.acquire(timeout=1)
    lk.release()


def test_readcap_uses_reads_lock(tmp_path):
    cap = intake.ReadCap(tmp_path / "state" / "reads.json", 3)
    assert cap._lock.path() == tmp_path / "state" / "reads.lock"
    cap.take()
    if HAVE_FCNTL:
        assert (tmp_path / "state" / "reads.lock").exists()


# ---------- two processes (Linux only) ----------

def _hold(path, ready, hold_s):
    lk = locks.ProcessLock(lambda: path)
    with lk:
        ready.set()
        time.sleep(hold_s)


@needs_fcntl
def test_second_process_waits_for_the_lock(tmp_path):
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    p = ctx.Process(target=_hold, args=(tmp_path / "x.lock", ready, 1.0))
    p.start()
    try:
        assert ready.wait(20)
        lk = locks.ProcessLock(lambda: tmp_path / "x.lock")
        assert not lk.acquire(timeout=0.2)
        t0 = time.monotonic()
        with lk:
            waited = time.monotonic() - t0
        assert waited > 0.3
    finally:
        p.join(20)


def _add_one(url, state, barrier, out):
    os.environ["FK_STATE"] = state
    from filament_kit import inventory as inv
    from filament_kit.spoolman import Spoolman
    sm = Spoolman(url)
    real_post = sm.post

    def slow_post(path, body):          # widen the window between reading free boxes and writing the spool
        time.sleep(0.4)
        return real_post(path, body)

    sm.post = slow_post
    item = {"vendor": "SUNLU", "name": "PETG Grey", "material": "PETG", "net": 1000, "tare": 213,
            "density": 1.27, "count": 1, "sealed": False}
    barrier.wait()
    r = inv.add_spools(sm, [item], RULES, dry=False, parents_checked=True)
    out.put(r.spool_ids[0])


@needs_fcntl
def test_two_processes_adding_never_pick_the_same_box(tmp_path, spoolman_url, spoolman_fake_store):
    """Review focus 3: `web` and `server` adding spools at once never pick the same storage box."""
    from filament_kit.spoolman import Spoolman
    Spoolman(spoolman_url).ensure_fields()
    ctx = mp.get_context("spawn")
    barrier, out = ctx.Barrier(2), ctx.Queue()
    state = str(tmp_path / "shared-state")
    ps = [ctx.Process(target=_add_one, args=(spoolman_url, state, barrier, out)) for _ in range(2)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert all(p.exitcode == 0 for p in ps)
    locs = sorted(s["location"] for s in spoolman_fake_store["spools"].values())
    assert locs == ["Storage box 01", "Storage box 02"], json.dumps(locs)
