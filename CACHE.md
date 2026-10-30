proto: 2
task: 3558860047
## idx   path | purpose; symbols Lx-y | sig | prov@step (read|skim|inferred|unread)
rust/main.rs | bin entry: `use zenpel_bind::bind;` L3-5, parse_args, signal handler, run per Runtime | 1251627317/3373 | read@5
rust_binds/luau/mod.rs | glue (s10: CURRENT/TASK_LUA/current_lua near top, Runtime::lua; s9: `binds::register(&lua)` in with_source): Handlers, require shim, Runtime{lua,handlers} new/embedded/with_source L322-355 (Lua::new L346) | 686232666/12142 | skim@0
rust_binds/luau/ | generated.rs = OUT_DIR includes (gen_*, scripts; harness copy differs on purpose), convert, extra_*, real_* (feature real), lune_* (feature lune), generated.rs (OUT_DIR includes) | - | skim@0
rust_binds/luau/real_hub.rs | EMPTY (1 byte), declared mod.rs L30 (+harness copy), no refs; kept | 3515105045/1 | read@0
rust_binds/luau/real_packets.rs | packets glue; merge_injected L55-75, #[cfg(test)] 4 assert_eq! L77-103 (rustfmt-wrapped) | 3152814727/6352 | read@1
build.rs | runs tools/bindgen.py L66-90, then write_binds L62-91 (bind_gen -> OUT_DIR/binds.rs; EMPTY_BINDS L58), embeds src/**.luau -> OUT_DIR/scripts.rs; main L93; std only | 3368258663/5612 | read@8
Cargo.toml | bin zenpel=rust/main.rs; mlua 0.12 luau,async,send,macros; features real,packets,lune; path dep zenpel_bind=rust_binds/bind | 2002463076/5559 | read@5
harness/ | own workspace, fake azalea; runs test.luau; src/luau = copies of rust_binds/luau glue; STAYS PUT | - | skim@0
harness/src/luau/ | copies of mod,convert,extra_* + gen_*.rs; generated.rs differs on purpose | - | skim@0
harness/fake/ | fake azalea + rustdoc fixture | - | unread
tools/sync_harness.sh | cp rust_binds/luau/{mod,convert,extra_*}.rs -> harness/src/luau | 2044519931/454 | read@0
tools/check.sh | verify script; steps 1-6 incl harness build (skips w/o cargo) | 1839602376/7222 | skim@0
tools/bind_scan.py | bind scanner; FN named groups pub/mods/name L24; walk L75 close_of L94 split_top L102 parse_param L112 signature L124 (params,ret,body,generic) attrs_before L157 file_mode L176 brace_kind L190 enclosing L198 skip_reason L214 scan_text L227 (yields label,line,fn,mode,params,ret) scan_root L247 main L256 | 287084658/8970 | read@4
tools/ | bindgen*.py, zenpel_gen.py, rdj*.py, golden*, coverage*, fuzz/, testdata/ | - | unread
tests/py/ | stdlib unittest suite (_common.py ROOT, FAKE=harness/fake, run(), TOOLS on sys.path); 282 tests; test_packets_race.py L27 regex; test_bind_scan.py (29, s4) | 2200485911/1357 | read@1
rust_binds/bind/ | crate zenpel_bind: Cargo.toml (proc-macro, no deps), src/lib.rs `#[proc_macro_attribute] bind` passthrough | 465961607/691 | read@5
tools/bind_gen.py | register() generator; module_path L23 arg_ok L36 split_sig L41 statement L54 generate L68 main L88; imports bind_scan (split_top) | 485747434/4204 | read@7
tests/py/test_bind_gen.py | exact-text asserts on tmp trees (Text/Lua/Optional/Results/Cli), rustfmt syntax check (25) | 2740479566/9437 | read@7
tests/py/test_bind_wiring.py | static wiring of mod binds / register call / harness sync (5) | 1243414367/1708 | read@9
tests/py/test_bind_build_rs.py | static + real rustc build of build.rs on a scratch tree (6) | 2584029506/4479 | read@8
tests/py/test_bind_crate.py | static wiring asserts + a real stable cargo compile of the attr (skips w/o cargo) | 2656115712/3124 | read@5
tests/e2e/ | *.luau e2e + run.sh BIN SERVER | - | skim@0
src/ | .luau scripts embedded by build.rs (main.luau entry) | - | unread
bindgen.toml | bindgen config for azalea | - | unread
README.md | project readme | - | unread
.github/workflows/ | api-docs generator release rust rustdoc tests (no compile.yml); refs harness/; tests.yml runs unittest + check.sh | - | skim@1
## facts
[P] cmd: check=SKIP_HARNESS=1 sh tools/check.sh; py=python3 -m unittest discover -s tests/py (~70s)
[P] env@9: crates.io reachable via proxy: `cd harness && RUSTUP_TOOLCHAIN=stable cargo build` works (~45s), so `sh tools/check.sh` (no SKIP_HARNESS) runs the harness for real and passes; root build (azalea checkout bind/azalea-src) still not possible
[P] env: cargo 1.97 STABLE works (`RUSTUP_TOOLCHAIN=stable`, as tools/env.sh does), nightly cannot be fetched offline; dep-free crates can be built for real, azalea/mlua builds unverified; .env exists = secrets, never read
[P] conv: rustfmt style 4sp, edition 2024; stdlib-only python tools
[P] skip: .git vendor target __pycache__ *.lock logo.svg harness/fake/rustdoc/azalea.json .env
[T] baseline@1: check.sh OK; unittest 253 OK (~15s)
[T] @3: cargo exists on PATH but rustup can't download offline -> test_bindgen_selftest fails (pre-existing, not a regression); 281 OK otherwise (282 total @4)
[T] scan_text yields (label,line,fn,mode,params,ret)
[T] rust/ already exists with main.rs + luau/; harness stays at harness/
[T] harness/src/luau + tools/sync_harness.sh + check.sh step 5 must stay consistent with any rust_binds/luau/mod.rs edit
[T] chain=12 (user swap@1): step_done 0-12, plan<=12 slices; lint regex step_done must allow 10-12
[T] slice rule: easy-medium, 1 concern, small diff; split hard work, never push through
[T] strip_comments.py is a script (mutates argv files on import): never import it
[T] smoke tree /tmp/s2 is scratch; rebuild if needed
[T] @10: no cargo on PATH this session; s10 Rust unverified by compiler (task_local!/Mutex static/scope); retry compile when a toolchain exists
[T] @11: demo_binds.rs is the only //BIND file; harness copies it (sync_harness.sh); bind_e2e.sh rewrites `mod binds {..}` in a scratch generated.rs; still no cargo
