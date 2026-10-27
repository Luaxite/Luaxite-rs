#!/usr/bin/env python3
"""bindgen_selftest.py - stdlib-only tests of tools/bindgen_*.py (PROMPT items I3-I5). Run by tools/check.sh; exit 0 = all passed.
`cargo metadata` is replaced by tools/testdata/bind/cargo_shim.py (recorded metadata, see its docstring)."""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.dont_write_bytecode = True
import bindgen_crates  # noqa: E402
import bindgen_rdj  # noqa: E402

TESTS = []
_tmp: list[str] = []
SHIM_PY = ROOT / "tools" / "testdata" / "bind" / "cargo_shim.py"
MAKE_PY = ROOT / "tools" / "testdata" / "bind" / "make_shim.py"


def test(f):
    TESTS.append(f)
    return f


def tmpdir() -> Path:
    d = tempfile.mkdtemp(prefix="bindgen_t_")
    _tmp.append(d)
    return Path(os.path.realpath(d))


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def shim(root: Path) -> dict:
    """Env for a subprocess/resolve call that uses the recorded-metadata cargo; BINDGEN_SHIM_LOG lists the manifests asked for."""
    w = root.parent / (root.name + "-shim.sh")
    write(w, f'#!/bin/sh\nexec "{sys.executable}" "{SHIM_PY}" "$@"\n')
    w.chmod(0o755)
    return {"BINDGEN_CARGO": str(w), "BINDGEN_SHIM_ROOT": str(root), "BINDGEN_SHIM_LOG": str(root.parent / (root.name + "-calls.log"))}


def layout(deps: str = 'ws-a = { path = "bind/ws/a" }\nserde = "1"\n', crates=("solo", "tool", "ws")) -> Path:
    """A project root: Cargo.toml (+ the given [dependencies]) and bind/<crates>/Cargo.toml (contents matter only to roots())."""
    r = tmpdir() / "root"
    write(r / "Cargo.toml", f'[package]\nname = "host"\nversion = "0.1.0"\n\n[dependencies]\n{deps}')
    for c in crates:
        if c == "ws":
            write(r / "bind/ws/Cargo.toml", '[workspace]\nmembers = ["a", "b", "c", "d"]\n')
            for m in "abcd":
                write(r / f"bind/ws/{m}/Cargo.toml", f'[package]\nname = "ws-{m}"\nversion = "0.1.0"\n')
        else:
            write(r / f"bind/{c}/Cargo.toml", f'[package]\nname = "{c}"\nversion = "0.1.0"\n')
    (r / "bind/notes").mkdir(parents=True, exist_ok=True)       # a directory without Cargo.toml is ignored
    return r


def resolve(r: Path) -> list[dict]:
    old = {k: os.environ.get(k) for k in shim(r)}
    os.environ.update(shim(r))
    try:
        return bindgen_crates.resolve(r)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


@test
def test_roots_layout():
    r = layout()
    got = [os.path.relpath(d, r) for d in bindgen_crates.roots(r)]
    assert got == ["bind/solo", "bind/tool", "bind/ws/a"], got      # (a) bind/* with [package] (ws has none), then (b) path deps; serde is not


@test
def test_closure_order_and_filters():
    r = layout()
    got = resolve(r)
    assert [c["name"] for c in got] == ["ws-c", "ws-b", "solo", "ws-a"], [c["name"] for c in got]    # deps first, ties alphabetical (solo < ws_a)
    # `tool` is bin-only (no rustdoc lib), `ws-d` is a workspace member nobody depends on
    assert {c["lib"] for c in got} == {"ws_a", "ws_b", "ws_c", "solo"}
    a = got[3]
    assert a["dir"] == str(r / "bind/ws/a") and a["manifest"] == str(r / "bind/ws/a/Cargo.toml"), a
    assert a["workspace_root"] == str(r / "bind/ws") and got[2]["workspace_root"] == str(r / "bind/solo")


