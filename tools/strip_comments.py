import io
import re
import sys
import tokenize
from pathlib import Path

KEEP = re.compile(r"//\s*luau\[")
SKIP = (
    "harness/fake/",
    "tools/testdata/",
    "harness/luau/",
    "harness/src/luau/gen_",
    "harness/src/luau/generated.rs",
)
LITERAL = re.compile(
    r'b?r(#*)".*?"\1'
    r'|"(?:\\.|[^"\\])*"'
    r"|'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^\\'\n])'",
    re.S,
)


def strip_rust(src):
    out = []
    i = 0
    n = len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "//" and KEEP.match(src, i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.extend(src[i:j])
            i = j
        elif two in ("//", "/*"):
            if two == "//":
                while i < n and src[i] != "\n":
                    i += 1
            else:
                depth = 0
                while True:
                    pair = src[i:i + 2]
                    depth += (pair == "/*") - (pair == "*/")
                    i += 2 if pair in ("/*", "*/") else 1
                    if depth == 0 or i >= n:
                        break
            if i >= n or src[i] == "\n":
                while out and out[-1] in " \t":
                    out.pop()
                if not out or out[-1] == "\n":
                    i += 1
            elif out and not out[-1].isspace() and not src[i].isspace():
                out.append(" ")
        elif m := LITERAL.match(src, i):
            out.extend(m.group())
            i = m.end()
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def strip_python(src):
    lines = src.splitlines(keepends=True)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        row, col = tok.start
        if tok.type == tokenize.COMMENT and not (row == 1 and tok.string.startswith("#!")):
            head = lines[row - 1][:col].rstrip()
            lines[row - 1] = head + "\n" if head else ""
    return "".join(lines)


STRIPPERS = {".rs": strip_rust, ".py": strip_python}

for arg in sys.argv[1:]:
    p = Path(arg)
    for path in [p] if p.is_file() else sorted(p.rglob("*")):
        posix = path.as_posix()
        if path.suffix in STRIPPERS and "target" not in path.parts and not any(s in posix for s in SKIP):
            path.write_text(STRIPPERS[path.suffix](path.read_text()))
