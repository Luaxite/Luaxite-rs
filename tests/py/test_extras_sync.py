"""`// luau[Class]: function name(self, ..)` declarations in rust/luau/{extra,real}_*.rs vs the Rust method they annotate.

The generator copies those lines into azalea.d.luau as free text and never looks at the Rust; this keeps the parameter
counts in sync (Luau params minus `self` == Rust params minus `self` and the `Lua` handle). Self-less library-table decls
(`name: (..) -> ..`) are built from closures, not `fn` items, so they are out of scope here."""
import re
import tempfile
import unittest
from pathlib import Path

from _common import ROOT
import luaxite_gen as g

RUST_DIR = ROOT / "rust" / "luau"
FN_DECL = re.compile(r"function (\w+)\(")
OPEN, CLOSE = "([{<", ")]}>"


def balanced(text: str, start: int) -> str:
    """text[start] is the opening `(`: the text up to its matching `)` (strings and `->` ignored)."""
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'" and not (c == "'" and re.match(r"'\w+\b(?!')", text[i:i + 12])):
            quote = c
        elif c == "-" and text.startswith("->", i):
            i += 1
        elif c in OPEN:
            depth += 1
        elif c in CLOSE:
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    raise ValueError("unbalanced parameter list")


def split_top(params: str) -> list:
    """Split on commas outside any bracket/string; `->` is not a closing `>`."""
    out, depth, cur, quote, i = [], 0, "", None, 0
    while i < len(params):
        c = params[i]
        if quote:
            cur += c
            if c == quote:
                quote = None
        elif c in "\"'" and not (c == "'" and re.match(r"'\w+\b(?!')", params[i:i + 12])):
            quote = c
            cur += c
        elif c == "-" and params.startswith("->", i):
            cur += "->"
            i += 1
        elif c in OPEN:
            depth += 1
            cur += c
        elif c in CLOSE:
            depth -= 1
            cur += c
        elif c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def luau_param_count(decl: str) -> int:
    """`function name(self, a: T, b: U?): R` -> 2."""
    m = FN_DECL.match(decl)
    params = split_top(balanced(decl, m.end() - 1))
    assert params and params[0] == "self", f"a hand-written method must take self: {decl}"
    return len(params) - 1


def rust_param_count(src: str, name: str, after: int):
    """Parameter count of the first `fn name(` at/after offset `after` (self and the Lua handle excluded), or None."""
    m = re.compile(rf"\bfn\s+{re.escape(name)}\s*(?:<[^>]*>)?\s*\(").search(src, after)
    if not m:
        return None
    n = 0
    for p in split_top(balanced(src, m.end() - 1)):
        if re.fullmatch(r"(?:mut\s+)?(?:&\s*(?:mut\s+)?)?self", p):
            continue
        ty = p.split(":", 1)[1].strip() if ":" in p else p
        if re.fullmatch(r"&?\s*(?:mlua::)?Lua", ty):
            continue
        n += 1
    return n


def check_file(path: Path) -> tuple:
    """-> (number of decls checked, [problem strings])."""
    src = path.read_text(encoding="utf-8")
    problems, checked, off = [], 0, 0
    for ln in src.splitlines(keepends=True):
        end = off + len(ln)
        m = g.EXTRA_RE.match(ln.rstrip("\n"))
        if m and FN_DECL.match(m.group(2)):
            name = FN_DECL.match(m.group(2)).group(1)
            want = luau_param_count(m.group(2))
            got = rust_param_count(src, name, end)
            checked += 1
            if got is None:
                problems.append(f"{path.name}: luau[{m.group(1)}] {name}: no Rust fn {name} after the declaration")
            elif got != want:
                problems.append(f"{path.name}: luau[{m.group(1)}] {name}: Luau has {want} param(s), Rust fn has {got}")
        off = end
    return checked, problems


class ExtrasSync(unittest.TestCase):
    def test_decl_param_counts_match_rust(self):
        total, problems = 0, []
        for f in sorted([*RUST_DIR.glob("extra_*.rs"), *RUST_DIR.glob("real_*.rs")]):
            n, p = check_file(f)
            total += n
            problems += p
        self.assertGreater(total, 50, "the scan must find the hand-written method declarations")
        self.assertEqual(problems, [])

    def test_detects_mismatch(self):
        body = (
            "// luau[Bot]: function two(self, a: number, f: (x: number, y: number) -> ()): ()\n"
            "impl LuaBot {\n    fn two(&self, lua: &Lua, a: f64, f: Function) -> mlua::Result<()> {}\n}\n"
            "// luau[Bot]: function one(self, a: number): ()\n"
            "impl LuaBot {\n    fn one(&self, a: f64, b: f64) {}\n}\n"
            "// luau[Bot]: function gone(self): ()\n"
            "impl LuaBot {\n    fn other(&self) {}\n}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "extra_x.rs"
            p.write_text(body)
            n, problems = check_file(p)
        self.assertEqual(n, 3)
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("one: Luau has 1 param(s), Rust fn has 2", problems[0])
        self.assertIn("gone: no Rust fn gone", problems[1])

    def test_param_splitting(self):
        d = "function f(self, cb: (a: number, b: { x: number, y: number }) -> any, k: \"a\" | \"b,c\"?): ()"
        self.assertEqual(luau_param_count(d), 2)
        self.assertEqual(rust_param_count("fn f(&self, lua: Lua, g: impl FnMut(&str, u8) -> bool, v: Vec<(u8, u8)>) {}", "f", 0), 2)


if __name__ == "__main__":
    unittest.main()
