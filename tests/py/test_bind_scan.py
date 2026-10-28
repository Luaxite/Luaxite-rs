"""tools/bind_scan.py: which Rust fns under rust/ are selected for Luau binding, their signatures, and skip rules."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _common
import bind_scan


def scan(src, label="rust/t.rs"):
    """(rows, stderr) for one source text; rows = (fn, mode)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rows = list(bind_scan.scan_text(src, label))
    return rows, err.getvalue()


def names(src):
    return [r[2] for r in scan(src)[0]]


class Modes(unittest.TestCase):
    SRC = "pub fn a() {}\nfn b() {}\npub(crate) fn c() {}\n#[bind]\nfn d() {}\n"

    def test_default_is_macro(self):
        self.assertEqual(names(self.SRC), ["d"])

    def test_header_modes(self):
        self.assertEqual(names("//BIND *macro\n" + self.SRC), ["d"])
        self.assertEqual(names("//BIND *all\n" + self.SRC), ["a", "b", "c", "d"])
        self.assertEqual(names("//BIND *pub\n" + self.SRC), ["a"])  # pub(crate) is not public

    def test_header_without_placeholder_and_bom(self):
        self.assertEqual(names("//BIND pub\n" + self.SRC), ["a"])
        self.assertEqual(names("﻿//BIND *pub\n" + self.SRC), ["a"])

    def test_unknown_mode_warns_and_uses_macro(self):
        rows, err = scan("//BIND *bogus\n" + self.SRC)
        self.assertEqual([r[2] for r in rows], ["d"])
        self.assertIn("unknown BIND mode", err)

    def test_header_only_on_line_one(self):
        self.assertEqual(names("\n//BIND *all\n" + self.SRC), ["d"])

    def test_attr_forms(self):
        src = "#[bind]\nfn a() {}\n#[luaxite_bind::bind]\nfn b() {}\n#[bind(name = \"x\")]\nfn c() {}\n#[bindx]\nfn d() {}\n"
        self.assertEqual(names(src), ["a", "b", "c"])

    def test_attr_stacked_with_others(self):
        self.assertEqual(names("#[inline]\n#[bind]\n#[allow(dead_code)]\npub fn a() {}\n"), ["a"])

    def test_comments_and_strings_are_inert(self):
        src = '//BIND *all\n// fn c() {}\n/* fn d() {} */\nfn a() { let s = "fn e() {"; }\nfn b() {}\n'
        self.assertEqual(names(src), ["a", "b"])

    def test_line_numbers(self):
        rows, _ = scan("//BIND all\n\n/* x\n y */\nfn a() {}\n")
        self.assertEqual([r[1] for r in rows], [5])


class Signatures(unittest.TestCase):
    def sig(self, decl):
        (row,), _ = scan("//BIND all\n" + decl + " {}\n")
        return row[4], row[5]

    def test_smoke_case(self):
        params, ret = self.sig("fn f(a: Vec<(i32, u8)>, cb: fn(i32) -> i32) -> Result<(), String>")
        self.assertEqual(params, [{"name": "a", "ty": "Vec<(i32, u8)>"}, {"name": "cb", "ty": "fn(i32) -> i32"}])
        self.assertEqual(ret, "Result<(), String>")

    def test_unit_and_no_params(self):
        self.assertEqual(self.sig("pub fn f()"), ([], ""))

    def test_trailing_comma_mut_and_lifetime(self):
        params, _ = self.sig("fn f(mut a: i32, s: &'a str,)")
        self.assertEqual(params, [{"name": "a", "ty": "i32"}, {"name": "s", "ty": "&'a str"}])

    def test_pattern_param_and_nested_generics(self):
        params, ret = self.sig("fn f((a, b): (i32, i32), m: HashMap<String, Vec<u8>>) -> Option<Vec<Vec<u8>>>")
        self.assertEqual(params[0], {"name": "(a, b)", "ty": "(i32, i32)"})
        self.assertEqual(params[1]["ty"], "HashMap<String, Vec<u8>>")
        self.assertEqual(ret, "Option<Vec<Vec<u8>>>")

    def test_array_type_and_where_clause(self):
        params, ret = self.sig("fn f(y: [u8; 4]) -> impl Fn(i32) -> i32 where Self: Sized")
        self.assertEqual(params, [{"name": "y", "ty": "[u8; 4]"}])
        self.assertEqual(ret, "impl Fn(i32) -> i32")

    def test_comment_in_params(self):
        params, _ = self.sig("fn f(a: i32 /* c, d: x */, b: bool)")
        self.assertEqual([p["name"] for p in params], ["a", "b"])

    def test_self_param_is_reported_as_self(self):
        for decl in ("self", "&self", "&mut self", "mut self", "&'a self", "self: Box<Self>"):
            with self.subTest(decl=decl):
                self.assertEqual(bind_scan.parse_param(decl), {"name": "self", "ty": ""})


