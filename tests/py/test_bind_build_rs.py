"""build.rs writes OUT_DIR/binds.rs with tools/bind_gen.py; an empty register() is the fallback and never fails the build."""
import ast
import contextlib
import io
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import _common
import bind_gen
from _common import ROOT

SRC = _common.read("build.rs")
RUSTC = shutil.which("rustc")
ENV = {**os.environ, "RUSTUP_TOOLCHAIN": os.environ.get("RUSTUP_TOOLCHAIN", "stable")}


def empty_binds():
    m = re.search(r'const EMPTY_BINDS: &str = ("(?:[^"\\]|\\.)*");', SRC)
    return ast.literal_eval(m.group(1))


class Static(unittest.TestCase):
    def test_empty_text_is_what_the_generator_writes_for_no_binds(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(empty_binds(), bind_gen.generate(d))

    def test_build_rs_runs_bind_gen_after_bindgen(self):
        self.assertIn('"tools/bind_gen.py"', SRC)
        self.assertIn('join("binds.rs")', SRC)
        self.assertLess(SRC.index('"tools/bindgen.py"'), SRC.index("write_binds(&root, &out_dir);"))
        self.assertIn("cargo:warning=", SRC)

    def test_rerun_lines_cover_the_inputs(self):
        # tools/bindgen.py (printed through build.rs) lists rust/, rust_binds/ and tools/*.py; once any rerun line exists cargo watches nothing else
        self.assertIn('root / "rust", root / "rust_binds"', _common.read("tools/bindgen.py"))
        self.assertIn('"tools" / "*.py"', _common.read("tools/bindgen.py"))


@unittest.skipUnless(RUSTC, "no rustc")
class Run(unittest.TestCase):
    """Compile build.rs for real (it only needs std) and run it on a scratch tree whose tools/bindgen.py is a stub."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="azl-test-buildrs-"))
        cls.exe = cls.tmp / "build_rs"
        p = _common.run(["rustc", "--edition", "2024", "-o", cls.exe, ROOT / "build.rs"], env=ENV)
        if p.returncode:
            raise unittest.SkipTest("rustc unavailable: " + p.stderr[-300:])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tree(self, name, gen_py=None):
        root = self.tmp / name
        (root / "tools").mkdir(parents=True)
        (root / "src").mkdir()
        (root / "rust").mkdir()
        (root / "src" / "main.luau").write_text("print('hi')\n")
        (root / "tools" / "bindgen.py").write_text("print('cargo:rerun-if-changed=stub')\n")
        for f in ("bind_scan.py", "bind_gen.py"):
            shutil.copy(ROOT / "tools" / f, root / "tools" / f)
        if gen_py is not None:
            (root / "tools" / "bind_gen.py").write_text(gen_py)
        (root / "rust" / "main.rs").write_text("#[bind]\nfn f(a: i32) -> i32 { a }\n#[bind]\nfn bad(v: Vec<u8>) {}\n")
        return root

    def build(self, root):
        out = root / "out"
        out.mkdir()
        p = _common.run([self.exe], env={**ENV, "CARGO_MANIFEST_DIR": str(root), "OUT_DIR": str(out)}, cwd=root)
        return p, out / "binds.rs"

    def test_binds_are_generated_and_warnings_forwarded(self):
        root = self.tree("ok")
        p, binds = self.build(root)
        self.assertEqual(p.returncode, 0, p.stderr[-500:])
        self.assertIn("crate::f(a0)", binds.read_text())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(binds.read_text(), bind_gen.generate(root))
        self.assertIn("cargo:warning=unsupported rust/main.rs:4 bad Vec<u8>", p.stdout)
        self.assertTrue((root / "out" / "scripts.rs").is_file())

    def test_failing_generator_falls_back_to_empty_register(self):
        root = self.tree("fail", gen_py="import sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n")
        out = root / "out"
        out.mkdir()
        (out / "binds.rs").write_text("stale junk that is not rust")
        p = _common.run([self.exe], env={**ENV, "CARGO_MANIFEST_DIR": str(root), "OUT_DIR": str(out)}, cwd=root)
        self.assertEqual(p.returncode, 0, p.stderr[-500:])
        self.assertEqual((out / "binds.rs").read_text(), empty_binds())
        self.assertIn("cargo:warning=boom", p.stdout)
        self.assertIn("cargo:warning=tools/bind_gen.py failed", p.stdout)

    def test_no_rust_dir_is_an_empty_register(self):
        root = self.tree("none")
        shutil.rmtree(root / "rust")
        p, binds = self.build(root)
        self.assertEqual((p.returncode, binds.read_text()), (0, empty_binds()))


if __name__ == "__main__":
    unittest.main()
