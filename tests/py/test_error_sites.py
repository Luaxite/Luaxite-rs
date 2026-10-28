"""Handler / task errors must set the process error flag (exit 1), not only print: every `[luau]` error print of a `bot:on` handler,
an `init`/`update` handler, an event task or a task.spawn thread is preceded by `note_error()` (rust_binds/luau/mod.rs)."""
import re
import unittest

from _common import read

SITES = {
    "rust_binds/luau/mod.rs": ["error in `init` handler", "error in `{event}` handler"],
    "rust_binds/luau/real_events.rs": ["error in `update` handler"],
    "rust_binds/luau/lune_task.rs": ["task error"],
}


class ErrorSites(unittest.TestCase):
    def test_prints_note_error(self):
        for path, needles in SITES.items():
            lines = read(path).splitlines()
            for needle in needles:
                idx = [i for i, ln in enumerate(lines) if "eprintln!" in ln and needle in ln]
                self.assertTrue(idx, f"{path}: no print for {needle!r}")
                for i in idx:
                    self.assertIn("note_error()", lines[i - 1], f"{path}:{i + 1}: {needle!r} print not preceded by note_error()")

    def test_lifecycle_event_tasks(self):
        src = read("rust_binds/luau/real_lifecycle.rs")
        self.assertEqual(len(re.findall(r"note_error\(\);\n\s+eprintln!\(\"\[luau\] \{e\}\"\);", src)), 2)

    def test_run_standalone_checks_flag(self):
        src = read("rust_binds/luau/mod.rs")
        self.assertRegex(src, r"None if had_error\(\) => Err\(")


if __name__ == "__main__":
    unittest.main()
