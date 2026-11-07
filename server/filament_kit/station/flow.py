"""The intake flow on the button panel (the owner's spec, 2026-11-06): red = cancel, yellow = advance, long yellow =
save. Ported from filament-ops' intake_station.py (panel sync 5).

idle -> (tag) lookup -> camera (new tag) -> (yellow) recognising -> weigh -> (yellow) ready -> (long yellow) saving
-> done. A linked tag skips the camera (lookup -> weigh). "phone": the server or its AI can't help, use the phone app.

The kit server does the thinking, statelessly (filament_kit/station_flow.py on the server): `server_api.ServerApi`
looks the tag up, recognises the photo (local AI, then Claude) and saves; every answer carries `display`, ready-made
OLED lines. The station keeps the flow: which step, the spool or recognised filament, the photo and the taken weight.
A sequence number drops any server answer that comes back after red or a new scan.

Timeouts: any step goes back to idle after STATION_FLOW_TIMEOUT (600 s) with no progress, and done after
DONE_SECONDS; a recognition waits up to STATION_RECOGNISE_TIMEOUT (90 s).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import unicodedata

from . import beep, camera, server_api, speech
from . import state as st

log = logging.getLogger("intake-station")

# Lamps (yellow = Hold, red = Discard), modes 0 off, 1 on, 2 blink, 3 three blinks, 4 rapid blink
STEP_LAMPS = {"idle": (0, 0), "lookup": (4, 1), "camera": (2, 1), "recognising": (4, 1), "weigh": (2, 1),
              "ready": (1, 1), "saving": (4, 1), "done": (3, 0), "phone": (0, 1)}
DONE_SECONDS = 10  # done -> idle
TITLE_WIDTH, LINE_WIDTH = 16, 21  # the OLED's title row (bold) and body rows (6x10 font)

flow = st.flow


def ascii_text(text, width=LINE_WIDTH):
    """The panel's fonts are Latin-1 and its lines 21 characters: plain ASCII, cut to width."""
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()[:width]


# ---- the kit server: one ServerApi, built again when `filament-kit station pair` rewrites the pairing files -------

_api: dict = {"key": None, "api": None}


