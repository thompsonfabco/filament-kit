"""Minimal Spoolman REST client (urllib, JSON). Paths are relative to /api/v1."""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any

EXTRA_FIELDS: list[tuple[str, str, str]] = [
    ("spool", "nfc_id", "text"),
    ("spool", "prev_location", "text"),
    ("spool", "box_humidity", "float"),          # open_spool: box hygrometer % ...
    ("spool", "humidity_checked", "datetime"),   # ... and when it was read (UTC)
    ("filament", "nozzle_range", "text"),
    ("filament", "bed_range", "text"),
    ("filament", "line", "text"),
]


class SpoolmanError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Spoolman:
    def __init__(self, base_url: str, timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        url = f"{self.base_url}/api/v1/{path.lstrip('/')}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise SpoolmanError(f"spoolman {method} {path} -> {e.code}: {detail}", status=e.code) from e
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise SpoolmanError("spoolman_unreachable", status=None) from e
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as e:
            raise SpoolmanError(f"bad response from spoolman {method} {path}: not JSON", status=status) from e

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, body: Any) -> Any:
        return self._request("POST", path, body)

    def patch(self, path: str, body: Any) -> Any:
        return self._request("PATCH", path, body)

    def put(self, path: str, body: Any) -> Any:
        return self._request("PUT", path, body)

    def use(self, spool_id: int, grams: float) -> Any:
        """Record `grams` used from a spool (`PUT /spool/{id}/use`); negative grams give them back (undo)."""
        return self.put(f"spool/{int(spool_id)}/use", {"use_weight": grams})

    def ping(self) -> str:
        return self.get("info")["version"]

    def ensure_fields(self) -> list[str]:
        created: list[str] = []
        existing: dict[str, set[str]] = {}
        for entity, key, ftype in EXTRA_FIELDS:
            if entity not in existing:
                existing[entity] = {f["key"] for f in self.get(f"field/{entity}")}
            if key in existing[entity]:
                continue
            self.post(f"field/{entity}/{key}", {"name": key, "order": 0, "field_type": ftype})
            created.append(key)
        return created
