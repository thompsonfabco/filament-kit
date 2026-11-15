"""The one error type the web tools raise on purpose: its text is shown to the caller as is (an MCP tool error or
the web app's `{"error": ...}`); anything else is logged and shown as a generic failure."""
from __future__ import annotations


class Problem(ValueError):
    """`field`: the request body's key the refusal is about, when it is about one (the web app's reply carries it).
    `param`: the same for the phone routes of /api/profiles, which name their own fields; the web replies ignore it."""

    def __init__(self, message: str = "", field: str | None = None, param: str | None = None):
        super().__init__(message)
        self.field = field
        self.param = param


class TapChanged(Problem):
    """The readers' last tap is no longer the one the caller looked at (a spool opened with `nfc_id` / `read_at`): the web app
    answers 409 with `code` "tap_changed" and shows the text at the tag line."""
    def __init__(self, message: str = "", code: str = "tap_changed"):
        super().__init__(message)
        self.code = code            # "tap_changed" (another tag), or "tap_again" (the same tag, tapped again)
