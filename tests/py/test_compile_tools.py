"""tools/api_surface.py and tools/cargo_warnings.py (the helpers of .github/workflows/rust.yml) on small synthetic inputs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from _common import ROOT, TOOLS, run

DLUAU = """declare extern type Bot with
    function chat(self, message: string): ()
    function goto(self, pos: BlockPos): ()
end
declare class GoalLib
    xz: (x: number, z: number) -> Goal
    y: (y: number) -> Goal
end
"""


def msg(level, text, pkg="path+file:///w/zenpel#0.1.0", target="zenpel"):
    return json.dumps({"reason": "compiler-message", "package_id": pkg, "target": {"name": target}, "message": {"level": level, "message": text}})


class ApiSurface(unittest.TestCase):
    def go(self, dluau, baseline):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "b.d.luau").write_text(dluau)
            (Path(d) / "base.txt").write_text(baseline)
            return run([sys.executable, TOOLS / "api_surface.py", "--bindings", Path(d) / "b.d.luau", "--baseline", Path(d) / "base.txt"])

    def test_all_names_present(self):
        p = self.go(DLUAU, "chat\ngoto\nxz\ny\n")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("0 missing", p.stdout)

    def test_a_vanished_name_fails_and_is_named(self):
        p = self.go(DLUAU, "chat\nmine\nxz\n")
        self.assertEqual(p.returncode, 1)
        self.assertIn("mine", p.stdout)
        self.assertNotIn("chat ", p.stdout.split("vanished")[-1])

    def test_missing_file_is_exit_2(self):
        p = run([sys.executable, TOOLS / "api_surface.py", "--bindings", "/nonexistent/b.d.luau"])
        self.assertEqual(p.returncode, 2)

    def test_real_baseline_is_sorted_and_names_are_plain(self):
        names = (ROOT / "tools/baseline_api.txt").read_text().split()
        self.assertTrue(all(n.replace("_", "").isalnum() for n in names))


class CargoWarnings(unittest.TestCase):
    def go(self, lines, *args):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "build.json"
            log.write_text("\n".join(lines) + "\n")
            return run([sys.executable, TOOLS / "cargo_warnings.py", log, *args])

    def test_clean_build(self):
        p = self.go([msg("note", "x"), '{"reason":"build-finished","success":true}'])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("0 warning(s), 0 error(s)", p.stdout)

    def test_warning_passes_unless_strict(self):
        lines = [msg("warning", "unused variable: `x`"), msg("warning", "1 warning emitted")]
        p = self.go(lines)
        self.assertEqual(p.returncode, 0)
        self.assertIn("1 warning(s)", p.stdout)
        self.assertEqual(self.go(lines, "--strict").returncode, 1)

    def test_error_in_the_judged_package_fails(self):
        p = self.go([msg("error", "cannot find type `Foo` in this scope", target="build-script-build")])
        self.assertEqual(p.returncode, 1)
        self.assertIn("1 error(s)", p.stdout)

    def test_other_packages_are_counted_not_judged(self):
        azalea = "path+file:///w/bind/azalea-src/azalea#azalea@0.15.0"
        p = self.go([msg("warning", "unused import", pkg=azalea, target="azalea"), msg("warning", "unused", pkg="registry+https://x#serde@1.0.0", target="serde")], "--strict")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("other packages (not judged): 2 warning(s)", p.stdout)

    def test_old_package_id_form(self):
        p = self.go([msg("warning", "w", pkg="zenpel 0.1.0 (path+file:///w)")])
        self.assertIn("1 warning(s)", p.stdout)

    def test_missing_log_and_empty_log_are_exit_2(self):
        self.assertEqual(run([sys.executable, TOOLS / "cargo_warnings.py", "/nonexistent/build.json"]).returncode, 2)
        self.assertEqual(self.go(["not json", ""]).returncode, 2)

    def test_render_diagnostics_log_has_no_messages_and_says_why(self):
        p = self.go(['{"reason":"compiler-artifact","package_id":"path+file:///w/zenpel#0.1.0","fresh":false}', '{"reason":"build-finished","success":true}'])
        self.assertEqual(p.returncode, 2)
        self.assertIn("json-render-diagnostics", p.stderr)

    def test_errors_are_printed_rendered(self):
        line = json.dumps({"reason": "compiler-message", "package_id": "path+file:///w/zenpel#0.1.0", "target": {"name": "zenpel"},
                           "message": {"level": "error", "message": "the trait bound `Option<()>: IntoLua` is not satisfied",
                                       "rendered": "error[E0277]: the trait bound `Option<()>: IntoLua` is not satisfied\n --> gen_types.rs:1:1\n"}})
        p = self.go([line])
        self.assertEqual(p.returncode, 1)
        self.assertIn("error in zenpel:", p.stdout)
        self.assertIn("--> gen_types.rs:1:1", p.stdout)


if __name__ == "__main__":
    unittest.main()
