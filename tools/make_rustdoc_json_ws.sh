#!/bin/sh
# tools/make_rustdoc_json_ws.sh WORKSPACE_DIR OUT_DIR [CRATE_NAME ...]
# Document every library crate of a cargo workspace (real azalea: a checkout of github.com/azalea-rs/azalea) to rustdoc JSON, in
# dependency order (path dependencies inside the workspace first), into ONE directory: `<lib>.json` + `<lib>.meta` per crate. That
# directory is what the generator reads as `AZALEA_RDJ=<OUT_DIR>` / `--rustdoc <OUT_DIR>`; the crate JSONs refer to each other
# (`azalea` re-exports `azalea_client`, `azalea_core`, ...), so they must all be made with the SAME toolchain.
#
#   AZALEA_RDJ=/tmp/azalea-rdj sh tools/make_rustdoc_json_ws.sh /tmp/azalea-src "$AZALEA_RDJ"
#   RUSTUP_TOOLCHAIN=nightly-2026-06-01 sh tools/make_rustdoc_json_ws.sh /tmp/azalea-src /tmp/azalea-rdj azalea azalea_client
#
# With CRATE_NAME arguments only those packages (package names, `-` or `_`) are documented, still in dependency order. Nothing is
# vendored/offline here: your own toolchain and network are used (azalea needs the nightly its rust-toolchain.toml names; the
# rustdoc JSON format_version the front end accepts is in tools/rdj.py FORMAT_ACCEPTED). This script has only been run against
# shims in the sandbox that wrote it (no cargo, no network): the first real run on azalea is the user's.
# Env: AZL_WS_SKIP  space-separated package names to leave out (default: none)
#      AZL_RDJ_MAKE the per-crate script (default tools/make_rustdoc_json.sh; the selftest points it at a recorder)
#      everything make_rustdoc_json.sh reads (AZL_RDJ_TARGET, AZL_RDJ_PRIVATE, AZL_RDJ_EXTRA, ...) passes through
# Exit: 0 all documented, 1 some crate failed (the others are still written, failures listed), 2 usage / no workspace.
set -u

if [ $# -lt 2 ]; then
    sed -n '2,/^# Exit:/p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
fi
ws=$(cd "$1" 2>/dev/null && pwd) || { echo "make_rustdoc_json_ws: no such workspace dir: $1" >&2; exit 2; }
[ -f "$ws/Cargo.toml" ] || { echo "make_rustdoc_json_ws: no Cargo.toml in $ws" >&2; exit 2; }
mkdir -p "$2" || exit 2
out=$(cd "$2" && pwd) || exit 2
shift 2
want="$*"

here=$(cd "$(dirname "$0")/.." && pwd) || exit 2
make=${AZL_RDJ_MAKE:-$here/tools/make_rustdoc_json.sh}
# own toolchain and network: never the vendored offline registry of tools/env.sh
AZL_RDJ_ENV=0; AZL_RDJ_OFFLINE=0; export AZL_RDJ_ENV AZL_RDJ_OFFLINE

meta=$(cargo metadata --manifest-path "$ws/Cargo.toml" --no-deps --format-version 1) \
    || { echo "make_rustdoc_json_ws: cargo metadata failed in $ws" >&2; exit 2; }

# "<package>\t<crate dir>" lines, dependencies first (Kahn's algorithm, ties alphabetical), library packages only.
order=$(printf '%s' "$meta" | python3 -c '
import json, os, sys
meta = json.load(sys.stdin)
want = {w.replace("-", "_") for w in sys.argv[1].split()}
skip = {w.replace("-", "_") for w in sys.argv[2].split()}
members = set(meta.get("workspace_members") or [])
pk = {}
for p in meta["packages"]:
    if members and p["id"] not in members:
        continue
    if not any(k in ("lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro") for t in p["targets"] for k in t["kind"]):
        continue
    n = p["name"].replace("-", "_")
    if n in skip or (want and n not in want):
        continue
    pk[n] = p
missing = want - set(pk)
if missing:
    sys.stderr.write("make_rustdoc_json_ws: no library package named: %s\n" % ", ".join(sorted(missing)))
    sys.exit(3)
deps = {n: {d["name"].replace("-", "_") for d in p["dependencies"] if d["name"].replace("-", "_") in pk and d["name"].replace("-", "_") != n} for n, p in pk.items()}
done, out = set(), []
while len(out) < len(pk):
    ready = sorted(n for n in pk if n not in done and deps[n] <= done)
    if not ready:
        sys.stderr.write("make_rustdoc_json_ws: dependency cycle among: %s\n" % ", ".join(sorted(set(pk) - done)))
        sys.exit(3)
    done.add(ready[0])
    out.append(ready[0])
for n in out:
    print("%s\t%s" % (n, os.path.dirname(pk[n]["manifest_path"])))
' "$want" "${AZL_WS_SKIP:-}") || exit 2
[ -n "$order" ] || { echo "make_rustdoc_json_ws: no library crates to document in $ws" >&2; exit 2; }

failed=""
count=0
while IFS="$(printf '\t')" read -r name dir; do
    echo "== $name ($dir)"
    count=$((count + 1))
    if ! sh "$make" "$dir" "$out"; then
        failed="$failed $name"
    fi
done <<EOF
$order
EOF

if [ -n "$failed" ]; then
    echo "make_rustdoc_json_ws: failed:$failed (of $count crates); JSON of the others is in $out" >&2
    exit 1
fi
echo "make_rustdoc_json_ws: $count crates -> $out (use: AZALEA_RDJ=$out)"
