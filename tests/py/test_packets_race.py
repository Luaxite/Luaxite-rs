"""raw_connection_mut (rust_binds/luau/real_packets.rs) yields in the callback, so it must not write the whole snapshot back over the live
connection: only a changed `state` is set, and a changed `injected` list is merged into the current one (merge_injected)."""
import re
import unittest

from _common import read


class PacketsRace(unittest.TestCase):
    def setUp(self):
        src = read("rust_binds/luau/real_packets.rs")
        self.body = src[src.index("async fn raw_connection_mut"):]

    def test_no_wholesale_write_back(self):
        self.assertNotRegex(self.body, r"injected_clientbound_packets\s*=\s*injected\s*;")
        self.assertNotRegex(self.body, r"c\.state\s*=\s*state\s*;\s*\n\s*c\.injected")

    def test_only_changes_are_applied(self):
        self.assertIn("if new_state == old_state", self.body)
        self.assertIn("if new_injected != old_injected", self.body)
        self.assertRegex(self.body, r"merge_injected\(&old_injected, new_injected, live\)")
        self.assertRegex(self.body, r"if let Some\(state\) = state\s*\{\s*c\.state = state;")

    def test_merge_has_rust_unit_tests(self):
        src = read("rust_binds/luau/real_packets.rs")
        self.assertIn("fn merge_injected(", src)
        self.assertGreaterEqual(len(re.findall(r"assert_eq!\(\s*merge_injected\(", src)), 4)


if __name__ == "__main__":
    unittest.main()
