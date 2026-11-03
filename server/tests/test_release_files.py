"""Release and packaging files: checked as text (CI files are written and linted here, run on GitHub)."""
import re

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _version(rel: str) -> str:
    m = re.search(r'^__version__ = "([^"]+)"\s*$', _read(rel), re.M)
    assert m, f"no __version__ in {rel}"
    return m.group(1)


def test_release_workflow_triggers_on_version_tags():
    text = _read(".github/workflows/release.yml")
    assert re.search(r"^on:\s*\n\s+push:\s*\n\s+tags:\s*\n\s+-\s*['\"]v\*['\"]", text, re.M)


def test_release_workflow_uses_both_signing_secrets():
    text = _read(".github/workflows/release.yml")
    assert "${{ secrets.FK_KEYSTORE_B64 }}" in text
    assert "${{ secrets.FK_KEYSTORE_PASSWORD }}" in text
    # secrets only ever reach a step through env, never a run line
    for line in text.splitlines():
        if "secrets." in line:
            assert re.match(r"\s+(FK_KEYSTORE(_B64|_PASSWORD)|FK_RELEASE_KEY): "
                            r"\$\{\{ secrets\.(FK_KEYSTORE(_B64|_PASSWORD)|FK_RELEASE_KEY) \}\}$", line), line


def test_release_workflow_builds_sync_on_windows_with_pinned_pyinstaller():
    text = _read(".github/workflows/release.yml")
    assert "windows-2022" in text
    assert "pyinstaller==6.11.1" in text
    assert re.search(r"softprops/action-gh-release@[0-9a-f]{40}  # v2\.", text)


def test_release_workflow_pins_every_action_by_commit():
    """M3: the release jobs hold signing secrets, so every action is a full commit SHA with its tag beside it."""
    text = _read(".github/workflows/release.yml")
    uses = re.findall(r"^\s*- uses: (\S+)(.*)$", text, re.M)
    assert uses
    for ref, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
        assert re.fullmatch(r"\s+# v\d+\.\d+\.\d+", rest), (ref, rest)
    assert "--require-hashes --only-binary :all: -r tools/release-signing-requirements.txt" in text
    req = _read("tools/release-signing-requirements.txt")
    for pkg in ("cryptography==", "cffi==", "pycparser=="):
        assert pkg in req
    assert "--require-hashes --only-binary :all: -r tools/release-build-requirements.txt" in text
    assert "pip install build" not in text
    req = _read("tools/release-build-requirements.txt")
    for pkg in ("build==", "packaging==", "pyproject_hooks=="):
        assert pkg in req
    for path in ("tools/release-signing-requirements.txt", "tools/release-build-requirements.txt"):
        for line in _read(path).splitlines():
            assert not line or line.startswith("#") or re.fullmatch(
                r"[\w-]+==[\w.]+ \\|    --hash=sha256:[0-9a-f]{64}( \\)?", line), line
    assert re.search(r"sha256sum .*\\\n\s+\"filament-kit-sync-setup", text)   # M4: the continuation is kept


def test_pc_sync_workflow():
    text = _read(".github/workflows/pc-sync.yml")
    assert "windows-2022" in text
    assert "pyinstaller==6.11.1" in text
    assert "pc-sync/**" in text


def test_server_workflow_runs_pc_sync_tests():
    text = _read(".github/workflows/server.yml")
    assert "./pc-sync[test]" in text
    assert "pytest pc-sync/tests" in text


def test_installer_is_per_user():
    text = _read("pc-sync/installer/filament-kit-sync.iss")
    assert re.search(r"^PrivilegesRequired=lowest\s*$", text, re.M)
    assert r"DefaultDirName={localappdata}\Programs\filament-kit-sync" in text


def test_installer_adds_app_to_user_path_once_and_removes_it():
    text = _read("pc-sync/installer/filament-kit-sync.iss")
    assert re.search(r"^ChangesEnvironment=yes\s*$", text, re.M)
    reg = [ln for ln in text.splitlines() if ln.startswith("Root: HKCU;")]
    assert len(reg) == 1, reg
    entry = reg[0]
    for part in ('Subkey: "Environment"', 'ValueType: expandsz', 'ValueName: "Path"',
                 'ValueData: "{olddata};{app}"', "Check: NeedsAddPath(ExpandConstant('{app}'))"):
        assert part in entry, part
    assert "uninsdeletevalue" not in entry  # that would delete the user's whole PATH
    assert "function NeedsAddPath(" in text
    assert re.search(r"usUninstall then\s+RemovePath\(ExpandConstant\('\{app\}'\)\)", text)


