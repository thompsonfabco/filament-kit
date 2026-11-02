"""Errors the profiles routes return as `{"error": code, "message": message, **extra}` with HTTP `status`."""
from __future__ import annotations


class ProfileError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra
