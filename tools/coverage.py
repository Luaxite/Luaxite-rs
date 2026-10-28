#!/usr/bin/env python3
"""Coverage ledger check: every azalea API the generator skips must be classified in tools/coverage.toml.

usage: python3 tools/coverage.py [--report $GEN_REPORT|GEN_REPORT.json] [--dluau types/bindings.d.luau] [--toml tools/coverage.toml]
                                 [--strict] [--todo [sN]] [--quiet] | --selftest

Keys = what GEN_REPORT.json lists as not generated: `Client.<fn>` / `EntityRef.<fn>` (Skipped methods), `Goal.<Type>` (Goals not exposed),
`Event.<Variant>` (Events notes), plus `extra.<name>` for APIs the report cannot see. Status strings (tools/coverage.toml):
  hand <Luau name | Class.name>   bound by hand (rust/luau/extra_*.rs etc.); the name must be declared in types/bindings.d.luau
  todo sN <what>                  planned, owned by slice N of the current chain
  no <reason>                     cannot / must not be a script API (reason >= 10 chars)
Exit 1 when: a skipped API has no entry (unclassified), an entry matches nothing (stale), a `hand` name is not in the .d.luau,
a status is malformed; with --strict also on any `todo`. Stdlib only.
"""
import json
import re
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_SLICE = 20
CLASS_LUAU = {"Client": "Bot", "EntityRef": "Entity"}
SECTIONS = ("Client", "EntityRef", "Goal", "Event", "extra")
REPORT_SCHEMA = 1


class ReportError(Exception):
    pass


def load_report(path):
    """GEN_REPORT.json -> dict. Anything else (a stale GEN_REPORT.md, broken JSON, another schema) is a ReportError, never a guess."""
    path = Path(path)
    if path.suffix == ".md":
        raise ReportError(f"{path.name} is the text view; pass the machine-readable GEN_REPORT.json next to it")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReportError(f"cannot read {path}: {e}")
    if not isinstance(data, dict) or data.get("schema") != REPORT_SCHEMA:
        raise ReportError(f"{path.name}: expected a report with schema {REPORT_SCHEMA}, got {data.get('schema') if isinstance(data, dict) else type(data).__name__}")
    return data


def parse_report(data):
    """-> set of keys the report lists as not generated."""
    keys = set()
    for cls in data.get("classes") or []:
        for sk in cls.get("skipped") or []:
            keys.add(f"{cls['name']}.{sk['name']}")
    for g in data.get("goals_not_exposed") or []:
        keys.add(f"Goal.{g['name']}")
    for n in (data.get("events") or {}).get("not_exposed") or []:
        keys.add(f"Event.{n['variant']}")
    return keys


def parse_dluau(text):
    """-> {Luau class: {function names}}. A function is `function name(self, ..)` or, for self-less library tables (`goal`, `azalea`), a
    property of function type `name: (..) -> ..`."""
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"declare extern type (\w+)", line)
        if m:
            cur = out.setdefault(m.group(1), set())
        elif cur is not None and (fm := re.match(r"\s*(?:function\s+(\w+)|(\w+):\s*\()", line)):
            cur.add(fm.group(1) or fm.group(2))
        elif line.startswith("end"):
            cur = None
    return out


def classify(status):
    """-> (kind, detail) or raises ValueError."""
    status = status.strip()
    m = re.match(r"(hand|todo|no)\b\s*(.*)$", status)
    if not m:
        raise ValueError(f"status must start with hand|todo|no, got `{status}`")
    kind, rest = m.groups()
    if kind == "hand" and not re.fullmatch(r"(\w+\.)?\w+( .*)?", rest):
        raise ValueError("`hand` needs a Luau name (Name or Class.name)")
    if kind == "todo" and not re.match(r"s(\d{1,2})\b", rest):
        raise ValueError("`todo` needs an owner slice: `todo sN what`")
    if kind == "todo" and not 2 <= int(re.match(r"s(\d+)", rest).group(1)) <= MAX_SLICE:
        raise ValueError(f"`todo` slice must be s2..s{MAX_SLICE}")
    if kind == "no" and len(rest) < 10:
        raise ValueError("`no` needs a reason of at least 10 characters")
    return kind, rest


def run(report, dluau, toml_path, strict=False, todo=None, quiet=False):
    problems = []
    skipped = parse_report(load_report(report))
    luau = parse_dluau(Path(dluau).read_text())
    ledger = tomllib.loads(Path(toml_path).read_text())
    for sec in ledger:
        if sec not in SECTIONS:
            problems.append(f"unknown section [{sec}] (allowed: {', '.join(SECTIONS)})")
    entries = {}
    for sec in SECTIONS:
        for name, status in (ledger.get(sec) or {}).items():
            entries[f"{sec}.{name}"] = (sec, status)
    counts = {"hand": 0, "todo": 0, "no": 0}
    rows = []
    for key in sorted(entries):
        sec, status = entries[key]
        try:
            kind, rest = classify(status)
        except ValueError as e:
            problems.append(f"{key}: {e}")
            continue
        counts[kind] += 1
        rows.append((key, kind, rest))
        if sec != "extra" and key not in skipped:
            problems.append(f"{key}: stale entry (the report no longer lists it as skipped; delete it)")
        if kind == "hand":
            name = rest.split()[0]
            cls, _, fn = name.rpartition(".")
            cls = cls or CLASS_LUAU.get(sec, "Bot")
            if fn not in luau.get(cls, set()):
                problems.append(f"{key}: `hand {name}` but {cls}.{fn} is not declared in {Path(dluau).name}")
        if kind == "todo" and strict:
            problems.append(f"{key}: still todo ({rest}) under --strict")
    for key in sorted(skipped - set(entries)):
        problems.append(f"{key}: unclassified (add it to tools/coverage.toml)")
    if todo is not None:
        want = todo if todo else None
        for key, kind, rest in rows:
            if kind == "todo" and (want is None or rest.split()[0] == want):
                print(f"{key}\t{rest}")
        return 0
    if not quiet:
        total = len(skipped) + sum(1 for k, (s, _) in entries.items() if s == "extra")
        print(f"coverage ledger: {total} not-generated APIs: {counts['hand']} hand-written, {counts['todo']} todo, {counts['no']} not a script API")
        by_slice = {}
        for _, kind, rest in rows:
            if kind == "todo":
                by_slice[rest.split()[0]] = by_slice.get(rest.split()[0], 0) + 1
        if by_slice:
            print("  todo by slice: " + ", ".join(f"{s}={n}" for s, n in sorted(by_slice.items(), key=lambda kv: int(kv[0][1:]))))
    for p in problems:
        print("coverage: " + p)
    return 1 if problems else 0


