#!/bin/sh
# tests/e2e/run.sh BIN SERVER - run the e2e scripts and every example against a running server (flat world, offline mode).
# A test passes when it prints "E2E PASS <name>" and no "[luau]" line (the binary exits 1 when a script fails; the log is what is checked); a "[luau]" line that
# contains "e2e-expected" is an error the test raised on purpose and does not count.
# Examples only have to load and run for a while without a "[luau]" line.
# LUNE_ONLY=1 runs just the lune* scripts (they need no Minecraft server).
set -u
cd "$(dirname "$0")/../.." || exit 2
bin=$1
server=${2:-localhost}
[ "$server" = localhost ] || echo "note: scripts join localhost (azalea.join default); the server argument $server is ignored"
fail=0
lb=; command -v stdbuf > /dev/null && lb="stdbuf -oL"

run() { # run NAME LIMIT SCRIPT [STDIN_FILE]
    name=$1; limit=$2; script=$3
    log=/tmp/e2e-$name.log
    # Luau's print() writes through C stdio, which is fully buffered into a file: if `timeout` kills a hung run, every line is lost.
    # stdbuf -oL makes it line-buffered, so the log shows how far the script got (and whether "E2E PASS" was printed before a hang).
    # `path` runs the script instead of the embedded main; CLI_ARGS (word-split on purpose) are the arguments that reach process.args.
    timeout "$limit" $lb "$bin" path "$script" ${CLI_ARGS:-} < "${4:-/dev/stdin}" > "$log" 2>&1
    cat "$log"
    if grep -F '[luau]' "$log" | grep -vF 'a handler or task raised an error (printed above)' | grep -qvF 'e2e-expected'; then echo "FAIL $name: [luau] error"; fail=1; fi
    case $script in tests/*) grep -q "E2E PASS $name" "$log" || { echo "FAIL $name: no PASS line"; fail=1; } ;; esac
}

if [ "${LUNE_ONLY:-0}" != 1 ]; then
    run basic 180 tests/e2e/basic.luau
    RUST_LOG=info,azalea=debug,azalea_client=debug; export RUST_LOG # verbose: this test hangs
    run packets 120 tests/e2e/packets.luau
    unset RUST_LOG
    run multi 120 tests/e2e/multi.luau
    # the bound azalea API, one area per script (each joins its own bot)
    for n in azalea_surface azalea_state azalea_world azalea_movement azalea_inventory azalea_events azalea_ecs azalea_swarm azalea_sweep; do
        run "$n" 180 "tests/e2e/$n.luau"
    done
fi
run offline_api 30 tests/e2e/offline_api.luau   # the API that needs no bot (also what .github/workflows/rust.yml runs on every OS)
run bind_demo 30 tests/e2e/bind_demo.luau   # the globals bound from rust_binds/luau/demo_binds.rs (//BIND pub)
run lune 30 tests/e2e/lune.luau
run lune_fs 30 tests/e2e/lune_fs.luau
run lune_serde 30 tests/e2e/lune_serde.luau
run lune_regex 30 tests/e2e/lune_regex.luau
run lune_datetime 30 tests/e2e/lune_datetime.luau
run lune_luau 30 tests/e2e/lune_luau.luau
run lune_task 30 tests/e2e/lune_task.luau
run coroutine_async 30 tests/e2e/coroutine_async.luau
run lune_stdio 30 tests/e2e/lune_stdio.luau /dev/null
run lune_process 30 tests/e2e/lune_process.luau
CLI_ARGS="debug=true debug true --verbose -x"; export CLI_ARGS
run lune_process_args 30 tests/e2e/lune_process_args.luau   # luaxite path <script> <args...>: the args reach process.args
unset CLI_ARGS
run lune_process_idle 30 tests/e2e/lune_process_idle.luau   # create() child must not hold the program open (timeout 30s < the child's sleep)
run lune_net 30 tests/e2e/lune_net.luau

# Ctrl-C: SIGINT (sent by `timeout` after 3s, to luaxite only: its children are in their own process groups) must kill the running create()
# child and end luaxite with exit code 130. The script never ends by itself, so run.sh checks the exit code + the child and prints the PASS line.
alive() { # alive PID: running (a zombie does not count)
    kill -0 "$1" 2> /dev/null || return 1
    st=$(sed 's/.*) //' "/proc/$1/stat" 2> /dev/null | cut -c1)
    [ "$st" != Z ]
}
sigint_test() {
    name=lune_process_sigint
    log=/tmp/e2e-$name.log
    pidf=/tmp/e2e-$name.pid
    rm -f "$pidf"
    SIGINT_PID_FILE=$pidf timeout --preserve-status -k 10 -s INT 3 $lb "$bin" path tests/e2e/$name.luau < /dev/null > "$log" 2>&1
    rc=$?
    cat "$log"
    if grep -F '[luau]' "$log" | grep -qvF 'e2e-expected'; then echo "FAIL $name: [luau] error"; fail=1; return; fi
    [ "$rc" -eq 130 ] || { echo "FAIL $name: luaxite exit code $rc after SIGINT, want 130"; fail=1; return; }
    [ -s "$pidf" ] || { echo "FAIL $name: the child never wrote its pid"; fail=1; return; }
    cpid=$(cat "$pidf")
    i=0
    while alive "$cpid"; do
        i=$((i + 1))
        [ "$i" -gt 20 ] && { echo "FAIL $name: child $cpid still running after SIGINT"; kill -9 "$cpid" 2> /dev/null; fail=1; return; }
        sleep 0.1
    done
    echo "E2E PASS lune_process_sigint"
}
case $(uname -s) in
    MINGW* | MSYS* | CYGWIN*) echo "skip lune_process_sigint: unix only" ;;
    *) sigint_test ;;
esac

# Grandchildren of an exited child: lune_process_orphan.luau starts `sleep 100 &` from a shell = true create() and exec() child (both shells
# exit at once) and ends through process.exit; the sleeps must be gone once luaxite has exited (kill_all kills the exited children's groups).
orphan_test() {
    name=lune_process_orphan
    dir=/tmp/e2e-$name.d
    rm -rf "$dir"; mkdir -p "$dir"
    ORPHAN_PID_DIR=$dir; export ORPHAN_PID_DIR
    run $name 30 tests/e2e/$name.luau
    unset ORPHAN_PID_DIR
    for kind in create exec; do
        [ -s "$dir/$kind.pid" ] || { echo "FAIL $name: the $kind shell never wrote the sleep's pid"; fail=1; continue; }
        spid=$(cat "$dir/$kind.pid")
        i=0
        while alive "$spid"; do
            i=$((i + 1))
            [ "$i" -gt 20 ] && { echo "FAIL $name: $kind: grandchild $spid still running after luaxite exited"; kill -9 "$spid" 2> /dev/null; fail=1; break; }
            sleep 0.1
        done
    done
}
case $(uname -s) in
    MINGW* | MSYS* | CYGWIN*) echo "skip lune_process_orphan: unix only" ;;
    *) orphan_test ;;
esac

[ "$fail" -eq 0 ] && echo "e2e: OK" || echo "e2e: FAILED"
exit "$fail"