class Skips(unittest.TestCase):
    def check(self, body, reason, fn="x"):
        rows, err = scan("//BIND all\n" + body)
        self.assertNotIn(fn, [r[2] for r in rows])
        self.assertIn(f" {fn} {reason}\n", err)

    def test_generic(self):
        self.check("pub fn x<T: Into<String>>(a: T) {}\n", "generic")

    def test_lifetime_generic(self):
        self.check("fn x<'a>(a: &'a str) {}\n", "generic")

    def test_self(self):
        rows, err = scan("//BIND all\nimpl S {\n    fn x(&self) {}\n    fn y(a: u8) {}\n}\n")
        self.assertEqual(rows, [])
        self.assertEqual(err, "skip rust/t.rs:3 x self\nskip rust/t.rs:4 y inner\n")

    def test_async(self):
        self.check("pub async fn x() {}\n", "async")
        self.check("pub async unsafe fn x() {}\n", "async")

    def test_cfg_test_module(self):
        rows, err = scan("//BIND all\nfn keep() {}\n#[cfg(test)]\nmod tests {\n    fn x() {}\n}\nfn after() {}\n")
        self.assertEqual([r[2] for r in rows], ["keep", "after"])
        self.assertIn("skip rust/t.rs:5 x cfg_test\n", err)

    def test_cfg_test_and_test_attr_on_fn(self):
        rows, err = scan("//BIND all\n#[cfg(test)]\nfn x() {}\n#[test]\nfn y() {}\n")
        self.assertEqual(rows, [])
        self.assertEqual(err, "skip rust/t.rs:3 x cfg_test\nskip rust/t.rs:5 y cfg_test\n")

    def test_nested(self):
        rows, err = scan("//BIND all\nfn outer() {\n    fn x() {}\n    if true { fn z() {} }\n}\nfn y() {}\n")
        self.assertEqual([r[2] for r in rows], ["outer", "y"])
        self.assertIn("skip rust/t.rs:3 x nested\n", err)
        self.assertIn("skip rust/t.rs:4 z nested\n", err)

    def test_impl_mod_and_trait_bodies_are_inner(self):
        # `crate::<file module>::name` does not name a fn inside them
        rows, err = scan("//BIND all\nmod m {\n    pub fn a() {}\n    impl S { pub fn b() {} }\n}\ntrait T { fn c() {} fn d(); }\nfn top() {}\n")
        self.assertEqual([r[2] for r in rows], ["top"])
        for n, f in ((3, "a"), (4, "b"), (6, "c"), (6, "d")):
            self.assertIn(f"skip rust/t.rs:{n} {f} inner\n", err)

    def test_extras_vis_and_cfgs(self):
        src = '//BIND all\npub fn a() {}\npub(crate) fn b() {}\npub(self) fn c() {}\nfn d() {}\n#[cfg(feature = "x")]\n#[inline]\nfn e() {}\n'
        got = {r[2]: r[6] for r in bind_scan.scan_text(src, "rust/t.rs")}
        self.assertEqual([got[k]["vis"] for k in "abcde"], [True, True, False, False, False])
        self.assertEqual(got["e"]["cfgs"], ['cfg(feature = "x")'])
        self.assertEqual(got["a"]["cfgs"], [])

    def test_only_selected_fns_are_reported(self):
        rows, err = scan("fn plain<T>(t: T) {}\n#[bind]\nfn marked<T>(t: T) {}\n")
        self.assertEqual(rows, [])
        self.assertEqual(err, "skip rust/t.rs:3 marked generic\n")

    def test_fn_pointer_type_is_not_a_fn(self):
        self.assertEqual(names("//BIND all\nfn a(cb: fn(i32) -> i32, g: Fn(u8)) {}\n"), ["a"])


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        rs = Path(self.tmp.name) / "rust_binds" / "luau"
        rs.mkdir(parents=True)
        (rs / "a.rs").write_text("//BIND *pub\npub fn f(a: i32, s: String) -> bool { true }\npub fn g<T>() {}\n")
        (rs / "b.rs").write_text("#[bind]\nfn h() {}\nfn ignored() {}\n")
        tgt = Path(self.tmp.name) / "rust" / "target"
        tgt.mkdir(parents=True)
        (tgt / "c.rs").write_text("//BIND all\nfn nope() {}\n")

    def test_text_output_and_skip_stderr(self):
        p = _common.run(["python3", _common.TOOLS / "bind_scan.py", "--root", self.tmp.name])
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.splitlines(), ["rust_binds/luau/a.rs:2 f pub", "rust_binds/luau/b.rs:2 h macro"])
        self.assertEqual(p.stderr, "skip rust_binds/luau/a.rs:3 g generic\n")

    def test_user_code_in_rust_is_scanned_before_the_glue(self):
        (Path(self.tmp.name) / "rust" / "main.rs").write_text("#[bind]\nfn mine() {}\n")
        p = _common.run(["python3", _common.TOOLS / "bind_scan.py", "--root", self.tmp.name])
        self.assertEqual(p.stdout.splitlines()[0], "rust/main.rs:2 mine macro")
        self.assertEqual(len(p.stdout.splitlines()), 3)

    def test_json_output(self):
        p = _common.run(["python3", _common.TOOLS / "bind_scan.py", "--root", self.tmp.name, "--json"])
        self.assertEqual(p.returncode, 0)
        self.assertEqual(
            json.loads(p.stdout),
            [
                {
                    "file": "rust_binds/luau/a.rs",
                    "line": 2,
                    "fn": "f",
                    "mode": "pub",
                    "params": [{"name": "a", "ty": "i32"}, {"name": "s", "ty": "String"}],
                    "ret": "bool",
                    "vis": True,
                    "cfgs": [],
                },
                {"file": "rust_binds/luau/b.rs", "line": 2, "fn": "h", "mode": "macro", "params": [], "ret": "", "vis": False, "cfgs": []},
            ],
        )

    def test_missing_rust_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = _common.run(["python3", _common.TOOLS / "bind_scan.py", "--root", d, "--json"])
            self.assertEqual((p.returncode, json.loads(p.stdout)), (0, []))


if __name__ == "__main__":
    unittest.main()
