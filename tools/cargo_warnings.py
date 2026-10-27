#!/usr/bin/env python3
"""cargo_warnings.py - count the compiler warnings / errors of one package in a `cargo build --message-format=json` log.

    cargo build --message-format=json > build.json

Plain `json`, not `json-render-diagnostics`: that one renders the diagnostics on stderr and leaves no `compiler-message` in the JSON, so
there would be nothing to count. The errors are printed here in their rendered (rustc) form, since `json` leaves them out of the build log.
    python3 tools/cargo_warnings.py build.json [--package luaxite] [--strict]

Only the packages named with --package (default: luaxite, which includes its build.rs and the generated bindings) are judged; the other
packages (azalea and the crates it pulls in) are only counted. Exit status: 1 when a judged package has an error, or (--strict) a warning;
2 when the log is missing or has no cargo messages; else 0.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

SUMMARY = re.compile(r"^(\d+ warnings? emitted|aborting due to .*|\d+ previous errors?.*)$")


def package_of(package_id: str) -> str:
    """The package name out of cargo's package_id (both the `path+file:///x/name#0.1.0` / `...#name@0.1.0` form and the old `name 0.1.0 (...)` one)."""
    m = re.search(r"#([A-Za-z0-9_\-]+)@", package_id) or re.match(r"([A-Za-z0-9_\-]+) \d", package_id) or re.search(r"/([A-Za-z0-9_\-]+)#[\d.]", package_id)
    return m.group(1) if m else package_id


def scan(lines):
    """-> (Counter[(package, level)], {package: [first line of each warning / error]}, number of cargo messages seen, [(package, rendered error)])"""
    counts, texts, seen, errors = Counter(), {}, 0, []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("reason") != "compiler-message":
            continue
        seen += 1
        msg = obj.get("message") or {}
        level = msg.get("level")
        if level not in ("warning", "error") or SUMMARY.match(msg.get("message", "")):
            continue
        pkg = package_of(obj.get("package_id", "?"))
        counts[(pkg, level)] += 1
        texts.setdefault(pkg, []).append(f"{level}: {msg.get('message', '')}")
        if level == "error":
            errors.append((pkg, msg.get("rendered") or f"error: {msg.get('message', '')}"))
    return counts, texts, seen, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log", help="cargo JSON log (a file, or - for stdin)")
    ap.add_argument("--package", action="append", default=None, help="package to judge (repeatable; default luaxite)")
    ap.add_argument("--strict", action="store_true", help="warnings in a judged package fail too")
    ap.add_argument("--show", type=int, default=20, help="print at most this many messages per judged package")
    ap.add_argument("--show-errors", type=int, default=10, help="print at most this many errors in full (rendered), from any package")
    a = ap.parse_args(argv)
    judged = a.package or ["luaxite"]
    if a.log == "-":
        lines = sys.stdin.read().splitlines()
    elif Path(a.log).is_file():
        lines = Path(a.log).read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        print(f"compiler diagnostics: no build log at {a.log} (the build did not run?)", file=sys.stderr)
        return 2
    counts, texts, seen, errors = scan(lines)
    if seen == 0:
        print("compiler diagnostics: no cargo messages in the log (not --message-format=json -- json-render-diagnostics keeps them out of the JSON -- "
              "or nothing was compiled)", file=sys.stderr)
        return 2
    bad = False
    for pkg in judged:
        w, e = counts[(pkg, "warning")], counts[(pkg, "error")]
        print(f"compiler diagnostics for {pkg}: {w} warning(s), {e} error(s)")
        for t in texts.get(pkg, [])[: a.show]:
            print(f"  {t}")
        if len(texts.get(pkg, [])) > a.show:
            print(f"  ... {len(texts[pkg]) - a.show} more")
        bad = bad or e > 0 or (a.strict and w > 0)
    for pkg, text in errors[: a.show_errors]:
        lines_ = text.rstrip().splitlines()
        print(f"\nerror in {pkg}:")
        print("\n".join(lines_[:60]) + (f"\n  ... {len(lines_) - 60} more lines" if len(lines_) > 60 else ""))
    if len(errors) > a.show_errors:
        print(f"\n... {len(errors) - a.show_errors} more error(s)")
    other_w = sum(n for (p, l), n in counts.items() if l == "warning" and p not in judged)
    other_e = sum(n for (p, l), n in counts.items() if l == "error" and p not in judged)
    print(f"other packages (not judged): {other_w} warning(s), {other_e} error(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
