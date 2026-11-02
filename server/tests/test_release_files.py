"""Release and packaging files: checked as text (CI files are written and linted here, run on GitHub)."""
import re
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
            assert re.match(r"\s+FK_KEYSTORE(_B64|_PASSWORD): \$\{\{ secrets\.FK_KEYSTORE(_B64|_PASSWORD) \}\}$", line), line


def test_release_workflow_builds_sync_on_windows_with_pinned_pyinstaller():
    text = _read(".github/workflows/release.yml")
    assert "windows-2022" in text
    assert "pyinstaller==6.11.1" in text
    assert "softprops/action-gh-release@v2" in text


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


def test_release_copies_spoolman_script():
    text = _read("tools/make_release.sh")
    assert "install/spoolman.sh" in text
    assert '"$stage/install/spoolman.sh"' in text  # made executable in the stage


def test_install_hands_over_to_modules_apply():
    text = _read("install/install.sh")
    assert "exec /usr/local/bin/filament-kit modules apply" in text
    assert "--mode" in text
    assert "Install mode: 1) server 2) station 3) all-in-one 4) custom [1]" in text
    assert "Server address (name or IP): " in text
    assert '"$WHEEL[station]"' in text
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
    assert re.search(r'^station = \["nfcpy==1\.0\.4", "pyserial>=3\.5"\]\s*$', text, re.M)


def test_wrapper_runs_modules_as_root():
    text = _read("install/filament-kit-cli.sh")
    assert re.search(r"^\s+config \| cert \| modules\)\s*$", text, re.M)


def test_uninstall_uses_modules_units_and_cleans_station():
    text = _read("install/uninstall.sh")
    assert "modules units" in text
    assert "/etc/systemd/system/filament-kit-station.service.d" in text
    assert "/etc/udev/rules.d/99-filament-kit-station.rules" in text
    purge = text[text.index('if [ "$PURGE" -eq 1 ]; then\n    rm -rf'):]
    assert "filament-kit-station" in purge
