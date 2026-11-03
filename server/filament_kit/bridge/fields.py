"""Defensive readers for report fields (whatever the printer sent): shared by `status`, `layout` and friends."""
from __future__ import annotations

from typing import Any


def _int(v: Any, default: int | None = None) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):  # OverflowError: JSON Infinity
        return default


def _d(v: Any) -> dict:
    """`v` if it is a dict, else {}: report fields are whatever the printer sent."""
    return v if isinstance(v, dict) else {}


def _l(v: Any) -> list:
    """The dict items of `v` if it is a list, else []."""
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _s(v: Any) -> str:
    return v if isinstance(v, str) else ''
