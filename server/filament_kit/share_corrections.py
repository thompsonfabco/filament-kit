"""The "Share corrections" setting (`label_reader.share_corrections`, design 03 section 10.5.1): whether corrections
to label readings wait on the local reader to be shared, and the root job that sets the reader the same way.

The setting is the Hub's; the reader keeps its own copy (`feedback-opt-in` in its service_config.xml), and the
v0.2.0 reader has no route to change it. So the Hub does what the module's own command does, as the module's service
user with the module's prefix, and restarts the reader's service:

    <PREFIX>/.venv/bin/filament-kit-vision config --feedback-opt-in true|false      (runuser -u filament-kit-vision)
    systemctl restart filament-kit-vision.service

Never `--feedback-endpoint`: the reader's review address is its own, and the Hub neither shows nor sets it (plan
section 8). The job is `local_intake_share` (`spoolwarden local-intake share-corrections`); the page's helper starts it
when a save changes the value, and the page can start it again when the reader's own state differs (`state`).

The reader's actual state comes from its health (`capabilities.opt_in`) or, when that does not say, from
GET /v1/feedback. Turning off may also delete what is waiting (`delete_waiting`), before the switch: the owner is asked
on the page, the reader's queue is the only copy.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from . import local_intake_install as lii, local_reader, modules

KEY = "label_reader.share_corrections"
SERVICE = "filament-kit-vision.service"


class ShareError(Exception):
    """The setting cannot be applied; the message says why and what to do."""


class DeleteFailed(ShareError):
    """Deleting the waiting corrections stopped part-way: `done` of `total` are gone, the rest are still waiting."""

    def __init__(self, done: int, total: int, why: str):
        super().__init__(f"{done} of {total} waiting corrections were deleted, then the reader failed ({why}); the "
                         "rest are still waiting")
        self.done, self.total = done, total


def saved(cfg: dict) -> bool:
    """The Hub's setting: off unless it is exactly true."""
    sec = cfg.get("label_reader") if isinstance(cfg.get("label_reader"), dict) else {}
    return sec.get("share_corrections") is True


def refusal(cfg: dict) -> str | None:
    """Why the setting cannot be turned on, or None. It needs the reader the kit installed on this machine: that one
    is configured by the job (a reader on another computer is set up there)."""
    if "local_intake" not in modules.enabled(cfg):
        return ("Share corrections needs Label Reader: On this Hub, which keeps the corrections until they are sent. "
                "Switch it on in Features")
    if lii.installed() is None:
        return ("Share corrections needs the Label Reader installed on this Hub, which keeps the corrections until "
                "they are sent (a reader on another computer is set up there)")
    return None


def actual_opt_in(cfg: dict, h: dict | None = None) -> bool | None:
    """The reader's own opt-in state, or None when it does not answer or does not say."""
    h = h if h is not None else local_reader.health(cfg)
    caps = h.get("capabilities") or {}
    if isinstance(caps.get("opt_in"), bool):
        return caps["opt_in"]
    if not caps.get("feedback"):
        return None
    try:
        return local_reader.feedback_list(cfg)["opt_in"]
    except local_reader.LocalReaderError:
        return None


def state(cfg: dict, h: dict | None = None) -> dict:
    """What the Label Reader status shows for the switch (03 10.5.1):
        {"saved": bool, "actual": bool|None, "differs": bool, "count": int|None,
         "reason": None | "off" | "not_installed" | "too_old" | "no_answer"}
    `reason` is why the switch is disabled (the page words it); `differs`: the reader is set differently from the
    Hub. `h` is a health answer already in hand."""
    out = {"saved": saved(cfg), "actual": None, "differs": False, "count": None, "reason": None}
    if "local_intake" not in modules.enabled(cfg):
        return {**out, "reason": "off"}
    if lii.installed() is None:
        return {**out, "reason": "not_installed"}
    h = h if h is not None else local_reader.health(cfg)
    caps = h.get("capabilities") or {}
    if not h.get("ok") and caps.get("known_from", "none") == "none":
        return {**out, "reason": "no_answer"}
    if not caps.get("feedback"):
        return {**out, "reason": "too_old"}
    out["actual"] = actual_opt_in(cfg, h)
    out["count"] = caps.get("count")
    out["differs"] = out["actual"] is not None and out["actual"] != out["saved"]
    return out


