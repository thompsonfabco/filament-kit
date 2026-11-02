"""Static checks on the systemd units and install scripts (Task 8, stage 4)."""
import configparser
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install"
UNITS = INSTALL / "systemd"
NEW_UNITS = ["filament-kit-library.service", "filament-kit-library.timer",
             "filament-kit-build.service", "filament-kit-build.path"]


def _unit(name: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read_string((UNITS / name).read_text(encoding="utf-8"))
    return cp


def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


HARDENING = {"User": "filament-kit", "Group": "filament-kit", "ProtectSystem": "strict",
             "ReadWritePaths": "/var/lib/filament-kit", "NoNewPrivileges": "yes",
             "PrivateTmp": "yes", "ProtectHome": "yes"}


@pytest.mark.parametrize("name", ["filament-kit-build.service", "filament-kit-library.service"])
def test_oneshot_services_hardened(name):
    svc = _unit(name)["Service"]
    assert svc["Type"] == "oneshot"
    for k, v in HARDENING.items():
        assert svc[k] == v, k


def test_build_service():
    svc = _unit("filament-kit-build.service")["Service"]
    assert svc["ExecStart"] == "/opt/filament-kit/venv/bin/filament-kit profiles build"
    assert svc["IPAddressDeny"] == "any"
    # final review: a LAN spoolman_url must work in builds too; the same allowlist as the main service
    main = _unit("filament-kit.service")["Service"]
    assert svc["IPAddressAllow"] == main["IPAddressAllow"]
    assert "192.168.0.0/16" in svc["IPAddressAllow"].split() and "localhost" in svc["IPAddressAllow"].split()


def test_library_service_has_no_ip_lines():
    svc = _unit("filament-kit-library.service")["Service"]
    assert svc["ExecStart"] == "/opt/filament-kit/venv/bin/filament-kit library update --scheduled"
    assert "IPAddressDeny" not in svc and "IPAddressAllow" not in svc


def test_library_timer():
    cp = _unit("filament-kit-library.timer")
    assert cp["Timer"]["OnCalendar"] == "daily"
    assert cp["Timer"]["RandomizedDelaySec"] == "1h"
    assert cp["Timer"]["Persistent"] == "true"
    assert cp["Install"]["WantedBy"] == "timers.target"


def test_build_path_unit():
    cp = _unit("filament-kit-build.path")
    assert cp["Path"]["PathModified"] == "/var/lib/filament-kit/profiles/rebuild-request"
    assert cp["Path"]["Unit"] == "filament-kit-build.service"
    assert cp["Install"]["WantedBy"] == "multi-user.target"


def test_install_enables_new_units_and_state_dirs():
    text = _text(INSTALL / "install.sh")
    for name in NEW_UNITS:
        assert f'"$RES/systemd/{name}" /etc/systemd/system/{name}' in text, name
    enable = [ln for ln in text.splitlines() if ln.startswith("systemctl enable filament-kit ")]
    assert enable and "filament-kit-library.timer" in enable[0] and "filament-kit-build.path" in enable[0]
    assert ('install -d -m 750 -o filament-kit -g filament-kit '
            '"$STATE/profiles" "$STATE/library" "$STATE/library-local"') in text
    assert "filament-kit profiles build || true" in text


def test_uninstall_removes_all_four():
    units_line = next(ln for ln in _text(INSTALL / "uninstall.sh").splitlines() if ln.startswith("UNITS="))
    for name in NEW_UNITS:
        assert name in units_line, name


def test_backup_excludes():
    text = _text(INSTALL / "backup.sh")
    for p in ("var/lib/filament-kit/profiles/live/system", "var/lib/filament-kit/library/versions",
              "var/lib/filament-kit/profiles/builds/*.tmp"):
        assert f"--exclude='{p}'" in text, p


def test_cli_wrapper_library_add_uses_stdin():
    text = _text(INSTALL / "filament-kit-cli.sh")
    assert 'exec runuser -u filament-kit -- "$BIN" library add - < "$3"' in text
    assert '[ ! -f "$3" ] || [ ! -r "$3" ]' in text  # a missing file is refused with a message


def test_release_packages_path_units_and_checks_library_data():
    text = _text(ROOT / "tools" / "make_release.sh")
    assert "install/systemd/*.path" in text
    assert "filament_kit/library_data/index.json" in text


def test_readme_final_review_points():
    """Final review: README documents restore-deleted, the real pairing order, that unpair covers the PC, and that
    a library rollback is undone by the next scheduled update unless updates are off."""
    readme = _text(ROOT / "README.md")
    assert "sudo filament-kit profiles restore-deleted" in readme
    pair = readme[readme.index("## Pair your PC"):readme.index("## Building the Android app release")]
    assert pair.index("Finish") < pair.index("paste the link")
    assert "Pair this PC with the filament-kit server now" in pair
    row = next(line for line in readme.splitlines() if line.startswith("| `sudo filament-kit unpair`"))
    assert "PC" in row and "phones" in row
    lib = readme[readme.index("## Spec library updates"):readme.index("## Troubleshooting")]
    assert '"schedule": "off"' in lib and "rollback" in lib and "next" in lib