@test
def test_metadata_calls_are_cached():
    r = layout()
    resolve(r)
    calls = (r.parent / "root-calls.log").read_text().split()
    assert sorted(calls) == ["bind__solo", "bind__tool", "bind__ws__b"], calls    # solo needs b: one workspace answer also covers a and c


@test
def test_dependency_only_root_pulls_closure():
    r = layout(deps='ws-b = { path = "bind/ws/b" }\n', crates=("ws",))
    assert [c["name"] for c in resolve(r)] == ["ws-c", "ws-b"]


@test
def test_empty_project():
    r = layout(deps="", crates=())
    shutil.rmtree(r / "bind")
    assert resolve(r) == []


@test
def test_cycle_is_an_error():
    r = layout(deps="", crates=("cyca", "cycb"))
    try:
        resolve(r)
    except bindgen_crates.CrateError as e:
        assert "cycle" in str(e) and "cyca" in str(e) and "\n" not in str(e), str(e)
    else:
        raise AssertionError("no error")


@test
def test_cargo_errors_are_one_line():
    r = layout()
    os.environ["BINDGEN_CARGO"] = str(r / "no-such-cargo")
    try:
        bindgen_crates.resolve(r)
    except bindgen_crates.CrateError as e:
        assert "BINDGEN_CARGO" in str(e) and "\n" not in str(e), str(e)
    else:
        raise AssertionError("no error")
    finally:
        os.environ.pop("BINDGEN_CARGO")
    r2 = layout(deps='ws-x = { path = "bind/missing" }\n', crates=())
    try:
        resolve(r2)
    except bindgen_crates.CrateError as e:
        assert "bind/missing" in str(e) and "\n" not in str(e), str(e)
    else:
        raise AssertionError("no error")


@test
def test_cli_json_and_exit_codes():
    r = layout()
    env = {**os.environ, **shim(r)}
    p = subprocess.run([sys.executable, str(ROOT / "tools/bindgen_crates.py"), "--root", str(r)], capture_output=True, text=True, env=env)
    assert p.returncode == 0 and p.stderr == "", p.stderr
    assert [c["name"] for c in json.loads(p.stdout)] == ["ws-c", "ws-b", "solo", "ws-a"]
    env["BINDGEN_CARGO"] = str(r / "no-such-cargo")
    p = subprocess.run([sys.executable, str(ROOT / "tools/bindgen_crates.py"), "--root", str(r)], capture_output=True, text=True, env=env)
    assert p.returncode == 1 and p.stdout == "" and p.stderr.startswith("error: ") and p.stderr.count("\n") == 1, p.stderr
    p = subprocess.run([sys.executable, str(ROOT / "tools/bindgen_crates.py"), "--bogus"], capture_output=True, text=True, env=env)
    assert p.returncode == 2, p.returncode


@test
def test_no_hardcoded_crate_names():
    src = (ROOT / "tools/bindgen_crates.py").read_text().lower()
    assert "azalea" not in src, "bindgen_crates.py must not name azalea or azalea-src"


@contextlib.contextmanager
def envset(**kw):
    old = {k: os.environ.get(k) for k in kw}
    os.environ.update({k: v for k, v in kw.items() if v is not None})
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def rdj_env(r: Path) -> dict:
    """shim() plus a rustc stand-in (version names the toolchain; `nosuch` is not installed) and the make_rustdoc_json.sh stand-in."""
    e = shim(r)
    rustc, make = r.parent / "rustc-shim.sh", r.parent / "make-shim.sh"
    write(rustc, '#!/bin/sh\n[ "$RUSTUP_TOOLCHAIN" = nosuch ] && { echo "error: toolchain \'nosuch\' is not installed" >&2; exit 1; }\n'
                 'echo "rustc 9.9.9 (shim $RUSTUP_TOOLCHAIN)"\n')
    rustc.chmod(0o755)
    write(make, f'exec "{sys.executable}" "{MAKE_PY}" "$@"\n')
    return {**e, "BINDGEN_RUSTC": str(rustc), "BINDGEN_MAKE_RDJ": str(make)}


