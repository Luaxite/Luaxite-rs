"""s8/s11: goto_reach defaults to 4.5 again (reach_goal keeps azalea's default); every entity query excludes the bot; Runtime::handle is gone."""
import re
import unittest

from _common import read


class ReachEntities(unittest.TestCase):
    def test_goto_reach_defaults_to_4_5(self):
        src = read("rust_binds/luau/extra_misc.rs")
        self.assertIn("const DEFAULT_REACH: f64 = 4.5;", src)
        self.assertIn("distance.unwrap_or(DEFAULT_REACH)", src)
        self.assertIn("ReachBlockPosGoal::new_with_distance(", src)
        self.assertNotIn("ReachBlockPosGoal::new(pos.0, chunks)", src)
        self.assertIn("(default 4.5)", src)
        self.assertNotIn("default azalea's reach", src)
        self.assertIn("ReachBlockPosGoal::new(pos.0, chunks)", read("rust_binds/luau/real_goal.rs"))

    def test_entity_queries_exclude_the_bot(self):
        search = read("rust_binds/luau/real_search.rs")
        self.assertIn("self.others(found)", search)
        self.assertRegex(search, r"filter\(\|e\| e\.id\(\) != me\)")
        self.assertNotIn("itself included", search)
        self.assertRegex(read("rust_binds/luau/extra_query.rs"), r"pub\(super\) fn others\(")

    def test_entity_query_change_is_marked_breaking(self):
        search = read("rust_binds/luau/real_search.rs")
        docs = [l for l in search.splitlines() if l.lstrip().startswith("// luau[Bot]: ---")]
        self.assertEqual(len(docs), 4)
        for doc in docs:
            self.assertIn("BREAKING: older versions included the bot itself", doc)

    def test_runtime_handle_removed(self):
        for path in ("rust_binds/luau/mod.rs", "harness/src/luau/mod.rs"):
            src = read(path)
            self.assertNotRegex(src, r"fn handle\(")
            self.assertNotIn("azalea::prelude::{Client, Event}", src)


    def test_harness_main_calls_a_handle_the_harness_defines(self):
        """harness/src/main.rs drives test.luau with `rt.handle(..)`; the real host has none (run_standalone), so the harness defines it in
        its own generated.rs (not part of the mod.rs/convert.rs mirror). CI's harness build failed with E0599 when only the call was left."""
        main = read("harness/src/main.rs")
        self.assertRegex(main, r"rt\.handle\(")
        harness_gen = read("harness/src/luau/generated.rs")
        self.assertRegex(harness_gen, r"impl Runtime \{\s*pub async fn handle\(")
        self.assertIn("gen_events::dispatch(", harness_gen)
        self.assertIn("close_waiters()", harness_gen)
        self.assertNotRegex(read("rust_binds/luau/generated.rs"), r"fn handle\(")

if __name__ == "__main__":
    unittest.main()
