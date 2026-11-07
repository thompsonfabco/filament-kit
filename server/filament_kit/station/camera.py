"""The webcam picture of a new spool, taken when yellow is pressed at the camera step (ffmpeg, v4l2) for the server to
recognise; kept until red or a new scan and served as GET /photo. STATION_CAMERA: a /dev/video path, `auto` = the first
USB camera, or `off`."""
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


def grab_photo():
    """(JPEG, None) from the webcam, or (None, why): "no camera" or "camera failed". Skips the first frames while the
    camera sets its exposure; 1080p MJPEG if the camera has it, else whatever it gives."""
    dev = camera_dev()
    if not dev:
        return None, "no camera"
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
        return None, "camera failed"
    log.info("photo: %d KB", len(jpeg) // 1024)
    return jpeg, None