def make_log(r: Path) -> list[str]:
    f = r.parent / "root-calls.log.make"
    return f.read_text().splitlines() if f.exists() else []


def run_rdj(r: Path, out: Path | None = None) -> list[dict]:
    with envset(**rdj_env(r)):
        return bindgen_rdj.make_all(r, out or r.parent / "out")


@test
def test_rdj_toolchain_choice_and_flags():
    r = layout()
    write(r / "bind/ws/rust-toolchain.toml", '[toolchain]\nchannel = "nightly-2026-01-01"\n')
    res = run_rdj(r)
    assert [(x["name"], x["status"]) for x in res] == [("ws-c", "built"), ("ws-b", "built"), ("solo", "built"), ("ws-a", "built")], res
    got = {l.split()[0]: l.split()[1:] for l in make_log(r)}
    assert got["ws_a"] == ["nightly-2026-01-01", "0", "0"] and got["ws_c"][0] == "nightly-2026-01-01", got   # workspace file, AZL_RDJ_ENV=0 OFFLINE=0
    assert got["solo"][0] == "nightly", got                                                                   # no workspace file, no root file
    assert [l.split()[0] for l in make_log(r)] == ["ws_c", "ws_b", "solo", "ws_a"]                            # dependencies first
    assert all((r.parent / "out/rdj" / f"{x['lib']}.json").is_file() and x["json"].endswith(f"{x['lib']}.json") for x in res)
    write(r / "rust-toolchain.toml", '[toolchain]\nchannel = "beta"\n')                                       # root file: crates outside a workspace file
    res = run_rdj(r, r.parent / "out2")
    assert {l.split()[0]: l.split()[1] for l in make_log(r)[4:]} == {"ws_c": "nightly-2026-01-01", "ws_b": "nightly-2026-01-01", "solo": "beta", "ws_a": "nightly-2026-01-01"}


@test
def test_rdj_cache():
    r = layout()
    write(r / "bind/ws/rust-toolchain.toml", '[toolchain]\nchannel = "nightly"\n')
    run_rdj(r)
    n = len(make_log(r))
    assert [x["status"] for x in run_rdj(r)] == ["cached"] * 4 and len(make_log(r)) == n          # same sources + toolchain: nothing runs
    write(r / "bind/ws/c/src/lib.rs", "pub fn changed() {}\n")                                     # one crate's source changes
    res = run_rdj(r)
    assert {x["name"]: x["status"] for x in res} == {"ws-c": "built", "ws-b": "cached", "solo": "cached", "ws-a": "cached"}, res
    write(r / "rust-toolchain.toml", '[toolchain]\nchannel = "beta"\n')                           # toolchain change: every crate whose rustc differs
    res = run_rdj(r)
    assert {x["name"]: x["status"] for x in res} == {"ws-c": "cached", "ws-b": "cached", "solo": "built", "ws-a": "cached"}, res   # ws crates stay nightly
    (r.parent / "out/rdj/solo.json").unlink()
    assert {x["name"]: x["status"] for x in run_rdj(r)}["solo"] == "built"                        # JSON missing: rebuilt


@test
def test_rdj_errors_are_one_line():
    r = layout()
    write(r / "rust-toolchain.toml", '[toolchain]\nchannel = "nosuch"\n')
    try:
        run_rdj(r)
    except bindgen_crates.CrateError as e:
        assert "nosuch" in str(e) and "not installed" in str(e) and "\n" not in str(e), str(e)
    else:
        raise AssertionError("no error")
    r = layout()
    write(r / "bind/solo/Cargo.toml", '[package]\nname = "solo-broken"\nversion = "0.1.0"\n')
    try:
        run_rdj(r)
    except bindgen_crates.CrateError as e:
        assert "solo" in str(e) and "E0432" in str(e) and "more noise" not in str(e) and "\n" not in str(e), str(e)
    else:
        raise AssertionError("no error")
    with envset(**{**rdj_env(r), "BINDGEN_MAKE_RDJ": None, "BINDGEN_CARGO": str(r / "no-such-cargo")}):
        try:
            bindgen_rdj.make_all(r, r.parent / "out3")
        except bindgen_crates.CrateError as e:
            assert "cargo not found" in str(e), str(e)
        else:
            raise AssertionError("no error")
    with envset(**{**rdj_env(r), "BINDGEN_RUSTC": str(r / "no-such-rustc")}):
        try:
            bindgen_rdj.make_all(r, r.parent / "out4")
        except bindgen_crates.CrateError as e:
            assert "rustc" in str(e) and "\n" not in str(e), str(e)
        else:
            raise AssertionError("no error")


