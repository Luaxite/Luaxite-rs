"""tools/rdj.py: the rustdoc-JSON loader, against the committed fixture and hand-made JSON."""
import json
import tempfile
import unittest
from pathlib import Path

from _common import FAKE, FAKE_RDJ, ROOT, run
import rdj
from rdj_synth import synth_ws2, synth_weird


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = rdj.load_dir(FAKE_RDJ)
        cls.c = cls.r.crate("azalea")

    def test_format_version_is_accepted(self):
        lo, hi = rdj.accepted_range()
        self.assertEqual((lo, hi), (57, 61))
        self.assertTrue(lo <= self.c.format_version <= hi)
        self.assertEqual(rdj.peek_format_version(FAKE_RDJ / "azalea.json"), self.c.format_version)

    def test_root_is_a_module_with_children(self):
        root = self.r.root("azalea")
        self.assertEqual(rdj.inner_kind(self.c.item(root)), "module")
        kids = self.r.children("azalea", root)
        self.assertGreater(len(kids), 5)
        names = {self.c.item(k)["name"] for k in kids}
        self.assertIn("ecs", names)

    def test_every_item_has_a_known_kind_and_visibility(self):
        kinds = set()
        for it in self.c.index.values():
            kinds.add(rdj.inner_kind(it))
            self.assertIn(rdj.visibility(it), {"public", "default", "crate", "restricted"})
            rdj.payload(it)
            rdj.attr_texts(it)
        self.assertTrue({"module", "struct", "enum", "function", "impl", "trait"} <= kinds)

    def test_item_paths_resolve_for_public_modules(self):
        root = self.r.root("azalea")
        for k in self.r.children("azalea", root):
            it = self.c.item(k)
            if rdj.inner_kind(it) == "module":
                path = self.r.item_path("azalea", k)
                self.assertEqual(path[0], "azalea")
                self.assertEqual(path[-1], it["name"])

    def test_render_and_convert_every_function_signature(self):
        n = 0
        for it in self.c.index.values():
            if rdj.inner_kind(it) != "function":
                continue
            sig = rdj.payload(it).get("sig") or {}
            for _name, ty in sig.get("inputs", []):
                self.assertIsInstance(rdj.render_type(ty), str)
                rdj.convert_type(ty)
                n += 1
            if sig.get("output"):
                self.assertTrue(rdj.render_type(sig["output"]))
        self.assertGreater(n, 100)

    def test_primitive_conversions(self):
        self.assertEqual(rdj.render_type({"primitive": "u32"}), "u32")
        self.assertEqual(rdj.convert_type({"primitive": "u32"}), ("prim", "u32"))
        self.assertEqual(rdj.render_type({"borrowed_ref": {"lifetime": None, "is_mutable": True, "type": {"primitive": "str"}}}), "&mut str")

    def test_doc_summary_is_first_paragraph(self):
        self.assertEqual(rdj.doc_summary("Hello world.\n\nMore text"), "Hello world.")
        self.assertEqual(rdj.doc_summary(None), "")
        self.assertEqual(rdj.doc_summary(""), "")

    def test_source_sha1_is_stable_and_tracks_content(self):
        a = rdj.source_sha1(FAKE / "azalea")
        self.assertEqual(a, rdj.source_sha1(FAKE / "azalea"))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src/lib.rs").write_text("pub fn a() {}\n")
            (Path(d) / "Cargo.toml").write_text("[package]\nname='x'\n")
            h1 = rdj.source_sha1(d)
            (Path(d) / "src/lib.rs").write_text("pub fn b() {}\n")
            self.assertNotEqual(h1, rdj.source_sha1(d))

    def test_fixture_is_fresh(self):
        meta = (FAKE_RDJ / "azalea.meta").read_text()
        self.assertIn(rdj.source_sha1(FAKE / "azalea"), meta)


class Errors(unittest.TestCase):
    def write(self, d, name, obj):
        p = Path(d) / name
        p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)
        return p

    def test_unsupported_format_version_is_rejected_with_a_message(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "x.json", {"format_version": 9999, "root": 0, "index": {}, "paths": {}, "external_crates": {}})
            with self.assertRaises(rdj.RdjError) as cm:
                rdj.load_file(Path(d) / "x.json")
            self.assertIn("9999", str(cm.exception))

    def test_garbage_json_is_an_rdj_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write(d, "x.json", "{ not json")
            with self.assertRaises((rdj.RdjError, ValueError)):
                rdj.load_file(p)

    def test_missing_directory_is_an_error(self):
        with self.assertRaises((rdj.RdjError, FileNotFoundError, OSError)):
            rdj.load_dir(ROOT / "does-not-exist")

    def test_range_override_by_env(self):
        self.assertEqual(rdj.accepted_range((50, 70)), (50, 70))


class Synthetic(unittest.TestCase):
    def test_ws2_workspace_has_two_crates_a_and_b(self):
        ws = synth_ws2()
        self.assertEqual(sorted(ws), ["a", "b"])

    def test_weird_crate_is_a_synth_with_an_index(self):
        syn = synth_weird()
        self.assertTrue(syn.index)
        self.assertIn(syn.root, syn.index)

    def test_cli_selftest_entrypoints_exist(self):
        out = run(["python3", ROOT / "tools/rdj_synth.py"])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("usage", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
