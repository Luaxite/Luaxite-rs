"""tools/api_list.py: the API list (API_list.md) from a generated .d.luau."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from _common import ROOT, TOOLS, run
import sys

import api_list

FIXTURE = ROOT / "tools/testdata/api_list"
D_LUAU = (FIXTURE / "bindings.d.luau").read_text()
GOLDEN = (FIXTURE / "API_list.md").read_text()
CONFIG = ROOT / "bindgen.toml"


def bullets(text, title):
    """The bullet texts of the `## title` section."""
    sec = re.split(r"^## ", text, flags=re.M)
    body = next(s for s in sec if s.split("\n", 1)[0] == title)
    return [l[3:-1] for l in body.splitlines() if l.startswith("- `")]


class Fixture(unittest.TestCase):

    def test_matches_the_committed_api_list_byte_for_byte(self):
        # the fixture is the .d.luau shape tools/luaxite_gen.py writes (library tables, hand classes, docs, methods out of order)
        self.assertEqual(api_list.build(D_LUAU, CONFIG), GOLDEN)

    def test_is_deterministic(self):
        self.assertEqual(api_list.build(D_LUAU, CONFIG), api_list.build(D_LUAU, CONFIG))

    def test_every_declaration_is_listed_once(self):
        decls = len(re.findall(r"^    function ", D_LUAU, flags=re.M)) + len(re.findall(r"^    [a-z_]+: \(", D_LUAU, flags=re.M))
        self.assertEqual(GOLDEN.count("- `declare function "), decls)
        self.assertEqual(len(bullets(GOLDEN, "Types")), len(re.findall(r"^type ", D_LUAU, flags=re.M)))

    def test_section_order(self):
        self.assertEqual(re.findall(r"^## (.*)$", GOLDEN, flags=re.M),
                         ["Types", "Globals", "`azalea`", "`goal`", "`process`", "Bot", "Entity", "Container", "World", "Goal", "Swarm"])

    def test_without_config_classes_keep_the_d_luau_order(self):
        text = api_list.build(D_LUAU, None)
        self.assertEqual(re.findall(r"^## (.*)$", text, flags=re.M)[5:], ["Container", "World", "Goal", "Swarm", "Entity", "Bot"])

    def test_methods_are_sorted_and_overloads_keep_their_order(self):
        bot = bullets(GOLDEN, "Bot")
        names = [re.match(r"declare function Bot:(\w+)", b).group(1) for b in bot]
        self.assertEqual(names, sorted(names))
        on = [b for b in bot if ":on(" in b]
        self.assertEqual([re.search(r'event: "(\w+)"', b).group(1) for b in on][:3], ["init", "login", "chat"])

    def test_self_is_dropped_and_library_tables_use_a_dot(self):
        self.assertIn("declare function Entity:attack(): ()", bullets(GOLDEN, "Entity"))
        self.assertIn("declare function Bot:chat(content: string): ()", bullets(GOLDEN, "Bot"))
        self.assertIn("declare function goal.all(...Goal): Goal", bullets(GOLDEN, "`goal`"))
        self.assertIn("declare function azalea.wait(): ()", bullets(GOLDEN, "`azalea`"))
        self.assertIsNone(re.search(r"\bself\b", GOLDEN))           # `query_self` is a name, not the receiver

    def test_no_doc_comments_leak_in(self):
        self.assertNotIn("Doc for", GOLDEN)
        self.assertNotIn("hand-written", GOLDEN)


class Parsing(unittest.TestCase):

    def test_multiline_union_is_one_line(self):
        text = api_list.build("type P =\n    | A\n    | B\n\ndeclare extern type Bot with\nend\n", None)
        self.assertEqual(bullets(text, "Types"), ["type P = A | B"])

    def test_nested_callback_signatures(self):
        d = ('declare extern type Bot with\n'
             '    function q(self, names: { string }, f: (row: { [string]: any }) -> any): any?\n'
             '    function s(self, t: "(" | ")"): ()\n'
             'end\n'
             'declare extern type Lib with\n'
             '    each: (f: (x: number) -> boolean, ...string) -> { number }\n'
             'end\n'
             'declare lib: Lib\ndeclare bot: Bot\n')
        text = api_list.build(d, None)
        self.assertEqual(bullets(text, "Bot"), ["declare function Bot:q(names: { string }, f: (row: { [string]: any }) -> any): any?",
                                                 'declare function Bot:s(t: "(" | ")"): ()'])
        self.assertEqual(bullets(text, "`lib`"), ["declare function lib.each(f: (x: number) -> boolean, ...string): { number }"])
        self.assertEqual(bullets(text, "Globals"), ["declare bot: Bot", "declare lib: Lib"])

    def test_free_function_table_of_the_generic_mode(self):
        d = "declare toy: {\n    --- Double.\n    double: (x: number) -> number,\n    zero: () -> (),\n}\n"
        text = api_list.build(d, None)
        self.assertEqual(bullets(text, "`toy`"), ["declare function toy.double(x: number): number", "declare function toy.zero(): ()"])
        self.assertEqual(bullets(text, "Globals"), ["declare toy: toy"])

    def test_empty_and_junk_input(self):
        for d in ("", "-- only a comment\n", "garbage {{{\n"):
            self.assertEqual(api_list.build(d, None), "# Luaxite Luau API\n\nDeclarations for everything scripts can use. Generated; do not edit by hand.\n")

    def test_backticks_in_a_declaration(self):
        self.assertEqual(api_list.code("a`b"), "``a`b``")
        self.assertEqual(api_list.code("`x`"), "`` `x` ``")


class Harness(unittest.TestCase):

    def test_on_the_fake_azalea_output(self):
        d = (ROOT / "harness/luau/azalea.d.luau").read_text()
        text = api_list.build(d, CONFIG)
        self.assertEqual(re.findall(r"^## (.*)$", text, flags=re.M), ["Types", "Globals", "Bot", "Entity", "Container"])
        self.assertEqual(bullets(text, "Globals"), ["declare bot: Bot"])
        want = len(re.findall(r"^    function ", d, flags=re.M))
        self.assertEqual(text.count("- `declare function "), want)

    def test_types_match_the_real_list_prefix(self):
        d = (ROOT / "harness/luau/azalea.d.luau").read_text()
        self.assertEqual(bullets(api_list.build(d, CONFIG), "Types"), bullets(GOLDEN, "Types"))


class ApiJson(unittest.TestCase):
    """API.json is what tools and CI read; API_list.md is rendered from the same data and never parsed."""

    def test_the_text_list_is_rendered_from_the_data(self):
        api = api_list.build_dict(D_LUAU, CONFIG)
        self.assertEqual(api_list.render(api), GOLDEN)

    def test_dumps_round_trips_and_is_deterministic(self):
        api = api_list.build_dict(D_LUAU, CONFIG)
        self.assertEqual(json.loads(api_list.dumps(api)), api)
        self.assertEqual(api_list.dumps(api), api_list.dumps(api_list.build_dict(D_LUAU, CONFIG)))

    def test_declarations_are_data(self):
        api = api_list.build_dict(D_LUAU, CONFIG)
        self.assertEqual(api["schema"], api_list.API_SCHEMA)
        bot = next(c for c in api["classes"] if c["name"] == "Bot")
        self.assertFalse(bot["library"])
        self.assertTrue(all(set(m) == {"name", "method", "params", "ret", "decl"} for m in bot["members"]))
        self.assertIn({"name": "bot", "type": "Bot"}, api["globals"])
        goal = next(c for c in api["classes"] if c["prefix"] == "goal")
        self.assertTrue(goal["library"] and not any(m["method"] for m in goal["members"]))
        # every bullet of the text list is one `decl` of the data, and the other way round
        decls = [m["decl"] for c in api["classes"] for m in c["members"]]
        self.assertEqual(sorted(decls), sorted(l[3:-1] for l in GOLDEN.splitlines() if l.startswith("- `declare function ")))

    def test_cli_json_out(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "API.json"
            p = run([sys.executable, TOOLS / "api_list.py", "--dluau", FIXTURE / "bindings.d.luau", "--config", CONFIG, "--json-out", out])
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(out.read_text()), api_list.build_dict(D_LUAU, CONFIG))


class Cli(unittest.TestCase):

    def test_writes_the_file(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "API_list.md"
            p = run([sys.executable, TOOLS / "api_list.py", "--dluau", FIXTURE / "bindings.d.luau", "--out", out])
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(out.read_text(), GOLDEN)

    def test_stdout_by_default(self):
        p = run([sys.executable, TOOLS / "api_list.py", "--dluau", FIXTURE / "bindings.d.luau"])
        self.assertEqual((p.returncode, p.stdout), (0, GOLDEN))

    def test_missing_input_is_one_error_line(self):
        p = run([sys.executable, TOOLS / "api_list.py", "--dluau", "/no/such/file.d.luau"])
        self.assertEqual(p.returncode, 1)
        self.assertTrue(p.stderr.startswith("error: ") and p.stderr.count("\n") == 1, p.stderr)


if __name__ == "__main__":
    unittest.main()
