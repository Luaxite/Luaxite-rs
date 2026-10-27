#!/bin/sh
# Source from the project root: `. tools/env.sh`. Idempotent. Picks a toolchain for the tools: RUSTUP_TOOLCHAIN=stable when no nightly is
# installed and none is already set (the fake azalea and the committed rustdoc fixture build on stable). Network use is cargo's default.
if [ -z "${RUSTUP_TOOLCHAIN:-}" ] && ! rustup toolchain list 2>/dev/null | grep -q '^nightly'; then RUSTUP_TOOLCHAIN=stable; export RUSTUP_TOOLCHAIN; fi
