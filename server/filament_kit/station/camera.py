"""The webcam picture of the pan taken when Hold is pressed (ffmpeg, v4l2), kept until Discard, release or a new scan and
served as GET /photo. STATION_CAMERA: a /dev/video path, `auto` = the first USB camera, or `off`."""
from __future__ import annotations

import glob
import logging
import subprocess
import time

from . import state as st

log = logging.getLogger("intake-station")


def camera_dev():
    cam = st.settings["camera"]
    if cam == "off":
        return None
    if cam != "auto":
        return cam
    cams = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))
    return cams[0] if cams else None


def take_photo(held_at):
    """A webcam picture of the pan for the Hold pressed at held_at (dropped if that hold is gone by then). Skips the
    first frames while the camera sets its exposure; 1080p MJPEG if the camera has it, else whatever it gives."""
    dev = camera_dev()
    if not dev:
        return
    grab = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2"]
    out = ["-i", dev, "-vf", r"select=gte(n\,15)", "-frames:v", "1", "-q:v", "3", "-f", "image2pipe", "-c:v", "mjpeg",
           "pipe:1"]
    jpeg, err = None, ""
    for opts in (["-input_format", "mjpeg", "-video_size", "1920x1080"], []):
        try:
            p = subprocess.run(grab + opts + out, capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            err = str(e)
            continue
        if p.returncode == 0 and p.stdout[:3] == b"\xff\xd8\xff":
            jpeg = p.stdout
            break
        err = p.stderr.decode(errors="replace").strip()
    if not jpeg:
        log.warning("camera %s: %s", dev, err)
        return
    with st.lock:
        if st.state["held_at"] == held_at:
            st.state.update(photo=jpeg, photo_at=time.time())
    log.info("photo: %d KB", len(jpeg) // 1024)
