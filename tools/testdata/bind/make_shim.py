#!/usr/bin/env python3
"""Stand-in for tools/make_rustdoc_json.sh in tools/bindgen_selftest.py: `make_shim.py CRATE_DIR OUT_DIR` writes `<lib>.json` (`{}`)
and `<lib>.meta` (rustc from `rustc -V` of $BINDGEN_RUSTC under RUSTUP_TOOLCHAIN, source_sha1 via tools/rdj.py) and appends
`<lib> <RUSTUP_TOOLCHAIN> <AZL_RDJ_ENV> <AZL_RDJ_OFFLINE>` to $BINDGEN_SHIM_LOG. Exits 1 for a crate dir named `*broken*`."""
import os, subprocess, sys, tomllib
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", ".."))
import rdj
d, out = sys.argv[1], sys.argv[2]
lib = tomllib.load(open(os.path.join(d, "Cargo.toml"), "rb"))["package"]["name"].replace("-", "_")
if "broken" in lib:
    sys.stderr.write("error[E0432]: unresolved import in %s\nmore noise\n" % lib)
    sys.exit(1)
env = os.environ
open(env["BINDGEN_SHIM_LOG"] + ".make", "a").write(f"{lib} {env['RUSTUP_TOOLCHAIN']} {env['AZL_RDJ_ENV']} {env['AZL_RDJ_OFFLINE']}\n")
ver = subprocess.run([env["BINDGEN_RUSTC"], "-V"], capture_output=True, text=True).stdout.strip()
open(os.path.join(out, lib + ".json"), "w").write("{}")
open(os.path.join(out, lib + ".meta"), "w").write(f"rustc: {ver}\nformat_version: 57\nprivate_items: 1\nsource_sha1: {rdj.source_sha1(d)}\n")
print("wrote:", lib)
