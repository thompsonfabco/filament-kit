import logging
import socket
import threading
import time

import pytest
import uvicorn

from fakes import spoolman_fake


@pytest.fixture(autouse=True)
def _restore_app_logger():
    """main() gives the filament_kit logger its own handler and stops propagation; put it back after every test
    so later caplog-based tests still see records, whatever order the tests run in."""
    log = logging.getLogger("filament_kit")
    saved = (list(log.handlers), log.level, log.propagate)
    yield
    log.handlers[:], log.level, log.propagate = saved


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def spoolman_fake_store():
    """In-memory data behind the fake Spoolman; seed or inspect it directly (reset per test)."""
    return spoolman_fake.new_store()


@pytest.fixture
def spoolman_url(spoolman_fake_store):
    sock = socket.socket()      # bound here and handed over: with parallel workers, a port chosen first can be taken before it's used
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(spoolman_fake.app(spoolman_fake_store), log_level="warning"))
    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("fake spoolman did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)
    sock.close()


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    """Tests that read the printer registry indirectly (camera sources pin TLS leaves through it) never touch the
    real /var/lib/filament-kit; a test's own FK_STATE still wins."""
    monkeypatch.setenv("FK_STATE", str(tmp_path / "fk-state"))


@pytest.fixture(autouse=True)
def _library_snapshot(monkeypatch):
    """The program ships no library entries (they are downloaded), so on its first library access in a test's state
    directory (whatever FK_STATE the test chose) the snapshot is installed there as a downloaded copy: the
    production path. Tests of the empty case request the `no_library` fixture."""
    from libsnap import install_snapshot
    from filament_kit import library
    real = library._dir
    done = set()

    def _dir():
        d = real()
        if d not in done:
            done.add(d)
            install_snapshot(d.parent)
        return d

    monkeypatch.setattr(library, "_dir", _dir)
    monkeypatch.setattr(library, "_real_dir", real, raising=False)


@pytest.fixture
def no_library(monkeypatch):
    """A fresh install: nothing downloaded."""
    from filament_kit import library
    monkeypatch.setattr(library, "_dir", library._real_dir)


@pytest.fixture(autouse=True)
def _no_real_kit_paths(tmp_path_factory, monkeypatch):
    """Every test starts with FK_ETC/FK_STATE/FK_OPT in a temp folder, so a test that forgets its own never writes
    (or reads) the real /etc/filament-kit, /var/lib/filament-kit or /opt/filament-kit; on Windows those resolve to
    C:/etc/... and a stray config there changed other tests' builds. Tests that set their own still win."""
    base = tmp_path_factory.mktemp("kit-paths")
    for name in ("etc", "state", "opt"):
        (base / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(base / name))


@pytest.fixture
def moonraker():
    """A running FakeMoonraker (tests/fakes/fake_moonraker.py); `.host`, `.port` set; stopped after the test."""
    from fakes.fake_moonraker import FakeMoonraker
    fake = FakeMoonraker()
    fake.host, fake.port, stop = fake.serve()
    yield fake
    stop()
