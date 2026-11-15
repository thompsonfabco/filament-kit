"""The corrections waiting to be shared ("Share corrections"): the Hub's thin pass-through to the local reader's queue
(local_reader.feedback_*), one set of functions for the setup page, the phone app's API and the phone web app. The queue
lives in the reader; the Hub keeps nothing, and the upload is the reader's own (the Send job, `filament-kit local-intake
corrections send`, only asks the reader to do it: the Hub names no address and makes no new outbound connection).

    waiting(cfg)          {opt_in, endpoint_configured, count, bytes, bundle_mb, capabilities, entries}
    remove(cfg, id)       {ok, removed: id}
    remove_all(cfg)       {ok, removed: n}
    package(cfg)          the zip the reader would send, exactly (bytes) and the name to save it as
    send(cfg)             asks the reader to send what waits; {ok, sent}

Every failure is a CorrectionsError(status, code, text): the text is the Hub's words (shown as they are), the codes are
no_reader | no_feedback | unreachable | unauthorized | feedback_disabled | empty | not_found | too_large |
upload_failed | conflict | reader_error."""
from __future__ import annotations

import time

from . import local_reader, modules

NO_READER = ("The Label Reader: On this Hub is not on, so there are no corrections waiting. Turn it on in Features "
             "first.")
NO_FEEDBACK = ("This Label Reader is too old to keep corrections for sharing. Update it, then try again.")
UNREACHABLE = "The reader does not answer, so the corrections waiting cannot be reached. They are kept."
FEEDBACK_OFF = "Share corrections is switched off in the reader. Switch it on first."
EMPTY = "No corrections are waiting."
NOT_FOUND = "That correction is not waiting any more."
TOO_LARGE = "The corrections waiting are too big to make one package. Remove some, then try again."
UPLOAD_FAILED = "The reader could not send the corrections. They are still waiting; try again later."
UNAUTHORIZED = "The reader did not accept the Hub's token. Set the token again in Settings > Label Reader."

# the client's error kinds, in the Hub's refusal style: (status, code, text); None keeps the reader's own sentence
_MAP = {"unreachable": (503, "unreachable", UNREACHABLE), "unauthorized": (502, "unauthorized", UNAUTHORIZED),
        "feedback_disabled": (409, "feedback_disabled", FEEDBACK_OFF), "empty": (409, "empty", EMPTY),
        "not_found": (404, "not_found", NOT_FOUND), "too_large": (413, "too_large", TOO_LARGE),
        "upload_failed": (502, "upload_failed", UPLOAD_FAILED),
        "conflict": (409, "conflict", "The reader already has this correction.")}


class CorrectionsError(Exception):
    def __init__(self, status: int, code: str, text: str, **extra):
        super().__init__(text)
        self.status, self.code, self.extra = status, code, extra


def _wrap(e: local_reader.LocalReaderError) -> CorrectionsError:
    status, code, text = _MAP.get(e.code) or (502, "reader_error", f"The reader refused: {e}")
    return CorrectionsError(status, code, text)


def _ready(cfg: dict) -> dict:
    """The reader's capabilities when it is on, answers and has the correction queue: else the refusal that says which."""
    if "local_intake" not in modules.enabled(cfg):
        raise CorrectionsError(409, "no_reader", NO_READER)
    h = local_reader.health(cfg)
    if h["api_version"] is None:
        raise CorrectionsError(503, "unreachable", UNREACHABLE)
    if not h["capabilities"]["feedback"]:
        raise CorrectionsError(409, "no_feedback", NO_FEEDBACK)
    return h["capabilities"]


def waiting(cfg: dict) -> dict:
    caps = _ready(cfg)
    try:
        out = local_reader.feedback_list(cfg)
    except local_reader.LocalReaderError as e:
        raise _wrap(e) from None
    return {**out, "bytes": round(out["bundle_mb"] * 1048576), "capabilities": caps}


def remove(cfg: dict, entry_id: str) -> dict:
    _ready(cfg)
    try:
        local_reader.feedback_delete(cfg, entry_id)
    except local_reader.LocalReaderError as e:
        raise _wrap(e) from None
    return {"ok": True, "removed": str(entry_id)}


def remove_all(cfg: dict) -> dict:
    """Every waiting correction, one by one; a failure part-way says how many went (`removed` in the refusal)."""
    _ready(cfg)
    try:
        ids = [str(e.get("id")) for e in local_reader.feedback_list(cfg)["entries"] if e.get("id") is not None]
    except local_reader.LocalReaderError as e:
        raise _wrap(e) from None
    done = 0
    for eid in ids:
        try:
            local_reader.feedback_delete(cfg, eid)
        except local_reader.LocalReaderError as e:
            if e.code == "not_found":           # taken out by another phone meanwhile: it is gone, as wanted
                done += 1
                continue
            err = _wrap(e)
            err.extra["removed"] = done
            raise err from None
        done += 1
    return {"ok": True, "removed": done}


def package(cfg: dict) -> tuple[bytes, str]:
    """(the zip, the file name to save it as): the exact file Send would send."""
    _ready(cfg)
    try:
        data = local_reader.feedback_bundle(cfg)
    except local_reader.LocalReaderError as e:
        raise _wrap(e) from None
    return data, f"spoolwarden-corrections-{time.strftime('%Y-%m-%d')}.zip"


def send(cfg: dict) -> dict:
    """Ask the reader to send what waits, to wherever it sends it itself. Nothing but the API version goes along."""
    _ready(cfg)
    try:
        out = local_reader.feedback_submit(cfg)
    except local_reader.LocalReaderError as e:
        raise _wrap(e) from None
    sent = out.get("sent")
    return {"ok": True, "sent": sent if isinstance(sent, int) and not isinstance(sent, bool) else None}
