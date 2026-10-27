#!/bin/sh
# tools/make_rustdoc_json.sh CRATE_DIR OUT_DIR
# Document one crate to rustdoc JSON and copy `<lib name>.json` into OUT_DIR, plus a `<lib name>.meta` sidecar (rustc,
# format_version, private_items, source_sha1 of the crate's sources). Prints the rustc version and the JSON's
# format_version (the rustdoc front end accepts a pinned range of those), then the file written.
#
#   sh tools/make_rustdoc_json.sh harness/fake/azalea /tmp/rdj
#
# Toolchain: tools/env.sh (stable unless a nightly is installed). Stable rustc works because RUSTC_BOOTSTRAP=1 is set for
# the one cargo call below and never exported. Real azalea needs nightly + hundreds of deps, so it cannot be documented
# here; its JSON is made by tools/make_rustdoc_json_ws.sh on the user's machine (AZALEA_RDJ).
# Env: AZL_RDJ_TARGET  cargo target dir (default /tmp/azl-rdj-target; JSON lands in $AZL_RDJ_TARGET/doc)
#      AZL_RDJ_PRIVATE 1 (default) = --document-private-items: private items/fields/modules are in the JSON with their
#                      `visibility`, so the front end can fill `is_pub` and `mod_pub`; 0 = public API only
#      AZL_RDJ_EXTRA   extra rustdoc flags after `--output-format json` (word-split), e.g. --document-hidden-items
#      AZL_RDJ_FEATURES cargo feature flags (word-split), default `--all-features`. Each crate is documented ALONE, so a feature that
#                      only a dependent turns on stays off and `#[cfg(feature)]` items vanish from the JSON: azalea-entity's whole
#                      `pub mod metadata` (~470 ECS components such as `Pose`, `ArmadilloState`, and the types only they reach) is
#                      `#[cfg(feature = "bevy_ecs")]`, which only azalea-client enables. `none` = cargo's default features only.
#      AZL_RDJ_ENV     0 = do not source tools/env.sh: use your own cargo/toolchain, e.g. real azalea
#                      with RUSTUP_TOOLCHAIN=nightly (make_rustdoc_json_ws.sh sets this); default 1
#      AZL_RDJ_OFFLINE 0 = no `--offline` (cargo may fetch dependencies); default 1
# Exit: 0 ok, 1 cargo/JSON failure, 2 usage.
set -u

if [ $# -ne 2 ]; then
    sed -n '2,/^# Exit:/p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
fi
crate=$(cd "$1" 2>/dev/null && pwd) || { echo "make_rustdoc_json: no such crate dir: $1" >&2; exit 2; }
[ -f "$crate/Cargo.toml" ] || { echo "make_rustdoc_json: no Cargo.toml in $crate" >&2; exit 2; }
mkdir -p "$2" || exit 2
out=$(cd "$2" && pwd) || exit 2

cd "$(dirname "$0")/.." || exit 2
[ "${AZL_RDJ_ENV:-1}" = 0 ] || . tools/env.sh
offline=--offline
[ "${AZL_RDJ_OFFLINE:-1}" = 1 ] || offline=

features=${AZL_RDJ_FEATURES---all-features}
[ "$features" != none ] || features=
target=${AZL_RDJ_TARGET:-/tmp/azl-rdj-target}
mkdir -p "$target"

# The lib target's name is the JSON file name (`[lib] name`, else the package name; '-' -> '_').
lib=$(cargo metadata --manifest-path "$crate/Cargo.toml" --no-deps --format-version 1 2>/dev/null | python3 -c '
import json, os, sys
want = os.path.realpath(sys.argv[1])
for p in json.load(sys.stdin)["packages"]:
    if os.path.realpath(p["manifest_path"]) != want:
        continue
    for t in p["targets"]:
        if any(k in ("lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro") for k in t["kind"]):
            print(t["name"].replace("-", "_"))
            sys.exit(0)
' "$crate/Cargo.toml" 2>/dev/null)
if [ -z "$lib" ]; then
    lib=$(basename "$crate" | tr '-' '_')
    echo "make_rustdoc_json: cargo metadata gave no lib target, assuming '$lib'" >&2
fi

rm -f "$target/doc/$lib.json"        # a stale file must never pass for a fresh one
priv=--document-private-items   # a rustdoc flag: `cargo rustdoc` has no such cargo option
[ "${AZL_RDJ_PRIVATE:-1}" = 1 ] || priv=
log="$target/make_rustdoc_json.$lib.log"
# RUSTC_BOOTSTRAP=1 only for this command (stable rustc may then use `-Z unstable-options`).
# shellcheck disable=SC2086
RUSTC_BOOTSTRAP=1 CARGO_TARGET_DIR="$target" cargo rustdoc --manifest-path "$crate/Cargo.toml" --lib $features $offline \
    -- -Z unstable-options --output-format json $priv ${AZL_RDJ_EXTRA:-} > "$log" 2>&1
status=$?
if [ "$status" -ne 0 ]; then
    tail -n 40 "$log" >&2
    echo "make_rustdoc_json: cargo rustdoc failed ($status), full log: $log" >&2
    exit 1
fi
json="$target/doc/$lib.json"
[ -f "$json" ] || { echo "make_rustdoc_json: cargo succeeded but $json was not written (log: $log)" >&2; exit 1; }

# `format_version` is the last key rustdoc writes; fall back to a full parse if a future rustdoc reorders them.
fv=$(tail -c 4096 "$json" | grep -o '"format_version": *[0-9]*' | tail -n 1 | grep -o '[0-9]*$')
[ -n "$fv" ] || fv=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("format_version", ""))' "$json" 2>/dev/null)
[ -n "$fv" ] || { echo "make_rustdoc_json: no format_version in $json" >&2; exit 1; }

# sha1 over the crate's sources (src/**/*.rs in C-locale path order, then Cargo.toml): lets a committed fixture be checked for staleness.
sha1() { if command -v sha1sum >/dev/null 2>&1; then sha1sum | cut -d' ' -f1; else shasum -a 1 | cut -d' ' -f1; fi; }
src_sha1=$({
    find "$crate/src" -type f -name '*.rs' | LC_ALL=C sort | while read -r f; do cat "$f"; done
    cat "$crate/Cargo.toml"
} | sha1)

rustc_v=$(rustc --version)
cp "$json" "$out/$lib.json" || exit 1
# Sidecar read by tools/rdj.py: names the rustc in a format_version error and pins the sources the JSON was made from.
{
    echo "rustc: $rustc_v"
    echo "format_version: $fv"
    echo "features: ${features:-default}"
    echo "private_items: $([ -n "$priv" ] && echo 1 || echo 0)"
    echo "source_sha1: $src_sha1"
} > "$out/$lib.meta"
echo "rustc: $rustc_v"
echo "format_version: $fv"
echo "wrote: $out/$lib.json ($(wc -c < "$out/$lib.json" | tr -d ' ') bytes) + $lib.meta"
