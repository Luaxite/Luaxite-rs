"""s10: Runtime::lua + luau::current_lua (static checks on mod.rs, harness copy in sync)."""
import re
import unittest

from _common import ROOT


def read(rel):
    return (ROOT / rel).read_text()


class LuaHandle(unittest.TestCase):
    def setUp(self):
        self.mod = read("rust_binds/luau/mod.rs")

    def test_runtime_lua_accessor(self):
        self.assertRegex(self.mod, r"pub fn lua\(&self\) -> &Lua \{\s*&self\.lua\s*\}")

    def test_current_lua_exists(self):
        self.assertRegex(self.mod, r"pub fn current_lua\(\) -> Lua")

    def test_with_source_sets_current(self):
        body = self.mod.split("fn with_source", 1)[1].split("pub fn waiting", 1)[0]
        self.assertRegex(body, r"CURRENT\.lock\(\).*=\s*Some\(lua\.clone\(\)\)")
        self.assertLess(body.index("binds::register"), body.index("CURRENT"))

    def test_panic_message(self):
        self.assertIn("current_lua called before a Runtime exists", self.mod)

    def test_task_local_scoped_in_run_standalone(self):
        self.assertIn("tokio::task_local!", self.mod)
        self.assertRegex(self.mod, r"TASK_LUA\.scope\(self\.lua\.clone\(\)")

    def test_harness_copy_identical(self):
        self.assertEqual(self.mod, read("harness/src/luau/mod.rs"))


if __name__ == "__main__":
    unittest.main()
