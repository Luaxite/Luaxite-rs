#!/bin/sh
# tests/projects/run.sh [NAME...] - build and run the test projects (every directory here with a src/main.luau, or just the NAMEs given).
# A test project is a directory holding only its own src/: main.luau is the script and the other .luau files are the modules it requires. It is built
# as luaxite itself, in a scratch tree under target/projects/ that has the repo's build inputs (Cargo.toml, build.rs, bindgen.toml, rust/, tools/,
# bind/, vendor/) and the project's src/ instead of the repo's, then run with no arguments (the embedded main.luau). The binary build has no test
# options and a project never reads the repo's src/. The first build compiles the dependencies once into target/projects/build.
# A project passes when it prints "E2E PASS <name>" and no "[luau]" line (the binary exits 1 when its script fails).
set -u
cd "$(dirname "$0")/../.." || exit 2
root=$(pwd)
work=${PROJECTS_DIR:-$root/target/projects}
if [ $# -gt 0 ]; then
    names=$*
else
    names=$(cd tests/projects && for d in */; do [ -f "${d}src/main.luau" ] && printf '%s\n' "${d%/}"; done)
fi
[ -n "$names" ] || { echo "no test projects in tests/projects"; exit 2; }
lb=; command -v stdbuf > /dev/null && lb="stdbuf -oL"
fail=0
for name in $names; do
    proj=tests/projects/$name
    [ -f "$proj/src/main.luau" ] || { echo "FAIL $name: no $proj/src/main.luau"; fail=1; continue; }
    scratch=$work/src/$name
    rm -rf "$scratch"; mkdir -p "$scratch"
    cp Cargo.toml build.rs bindgen.toml rust-toolchain.toml "$scratch"/
    [ -f Cargo.lock ] && cp Cargo.lock "$scratch"/
    for d in rust tools bind vendor; do ln -s "$root/$d" "$scratch/$d"; done
    cp -R "$proj/src" "$scratch/src"
    if ! (cd "$scratch" && CARGO_TARGET_DIR=$work/build cargo build); then
        echo "FAIL $name: cargo build"; fail=1; continue
    fi
    log=$work/$name.log
    timeout 60 $lb "$work/build/debug/luaxite" > "$log" 2>&1
    cat "$log"
    if grep -F '[luau]' "$log" | grep -vF 'a handler or task raised an error (printed above)' | grep -qvF 'e2e-expected'; then echo "FAIL $name: [luau] error"; fail=1; fi
    grep -q "E2E PASS $name" "$log" || { echo "FAIL $name: no PASS line"; fail=1; }
done
[ "$fail" -eq 0 ] && echo "projects: OK" || echo "projects: FAILED"
exit "$fail"
