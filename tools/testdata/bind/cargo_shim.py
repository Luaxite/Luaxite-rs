#!/usr/bin/env python3
"""Stand-in for `cargo metadata` in tools/bindgen_selftest.py: prints tools/testdata/bind/<manifest dir relative to
$BINDGEN_SHIM_ROOT, `/` -> `__`>.json with @ROOT@ replaced by that root. Records the shape of real `cargo metadata --no-deps
--format-version 1` output (hand-written: no cargo in the authoring sandbox). Appends each call to $BINDGEN_SHIM_LOG if set."""
import os, sys
a = sys.argv[1:]
if a[:1] != ["metadata"] or "--no-deps" not in a or "--manifest-path" not in a:
    sys.exit("shim: expected `metadata --no-deps ... --manifest-path M`")
root = os.path.realpath(os.environ["BINDGEN_SHIM_ROOT"])
m = os.path.realpath(a[a.index("--manifest-path") + 1])
rel = os.path.relpath(os.path.dirname(m), root).replace(os.sep, "__")
if os.environ.get("BINDGEN_SHIM_LOG"):
    open(os.environ["BINDGEN_SHIM_LOG"], "a").write(rel + "\n")
f = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel + ".json")
if not os.path.isfile(f):
    sys.stderr.write("error: could not read manifest %s\n" % m)
    sys.exit(101)
sys.stdout.write(open(f).read().replace("@ROOT@", root))
