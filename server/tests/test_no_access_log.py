"""Neither server writes request lines to the journal: a query string or path can hold the PC sync's Bambu Studio user
id (PUT /api/sync/live?user_id=...) or a printer's serial."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
import uvicorn

from filament_kit import __main__ as kit_main
from filament_kit.web import __main__ as web_main


async def _app(scope, receive, send):
    pass


@pytest.mark.parametrize("options", [kit_main.serve_options({"port": 8710}, Path("/nowhere")),
                                     web_main.uvicorn_options({"web": {"port": 8101}})], ids=["kit", "web"])
def test_the_server_is_configured_without_an_access_log(options):
    assert options["access_log"] is False
    cfg = uvicorn.Config(_app, **{k: v for k, v in options.items() if not k.startswith("ssl_")})
    assert cfg.access_log is False
    cfg.configure_logging()
    # uvicorn's own way to silence it: the logger has no handler left and passes nothing up
    log = logging.getLogger("uvicorn.access")
    assert log.handlers == [] and log.propagate is False


def test_no_other_uvicorn_server_starts_with_its_default_access_log():
    pkg = Path(kit_main.__file__).parent
    starters = [p.relative_to(pkg).as_posix() for p in pkg.rglob("*.py")
                if "uvicorn.run(" in p.read_text(encoding="utf-8") or "uvicorn.Config(" in p.read_text(encoding="utf-8")]
    assert sorted(starters) == ["__main__.py", "web/__main__.py"]
