"""Which bash the tests that run the kit's shell scripts may use."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _is_wsl_launcher(path: str) -> bool:
    """Windows' own bash.exe (System32, or the WindowsApps alias) starts WSL: it cannot take a Windows path, and it
    writes its own warnings to stderr."""
    low = path.lower().replace("/", "\\")
    return sys.platform == "win32" and ("\\system32\\" in low or "\\windowsapps\\" in low)


def git_bash() -> str | None:
    """A bash that takes this machine's paths: the one on PATH unless it is WSL's launcher; on Windows then Git
    Bash, found beside git.exe (<Git>\\cmd\\git.exe -> <Git>\\bin\\bash.exe). None: the test is skipped."""
    found = shutil.which("bash")
    if found and not _is_wsl_launcher(found):
        return found
    git = shutil.which("git")
    if sys.platform == "win32" and git:
        for cand in (Path(git).resolve().parent.parent / "bin" / "bash.exe",
                     Path(git).resolve().parent.parent / "usr" / "bin" / "bash.exe"):
            if cand.is_file():
                return str(cand)
    return None