@test
def test_rdj_cli():
    r = layout()
    env = {**os.environ, **rdj_env(r)}
    cmd = [sys.executable, str(ROOT / "tools/bindgen_rdj.py"), "--root", str(r), "--out", str(r.parent / "cli")]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert p.returncode == 0 and p.stderr == "" and [x["status"] for x in json.loads(p.stdout)] == ["built"] * 4, p.stderr
    write(r / "rust-toolchain.toml", '[toolchain]\nchannel = "nosuch"\n')
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert p.returncode == 1 and p.stdout == "" and p.stderr.startswith("error: ") and p.stderr.count("\n") == 1, p.stderr
    assert subprocess.run(cmd[:2], capture_output=True, text=True, env=env).returncode == 2


FAKE_RUSTC = "rustc 1.97.0 (2d8144b78 2026-07-07)"      # what harness/fake/rustdoc/azalea.meta records


def fake_project() -> Path:
    """A project root whose bind/azalea is harness/fake/azalea and whose glue is the harness's extra_*.rs; the rustdoc JSON comes from
    the committed fixture (make shim = cp), so no rustc/cargo runs."""
    r = tmpdir() / "root"
    write(r / "Cargo.toml", '[package]\nname = "host"\nversion = "0.1.0"\n')
    shutil.copytree(ROOT / "harness/fake/azalea", r / "bind/azalea", ignore=shutil.ignore_patterns("target"))
    write(r / "bindgen.toml", (ROOT / "bindgen.toml").read_text())        # the azalea config: the fake is bound with it (no file = the built-in empty tables)
    for f in (ROOT / "harness/src/luau").glob("extra_*.rs"):
        write(r / "rust/luau" / f.name, f.read_text())
    return r


def fake_env(r: Path) -> dict:
    e = shim(r)
    rustc, make = r.parent / "rustc-fake.sh", r.parent / "make-fake.sh"
    write(rustc, f'#!/bin/sh\necho "{FAKE_RUSTC}"\n')
    rustc.chmod(0o755)
    write(make, f'mkdir -p "$2" && cp "{ROOT}/harness/fake/rustdoc/"azalea.json "{ROOT}/harness/fake/rustdoc/"azalea.meta "$2/"\n')
    return {**e, "BINDGEN_RUSTC": str(rustc), "BINDGEN_MAKE_RDJ": str(make)}


def run_bindgen(r: Path, out: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **fake_env(r), **(extra_env or {})}
    return subprocess.run([sys.executable, str(ROOT / "tools/bindgen.py"), "--root", str(r), "--out", str(out)], capture_output=True, text=True, env=env)


