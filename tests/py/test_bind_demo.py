"""s11: the sample //BIND file, its Luau demo, the e2e script wiring (static; the real-mlua run is tools/bind_e2e.sh, skipped without cargo)."""
import re
import subprocess
import sys
import unittest

from _common import ROOT

DEMO = ROOT / "rust_binds/luau/demo_binds.rs"
FNS = ["demo_add", "demo_greet", "demo_div", "demo_set_global"]


def tool(name, *args):
    return subprocess.run([sys.executable, str(ROOT / "tools" / name), "--root", str(ROOT), *args], capture_output=True, text=True)


class Demo(unittest.TestCase):
    def test_header_is_line_one(self):
        self.assertEqual(DEMO.read_text().splitlines()[0], "//BIND pub")

    def test_scanner_finds_all_fns_in_pub_mode(self):
        r = tool("bind_scan.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = [l.split()[1:] for l in r.stdout.splitlines() if "demo_binds.rs" in l]
        self.assertEqual(got, [[f, "pub"] for f in FNS])

    def test_generator_binds_each_without_warnings(self):
        r = tool("bind_gen.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        for f in FNS:
            self.assertIn(f'globals.set("{f}", ', r.stdout)
            self.assertIn(f"crate::luau::demo_binds::{f}(", r.stdout)
        self.assertRegex(r.stdout, r"\|lua, \(a0, a1\): \(String, f64\)\| crate::luau::demo_binds::demo_set_global\(lua, a0, a1\)")

    def test_mod_declared_and_harness_copy_identical(self):
        mod = (ROOT / "rust_binds/luau/mod.rs").read_text()
        self.assertRegex(mod, r"#\[allow\(dead_code\)\]\nmod demo_binds;")
        self.assertEqual(DEMO.read_text(), (ROOT / "harness/src/luau/demo_binds.rs").read_text())
        self.assertIn("demo_binds", (ROOT / "tools/sync_harness.sh").read_text())
        self.assertIn("demo_binds.rs", (ROOT / "tools/check.sh").read_text())

    def test_luau_scripts_use_every_global(self):
        for rel in ("src/bind_demo.luau", "tests/e2e/bind_demo.luau"):
            text = (ROOT / rel).read_text()
            for f in FNS:
                self.assertRegex(text, rf"\b{f}\b", f"{rel} lacks {f}")
        self.assertIn("E2E PASS bind_demo", (ROOT / "tests/e2e/bind_demo.luau").read_text())
        self.assertIn("run bind_demo", (ROOT / "tests/e2e/run.sh").read_text())


class Defs(unittest.TestCase):
    def test_definitions_cover_every_global_and_ci_loads_them(self):
        d = (ROOT / "rust_binds/luau/demo_binds.d.luau").read_text()
        for f in FNS:
            self.assertRegex(d, rf"declare function {f}\(")
        self.assertIn("--defs=rust_binds/luau/demo_binds.d.luau", (ROOT / ".github/workflows/generator.yml").read_text())


class E2eScript(unittest.TestCase):
    def test_hooked_into_check(self):
        self.assertIn("sh tools/bind_e2e.sh", (ROOT / "tools/check.sh").read_text())

    def test_binds_module_regex_matches_the_harness_generated_rs(self):
        s = (ROOT / "harness/src/luau/generated.rs").read_text()
        self.assertIsNotNone(re.search(r"mod binds \{.*?\n\}\n", s, flags=re.S))
        self.assertIn("mod binds {", s)

    def test_skips_cleanly_without_cargo(self):
        r = subprocess.run(["sh", str(ROOT / "tools/bind_e2e.sh")], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SKIPPED", r.stdout)


if __name__ == "__main__":
    unittest.main()
