"""What _FK_TAG_SPOOL sends for each active tool, rendered as Klipper does, with the jinja2 in Klipper's own venv: the e2e
printer has no extruder, so the real one only ever takes the no-tool branch. Usage: python render_tag_macro.py <fk_spool.cfg>"""
import re
import sys

import jinja2

text = open(sys.argv[1], encoding="utf-8").read()
body = re.search(r"\[gcode_macro _FK_TAG_SPOOL\].*?\ngcode:\n(.*?)\n\n", text, re.S).group(1)
env = jinja2.Environment("{%", "%}", "{", "}", extensions=["jinja2.ext.do"])     # as klippy/extras/gcode_macro.py does
template = env.from_string(body)


def sends(extruder):
    out = template.render(params={"ID": "7"}, printer={"toolhead": {"extruder": extruder}})
    return " ".join(out.split())


for extruder, want in (("extruder", "FK_SET_TOOL_SPOOL TOOL=0 ID=7"), ("extruder2", "FK_SET_TOOL_SPOOL TOOL=2 ID=7"),
                       ("extruder15", "FK_SET_TOOL_SPOOL TOOL=15 ID=7"), ("extruder16", "SET_ACTIVE_SPOOL ID=7"),
                       ("", "SET_ACTIVE_SPOOL ID=7")):
    got = sends(extruder)
    assert got == want, f"{extruder!r}: {got!r}, wanted {want!r}"
print("ok: _FK_TAG_SPOOL renders per active tool")
