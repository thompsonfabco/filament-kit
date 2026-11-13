"""Release and packaging files: checked as text (CI files are written and linted here, run on GitHub)."""
import functools
import re
import subprocess
import sys

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
    # (the one exception: actions/checkout's `token` input for the private filament-library, Ruling BU)
    for line in text.splitlines():
        if "secrets." in line:
            assert (re.match(r"\s+(FK_KEYSTORE(_B64|_PASSWORD)|FK_RELEASE_KEY|FK_LIBRARY_TOKEN): "
                             r"\$\{\{ secrets\.(FK_KEYSTORE(_B64|_PASSWORD)|FK_RELEASE_KEY|FK_LIBRARY_TOKEN) \}\}$",
                             line)
                    or re.match(r"\s+token: \$\{\{ secrets\.FK_LIBRARY_TOKEN( \|\| github\.token)? \}\}$", line)), line


def test_release_workflow_builds_sync_on_windows_with_pinned_pyinstaller():
    text = _read(".github/workflows/release.yml")
    assert "windows-2022" in text
    assert "--require-hashes --only-binary :all: -r tools/release-sync-requirements.txt" in text
    assert "pyinstaller==6.11.1 \\" in _read("tools/release-sync-requirements.txt")
    assert "choco install innosetup --version=" in text
    assert re.search(r"softprops/action-gh-release@[0-9a-f]{40}  # v2\.", text)


def test_release_workflow_pins_every_action_by_commit():
    """M3: the release jobs hold signing secrets, so every action is a full commit SHA with its tag beside it."""
    text = _read(".github/workflows/release.yml")
    uses = re.findall(r"^\s*(?:- )?uses: (\S+)(.*)$", text, re.M)      # `- name: X` then `uses:` is a step too
    assert uses and len(uses) == len([ln for ln in text.splitlines() if "uses:" in ln and not ln.lstrip().startswith("#")])
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
    # M4: the sync installer is summed (one assets line now; test_release_workflow_sums_step_runs runs it)
    assert re.search(r'assets="[^"]*filament-kit-sync-setup-\$VERSION\.exe', text)


def test_pc_sync_workflow():
    text = _read(".github/workflows/pc-sync.yml")
    assert "windows-2022" in text
    assert "pyinstaller==6.11.1" in text
    assert "pc-sync/**" in text


def test_server_workflow_runs_pc_sync_tests():
    text = _read(".github/workflows/server.yml")
    assert "tools/testenv.sh" in text and "pc-sync" in _read("tools/testenv.sh")


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


def _publish_step() -> str:
    text = _read(".github/workflows/release.yml")
    return text[text.index("uses: softprops/action-gh-release@"):]


def _marker_step() -> str:
    """The whole 'Pre-release marker' step: from its name line up to the next step."""
    text = _read(".github/workflows/release.yml")
    start = text.index("- name: Pre-release marker")
    rest = text[start + 1:]
    nxt = re.search(r"^\s+- (name|uses):", rest, re.M)
    assert nxt, "no step after the marker step"
    return text[start:start + 1 + nxt.start()]


def test_release_prerelease_marker_step_tests_the_notes_marker_file():
    step = _marker_step()
    assert re.search(r"^\s+id: pre$", step, re.M)  # the publish step reads steps.pre.outputs
    assert not re.search(r"^\s+(- )?if:", step, re.M)  # it must run on every release
    assert 'test -f "release-notes/v${VERSION}.prerelease"' in step
    assert "VERSION: ${{ needs.version.outputs.version }}" in step
    out = r'>> "\$GITHUB_OUTPUT"\s*$'
    assert re.search(r"then\s+echo prerelease=true " + out + r"\s+echo make_latest=false " + out, step, re.M)
    # without the marker both outputs are empty, so the action sends what it sent before the marker existed
    assert re.search(r"else\s+(#.*\s+)?echo prerelease= " + out + r"\s+echo make_latest= " + out, step, re.M)


def test_release_publish_is_driven_by_the_marker_for_both_inputs():
    step = _publish_step()
    assert "prerelease: ${{ steps.pre.outputs.prerelease }}" in step
    assert "make_latest: ${{ steps.pre.outputs.make_latest }}" in step
    # no literal value that would ignore the marker
    assert not re.search(r"^\s+(prerelease|make_latest):\s*(true|false|legacy)\s*$", step, re.M)


