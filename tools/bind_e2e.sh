#!/bin/sh
# tools/bind_e2e.sh - end-to-end check of the bind generator against REAL mlua (the harness crate, a scratch copy):
# the register() that tools/bind_gen.py writes for rust/ is compiled into the harness and tests/e2e/bind_demo.luau is run through it.
# Skipped (exit 0, says so) when cargo is not on PATH.
set -u
cd "$(dirname "$0")/.." || exit 2
. tools/env.sh
command -v cargo >/dev/null 2>&1 || { echo "bind e2e SKIPPED, log A: no cargo on PATH (generated register() NOT compiled)"; exit 0; }
root=$(pwd)
tmp=$(mktemp -d) || exit 2
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/harness"
(cd harness && tar --exclude=./target -cf - .) | (cd "$tmp/harness" && tar -xf -)
python3 tools/bind_gen.py --root . --out "$tmp/harness/src/luau/binds_gen.rs" || exit 1
python3 - "$tmp/harness/src/luau/generated.rs" <<'PY' || exit 1
import re, sys
p = sys.argv[1]
s = open(p).read()
s2 = re.sub(r"mod binds \{.*?\n\}\n", 'mod binds {\n    include!("binds_gen.rs");\n}\n', s, count=1, flags=re.S)
if s2 == s:
    sys.exit("bind e2e: no `mod binds { .. }` in " + p)
open(p, "w").write(s2)
PY
cp tests/e2e/bind_demo.luau "$tmp/harness/test.luau"
# bind_demo.luau ends with process.exit (lune); the harness has no lune: strip it, the PASS line is what counts.
sed -i '/^process.exit/d' "$tmp/harness/test.luau"
# the harness's main fires bot events at test.luau; this script only needs Runtime::new to run it.
out=$( (cd "$tmp/harness" && CARGO_TARGET_DIR="$root/harness/target" cargo run -q 2>&1) )
status=$?
echo "$out"
echo "$out" | grep -q "E2E PASS bind_demo" || { echo "FAIL bind e2e: no PASS line"; exit 1; }
echo "$out" | grep -F '[luau]' && { echo "FAIL bind e2e: [luau] error"; exit 1; }
[ "$status" -eq 0 ] || { echo "FAIL bind e2e: cargo run exited $status"; exit 1; }
echo "bind e2e: OK"
