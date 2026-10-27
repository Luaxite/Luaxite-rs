#!/usr/bin/env python3
"""Superset check: does the rustdoc front end generate at least the API of the committed bindings?

    python3 tools/rdj_superset.py COMMITTED_RUST_DIR COMMITTED_LUAU_DIR RDJ_RUST_DIR RDJ_LUAU_DIR [--allow FILE]

Every API item of a committed file must also exist in the rdj output; items only the rdj output has are fine (reported, not an error).
Items are compared as sets by identity, not by line: an item whose body grew (a packet type that gained fields) still counts as present.

  rust file   item = (enclosing fn, name) of every `struct/enum/fn/const/static/type NAME`, `"label" =>` match arm, `EcsEntry { name: ".." }`
  azalea.d.luau  item = (enclosing `declare extern type` / `declare`, name) of every `type`, `declare`, member `name:` and `function name`

--allow FILE: one `<file>: <item>` per line (`#` comments); known gaps that may be missing. Allowed items that are no longer missing are listed
so the file can shrink. Exit 1 when a non-allowed item is missing.
"""
import re
import sys
from pathlib import Path

RUST = ["gen_client.rs", "gen_types.rs", "gen_events.rs", "gen_packets_in.rs", "gen_packets_out.rs", "gen_ecs.rs"]
R_FN = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)")
R_DECL = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|const|static|type|trait)\s+(\w+)")
R_ARM = re.compile(r'^\s*"([^"]+)"\s*(?:\|\s*"[^"]+"\s*)*(?:=>|if\b)')
R_ECS = re.compile(r'EcsEntry\s*\{\s*name:\s*"([^"]+)"')
L_TYPE = re.compile(r"^(?:export\s+)?type\s+(\w+)")
L_BLOCK = re.compile(r"^declare\s+(?:extern\s+)?(?:type|class)\s+(\w+)")
L_GLOBAL = re.compile(r"^declare\s+(\w+)\s*:")
L_FUNC = re.compile(r"^\s+(?:function\s+)?(\w+)\s*[:(]")


def rust_items(text: str) -> set:
    out, fn = set(), "<top>"
    for line in text.splitlines():
        if (m := R_FN.match(line)):
            fn = m.group(1)
            out.add((fn, "fn " + m.group(1)))
            continue
        if (m := R_DECL.match(line)):
            out.add(("<top>", m.group(0).strip().split("(")[0].split("{")[0].split("<")[0].split(";")[0].split("=")[0].strip()))
        if (m := R_ECS.search(line)):
            out.add(("ECS_ENTRIES", m.group(1)))
        elif (m := R_ARM.match(line)):
            out.add((fn, m.group(1)))
    return out


def luau_items(text: str) -> set:
    out, block = set(), "<top>"
    for line in text.splitlines():
        if (m := L_BLOCK.match(line)):
            block = m.group(1)
            out.add(("<top>", "extern type " + block))
        elif (m := L_TYPE.match(line)):
            out.add(("<top>", "type " + m.group(1)))
        elif (m := L_GLOBAL.match(line)):
            out.add(("<top>", "declare " + m.group(1)))
        elif line.startswith("end"):
            block = "<top>"
        elif block != "<top>" and (m := L_FUNC.match(line)):
            out.add((block, m.group(1)))
    return out


def load_allow(path):
    allow = set()
    if path:
        for raw in Path(path).read_text().splitlines():
            raw = raw.split("#", 1)[0].strip()
            if raw:
                allow.add(raw)
    return allow


def main(argv):
    allow_file = None
    if "--allow" in argv:
        i = argv.index("--allow")
        allow_file = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) != 4:
        print(__doc__)
        return 2
    c_rust, c_luau, r_rust, r_luau = map(Path, argv)
    allow = load_allow(allow_file)
    pairs = [(f, c_rust / f, r_rust / f, rust_items) for f in RUST]
    pairs.append(("azalea.d.luau", c_luau / "azalea.d.luau", r_luau / "azalea.d.luau", luau_items))
    bad, extra_total, stale = 0, 0, []
    for name, committed, rdj, items in pairs:
        if not committed.exists():
            continue                      # e.g. no gen_ecs.rs committed
        if not rdj.exists():
            print(f"MISSING FILE  {name}: the rustdoc front end wrote nothing")
            bad += 1
            continue
        want, got = items(committed.read_text()), items(rdj.read_text())
        missing = sorted(want - got)
        extra_total += len(got - want)
        real = []
        for blk, it in missing:
            key = f"{name}: {blk}::{it}" if blk != "<top>" else f"{name}: {it}"
            if key not in allow:
                real.append(key)
        for key in sorted(k for k in allow if k.startswith(name + ": ")):
            if not any((f"{name}: {b}::{i}" if b != "<top>" else f"{name}: {i}") == key for b, i in missing):
                stale.append(key)
        status = "ok" if not real else f"{len(real)} MISSING"
        print(f"{name}: committed {len(want)} items, rdj {len(got)}, +{len(got - want)} only in rdj -> {status}")
        for key in real:
            print(f"    missing in rdj: {key[len(name) + 2:]}")
        bad += len(real)
    for key in stale:
        print(f"note: allowed gap no longer present, drop it from the allow file: {key}")
    print(f"rdj-only items: {extra_total} (fine)")
    if bad:
        print(f"FAIL: the rustdoc front end lost {bad} API item(s) the committed bindings have")
        return 1
    print("OK: the rustdoc front end output is a superset of the committed API")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
