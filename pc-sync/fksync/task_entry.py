"""Entry of filament-kit-sync-task.exe: the windowed build that Task Scheduler starts every 10 minutes.

It runs `filament-kit-sync run --quiet`: no console window, no output (the log gets every line). Any
error that escapes is swallowed and turned into exit code 1, so the windowed exe never shows an error
dialog that would sit there and block the next scheduled runs (the task ignores new instances).
"""
import sys

from fksync.__main__ import main


def run() -> int:
    try:
        return main(["run", "--quiet"])
    except Exception:  # noqa: BLE001 - nobody is there to read it; cmd_run already logs what it can
        return 1


if __name__ == "__main__":
    sys.exit(run())