def _mtime(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def api() -> server_api.ServerApi:
    key = (_mtime(server_api.server_file()), _mtime(server_api.token_file()))
    if _api["api"] is None or _api["key"] != key:
        _api.update(key=key, api=server_api.ServerApi(timeout=st.settings["recognise_timeout"]))
    return _api["api"]


def spawn(fn, *args):
    """Run a server call off the reader / panel thread (tests run it inline)."""
    threading.Thread(target=fn, args=args, daemon=True).start()


# ---- the steps -----------------------------------------------------------------------------------------------------

def go(step, seq=None, **kw):
    """Move the flow to step (only if it is still on attempt seq, when given: a red press or a new tag since then
    drops the late result). Returns False if dropped."""
    with st.lock:
        if seq is not None and seq != flow["seq"]:
            return False
        flow.update(step=step, at=time.time(), message=kw.pop("message", ""), **kw)
    st.panel_dirty.set()
    return True


def weight_now():
    """The scale's reading if it is a settled spool (stable, over MIN_GRAMS), else None (callers hold the lock)."""
    sc = st.state["scale"]
    return sc["grams"] if sc and sc["status"] == "stable" and sc["grams"] >= st.MIN_GRAMS else None


def on_tag(nfc_id):
    """A tap, in any step: start over with this tag and ask the server about it."""
    with st.lock:
        flow["seq"] += 1
        seq = flow["seq"]
        st.state.update(tag=nfc_id, tag_at=time.time(), held=None, held_at=None, photo=None, photo_at=None)
        flow.update(spool=None, filament=None, display=[])
    log.info("tag %s", nfc_id)
    beep.beep("scan")
    go("lookup")
    spawn(lookup, seq, nfc_id)


def lookup(seq, nfc_id):
    """Is the tag on a spool already? Known: straight to weighing. New: show the spool to the camera."""
    status, r = api().tag_lookup(nfc_id)
    d = r.get("display") or []
    if status == 200 and r.get("known"):
        if go("weigh", seq, spool=r.get("spool"), display=d):
            speech.say("Known spool. Put it on the scale.")
    elif status == 200:
        if go("camera", seq, display=[]):
            speech.say("New tag. Show the spool to the camera.")
    elif go("phone", seq, display=d):
        speech.say("The server can't help. Use the phone.")


def recognise(seq, nfc_id):
    """Picture -> the server's recognition (local AI, then Claude): the filament, or why not."""
    jpeg, err = camera.grab_photo()
    if not jpeg:
        if err == "no camera":
            go("phone", seq, display=["No camera"])
        else:
            go("camera", seq, message="Camera failed, retry")
        beep.beep("nothing")
        return
    with st.lock:
        if seq != flow["seq"]:
            return
        st.state.update(photo=jpeg, photo_at=time.time())
    status, r = api().recognize(jpeg, nfc_id)
    d = r.get("display") or []
    if status == 200:  # low confidence too: its "?" is in the display, and the save still goes through
        if go("weigh", seq, filament=r.get("item"), display=d):
            beep.beep("hold")
            speech.say(" ".join(d[:2]) + ". Put it on the scale." if d else "Recognised. Put it on the scale.")
    elif status == 409:  # no recognizer: neither local AI nor Claude
        if go("phone", seq, display=d):
            speech.say("No recognition available. Use the phone.")
    elif go("camera", seq, message=d[0] if d else "No match, retry"):  # no match, failed, cap, unreachable
        beep.beep("nothing")
        speech.say("Not recognised. Try again.")


def save(seq):
    """The long press: the server updates the linked spool's weight, or adds the recognised one and links the tag."""
    with st.lock:
        sp = flow["spool"] or {}
        body = {"uid": st.state["tag"], "gross_g": st.state["held"]}
        # the filament exactly as recognize gave it (its `item`); the server takes "filament" or "item"
        body.update({"spool_id": sp["id"]} if sp.get("id") else {"filament": flow["filament"]})
    status, r = api().save(body)
    d = r.get("display") or []
    if status == 200:
        if go("done", seq, display=d or ["Saved"]):
            beep.beep("hold")
            speech.say("Saved.")
    elif go("ready", seq, message=d[0] if d else "Save failed"):
        beep.beep("nothing")
        speech.say("Save failed.")


def on_yellow(long_press):
    """Yellow: take the picture (new tag), take the weight, or (long press, weight taken) save."""
    with st.lock:
        step, seq, nfc_id = flow["step"], flow["seq"], st.state["tag"]
    log.info("yellow %s at %s", "long" if long_press else "press", step)
    if long_press and step == "ready":
        go("saving", seq)
        spawn(save, seq)
    elif not long_press and step == "camera":
        go("recognising", seq)
        spawn(recognise, seq, nfc_id)
    elif not long_press and step in ("weigh", "ready"):
        with st.lock:
            grams = weight_now()
            if grams is not None:
                st.state.update(held=grams, held_at=time.time())
        if grams is None:
            go(step, seq, message="Scale not settled")
            beep.beep("nothing")
            speech.say("Put the spool on the scale and wait for it to settle.")
        else:
            go("ready", seq)
            beep.beep("hold")
            speech.say(f"{grams:.0f} grams. Hold yellow to save.")
    else:  # a long press outside ready, or a press while waiting on the server
        beep.beep("nothing")
        if step in ("idle", "done", "phone"):
            go(step, seq, message="Scan a tag first")


def reset():
    """Forget the scan, weight, picture and flow (callers hold the lock)."""
    flow["seq"] += 1
    st.state.update(tag=None, tag_at=None, held=None, held_at=None, photo=None, photo_at=None)
    flow.update(spool=None, filament=None, display=[])


def on_red():
    """Red: start over, from any step."""
    with st.lock:
        busy = flow["step"] != "idle"
        reset()
        st.state["blink_until"] = time.time() + 0.7 if busy else 0
    log.info("red: reset")
    go("idle")
    beep.beep("discard" if busy else "nothing")
    if busy:
        speech.say("Cancelled.")


def flow_tick(now):
    """Timeouts: back to idle after STATION_FLOW_TIMEOUT of no progress, or DONE_SECONDS after a save."""
    with st.lock:
        step, at = flow["step"], flow["at"]
        if step == "idle" or now - at <= (DONE_SECONDS if step == "done" else st.settings["flow_timeout"]):
            return
        reset()
    log.info("flow timeout at %s", step)
    go("idle")


def lamps(now):
    """(yellow, red) lamp modes for the step; red blinks three times after a cancel."""
    with st.lock:
        y, r = STEP_LAMPS[flow["step"]]
        if now < st.state["blink_until"]:
            r = 3
    return y, r


def screen():
    """The display's five rows (title, 4 body lines) for the current step; the panel adds room air at the bottom.
    The server's display lines fill the title and body rows 1-2; rows 3-4 are the station's hint and message."""
    with st.lock:
        f, held = dict(flow), st.state["held"]
    what = f["spool"] or f["filament"] or {}
    d = [x for x in f["display"] if x] or [
        "Spool #%s" % what["id"] if f["spool"] and what.get("id") else "Recognised",
        " ".join(x for x in (what.get("vendor"), what.get("name")) if x), what.get("material") or ""]
    d += ["", "", ""]
    step, msg = f["step"], f["message"]
    rows = {
        "idle": ["Ready", "Scan a spool's tag", "", "", msg],
        "lookup": ["Tag scanned", "Looking it up...", "", "", ""],
        "camera": ["New Tag Scanned", "Show the spool to", "the camera, then", "press yellow", msg],
        "recognising": ["Recognising...", "Please wait", "", "", "Red cancels"],
        "weigh": [d[0], d[1], d[2], "Scale, then yellow", msg],
        "ready": ["%.0f g" % held if held is not None else "-", d[0], d[1], "Hold yellow: save", msg],
        "saving": ["Saving...", d[0], d[1], "", ""],
        "done": [d[0], d[1], d[2], "", ""],
        "phone": ["Use phone"] + [x for x in d if x.lower() != "use phone"][:2] + ["Red: start over", ""],
    }[step]
    return [ascii_text(rows[0], TITLE_WIDTH)] + [ascii_text(r) for r in rows[1:]]

