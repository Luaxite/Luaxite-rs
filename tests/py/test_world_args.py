"""World coordinate arguments (rust/luau/real_world.rs): `height` / `is_chunk_loaded` take numbers and floor them (a fractional
`bot:position().x` is fine, NaN / out of i32 range is a clear error); `find_block` distances use i64 so far-apart positions can't overflow i32."""
import re
import unittest

from _common import read


class WorldArgs(unittest.TestCase):
    def setUp(self):
        self.src = read("rust/luau/real_world.rs")

    def test_height_and_chunk_take_floored_numbers(self):
        self.assertRegex(self.src, r"fn is_chunk_loaded\(&self, chunk_x: f64, chunk_z: f64\)")
        self.assertRegex(self.src, r"fn height\(&self, x: f64, z: f64\)")
        self.assertEqual(len(re.findall(r"floor_coord\(", self.src)), 5)      # definition + 4 uses
        m = re.search(r"fn floor_coord\(.*?\n\}\n", self.src, re.S)
        self.assertTrue(m)
        for needle in ("n.floor()", "is_nan()", "i32::MIN", "i32::MAX"):
            self.assertIn(needle, m.group(0))

    def test_find_block_distance_has_no_i32_subtraction(self):
        self.assertNotRegex(self.src, r"\(pos\.[xyz] - center\.[xyz]\)")
        self.assertEqual(len(re.findall(r"pos\.[xyz] as i64 - center\.[xyz] as i64", self.src)), 3)


if __name__ == "__main__":
    unittest.main()