def delete_waiting(cfg: dict) -> int:
    """Delete every correction waiting on the reader, one by one; returns how many. Raises LocalReaderError when the
    list cannot be read (nothing was deleted) and DeleteFailed when it stops part-way (some were)."""
    entries = [e for e in local_reader.feedback_list(cfg)["entries"]
               if isinstance(e.get("id"), (str, int)) and not isinstance(e.get("id"), bool) and str(e["id"]).strip()]
    done = 0
    for e in entries:
        try:
            local_reader.feedback_delete(cfg, str(e["id"]))
        except local_reader.LocalReaderError as err:
            raise DeleteFailed(done, len(entries), str(err)) from None
        done += 1
    return done


def config_command(on: bool) -> list[str]:
    """The module's own configuration command, run as its service user. No endpoint, ever."""
    return ["runuser", "-u", lii.SERVICE_USER, "--", f"{lii.PREFIX}/.venv/bin/{lii.NAME}", "config",
            "--feedback-opt-in", "true" if on else "false"]


def restart_command() -> list[str]:
    return ["systemctl", "restart", SERVICE]


def default_run(cmd: list[str], log: Callable[[str], None]) -> int:
    """lii.default_run, started in the module's prefix when it exists (the unit's WorkingDirectory)."""
    cwd = lii.PREFIX if Path(lii.PREFIX).is_dir() else None
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         errors="replace", cwd=cwd)
    assert p.stdout is not None
    for line in p.stdout:
        log(line.rstrip("\n"))
    return p.wait()


def apply(cfg: dict, *, run: Callable[..., int] | None = None, say: Callable[[str], None] = print,
          step: Callable[[str], None] | None = None, wait: Callable[..., dict] | None = None) -> dict:
    """Set the reader to the Hub's saved value if it differs: the module's config command, a restart, a check that the
    reader now says the same. Returns {"want", "changed"}. Raises ShareError. Four counted steps (steps.Steps(4))."""
    run = run or default_run
    step = step or (lambda text: None)
    wait = wait or lii.wait_healthy
    want = saved(cfg)
    why = refusal(cfg) if want else None        # off is always allowed: the Feature may be off with the reader installed
    if why:
        raise ShareError(why)
    if not want and lii.installed() is None:
        say("No reader is installed on this Hub: nothing to switch off.")
        return {"want": False, "changed": False}
    step("Checking how the reader is set")
    h = local_reader.health(cfg)
    caps = h.get("capabilities") or {}
    if h.get("ok") and not caps.get("feedback"):
        if not want:
            say("The reader has no corrections queue: nothing to switch off.")
            return {"want": False, "changed": False}
        raise ShareError("the reader on this Hub is too old to share corrections: update it in Updates")
    if actual_opt_in(cfg, h) is want:
        say(f"The reader already has sharing of corrections {'on' if want else 'off'}.")
        return {"want": want, "changed": False}
    step(f"Setting sharing of corrections {'on' if want else 'off'} in the reader")
    rc = run(config_command(want), say)
    if rc != 0:
        raise ShareError(f"the reader's own config command failed (exit {rc}); its output is above. Nothing was "
                         "restarted")
    step("Restarting the reader")
    rc = run(restart_command(), say)
    if rc != 0:
        raise ShareError(f"the reader's service did not restart (exit {rc}); at the Hub: sudo systemctl restart {SERVICE}")
    step("Checking that the reader answers")
    h = wait(cfg)
    if not h.get("ok"):
        raise ShareError(f"the reader was set, but does not answer yet: {h.get('error')}")
    got = actual_opt_in(cfg, h)
    if got is not None and got != want:
        raise ShareError(f"the reader restarted but still has sharing of corrections {'on' if got else 'off'}")
    return {"want": want, "changed": True}
