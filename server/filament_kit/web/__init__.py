"""Web unit (merge-ops, module `web`): the filament-kit-web.service process on web.port (8101).

  app.py         the ASGI app: the remote MCP endpoint (+ OAuth), /login, /health and the phone intake app
  auth.py        OAuth provider and store, passphrase and lockout, the LAN-only wrapper, cookie sessions
  intake_app.py  the phone intake app (PWA, ported from filament-ops), on the same tools as MCP
  mcp_tools.py   the MCP tools; presets.py (preset lines) and slots.py (printer AMS slots) behind them
  reader.py      the Printer Station reader API (/reader/...), its tokens and the queue-on-empty
  errors.py      the one error type whose text the caller sees
  __main__.py    `python -I -m filament_kit.web`: what the unit runs (plain HTTP on 127.0.0.1)

Only this package imports the `mcp` SDK (extra `[web]`, pinned): the server process never does."""
