#!/bin/sh
# tests/run_all.sh [BIN [SERVER]] - the whole test suite.
#   1. tests/py: stdlib-only Python tests (rustdoc generator, Luau generator, bindings, Lune surface, Luau script structure).
#      Always run; need only python3 3.11+.
#   2. tests/e2e (only with BIN, a built zenpel): the Luau scripts. The azalea_* ones join a flat-world server on localhost
#      (see .github/workflows/rust.yml, jobs `lune` and `server`); LUNE_ONLY=1 runs just the lune* scripts, which need no server.
# Exit status: 0 = everything that ran passed.
set -u
cd "$(dirname "$0")/.." || exit 2
fail=0

echo "== python tests (tests/py)"
python3 -m unittest discover -s tests/py -t tests/py "${UNITTEST_ARGS:--q}" || fail=1

if [ $# -ge 1 ]; then
    echo "== e2e (tests/e2e/run.sh $*)"
    sh tests/e2e/run.sh "$@" || fail=1
else
    echo "== e2e SKIPPED: pass the path of a built zenpel to run tests/e2e (LUNE_ONLY=1 for the server-less ones)"
fi

[ "$fail" -eq 0 ] && echo "tests: OK" || echo "tests: FAILED"
exit "$fail"
