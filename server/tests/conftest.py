import logging
import os
import platform
import socket

import pytest

from fakes import spoolman_fake


@pytest.fixture(autouse=True)
def _restore_app_logger():
    """main() gives the filament_kit logger its own handler and stops propagation; put it back after every test
    so later caplog-based tests still see records, whatever order the tests run in."""
    log = logging.getLogger("filament_kit")
    saved = (list(log.handlers), log.level, log.propagate)
    yield
    log.handlers[:], log.level, log.propagate = saved


HOST_NAME = "workshop-hub"


@pytest.fixture(autouse=True)
def _made_up_host_name(monkeypatch):
    """No test sees this machine's real host name (it is owner data, and a test that asserted it passed on one PC
    only): every lookup the server code uses answers `workshop-hub`. A test that needs another name sets its own."""
    from filament_kit import config
    monkeypatch.setattr(socket, "gethostname", lambda: HOST_NAME)
    monkeypatch.setattr(socket, "getfqdn", lambda name="": HOST_NAME)
    monkeypatch.setattr(platform, "node", lambda: HOST_NAME)
    real_getaddrinfo, real_gethostbyname = socket.getaddrinfo, socket.gethostbyname
    # the made-up name resolves here, at once, as a machine's own name does (no DNS wait in any test)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: real_getaddrinfo(
        "127.0.0.1" if str(host).lower() in (HOST_NAME, HOST_NAME + ".local") else host, *a, **k))
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1" if str(host).lower() in (HOST_NAME, HOST_NAME + ".local")
                        else real_gethostbyname(host))
    monkeypatch.setitem(config.DEFAULTS, "server_name", HOST_NAME)    # read once, when config was imported
    if hasattr(os, "uname"):
        real = os.uname()
        monkeypatch.setattr(os, "uname", lambda: os.uname_result((real.sysname, HOST_NAME, *real[2:])))


@pytest.fixture(autouse=True)
def _roomy_disk_for_alerts(monkeypatch):
    """The status rows and the alert code measure the disk (alerts.py, EA3): no test result may depend on how full the
    machine running it is. Only calls made from alerts.py see a roomy disk; every other caller gets the real answer, and a
    test that wants a full disk sets `alerts.shutil.disk_usage` itself (the later patch wins)."""
    import shutil
    import sys
    from collections import namedtuple
    real, usage = shutil.disk_usage, namedtuple("usage", "total used free")

    def disk_usage(path):
        if sys._getframe(1).f_globals.get("__name__") == "filament_kit.alerts":
            return usage(1000 * 1000 ** 3, 100 * 1000 ** 3, 900 * 1000 ** 3)
        return real(path)
    monkeypatch.setattr(shutil, "disk_usage", disk_usage)


@pytest.fixture(autouse=True)
def _no_real_journal(monkeypatch):
    """No test writes audit lines into the machine's real journal (/dev/log on Linux and CI): a test that checks the
    journal route patches `cli._journal_address` itself."""
    from filament_kit import cli
    monkeypatch.setattr(cli, "_journal_address", lambda: None)


# The places the server code writes on a real machine. Resolved per OS: on Windows "/etc" is C:\etc, which is where a
# test once left a real drop-in file.
SYSTEM_ROOTS = ("/etc", "/var/lib", "/var/backups", "/usr", "/opt", "/run")


def _system_path(path) -> bool:
    try:
        text = os.path.normcase(os.path.abspath(os.fsdecode(path)))
    except (TypeError, ValueError):
        return False
    for root in SYSTEM_ROOTS:
        root = os.path.normcase(os.path.abspath(root))
        if text == root or text.startswith(root + os.sep):
            return True
    return False