def test_release_notes_are_written_for_the_current_version():
    """The workflow refuses a tag without release-notes/v<version>.md and publishes it as the release body."""
    text = _read(".github/workflows/release.yml")
    assert 'release-notes/v$version.md' in text and "body_path: release-notes/v${{ needs.version.outputs.version }}.md" in text
    version = _version("server/filament_kit/__init__.py")
    notes = _read(f"release-notes/v{version}.md")
    assert notes.startswith(f"# filament-kit {version}") and len(notes) > 200


def test_task_runs_every_ten_minutes():
    text = _read("pc-sync/installer/install_task.ps1")
    assert "-RepetitionInterval (New-TimeSpan -Minutes 10)" in text
    assert "-MultipleInstances IgnoreNew" in text
    assert "RestartCount" not in text  # no restart on failure: the next 10-minute run retries


def test_server_and_pc_sync_versions_match():
    assert _version("server/filament_kit/__init__.py") == _version("pc-sync/fksync/__init__.py") == "0.5.4"
    # the wheel takes its version from pyproject; make_release.sh looks for the __version__ wheel
    assert re.search(r'^version = "0\.5\.4"\s*$', _read("pc-sync/pyproject.toml"), re.M)
    server = _read("server/pyproject.toml")        # the server's wheel reads __version__: one number, typed once
    assert not re.search(r'^version = ', server.split("[project.optional-dependencies]")[0], re.M)
    assert 'dynamic = ["version"]' in server and 'version = {attr = "filament_kit.__version__"}' in server


SPOOLMAN_SHA = "bcc961af4c20d7ad7f1740f5609cd3efd94c4556baafaeba5036122dd7e46704"


def test_release_no_grep_q_after_a_pipe():
    # set -o pipefail: `cmd | grep -q` fails when grep exits on the first match and cmd gets SIGPIPE
    text = _read("tools/make_release.sh")
    assert "set -euo pipefail" in text
    assert not re.search(r"\|\s*grep\s+-[a-zA-Z]*q", text)


def test_release_defaults_are_beside_the_checkout():
    text = _read("tools/make_release.sh")
    assert "${FK_LIBRARY_SRC:-$ROOT/../filament-library}" in text and "${FK_JDK:-$ROOT/../jdk}" in text
    assert "/c/" not in text and "/g/" not in text


def test_release_version_code_defaults_to_the_workflows_formula():
    """A tarball built by hand without FK_VERSION_CODE used to carry an app with versionCode 1, which no phone updates
    to. Unset, the script now computes MAJOR*10000 + MINOR*100 + PATCH from the tree's version, as release.yml and
    android/app/build.gradle.kts do."""
    text = _read("tools/make_release.sh")
    assert "FK_VERSION_CODE=${FK_VERSION_CODE:-1}" not in text
    assert "10#$v_major * 10000 + 10#$v_minor * 100 + 10#$v_patch" in text
    gradle = _read("android/app/build.gradle.kts")
    assert "major.toInt() * 10000 + minor.toInt() * 100 + patch.toInt()" in gradle
    assert 'resolve("../server/filament_kit/__init__.py")' in gradle      # the file every Gradle build reads
    # the release and Android workflows check the whole repository out, so that file is where Gradle looks
    for wf in ("release.yml", "android.yml"):
        text = _read(f".github/workflows/{wf}")
        assert "sparse-checkout" not in text and "actions/checkout@" in text, wf


def test_release_copies_spoolman_script():
    text = _read("tools/make_release.sh")
    assert "install/spoolman.sh" in text
    assert '"$stage/install/spoolman.sh"' in text  # made executable in the stage


def test_release_ships_no_ops_export_script():
    """filament-ops never went public: no install migrates from it, so the release carries no export script."""
    assert "export_ops" not in _read("tools/make_release.sh")
    assert not (ROOT / "tools" / "export_ops.sh").exists()


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


