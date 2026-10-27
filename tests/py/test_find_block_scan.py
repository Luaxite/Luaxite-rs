"""find_block / find_blocks scan (rust/luau/real_world.rs) and registry lookups (rust/luau/real_registry.rs), checked on source structure
(the root crate can't be built here): the loaded-chunk filter runs before a hit counts, only the `limit` nearest are kept (no full sort),
and registry lookups neither rebuild the whole name list nor depend only on the hard-coded list."""
import re
import unittest

from _common import read


def fn_body(src: str, name: str, method: bool = False) -> str:
    """Body of `fn name`; method=True picks the one taking `&self` (a free fn and a Lua method may share a name)."""
    m = next((m for m in re.finditer(r"\n\s*fn " + name + r"\b[^{]*\{", src) if ("&self" in m.group(0)) == method), None)
    assert m, name
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i]


class FindBlockScan(unittest.TestCase):
    def setUp(self):
        self.src = read("rust/luau/real_world.rs")
        self.search = fn_body(self.src, "search", method=True)

    def test_filter_before_cap_and_push(self):
        s = self.search
        # s15: the loaded-chunk answer comes from the map built by loaded_chunk_map (no partial lock inside the scan loop)
        loaded, push, cap = s.index("loaded_chunks.get("), s.index("nearest.push("), s.index("examined >= MAX_CANDIDATES")
        self.assertLess(loaded, push)
        self.assertLess(push, cap)
        self.assertIn("if !loaded {\n                    continue;", s)            # skipped hits never reach the counter
        self.assertIn(".unwrap_or(false)", s)                                      # a chunk missing from the map is not loaded

    def test_search_never_nests_the_world_and_partial_locks(self):
        s = self.search
        self.assertNotIn("chunk_is_loaded", s)                    # that one takes the partial lock: not while a world guard is held
        self.assertNotIn("partial_world", s)
        self.assertIn("loaded_chunk_map(", s)
        self.assertEqual(s.count("world.read()"), 2)              # pass 1 and pass 2, each its own guard
        # pass 1's guard lives in a block that is closed again before loaded_chunk_map is called
        pass1 = s[s.index("world.read()"):s.index("loaded_chunk_map(")]
        self.assertIn("HashSet", s)
        self.assertIn("keys.insert(", pass1)
        self.assertGreater(pass1.count("}"), pass1.count("{"))
        # the map is built under ONE partial guard, which never meets the world lock
        m = fn_body(self.src, "loaded_chunk_map", method=True)
        self.assertEqual(m.count("partial.read()"), 1)
        self.assertNotIn("world", m.replace("partial_world", ""))
        self.assertIn("drop(guard)", m)
        # the only other partial-lock site is the single-chunk read
        self.assertEqual(self.src.count("partial.read()"), 2)

    def test_lock_order_comments(self):
        for name in ("chunk_is_loaded", "search"):
            i = self.src.index("fn " + name)
            doc = self.src[self.src.rindex("\n\n", 0, i):i]
            self.assertIn("never hold both locks", doc.lower(), name)

    def test_no_collect_all_then_sort(self):
        s = self.search
        self.assertNotIn("found", s)
        self.assertNotRegex(s, r"\.sort(_by|_unstable)?\(")
        self.assertNotRegex(s, r"Vec<\(f64, BlockPos\)>")
        self.assertIn("Nearest::new(limit)", s)

    def test_nearest_keeps_only_limit(self):
        body = re.search(r"impl Nearest \{.*?\n\}\n", self.src, re.S).group(0)
        self.assertIn("select_nth_unstable_by(self.limit - 1", body)
        self.assertIn("truncate(self.limit)", body)
        self.assertIn("saturating_mul(2)", body)
        self.assertIn("total_cmp", self.src)                                       # no partial_cmp().unwrap_or(Equal)
        self.assertNotIn("partial_cmp", self.src)

    def test_limit_is_clamped_and_zero_short_circuits(self):
        self.assertIn("limit.min(MAX_CANDIDATES)", self.search)
        self.assertRegex(self.search, r"if limit == 0 \{\s*return Ok\(Vec::new\(\)\);")

    def test_rust_unit_tests_present(self):
        self.assertIn("#[cfg(test)]", self.src)
        self.assertIn("fn nearest_keeps_the_closest_in_order", self.src)
        self.assertIn("fn nearest_limit_zero_and_ties", self.src)


class RegistryLookups(unittest.TestCase):
    def setUp(self):
        self.src = read("rust/luau/real_registry.rs")

    def test_resolve_get_name_do_not_build_the_whole_list(self):
        for name in ("registry_resolve", "registry_name", "registry_get"):
            body = fn_body(self.src, name, method=True)
            self.assertNotIn("entries_of(", body, name)
            self.assertNotRegex(body, r"\.collect\(\)", name)
        self.assertIn("entries_of(&self.client", fn_body(self.src, "registry_entries", method=True))   # the only caller that needs the list

    def test_names_come_from_the_holder_too(self):
        self.assertIn("fn holder_extra_names", self.src)
        self.assertIn("holder.extra.contains_key(", fn_body(self.src, "registry_name"))
        self.assertIn("kinds_of(&self.client)", fn_body(self.src, "registry_kinds", method=True))
        self.assertNotIn("REGISTRIES.iter().map(|n| n.to_string()).collect()\n    }", fn_body(self.src, "registry_kinds", method=True))

    def test_decl_signatures_unchanged(self):
        for decl in (
            "function registry_kinds(self): { string }",
            "function registry_entries(self, registry: string): { string }",
            "function registry_resolve(self, registry: string, name: string): number?",
            "function registry_name(self, registry: string, id: number): string?",
            "function registry_get(self, registry: string, name: string): { name: string, id: number }?",
        ):
            self.assertIn("// luau[Bot]: " + decl, self.src)


if __name__ == "__main__":
    unittest.main()
