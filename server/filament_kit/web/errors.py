"""The one error type the web tools raise on purpose: its text is shown to the caller as is (an MCP tool error or
the web app's `{"error": ...}`); anything else is logged and shown as a generic failure."""
from __future__ import annotations


class Problem(ValueError):
    """`field`: the request body's key the refusal is about, when it is about one (the web app's reply carries it)."""

    def __init__(self, message: str = "", field: str | None = None):
        super().__init__(message)
        self.field = field