def test_a_spoolman_pin_bump_brings_its_database_copy():
    """The first bump migrates the database, and a rollback's older spoolman.sh would then reinstall the old Spoolman on it:
    it fails to start, and with it the kit's trusted rollback. So the release that raises the pin must also copy the database
    before the swap and put it back on a downgrade (with this pin nothing has migrated yet)."""
    text = _read("install/spoolman.sh")
    if "SPOOLMAN_VERSION=v0.27.0" not in text:
        assert "pre-swap copy" in text and "alembic_version" in text, (
            "raising the Spoolman pin needs the pre-swap database copy and the downgrade path (see this test's docstring)")


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
    assert re.search(r"^\s+config \| cert \| modules \| remote \| update \| uninstall \| station \| setup-code\)\s*$",
                     text, re.M)


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
    assert 'KIT_USERS="filament-kit filament-kit-web"' in purge and "for u in $KIT_USERS; do" in purge


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
    assert f"grep -qF '{remote.MARK}'" in block and "for n in $KIT_ROUTES" in block  # listed AND the kit's marker
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
    from fakes.shells import git_bash   # never WSL's launcher (System32 or WindowsApps)
    return git_bash()


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
    cfg = _run_save(tmp_path, "custom", ",station", server="spoolman.example.lan")
    assert cfg["modules"]["station"] and not cfg["modules"]["server"]
    assert cfg["station"]["allow"] == ["spoolman.example.lan"]
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
    ('printf "station\\nset station.allow=srv.example.lan\\n"', 0,
     "CUSTOM=,station SETS=set station.allow=srv.example.lan ADDR=srv.example.lan"),
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
                        "--set=station.allow=srv.example.lan"], capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["MODE=custom SERVER=srv.example.lan",
                                     "set web.public_url=https://m.example.com/f",
                                     "set station.allow=srv.example.lan"]


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


SAVED_NOTE = "using the station's saved server address kit.example.lan"


def _saved_station_etc(tmp_path, allow=("127.0.0.1", "kit.example.lan")):
    import json
    etc = tmp_path / "etc"
    etc.mkdir(exist_ok=True)
    (etc / "config.json").write_text(json.dumps({"modules": {"station": True, "server": False},
                                                 "station": {"allow": list(allow)}}), encoding="utf-8")
    return etc


def _install_no_tty(tmp_path, etc, *args):
    """install.sh with no terminal (as the updater and get.sh piped to bash run it), with a python3 on PATH."""
    import os
    import subprocess
    import sys
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8")
    (shim / "python3").chmod(0o755)
    bash_path = subprocess.run([_bash(), "-c", "cygpath -u \"$1\" 2>/dev/null || printf %s \"$1\"", "_", str(shim)],
                               capture_output=True, text=True).stdout.strip()
    return subprocess.run([_bash(), "-c", f'PATH="{bash_path}:$PATH" exec bash "$0" "$@"',
                           str(ROOT / "install" / "install.sh"), *args],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                          env={**os.environ, "FK_ETC": str(etc)})


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_station_upgrade_without_server_reuses_the_saved_address(tmp_path):
    """The updater (or get.sh piped to bash) runs install.sh with no terminal: a station upgrade given --mode station
    but no --server takes the server address the station already has (station.allow in its config.json) instead
    of dying for it. It then stops at the root check here, past the address check."""
    etc = _saved_station_etc(tmp_path)
    r = _install_no_tty(tmp_path, etc, "--mode", "station")
    assert "needs the kit server's address" not in r.stderr, r.stderr
    assert SAVED_NOTE in r.stderr
    assert r.returncode == 1 and "run as root" in r.stderr, r.stderr
    etc = _saved_station_etc(tmp_path, allow=("127.0.0.1",))
    r = _install_no_tty(tmp_path, etc, "--mode", "station")
    assert "station mode needs the kit server's address" in r.stderr     # only a local address saved: still asks


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_custom_run_without_terminal_uses_the_saved_address_unless_one_is_given(tmp_path):
    etc = _saved_station_etc(tmp_path)
    r = _install_no_tty(tmp_path, etc, "--modules", "station")
    assert SAVED_NOTE in r.stderr and "run as root" in r.stderr, r.stderr
    r = _install_no_tty(tmp_path, etc, "--modules", "station", "--set", "station.allow=other.example.lan")
    assert "saved server address" not in r.stderr and "run as root" in r.stderr, r.stderr
    r = _install_no_tty(tmp_path, etc, "--mode", "station", "--server", "other.example.lan")
    assert "saved server address" not in r.stderr and "run as root" in r.stderr, r.stderr


@functools.lru_cache(maxsize=None)       # asked by two skipif marks at collection: probe once per worker
def _wsl() -> bool:
    import shutil
    if not shutil.which("wsl"):
        return False
    try:
        r = subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "sh", "-c", "command -v script && command -v python3"],
                           capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return False                    # a WSL that does not answer is no WSL: skip, not a collection error
    return r.returncode == 0


