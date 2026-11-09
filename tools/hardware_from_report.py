#!/usr/bin/env python3
"""For a maintainer: read a printer report (filament-kit's bridge/printer_report.py) and print a proposed
bambu_hardware.xml entry, with what the report proves and what it doesn't. It proposes; a person checks and commits it.

    python tools/hardware_from_report.py printer-report-XX-20261108-120000.xml
"""
from __future__ import annotations

import sys
from xml.sax.saxutils import quoteattr

from defusedxml import ElementTree


def propose(xml: bytes) -> str:
    root = ElementTree.fromstring(xml)
    if root.tag != "printer-report":
        raise ValueError("not a printer report")
    printer = root.find("printer")
    code = printer.get("model-code") if printer is not None else None
    out = [f"<!-- report from kit {root.get('kit')}, {root.get('when')}; wanted: {root.get('wanted') or 'nothing'} -->"]
    holders = [u for u in root.iterfind("layout/unit") if u.get("kind") == "ext"]
    units = [u for u in root.iterfind("layout/unit") if u.get("kind") != "ext"]
    attempts = root.findall("attempt")
    fits = [f for a in attempts for f in (a.findtext("fits") or "").split()]
    numbering = list(dict.fromkeys(fits))
    if printer is not None and printer.get("known") == "false":
        out.append(f"<model code={quoteattr(code or '?')} name=\"?\" nozzles={quoteattr(str(len(root.findall('nozzle')) or 1))}>")
        for h in holders:
            out.append(f"  <external id={quoteattr(h.get('id'))} label=\"?\"/>")
        for key in numbering:
            out.append(f"  <numbering ref={quoteattr(key)}/>")
        out.append("</model>")
    for u in units:
        if u.get("known") == "false":
            out.append(f"<!-- unknown AMS: module {u.get('module')}, id {u.get('id')}, {u.get('slots')} slots -->")
    proved = ["numbering: " + (", ".join(numbering) or "no scheme fits")] if attempts else ["no job ran: numbering unproved"]
    for a in attempts:
        proved.append(f"job {a.get('job-file')}: ended {a.get('final')}" + (f", {a.get('print-error')}" if a.get("print-error") else "")
                      + f"; sent {a.findtext('sent')}; reported {a.findtext('reported')}")
    out.append("Proves: " + "; ".join(proved))
    if len(numbering) > 1:
        out.append("Doesn't settle the numbering: more than one scheme fits. A report with a second unit would.")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1], "rb") as fh:
        print(propose(fh.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
