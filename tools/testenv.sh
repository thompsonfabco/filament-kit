#!/usr/bin/env bash
# The one test recipe: a builder, a reviewer, the merge gate and CI all run this, so "green" means the same at each stage.
#
#   bash tools/testenv.sh [--root] [--klipper] [--lint] [--no-retry] [--only server,pc-sync,other,get] [--workers N] [-- PYTEST-ARGS]
#
# Default: the server suite and pc-sync in parallel, then printer-pack + orca-spool-sync + the reader's tools and the get.sh end
# to end. --root adds the tests that need root (sudo without a password), --klipper the Klipper end to end (tools/e2e/klipper.sh),
# --lint shellcheck. PYTEST-ARGS go to the server suite (for example --durations=30). Every suite runs even after a failure, and
# the last lines are each suite's counts and wall time; the exit code is non-zero if any of them failed.
#
# A test that fails in the crowd of a parallel run gets one more try alone, right after. If it then passes the suite counts as
# passed, and the summary names it as FLAKY: a timing race in a test, or a real one in the code, so it's to be read, not ignored.
# --no-retry turns that off.
#
# Linux or WSL, from a tree on a Linux file system: on /mnt/c every test's file work goes through the Windows bridge. It reuses a
# venv in ~/.cache/filament-kit while server/pyproject.toml, pc-sync/pyproject.toml and the Python version stay the same, and the
# program under test is always this tree's (PYTHONPATH), never the copy in that venv, so clones can share one.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ONLY=server,pc-sync,other,get
WITH_ROOT=0
WITH_KLIPPER=0
WITH_LINT=0
RETRY=1
WORKERS=auto
SUITE_TIMEOUT=${FK_SUITE_TIMEOUT:-1500}
EXTRA=()
usage() { echo "usage: bash tools/testenv.sh [--root] [--klipper] [--lint] [--no-retry] [--only server,pc-sync,other,get] [--workers N] [-- PYTEST-ARGS]" >&2; exit 2; }
while [ $# -gt 0 ]; do
    case "$1" in
        --root) WITH_ROOT=1; shift ;;
        --klipper) WITH_KLIPPER=1; shift ;;
        --lint) WITH_LINT=1; shift ;;
        --no-retry) RETRY=0; shift ;;
        --only) [ $# -ge 2 ] || usage; ONLY=$2; shift 2 ;;
        --workers) [ $# -ge 2 ] || usage; WORKERS=$2; shift 2 ;;
        --) shift; EXTRA=("$@"); break ;;
        *) usage ;;
    esac
done
wanted() { case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

case "$ROOT" in
    /mnt/*)
        echo "error: $ROOT is on a Windows drive, where the suites crawl. Use a clone on the Linux side:" >&2
        echo "  git clone -b <branch> \"$ROOT\" ~/fk-test && bash ~/fk-test/tools/testenv.sh" >&2
        exit 2 ;;
esac
command -v python3 >/dev/null || { echo "error: python3 is missing" >&2; exit 2; }

CACHE=$HOME/.cache/filament-kit
mkdir -p "$CACHE"
key=$( { cat "$ROOT/server/pyproject.toml" "$ROOT/pc-sync/pyproject.toml"; python3 --version; } | sha256sum | cut -c1-16)
VENV=$CACHE/venv-$key
export PIP_CACHE_DIR=$CACHE/pip
(
    flock 9                                 # two runs at once: one builds, the other waits and reuses it
    if [ ! -f "$VENV/.done" ]; then
        echo "==> building the test venv ($VENV)"
        rm -rf "$VENV"
        # from a copy: pip leaves build/ in what it builds, and server/build on PYTHONPATH would hide the `build` package
        src=$(mktemp -d "$CACHE/src.XXXXXX")
        cp -r "$ROOT/server" "$ROOT/pc-sync" "$src/" \
            && python3 -m venv "$VENV" \
            && "$VENV/bin/python" -m pip install -q "$src/server[test,web]" "$src/pc-sync[test]" \
            && touch "$VENV/.done"
        rm -rf "$src"
    fi
) 9>"$CACHE/venv.lock"
[ -f "$VENV/.done" ] || { echo "error: could not build the test venv" >&2; exit 2; }

# In the home folder: /tmp can be a small tmpfs shared with everything else on the machine.
RUN=$(mktemp -d "$CACHE/run.XXXXXX")
# shellcheck disable=SC2329  # the trap below calls it
cleanup() {
    if [ "$WITH_ROOT" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then sudo -n rm -rf "$RUN/t-root"; fi
    rm -rf "$RUN"
}
trap cleanup EXIT
export PYTHONPATH=$ROOT/server:$ROOT/pc-sync
export PYTHONDONTWRITEBYTECODE=1

SUMMARY=()
FAILED=0
# run NAME DIR COMMAND...: tee its output, keep its counts and time
run() {
    local name=$1 dir=$2 start=$SECONDS rc counts
    shift 2
    FAILED_BEFORE=$FAILED
    if [ "${SUITE_NAME:-}" != "$name" ]; then SUITE_NAME=$name; SUITE_START=$start; fi
    echo
    echo "==> $name"
    (cd "$dir" && timeout "$SUITE_TIMEOUT" "$@") 2>&1 | tee "$RUN/$name.log"
    rc=${PIPESTATUS[0]}
    counts=$(grep -E '[0-9]+ (passed|failed|error|errors|skipped)' "$RUN/$name.log" | tail -n 1 | sed -E 's/^=+ *//; s/ *=+$//; s/ in [0-9.]+s.*$//')
    [ -n "$counts" ] || counts="$(grep -c '^ok ' "$RUN/$name.log") checks ok"
    [ "$rc" -eq 0 ] || FAILED=1
    [ "$rc" -ne 124 ] || counts="timed out after ${SUITE_TIMEOUT}s"
    LAST_RC=$rc
    LAST_COUNTS=$counts
    SUMMARY+=("$(printf '%-5s %-10s %5ss  %s' "$([ "$rc" -eq 0 ] && echo ok || echo FAIL)" "$name" "$((SECONDS - start))" "$counts")")
}
PYTEST=("$VENV/bin/python" -m pytest -q -rfEs -p no:cacheprovider)
FLAKY=()

