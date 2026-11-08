"""Neither server writes request lines to the journal: a query string or path can hold the PC sync's Bambu Studio user
id (PUT /api/sync/live?user_id=...) or a printer's serial."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
import uvicorn

from filament_kit import __main__ as kit_main

PKG = Path(kit_main.__file__).parent


async def _app(scope, receive, send):
    pass


def _check(options: dict) -> None:
    assert options["access_log"] is False
    cfg = uvicorn.Config(_app, **{k: v for k, v in options.items() if not k.startswith("ssl_")})
    assert cfg.access_log is False
    cfg.configure_logging()
    # uvicorn's own way to silence it: the logger has no handler left and passes nothing up
    log = logging.getLogger("uvicorn.access")
    assert log.handlers == [] and log.propagate is False


def test_the_kit_server_has_no_access_log():
    _check(kit_main.serve_options({"port": 8710}, Path("/nowhere")))


def test_the_web_unit_has_no_access_log():
    pytest.importorskip("mcp")          # the web extra
    from filament_kit.web import __main__ as web_main
    _check(web_main.uvicorn_options({"web": {"port": 8101}}))


def test_the_web_units_options_say_so_without_the_web_extra():
    src = (PKG / "web" / "__main__.py").read_text(encoding="utf-8")
    body = src[src.index("def uvicorn_options"):]
    assert re.search(r'"access_log": False', body[:body.index("\n\n")])


def test_no_other_uvicorn_server_starts_with_its_default_access_log():
    starters = [p.relative_to(PKG).as_posix() for p in PKG.rglob("*.py")
                if "uvicorn.run(" in p.read_text(encoding="utf-8") or "uvicorn.Config(" in p.read_text(encoding="utf-8")]
    assert sorted(starters) == ["__main__.py", "web/__main__.py"]
