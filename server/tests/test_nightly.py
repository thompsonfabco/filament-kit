"""The nightly build: its workflow's promises, make_release.sh FK_NIGHTLY=1 and the version a nightly kit shows."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from filament_kit import updates
from test_release import _git_bash, _wheel_builder

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"


def _nightly() -> str:
    return (WF / "nightly.yml").read_text(encoding="utf-8")


def _job(text: str, name: str) -> str:
    return re.search(rf"^  {name}:\n(.*?)(?=^  [a-z-]+:\n|\Z)", text, re.M | re.S)[1]


def test_it_runs_at_23_new_york_all_year():
    text = _nightly()
    assert "- cron: '0 3 * * *'" in text and "- cron: '0 4 * * *'" in text and "workflow_dispatch:" in text
    assert '"$(TZ=America/New_York date +%H)" != 23' in text


def test_it_runs_no_tests():
    for word in ("pytest", "testenv", "fkgate", "shellcheck", "ruff", "gradlew test"):
        assert word not in _nightly(), word


def test_it_publishes_only_a_prerelease_and_prunes_only_nightlies():
    text = _nightly()
    assert "--prerelease --latest=false" in text
    assert "Untested nightly build from the nightly branch; may be broken. Not offered to installed kits." in text
    assert "'^nightly-[0-9]{8}$'" in text and "tail -n +8" in text
    assert "library" not in _job(text, "publish")


def test_release_workflow_does_not_fire_on_a_nightly_tag():
    assert "      - 'v*'\n" in (WF / "release.yml").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_it_holds_no_secret_and_signs_nothing():
    text = _nightly()
    for word in ("secrets.", "FK_RELEASE_KEY", "FK_KEYSTORE", "sign_release", "SHA256SUMS.sig"):
        assert word not in text, word
    assert "contents: write" not in _job(text, "build")
    assert "Nightlies are unsigned" in text


@pytest.mark.parametrize("name", ["merge", "build", "publish"])
def test_every_job_starts_by_refusing_any_ref_but_main(name):
    steps = _job(_nightly(), name).split("    steps:\n", 1)[1]
    first = steps.split("\n      - ", 2)[0]
    assert "name: Only from main" in first and "REF: ${{ github.ref }}" in first
    assert '[ "$REF" != refs/heads/main ]' in first and "exit 1" in first


def test_every_action_is_pinned_by_commit():
    uses = re.findall(r"^\s*- uses: (\S+)(.*)$", _nightly(), re.M)
    assert uses
    for ref, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
        assert re.fullmatch(r"\s+# v\d+\.\d+\.\d+", rest), (ref, rest)


@pytest.mark.parametrize("name", ["server", "android", "pc-sync", "reader"])
def test_the_test_workflows_leave_the_nightly_branch_alone(name):
    text = (WF / f"{name}.yml").read_text(encoding="utf-8")
    assert text.count("branches-ignore: [nightly]") == 2
    assert text.count("tags: ['**']") == 1      # a tag push still runs them


def test_version_text_is_the_version_on_a_stable_kit(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_OPT", str(tmp_path))
    monkeypatch.setattr(updates, "current_version", lambda: "1.2.3")
    assert updates.version_text() == "1.2.3"


@pytest.mark.parametrize("content,shown", [
    ("1.2.3-nightly.20261109\n", "1.2.3-nightly.20261109"),
    ("1.2.2-nightly.20261109\n", "1.2.3"),      # left by another version
    ("<script>\n", "1.2.3"),
    ("", "1.2.3"),
])
def test_version_text_on_a_nightly_kit(tmp_path, monkeypatch, content, shown):
    monkeypatch.setenv("FK_OPT", str(tmp_path))
    monkeypatch.setattr(updates, "current_version", lambda: "1.2.3")
    (tmp_path / "resources").mkdir()
    (tmp_path / "resources" / "NIGHTLY").write_text(content, encoding="utf-8")
    assert updates.version_text() == shown


def test_the_page_shows_version_text_and_still_compares_the_version():
    """r.version decides whether the page reloads for a new release: it must stay what S.version is."""
    js = (ROOT / "server/filament_kit/setup_static/setup_tabs.js").read_text(encoding="utf-8")
    assert "${r.version_text || r.version}" in js and "r.version !== S.version" in js


def test_gradle_keeps_the_stable_identity_without_fk_nightly():
    text = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert '" + if (nightlyDate != null) ".nightly" else ""' in text
    assert 'if (nightlyDate != null) "Filament Kit Nightly" else "filament-kit"' in text
    assert 'signingConfigs.getByName("debug")' in text
    assert 'android:label="${appLabel}"' in (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")


@pytest.mark.skipif(not _git_bash(), reason="needs bash (Git Bash on Windows)")
@pytest.mark.skipif(not _wheel_builder(), reason="needs uv or python -m build to build the wheel")
def test_make_release_nightly_tarball(tmp_path):
    def posix(p: Path) -> str:
        r = subprocess.run([_git_bash(), "-c", 'cygpath -u "$1" 2>/dev/null || printf %s "$1"', "_", str(p)],
                           capture_output=True, text=True)
        return r.stdout.strip() or p.as_posix()
    src = tmp_path / "src"
    skip = shutil.ignore_patterns(".venv", "*.egg-info", "build", "dist", "__pycache__", ".pytest_cache")
    for part in ("tools", "install", "server", "station/panel/firmware", "printer-pack"):
        shutil.copytree(ROOT / part, src / part, ignore=skip)
    for f in ("LICENSE", "THIRD-PARTY.md"):
        shutil.copy(ROOT / f, src / f)
    # a library checkout is there, as on the dev PC: a nightly still builds no library asset
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "index.json").write_text("{}")
    dist = tmp_path / "dist"
    env = {**os.environ, "FK_DIST": posix(dist), "FK_NO_APP": "1", "FK_NIGHTLY": "1", "FK_NIGHTLY_DATE": "20261109",
           "FK_LIBRARY_SRC": posix(lib)}
    env.pop("PYTHONPATH", None)
    r = subprocess.run([_git_bash(), str(src / "tools" / "make_release.sh")], cwd=src, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    version = re.search(r'^__version__ = "(.*)"', (ROOT / "server/filament_kit/__init__.py").read_text(), re.M)[1]
    name = f"filament-kit-{version}-nightly.20261109"
    assert not (dist / "library.tar.gz").exists()
    x = tmp_path / "x"
    with tarfile.open(dist / f"{name}.tar.gz") as t:
        names = t.getnames()
        t.extractall(x, filter="data")
    assert not any("/app/" in n for n in names)
    assert (x / name / "NIGHTLY").read_text() == f"{version}-nightly.20261109\n"
    assert len(list((x / name).glob(f"filament_kit-{version}-*.whl"))) == 1     # the wheel keeps the plain version
    # install.sh's first line, before its argument check stops it
    r = subprocess.run([_git_bash(), str(x / name / "install.sh"), "--no-such-option"], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    assert r.stdout.splitlines()[0].startswith("nightly build 20261109:"), r.stdout + r.stderr


@pytest.mark.skipif(not _git_bash(), reason="needs bash (Git Bash on Windows)")
def test_make_release_refuses_a_bad_nightly_date(tmp_path):
    env = {**os.environ, "FK_DIST": "dist-unused", "FK_NO_APP": "1", "FK_NIGHTLY": "1", "FK_NIGHTLY_DATE": "tonight"}
    src = tmp_path / "src"
    shutil.copytree(ROOT / "tools", src / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "server/filament_kit", src / "server/filament_kit",
                    ignore=shutil.ignore_patterns("__pycache__", "library_data"))
    r = subprocess.run([_git_bash(), str(src / "tools" / "make_release.sh")], cwd=src, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "FK_NIGHTLY_DATE must be YYYYMMDD" in r.stderr