@pytest.mark.skipif(not _wsl(), reason="needs WSL Ubuntu with script(1) for a pty")
def test_with_a_terminal_the_saved_address_is_not_used(tmp_path):
    """At a terminal (get.sh hands install.sh /dev/tty) the saved address is not taken: the custom menu's address
    or the "Server address" prompt decide. Run under script(1)'s pty in WSL; it stops at the root check."""
    import subprocess

    def wslpath(p):
        return subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "wslpath", "-a", str(p).replace("\\", "/")],
                              capture_output=True, text=True, timeout=60).stdout.strip()
    etc = _saved_station_etc(tmp_path)
    sh = wslpath(ROOT / "install" / "install.sh")
    for args in ("--mode station", "--modules station"):
        r = subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "env", f"FK_ETC={wslpath(etc)}", "script", "-qec",
                            f"bash {sh} {args}", "/dev/null"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        assert "run as root" in out, out
        assert "saved server address" not in out, out
    # without the pty, the same run takes it (the same WSL shell: the difference is only the terminal)
    r = subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "env", f"FK_ETC={wslpath(etc)}", "bash", sh, "--mode",
                        "station"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    assert SAVED_NOTE in r.stderr, r.stdout + r.stderr


def _stubs_first(script: str) -> str:
    """The wrapper with ./stubs first on its PATH, set inside the script: a PATH handed over from Windows is
    converted differently by Git Bash depending on what started it (PowerShell or Git Bash), so the stand-ins for
    id and runuser were not always found there."""
    first, _, rest = script.partition("\n")
    assert first.startswith("#!"), first
    return f'{first}\nPATH="./stubs:$PATH"\n{rest}'