def selftest():
    """Synthetic report/.d.luau/ledger: every check of `run` must fire on its own bad input and stay quiet on the good one."""
    import contextlib
    import io
    import tempfile

    report = {
        "schema": REPORT_SCHEMA,
        "classes": [
            {"name": "Client", "skipped": [{"name": "component", "sig": "pub fn component<T>(&self) -> T", "reason": "generic method"},
                                           {"name": "physics", "sig": "pub fn physics(&self) -> Physics", "reason": "other"}]},
            {"name": "EntityRef", "skipped": [{"name": "id", "sig": "pub fn id(&self) -> Entity", "reason": "x"}]},
        ],
        "goals_not_exposed": [{"name": "AndGoal", "why": "generic"}],
        "events": {"not_exposed": [{"variant": "Init", "why": "fires early"}]},
    }
    dluau = "declare extern type Bot with\n    function physics(self): { x: number }\nend\n"
    good = ('[Client]\ncomponent = "todo s5 bot:component(name)"\nphysics = "hand physics"\n[EntityRef]\nid = "no raw ECS ids are internal"\n'
            '[Goal]\nAndGoal = "todo s3 goal.all"\n[Event]\nInit = "todo s2 replay"\n[extra]\nQuickCraft = "todo s7 drag"\n')

    def go(toml_text, **kw):
        with tempfile.TemporaryDirectory() as d:
            files = {"r.json": json.dumps(report), "d.luau": dluau, "l.toml": toml_text}
            for n, t in files.items():
                (Path(d) / n).write_text(t)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run(Path(d) / "r.json", Path(d) / "d.luau", Path(d) / "l.toml", quiet=True, **kw)
            return rc, out.getvalue()

    def bad(text, needle, **kw):
        rc, out = go(text, **kw)
        assert rc == 1 and needle in out, f"expected `{needle}` in: {out!r} (rc {rc})"

    rc, out = go(good)
    assert rc == 0 and out == "", out
    bad(good, "still todo", strict=True)
    bad(good.replace('component = "todo s5 bot:component(name)"\n', ""), "Client.component: unclassified")
    bad(good.replace('[extra]', '[Client2]\n[extra]'), "unknown section")
    bad(good.replace("[EntityRef]\n", "[EntityRef]\nghost = \"no never existed in report\"\n"), "EntityRef.ghost: stale entry")
    bad(good.replace('physics = "hand physics"', 'physics = "hand nothere"'), "not declared")
    bad(good.replace('"todo s5 bot:component(name)"', '"todo bot:component(name)"'), "needs an owner slice")
    bad(good.replace('"todo s5 bot:component(name)"', f'"todo s{MAX_SLICE + 1} x"'), f"s2..s{MAX_SLICE}")
    bad(good.replace('"todo s5 bot:component(name)"', '"todo s1 x"'), "s2..")
    bad(good.replace('"no raw ECS ids are internal"', '"no short"'), "at least 10")
    bad(good.replace('"no raw ECS ids are internal"', '"maybe later"'), "must start with")

    got = parse_dluau("declare extern type GoalLib with\n    block: (pos: number) -> number\n    function describe(self): string\n    count: number\nend\n")
    assert got == {"GoalLib": {"block", "describe"}}, got

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "GEN_REPORT.md").write_text("## Skipped methods\n")
        (Path(d) / "old.json").write_text(json.dumps({"schema": 0}))
        for name in ("GEN_REPORT.md", "old.json", "missing.json"):
            try:
                load_report(Path(d) / name)
            except ReportError:
                continue
            raise AssertionError(f"{name} was accepted")
    print("coverage selftest: OK")
    return 0


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    a = {"--report": os.environ.get("GEN_REPORT", str(ROOT / "GEN_REPORT.json")), "--dluau": str(ROOT / "types/bindings.d.luau"), "--toml": str(ROOT / "tools/coverage.toml")}
    strict = quiet = False
    todo = None
    it = iter(argv)
    for arg in it:
        if arg in a:
            a[arg] = next(it, None) or sys.exit(f"{arg} needs a value")
        elif arg == "--strict":
            strict = True
        elif arg == "--quiet":
            quiet = True
        elif arg == "--todo":
            todo = ""
        elif todo == "" and re.fullmatch(r"s\d+", arg):
            todo = arg
        else:
            sys.exit(__doc__)
    try:
        return run(a["--report"], a["--dluau"], a["--toml"], strict, todo, quiet)
    except ReportError as e:
        print(f"coverage: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