@test
def test_bindgen_on_fake_crate():
    r = fake_project()
    out = r.parent / "out"
    p = run_bindgen(r, out)
    assert p.returncode == 0 and p.stderr == "", p.stderr
    lines = p.stdout.splitlines()
    assert lines and all(l.startswith(("cargo:rerun-if-changed=", "cargo:warning=")) for l in lines), p.stdout           # nothing else on stdout
    rer = {l.split("=", 1)[1] for l in lines if l.startswith("cargo:rerun-if-changed=")}
    for want in (r / "src", r / "bind/azalea/src", r / "bind/azalea/Cargo.toml", r / "bindgen.toml"):
        assert str(want) in rer, (want, rer)
    # same output as the committed harness bindings (the first line is the `<dir> @ <sha1>` label, which names the staging dir)
    for f in ("gen_client.rs", "gen_events.rs", "gen_types.rs"):
        a, b = (out / f).read_text().splitlines(), (ROOT / "harness/src/luau" / f).read_text().splitlines()
        assert a[1:] == b[1:] and a[0].startswith("// ") and a[0].split(" @ ")[1] == b[0].split(" @ ")[1], f
    assert (out / "bindings.d.luau").read_text().splitlines()[1:] == (ROOT / "harness/luau/azalea.d.luau").read_text().splitlines()[1:]
    for f in ("gen_client.rs", "gen_events.rs", "gen_types.rs"):                                  # inc/: same file minus inner attributes
        inc = (out / "inc" / f).read_text().splitlines()
        full = [l for l in (out / f).read_text().splitlines() if not l.startswith("#![")]
        assert inc == full and not any(l.startswith("#![") for l in inc) and len(full) < len((out / f).read_text().splitlines()), f
    assert not (out / "azalea.d.luau").exists() and (out / "GEN_REPORT.md").is_file()
    report = json.loads((out / "GEN_REPORT.json").read_text())                  # the machine-readable report sits beside the text one
    assert report["schema"] == 1 and report["classes"][0]["luau"] == "Bot", report["classes"][0]
    assert (r / "types/bindings.d.luau").read_text() == (out / "bindings.d.luau").read_text()      # copied into R/types
    # the API list: made from that .d.luau (tools/api_list.py), in O and in R/types next to it
    import api_list
    want = api_list.build((out / "bindings.d.luau").read_text(), r / "bindgen.toml")
    assert (out / "API_list.md").read_text() == want and (r / "types/API_list.md").read_text() == want
    assert want.startswith("# Luaxite Luau API\n") and "- `declare function Bot:chat(content: string): ()`" in want and "declare bot: Bot" in want
    api = api_list.build_dict((out / "bindings.d.luau").read_text(), r / "bindgen.toml")      # the same list as data: what CI and tools read
    assert (out / "API.json").read_text() == api_list.dumps(api) and (r / "types/API.json").read_text() == api_list.dumps(api)
    bot = next(c for c in api["classes"] if c["name"] == "Bot")
    assert any(m["decl"] == "declare function Bot:chat(content: string): ()" for m in bot["members"]) and {"name": "bot", "type": "Bot"} in api["globals"]
    # second run: R/types/bindings.d.luau and API_list.md are not rewritten (a rewrite would re-trigger cargo's rerun-if-changed)
    st = (r / "types/bindings.d.luau").stat().st_mtime_ns
    st2 = (r / "types/API_list.md").stat().st_mtime_ns
    st3 = (r / "types/API.json").stat().st_mtime_ns
    assert run_bindgen(r, out).returncode == 0 and (r / "types/bindings.d.luau").stat().st_mtime_ns == st
    assert (r / "types/API_list.md").stat().st_mtime_ns == st2 and (r / "types/API.json").stat().st_mtime_ns == st3


@test
def test_bindgen_forwards_warnings_and_errors():
    r = fake_project()
    gen = r.parent / "gen_warn.py"
    write(gen, "import os, sys\nsys.stderr.write('warning: first\\nwarning: second\\n')\n"
               "open(os.path.join(sys.argv[sys.argv.index('--luau-out') + 1], 'azalea.d.luau'), 'w').write('-- d\\n')\n")
    p = run_bindgen(r, r.parent / "out", {"BINDGEN_GENERATOR": str(gen)})
    assert p.returncode == 0 and p.stdout.splitlines()[-2:] == ["cargo:warning=warning: first", "cargo:warning=warning: second"], p.stdout
    bad = r.parent / "gen_bad.py"
    write(bad, "import sys\nsys.exit('error: rustdoc front end: nope')\n")
    p = run_bindgen(r, r.parent / "out", {"BINDGEN_GENERATOR": str(bad)})
    assert p.returncode == 1 and p.stdout == "" and p.stderr == "error: rustdoc front end: nope\n", (p.stdout, p.stderr)
    noisy = r.parent / "gen_noisy.py"
    write(noisy, "import sys\nsys.stderr.write('Traceback (most recent call last):\\nboom\\n')\nsys.exit(1)\n")
    p = run_bindgen(r, r.parent / "out", {"BINDGEN_GENERATOR": str(noisy)})
    assert p.returncode == 1 and p.stdout == "" and p.stderr.startswith("error: generator failed: Traceback"), p.stderr