def test_release_publishes_with_generated_notes():
    assert "generate_release_notes: true" in _read(".github/workflows/release.yml")


def test_task_runs_every_ten_minutes():
    text = _read("pc-sync/installer/install_task.ps1")
    assert "-RepetitionInterval (New-TimeSpan -Minutes 10)" in text
    assert "-MultipleInstances IgnoreNew" in text
    assert "RestartCount" not in text  # no restart on failure: the next 10-minute run retries


def test_server_and_pc_sync_versions_match():
    assert _version("server/filament_kit/__init__.py") == _version("pc-sync/fksync/__init__.py") == "0.2.0"
    # the wheel takes its version from pyproject; make_release.sh looks for the __version__ wheel
    for rel in ("server/pyproject.toml", "pc-sync/pyproject.toml"):
        assert re.search(r'^version = "0\.2\.0"\s*$', _read(rel), re.M), rel


SPOOLMAN_SHA = "bcc961af4c20d7ad7f1740f5609cd3efd94c4556baafaeba5036122dd7e46704"


def test_release_no_grep_q_after_a_pipe():
    # set -o pipefail: `cmd | grep -q` fails when grep exits on the first match and cmd gets SIGPIPE
    text = _read("tools/make_release.sh")
    assert "set -euo pipefail" in text
    assert not re.search(r"\|\s*grep\s+-[a-zA-Z]*q", text)


def test_release_copies_spoolman_script():
    text = _read("tools/make_release.sh")
    assert "install/spoolman.sh" in text
    assert '"$stage/install/spoolman.sh"' in text  # made executable in the stage


def test_release_ships_the_ops_export_script():
    text = _read("tools/make_release.sh")
    assert 'cp tools/export_ops.sh "$stage/install/"' in text
    assert '"$stage/install/export_ops.sh"' in text  # made executable in the stage


def test_install_hands_over_to_modules_apply():
    text = _read("install/install.sh")
    assert "exec /usr/local/bin/filament-kit modules apply" in text
    assert "--mode" in text
    assert "Install mode: 1) server 2) station 3) all-in-one 4) custom [1]" in text
    assert "Server address (name or IP): " in text
    assert '"${WHEEL}[station,web]"' in text
    assert "modules.set_mode" in text


def test_spoolman_sha_only_in_spoolman_script():
    assert SPOOLMAN_SHA not in _read("install/install.sh")
    text = _read("install/spoolman.sh")
    assert f"SPOOLMAN_SHA256={SPOOLMAN_SHA}" in text
    assert "SPOOLMAN_VERSION=v0.27.0" in text
    assert "sha256sum -c" in text
    assert '/etc/systemd/system/spoolman.service' in text


def test_station_extra_in_pyproject():
    text = _read("server/pyproject.toml")
    assert re.search(r'^station = \["nfcpy==1\.0\.4", "pyserial>=3\.5", "esptool==5\.6\.0"\]\s*$', text, re.M)


def test_web_extra_pins_mcp_exactly():
    """filament_kit.web imports MCP SDK internals and install.sh runs `pip install --upgrade`, so a range would pull
    any future SDK: the web extra pins the exact version it was built against."""
    text = _read("server/pyproject.toml")
    assert re.search(r'^web = \["mcp==2\.3\.0"\]', text, re.M)


def test_wrapper_runs_modules_as_root():
    text = _read("install/filament-kit-cli.sh")
    assert re.search(r"^\s+config \| cert \| modules \| remote \| migrate-ops \| update\)\s*$", text, re.M)


def test_wrapper_runs_web_passphrase_as_root():
    """`web passphrase` writes /etc/filament-kit/web_passphrase (root:filament-kit 640) and refuses unless root:
    the wrapper must not drop to the service user for it (other `web` commands still do)."""
    text = _read("install/filament-kit-cli.sh")
    assert re.search(r'^if \[ "\$\{1:-\}" = web \] && \[ "\$\{2:-\}" = passphrase \]; then\s*$', text, re.M)
    i = text.index('= passphrase ]')
    assert 'exec "$BIN" "$@"' in text[i:i + 120]
    assert i < text.index("runuser")


