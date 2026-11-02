"""Stands in for ffmpeg in camera tests: records its argv and a child pid, writes a playlist + one segment into
the directory of its last argument (the playlist path), then sleeps like a live remux would."""
import json
import os
import subprocess
import sys
import time

out = sys.argv[-1]
d = os.path.dirname(out)
child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(120)"])
with open(os.path.join(d, "argv.json.tmp"), "w") as f:
    json.dump({"argv": sys.argv[1:], "pid": os.getpid(), "child": child.pid}, f)
os.replace(os.path.join(d, "argv.json.tmp"), os.path.join(d, "argv.json"))
with open(os.path.join(d, "seg00000.ts"), "wb") as f:
    f.write(b"\x47" * 188)
with open(os.path.join(d, "index.m3u8.tmp"), "w") as f:
    f.write("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1.0,\nseg00000.ts\n")
os.replace(os.path.join(d, "index.m3u8.tmp"), out)
time.sleep(120)
