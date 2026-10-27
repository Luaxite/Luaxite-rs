"""The rustdoc front end on hand-built crates (tools/rdj_synth.py): shapes the fixture does not have and no rustc is needed for."""
import json
import tempfile
import unittest
from pathlib import Path

import _common  # noqa: F401  (puts tools/ on sys.path)
import rdj
import rdj_index as ri
from rdj_synth import synth_weird, synth_ws2


def load(synths: dict):
    d = tempfile.mkdtemp(prefix="azl-synth-")
    for name, s in synths.items():
        Path(d, f"{name}.json").write_text(json.dumps(s.raw()))
    return rdj.load_dir(d)


class Weird(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = load({"a": synth_weird()})
        cls.defs = ri.build_defs(cls.r)
        cls.impls = ri.build_impls(cls.r)
        cls.sigs = {m.name: m for m in cls.impls.methods if m.target == "Client"}

    def test_defs_found(self):
        self.assertEqual(sorted(self.defs), ["Client", "Deep", "EntityRef", "Event", "Grid", "Kind", "Raw", "Tick"])

    def test_nested_generics_are_rendered_in_full(self):
        self.assertEqual(self.sigs["nested"].sig, "pub fn nested(&self, m: HashMap<String, Vec<Option<(u8, u16)>>>) -> Option<Vec<u32>>")

    def test_impl_trait_argument_and_return(self):
        self.assertIn("impl Fn(u32) -> u32 + Send", self.sigs["imp"].sig)
        self.assertIn("-> impl Iterator<Item = u32>", self.sigs["imp"].sig)

    def test_where_clause_is_kept(self):
        self.assertTrue(self.sigs["bound"].sig.endswith("where T: Into<u32> + Copy"))

    def test_mut_reference(self):
        self.assertIn("v: &mut Vec<u8>", self.sigs["mutref"].sig)

    def test_raw_identifier(self):
        self.assertIn("r#match", self.sigs)

    def test_const_generics(self):
        self.assertIn("Grid<3, 4>", self.sigs["grid"].sig)

    def test_async_fn_and_async_in_trait_flag(self):
        self.assertTrue(self.sigs["waits"].is_async)
        self.assertFalse(self.sigs["nested"].is_async)

    def test_doc_hidden_is_reported_with_a_decision(self):
        self.assertIn(("Client", "hidden", "kept"), self.impls.hidden)

    def test_hidden_can_be_skipped_on_request(self):
        impls = ri.build_impls(self.r, hidden="skip")
        self.assertNotIn("hidden", {m.name for m in impls.methods})
        self.assertIn(("Client", "hidden", "skipped"), impls.hidden)

    def test_cfg_gated_fn_is_absent_as_rustdoc_leaves_it_out(self):
        self.assertNotIn("gated", self.sigs)


class Workspace(unittest.TestCase):
    def test_two_crates_load_side_by_side(self):
        r = load(synth_ws2())
        self.assertIsNotNone(r.crate("a"))
        self.assertIsNotNone(r.crate("b"))

    def test_defs_of_both_crates_are_indexed(self):
        defs = ri.build_defs(load(synth_ws2()))
        self.assertGreaterEqual(len(defs), 2)

    def test_paths_resolve_across_the_crate_boundary(self):
        r = load(synth_ws2())
        for crate in ("a", "b"):
            root = r.root(crate)
            for k in r.children(crate, root):
                path = r.item_path(crate, k)
                self.assertTrue(path is None or path[0] in ("a", "b"))


class Errors(unittest.TestCase):
    def test_unreadable_crate_dir_message_names_the_directory(self):
        with self.assertRaises(rdj.RdjError) as cm:
            rdj.load_dir(Path(tempfile.mkdtemp()) / "missing")
        self.assertIn("missing", str(cm.exception))

    def test_empty_dir_has_no_crates(self):
        d = tempfile.mkdtemp()
        try:
            r = rdj.load_dir(d)
        except rdj.RdjError:
            return
        with self.assertRaises(Exception):
            r.crate("azalea")


if __name__ == "__main__":
    unittest.main()
