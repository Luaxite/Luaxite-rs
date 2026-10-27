"""A cheap structural check of every Luau script (no Luau interpreter is needed): strings / comments are skipped, then brackets must
balance and every `function` / `if` / `do` / `repeat` must be closed by `end` / `until`. It cannot prove a script runs; it catches the
typos (a missing `end`, an unclosed `{`) that would otherwise only show in the e2e run."""
import glob
import re
import unittest
from pathlib import Path

from _common import ROOT

FILES = sorted(glob.glob(str(ROOT / "tests/e2e/*.luau")) + glob.glob(str(ROOT / "tests/e2e/**/*.luau"), recursive=True))
EXPR_PREV = {"=", "(", ",", "return", "and", "or", "not", "+", "-", "*", "/", ".." , "{", "==", "~=", "<", ">", "<=", ">=", "else", "then", "in"}


def tokens(src: str):
    """Yield (kind, text, line) for words and punctuation; strings, comments are dropped."""
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif src.startswith("--", i):
            m = re.match(r"--\[(=*)\[", src[i:])
            if m:
                end = src.find("]" + m.group(1) + "]", i)
                end = n if end < 0 else end + len(m.group(1)) + 2
                line += src[i:end].count("\n")
                i = end
            else:
                while i < n and src[i] != "\n":
                    i += 1
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if j < n and src[j] == "\n":
                    line += 1
                j += 1
            yield ("str", src[i:j + 1], line)
            i = j + 1
        elif c == "`":
            j, depth = i + 1, 0
            while j < n and not (src[j] == "`" and depth == 0):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                if j < n and src[j] == "\n":
                    line += 1
                j += 1
            yield ("str", src[i:j + 1], line)
            i = j + 1
        elif src.startswith("[", i) and re.match(r"\[=*\[", src[i:]):
            m = re.match(r"\[(=*)\[", src[i:])
            end = src.find("]" + m.group(1) + "]", i)
            end = n if end < 0 else end + len(m.group(1)) + 2
            line += src[i:end].count("\n")
            yield ("str", "[[...]]", line)
            i = end
        elif c.isalpha() or c == "_":
            m = re.match(r"[A-Za-z_][A-Za-z_0-9]*", src[i:])
            yield ("word", m.group(0), line)
            i += len(m.group(0))
        elif c.isdigit():
            m = re.match(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|[0-9][0-9_]*(\.[0-9_]*)?([eE][+-]?[0-9]+)?", src[i:])
            yield ("num", m.group(0), line)
            i += len(m.group(0))
        else:
            two = src[i:i + 2]
            if two in ("..", "==", "~=", "<=", ">=", "::", "->", "//"):
                yield ("p", two, line)
                i += 2
            else:
                yield ("p", c, line)
                i += 1


def check(src: str):
    """Returns a list of problems."""
    problems, stack = [], []  # stack of (opener, line) for blocks and brackets
    prev = None
    pairs = {")": "(", "]": "[", "}": "{"}
    for kind, text, line in tokens(src):
        if kind == "p" and text in "([{":
            stack.append((text, line))
        elif kind == "p" and text in pairs:
            if not stack or stack[-1][0] != pairs[text]:
                problems.append(f"line {line}: unmatched `{text}`")
                stack = [s for s in stack if s[0] in ("function", "if", "do", "repeat")] if not stack else stack
            else:
                stack.pop()
        elif kind == "word":
            if text in ("function", "do", "repeat"):
                stack.append((text, line))
            elif text == "if" and not (prev in EXPR_PREV):
                stack.append(("if", line))
            elif text == "end":
                if not stack or stack[-1][0] not in ("function", "if", "do"):
                    problems.append(f"line {line}: `end` without a block ({stack[-1] if stack else 'empty'})")
                else:
                    stack.pop()
            elif text == "until":
                if not stack or stack[-1][0] != "repeat":
                    problems.append(f"line {line}: `until` without `repeat`")
                else:
                    stack.pop()
        prev = text if kind in ("word", "p") else "<v>"
    for opener, line in stack:
        problems.append(f"line {line}: `{opener}` is never closed")
    return problems


class Checker(unittest.TestCase):
    def test_detects_a_missing_end(self):
        self.assertTrue(check("local function f()\n  if x then\n    y()\nend\n"))

    def test_detects_unbalanced_brackets(self):
        self.assertTrue(check("local t = { 1, 2\nprint(t)\n"))
        self.assertTrue(check("f(1))\n"))

    def test_ignores_strings_and_comments(self):
        self.assertEqual(check('local s = "end ) ]"\n-- function (\n--[[ if { ]]\nlocal t = `x {1 + 1} end`\nlocal u = [[ do ]]\n'), [])

    def test_if_expressions_do_not_open_blocks(self):
        self.assertEqual(check("local a = if x then 1 else 2\nreturn (if y then 3 else 4)\n"), [])

    def test_repeat_until_and_while_do(self):
        self.assertEqual(check("repeat\n  x()\nuntil done\nwhile a do\n  b()\nend\nfor i = 1, 2 do\nend\n"), [])


class Scripts(unittest.TestCase):
    def test_there_are_scripts_to_check(self):
        self.assertGreater(len(FILES), 20)

    def test_every_script_is_structurally_sound(self):
        bad = {Path(f).name: check(Path(f).read_text()) for f in FILES}
        bad = {k: v for k, v in bad.items() if v}
        self.assertEqual(bad, {})

    def test_every_e2e_script_prints_a_pass_line_and_ends(self):
        for f in glob.glob(str(ROOT / "tests/e2e/*.luau")):
            text = Path(f).read_text()
            name = Path(f).stem
            if name.endswith("_sigint"):
                # killed by SIGINT on purpose (never ends by itself): run.sh checks the exit code + the child and prints the PASS line
                self.assertIn(f"E2E PASS {name}", (ROOT / "tests/e2e/run.sh").read_text(), name)
                continue
            self.assertIn(f"E2E PASS {name}", text, name)
            if name.endswith("_idle"):
                continue  # ends by itself on purpose (checks that the program exits without process.exit)
            self.assertTrue("process.exit(0)" in text or ":exit()" in text, f"{name} never ends the process / bot")
            self.assertGreater(text.index("process.exit(0)" if "process.exit(0)" in text else ":exit()"), text.index(f"E2E PASS {name}"), f"{name}: exit comes before the PASS line")

    def test_scripts_use_tabs_or_spaces_consistently_per_file(self):
        for f in FILES:
            lines = [l for l in Path(f).read_text().splitlines() if l[:1] in ("\t", " ")]
            tabs = sum(l.startswith("\t") for l in lines)
            spaces = sum(l.startswith(" ") for l in lines)
            self.assertTrue(tabs == 0 or spaces == 0 or min(tabs, spaces) <= 2, f"{Path(f).name}: mixed indentation ({tabs} tab / {spaces} space lines)")


if __name__ == "__main__":
    unittest.main()