def test_uninstall_uses_modules_units_and_cleans_station():
    text = _read("install/uninstall.sh")
    assert "modules units" in text
    assert "/etc/systemd/system/filament-kit-station.service.d" in text
    assert "/etc/udev/rules.d/99-zz-filament-kit-station.rules" in text
    assert "/etc/udev/rules.d/99-filament-kit-station.rules" in text        # the old name, from before C-I1
    # spec section 4: the station user owns no data, so every uninstall removes it, after its unit is gone
    i_user = text.index("userdel filament-kit-station")
    assert text.index("for u in $UNITS") < i_user < text.index('if [ "$PURGE" -eq 1 ]; then\n    rm -rf')
    purge = text[text.index('if [ "$PURGE" -eq 1 ]; then\n    rm -rf'):]
    assert "for u in filament-kit spoolman; do" in purge


def test_uninstall_removes_the_kits_remote_files():
    """Task 9 (WSL): uninstall left the kit's router conf, its deploy hook and its route (to a port nothing serves
    any more). Like `modules disable remote` (Ruling AF): only the kit's own files; nginx, certbot, the certificate,
    mcp-route and other routes stay. The certbot timer drop-in goes with --purge."""
    from filament_kit import remote
    text = _read("install/uninstall.sh")
    i = text.index("# remote:")
    block = text[i:text.index("rm -rf /opt/filament-kit")]
    for path in (remote.ROUTER_CONF, remote.DEPLOY_HOOK_FILE, remote.KIT_ROUTES):
        assert path in block, path
    assert f"{remote.ROUTE_DIR}/$n.conf" in block and remote.MARK in block       # only routes mcp-route wrote
    assert "nginx -t" in block and "systemctl reload nginx" in block
    purge = text[text.index('if [ "$PURGE" -eq 1 ]; then\n    rm -rf'):]
    assert remote.TIMER_DROPIN in purge


def test_install_server_flag_and_usage():
    text = _read("install/install.sh")
    assert "[--mode server|station|all-in-one | --modules a,b,c [--set KEY=VALUE]...] [--server NAME-OR-IP]" in text
    assert "--server) [ $# -ge 2 ] || usage; SERVER_ADDR=" in text
    assert "--server=*) SERVER_ADDR=" in text
    assert "run again with --server <name-or-IP>" in text
    assert "--modules) [ $# -ge 2 ] || usage; CUSTOM=" in text
    assert "modules menu --raw" in text and "close_selection" in text


def _bash():
    import shutil
    found = shutil.which("bash")
    # Windows' System32 bash.exe is WSL, which cannot take a Windows path; Git Bash can.
    return None if found and "system32" in found.lower() else found


