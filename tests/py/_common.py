"""Shared helpers of the Python test suite (stdlib unittest only; run with `python3 -m unittest discover -s tests/py -v`)."""
import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = ROOT / "tools"
FAKE = ROOT / "harness" / "fake"
FAKE_RDJ = FAKE / "rustdoc"
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS))
os.environ.pop("AZL_RDJ_FORMAT_RANGE", None)


def run(args, **kw):
    """subprocess.run with text output; never raises."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("cwd", ROOT)
    return subprocess.run([str(a) for a in args], **kw)


def read(path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def generate(rustdoc=str(FAKE_RDJ), azalea=str(FAKE), with_extras=True, config=None):
    """Run the generator into a scratch dir once per argument set; returns (rust_dir, luau_dir, CompletedProcess)."""
    out = Path(tempfile.mkdtemp(prefix="azl-test-gen-"))
    rust, luau = out / "rust", out / "luau"
    rust.mkdir()
    luau.mkdir()
    if with_extras:
        for f in (ROOT / "harness/src/luau").glob("extra_*.rs"):
            shutil.copy(f, rust)
    cmd = [sys.executable, TOOLS / "zenpel_gen.py", "--azalea", azalea, "--rustdoc", rustdoc, "--rust-out", rust, "--luau-out", luau]
    if config:
        cmd += ["--config", config]
    return rust, luau, run(cmd)


def d_luau_functions(text: str):
    """[(class or None, name)] of every `function name(` in a .d.luau, `declare extern type X with` blocks as the class."""
    out, cls = [], None
    for line in text.splitlines():
        m = re.match(r"declare extern type (\w+)", line)
        if m:
            cls = m.group(1)
            continue
        if line.strip() == "end":
            cls = None
            continue
        m = re.match(r"\s*function (\w+)\(", line)
        if m:
            out.append((cls, m.group(1)))
    return out


def lua_strings_called(text: str):
    """Names of methods/functions a Luau script calls: `x:name(` and `x.name(`."""
    return set(re.findall(r"[:.]([A-Za-z_][A-Za-z0-9_]*)\s*[({\"']", text))
