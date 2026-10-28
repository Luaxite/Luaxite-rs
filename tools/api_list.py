#!/usr/bin/env python3
"""api_list.py - the Luau API list (API.json, plus API_list.md rendered from it) from a generated .d.luau (stdlib only; called by tools/bindgen.py).

    python3 tools/api_list.py [--dluau types/bindings.d.luau] [--config bindgen.toml] [--out API_list.md] [--json-out API.json]

Reads the declarations tools/luaxite_gen.py wrote (`type ..`, `declare extern type X with .. end`, `declare name: X`) and lists one entry per
declaration, no doc comments. API.json holds it as data (`types`, `globals`, `classes[].members[]`); API_list.md is only the text view of it:

    # Luaxite Luau API
    ## Types       every `type ..` line (a multi-line union is joined onto one line)
    ## Globals     `declare name: Class`, by name
    ## `name`      a library global (a class of `name: (..) -> ..` members, e.g. `goal`): `declare function name.fn(..): R`, by name
    ## Class       the other classes: `declare function Class:method(..): R` (`self` dropped), by name; overloads (`on`, `wait_for`) keep their order

Class order: the classes of bindgen.toml `[classes.*]` first (Bot, Entity), then the rest in .d.luau order. No config = the .d.luau order.
Same input, same bytes. Exit status: 0 = written, 1 = unreadable input, 2 = usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TITLE = "# Luaxite Luau API"
INTRO = "Declarations for everything scripts can use. Generated; do not edit by hand."


class DluauError(Exception):
    pass


class Member:
    """One declaration inside a class: `function name(self, ..): R` (method) or `name: (..) -> R` (a self-less function of a library table)."""

    def __init__(self, name: str, params: str, ret: str, method: bool):
        self.name, self.params, self.ret, self.method = name, params, ret, method


class Class:
    def __init__(self, name: str):
        self.name = name
        self.members: list[Member] = []

    @property
    def is_library(self) -> bool:
        return bool(self.members) and not any(m.method for m in self.members)


class Model:
    def __init__(self):
        self.types: list[str] = []
        self.classes: dict[str, Class] = {}
        self.globals: dict[str, str] = {}


def matching_paren(s: str, start: int) -> int:
    """Index of the `)` that closes the `(` at s[start]; -1 when it never closes. Quoted strings (`"("`) are skipped."""
    depth, i, quote = 0, start, None
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_signature(rest: str) -> tuple[str, str] | None:
    """`(params): ret` -> (params, ret)   or   `(params) -> ret` -> (params, ret); the parens around params are dropped."""
    if not rest.startswith("("):
        return None
    end = matching_paren(rest, 0)
    if end < 0:
        return None
    params, tail = rest[1:end], rest[end + 1:].strip()
    for lead in (":", "->"):
        if tail.startswith(lead):
            return params, tail[len(lead):].strip()
    return None


def parse_method(line: str) -> Member | None:
    m = re.match(r"function\s+([A-Za-z_]\w*)\s*(\(.*)$", line)
    if not m:
        return None
    sig = split_signature(m.group(2))
    if not sig:
        return None
    params, ret = sig
    parts = re.match(r"self\s*(?:,\s*)?(.*)$", params, re.S)
    return Member(m.group(1), parts.group(1) if parts else params, ret, method=True)


def parse_property(line: str) -> Member | None:
    m = re.match(r"([A-Za-z_]\w*)\s*:\s*(\(.*?)\s*,?$", line)
    if not m:
        return None
    text = m.group(2)
    end = matching_paren(text, 0)
    tail = text[end + 1:].strip() if end >= 0 else ""
    if end < 0 or not tail.startswith("->"):
        return None
    return Member(m.group(1), text[1:end], tail[2:].strip(), method=False)


def parse(text: str) -> Model:
    model = Model()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1
        if not line or line.lstrip().startswith("--"):
            continue
        if line.startswith("type "):

            if line.endswith("="):
                alts = []
                while i < len(lines) and re.match(r"\s+\|", lines[i]):
                    alts.append(lines[i].strip().lstrip("|").strip())
                    i += 1
                line = line[:-1].rstrip() + " = " + " | ".join(alts) if alts else line
            model.types.append(line)
            continue
        m = re.match(r"declare extern type (\w+) with$", line)
        if m:
            cls = model.classes.setdefault(m.group(1), Class(m.group(1)))
            while i < len(lines) and lines[i].strip() != "end":
                body = lines[i].strip()
                i += 1
                if not body or body.startswith("--"):
                    continue
                mem = parse_method(body) or parse_property(body)
                if mem:
                    cls.members.append(mem)
            i += 1
            continue
        m = re.match(r"declare (\w+): \{$", line)
        if m:
            cls = model.classes.setdefault(m.group(1), Class(m.group(1)))
            model.globals[m.group(1)] = m.group(1)
            while i < len(lines) and lines[i].strip() != "}":
                body = lines[i].strip()
                i += 1
                mem = None if body.startswith("--") else parse_property(body)
                if mem:
                    cls.members.append(mem)
            i += 1
            continue
        m = re.match(r"declare (\w+): (\w+)$", line)
        if m:
            model.globals[m.group(1)] = m.group(2)
    return model


def class_priority(config: Path | None) -> list[str]:
    """Luau class names of bindgen.toml `[classes.*]`, in file order (the classes that lead the list); [] without a usable config."""
    if config is None or not config.is_file():
        return []
    try:
        import tomllib
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (ImportError, ValueError, OSError):
        return []
    table = data.get("classes")
    if not isinstance(table, dict):
        return []
    return [c["luau"] for c in table.values() if isinstance(c, dict) and isinstance(c.get("luau"), str)]


def code(s: str) -> str:
    """`s` as inline markdown code (a longer fence when s itself holds backticks)."""
    fence = "`" * (max((len(r) for r in re.findall(r"`+", s)), default=0) + 1)
    pad = " " if s.startswith("`") or s.endswith("`") else ""
    return f"{fence}{pad}{s}{pad}{fence}"


def bullets(rows: list[str]) -> list[str]:
    return [f"- {code(r)}" for r in rows] + [""]


API_SCHEMA = 1


def to_dict(model: Model, priority: list[str] | None = None) -> dict:
    """The API as plain data (the API.json that tools and CI read; API_list.md is rendered from it). Classes come in list order: library
    tables first (by global name), then the `priority` classes, then the rest in .d.luau order. Members are sorted by name (stable)."""
    lib_global = {}
    for g, c in sorted(model.globals.items()):
        cls = model.classes.get(c)
        if cls is not None and cls.is_library:
            lib_global.setdefault(c, g)

    def entry(cls: Class, prefix: str, library: bool) -> dict:
        members = []
        for mem in sorted(cls.members, key=lambda m: m.name):
            sep = ":" if mem.method else "."
            members.append(dict(name=mem.name, method=mem.method, params=mem.params, ret=mem.ret,
                                decl=f"declare function {prefix}{sep}{mem.name}({mem.params}): {mem.ret}"))
        return dict(name=cls.name, prefix=prefix, library=library, members=members)

    classes = [entry(model.classes[c], g, True) for g, c in sorted((g, c) for c, g in lib_global.items())]
    first = [c for c in (priority or []) if c in model.classes]
    rest = [c for c in model.classes if c not in first]
    classes += [entry(model.classes[n], n, False) for n in first + rest if n not in lib_global]
    return dict(
        schema=API_SCHEMA,
        types=list(model.types),
        globals=[dict(name=g, type=c) for g, c in sorted(model.globals.items())],
        classes=classes,
    )


def render(api: dict) -> str:
    """API_list.md: a human-readable view of `to_dict`'s data. Nothing reads it back; read API.json instead."""
    out = [TITLE, "", INTRO, ""]
    if api["types"]:
        out += ["## Types", ""] + bullets(api["types"])
    if api["globals"]:
        out += ["## Globals", ""] + bullets([f"declare {g['name']}: {g['type']}" for g in api["globals"]])
    for cls in api["classes"]:
        rows = [m["decl"] for m in cls["members"]]
        if rows:
            out += [f"## `{cls['prefix']}`" if cls["library"] else f"## {cls['name']}", ""] + bullets(rows)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def build_dict(dluau: str, config: Path | None = None) -> dict:
    return to_dict(parse(dluau), class_priority(config))


def build(dluau: str, config: Path | None = None) -> str:
    return render(build_dict(dluau, config))


def dumps(api: dict) -> str:
    """API.json text. Same input, same bytes."""
    return json.dumps(api, indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dluau", default=str(ROOT / "types" / "bindings.d.luau"))
    ap.add_argument("--config", default=str(ROOT / "bindgen.toml"), help="bindgen.toml: its [classes.*] decide which classes come first")
    ap.add_argument("--out", default="-", help="API_list.md (the text view) to write (default: stdout)")
    ap.add_argument("--json-out", default=None, help="API.json (the machine-readable list) to write")
    a = ap.parse_args(argv)
    src = Path(a.dluau)
    if not src.is_file():
        print(f"error: {src} not found (it is written by tools/bindgen.py)", file=sys.stderr)
        return 1
    api = build_dict(src.read_text(encoding="utf-8"), Path(a.config))
    text = render(api)
    if a.json_out:
        Path(a.json_out).write_text(dumps(api), encoding="utf-8")
    if a.out == "-":
        sys.stdout.write(text)
    else:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