# parallel NAME DIR [PYTEST-ARGS]: run, and what failed once more alone, with its names kept for the summary
parallel() {
    local name=$1 dir=$2 ids
    shift 2
    run "$name" "$dir" "${PYTEST[@]}" -n "$WORKERS" --basetemp="$RUN/t-$name" "$@"
    [ "$RETRY" -eq 1 ] && [ "${LAST_RC:-0}" -eq 1 ] || return 0
    mapfile -t ids < <(grep -E '^(FAILED|ERROR) ' "$RUN/$name.log" | sed -E 's/^(FAILED|ERROR) //; s/ - .*$//')
    [ "${#ids[@]}" -gt 0 ] || return 0
    local first=$FAILED_BEFORE
    FAILED=$first
    unset 'SUMMARY[-1]'
    local kept=$LAST_COUNTS
    run "$name" "$dir" "${PYTEST[@]}" --basetemp="$RUN/t-$name-again" "${ids[@]}"
    unset 'SUMMARY[-1]'
    if [ "$LAST_RC" -eq 0 ]; then
        FLAKY+=("${ids[@]}")
        SUMMARY+=("$(printf '%-5s %-10s %5ss  %s; %s passed only alone' ok "$name" "$((SECONDS - SUITE_START))" "$kept" "${#ids[@]}")")
    else
        SUMMARY+=("$(printf '%-5s %-10s %5ss  %s; alone: %s' FAIL "$name" "$((SECONDS - SUITE_START))" "$kept" "$LAST_COUNTS")")
    fi
}

if wanted server; then
    parallel server "$ROOT/server" "${EXTRA[@]}"
fi
if wanted pc-sync; then
    parallel pc-sync "$ROOT/pc-sync"
fi
if wanted other; then
    run other "$ROOT" "${PYTEST[@]}" --basetemp="$RUN/t-other" printer-pack/tests integrations/orca-spool-sync/tests reader/tools
fi
if wanted get; then
    run get "$ROOT" "$VENV/bin/python" tools/test_get_e2e.py
fi
if [ "$WITH_ROOT" -eq 1 ]; then
    SUDO=()
    [ "$(id -u)" -eq 0 ] || SUDO=(sudo -n env "PYTHONPATH=$PYTHONPATH" PYTHONDONTWRITEBYTECODE=1)
    run root "$ROOT/server" "${SUDO[@]}" "${PYTEST[@]}" --basetemp="$RUN/t-root" tests/test_root_links.py
fi
if [ "$WITH_KLIPPER" -eq 1 ]; then
    run klipper "$ROOT" bash tools/e2e/klipper.sh
fi
if [ "$WITH_LINT" -eq 1 ]; then
    run shellcheck "$ROOT" bash -c 'shellcheck install/*.sh tools/*.sh printer-pack/*.sh tools/e2e/*.sh && echo "0 errors"'
fi

echo
echo "==> summary"
printf '%s\n' "${SUMMARY[@]}"
for t in "${FLAKY[@]}"; do echo "FLAKY $t"; done
exit "$FAILED"