@test
def test_bindgen_passes_config_or_builtin():
    r = fake_project()
    gen = r.parent / "gen_argv.py"
    write(gen, "import os, sys\nopen(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'argv.txt'), 'w').write('\\n'.join(sys.argv[1:]))\n"
               "open(os.path.join(sys.argv[sys.argv.index('--luau-out') + 1], 'azalea.d.luau'), 'w').write('-- d\\n')\n")

    def argv() -> list[str]:
        return (r.parent / "argv.txt").read_text().split("\n")

    (r / "bindgen.toml").unlink()
    assert run_bindgen(r, r.parent / "out", {"BINDGEN_GENERATOR": str(gen)}).returncode == 0
    a = argv()
    assert a[a.index("--config") + 1] == "builtin", a                  # no root bindgen.toml: the built-in empty tables
    write(r / "bindgen.toml", (ROOT / "bindgen.toml").read_text())
    assert run_bindgen(r, r.parent / "out", {"BINDGEN_GENERATOR": str(gen)}).returncode == 0
    a = argv()
    assert a[a.index("--config") + 1] == str(r / "bindgen.toml"), a
    # the real generator with that file: same bindings as the default config (the fake is bound with the azalea tables)
    out = r.parent / "out2"
    assert run_bindgen(r, out).returncode == 0
    assert (out / "gen_client.rs").read_text().splitlines()[1:] == (ROOT / "harness/src/luau/gen_client.rs").read_text().splitlines()[1:]
    write(r / "bindgen.toml", "deny_methods = [\n")
    p = run_bindgen(r, r.parent / "out3")
    assert p.returncode == 1 and p.stdout == "" and p.stderr.startswith("error: bindgen.toml: ") and p.stderr.count("\n") == 1, p.stderr


@test
def test_bindgen_error_paths():
    r = fake_project()
    shutil.rmtree(r / "bind")
    p = run_bindgen(r, r.parent / "out")
    assert p.returncode == 1 and p.stdout == "" and p.stderr.startswith("error: no crates to bind") and p.stderr.count("\n") == 1, p.stderr
    r = fake_project()
    p = run_bindgen(r, r.parent / "out", {"BINDGEN_CARGO": str(r / "no-such-cargo")})
    assert p.returncode == 1 and p.stderr.startswith("error: ") and "BINDGEN_CARGO" in p.stderr, p.stderr
    assert subprocess.run([sys.executable, str(ROOT / "tools/bindgen.py")], capture_output=True).returncode == 2


