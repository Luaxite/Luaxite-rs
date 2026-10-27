proto: 2
task: 1867628622
## idx   path | purpose; symbols Lx-y | sig | prov@step (read|skim|inferred|unread)
.github/actions/azalea/action.yml | ? | - | unread
.github/workflows/api-docs.yml | ? | - | unread
.github/workflows/compile.yml | ? | - | unread
.github/workflows/generator.yml | ? | - | unread
.github/workflows/release.yml | ? | - | unread
.github/workflows/rust.yml | CI; step "a failing script exits non-zero" ~L84, + s5 step "an erroring task.spawn thread exits non-zero" | 2093183624/11155 | skim@0
.github/workflows/rustdoc.yml | ? | - | unread
.github/workflows/tests.yml | ? | - | unread
.gitignore | + harness/target/ (cargo build of harness) | 2027837624/147 | read@1
.luaurc | ? | - | unread
Cargo.toml | tokio features L25 (s1: + signal); features real/packets/lune ~L48-57 | 1422889953/5326 | read@1
README.md | install + Luau API + Notes (async, s16: embedded require may yield/cyclic error, size/time limits) | - | read@16
bindgen.toml | ? | - | unread
build.rs | ? | - | unread
harness/Cargo.toml | ? | - | unread
harness/luau/ | dir, 2 files | - | unread
harness/src/ | dir, 14 files | - | unread
harness/test.luau | ? | - | unread
install.ps1 | ? | - | unread
install.sh | ? | - | unread
rust-toolchain.toml | ? | - | unread
rust/luau/convert.rs | conv types: lua_err L10; LBlockPos L29; LVec3; LBool L83 (strict FromLua, s7); LMinecraftEntityId; LPathfinderOpts L117 (FromLua ~L119-160, Option<LBool> .0 for allow_mining/retry_on_no_path (s8)); LItem LSlots LMenu LuaContainer | 1859628770/8161 | read@8
rust/luau/extra_block.rs | ? | - | unread
rust/luau/extra_container.rs | Container hand-written: open L9; throw L99, drop_cursor L111 take Option<LBool> (s7) | 93372523/4707 | read@7
rust/luau/extra_entity.rs | ? | - | unread
rust/luau/extra_inventory.rs | ? | - | unread
rust/luau/extra_misc.rs | hand-written Bot/misc glue; const DEFAULT_REACH 4.5 (s8); goto_reach ~L180: distance.unwrap_or(DEFAULT_REACH) -> ReachBlockPosGoal::new_with_distance (reach_goal in real_goal.rs keeps ::new) | 2263176867/8702 | read@11
rust/luau/extra_query.rs | nearest_player, nearby_entities; others() is pub(super) (drops the bot; used by real_search.rs) (s11) | 2825919004/1841 | read@11
rust/luau/extra_state.rs | ? | - | unread
rust/luau/generated.rs | ? | - | unread
rust/luau/lune_libs.rs | require(); MAX_BYTES (64 MiB) const, too_big(what) -> "<what> exceeds 64 MiB", read_capped/read_capped_to (take(max+1) -> None when over); timeout_from_secs(func, Option<f64>) -> Option<Duration> (>0, clamped to u32::MAX s, s13); s12: DEFAULT_EXEC_TIMEOUT_SECS 600 / DEFAULT_REQUEST_TIMEOUT_SECS 120 + timeout_with_default(func, Option<f64>, default) (None->default, 0->None); Rust unit tests at end (s12, s13) | 3139339228/5965 | read@13
rust/luau/lune_net.rs | @lune/net; s13: fn request_timeout(secs) = timeout_with_default(.., DEFAULT_REQUEST_TIMEOUT_SECS) for url-string / no-options / options.timeout; MAX_READ (Tcp read); CONNECT_TIMEOUT 30s in build_client; ReqSpec.timeout from options.timeout; req_err() -> "net.request: timed out"; send_request: content_length + chunk() loop capped at MAX_BYTES (s12); handle(): Content-Length precheck + Limited::new(body, MAX_BYTES).collect() -> payload_too_large() 413 + Connection: close, no error flag (s13); ws next ~L430-470; serve_fn ~L790 | 1958970407/32908 | skim@13
rust/luau/lune_process.rs | @lune/process; s13: parse_opts reads raw timeout first: exec -> timeout_with_default(DEFAULT_EXEC_TIMEOUT_SECS) (also without options), create + any timeout -> error; CHILDREN: Vec<Entry{pid,exited,group}> + MAX_TRACKED 1024 + Tracked::new(pid,group)/Drop (s3, ~L14-65); kill_group_cmd (unix: `kill -9 -pid; kill -9 pid`) + kill_tree (unix sh -c / windows taskkill /F /T) + kill_leftover_group (unix `kill -9 -pid` only, s4) + kill_all ~L68-100 (running -> kill_tree, exited group -> kill_leftover_group); Opts.timeout parsed in parse_opts (exec only, create errors); read_all (-> mlua::Result, errors past MAX_BYTES); build_command ~L219 (cfg(unix) process_group(0) unless stdin inherited, s14); Reader read + readToEnd via read_capped; exec: one `run` future (try_join! output + child.wait) under tokio::time::timeout, error arm kill_tree then child.kill, "process.exec: timed out after Ns" (s13/s14); create spawn + kill_wait arm kill_tree then child.kill | 854051337/19015 | read@14
rust/luau/lune_stdio.rs | stdio; readToEnd via read_capped (s12, no AsyncReadExt import) | 2549635681/7541 | skim@12
rust/luau/lune_task.rs | ? ; report() ~L79 calls super::note_error() before eprintln (s5) | - | skim@5
rust/luau/mod.rs | s10: begin_embedded/finish_embedded helpers + load_embedded_sync (call) beside load_embedded (call_async), glue picks by coroutine.isyieldable(); Runtime+Handlers; SCRIPT_ERRORS static + note_error()/had_error() ~L62-71; Handlers (map, waiters, closed:AtomicBool) wait ~L116 close_waiters ~L136 fire ~L142; Loading drop-guard + install_require (~L216-320): sync `resolve` closure, async `load_embedded` (call_async, azalea_loading/azalea_loaded registry tables), Lua `require_shim` glue (s15); run_standalone (None if had_error() -> Err) (Runtime::handle deleted s11) | 2585323314/13835 | read@15
rust/luau/real_ecs.rs | ? | - | unread
rust/luau/real_entity.rs | ? | - | unread
rust/luau/real_events.rs | start_update_pump L11-26 spawn_local; Bot wait_tick/update | 3642970409/2954 | skim@0 ; s5: update-handler error calls note_error
rust/luau/real_goal.rs | ? | - | unread
rust/luau/real_hub.rs | ? | - | unread
rust/luau/real_inventory.rs | ? | - | unread
rust/luau/real_lifecycle.rs | join/swarm; Live L16-45; BACKLOG_WARN L69; start_event_pump L72-125 (spawn_local per event, backlog warn); InFlight ~L129; PumpGuard ~L147; BotSink ~L270; swarm add channel ~L311 | 46909941/12231 | skim@0 ; s5: 2 event-task error prints preceded by note_error
rust/luau/real_packets.rs | snapshot L29; read_injected+merge_injected+#[cfg(test)] tests ~L45-100; write_packet; raw_connection; raw_connection_mut (writes back only changed state / merges injected) | 712286854/6878 | read@6
rust/luau/real_registry.rs | REGISTRIES fallback list L10; short_name, holder_extra_names, kinds_of (builtin + holder extras), registry_name(client,raw) free fn (accepts holder-sent registries), visit/scan_entries (no full list, reused buffer), entry_names (registry_entries only), index_of; Lua methods registry_kinds/entries/resolve/name/get (s10) | 3572984518/7503 | read@10
rust/luau/real_search.rs | (s7: 4 luau docs end with BREAKING; CHANGELOG.md/README note) nearest_entities + search() for any/nearest_entity(ies)_by: all go through others()/filter e.id() != me (bot excluded) (s11) | 1131818940/3995 | read@11
rust/luau/real_world.rs | World class + Bot world access; floor_coord L~38-47 (s9); nearer + Nearest (bounded nearest-k, select_nth_unstable_by; unit tests at file end) ~L27-85 (s10); MAX_CANDIDATES = scan cap on examined (filtered) hits + limit ceiling; search() ~L153-215: partial filter BEFORE push/cap, no full sort; is_chunk_loaded/height take f64 floored; find_block/find_blocks call search; s16: doc comments "never hold both locks" on search + chunk_is_loaded; s15: search() partial path = pass 1 (world guard: HashSet of chunk keys of in-range hits, guard dropped) -> loaded_chunk_map(&keys) (one partial.read(), HashMap<(i32,i32),bool>) -> pass 2 (world guard, filter via map, missing = unloaded), non-partial path unchanged; chunk_is_loaded stays for single-chunk reads; dist_sq/chunk_key closures | -/15004 | read@15
rust/main.rs | Cli+main; parse_args L14-27; install_signal_handler L32-55 (s1: unix SIGINT->130 / SIGTERM->143 via tokio::spawn, windows ctrl_c->130; all call luau::Runtime::kill_children()); main L58 (calls install_signal_handler after parse_args); run(real) L76, run(!real) L101 | 2038765412/3498 | read@1
src/chest.luau | ? | - | unread
src/ecs.luau | ? | - | unread
src/goals.luau | ? | - | unread
src/guard.luau | ? | - | unread
src/hello.luau | ? | - | unread
src/main.luau | ? | - | unread
src/multi.luau | ? | - | unread
src/packets.luau | ? | - | unread
src/swarm.luau | ? | - | unread
src/world.luau | ? | - | unread
tests/e2e/ | e2e luau (run.sh BIN); s9: lune_require_gsub.luau (hello.luau required inside a string.gsub callback with azalea.join stubbed; run.sh `run lune_require_gsub 30`, server-less; red until s10); s6: lune_process_orphan.luau (shell=true create+exec, `sleep 100 &`, ORPHAN_PID_DIR; run.sh orphan_test checks pids dead after exit); azalea_events.luau: task.defer-in-handler block, tail = disconnect + wait_for-after-exit asserts (s4); azalea_inventory.luau: strict-bool pcall asserts (s7); unrunnable here; s2: lune_process_sigint.luau (create() child via sh -c "echo $$ > $SIGINT_PID_FILE; exec sleep 100", loops task.wait; no PASS line, run.sh sigint_test() runs it under `timeout --preserve-status -k 10 -s INT 3`, asserts exit 130 + child gone, prints PASS; skipped on MINGW/MSYS/CYGWIN) | - | skim@4
tests/py/ | dir; test_timeouts.py s14: default constants/timeout_with_default shape, docs+stubs+CHANGELOG wording, e2e covers timeout=0; test_require_async.py (s11: glue isyieldable branch, load_embedded_sync structure, shared begin/finish helpers + tables, no preload, gsub e2e hooked; s15: install_require structure: call_async chunk, sync resolve keeps @lune sync, still-loading error, Loading drop guard, loaded set after chunk, glue; harness mod.rs in sync; imports fn_body from test_size_caps); test_kill_group.py (s6: orphan e2e + run.sh structure; s5: exec `_tracked` for every exit path; s4: kill_all leftover groups, create task drop, real exited-leader kill; s3: Entry/Tracked/cap/call-site structure; s14: process_group(0) cfg(unix) in build_command, kill_group_cmd/kill_tree/kill_all, windows taskkill kept, exec error arm + create kill arm call kill_tree first, real sh group-kill run; imports fn_body from test_size_caps); test_timeouts.py (s13: serve Limited/413, CONNECT_TIMEOUT, net.request options.timeout, exec timeout+kill, timeout_from_secs; imports fn_body from test_size_caps); test_size_caps.py (s12: MAX_BYTES/too_big/read_capped, readToEnd, exec try_join+kill, net chunk loop; fn_body(src,marker)); test_reach_entities.py (s8: goto_reach 4.5 test; s7: CHANGELOG/README/BREAKING docs; s11: goto_reach default, bot excluded from entity queries, handle removed); test_find_block_scan.py (s16: lock-order comments + search never calls chunk_is_loaded, uses loaded_chunk_map; s15: filter-before-cap now via loaded_chunks.get map lookup; s10: filter-before-cap, Nearest, registry lookups; fn_body(src,name,method)); test_world_args.py (s9: floor_coord, i64 distance); test_strict_bool.py (s7: LBool strict, container uses it); test_packets_race.py (s6: raw_connection_mut structure); test_error_sites.py (s5: note_error at handler/task error prints); test_extras_sync.py (new s3: luau[..] decl vs Rust fn param counts; helpers balanced/split_top/check_file; 74 decls); s2: test_signal_handler.py (Cargo tokio signal; main.rs install_signal_handler structure; run.sh/e2e sigint wiring); test_luau_syntax + test_lune_surface exempt `*_sigint` e2e scripts from own-PASS/exit(0) rule (run.sh must print the PASS line) | - | read@2
tests/run_all.sh | py unittest discover tests/py (-t tests/py; 220 tests @2) + optional e2e with BIN | - | skim@3
tools/api_list.py | ? | - | unread
tools/api_surface.py | ? | - | unread
tools/baseline_api.txt | ? | - | unread
tools/bindgen.py | ? | - | unread
tools/bindgen_crates.py | ? | - | unread
tools/bindgen_rdj.py | ? | - | unread
tools/bindgen_selftest.py | ? | - | unread
tools/cargo_warnings.py | ? | - | unread
tools/check.sh | verify: gen on harness/fake, golden, selftests, harness glue==real glue, harness build+run; prints "check: OK" | - | skim@1
tools/coverage.py | ? | - | unread
tools/coverage.toml | ? | - | unread
tools/env.sh | ? | - | unread
tools/fuzz/ | dir, many files | - | unread
tools/golden.sh | golden sha1 of gen outputs; write needs GOLDEN_FORCE=1 + line in tools/golden/ALLOWED_DIFF.md | - | skim@1
tools/golden/ | dir, many files | - | unread
tools/luaxite_gen.py | generator; Mapper(map_ty bool: param->LBool L383-388; Vec branch handles LBool L433;touched keys L361-373); Generator.goals L834-873; build L876; impl_top_fns L1294-1347 (brace-depth scan, top-level impl fns only); extras_reserved L1350; scan_extras L1370; emit_ecs L1644; ecs_name_error ~L1742 | 437144530/109487 | read@8
tools/lune-stubs/datetime.luau | ? | - | unread
tools/lune-stubs/fs.luau | ? | - | unread
tools/lune-stubs/luau.luau | ? | - | unread
tools/lune-stubs/net.luau | luau-lsp stub `return nil :: any` + behavior-note comments (options.timeout, 64 MiB, 413) (s16) | - | read@16
tools/lune-stubs/process.luau | luau-lsp stub `return nil :: any` + behavior-note comments (exec timeout/cap, group kill) (s16) | - | read@16
tools/lune-stubs/regex.luau | ? | - | unread
tools/lune-stubs/serde.luau | ? | - | unread
tools/lune-stubs/stdio.luau | ? | - | unread
tools/lune-stubs/task.luau | ? | - | unread
tools/make_rustdoc_json.sh | ? | - | unread
tools/make_rustdoc_json_ws.sh | ? | - | unread
tools/mapper_selftest.py | selftest (run by check.sh; LBool asserts L66-74, 69 checks) Generator/Mapper checks; ECS emit + goals-credit + extras_reserved nested-fn asserts at end (L312-330) | 3608833107/20492 | read@8
tools/rdj.py | ? | - | unread
tools/rdj_index.py | ? | - | unread
tools/rdj_selftest.py | ? | - | unread
tools/rdj_superset.py | ? | - | unread
tools/rdj_synth.py | ? | - | unread
tools/sync_harness.sh | ? | - | unread
CHANGELOG.md | ## Unreleased / ### Breaking (s7: entity queries exclude the bot) / ### Fixed (s8: goto_reach 4.5); s14 appends Breaking timeouts | - | read@7
## facts
[P] cmd: verify=export PYTHONDONTWRITEBYTECODE=1 RUSTUP_TOOLCHAIN=stable; sh tools/check.sh | tail -n 5 (needs "check: OK"); sh tests/run_all.sh | tail -n 5 (needs "tests: OK", 151 py tests); RUSTUP_TOOLCHAIN=stable needed: rust-toolchain.toml says nightly, no network -> bindgen_selftest fails otherwise
[P] env: cargo NOT on PATH in step 2 env (check.sh skips harness build/run, still prints "check: OK"); root crate never buildable (no network) -> real_*.rs/lune_*.rs/mod.rs/convert.rs edits unbuilt, review by reading
[P] cmd: build=cargo build (features: real default); e2e=sh tests/e2e/run.sh BIN; LUNE_ONLY=1 for server-less
[P] note: task lib only via require("@lune/task") (lune_libs.rs:34), not a global
[P] entry: rust/main.rs; embedded script src/main.luau
[P] mirror: rust/luau/{mod,convert,extra_*}.rs copied to harness/src/luau by sh tools/sync_harness.sh (check.sh step 5 fails if out of sync); real_*.rs/lune_*.rs not mirrored
[P] gen: tools/check.sh regenerates harness/src/luau/gen_*.rs + harness/luau/{azalea.d.luau,GEN_REPORT.md}; a generator change that alters them -> GOLDEN_FORCE=1 sh tools/golden.sh write fake + line in tools/golden/ALLOWED_DIFF.md
[P] conv: rustfmt style, 4 spaces; luau tabs; python stdlib only; run py with -I
[P] skip: vendor target .git *.lock tools/testdata harness/fake rustdoc json harness/target
[P] proto-cap: PROMPT first para CHAIN LENGTH -> chain cap 16; lint step_done regex ([0-9]|1[0-6]); plan<=16 (this task: exactly 16); reply STEP n/16
[P] paths: PROMPT refs main.rs=rust/main.rs, mod.rs=rust/luau/mod.rs, lune_*.rs/real_*.rs/convert.rs/extra_*.rs=rust/luau/
[P] azalea: uploaded azalea-main.zip is commit d3422ec8 (CI pins 0d38e0dc in .github/actions/azalea/action.yml); extracted to /home/claude/azalea/azalea-main (may be gone): goals.rs ReachBlockPosGoal::new = 4.5; chunks.rs L76-77 only nested lock site = shared.write then partial.write
