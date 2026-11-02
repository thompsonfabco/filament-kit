"""The PN532 NFC reader through nfcpy (NFC_DEVICE, default auto: the first ttyUSB port the button panel isn't on).
Tag ids are formatted by `tags.format_uid` like nfc2klipper's ("4:77:90:e:9:22:89"), so they match Spoolman's
extra.nfc_id."""
from __future__ import annotations

import logging
import time

from .. import tags
from . import beep
from . import state as st

log = logging.getLogger("intake-station")


def nfc_path():
    """nfcpy's path for the reader: NFC_DEVICE, or (auto) the first ttyUSB port the panel isn't on."""
    if st.settings["nfc_device"] != "auto":
        return st.settings["nfc_device"]
    st.probed.wait(15)
    ttys = st.usb_ttys()
    if st.ports["nfc"] in ttys and st.ports["nfc"] != st.ports["panel"]:
        dev = st.ports["nfc"]  # keep the claim across retries so the panel search never opens it
    else:
        dev = next((p for p in ttys if p != st.ports["panel"]), None)
    st.ports["nfc"] = dev
    return f"tty:{dev[len('/dev/tty'):]}:pn532" if dev else None


def on_tag(nfc_id):
    with st.lock:
        st.state.update(tag=nfc_id, tag_at=time.time(), held=None, held_at=None, suppress=False, photo=None,
                        photo_at=None)
    log.info("tag %s", nfc_id)
    beep.beep("scan")
    st.panel_dirty.set()


def on_identifier(identifier: bytes):
    on_tag(tags.format_uid(identifier))


def nfc_loop():
    """Poll the PN532 like nfc2klipper does: one read per tap, then wait for the tag to leave the field."""
    import nfc  # the [station] extra; only the reader loop needs it
    from nfc.clf import RemoteTarget
    while True:
        path = nfc_path()
        try:
            if not path:
                raise OSError("no USB serial port for the reader")
            with nfc.ContactlessFrontend(path) as clf:
                log.info("NFC reader open: %s", clf)
                while True:
                    tag = clf.connect(rdwr={"on-connect": lambda tag: False})
                    if tag and tag.identifier:
                        on_identifier(tag.identifier)
                        while clf.sense(RemoteTarget("106A"), RemoteTarget("106B"), RemoteTarget("212F")):
                            time.sleep(0.2)
                    else:
                        time.sleep(0.2)
        except Exception as e:  # reader unplugged or not there yet
            log.warning("NFC reader %s: %s; retrying in 5 s", path, e)
            time.sleep(5)
