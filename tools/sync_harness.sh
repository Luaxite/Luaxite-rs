#!/bin/sh
# Copy the hand-written glue (rust_binds/luau/{mod,convert,demo_binds,extra_*}.rs) into harness/src/luau. check.sh verifies the copies.
# NOT copied: real_*.rs (cargo feature `real`, needs the real azalea; mod.rs declares them behind #[cfg(feature = "real")]).
cd "$(dirname "$0")/.." || exit 2
mkdir -p harness/src/luau
for f in rust_binds/luau/mod.rs rust_binds/luau/convert.rs rust_binds/luau/demo_binds.rs rust_binds/luau/extra_*.rs; do
    [ -e "$f" ] && cp "$f" "harness/src/luau/$(basename "$f")"
done
