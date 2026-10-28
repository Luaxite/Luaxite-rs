"""rust_binds/bind (crate luaxite_bind): the passthrough `#[bind]` attribute and its wiring into the root crate."""
import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

import _common
import bind_scan
from _common import ROOT

CRATE = ROOT / "rust_binds" / "bind"


class Wiring(unittest.TestCase):
    def test_manifest_is_a_proc_macro_without_dependencies(self):
        m = tomllib.loads((CRATE / "Cargo.toml").read_text())
        self.assertEqual(m["package"]["name"], "luaxite_bind")
        self.assertEqual(m["package"]["edition"], "2024")
        self.assertIs(m["lib"]["proc-macro"], True)
        self.assertFalse(any(k in m for k in ("dependencies", "build-dependencies")))

    def test_lib_exports_a_passthrough_attribute(self):
        src = (CRATE / "src" / "lib.rs").read_text()
        self.assertIn("#[proc_macro_attribute]\npub fn bind(", src)
        self.assertRegex(src, r"\{\s*item\s*\}")  # returns the item untouched

    def test_root_depends_on_it_by_path(self):
        root = tomllib.loads((ROOT / "Cargo.toml").read_text())
        self.assertEqual(root["dependencies"]["luaxite_bind"], {"path": "rust_binds/bind"})
        self.assertNotIn("rust_binds/bind", root["workspace"].get("exclude", []))

    def test_main_imports_the_attribute(self):
        self.assertIn("use luaxite_bind::bind;", _common.read("rust/main.rs"))

    def test_harness_is_untouched(self):
        self.assertNotIn("luaxite_bind", _common.read("harness/Cargo.toml"))

    def test_scanner_does_not_select_the_crate_itself(self):
        self.assertEqual([r for r in bind_scan.scan_root(ROOT) if r[0].startswith("rust_binds/bind/")], [])


@unittest.skipUnless(shutil.which("cargo"), "no cargo")
class Compiles(unittest.TestCase):
    def test_attribute_leaves_items_alone(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "src").mkdir()
            (d / "Cargo.toml").write_text(
                f'[package]\nname = "t"\nversion = "0.1.0"\nedition = "2024"\n[workspace]\n'
                f'[dependencies]\nluaxite_bind = {{ path = "{CRATE.as_posix()}" }}\n'
            )
            (d / "src" / "main.rs").write_text(
                "#[allow(unused_imports)]\nuse luaxite_bind::bind;\n"
                "#[bind]\npub fn add(a: i32, b: i32) -> i32 { a + b }\n"
                "#[luaxite_bind::bind]\nfn twice(x: i32) -> i32 { x * 2 }\n"
                '#[bind(name = "x")]\nfn three() -> i32 { 3 }\n'
                "fn main() { println!(\"{}\", add(1, 2) + twice(3) + three()); }\n"
            )
            env = {**os.environ, "RUSTUP_TOOLCHAIN": os.environ.get("RUSTUP_TOOLCHAIN", "stable"), "CARGO_TARGET_DIR": str(d / "t")}
            probe = _common.run(["cargo", "--version"], env=env)
            if probe.returncode:
                self.skipTest("cargo toolchain unavailable offline")
            p = _common.run(["cargo", "run", "-q", "--offline", "--manifest-path", d / "Cargo.toml"], env=env)
            self.assertEqual((p.returncode, p.stdout.strip()), (0, "12"), p.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