@pytest.fixture(autouse=True)
def system_writes(request, monkeypatch, tmp_path_factory):
    """No test writes outside its temp dirs. `apply.execute` and `refresh_station` default to a temp dir as their root
    (they default to `/`), and every write to a system path (/etc, /var/lib, /usr, /opt, /run ...) is refused and
    recorded; the test then fails at its end, naming each one. The list is this fixture's value: a test that
    plants a write on purpose empties it. A root-only test that works on real system paths on purpose (testenv --root)
    carries `@pytest.mark.real_system_paths("reason")` and is not guarded; the marker fails the test when it is not
    running as root."""
    import builtins
    import io
    from filament_kit import apply
    root = tmp_path_factory.mktemp("sysroot")
    for fn in (apply.execute, apply.refresh_station):
        monkeypatch.setitem(fn.__kwdefaults__, "root", root)
    attempts: list[str] = []
    marker = request.node.get_closest_marker("real_system_paths")
    if marker is not None:
        if not (hasattr(os, "geteuid") and os.geteuid() == 0):
            pytest.fail("real_system_paths is for tests that run as root: " + str(marker.args[:1] or "no reason given"))
        yield attempts
        return

    def refuse(what, path):
        attempts.append(f"{what} {path}")
        raise PermissionError(f"test guard: a test must not write to the system path {path}")

    real_open, real_replace, real_rename, real_mkdir = io.open, os.replace, os.rename, os.mkdir

    def guarded_open(file, mode="r", *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)) and any(c in str(mode) for c in "wax+") and _system_path(file):
            refuse("open", file)
        return real_open(file, mode, *a, **k)

    def guarded_replace(src, dst, *a, **k):
        if _system_path(dst):
            refuse("replace", dst)
        return real_replace(src, dst, *a, **k)

    def guarded_rename(src, dst, *a, **k):
        if _system_path(dst):
            refuse("rename", dst)
        return real_rename(src, dst, *a, **k)

    def guarded_mkdir(path, *a, **k):
        if _system_path(path):
            refuse("mkdir", path)
        return real_mkdir(path, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(os, "replace", guarded_replace)
    monkeypatch.setattr(os, "rename", guarded_rename)
    monkeypatch.setattr(os, "mkdir", guarded_mkdir)
    yield attempts
    assert not attempts, "the test wrote to the system path(s): " + "; ".join(attempts)


@pytest.fixture(autouse=True)
def _command_line_output(monkeypatch):
    """What the command line writes (glyphs, colour, width) is the same on every machine: ASCII glyphs, no colour,
    80 columns, a colour-capable terminal type (colour then follows the stream, as on a real machine, whatever TERM the
    tests run under), and the switches of the last run forgotten."""
    from filament_kit import output
    for name in ("NO_COLOR", "SPOOLWARDEN_PLAIN", "LC_ALL", "LC_CTYPE", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "ascii")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("TERM", "xterm")
    output.reset()
    yield
    output.reset()


@pytest.fixture
def secret_terminal(monkeypatch):
    """Standard input counts as a terminal for the secret prompts: they then go to getpass (which the test replaces).
    Without it a secret prompt reads the next line of standard input, as it does when piped."""
    import sys
    from filament_kit import secret_input
    monkeypatch.setattr(secret_input, "_isatty", lambda stream: stream is sys.stdin)


def old_rows(out: str) -> list[str]:
    """`status` output as the lines it had before S5.1 (`OK   text`, `FAIL text`, `     fix: ...`, `--   text`), so a test
    of what a row says need not know the heading, glyph and wrapping of the new layout. The header, the group headings
    and the summary are left out; a row wrapped at the width is joined again. Any other line is an AssertionError, so a
    stray line, a wrong word or a row that lost its layout fails the test that reads the output through here."""
    import re
    from filament_kit import status
    mark = {"OK": "OK   ", "needs a look": "FAIL ", "note": "--   "}
    rows: list[str] = []
    for n, line in enumerate(l for l in out.splitlines() if l.strip()):
        m = re.match(r"^(?:  [+!*o~x] |)([A-Za-z][A-Za-z ]*?)(?: {2,}|$)(.*)$", line)
        if line.startswith("  ") and not line.startswith(" " * 5) and m and m[1] in mark:
            rows.append(mark[m[1]] + m[2])
        elif line.startswith(" " * 18) and rows:
            text = line.strip()
            if text.startswith("Fix: "):
                rows.append("     fix: " + text[5:])
            else:
                rows[-1] += " " + text
        elif line in status.GROUPS or re.fullmatch(r"\d+ (?:needs? a look|OK|notes?)(?: - \d+ (?:needs? a look|OK|notes?))*", line) or (
                n == 0 and re.match(r"Spoolwarden \S+ - ", line)):
            continue
        else:
            raise AssertionError(f"a status line that is no row, heading, header or summary: {line!r}")
    return rows


def free_port() -> int:
    from fakes import serving
    return serving.free_port()


@pytest.fixture
def dead_port():
    """A port nothing can answer for the whole test: a socket bound and never listening, so a connection is refused
    and no other process (pytest runs side by side, and their fake servers draw from the same ports) can take it."""
    from fakes import serving
    sock = serving.bind()
    yield sock.getsockname()[1]
    sock.close()


@pytest.fixture
def spoolman_fake_store():
    """In-memory data behind the fake Spoolman; seed or inspect it directly (reset per test)."""
    return spoolman_fake.new_store()


@pytest.fixture
def spoolman_url(spoolman_fake_store):
    yield from _serve(spoolman_fake.app(spoolman_fake_store))


def _serve(asgi):
    """Serve `asgi` on a free 127.0.0.1 port in a thread (fakes.serving); yields its URL."""
    from fakes import serving
    running = serving.start(asgi)
    try:
        yield running.url
    finally:
        running.stop()


@pytest.fixture
def fake_reader():
    """The fake local label reader: (url, data); change `data` (local_reader_fake.new_data) to steer it."""
    from fakes import local_reader_fake
    data = local_reader_fake.new_data()
    for url in _serve(local_reader_fake.app(data)):
        yield url, data


@pytest.fixture(autouse=True)
def _no_real_spoolman_for_the_storage_screens(monkeypatch):
    """`config` and `config show` ask Spoolman how full the storage locations are; a test never reaches a real one."""
    from filament_kit import locations_cli

    class NoSpools:
        def get(self, path):
            return []
    monkeypatch.setattr(locations_cli, "default_spoolman", lambda: NoSpools())


@pytest.fixture(autouse=True)
def _one_job_per_test(monkeypatch):
    """Each test is its own job for steps.py: no step owner in the environment and no Steps made yet (a real job is
    one process; the tests run many commands in one)."""
    from filament_kit import steps
    monkeypatch.delenv(steps.ENV, raising=False)
    monkeypatch.setattr(steps, "_made_here", False)


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


@pytest.fixture(autouse=True)
def _no_running_kit_server(monkeypatch):
    """`printer map` and `printer report` ask a running kit server first (cli._server_api). A test is never served by
    whatever kit may run on this machine: no server, unless the test sets up its own."""
    from filament_kit import cli
    monkeypatch.setattr(cli, "_server_api", lambda: None)
