"""The generated binds (OUT_DIR/binds.rs) are included by rust_binds/luau/generated.rs and registered by Runtime::with_source."""
import re
import unittest

import _common
from _common import read

HOST_GEN = read("rust_binds/luau/generated.rs")
HARNESS_GEN = read("harness/src/luau/generated.rs")
MOD = read("rust_binds/luau/mod.rs")


class Wiring(unittest.TestCase):
    def test_host_includes_binds_from_out_dir_inside_a_child_module(self):
        self.assertRegex(HOST_GEN, r'mod binds \{\s*include!\(concat!\(env!\("OUT_DIR"\), "/binds.rs"\)\);\s*\}')

    def test_harness_has_an_empty_register_with_the_same_signature(self):
        m = re.search(r"mod binds \{(.*?)\n\}\n", HARNESS_GEN, re.S)
        self.assertIsNotNone(m)
        self.assertIn("pub fn register(lua: &mlua::Lua) -> mlua::Result<()>", m.group(1))
        self.assertIn("let _ = lua;", m.group(1))
        self.assertNotIn("globals", m.group(1))

    def test_register_is_called_once_after_install_require(self):
        self.assertEqual(MOD.count("binds::register(&lua)"), 1)
        self.assertLess(MOD.index("install_require(&lua)"), MOD.index("binds::register(&lua)"))
        self.assertLess(MOD.index("binds::register(&lua)"), MOD.index("handlers: Arc::new(Handlers::default())"))
        self.assertIn('.context("registering #[bind] functions")?', MOD)

    def test_harness_mod_is_the_host_mod(self):
        self.assertEqual(MOD, read("harness/src/luau/mod.rs"))

    def test_mod_declarations_do_not_name_binds(self):
        # `binds` lives in generated.rs (included by mod.rs); a `mod binds;` line would look for a file
        self.assertNotRegex(MOD, r"(?m)^\s*(pub\s+)?mod binds\s*;")


if __name__ == "__main__":
    unittest.main()
