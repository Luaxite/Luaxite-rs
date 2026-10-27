#!/usr/bin/env python3
"""bindgen_rdj.py - rustdoc JSON for every bound crate (stdlib only; PROMPT item I4).

For each crate of tools/bindgen_crates.py (dependencies first) run `sh tools/make_rustdoc_json.sh <crate dir> <out>/rdj`
(AZL_RDJ_ENV=0 AZL_RDJ_OFFLINE=0: the user's own cargo, network allowed) with RUSTUP_TOOLCHAIN set to the channel of
rust-toolchain.toml in the crate's workspace, else in the project root, else `nightly`.
Cache: a crate is skipped when `<out>/rdj/<lib>.json` exists and its `<lib>.meta` has the same `source_sha1` (rdj.source_sha1 of the
crate dir) and the same `rustc` line as `rustc -V` under that toolchain.

    python3 tools/bindgen_rdj.py --root R --out O      # prints a JSON list: name lib dir status(built|cached) json
Env (tests): BINDGEN_MAKE_RDJ = script run instead of tools/make_rustdoc_json.sh; BINDGEN_RUSTC = rustc binary (default rustc).
Missing python3 / cargo / toolchain: one line `error: ...`, exit 1.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bindgen_crates  # noqa: E402
from bindgen_crates import CrateError  # noqa: E402
from rdj import source_sha1  # noqa: E402

DEFAULT_CHANNEL = "nightly"


def channel_of(directory) -> str | None:
    """`toolchain.channel` of DIR/rust-toolchain.toml; None when the file or key is missing."""
    f = Path(directory) / "rust-toolchain.toml"
    if not f.is_file():
        return None
    try:
        ch = tomllib.loads(f.read_text(encoding="utf-8")).get("toolchain", {}).get("channel")
    except (OSError, ValueError) as e:
        raise CrateError(f"cannot read {f}: {' '.join(str(e).split())[:160]}") from None
    return ch if isinstance(ch, str) and ch else None


def toolchain_for(crate: dict, root) -> str:
    return channel_of(crate["workspace_root"]) or channel_of(root) or DEFAULT_CHANNEL


def _first_line(text: str) -> str:
    return next((l.strip() for l in text.splitlines() if l.strip()), "no output")[:200]


def rustc_version(channel: str, cache: dict) -> str:
    """`rustc -V` under RUSTUP_TOOLCHAIN=channel (memoised)."""
    if channel not in cache:
        rustc = os.environ.get("BINDGEN_RUSTC") or "rustc"
        try:
            p = subprocess.run([rustc, "-V"], capture_output=True, text=True, env={**os.environ, "RUSTUP_TOOLCHAIN": channel})
        except OSError:
            raise CrateError(f"cannot run {rustc}; install Rust (rustup) first") from None
        if p.returncode != 0:
            raise CrateError(f"toolchain `{channel}` is not usable: {_first_line(p.stderr)} (rustup toolchain install {channel})")
        cache[channel] = p.stdout.strip()
    return cache[channel]


def read_meta(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text().splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def make_all(root, out) -> list[dict]:
    """Make (or reuse) rustdoc JSON for every crate under `root` into `<out>/rdj`. Raises CrateError."""
    root, rdj_dir = Path(root), Path(out) / "rdj"
    if shutil.which("python3") is None:
        raise CrateError("python3 not found on PATH (tools/make_rustdoc_json.sh needs it)")
    make = os.environ.get("BINDGEN_MAKE_RDJ") or str(HERE / "make_rustdoc_json.sh")
    if not os.environ.get("BINDGEN_MAKE_RDJ") and shutil.which(os.environ.get("BINDGEN_CARGO") or "cargo") is None:
        raise CrateError("cargo not found on PATH (install Rust via rustup)")
    crates = bindgen_crates.resolve(root)
    rdj_dir.mkdir(parents=True, exist_ok=True)
    versions: dict = {}
    results = []
    for c in crates:
        chan = toolchain_for(c, root)
        rustc = rustc_version(chan, versions)
        meta = read_meta(rdj_dir / f"{c['lib']}.meta")
        if (rdj_dir / f"{c['lib']}.json").is_file() and meta.get("source_sha1") == source_sha1(c["dir"]) and meta.get("rustc") == rustc:
            status = "cached"
        else:
            env = {**os.environ, "RUSTUP_TOOLCHAIN": chan, "AZL_RDJ_ENV": "0", "AZL_RDJ_OFFLINE": "0"}
            try:
                p = subprocess.run(["sh", make, c["dir"], str(rdj_dir)], capture_output=True, text=True, env=env)
            except OSError as e:
                raise CrateError(f"cannot run {make}: {e}") from None
            if p.returncode != 0:
                raise CrateError(f"rustdoc JSON failed for {c['name']} (toolchain {chan}): {_first_line(p.stderr or p.stdout)}")
            if not (rdj_dir / f"{c['lib']}.json").is_file():
                raise CrateError(f"rustdoc JSON for {c['name']}: {c['lib']}.json was not written to {rdj_dir}")
            status = "built"
        results.append({"name": c["name"], "lib": c["lib"], "dir": c["dir"], "status": status, "json": str(rdj_dir / f"{c['lib']}.json")})
    return results


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 4 or a[0] != "--root" or a[2] != "--out":
        print("usage: bindgen_rdj.py --root R --out O", file=sys.stderr)
        return 2
    try:
        res = make_all(a[1], a[3])
    except CrateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    json.dump(res, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
