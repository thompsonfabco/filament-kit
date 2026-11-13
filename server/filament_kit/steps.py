"""The step lines of the counted background jobs (docs/design 02 section 8.4, "Steps").

A command that has countable steps writes `==> step K of N <sentence>` when each step starts, on stdout where its
other progress lines go, so the setup page's job log and the command line show the same sentences.
setup_console/jobs.py reads them. N is fixed before the first line, K counts up from 1. A sentence holds no address,
serial or name: it is shown without the lock (a version number is fine).

A command that runs another counted command (restore and update run `modules apply`, install.sh does too) must not
let the inner one write step lines of its own into the same log: the first Steps of a process marks the environment
with its pid, and a Steps made in a child process, which sees another pid there, stays silent.
"""
from __future__ import annotations

import os

ENV = "FK_STEPS_OWNER"


_made_here = False        # a Steps already counts this process's job: a second one stays quiet (one N per log)


class Steps:
    def __init__(self, count: int, out=None):
        global _made_here
        if count < 1:
            raise ValueError("a job counts at least one step")
        self.count, self.index, self._out = count, 0, out
        owner = os.environ.get(ENV)
        self.quiet = (owner is not None and owner != str(os.getpid())) or _made_here
        if owner is None:
            os.environ[ENV] = str(os.getpid())
        _made_here = True

    def next(self, text: str) -> None:
        """Step K + 1 starts. Past N nothing is written: the bar never shows full while work remains."""
        self.index += 1
        if not self.quiet and self.index <= self.count:
            line = f"==> step {self.index} of {self.count} {text}"
            if self._out is None:
                print(line, flush=True)
            else:
                self._out(line)
