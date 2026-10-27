"""Hand-written boolean params are strict (mlua's own `bool` takes any value: `0` is true): `LBool` in convert.rs rejects non-booleans and the
Container `throw` / `drop_cursor` params use it."""
import re
import unittest

from _common import read


class StrictBool(unittest.TestCase):
    def test_lbool_rejects_non_boolean(self):
        src = read("rust/luau/convert.rs")
        m = re.search(r"impl FromLua for LBool \{.*?\n\}\n", src, re.S)
        self.assertTrue(m, "LBool must implement FromLua")
        self.assertIn("Value::Boolean(b) => Ok(Self(b))", m.group(0))
        self.assertIn("Err(", m.group(0))
        self.assertNotIn("Value::Nil", m.group(0))

    def test_container_methods_use_it(self):
        src = read("rust/luau/extra_container.rs")
        self.assertRegex(src, r"fn throw\(&self, slot: usize, whole_stack: Option<LBool>\)")
        self.assertRegex(src, r"fn drop_cursor\(&self, whole_stack: Option<LBool>\)")
        self.assertNotIn("Option<bool>", src)

    def test_pathfinder_opts_use_it(self):
        src = read("rust/luau/convert.rs")
        self.assertNotIn("Option<bool>", src)
        for key, setter in (("allow_mining", "allow_mining"), ("retry_on_no_path", "retry_on_no_path")):
            self.assertIn(f't.get::<Option<LBool>>("{key}")?', src)
            self.assertIn(f"opts.{setter}(b.0)", src)

    def test_generator_params_are_strict(self):
        src = read("tools/luaxite_gen.py")
        self.assertIn('return TypeInfo("LBool", "boolean", from_lua=lambda x: f"{x}.0")', src)


if __name__ == "__main__":
    unittest.main()
