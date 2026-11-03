# PlatformIO pre-script: stamp the build number (FW_BUILD) the OTA check compares.
# Uses $FW_BUILD if set (ota_publish.py sets it), else the current unix time.
# Written to a generated header that only main.cpp includes, so a new stamp
# recompiles one file instead of the whole tree (a global -D would). Also
# recorded next to firmware.bin for the publish step.
import os
import time

Import("env")  # noqa: F821  (provided by PlatformIO/SCons)

build = int(os.environ.get("FW_BUILD") or time.time())
build_dir = env.subst("$BUILD_DIR")  # noqa: F821
gen = os.path.join(build_dir, "gen")
os.makedirs(gen, exist_ok=True)
header = os.path.join(gen, "fw_build.h")
text = f"#pragma once\n#define FW_BUILD {build}L\n"
if not os.path.exists(header) or open(header).read() != text:
    with open(header, "w") as f:
        f.write(text)
env.Append(CPPPATH=[gen])  # noqa: F821
with open(os.path.join(build_dir, "fw_build.txt"), "w") as f:
    f.write(str(build))
print(f"FW_BUILD = {build}")