def _install_sh(*args):
    """Run install.sh with no terminal; the cases used here stop during argument checks, before anything else."""
    import subprocess
    return subprocess.run([_bash(), str(ROOT / "install" / "install.sh"), *args], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_station_without_terminal_or_server_fails_early():
    r = _install_sh("--mode", "station")
    assert r.returncode == 1
    assert "station mode needs the kit server's address: run again with --server <name-or-IP>" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
# not a bare "*": on Windows the MSYS runtime would glob it against the working directory
@pytest.mark.parametrize("addr", ["192.168.1.0/24", "nohost*x", "a b"])
def test_install_server_flag_rejects_ranges(addr):
    r = _install_sh("--mode", "station", "--server", addr)
    assert r.returncode == 1 and "--server takes one name or address" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_usage_mentions_server():
    r = _install_sh("--bogus")
    assert r.returncode == 2 and "--server NAME-OR-IP" in r.stderr


def _save_snippet() -> str:
    text = _read("install/install.sh")
    start = text.index("import json, os, sys\nfrom filament_kit import config, modules")
    return text[start:text.index("\n'\n", start)]


def _run_save(tmp_path, mode, modules_csv="", server="", sets="", ai="", existing=None):
    import json
    import os
    import subprocess
    import sys
    etc = tmp_path / "etc"
    etc.mkdir(parents=True, exist_ok=True)
    if existing is not None:
        (etc / "config.json").write_text(json.dumps(existing), encoding="utf-8")
    env = dict(os.environ, FK_ETC=str(etc), FK_MODE=mode, FK_MODULES=modules_csv, FK_SERVER=server, FK_AI=ai, FK_SETS=sets,
               FK_NO_SYSTEMD="1", PYTHONPATH=str(ROOT / "server"))
    r = subprocess.run([sys.executable, "-c", _save_snippet()], env=env, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads((etc / "config.json").read_text(encoding="utf-8"))


def test_install_save_custom_station_without_server_takes_address(tmp_path):
    cfg = _run_save(tmp_path, "custom", ",station", server="spoolman.home.arpa")
    assert cfg["modules"]["station"] and not cfg["modules"]["server"]
    assert cfg["station"]["allow"] == ["spoolman.home.arpa"]
    assert "server_name" not in cfg  # apply asks the first-run questions


def test_install_save_custom_station_with_server_is_local(tmp_path):
    cfg = _run_save(tmp_path, "custom", ",spoolman,server,station")
    assert cfg["station"]["allow"] == ["127.0.0.1"]
    assert cfg["station"]["url"] == "http://127.0.0.1:5003"


def test_install_save_station_mode_with_server(tmp_path):
    cfg = _run_save(tmp_path, "station", server="192.0.2.10")
    assert cfg["modules"] == {n: n == "station" for n in cfg["modules"]}
    assert cfg["station"]["allow"] == ["192.0.2.10"]


def test_install_apt_waits_for_the_dpkg_lock():
    # a fresh Ubuntu often runs unattended-upgrades right after boot; apt must wait, not fail
    calls = [ln for ln in _read("install/install.sh").splitlines()
             if ln.strip().startswith("apt-get")]
    assert calls and all("DPkg::Lock::Timeout=" in ln for ln in calls)


def test_install_save_custom_adds_what_modules_need(tmp_path):
    cfg = _run_save(tmp_path, "custom", ",spoolman,printers")
    assert cfg["modules"]["server"] and cfg["modules"]["printers"]


def _install_part(start_marker, end_marker):
    text = _read("install/install.sh")
    a = text.index(start_marker)
    return text[a:text.index(end_marker, a)]


def _stub_venv(tmp_path, kit_body=None):
    """A fake $VENV: bin/python runs the test interpreter; bin/filament-kit runs `kit_body` if given."""
    import os
    import stat
    import sys
    b = tmp_path / "venv" / "bin"
    b.mkdir(parents=True)
    py = b / "python"
    py.write_text(f'#!/bin/sh\nexec "{sys.executable.replace(chr(92), "/")}" "$@"\n', newline="\n")
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    if kit_body is not None:
        kit = b / "filament-kit"
        kit.write_text("#!/bin/sh\n" + kit_body + "\n", newline="\n")
        kit.chmod(kit.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "server"))
    return tmp_path / "venv", env


def _run_part(script, venv, env, tmp_path):
    import subprocess
    f = tmp_path / "part.sh"
    f.write_text(script, newline="\n")
    return subprocess.run([_bash(), str(f)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=60, env=dict(env, VENV=str(venv).replace(chr(92), "/")))


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_modules_closed_before_address_check(tmp_path):
    # --modules station,printers: printers pulls in the server, so no server address is needed (no terminal here)
    venv, env = _stub_venv(tmp_path)
    part = _install_part("# A custom list is closed first", '[ "$NEED_ADDR" -eq 1 ] || SERVER_ADDR=""')
    script = ('die() { echo "error: $*" >&2; exit 1; }\nbad_addr() { return 1; }\n'
              'MODE=custom\nCUSTOM=",station,printers"\nSERVER_ADDR=""\n' + part +
              'echo "NEED=$NEED_ADDR CUSTOM=$CUSTOM"\n')
    r = _run_part(script, venv, env, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "NEED=0 CUSTOM=,server,printers,station" in r.stdout
    assert "also turned on" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_modules_station_alone_still_needs_address_without_terminal(tmp_path):
    venv, env = _stub_venv(tmp_path)
    part = _install_part("# A custom list is closed first", '[ "$NEED_ADDR" -eq 1 ] || SERVER_ADDR=""')
    script = ('die() { echo "error: $*" >&2; exit 1; }\nbad_addr() { return 1; }\n'
              'MODE=custom\nCUSTOM=",station"\nSERVER_ADDR=""\n' + part)
    r = _run_part(script, venv, env, tmp_path)
    assert r.returncode == 1 and "needs the kit server's address" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_modules_unknown_name_fails(tmp_path):
    venv, env = _stub_venv(tmp_path)
    part = _install_part("# A custom list is closed first", "# A station whose server is on another machine")
    r = _run_part('MODE=custom\nCUSTOM=",bogus"\n' + part, venv, env, tmp_path)
    assert r.returncode == 1 and "unknown module 'bogus'" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_mode_custom_is_rejected():
    r = _install_sh("--mode", "custom")
    assert r.returncode == 1 and "--modules" in r.stderr and "unknown mode 'custom'" in r.stderr



@pytest.mark.skipif(not _bash(), reason="needs bash")
@pytest.mark.parametrize("body, rc, expect", [
    ('echo "spoolman,server,backup"', 0, "CUSTOM=,spoolman,server,backup SETS= ADDR="),
    ('printf "web,server\\nset web.public_url=https://a.example.com/f\\nset orders.file=/o=1.json\\n"', 0,
     "CUSTOM=,web,server SETS=set web.public_url=https://a.example.com/f|set orders.file=/o=1.json ADDR="),
    ('printf "station\\nset station.allow=srv.localdomain\\n"', 0,
     "CUSTOM=,station SETS=set station.allow=srv.localdomain ADDR=srv.localdomain"),
    ("exit 1", 1, "no modules chosen"),
])
def test_install_menu_wrapper_cancel_and_choice(tmp_path, body, rc, expect):
    venv, env = _stub_venv(tmp_path, body)
    text = _read("install/install.sh")
    a = text.index('        MENU_OUT=$("$VENV/bin/filament-kit" modules menu --raw)')
    b = text.index("\n", text.index('[ -z "$SERVER_ADDR" ] && SERVER_ADDR=', a))
    wrapper = text[a:b].strip()
    script = ('die() { echo "error: $*" >&2; exit 1; }\nSERVER_ADDR=""\n' + wrapper +
              '\necho "CUSTOM=$CUSTOM SETS=$(printf \'%s\' "$SETS" | tr \'\\n\' \'|\') ADDR=$SERVER_ADDR"\n')
    r = _run_part(script, venv, env, tmp_path)
    assert r.returncode == rc
    assert expect in (r.stdout if rc == 0 else r.stderr)


def test_install_save_applies_menu_settings(tmp_path):
    sets = "set web.public_url=https://mcp.example.com/filament" + chr(10) + "set orders.file=/srv/o.json"
    cfg = _run_save(tmp_path, "custom", ",spoolman,server,ai_intake,web,orders", sets=sets)
    assert cfg["web"]["public_url"] == "https://mcp.example.com/filament"
    assert cfg["web"]["lan"] and cfg["orders"]["file"] == "/srv/o.json"
    assert cfg["modules"]["web"] and cfg["modules"]["orders"]


def test_install_save_new_server_has_ai_intake_off_unless_chosen(tmp_path):
    """R1: a new install has AI label reading off; the first-install question (FK_AI) turns it on."""
    assert _run_save(tmp_path / "a", "server")["modules"]["ai_intake"] is False
    assert _run_save(tmp_path / "b", "all-in-one", ai="1")["modules"]["ai_intake"] is True


def test_install_save_mode_on_a_legacy_install_keeps_ai_intake(tmp_path):
    """An install from before modules (no `modules` key) had AI intake: `--mode` on its upgrade keeps it."""
    cfg = _run_save(tmp_path, "server", existing={"server_name": "fk", "port": 8443})
    assert cfg["modules"]["ai_intake"] is True and cfg["server_name"] == "fk"


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_set_refuses_other_keys():
    r = _install_sh("--modules", "web", "--set", "web.port=1")
    assert r.returncode == 1
    assert "web.public_url" in r.stderr and "orders.file" in r.stderr and "station.allow" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_set_needs_modules():
    r = _install_sh("--mode", "server", "--set", "orders.file=/x")
    assert r.returncode == 1 and "--set goes with --modules" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_set_is_collected_and_station_address_feeds_server_addr(tmp_path):
    # the argument block alone: repeated --set, station.allow becomes the server address
    text = _read("install/install.sh")
    a = text.index("# --set KEY=VALUE")
    b = text.index("# Checked before anything is installed")
    script = ('die() { echo "error: $*" >&2; exit 1; }\nusage() { exit 2; }\nbad_addr() { return 1; }\n'
              + text[a:b] + 'echo "MODE=$MODE SERVER=$SERVER_ADDR"; printf "%s\n" "$SETS"\n')
    f = tmp_path / "args.sh"
    f.write_text(script, newline="\n")
    import subprocess
    r = subprocess.run([_bash(), str(f), "--modules", "web,station", "--set", "web.public_url=https://m.example.com/f",
                        "--set=station.allow=srv.localdomain"], capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["MODE=custom SERVER=srv.localdomain",
                                     "set web.public_url=https://m.example.com/f",
                                     "set station.allow=srv.localdomain"]


def test_install_save_rejects_bad_set_value(tmp_path):
    import os
    import subprocess
    import sys
    etc = tmp_path / "etc"
    etc.mkdir()
    env = dict(os.environ, FK_ETC=str(etc), FK_MODE="custom", FK_MODULES=",spoolman,server,ai_intake,web",
               FK_SERVER="", FK_AI="", FK_SETS="set web.public_url=http://nope", FK_NO_SYSTEMD="1",
               PYTHONPATH=str(ROOT / "server"))
    r = subprocess.run([sys.executable, "-c", _save_snippet()], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "web.public_url" in r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_unknown_module_name_is_caught_before_packages(tmp_path):
    import subprocess
    import zipfile
    whl = tmp_path / "filament_kit-0.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("filament_kit/modules.py", (ROOT / "server" / "filament_kit" / "modules.py").read_text("utf-8"))
    part = _install_part("# --modules names are checked now", "FIRST_INSTALL=1")
    f = tmp_path / "early.sh"
    f.write_text(f'MODE=custom\nWHEEL="{str(whl).replace(chr(92), "/")}"\nCUSTOM="$1"\n' + part + 'echo passed\n',
                 newline="\n")
    import os
    import sys
    venv, env = _stub_venv(tmp_path)                 # its bin/python runs the test interpreter
    shim = tmp_path / "shim"
    shim.mkdir()
    exe = sys.executable.replace(chr(92), "/")
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{exe}" "$@"\n', newline="\n")
    env = dict(os.environ, PATH=str(shim).replace(chr(92), "/") + os.pathsep + os.environ["PATH"])
    ok = subprocess.run([_bash(), str(f), ",spoolman,server"], capture_output=True, text=True, timeout=30, env=env)
    bad = subprocess.run([_bash(), str(f), ",server,bogus"], capture_output=True, text=True, timeout=30, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stderr
    assert bad.returncode != 0 and "unknown module bogus" in bad.stderr and "passed" not in bad.stdout


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_install_set_station_allow_refused_when_server_in_list(tmp_path):
    import subprocess
    part = _install_part("# With the server on this machine", "# A station whose server")
    f = tmp_path / "m.sh"
    f.write_text('die() { echo "error: $*" >&2; exit 1; }\nMODE=custom\nCUSTOM="$1"\nSETS="set station.allow=x"\n'
                 + part + 'echo passed\n', newline="\n")
    bad = subprocess.run([_bash(), str(f), ",station,server"], capture_output=True, text=True, timeout=30)
    ok = subprocess.run([_bash(), str(f), ",station"], capture_output=True, text=True, timeout=30)
    assert bad.returncode == 1 and "drop --set station.allow" in bad.stderr
    assert ok.returncode == 0


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_station_upgrade_without_server_reuses_the_saved_address(tmp_path):
    """The updater (or get.sh piped to bash) runs install.sh with no terminal: a station upgrade given --mode station
    but no --server takes the server address the station already has (station.allow in its config.json) instead
    of dying for it. It then stops at the root check here, past the address check."""
    import json
    import os
    import subprocess
    import sys
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "config.json").write_text(json.dumps({"modules": {"station": True, "server": False},
                                                 "station": {"allow": ["127.0.0.1", "kit.localdomain"]}}),
                                     encoding="utf-8")
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8")
    (shim / "python3").chmod(0o755)
    env = {**os.environ, "FK_ETC": str(etc)}
    bash_path = subprocess.run([_bash(), "-c", "cygpath -u \"$1\" 2>/dev/null || printf %s \"$1\"", "_", str(shim)],
                               capture_output=True, text=True).stdout.strip()
    r = subprocess.run([_bash(), "-c", f'PATH="{bash_path}:$PATH" exec bash "$0" "$@"',
                        str(ROOT / "install" / "install.sh"), "--mode", "station"],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, env=env)
    assert "needs the kit server's address" not in r.stderr, r.stderr
    assert r.returncode == 1 and "run as root" in r.stderr, r.stderr
    (etc / "config.json").write_text(json.dumps({"station": {"allow": ["127.0.0.1"]}}), encoding="utf-8")
    r = subprocess.run([_bash(), "-c", f'PATH="{bash_path}:$PATH" exec bash "$0" "$@"',
                        str(ROOT / "install" / "install.sh"), "--mode", "station"],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, env=env)
    assert "station mode needs the kit server's address" in r.stderr     # only a local address saved: still asks
