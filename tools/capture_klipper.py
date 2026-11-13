"""Record a Klipper printer's Moonraker answers for filament-kit (read only: GET requests only, no gcode).

Use it to fill in a printer model in klipper_hardware.xml (e.g. the Sovol M1D when it arrives) or to make test
fixtures. It writes into --out:
    objects.json  info.json  server_info.json  status.json  webcams.json  history.json (last 3 jobs)
    spoolman_status.json  server_config.json  db_namespaces.json  lane_data.json (only if present)
status.json holds print_stats, toolhead, every extruder*, heater_bed, virtual_sdcard, every gcode_macro whose name has
SPOOL / TOOL / T<n>, every AFC* object and mmu. Any key named like *key*, *token*, *password* or *secret* is dropped
from every file. The host name, IPv4 addresses, the host part of absolute URLs (webcams, spoolman) and the user
name in home paths are replaced too (printer.example, 192.0.2.1, user); --keep-addresses turns that off. Skim the
files once before sharing anyway: free text (macro names, file names) is not touched.

    python tools/capture_klipper.py --host printer.home.arpa [--port 7125] [--keep-addresses] --out DIR
(an API key, when Moonraker wants one, is read from the FK_MOONRAKER_KEY environment variable, never an argument)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRET = re.compile(r"key|token|password|secret|passwd", re.I)
HOST_OUT, IP_OUT, USER_OUT = "printer.example", "192.0.2.1", "user"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\w.])")
_URL_HOST = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://(?:[^/@\s]*@)?)(\[[0-9a-f:]+\]|[^/:?#\s]+)")
_HOME = re.compile(r"(?i)(/home/|/Users/|[A-Z]:\\Users\\|[A-Z]:/Users/)([^/\\\s\"']+)")
MACRO = re.compile(r"gcode_macro .*(SPOOL|TOOL|\bT\d+\b)", re.I)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None     # the API key must not go wherever a redirect points; the 3xx stops the capture


OPENER = urllib.request.build_opener(NoRedirect)


def scrub_text(s: str, host: str | None = None) -> str:
    """An address-free copy of a string: the capture host, URL hosts, IPv4 addresses, the user in home paths."""
    if host:
        s = re.sub(re.escape(host), HOST_OUT, s, flags=re.I)
    s = _URL_HOST.sub(lambda m: m.group(1) + HOST_OUT, s)
    s = _IPV4.sub(IP_OUT, s)
    return _HOME.sub(lambda m: m.group(1) + USER_OUT, s)


def scrub(v, host: str | None = None, addresses: bool = True, key: str = ""):
    """Drops secret-named keys; with `addresses` also scrubs strings and any `hostname` value."""
    if isinstance(v, dict):
        return {k: scrub(x, host, addresses, str(k)) for k, x in v.items() if not SECRET.search(str(k))}
    if isinstance(v, list):
        return [scrub(x, host, addresses, key) for x in v]
    if addresses and isinstance(v, str):
        return HOST_OUT if key.lower() in ("hostname", "host_name") else scrub_text(v, host)
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=7125)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-addresses", action="store_true",
                    help="keep the host name, addresses, webcam URLs and user paths (default: replace them)")
    a = ap.parse_args(argv)
    base = f"http://{a.host}:{a.port}"
    headers = {"Accept": "application/json", "User-Agent": "filament-kit capture"}
    if os.environ.get("FK_MOONRAKER_KEY"):
        headers["X-Api-Key"] = os.environ["FK_MOONRAKER_KEY"]

    def get(path, query=None):
        url = base + path + ("?" + urllib.parse.urlencode(query, safe=",") if query else "")
        with OPENER.open(urllib.request.Request(url, headers=headers), timeout=10) as r:
            return json.loads(r.read())["result"]

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    def save(name, data):
        (out / name).write_text(json.dumps(scrub(data, a.host, not a.keep_addresses), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    try:
        objects = get("/printer/objects/list")["objects"]
    except (urllib.error.URLError, OSError) as e:
        print(f"error: cannot reach Moonraker at {base}: {e}", file=sys.stderr)
        return 1
    save("objects.json", {"objects": objects})
    save("info.json", get("/printer/info"))
    save("server_info.json", get("/server/info"))
    wanted = [o for o in objects
              if o in ("print_stats", "toolhead", "heater_bed", "virtual_sdcard", "webhooks", "mmu")
              or o.startswith("extruder") or o.startswith("AFC") or MACRO.match(o)]
    save("status.json", get("/printer/objects/query", {o: "" for o in wanted})["status"])
    save("webcams.json", get("/server/webcams/list"))
    save("history.json", get("/server/history/list", {"limit": 3, "order": "desc"}))
    for name, path in (("spoolman_status.json", "/server/spoolman/status"), ("server_config.json", "/server/config")):
        try:
            data = get(path)
        except urllib.error.HTTPError as e:
            data = {"error": e.code}
        save(name, data.get("config", data) if name == "server_config.json" else data)
    ns = get("/server/database/list").get("namespaces", [])
    save("db_namespaces.json", {"namespaces": ns})
    if "lane_data" in ns:
        save("lane_data.json", get("/server/database/item", {"namespace": "lane_data"}))
    print(f"captured {len(wanted)} objects from {base} into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