@test
def test_bindgen_on_toy_crate_without_config():
    """PROMPT done-when: a toy crate (not azalea) under a tmp `bind/` gets bindings from `python3 tools/bindgen.py`, no bindgen.toml:
    generic classes + a global table of the free fns, no events/packets/ecs files. cargo/rustc/rustdoc are shims; the rustdoc JSON is hand-built."""
    import rdj_selftest
    tmp = tmpdir()
    bind, d = rdj_selftest.toy_project(tmp)
    write(tmp / "Cargo.toml", '[package]\nname = "host"\nversion = "0.1.0"\n')
    man = bind / "toy" / "Cargo.toml"
    meta = {"packages": [{"name": "toy", "version": "0.1.0", "id": "toy 0.1.0", "source": None, "manifest_path": str(man), "edition": "2021",
                          "targets": [{"kind": ["lib"], "crate_types": ["lib"], "name": "toy", "src_path": str(bind / "toy/src/lib.rs")}], "dependencies": []}],
            "workspace_members": ["toy 0.1.0"], "resolve": None, "target_directory": str(bind / "toy/target"), "version": 1,
            "workspace_root": str(bind / "toy"), "metadata": None}
    write(tmp / "meta.json", json.dumps(meta))
    cargo, rustc, make = tmp / "cargo-toy.sh", tmp / "rustc-toy.sh", tmp / "make-toy.sh"
    write(cargo, f'#!/bin/sh\ncat "{tmp}/meta.json"\n')
    write(rustc, f'#!/bin/sh\necho "{FAKE_RUSTC}"\n')
    write(make, f'mkdir -p "$2" && cp "{d}/toy.json" "{d}/toy.meta" "$2/"\n')
    for f in (cargo, rustc):
        f.chmod(0o755)
    out = tmp / "out"
    env = {**os.environ, "BINDGEN_CARGO": str(cargo), "BINDGEN_RUSTC": str(rustc), "BINDGEN_MAKE_RDJ": str(make)}
    p = subprocess.run([sys.executable, str(ROOT / "tools/bindgen.py"), "--root", str(tmp), "--out", str(out)], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    assert all(l.startswith(("cargo:rerun-if-changed=", "cargo:warning=")) for l in p.stdout.splitlines()), p.stdout
    assert sorted(f.name for f in out.glob("gen_*.rs")) == ["gen_client.rs", "gen_types.rs"]
    rs = (out / "gen_client.rs").read_text()
    assert "pub struct LuaCounter" in rs and "Ok(toy::double(x))" in rs and "azalea::" not in rs
    assert (out / "inc" / "gen_client.rs").is_file()
    skipped = [sk for c in json.loads((out / "GEN_REPORT.json").read_text())["classes"] for sk in c["skipped"]]
    assert any("async free fn" in sk["reason"] for sk in skipped), skipped
    assert "declare extern type Counter with" in (tmp / "types" / "bindings.d.luau").read_text()


# ---- build.rs (s11). No rustc in some sandboxes (log A:): then only the static checks run; the compile+run test needs `rustc` on PATH.
BUILD_RS = ROOT / "build.rs"


def expected_scripts(root: Path) -> tuple[str, dict[str, str]]:
    """The scripts.rs contract (PROMPT I8) computed independently of build.rs: (MAIN path, {module name: path})."""
    src = root / "src"
    main = next((p for p in (src / "main.luau", src / "main.lua") if p.is_file()), None)
    assert main is not None, "no entry script"
    mods = {".".join(p.relative_to(src).with_suffix("").parts): str(p) for p in src.rglob("*.luau") if not p.name.endswith(".d.luau")}
    return str(main), mods


def parse_scripts_rs(text: str) -> tuple[str, dict[str, str]]:
    import re
    m = re.search(r'pub const MAIN: &str = include_str!\("([^"]*)"\);', text)
    assert m and "pub const SCRIPTS: &[(&str, &str)] = &[" in text, text
    return m.group(1), dict(re.findall(r'\("([^"]*)", include_str!\("([^"]*)"\)\),', text))


@test
def test_build_rs_static_contract():
    s = BUILD_RS.read_text()
    assert s.count("{") == s.count("}") and s.count("(") == s.count(")") and s.count("[") == s.count("]")
    for want in ("src/main.luau", "main.lua", "tools/bindgen.py", '"--root"', '"--out"', "scripts.rs", "pub const MAIN: &str", "pub const SCRIPTS: &[(&str, &str)]",
                 "include_str!", "cargo:rerun-if-changed", "OUT_DIR", "python3", ".d.luau"):
        assert want in s, want
    assert "extern crate" not in s and "unsafe" not in s                    # std only; edition 2024 makes env::set_var unsafe
    assert not any(l.lstrip().startswith("use ") and not l.lstrip().startswith("use std::") for l in s.splitlines())
    toml = (ROOT / "Cargo.toml").read_text() if (ROOT / "Cargo.toml").is_file() else ""
    assert "[build-dependencies]" not in toml


def build_rs_project() -> Path:
    r = fake_project()
    write(r / "src/main.luau", 'print("main")\n')
    write(r / "src/util/strings.luau", "return {}\n")
    write(r / "src/a/b/c.luau", "return 1\n")
    os.symlink(ROOT / "tools", r / "tools")                                 # build.rs runs `python3 tools/bindgen.py` relative to the root
    return r


def compile_build_rs(dst: Path) -> Path:
    exe = dst / "build_script"
    p = subprocess.run(["rustc", "--edition", "2024", str(BUILD_RS), "-o", str(exe)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return exe


def run_build_rs(exe: Path, r: Path, out: Path) -> subprocess.CompletedProcess:
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **fake_env(r), "CARGO_MANIFEST_DIR": str(r), "OUT_DIR": str(out)}
    return subprocess.run([str(exe)], capture_output=True, text=True, env=env, cwd=str(r.parent))


@test
def test_build_rs_compiles_and_runs():
    if shutil.which("rustc") is None:
        print("bindgen_selftest: A: no rustc on PATH, build.rs compile+run test SKIPPED (static checks only)")
        return
    r = build_rs_project()
    exe = compile_build_rs(r.parent)
    out = r.parent / "bout"
    p = run_build_rs(exe, r, out)
    assert p.returncode == 0, p.stderr
    assert (out / "gen_client.rs").is_file() and (r / "types/bindings.d.luau").is_file()          # the generator ran
    lines = p.stdout.splitlines()
    assert all(l.startswith(("cargo:rerun-if-changed=", "cargo:warning=")) for l in lines), p.stdout
    rer = {l.split("=", 1)[1] for l in lines if l.startswith("cargo:rerun-if-changed=")}
    for want in ("build.rs", str(r / "src"), str(r / "src/util"), str(r / "src/main.luau"), str(r / "src/a/b/c.luau")):
        assert want in rer, (want, rer)
    main, mods = parse_scripts_rs((out / "scripts.rs").read_text())
    assert (main, mods) == expected_scripts(r), (main, mods)
    assert set(mods) == {"main", "util.strings", "a.b.c"}                   # bindings.d.luau is not a script
    # main.lua is the fallback entry; with neither, the build fails naming src/
    os.rename(r / "src/main.luau", r / "src/main.lua")
    p = run_build_rs(exe, r, out)
    assert p.returncode == 0 and parse_scripts_rs((out / "scripts.rs").read_text())[0] == str(r / "src/main.lua"), p.stderr
    (r / "src/main.lua").unlink()
    p = run_build_rs(exe, r, out)
    assert p.returncode != 0 and "src/" in p.stderr, p.stderr


@test
def test_build_rs_fails_with_generator_stderr():
    if shutil.which("rustc") is None:
        return
    r = build_rs_project()
    exe = compile_build_rs(r.parent)
    (r / "bindgen.toml").write_text("not = [valid\n")                     # invalid config: bindgen.py's own error text must come through
    p = run_build_rs(exe, r, r.parent / "bout")
    assert p.returncode != 0 and p.stderr.strip(), p




def main() -> int:
    failed = 0
    try:
        for t in TESTS:
            try:
                t()
            except Exception as e:                                      # noqa: BLE001 - report every failing test
                failed += 1
                tb = traceback.extract_tb(e.__traceback__)[-1]
                print(f"FAIL {t.__name__}: {type(e).__name__}: {e} (line {tb.lineno})")
    finally:
        for d in _tmp:
            shutil.rmtree(d, ignore_errors=True)
            for sib in Path(d).parent.glob(Path(d).name + "*"):
                sib.unlink(missing_ok=True) if sib.is_file() else None
    if failed:
        print(f"bindgen_selftest: FAILED ({failed} of {len(TESTS)} tests)")
        return 1
    print(f"bindgen_selftest: OK ({len(TESTS)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
