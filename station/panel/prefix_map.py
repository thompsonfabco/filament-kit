# Rewrites the build host's directories in __FILE__ and assert strings (-fmacro-prefix-map), so the committed
# firmware/intake-panel.bin holds no user or machine paths. The compiler sees forward-slash paths, so the maps are too.
from pathlib import Path

Import("env")  # noqa: F821  (SCons injects it)

maps = [(env.subst("$PROJECT_PACKAGES_DIR"), "PKG"), (env.subst("$PROJECT_DIR"), ".")]  # noqa: F821
for src, dst in maps:
    # both spellings: GCC on Windows prints some paths with a leading slash before the drive letter
    posix = Path(src).as_posix()
    for form in (posix, "/" + posix):
        env.Append(CCFLAGS=["-fmacro-prefix-map=%s=%s" % (form, dst)])  # noqa: F821
