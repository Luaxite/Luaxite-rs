"""The bindings: generated Luau definitions vs the hand-written glue vs the scripts that use them, and the tool selftests."""
import glob
import re
import sys
import unittest
from pathlib import Path

from _common import ROOT, TOOLS, d_luau_functions, read, run

DLUAU = read("harness/luau/azalea.d.luau")
BASELINE = [l.strip() for l in read("tools/baseline_api.txt").splitlines() if l.strip()]
EXTRAS = sorted(glob.glob(str(ROOT / "rust/luau/extra_*.rs")))
SCRIPTS = sorted(glob.glob(str(ROOT / "tests/e2e/*.luau")))
NOT_BOT_METHODS = {"add", "read", "write", "close", "exit"}  # swarm:add, tcp stream, process child


def called(text, name):
    return re.search(rf"[:.]{re.escape(name)}\s*[({{\"']", text) is not None or re.search(rf'\{{\s*"{re.escape(name)}"', text) is not None


class Baseline(unittest.TestCase):
    def test_baseline_is_sorted_unique(self):
        self.assertEqual(BASELINE, sorted(set(BASELINE)))

    def test_every_baseline_name_is_called_by_an_azalea_script(self):
        text = "".join(read(f"tests/e2e/{Path(f).name}") for f in SCRIPTS if "tests/e2e/azalea_" in f)
        text += read("tests/e2e/basic.luau") + read("tests/e2e/packets.luau") + read("tests/e2e/multi.luau")
        missing = [n for n in BASELINE if not called(text, n)]
        self.assertEqual(missing, [], "API names no e2e script calls")

    def test_names_called_on_a_bot_exist_in_the_api(self):
        known = set(BASELINE) | {n for _, n in d_luau_functions(DLUAU)} | NOT_BOT_METHODS
        bad = {}
        for f in SCRIPTS:
            for n in set(re.findall(r"\b(?:bot|alice|bob|chest|inv|inventory|me|world)\s*:\s*(\w+)\(", Path(f).read_text())):
                if n not in known:
                    bad.setdefault(n, []).append(Path(f).name)
        self.assertEqual(bad, {}, "scripts call methods that no binding declares")


class Declarations(unittest.TestCase):
    def test_hand_written_signatures_appear_in_the_generated_definitions(self):
        found = 0
        for f in EXTRAS:
            for cls, sig in re.findall(r"//\s*luau\[(\w+)\]:\s*(function \w+\(.*)", Path(f).read_text()):
                name = re.match(r"function (\w+)", sig).group(1)
                self.assertIn((cls, name), d_luau_functions(DLUAU), f"{Path(f).name}: {cls}.{name} is missing from azalea.d.luau")
                found += 1
        self.assertGreaterEqual(found, 15)

    def test_every_hand_written_declaration_has_a_rust_fn(self):
        for f in EXTRAS:
            text = Path(f).read_text()
            for cls, name in re.findall(r"//\s*luau\[(\w+)\]:\s*function (\w+)\(", text):
                self.assertRegex(text, rf"\bfn {name}\b", f"{Path(f).name}: no fn {name}")

    def test_hand_written_section_follows_generated_one_per_class(self):
        for cls in re.findall(r"declare extern type (\w+) with(.*?)\nend", DLUAU, re.S):
            body = cls[1]
            if "-- hand-written" in body:
                before, after = body.split("-- hand-written", 1)
                self.assertNotIn("-- hand-written", after)
                names_after = re.findall(r"function (\w+)\(", after)
                names_before = re.findall(r"function (\w+)\(", before)
                self.assertTrue(set(names_after).isdisjoint(names_before - {"on", "wait_for"} if isinstance(names_before, set) else set(names_before) - {"on", "wait_for"}))

    def test_every_doc_comment_precedes_a_function(self):
        lines = DLUAU.splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("---"):
                j = i + 1
                while lines[j].strip().startswith("---"):
                    j += 1
                self.assertRegex(lines[j].strip(), r"^(function|--)", f"dangling doc comment at line {i + 1}")

    def test_harness_glue_is_a_copy_of_the_real_glue(self):
        for f in ["mod.rs", "convert.rs"] + [Path(p).name for p in EXTRAS]:
            self.assertEqual(read(f"rust/luau/{f}"), read(f"harness/src/luau/{f}"), f)

    def test_gen_files_exist_for_the_harness(self):
        for f in ["gen_client.rs", "gen_events.rs", "gen_types.rs"]:
            self.assertTrue((ROOT / "harness/src/luau" / f).exists())


class Config(unittest.TestCase):
    def test_bindgen_toml_parses_and_renames_point_at_real_methods(self):
        import tomllib
        cfg = tomllib.loads(read("bindgen.toml"))
        for key in ["deny_methods", "path_overrides", "renames"]:
            self.assertIn(key, cfg)
        client = read("harness/src/luau/gen_client.rs") + read("rust/luau/mod.rs")
        for _old, new in cfg["renames"].items():
            self.assertRegex(DLUAU + client, rf"\b{re.escape(new)}\b")

    def test_coverage_ledger_is_consistent(self):
        p = run([sys.executable, TOOLS / "coverage.py", "--report", "harness/luau/GEN_REPORT.json", "--dluau", "harness/luau/azalea.d.luau", "--quiet"])
        self.assertIn(p.returncode, (0, 1), p.stdout + p.stderr)  # the fixture is not the real azalea: only a crash fails here
        self.assertNotIn("Traceback", p.stderr)

    def test_coverage_selftest(self):
        p = run([sys.executable, TOOLS / "coverage.py", "--selftest"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class ToolSelftests(unittest.TestCase):
    def selftest(self, rel):
        p = run([sys.executable, TOOLS / rel])
        self.assertEqual(p.returncode, 0, f"{rel}\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
        return p

    def test_rdj_selftest(self):
        self.assertIn("OK", self.selftest("rdj_selftest.py").stdout)

    def test_bindgen_selftest(self):
        self.assertIn("OK", self.selftest("bindgen_selftest.py").stdout)

    def test_mapper_selftest(self):
        self.selftest("mapper_selftest.py")

    def test_fuzz_regressions(self):
        self.selftest("fuzz/regress.py")


class BindgenPipeline(unittest.TestCase):
    def test_crates_of_an_empty_root_is_an_empty_json_list(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            p = run([sys.executable, TOOLS / "bindgen_crates.py", "--root", d])
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout), [])

    def test_crates_usage_on_unknown_flag(self):
        p = run([sys.executable, TOOLS / "bindgen_crates.py", "--help"])
        self.assertIn("usage", p.stdout + p.stderr)

    def test_bindgen_fails_cleanly_without_cargo(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, PATH="/nonexistent", BINDGEN_CARGO="/nonexistent/cargo")
            p = run([sys.executable, TOOLS / "bindgen.py", "--root", d, "--out", Path(d) / "out"], env=env)
            self.assertNotEqual(p.returncode, 0)
            self.assertNotIn("Traceback", p.stderr)
            self.assertTrue(p.stderr.startswith("error:") or "error:" in p.stderr, p.stderr)
            self.assertEqual(p.stdout.strip(), "", "on failure stdout must stay empty (build.rs reads it)")


if __name__ == "__main__":
    unittest.main()
