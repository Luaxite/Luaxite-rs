#!/usr/bin/env python3
"""bindgen.py - bindings for every crate under `bind/` (stdlib only; PROMPT item I5). Called by build.rs.

    python3 tools/bindgen.py --root R --out O

1. tools/bindgen_crates.py: the crate set (roots in R/bind + path deps of R/Cargo.toml, closure over path deps)
2. tools/bindgen_rdj.py: rustdoc JSON of each crate into O/rdj (cached)
3. tools/luaxite_gen.py on the JSON -> O/gen_*.rs (+ O/inc/gen_*.rs without `#![..]`), O/bindings.d.luau, O/GEN_REPORT.md; the .d.luau is copied to R/types/
   (only when its content changed, so cargo's rerun-if-changed does not fire every build)
4. tools/api_list.py on that .d.luau -> O/API.json (the API list as data: what tools and CI read) and O/API_list.md (its text view for
   people, never parsed), both copied to R/types/ the same way
The generator reads the hand-written glue next to its output: R/rust/luau/{extra,real}_*.rs are copied to O first.

stdout carries only `cargo:rerun-if-changed=PATH` and `cargo:warning=LINE` lines. Any failure: `error: ...` on stderr, exit 1, no stdout.
Env (tests): BINDGEN_GENERATOR = script run instead of tools/luaxite_gen.py.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api_list
import bindgen_crates
import bindgen_rdj
from bindgen_crates import CrateError

D_LUAU = "bindings.d.luau"
API_LIST = "API_list.md"
API_JSON = "API.json"


def stage_sources(crates: list[dict], out: Path) -> Path:
    """O/bind/<package name> -> crate dir (the generator scans `<root>/<name>/src/lib.rs`); symlinks, copies where those fail."""
    stage = out / "bind"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for c in crates:
        link = stage / c["name"]
        try:
            link.symlink_to(c["dir"], target_is_directory=True)
        except OSError:
            shutil.copytree(c["dir"], link, ignore=shutil.ignore_patterns("target", ".git"))
    return stage


def copy_glue(root: Path, out: Path) -> None:
    for old in list(out.glob("extra_*.rs")) + list(out.glob("real_*.rs")):
        old.unlink()
    for pat in ("extra_*.rs", "real_*.rs"):
        for f in sorted((root / "rust" / "luau").glob(pat)):
            shutil.copy(f, out / f.name)


def write_inc(out: Path) -> None:
    """O/inc/gen_*.rs = O/gen_*.rs minus file-level inner attributes (`#![allow(..)]`): rustc rejects those in an `include!`d file, so the
    host wraps each in `#[allow(..)] mod gen_x { include!(\"$OUT_DIR/inc/gen_x.rs\") }` (rust/luau/generated.rs)."""
    inc = out / "inc"
    shutil.rmtree(inc, ignore_errors=True)
    inc.mkdir()
    for f in sorted(out.glob("gen_*.rs")):
        keep = [l for l in f.read_text().splitlines(keepends=True) if not l.startswith("#![")]
        (inc / f.name).write_text("".join(keep))


def rerun_lines(root: Path, crates: list[dict]) -> list[str]:
    paths = [root / "src", root / "rust"]
    for c in crates:
        paths += [Path(c["dir"]) / "src", Path(c["manifest"])]
    paths.append(root / "bindgen.toml")
    paths += sorted(Path(p) for p in glob.glob(str(root / "tools" / "*.py")))
    return [f"cargo:rerun-if-changed={p}" for p in paths]


def run(root, out) -> list[str]:
    """Do the work; returns the stdout lines. Raises CrateError."""
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    crates = bindgen_crates.resolve(root)
    if not crates:
        raise CrateError(f"no crates to bind under {root / 'bind'} (put a crate there or add a path dependency to Cargo.toml)")
    bindgen_rdj.make_all(root, out)
    stage = stage_sources(crates, out)
    copy_glue(root, out)
    gen = os.environ.get("BINDGEN_GENERATOR") or str(HERE / "luaxite_gen.py")
    cmd = [sys.executable, gen, "--azalea", str(stage), "--rustdoc", str(out / "rdj"), "--rust-out", str(out), "--luau-out", str(out)]
    cmd += ["--config", str(root / "bindgen.toml") if (root / "bindgen.toml").is_file() else "builtin"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        msg = p.stderr.strip() or p.stdout.strip() or f"exit {p.returncode}"
        raise CrateError(msg if msg.startswith("error:") else f"generator failed: {msg}")
    lines = [f"cargo:warning={l.strip()}" for l in p.stderr.splitlines() if l.strip()]
    produced = out / "azalea.d.luau"
    if produced.is_file():
        os.replace(produced, out / D_LUAU)
    if not (out / D_LUAU).is_file():
        raise CrateError(f"generator wrote no {D_LUAU} in {out}")
    text = (out / D_LUAU).read_text()
    cfg = root / "bindgen.toml"
    api = api_list.build_dict(text, cfg if cfg.is_file() else None)
    listing, api_json = api_list.render(api), api_list.dumps(api)
    (out / API_LIST).write_text(listing, encoding="utf-8")
    (out / API_JSON).write_text(api_json, encoding="utf-8")
    for name, body in ((D_LUAU, text), (API_LIST, listing), (API_JSON, api_json)):
        dest = root / "types" / name
        if not dest.is_file() or dest.read_text() != body:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body)
    write_inc(out)
    return rerun_lines(root, crates) + lines


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 4 or a[0] != "--root" or a[2] != "--out":
        print("usage: bindgen.py --root R --out O", file=sys.stderr)
        return 2
    try:
        lines = run(a[1], a[3])
    except CrateError as e:
        print(f"error: {e}" if not str(e).startswith("error:") else str(e), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