def _wrapper_run(tmp_path, *args) -> str:
    """Run install/filament-kit-cli.sh as root with stand-ins: the program prints `as-root ...`, runuser prints
    `as-user ...`. Returns what was printed."""
    import os
    import subprocess
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("id", 'echo 0'), ("runuser", 'shift 3; echo "as-user $*"'),
                       ("prog", 'echo "as-root $*"')):
        f = stubs / name
        f.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
        f.chmod(0o755)
    text = _read("install/filament-kit-cli.sh").replace("BIN=/opt/filament-kit/venv/bin/filament-kit",
                                                        "BIN=./stubs/prog")
    assert "BIN=./stubs/prog" in text
    (tmp_path / "w.sh").write_text(_stubs_first(text), encoding="utf-8", newline="\n")
    r = subprocess.run([_bash(), "w.sh", *args], cwd=tmp_path, env=dict(os.environ), capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_runs_reader_token_and_revoke_as_root(tmp_path):
    """`reader token` and `reader revoke` refuse unless root (they write the token file, chowned to the service
    user): `sudo filament-kit reader token` must reach the program as root. `reader tokens` (a list) drops to
    the service user like every other read."""
    assert _wrapper_run(tmp_path, "reader", "token", "--name", "bench") == "as-root reader token --name bench"


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_runs_reader_setup_as_root(tmp_path):
    """`reader setup` makes a token (root) and writes secrets.h where the caller said: never the service user."""
    assert _wrapper_run(tmp_path, "reader", "setup", "--out", "s.h") == "as-root reader setup --out s.h"


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_reader_revoke_as_root_and_list_as_user(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert _wrapper_run(tmp_path / "a", "reader", "revoke", "r1") == "as-root reader revoke r1"
    assert _wrapper_run(tmp_path / "b", "reader", "tokens") == "as-user ./stubs/prog reader tokens"


def _wrapper_half(tmp_path, *, marker=False, state=None, program=True, installing=False):
    """Run the wrapper over a kit folder with stand-ins; (exit code, stdout, stderr)."""
    import os
    import subprocess
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    bodies = {"id": "echo 1000", "pgrep": "exit 1", "systemctl": f"exit {0 if installing else 3}"}
    if program:
        bodies["prog"] = 'echo "ran $*"'
    for name, body in bodies.items():
        f = stubs / name
        f.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
        f.chmod(0o755)
    kit = tmp_path / "kit"
    (kit / "releases").mkdir(parents=True)
    if marker:
        (kit / ".fk-installed").write_text("x\n")
    if state:
        (kit / "releases" / "state.json").write_text(state, encoding="utf-8")
    text = _read("install/filament-kit-cli.sh")
    for old, new in (("BIN=/opt/filament-kit/venv/bin/filament-kit", "BIN=./stubs/prog"),
                     ("KIT_OPT=/opt/filament-kit", "KIT_OPT=./kit")):
        assert old in text
        text = text.replace(old, new)
    (tmp_path / "w.sh").write_text(text, encoding="utf-8", newline="\n")
    env = dict(os.environ, PATH="./stubs" + os.pathsep + os.environ.get("PATH", ""))
    if os.name == "nt":
        env["PATH"] = "./stubs:" + os.environ.get("PATH", "")
    r = subprocess.run([_bash(), "w.sh", "status"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout, r.stderr


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_says_nothing_on_a_whole_install(tmp_path):
    assert _wrapper_half(tmp_path, marker=True) == (0, "ran status\n", "")


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_takes_a_running_install_for_no_half_install(tmp_path):
    assert _wrapper_half(tmp_path, installing=True) == (0, "ran status\n", "")


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_prints_the_repair_and_still_runs_the_program(tmp_path):
    from filament_kit import config
    rc, out, err = _wrapper_half(tmp_path, state='{"previous": "1.2.3", "held": null}')
    assert rc == 0 and out == "ran status\n"
    assert "stopped halfway" in err and f"  {config.GET_COMMAND} --version 1.2.3\n" in err


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_with_no_program_prints_the_repair_and_exits_1(tmp_path):
    from filament_kit import config
    rc, out, err = _wrapper_half(tmp_path, program=False)
    assert rc == 1 and out == ""
    assert err.endswith(f"  {config.GET_COMMAND}\n")       # no state: the plain line


def test_the_page_shows_the_repair_line_unless_a_job_is_running():
    assert "u.half_install && !r.job.running" in _read("server/filament_kit/setup_static/setup_tabs.js")


def _wrapper_status(tmp_path, *, uid="0", folder=True, prog='echo "paired 192.0.2.10:8710"') -> list[str]:
    """Run `status` through the wrapper with stand-ins. The program answers `station pairing-state` with `prog`,
    and every run is logged; runuser logs `as-user ...`. Returns the log."""
    import os
    import subprocess
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    prog_body = f'echo "as-caller $*" >> log\nif [ "$1" = station ]; then {prog}; fi'
    for name, body in (("id", f"echo {uid}"), ("runuser", 'shift 3; echo "as-user $*" >> log'), ("prog", prog_body)):
        f = stubs / name
        f.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
        f.chmod(0o755)
    if folder:
        (tmp_path / "pairing").mkdir()
    text = _read("install/filament-kit-cli.sh")
    for old, new in (("BIN=/opt/filament-kit/venv/bin/filament-kit", "BIN=./stubs/prog"),
                     ("STATION_DIR=/etc/filament-kit-station", "STATION_DIR=./pairing")):
        assert old in text
        text = text.replace(old, new)
    (tmp_path / "w.sh").write_text(_stubs_first(text), encoding="utf-8", newline="\n")
    r = subprocess.run([_bash(), "w.sh", "status"], cwd=tmp_path, env=dict(os.environ), capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return (tmp_path / "log").read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_status_checks_the_station_pairing_as_root(tmp_path):
    """The pairing folder is closed to the service user that runs `status`: root looks, and status gets the answer."""
    assert _wrapper_status(tmp_path) == ["as-caller station pairing-state",
                                         "as-user ./stubs/prog status --station-pairing=paired 192.0.2.10:8710"]


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_status_says_failed_when_the_root_check_fails(tmp_path):
    assert _wrapper_status(tmp_path, prog="exit 3")[-1] == "as-user ./stubs/prog status --station-pairing=failed"


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_status_skips_the_check_with_no_station_folder(tmp_path):
    """A server without a station starts the program once, as before."""
    assert _wrapper_status(tmp_path, folder=False) == ["as-user ./stubs/prog status"]


@pytest.mark.skipif(not _bash(), reason="needs bash")
def test_wrapper_status_without_sudo_passes_nothing(tmp_path):
    """Not root: it can't look, so status says so itself ("run it with sudo", which is then true)."""
    assert _wrapper_status(tmp_path, uid="1000") == ["as-caller status"]


# The shell scripts with multi-line `python -c '...'` blocks (test_no_other_script_has_python_c_blocks keeps the list
# complete): each must keep at least one block, so the check below never passes on nothing.
PYTHON_C_SCRIPTS = ["get.sh", "install/install.sh"]


def test_no_other_script_has_python_c_blocks():
    scripts = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in [*(ROOT / "install").rglob("*.sh"),
                                                                           ROOT / "get.sh", *(ROOT / "tools").glob("*.sh")])
    have = [s for s in scripts if re.search(r"-c '$", _read(s), re.M)]
    assert have == PYTHON_C_SCRIPTS


@pytest.mark.parametrize("rel", PYTHON_C_SCRIPTS)
def test_inline_python_survives_shell_single_quotes(rel):
    """A `python -c '...'` block is one shell single-quoted word: a ' inside it ends the word, and Python gets a
    cut program (install.sh's custom-mode block did, so every --modules install without a terminal failed).
    Each block must end at its closing quote on a line of its own and compile."""
    text = _read(rel)
    blocks = 0
    for m in re.finditer(r"-c '\n", text):
        start = m.end()
        end = text.index("'", start)
        code = text[start:end]
        after = text[end + 1:end + 2]
        assert after in ("\n", ")", " ", ""), f"{rel}: a ' inside the python -c block near: {code[-80:]!r}"
        assert text[end - 1] == "\n", f"{rel}: a ' inside the python -c block near: {code[-80:]!r}"
        compile(code, f"{rel} python -c block", "exec")
        blocks += 1
    assert blocks >= 1, f"{rel}: no python -c block left; update PYTHON_C_SCRIPTS"


# --- final review I3 (Ruling BU): CI builds, signs and publishes library.tar.gz ----------------------------------

def _step(text: str, name: str) -> str:
    i = text.index(f"- name: {name}")
    j = text.find("\n      - ", i + 1)
    return text[i:j if j > 0 else len(text)]


def test_release_workflow_builds_the_library_from_the_public_repo():
    """filament-library is public: every release checks it out (the FK_LIBRARY_TOKEN secret is optional, used when
    set) and builds, signs and publishes library.tar.gz (queue item 9: v0.2.0 had none)."""
    text = _read(".github/workflows/release.yml")
    assert "Filament library token" not in text and "steps.library.outputs.have" not in text
    i = text.index("repository: thompsonfabco/filament-library")
    co = text[text.rindex("- uses: actions/checkout@", 0, i):i + 600]
    assert "if:" not in co
    assert "token: ${{ secrets.FK_LIBRARY_TOKEN || github.token }}" in co
    assert "persist-credentials: false" in co
    assert "path: filament-library" in co
    build = _step(text, "Build the tarball and the signed APK")
    assert "FK_LIBRARY_SRC: ${{ github.workspace }}/filament-library" in build
    up = text[text.index("name: library\n"):]
    assert "if-no-files-found: error" in up[:200]


def test_release_workflow_signs_and_publishes_the_library():
    text = _read(".github/workflows/release.yml")
    assert "dist/library.tar.gz" in text                     # uploaded by the server job
    sums = _step(text, "SHA256SUMS and its signature")
    assert "library.tar.gz" in sums                           # in the signed SHA256SUMS, always
    assert not re.search(r"if \[ -f dist/library\.tar\.gz \]", sums)
    assert "files: ${{ steps.sums.outputs.files }}" in text
    assert "id: sums" in sums


@pytest.mark.skipif(not _bash(), reason="needs bash")
@pytest.mark.parametrize("with_library", [True, False])
def test_release_workflow_sums_step_runs(tmp_path, with_library):
    """Run the sums step's shell (signing stubbed) on a stand-in dist, as GitHub runs it (`bash -e`): library.tar.gz is
    summed and published, and a release without it fails rather than shipping without its data."""
    import os
    import subprocess
    text = _read(".github/workflows/release.yml")
    sums = _step(text, "SHA256SUMS and its signature")
    run = sums[sums.index("run: |") + len("run: |"):]
    script = "\n".join(line[10:] if line.startswith(" " * 10) else line for line in run.splitlines())
    script = script.replace("python tools/sign_release.py sign dist/SHA256SUMS", "touch dist/SHA256SUMS.sig")
    dist = tmp_path / "dist"
    dist.mkdir()
    for f in ("filament-kit-1.2.3.tar.gz", "filament-kit.apk", "filament-kit-sync-setup-1.2.3.exe",
              "filament-kit-sync-linux-x86_64-1.2.3.tar.gz",
              "bambu_hardware.xml", "klipper_hardware.xml", "fk-printer-pack.tar.gz") + (("library.tar.gz",) if with_library else ()):
        (dist / f).write_bytes(f.encode())
    (tmp_path / "get.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    out = tmp_path / "out"
    (tmp_path / "s.sh").write_text(script, encoding="utf-8", newline="\n")
    env = dict(os.environ, FK_RELEASE_KEY="stand-in", VERSION="1.2.3", GITHUB_OUTPUT="out")
    r = subprocess.run([_bash(), "-e", "s.sh"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    if not with_library:
        assert r.returncode != 0 and not (dist / "SHA256SUMS.sig").exists()
        return
    assert r.returncode == 0, r.stdout + r.stderr
    listed = (dist / "SHA256SUMS").read_text()
    assert "library.tar.gz" in listed
    files = out.read_text()
    assert "dist/library.tar.gz" in files
    for f in ("dist/filament-kit-1.2.3.tar.gz", "dist/get.sh", "dist/SHA256SUMS.sig", "dist/bambu_hardware.xml",
              "dist/filament-kit-sync-linux-x86_64-1.2.3.tar.gz"):
        assert f in files
    assert "filament-kit-sync-linux-x86_64-1.2.3.tar.gz" in listed     # the Linux PC sync is signed too


# --- final review M12: get.sh on an existing install waits for no printer job, as the updater does ---------------

def _get_sh_hold_function() -> str:
    text = _read("get.sh")
    i = text.index("fk_hold_printers() {")
    return text[i:text.index("\n}\n", i) + 3]


def test_get_sh_holds_the_printer_locks_before_install_sh():
    text = _read("get.sh")
    body = text[text.index("fk_main() {"):]
    assert body.index("fk_hold_printers") < body.index('bash "$root/install.sh"')
    fn = _get_sh_hold_function()
    assert "mapping.lock" in fn and "flock -n -x" in fn and "fk_die" in fn


@pytest.mark.skipif(not _wsl(), reason="needs WSL Ubuntu")
def test_get_sh_refuses_while_a_printer_job_holds_its_lock(tmp_path):
    import subprocess
    script = tmp_path / "hold.sh"
    script.write_text("set -euo pipefail\n"
                      "fk_die() { printf 'error: %s\n' \"$*\" >&2; exit 1; }\n"
                      + _get_sh_hold_function() +
                      'st=$(mktemp -d); mkdir -p "$st/printers/S1" "$st/printers/S2"\n'
                      ': > "$st/printers/S1/mapping.lock"; : > "$st/printers/S2/mapping.lock"\n'
                      'FK_STATE=$st fk_hold_printers\n'
                      # held now: another holder cannot take it, as a mapping job could not
                      'if flock -n -x "$st/printers/S2/mapping.lock" true; then echo NOT-HELD; else echo HELD; fi\n',
                      encoding="utf-8", newline="\n")
    busy = tmp_path / "busy.sh"
    busy.write_text("set -euo pipefail\n"
                    "fk_die() { printf 'error: %s\n' \"$*\" >&2; exit 1; }\n"
                    + _get_sh_hold_function() +
                    'st=$(mktemp -d); mkdir -p "$st/printers/S1"; : > "$st/printers/S1/mapping.lock"\n'
                    # the lock is held once the child, running under flock, has written the ready file
                    'flock -x "$st/printers/S1/mapping.lock" sh -c \': > "$1"; sleep 5\' sh "$st/ready" &\n'
                    'for _ in $(seq 100); do [ -e "$st/ready" ] && break; sleep 0.1; done; [ -e "$st/ready" ]\n'
                    'FK_STATE=$st fk_hold_printers; echo REACHED\n', encoding="utf-8", newline="\n")

    def run(p):
        wp = subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "wslpath", "-a", str(p).replace("\\", "/")],
                            capture_output=True, text=True, timeout=60).stdout.strip()
        return subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "bash", wp], capture_output=True, text=True,
                              timeout=60)
    r = run(script)
    assert r.returncode == 0 and r.stdout.strip() == "HELD", r.stdout + r.stderr
    r = run(busy)
    assert r.returncode == 1 and "REACHED" not in r.stdout
    assert "printer S1 is mapping slots or loading a spool" in r.stderr and "nothing was installed" in r.stderr


# --- licence audit (queue item 16): the GPL text and the third-party notices ship with everything ---------------

def test_both_packages_declare_the_kit_licence():
    for f in ("server/pyproject.toml", "pc-sync/pyproject.toml"):
        assert 'license = {text = "GPL-3.0-or-later"}' in _read(f), f


def test_releases_ship_license_and_third_party_notices():
    assert (ROOT / "THIRD-PARTY.md").is_file() and (ROOT / "LICENSE").is_file()
    assert re.search(r'^cp LICENSE THIRD-PARTY\.md "\$stage/"', _read("tools/make_release.sh"), re.M)
    assert re.search(r'^install -m 644 LICENSE THIRD-PARTY\.md "\$stage/\$name/"', _read("pc-sync/linux/build.sh"), re.M)
    iss = _read("pc-sync/installer/filament-kit-sync.iss")
    assert r'Source: "..\..\LICENSE"; DestDir: "{app}"' in iss
    assert r'Source: "..\..\THIRD-PARTY.md"; DestDir: "{app}"' in iss


def test_the_library_builder_imports_without_the_kits_dependencies():
    """release.yml builds library.tar.gz with the runner's plain Python (tools/build_library_asset.py imports
    filament_kit.library): it must not need cryptography or any other kit dependency (v0.3.0's first release run
    failed with ModuleNotFoundError: cryptography)."""
    code = ("import sys\n"
            "for m in ('cryptography', 'starlette', 'uvicorn', 'httpx', 'anthropic', 'mcp', 'defusedxml'):\n"
            "    sys.modules[m] = None\n"
            f"sys.path.insert(0, {str(ROOT / 'tools')!r}); sys.path.insert(0, {str(ROOT / 'server')!r})\n"
            "import sync_library_snapshot\n"
            "print('ok')\n")
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_the_release_pins_the_library_commit_and_needs_its_asset():
    """An unpinned third-repo checkout inside a signed release is the one gap the signature can't see."""
    text = _read(".github/workflows/release.yml")
    co = text[text.index("repository: thompsonfabco/filament-library"):]
    assert re.search(r"^\s*ref: [0-9a-f]{40}\s*$", co[:co.index("path: filament-library")], re.M)
    assert "kept conditional" not in text and "[ -f dist/library.tar.gz ]" not in text
    assert re.search(r'assets="[^"]*library\.tar\.gz"', text)


def test_ci_runs_the_web_tests_and_the_other_suites():
    """The web module's tests skip themselves without the extra, so the recipe must install it: "green" must mean the same at each
    stage, so CI runs the same script as everyone else."""
    flow, recipe = _read(".github/workflows/server.yml"), _read("tools/testenv.sh")
    assert "bash tools/testenv.sh --root --lint" in flow and "timeout-minutes:" in flow and "refs/tags/v0.3.0" in flow
    assert "pytest " not in flow.split("testenv.sh")[1]
    for suite in ('server[test,web]', 'pc-sync[test]', "-n \"$WORKERS\"", "-rfEs", "printer-pack/tests", "integrations/orca-spool-sync/tests",
                  "reader/tools", "test_root_links.py", "tools/test_get_e2e.py", "tools/e2e/*.sh", "printer-pack/*.sh", "tools/e2e/klipper.sh"):
        assert suite in recipe, suite


def test_every_workflow_run_of_pytest_is_parallel():
    for name in ("pc-sync", "release", "reader"):
        for line in _read(f".github/workflows/{name}.yml").splitlines():
            if line.strip().removeprefix("run: ").startswith("pytest "):
                assert "-n auto" in line, (name, line)
    assert "-n $Workers" in _read("tools/testenv.ps1") and "-rfEs" in _read("tools/testenv.ps1")


def test_the_recipe_refuses_a_windows_drive_and_tests_this_tree_not_its_venv():
    recipe = _read("tools/testenv.sh")
    assert "/mnt/*)" in recipe and "PYTHONPATH=$ROOT/server:$ROOT/pc-sync" in recipe and "sha256sum" in recipe
    assert "--basetemp=\"$RUN" in recipe and "/tmp" not in recipe.replace("/tmp can be", "")


def test_release_version_job_refuses_a_tag_off_main_unless_switched_off():
    """FA-095: a v* tag on a branch commit must not reach the signing jobs; the repo variable is the off switch."""
    text = _read(".github/workflows/release.yml")
    version_job = text.split("\n  version:\n", 1)[1].split("\n  server:", 1)[0] if "\n  server:" in text else text
    assert "fetch-depth: 0" in version_job
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in version_job
    assert "${{ vars.FK_RELEASE_ANY_BRANCH }}" in version_job


def test_get_e2e_final_read_has_a_timeout_when_a_descendant_holds_the_pipe():
    pytest.importorskip("cryptography")
    import importlib.util
    import os
    import signal
    import time
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("get_e2e_under_test", ROOT / "tools" / "test_get_e2e.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    child = "import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); " \
            "print(c.pid, flush=True); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = None
    try:
        time.sleep(1.5)
        proc.kill()                      # the child lives on and keeps the pipe open
        started = time.time()
        out = mod._final_output(proc, grace=1)
        assert time.time() - started < 20
        pid = int(out.split()[0]) if out.split() else None
    finally:
        proc.kill()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)     # the one this test started, by PID
            except OSError:
                pass
