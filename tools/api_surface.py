#!/usr/bin/env python3
"""api_surface.py - is every API name in tools/baseline_api.txt still bound in the generated types/bindings.d.luau?

Same rule as the `== API surface` step of tools/check.sh, in Python so it runs the same on Linux, macOS and Windows (no grep / comm needed):
the bound names are the `function name` members plus the function-typed properties (`name: (..) -> ..`; the `goal` / `azalea` library tables
are called with `.`, so they have no `self`).

    python3 tools/api_surface.py [--bindings types/bindings.d.luau] [--baseline tools/baseline_api.txt]

Exit status: 0 = nothing vanished, 1 = names missing, 2 = a file is missing (the bindings only exist after a build against bind/azalea-src).
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def bound_names(text: str) -> set:
    names = set()
    for line in text.splitlines():
        m = re.match(r" *function ([A-Za-z_0-9]+)", line) or re.match(r" +([A-Za-z_0-9]+): \(", line)
        if m:
            names.add(m.group(1))
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bindings", default=str(ROOT / "types" / "bindings.d.luau"))
    ap.add_argument("--baseline", default=str(ROOT / "tools" / "baseline_api.txt"))
    a = ap.parse_args(argv)
    for label, path in (("bindings", a.bindings), ("baseline", a.baseline)):
        if not Path(path).is_file():
            print(f"API surface: {label} file not found: {path}", file=sys.stderr)
            return 2
    baseline = [l.strip() for l in Path(a.baseline).read_text(encoding="utf-8").splitlines() if l.strip()]
    bound = bound_names(Path(a.bindings).read_text(encoding="utf-8"))
    missing = sorted(set(baseline) - bound)
    print(f"API surface: {len(baseline)} baseline names, {len(bound)} bound names, {len(missing)} missing")
    if missing:
        print("names vanished from the bindings: " + " ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
