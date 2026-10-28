#!/usr/bin/env python3
"""
rdj_selftest.py - stdlib-only self test of tools/rdj.py against the committed fixture harness/fake/rustdoc/azalea.json.
Run by tools/check.sh (`python3 tools/rdj_selftest.py`); exit 0 = all tests passed. Since slice 3 it also imports the
generator (stdlib only). Later slices add their tests here
(types, defs, methods, paths, ...) so one file stays the single place to look.

The fixture is made by `sh tools/make_rustdoc_json.sh harness/fake/azalea harness/fake/rustdoc`; test_fixture_fresh fails
when harness/fake/azalea's sources changed since (re-run the script and commit the JSON).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.dont_write_bytecode = True
import rdj



os.environ.pop("AZL_RDJ_FORMAT_RANGE", None)
from rdj_synth import Synth

FIXTURE = ROOT / "harness" / "fake" / "rustdoc"
FAKE_CRATE = ROOT / "harness" / "fake" / "azalea"
FAKE_SRC = (FAKE_CRATE / "src" / "lib.rs").read_text()

TESTS = []


def test(f):
    TESTS.append(f)
    return f


_cache = {}


def fixture():
    if "r" not in _cache:
        _cache["r"] = rdj.load_dir(FIXTURE)
    return _cache["r"]


def by_name(c, name, kind):
    found = [i for i, it in c.index.items() if it.get("name") == name and rdj.inner_kind(it) == kind]
    assert len(found) == 1, f"expected exactly one {kind} `{name}`, found {found}"
    return found[0]


def raises(fn, *needles):
    """fn must raise RdjError whose message contains every needle."""
    try:
        fn()
    except rdj.RdjError as e:
        for n in needles:
            assert n in str(e), f"{n!r} not in error: {e}"
        return str(e)
    raise AssertionError("expected RdjError, nothing raised")




@test
def test_fixture_fresh():
    meta = rdj.read_meta(FIXTURE / "azalea.json")
    assert meta.get("source_sha1"), "azalea.meta has no source_sha1 (rebuild with tools/make_rustdoc_json.sh)"
    assert meta["source_sha1"] == rdj.source_sha1(FAKE_CRATE), (
        "harness/fake/rustdoc/azalea.json is stale: harness/fake/azalea changed since it was made; run "
        "`sh tools/make_rustdoc_json.sh harness/fake/azalea harness/fake/rustdoc` and commit the result")
    assert meta.get("private_items") == "1", "fixture must be built with --document-private-items"


@test
def test_fixture_loads():
    r = fixture()
    assert sorted(r.crates) == ["azalea"], sorted(r.crates)
    c = r.crate("azalea")
    assert r.format_version == c.format_version == rdj.FORMAT_TESTED == 57
    assert c.includes_private is True
    assert c.name == "azalea" and c.stem == "azalea" and c.target_triple
    root = c.item(c.root)
    assert rdj.inner_kind(root) == "module" and root["name"] == "azalea"
    assert c.meta["rustc"].startswith("rustc 1.97"), c.meta
    assert r.warnings == [], r.warnings
    assert r.root("azalea") == c.root and r.item("azalea", c.root) is root
    raises(lambda: r.crate("nope"), "no JSON loaded for crate `nope`", "azalea")


@test
def test_index_integrity():
    c = fixture().crate("azalea")
    assert len(c.index) > 1000 and len(c.paths) > 1000
    assert all(isinstance(k, int) for k in list(c.index) + list(c.paths) + list(c.external_crates))
    for k, it in c.index.items():
        assert it["id"] == k, (k, it["id"])
    for pid, it in c.index.items():
        for cid in c.children(pid):
            assert cid in c.index, f"child {cid} of item {pid} ({it.get('name')}) is not in index"
    ext = c.external_crates
    assert {"core", "alloc", "std", "tokio"} <= {e["name"] for e in ext.values()}
    for i, s in c.paths.items():
        assert s["crate_id"] == 0 or s["crate_id"] in ext, (i, s)


        assert s["kind"] == "variant" or c.crate_name(s["crate_id"]) == s["path"][0], (i, s, c.crate_name(s["crate_id"]))
    assert c.crate_name(0) == "azalea" and c.crate_name(99999) is None


@test
def test_root_items_match_source():
    """Top-level items of the root module = the column-0 items of lib.rs (independent of the rustdoc reader)."""
    c = fixture().crate("azalea")
    want = set()
    kinds = {"struct": "struct", "enum": "enum", "trait": "trait", "mod": "module", "type": "type_alias",
             "fn": "function", "union": "union", "macro_rules!": "macro"}
    for m in re.finditer(r"^(?:pub(?:\([^)]*\))? )?(?:async )?(struct|enum|trait|mod|type|fn|union|macro_rules!) ?(\w+)",
                         FAKE_SRC, re.M):
        want.add((kinds[m.group(1)], m.group(2)))
    have = {(c.kind(i), c.item(i)["name"]) for i in c.children(c.root) if c.kind(i) != "use"}
    assert have == want, f"only in JSON: {sorted(have - want)}; only in source: {sorted(want - have)}"
    uses = [i for i in c.children(c.root) if c.kind(i) == "use"]
    assert len(uses) == len(re.findall(r"^(?:pub(?:\([^)]*\))? )?use ", FAKE_SRC, re.M)), len(uses)


@test
def test_children_and_impls():
    c = fixture().crate("azalea")

    ev = by_name(c, "Event", "enum")
    body = FAKE_SRC.split("pub enum Event {", 1)[1].split("\n}", 1)[0]
    want = re.findall(r"^    ([A-Z]\w*)", body, re.M)
    assert [c.item(i)["name"] for i in c.children(ev)] == want, want
    assert all(c.kind(i) == "variant" for i in c.children(ev))

    cl = by_name(c, "Client", "struct")
    assert [c.item(i)["name"] for i in c.children(cl)] == ["entity"]
    mid = by_name(c, "MinecraftEntityId", "struct")
    assert [c.item(i)["name"] for i in c.children(mid)] == ["0"]
    assert c.children(by_name(c, "Uuid", "struct")) is not None

    death = [i for i in c.children(ev) if c.item(i)["name"] == "Death"][0]
    assert len(c.children(death)) == 1 and c.kind(c.children(death)[0]) == "struct_field"
    assert c.children(-1) == [] and c.impls(-1) == []

    imps = c.impls(cl)
    assert len(imps) > 5 and all(c.kind(i) == "impl" for i in imps)
    fns = [n for i in imps for n in c.children(i) if c.kind(n) == "function"]
    names = {c.item(n)["name"] for n in fns}
    assert {"chat", "position", "health"} <= names, sorted(names)[:20]

    tr = by_name(c, "PathfinderClientExt", "trait")
    assert c.kind(tr) == "trait" and len(c.children(tr)) > 0 and isinstance(c.impls(tr), list)


@test
def test_item_path():
    r = fixture()
    c = r.crate("azalea")
    ev = by_name(c, "Event", "enum")
    assert r.item_path("azalea", by_name(c, "Client", "struct")) == ("azalea", "Client")
    assert r.item_path(c, ev) == ("azalea", "Event")

    assert c.item_path(by_name(c, "BlockPos", "struct")) == ("azalea", "position", "BlockPos")
    assert c.item_path(by_name(c, "ClientboundPlayerCombatKill", "struct")) == (
        "azalea", "protocol", "packets", "game", "ClientboundPlayerCombatKill")

    death = [i for i in c.children(ev) if c.item(i)["name"] == "Death"][0]
    assert c.item_path(death) == ("azalea", "Event", "Death")
    assert c.item_path(c.children(by_name(c, "Client", "struct"))[0]) == ("azalea", "Client", "entity")
    tr = by_name(c, "PathfinderClientExt", "trait")
    assert c.item_path(c.children(tr)[0]) == ("azalea", "pathfinder", "PathfinderClientExt", c.item(c.children(tr)[0])["name"])
    chat = [n for i in c.impls(by_name(c, "Client", "struct")) for n in c.children(i) if c.item(n).get("name") == "chat"]
    assert len(chat) == 1 and c.item_path(chat[0]) == ("azalea", "Client", "chat")

    imp = c.impls(by_name(c, "Client", "struct"))[0]
    assert c.item_path(imp) is None and c.item_path(-1) is None
    use = [i for i in c.children(c.root) if c.kind(i) == "use"][0]
    assert c.item_path(use)[:1] == ("azalea",) and len(c.item_path(use)) == 2, c.item_path(use)

    arc = next(i for i, s in c.paths.items() if s["path"] == ["alloc", "sync", "Arc"])
    assert c.paths[arc]["crate_id"] != 0 and c.crate_name(c.paths[arc]["crate_id"]) == "alloc"
    assert c.item_path(arc) == ("alloc", "sync", "Arc")


@test
def test_visibility_helpers():
    c = fixture().crate("azalea")
    assert rdj.visibility(c.item(by_name(c, "Client", "struct"))) == "public"
    seen = {rdj.visibility(it) for it in c.index.values()}
    assert {"public", "default"} <= seen <= {"public", "default", "crate", "restricted"}, seen
    assert rdj.visibility({}) == "default" and rdj.visibility({"visibility": {"restricted": {}}}) == "restricted"
    assert rdj.inner_kind({}) == "" and rdj.inner_kind({"inner": "x"}) == "x" and rdj.payload({"inner": "x"}) == {}




def tmpdir():
    d = Path(tempfile.mkdtemp(prefix="rdj_selftest_"))
    _cache.setdefault("tmp", []).append(d)
    return d


def with_format(version, meta=True):
    """A copy of the fixture directory whose JSON claims `version`."""
    d = tmpdir()
    text = (FIXTURE / "azalea.json").read_text()
    tail = f'"format_version":{rdj.FORMAT_TESTED}}}'
    assert text.endswith(tail), text[-60:]
    (d / "azalea.json").write_text(text[: -len(tail)] + f'"format_version":{version}}}')
    if meta:
        shutil.copy(FIXTURE / "azalea.meta", d / "azalea.meta")
    return d


@test
def test_format_range_error():
    msg = raises(lambda: rdj.load_dir(with_format(99)), "format_version 99", "accepted range 57-61", "tested with format_version 57",
                 "rustc 1.97.0 (2d8144b78 2026-07-07)", "make_rustdoc_json.sh", "AZL_RDJ_FORMAT_RANGE=99-99")
    assert "\n" not in msg and "Traceback" not in msg
    raises(lambda: rdj.load_dir(with_format(56)), "format_version 56")
    raises(lambda: rdj.load_dir(with_format(62)), "format_version 62")
    raises(lambda: rdj.load_dir(with_format(99, meta=False)), "unknown rustc", "azalea.meta")
    assert rdj.load_dir(with_format(99), accept=(50, 100)).format_version == 99


@test
def test_format_range_override():
    d = with_format(99)
    r = rdj.load_dir(d, accept=(57, 100))
    assert r.crate("azalea").format_version == 99 and any("only 57 is tested" in w for w in r.warnings), r.warnings
    old = os.environ.get("AZL_RDJ_FORMAT_RANGE")
    try:
        os.environ["AZL_RDJ_FORMAT_RANGE"] = "99"
        assert rdj.load_dir(d).format_version == 99
        os.environ["AZL_RDJ_FORMAT_RANGE"] = "50-60"
        raises(lambda: rdj.load_dir(d), "accepted range 50-60")
        os.environ["AZL_RDJ_FORMAT_RANGE"] = "bogus"
        raises(lambda: rdj.load_dir(d), "AZL_RDJ_FORMAT_RANGE='bogus'")
    finally:
        if old is None:
            os.environ.pop("AZL_RDJ_FORMAT_RANGE", None)
        else:
            os.environ["AZL_RDJ_FORMAT_RANGE"] = old
    assert rdj.peek_format_version(FIXTURE / "azalea.json") == 57


@test
def test_bad_input_errors():
    raises(lambda: rdj.load_dir(tmpdir()), "no *.json files")
    raises(lambda: rdj.load_dir(tmpdir() / "missing"), "does not exist")
    d = tmpdir()
    (d / "a.json").write_text("{not json")
    raises(lambda: rdj.load_dir(d), "a.json", "not valid JSON")
    (d / "a.json").write_text("[1, 2]")
    raises(lambda: rdj.load_dir(d), "not a rustdoc JSON file", "list")
    (d / "a.json").write_text('{"format_version": 57, "root": 0}')
    raises(lambda: rdj.load_dir(d), "missing keys", "index", "paths", "external_crates")

    (d / "a.json").write_text('{"junk": [1, 2, 3], "format_version":99}')
    raises(lambda: rdj.load_dir(d), "format_version 99")
    (d / "a.json").write_text('{"root": 7, "index": {}, "paths": {}, "external_crates": {}, "format_version": 57}')
    raises(lambda: rdj.load_dir(d), "root item id 7")
    (d / "a.json").write_text('{"root": 7, "index": [], "paths": {}, "external_crates": {}, "format_version": 57}')
    raises(lambda: rdj.load_dir(d), "`index` should be an object")

    d2 = tmpdir()
    shutil.copy(FIXTURE / "azalea.json", d2 / "azalea.json")
    shutil.copy(FIXTURE / "azalea.json", d2 / "azalea2.json")
    raises(lambda: rdj.load_dir(d2), "already loaded")


@test
def test_main_cli():
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        assert rdj.main([str(FIXTURE)]) == 0
    assert "azalea: format_version 57" in out.getvalue() and "root:" in out.getvalue()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        assert rdj.main([str(tmpdir())]) == 1 and rdj.main([]) == 2
    assert "error: " in err.getvalue()




def generator():
    """tools/luaxite_gen.py as a module (stdlib only)."""
    if "gen" not in _cache:
        try:
            import luaxite_gen
        except ImportError as e:
            raise AssertionError(f"cannot import the generator ({e})")
        _cache["gen"] = luaxite_gen
    return _cache["gen"]


@test
def test_convert_type_unit_cases():
    P = {"primitive": "u32"}
    path = lambda n, *a: {"resolved_path": {"path": n, "id": 1, "args": {"angle_bracketed": {"args": [{"type": x} for x in a], "constraints": []}} if a else None}}
    assert rdj.convert_type(P) == ("prim", "u32")
    assert rdj.convert_type({"tuple": []}) == ("unit",)
    assert rdj.convert_type({"tuple": [P, P]}) == ("tuple", [("prim", "u32")] * 2)
    assert rdj.convert_type({"slice": P}) == ("slice", ("prim", "u32"))
    assert rdj.convert_type({"array": {"type": P, "len": "4"}}) == ("slice", ("prim", "u32"))
    assert rdj.convert_type(path("std::collections::HashMap", path("String"), path("Vec3"))) == \
        ("path", "HashMap", [("path", "String", []), ("path", "Vec3", [])])
    ref = lambda t, m=False, lt=None: {"borrowed_ref": {"lifetime": lt, "is_mutable": m, "type": t}}
    assert rdj.convert_type(ref(P)) == ("ref", ("prim", "u32"))
    assert rdj.convert_type(ref(P, lt="'a")) == ("ref", ("prim", "u32"))
    assert rdj.convert_type(ref(path("Vec", P), True)) == ("other", "&mut Vec<u32>")
    assert rdj.convert_type(ref(P, True, "'a")) == ("other", "&'a mut u32")
    into = {"impl_trait": [{"trait_bound": {"trait": {"path": "Into", "id": 2, "args": {"angle_bracketed": {"args": [{"type": path("Pos")}], "constraints": []}}},
                                           "generic_params": [], "modifier": "none"}}, {"outlives": "'static"}]}
    assert rdj.convert_type(into) == ("impl", "impl Into<Pos> + 'static")
    assert rdj.convert_type({"dyn_trait": {"traits": [{"trait": {"path": "Fn", "id": 3, "args": {"parenthesized": {"inputs": [P], "output": None}}},
                                                       "generic_params": []}], "lifetime": None}}) == ("impl", "dyn Fn(u32)")
    for t, text in (({"generic": "T"}, "T"), ({"generic": "Self"}, "Self"), ({"infer": None}, "_"),
                    ({"raw_pointer": {"is_mutable": False, "type": P}}, "*const u32"),
                    ({"function_pointer": {"sig": {"inputs": [["a", P]], "output": P}}}, "fn(u32) -> u32"),
                    ({"qualified_path": {"name": "Error", "args": None, "self_type": {"generic": "T"},
                                         "trait": {"path": "TryFrom", "id": 4, "args": {"angle_bracketed": {"args": [{"type": {"generic": "U"}}], "constraints": []}}}}},
                     "<T as TryFrom<U>>::Error"),
                    ({"qualified_path": {"name": "Item", "args": None, "self_type": {"generic": "Self"}, "trait": {"path": "", "id": 5, "args": None}}}, "Self::Item"),
                    ({"brand_new_variant": 1}, "<brand_new_variant>")):
        assert rdj.convert_type(t) == ("other", text), (t, rdj.convert_type(t))

    for bad in (None, 3, "x", [], {}, {"resolved_path": 5}, {"borrowed_ref": None}, {"a": 1, "b": 2}):
        assert rdj.convert_type(bad)[0] in ("other", "path", "ref", "slice", "tuple", "unit", "prim", "impl"), bad

    it = {"resolved_path": {"path": "Iterator", "id": 6, "args": {"angle_bracketed": {"args": [], "constraints": [
        {"name": "Item", "args": None, "binding": {"equality": {"type": P}}}]}}}}
    assert rdj.convert_type(it) == ("path", "Iterator", [("other", "Item = u32")])




def rdj_defs():
    if "defs" not in _cache:
        import rdj_index
        _cache["defs"] = rdj_index.build_defs(fixture())
    return _cache["defs"]


def split_attrs(attrs):
    """-> (derived traits in order, other attributes without cfg/doc/#[default]: rustc resolves or consumes those before rustdoc
    writes the JSON, so the front end cannot see them; slice 7 decides what that means for cfg-gated items)."""
    derive, other = [], []
    for a in attrs:
        m = re.fullmatch(r"#\[derive\((.*)\)\]", a)
        if m:
            derive += [x.strip() for x in m.group(1).split(",") if x.strip()]
        elif not a.startswith(("#[cfg(", "#[doc")) and a != "#[default]":
            other.append(a)
    return derive, sorted(other)


@test
def test_defs_shapes_and_edge_cases():
    import rdj_index
    js = rdj_defs()
    one = lambda name: js[name][0]
    assert one("BlockPos").kind == "struct" and one("BlockPos").modpath == ("position",) and one("BlockPos").crate == "azalea"
    assert one("Entity").tuple_style and one("Entity").fields[0][0] == "0"
    kinds = {d.kind for defs in js.values() for d in defs}
    assert {"struct", "enum", "trait"} <= kinds, kinds

    assert "StructuralPartialEq" not in " ".join(a for defs in js.values() for d in defs for a in d.attrs)
    assert any("#[non_exhaustive]" in d.attrs for defs in js.values() for d in defs if d.kind == "enum")

    c = fixture().crate("azalea")
    p = {"kind": {"plain": {"fields": [], "has_stripped_fields": True}}}
    assert rdj_index._struct_fields(c, p) == ([rdj_index.STRIPPED], False)
    f, ts = rdj_index._struct_fields(c, {"kind": {"tuple": [None, None]}})
    assert ts and f == [("0", ("other", "_"), False), ("1", ("other", "_"), False)], f
    assert rdj_index._struct_fields(c, {"kind": "unit"}) == ([], False)

    assert rdj.doc_summary("First line\nsecond [`Foo`](x) line\n\nSecond paragraph") == "First line second `Foo` line"
    assert rdj.doc_summary(None) == "" and rdj.doc_summary("") == ""
    assert rdj.attr_texts({"attrs": ["non_exhaustive", "automatically_derived", {"other": "#[allow(dead_code)]"}, {"other": "#[attr = Inline(Hint)]"}, 7]}) \
        == ["#[non_exhaustive]", "#[allow(dead_code)]"]

    assert rdj_index._fields(c, [None, 10 ** 9]) == [("0", ("other", "_"), False), ("1", ("other", "_"), False)]
    assert rdj_index._variants(c, {"variants": [10 ** 9]}) == []





def rdj_impls():
    if "impls" not in _cache:
        import rdj_index
        _cache["impls"] = rdj_index.build_impls(fixture(), strip_prefix="fake/")
    return _cache["impls"]


@test
def test_impls_filters():
    """Which impls count: user-written ones for the bound classes (macro-made ones included), not derives / synthetic / blanket."""
    import rdj_index
    r = fixture()
    d = rdj_impls()
    assert not [m for m in d.methods if m.owner in ("Clone", "Debug", "Default", "PartialEq")], \
        "#[derive] impls (automatically_derived) must not become methods"
    assert "Clone" not in d.client_traits
    assert {m.target for m in d.methods} == {"Client", "EntityRef"}
    only_client = rdj_index.build_impls(r, classes={"Client"}, strip_prefix="fake/")
    assert {m.target for m in only_client.methods} == {"Client"} and len(only_client.methods) < len(d.methods)
    assert not rdj_index.build_impls(r, classes=set()).methods

    assert {m.file.split(" ")[0] for m in rdj_index.build_impls(r).methods} == {"fake/azalea/src/lib.rs"}

    plain = [m for m in d.methods if m.target == "Client" and not m.file.endswith("(via macro)")]
    c = r.crate("azalea")
    lines = {}
    for i, it in c.index.items():
        if rdj.inner_kind(it) == "function" and it.get("crate_id") == 0 and (it.get("span") or {}).get("begin"):
            lines.setdefault(it["name"], []).append(it["span"]["begin"][0])
    first = [min(lines[m.name]) for m in plain]
    assert first == sorted(first), "methods must come in source order"

    mk = lambda b, e, f="a.rs": {"span": {"filename": f, "begin": b, "end": e}}
    assert rdj_index.method_file(mk([5, 1], [9, 2]), mk([5, 1], [9, 2])) == "a.rs (via macro)"
    assert rdj_index.method_file(mk([5, 1], [9, 2]), mk([6, 5], [8, 6])) == "a.rs"
    assert rdj_index.method_file({}, {}) == "<unknown>"
    assert rdj_index.method_file(mk([1, 1], [2, 2], "fake\\a.rs"), mk([1, 2], [1, 9], "fake\\a.rs"), "fake/") == "a.rs"


@test
def test_impls_helpers():
    import rdj_index as ri
    P = {"primitive": "u32"}
    S = {"generic": "Self"}
    ref = lambda t, m=False, lt=None: {"borrowed_ref": {"lifetime": lt, "is_mutable": m, "type": t}}

    assert ri.split_receiver([["self", ref(S)], ["a", P]]) == ("&self", [["a", P]])
    assert ri.split_receiver([["self", ref(S, True)]]) == ("&mut self", [])
    assert ri.split_receiver([["self", ref(S, False, "'a")]]) == ("&'a self", [])
    assert ri.split_receiver([["self", S]]) == ("self", [])
    assert ri.split_receiver([["self", {"resolved_path": {"path": "Arc", "id": 1, "args": {"angle_bracketed": {"args": [{"type": S}], "constraints": []}}}}]])[0] == "self: Arc<Self>"
    assert ri.split_receiver([["a", P]]) == (None, [["a", P]]) and ri.split_receiver([]) == (None, []) and ri.split_receiver(None) == (None, [])
    assert ri.split_receiver([["self"]])[0] is None

    assert [ri.param_name(n) for n in ("x", "_", "_x", "(a, b)", "&x", "", None, "r#type", "x2")] == ["x", None, "_x", None, None, None, None, None, "x2"]

    tb = lambda n: {"trait_bound": {"trait": {"path": n, "id": 1, "args": None}, "generic_params": [], "modifier": "none"}}
    gp = [{"name": "'a", "kind": {"lifetime": {"outlives": ["'b"]}}},
          {"name": "T", "kind": {"type": {"bounds": [tb("A"), tb("B")], "default": None, "is_synthetic": False}}},
          {"name": "U", "kind": {"type": {"bounds": [], "default": P, "is_synthetic": False}}},
          {"name": "impl Into<X>", "kind": {"type": {"bounds": [tb("Into")], "default": None, "is_synthetic": True}}},
          {"name": "N", "kind": {"const": {"type": P, "default": "3"}}}]
    assert ri.render_generic_params(gp) == "<'a: 'b, T: A + B, U = u32, const N: u32 = 3>"
    assert ri.render_generic_params([gp[3]]) == "" and ri.render_generic_params([]) == "" and ri.render_generic_params(None) == ""
    assert ri.render_generic_params(["junk", {"name": "X"}]) == "<X>"
    assert ri.render_where([{"bound_predicate": {"type": {"generic": "T"}, "bounds": [tb("Send")], "generic_params": []}},
                            {"lifetime_predicate": {"lifetime": "'a", "outlives": ["'b"]}}]) == " where T: Send, 'a: 'b"
    assert ri.render_where([]) == "" and ri.render_where(None) == ""

    fn = {"name": "f", "visibility": "public", "inner": {"function": {
        "sig": {"inputs": [["self", ref(S)], ["x", P], ["_", P]], "output": P, "is_c_variadic": False},
        "generics": {"params": gp[1:2], "where_predicates": [{"bound_predicate": {"type": {"generic": "T"}, "bounds": [tb("Send")], "generic_params": []}}]},
        "header": {"is_const": True, "is_unsafe": True, "is_async": True, "abi": "Rust"}, "has_body": True}}}
    assert ri.fn_sig_text(fn, rdj.payload(fn)) == "pub const async unsafe fn f<T: A + B>(&self, x: u32, _: u32) -> u32 where T: Send"
    fn2 = {"name": "g", "visibility": "default", "inner": {"function": {"sig": {"inputs": [], "output": None}, "generics": {"params": [], "where_predicates": []},
                                                                      "header": {"abi": {"C": {"unwind": False}}}}}}
    assert ri.fn_sig_text(fn2, rdj.payload(fn2)) == 'extern "C" fn g()'
    fn2["visibility"] = "crate"
    assert ri.fn_sig_text(fn2, rdj.payload(fn2)).startswith("pub(crate) ")
    fn2["visibility"] = {"restricted": {"parent": 1, "path": "::crate::x"}}
    assert ri.fn_sig_text(fn2, rdj.payload(fn2)).startswith("pub(in crate::x) ")





def rdj_paths():
    if "paths" not in _cache:
        import rdj_index
        _cache["paths"] = rdj_index.RdjPaths(fixture(), rdj_defs())
    return _cache["paths"]


@test
def test_paths_fake_overrides():
    """The fake defines ClientboundPlayerCombatKill in a public module, so the JSON path is the PATH_OVERRIDES entry already.
    (The macro-style variant, a type behind a private module and a `pub use`, is test_paths_synthetic_workspace.)"""
    g = generator()
    assert rdj_paths().resolve_path("ClientboundPlayerCombatKill") == g.PATH_OVERRIDES["ClientboundPlayerCombatKill"]


def synth_workspace(drop=()):
    """azalea (root) over azalea_client / azalea_core / azalea_protocol, laid out like the real workspace:
    azalea: `pub use azalea_client::*; pub use azalea_core as core; pub use azalea_protocol as protocol;` + a private module
    azalea_client: private `inner` re-exported by name / rename / a glob module, a glob cycle (`pub mod a { pub use super::*; }`)
    azalea_protocol: the `declare_state_packets!` shape: a packet in a private module, `pub use`d by `packets::game`."""
    az, cl, co, pr = Synth("azalea"), Synth("azalea_client"), Synth("azalea_core"), Synth("azalea_protocol")

    pos = co.mod("position", co.root)
    co.struct("Vec3", pos)
    co.struct("BlockPos", pos)

    inner = cl.mod("inner", cl.root, vis="default")
    c_client = cl.struct("Client", inner)
    c_only = cl.struct("OnlyRenamed", inner)
    cl.use(cl.root, "inner::Client", c_client)
    cl.use(cl.root, "inner::OnlyRenamed", c_only, name="Renamed")
    plugins = cl.mod("plugins", cl.root)
    cl.struct("Plugin", plugins)
    ent = cl.mod("entity", cl.root)
    cl.struct("EntityRef", ent)
    cl.struct("Crate_Private", ent, vis="crate")
    cl.use(cl.root, "plugins", plugins, glob=True)
    cyc = cl.mod("a", cl.root)
    cl.use(cyc, "super", cl.root, glob=True)
    cl.use(ent, "crate::inner::Client", c_client, name="Client")

    packets = pr.mod("packets", pr.root)
    game = pr.mod("game", packets)
    kill_mod = pr.mod("c_player_combat_kill", game, vis="default")
    kill = pr.struct("ClientboundPlayerCombatKill", kill_mod)
    pr.use(game, "c_player_combat_kill::ClientboundPlayerCombatKill", kill)

    az.use(az.root, "azalea_client", az.foreign("azalea_client", kind="module"), glob=True)
    az.use(az.root, "azalea_core", az.foreign("azalea_core", kind="module"), name="core")
    az.use(az.root, "azalea_protocol", az.foreign("azalea_protocol", kind="module"), name="protocol")
    hidden = az.mod("hidden", az.root, vis="default")
    az.struct("Hidden", hidden)
    az.struct("Direct", az.root)
    prel = az.mod("prelude", az.root)
    az.use(prel, "crate::Direct", next(i for i, it in az.index.items() if it["name"] == "Direct"), name="Direct")
    r = rdj.Rdj()
    for c in (az, cl, co, pr):
        if c.name not in drop:
            r.crates[c.name] = c.crate()
    return r


@test
def test_paths_synthetic_workspace():
    import rdj_index
    g = generator()
    r = synth_workspace()
    pa = rdj_index.RdjPaths(r)
    rp = pa.resolve_path
    assert rp("Direct") == "azalea::Direct"
    assert pa.paths_of("azalea", (), "Direct") == ["azalea::Direct", "azalea::prelude::Direct"]
    assert rp("Client") == "azalea::Client"
    assert pa.paths_of("azalea_client", ("inner",), "Client")[0] == "azalea::Client"
    assert "azalea::entity::Client" in pa.paths_of("azalea_client", ("inner",), "Client")
    assert rp("Plugin") == "azalea::Plugin"
    assert rp("EntityRef") == "azalea::entity::EntityRef"
    assert rp("Vec3") == "azalea::core::position::Vec3" and rp("BlockPos") == "azalea::core::position::BlockPos"
    assert rp("Hidden") is None
    assert rp("OnlyRenamed") is None
    only = pa.paths_of("azalea_client", ("inner",), "OnlyRenamed")
    assert only[0] == "azalea::Renamed" and all(p.endswith("::Renamed") for p in only), only
    assert rp("Crate_Private") is None

    assert rp("ClientboundPlayerCombatKill") == "azalea::protocol::packets::game::ClientboundPlayerCombatKill" \
        == g.PATH_OVERRIDES["ClientboundPlayerCombatKill"]

    assert pa.paths_of("azalea_client", ("inner",), "Client")[0] == "azalea::Client"
    assert not any(len(p) > rdj_index.RdjPaths.MAX_DEPTH for ps in pa.public_paths().values() for p in ps)

    assert pa.aliases() == {"azalea_core": "core", "azalea_protocol": "protocol"}, pa.aliases()
    assert ("azalea", (), "*", "azalea_client") in pa.reexports and ("azalea", (), "azalea_client") in pa.globs
    assert pa.chain_public("azalea_protocol", ("packets", "game")) and not pa.chain_public("azalea", ("hidden",))
    assert not pa.chain_public("azalea_protocol", ("packets", "game", "c_player_combat_kill"))
    assert pa.mod_pub[("azalea", ("hidden",))] is False and pa.mod_pub[("azalea_client", ("plugins",))] is True
    assert not pa.unresolved, pa.unresolved


@test
def test_paths_missing_crates_and_errors():
    import rdj_index

    pa = rdj_index.RdjPaths(synth_workspace(drop=("azalea_core", "azalea_protocol")))
    assert pa.resolve_path("Direct") == "azalea::Direct" and pa.resolve_path("Client") == "azalea::Client"
    assert pa.resolve_path("Vec3") is None and pa.resolve_path("ClientboundPlayerCombatKill") is None
    pa.public_paths()
    assert ("azalea", "azalea_core") in pa.unresolved and ("azalea", "azalea_protocol") in pa.unresolved, pa.unresolved
    raises(lambda: rdj_index.RdjPaths(synth_workspace(drop=("azalea",))), "no rustdoc JSON for the root crate `azalea`")

    pa2 = rdj_index.RdjPaths(synth_workspace(), root="azalea_client")
    assert pa2.resolve_path("Client") == "azalea_client::Client" and pa2.resolve_path("Vec3") is None

    r = synth_workspace()
    c = r.crate("azalea")
    c.index[c.root]["inner"]["module"]["items"] += [10 ** 6]
    c.index[max(c.index) + 1] = {"id": max(c.index) + 1, "crate_id": 0, "name": None, "visibility": "public", "attrs": [],
                                  "inner": {"use": {"source": "x", "id": None, "is_glob": False}}}
    c.index[c.root]["inner"]["module"]["items"].append(max(c.index))
    assert rdj_index.RdjPaths(r).resolve_path("Direct") == "azalea::Direct"


@test
def test_unresolved_reason_names_the_real_cause():
    import rdj_index

    r = synth_workspace(drop=("azalea_core",))
    az = r.crate("azalea")
    pid = next(i for i, s in az.paths.items() if s.get("path") == ["azalea_protocol"])
    az.paths[pid]["path"] = ["azalea_protocol", "vanished"]
    ix = rdj_index.RdjIndex(ROOT, ROOT)
    ix.rdj = r
    ix.paths = rdj_index.RdjPaths(r)
    lines = ix.report_lines()
    gone = [ln for ln in lines if "`azalea_core`" in ln]
    vanished = [ln for ln in lines if "azalea_protocol::vanished" in ln]
    assert len(gone) == 1 and "its crate has no loaded JSON" in gone[0] and "not found" not in gone[0], lines
    assert len(vanished) == 1 and "not found in its loaded JSON" in vanished[0] and "no loaded JSON" not in vanished[0], lines
    assert r.not_found == {("azalea", "azalea_protocol::vanished")}, r.not_found


@test
def test_loader_warnings_printed_on_generator_path():
    import contextlib
    import io
    import rdj_index

    def load(rdir):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rdj_index.RdjIndex(FAKE_CRATE.parent, rdir).load()
        return err.getvalue()
    assert load(FIXTURE) == ""
    old = os.environ.get("AZL_RDJ_FORMAT_RANGE")
    try:
        os.environ["AZL_RDJ_FORMAT_RANGE"] = "57-100"
        out = load(with_format(99))
    finally:
        if old is None:
            os.environ.pop("AZL_RDJ_FORMAT_RANGE", None)
        else:
            os.environ["AZL_RDJ_FORMAT_RANGE"] = old
    lines = out.splitlines()
    assert len(lines) == 1 and lines[0].startswith("warning: azalea.json: format_version 99") and "only 57 is tested" in lines[0], out


def load_index_stderr(root, rdir):
    """RdjIndex(root, rdir).load() -> its stderr text (a raised error propagates)."""
    import contextlib
    import io
    import rdj_index
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rdj_index.RdjIndex(root, rdir).load()
    return err.getvalue()


@test
def test_stale_json_warns():

    root = tmpdir()
    shutil.copytree(FAKE_CRATE, root / "azalea")
    assert load_index_stderr(root, FIXTURE) == ""
    with open(root / "azalea" / "src" / "lib.rs", "a") as f:
        f.write("\npub struct AddedAfterTheJson;\n")
    lines = load_index_stderr(root, FIXTURE).splitlines()
    assert len(lines) == 1 and lines[0].startswith("warning: azalea.json is stale"), lines
    assert "`azalea`" in lines[0] and "make_rustdoc_json.sh" in lines[0], lines

    d = tmpdir()
    shutil.copy(FIXTURE / "azalea.json", d / "azalea.json")
    lines = load_index_stderr(root, d).splitlines()
    assert len(lines) == 1 and "azalea.json: its .meta has no source_sha1" in lines[0], lines


@test
def test_mixed_format_versions_warn():
    import rdj_index

    d = tmpdir()
    for f in WS2.joinpath("rustdoc").iterdir():
        if f.is_file():
            shutil.copy(f, d / f.name)
    assert rdj.load_dir(d).warnings == []
    raw = json.loads((d / "b.json").read_text())
    raw["format_version"] = 61
    (d / "b.json").write_text(json.dumps(raw))
    r = rdj.load_dir(d)
    mixed = [w for w in r.warnings if "mix format_versions" in w]
    assert len(mixed) == 1 and "a 57" in mixed[0] and "b 61" in mixed[0], r.warnings
    raises(lambda: r.format_version, "mix format_versions")
    ix = rdj_index.RdjIndex(ROOT, d)
    ix.rdj = r
    assert "format_version 57/61" in ix.frontend_label, ix.frontend_label
    ix.rdj = rdj.load_dir(FIXTURE)
    assert ix.frontend_label.endswith("format_version 57)"), ix.frontend_label


@test
def test_enum_variant_cfgs_scanner():
    import rdj_index
    text = '''
pub enum Event {
    /// doc with a ] a "quote" and , commas
    Init,
    #[cfg(feature = "packet-event")]
    /// the packet
    Packet(Arc<Foo<A, B>>),
    #[doc(hidden)] #[cfg(all(feature = "a",   not(test)))]
    Gated { x: u32, /* , #[cfg(no)] */ y: [u8; 2] },
    Tick = 5, // trailing, comma
    #[cfg_attr(test, derive(Debug))]
    Last,
}
enum Other { A }
'''
    got = rdj_index.enum_variant_cfgs(text, "Event")
    assert got == {"Init": [], "Packet": ['#[cfg(feature = "packet-event")]'], "Gated": ['#[cfg(all(feature = "a", not(test)))]'],
                   "Tick": [], "Last": []}, got
    assert rdj_index.enum_variant_cfgs(text, "Other") == {"A": []}
    assert rdj_index.enum_variant_cfgs(text, "Missing") is None and rdj_index.enum_variant_cfgs("enum Event", "Event") is None


@test
def test_cfg_gated_event_variant_is_not_exposed():
    import rdj_index

    g = generator()

    def events(src_edit):
        root = tmpdir()
        shutil.copytree(FAKE_CRATE, root / "azalea")
        lib = root / "azalea" / "src" / "lib.rs"
        lib.write_text(src_edit(lib.read_text()))
        ix = rdj_index.RdjIndex(root, FIXTURE)
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()) as err:
            ix.load()
        gen_ = g.Generator(ix)
        gen_.build()
        gen_.build_events()
        return gen_, err.getvalue()
    plain, err = events(lambda t: t)
    assert "tick" in [e["lname"] for e in plain.events] and not any("cfg-gated" in n for n in plain.event_notes), plain.event_notes
    assert err == "", err
    assert 'Tick,\n' in FAKE_SRC
    gated, err = events(lambda t: t.replace("    Tick,\n", '    #[cfg(feature = "ticks")]\n    Tick,\n', 1))
    assert "tick" not in [e["lname"] for e in gated.events], [e["lname"] for e in gated.events]
    assert any("`Tick`: cfg-gated (#[cfg(feature = \"ticks\")]), not exposed" in n for n in gated.event_notes), gated.event_notes
    assert "login" in [e["lname"] for e in gated.events]


@test
def test_cfg_gates_unreadable_source_warns():
    import rdj_index

    r = rdj.load_dir(FIXTURE)
    defs = rdj_index.build_defs(r)
    w = rdj_index.event_cfg_gates(r, defs, tmpdir(), "fake/")
    assert len(w) == 1 and w[0].startswith("enum Event (azalea): cannot read its `#[cfg]` gates") and "FileNotFoundError" in w[0], w
    assert all(name in w[0] for name in ("Tick", "Login", "Chat")), w[0]
    assert not any("#[cfg(" in a for d in defs["Event"] for v in d.variants for a in v["attrs"])
    assert rdj_index.event_cfg_gates(r, defs, ROOT / "harness" / "fake", "fake/") == []






WS2 = ROOT / "tools" / "testdata" / "ws2"


def ws2():
    if "ws2" not in _cache:
        _cache["ws2"] = rdj.load_dir(WS2 / "rustdoc")
    return _cache["ws2"]


@test
def test_ws2_fixture_fresh():
    import rdj_synth
    for name in ("a", "b"):
        meta = rdj.read_meta(WS2 / "rustdoc" / f"{name}.json")
        assert meta.get("source_sha1") == rdj.source_sha1(WS2 / name), \
            f"tools/testdata/ws2/{name} sources changed after the JSON was made: re-run tools/make_rustdoc_json.sh (or rdj_synth.py ws2)"
    if rdj.read_meta(WS2 / "rustdoc" / "a.json").get("rustc", "").startswith("hand-built"):
        d = tmpdir()
        for p in rdj_synth.write_ws2(d):
            assert p.read_bytes() == (WS2 / "rustdoc" / p.name).read_bytes(), f"{p.name}: committed JSON differs from tools/rdj_synth.py ws2"
    r = ws2()
    assert sorted(r.crates) == ["a", "b"] and r.format_version == rdj.FORMAT_TESTED


@test
def test_ws2_loader_resolves_siblings():
    r = ws2()
    a, b = r.crate("a"), r.crate("b")
    bot = by_name(a, "Bot", "struct")
    pos, facing, marks = (a.item(i) for i in a.children(bot))
    vec3_b, dir_b, marker_b = by_name(b, "Vec3", "struct"), by_name(b, "Dir", "enum"), by_name(b, "Marker", "struct")

    tpos = rdj_index_field_type(pos)
    assert a.index.get(tpos["resolved_path"]["id"]) is None and a.paths[tpos["resolved_path"]["id"]]["crate_id"] != 0
    assert r.resolve("a", tpos["resolved_path"]["id"]) == ("b", vec3_b)
    assert r.resolve("a", rdj_index_field_type(facing)["resolved_path"]["id"]) == ("b", dir_b)
    arg = rdj_index_field_type(marks)["resolved_path"]["args"]["angle_bracketed"]["args"][0]["type"]
    assert r.resolve("a", arg["resolved_path"]["id"]) == ("b", marker_b)

    uses = {rdj.payload(a.item(i)).get("name"): rdj.payload(a.item(i)) for i in a.children(a.root) if a.kind(i) == "use"}
    assert sorted(uses) == ["North", "Vec3", "base"], sorted(uses)
    assert r.resolve("a", uses["Vec3"]["id"]) == ("b", vec3_b)
    nid = r.resolve("a", uses["North"]["id"])
    assert nid[0] == "b" and b.item(nid[1])["name"] == "North" and b.kind(nid[1]) == "variant" and b.parent(nid[1]) == dir_b
    assert r.resolve("a", uses["base"]["id"]) == ("b", b.root)

    assert r.resolve("a", bot) == ("a", bot) and r.resolve("b", vec3_b) == ("b", vec3_b)
    miss = []
    vec_id = rdj_index_field_type(marks)["resolved_path"]["id"]
    assert r.resolve("a", vec_id, miss) is None and miss == [("a", "alloc::vec::Vec")], miss
    for bad in (None, "x", 10 ** 9, -1, 1.5):
        assert r.resolve("a", bad) is None
    assert a.local_paths()[("a",)] == a.root and b.local_paths()[("b", "geom", "Dir", "North")] == nid[1]


def rdj_index_field_type(item):
    import rdj_index
    return rdj_index.field_type(item)


@test
def test_ws2_cross_crate_fields_and_variants():
    import rdj_index
    r = ws2()
    a, b = r.crate("a"), r.crate("b")
    defs = rdj_index.build_defs(r)
    assert sorted(defs) == ["Bot", "Cmd", "Dir", "Marker", "Vec3"], sorted(defs)
    bot = by_name(a, "Bot", "struct")

    v3 = defs["Vec3"][0]
    assert v3.crate == "b" and v3.modpath == ("geom",) and v3.is_pub
    assert [(n, t, p) for n, t, p in v3.fields] == [("x", ("prim", "f64"), True), ("y", ("prim", "f64"), True), ("z", ("prim", "f64"), True)]
    dr = defs["Dir"][0]
    assert dr.kind == "enum" and dr.crate == "b"
    assert [(v["name"], v["kind"], v["types"], v["doc"]) for v in dr.variants] == [
        ("North", "unit", [], ""), ("Offset", "tuple", [("prim", "i32")], ""), ("Pos", "struct", [("path", "Vec3", [])], "")], dr.variants

    assert [(n, t) for n, t, _ in defs["Bot"][0].fields] == [("pos", ("path", "Vec3", [])), ("facing", ("path", "Dir", [])),
                                                              ("marks", ("path", "Vec", [("path", "Marker", [])]))]

    pa = rdj_index.RdjPaths(r, root="a")
    assert pa.resolve_path("Vec3") == "a::Vec3"
    assert pa.paths_of("b", ("geom",), "Vec3") == ["a::Vec3", "a::base::geom::Vec3"]
    assert pa.resolve_path("Dir") == "a::base::geom::Dir" and pa.resolve_path("Marker") == "a::base::Marker"
    assert pa.resolve_path("Bot") == "a::Bot" and not pa.unresolved, pa.unresolved
    assert pa.aliases() == {"b": "base"}


@test
def test_resolve_alias_quirk_and_name_fallbacks():
    """rustdoc lists a variant reached through a type alias with the enum's crate_id and the ALIAS path."""
    r = ws2()
    a, b = r.crate("a"), r.crate("b")
    north_b = by_name(b, "North", "variant")
    quirk = max(a.paths) + 1
    a.paths[quirk] = {"crate_id": next(k for k, v in a.external_crates.items() if v["name"] == "b"), "path": ["a", "Facing", "North"], "kind": "variant"}
    try:
        assert r.resolve("a", quirk) == ("b", north_b)

        c = r.crate("b")
        dup = max(c.index) + 1
        c.index[dup] = dict(c.index[north_b], id=dup)
        c.paths[dup] = {"crate_id": 0, "path": ["b", "geom", "Other", "North"], "kind": "variant"}
        c._local_paths = None
        miss = []
        assert r.resolve("a", quirk, miss) is None and miss == [("a", "a::Facing::North")], miss
        del c.index[dup], c.paths[dup]
        c._local_paths = None
        assert r.resolve("a", quirk) == ("b", north_b)

        vec3 = next(i for i, s in a.paths.items() if s["path"] == ["b", "geom", "Vec3"])
        saved = a.external_crates.pop(a.paths[vec3]["crate_id"])
        try:
            assert r.resolve("a", vec3) == ("b", by_name(b, "Vec3", "struct"))
        finally:
            a.external_crates[a.paths[vec3]["crate_id"]] = saved
    finally:
        del a.paths[quirk]
        r.crate("b")._local_paths = None


@test
def test_make_rustdoc_json_ws_order_and_failures():
    """tools/make_rustdoc_json_ws.sh against a shimmed `cargo metadata` and a recorder instead of make_rustdoc_json.sh (the
    sandbox has no cargo; the real run on azalea is the user's): dependency order, filtering, errors."""
    import subprocess
    d = tmpdir()
    (d / "ws").mkdir()
    (d / "ws" / "Cargo.toml").write_text("[workspace]\n")

    def pkg(name, deps=(), kind="lib", member=True):
        return {"id": f"{name} 0.1.0", "name": name.replace("_", "-"), "manifest_path": f"/w/{name}/Cargo.toml",
                "targets": [{"name": name, "kind": [kind]}], "dependencies": [{"name": x.replace("_", "-")} for x in deps]}
    pk = [pkg("azalea", ["azalea_client", "azalea_core", "tokio"]), pkg("azalea_client", ["azalea_protocol", "azalea_core"]),
          pkg("azalea_core"), pkg("azalea_protocol", ["azalea_core"]), pkg("azalea_cli", ["azalea"], kind="bin")]
    meta = {"packages": pk, "workspace_members": [p["id"] for p in pk]}
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "bin").mkdir()
    (d / "bin" / "cargo").write_text('#!/bin/sh\n[ "$1" = metadata ] && cat "$META" && exit 0\nexit 9\n')
    (d / "bin" / "cargo").chmod(0o755)
    (d / "rec.sh").write_text('#!/bin/sh\necho "$1 $2 env=$AZL_RDJ_ENV offline=$AZL_RDJ_OFFLINE" >> "$REC"\n'
                               '[ "$(basename "$1")" = "$FAILON" ] && exit 1\nexit 0\n')

    def run(*args, meta_file="meta.json", failon=""):
        rec = d / "rec.log"
        rec.write_text("")
        env = dict(os.environ, PATH=f"{d / 'bin'}:{os.environ['PATH']}", META=str(d / meta_file), REC=str(rec),
                   AZL_RDJ_MAKE=str(d / "rec.sh"), FAILON=failon)
        for k in ("AZL_RDJ_ENV", "AZL_RDJ_OFFLINE", "AZL_WS_SKIP"):
            env.pop(k, None)
        p = subprocess.run(["sh", str(ROOT / "tools" / "make_rustdoc_json_ws.sh"), str(d / "ws"), str(d / "out"), *args],
                           capture_output=True, text=True, env=env)
        return p, [Path(l.split()[0]).name for l in rec.read_text().splitlines()], rec.read_text()
    p, order, log = run()
    assert p.returncode == 0, p.stderr
    assert order == ["azalea_core", "azalea_protocol", "azalea_client", "azalea"], order
    assert all(f"{d / 'out'} env=0 offline=0" in l for l in log.splitlines()), log
    assert "4 crates" in p.stdout and "AZALEA_RDJ=" in p.stdout
    p, order, _ = run("azalea", "azalea-client")
    assert p.returncode == 0 and order == ["azalea_client", "azalea"], (order, p.stderr)
    p, order, _ = run("nope")
    assert p.returncode == 2 and "no library package named: nope" in p.stderr and order == []
    p, order, _ = run(failon="azalea_protocol")
    assert p.returncode == 1 and order == ["azalea_core", "azalea_protocol", "azalea_client", "azalea"] and "failed: azalea_protocol" in p.stderr
    cyc = {"packages": [pkg("x", ["y"]), pkg("y", ["x"])]}
    (d / "cyc.json").write_text(json.dumps(cyc))
    p, order, _ = run(meta_file="cyc.json")
    assert p.returncode == 2 and "dependency cycle" in p.stderr, p.stderr
    q = subprocess.run(["sh", str(ROOT / "tools" / "make_rustdoc_json_ws.sh")], capture_output=True, text=True)
    assert q.returncode == 2 and "WORKSPACE_DIR OUT_DIR" in q.stderr
    q = subprocess.run(["sh", str(ROOT / "tools" / "make_rustdoc_json_ws.sh"), str(d / "nowhere"), str(d / "o")], capture_output=True, text=True)
    assert q.returncode == 2 and "no such workspace dir" in q.stderr





def synth_macro_crate():
    """`impl Client` x3 as rustdoc gives them: one hand-written impl with a plain fn, a `#[doc(hidden)]` fn and a fn whose
    `#[cfg(feature)]` is on (plain), and what `impl_entity_functions!` expands to (one impl per method, the macro call's
    span on both the impl and the fn, one distinct doc per fn); the same for EntityRef; plus a derive impl."""
    cr = Synth("azalea")
    cl = cr.struct("Client", cr.root)
    er = cr.struct("EntityRef", cr.root)
    path = lambda n, i: {"resolved_path": {"path": n, "id": i, "args": None}}
    span = lambda b, e: {"filename": "azalea/src/lib.rs", "begin": [b, 1], "end": [e, 2]}
    sig = lambda ret: {"sig": {"inputs": [["self", {"borrowed_ref": {"lifetime": None, "is_mutable": False, "type": {"generic": "Self"}}}]],
                               "output": ret, "is_c_variadic": False},
                       "generics": {"params": [], "where_predicates": []},
                       "header": {"is_const": False, "is_unsafe": False, "is_async": False, "abi": "Rust"}, "has_body": True}

    def fn(name, doc, sp, ret=None, attrs=(), vis="public"):
        i = cr.nid
        cr.nid += 1
        cr.index[i] = {"id": i, "crate_id": 0, "name": name, "span": sp, "visibility": vis, "docs": doc, "links": {},
                       "attrs": list(attrs), "deprecation": None, "inner": {"function": sig(ret)}}
        return i

    def impl(target, tid, items, sp, trait=None, attrs=()):
        i = cr.nid
        cr.nid += 1
        cr.index[i] = {"id": i, "crate_id": 0, "name": None, "span": sp, "visibility": "default", "docs": None, "links": {},
                       "attrs": list(attrs), "deprecation": None,
                       "inner": {"impl": {"is_unsafe": False, "generics": {"params": [], "where_predicates": []}, "provided_trait_methods": [],
                                          "trait": trait, "for": path(target, tid), "items": items, "is_negative": False,
                                          "is_synthetic": False, "blanket_impl": None}}}
        return i

    u32 = {"primitive": "u32"}
    impl("Client", cl, [fn("chat", "Sends chat.", span(10, 12)), fn("raw", "Raw access.", span(14, 16), attrs=[{"other": "#[doc(hidden)]"}]),
                        fn("gated", "Only with the feature.", span(18, 20), ret=u32)], span(8, 22))
    call = span(30, 40)
    for tgt, tid in (("Client", cl), ("EntityRef", er)):
        for n in ("position", "health"):
            impl(tgt, tid, [fn(n, f"{tgt} {n}.", call, ret=u32)], call)
    impl("Client", cl, [fn("clone", None, span(1, 1))], span(1, 1), trait={"path": "Clone", "id": 99, "args": None}, attrs=["automatically_derived"])
    r = rdj.Rdj()
    r.crates["azalea"] = cr.crate()
    return r


@test
def test_macros_expanded_impls():
    import rdj_index as ri
    d = ri.build_impls(synth_macro_crate(), classes={"Client", "EntityRef"})
    by = {(m.target, m.name): m for m in d.methods}

    assert {("Client", "position"), ("Client", "health"), ("EntityRef", "position"), ("EntityRef", "health")} <= set(by)
    assert by[("Client", "position")].doc == "Client position." and by[("EntityRef", "position")].doc == "EntityRef position."
    assert by[("Client", "position")].file.endswith("(via macro)") and not by[("Client", "chat")].file.endswith("(via macro)")
    assert d.macro_notes == [] and ("Client", "clone") not in by and not d.client_traits
    assert [m.name for m in d.methods if m.target == "Client"][:4] == ["chat", "raw", "gated", "position"], "plain methods first, macro group last"

    src = (ROOT / "tools" / "rdj_index.py").read_text() + (ROOT / "tools" / "rdj.py").read_text()
    assert "ENTITY_FN" not in src and "impl_entity_functions" not in re.sub(r"#.*|\"\"\"[\s\S]*?\"\"\"", "", src)


@test
def test_bevy_derive_impls_count_as_derives():



    import rdj_index as ri
    r = synth_macro_crate()
    c = r.crates["azalea"]
    cid = next(i for i, it in c.index.items() if it.get("name") == "Client" and "struct" in it["inner"])
    base = next(i for i, it in c.index.items() if "impl" in it["inner"])
    nid = max(c.index) + 1
    for k, (tr, attrs, synth) in enumerate([("Component", [], False), ("Resource", [], False), ("Display", [], False), ("Component", [], True)]):
        it = json.loads(json.dumps(c.index[base]))
        it["id"] = nid + k
        it["attrs"] = attrs
        it["inner"]["impl"].update(trait={"path": tr, "id": 900 + k, "args": None}, items=[], is_synthetic=synth)
        c.index[nid + k] = it
        c.index[cid]["inner"]["struct"].setdefault("impls", []).append(nid + k)
    got = c.derived_traits(cid)
    assert "Component" in got and "Resource" in got and "Display" not in got and got.count("Component") == 1, got
    assert any("Component" in a for a in ri.def_attrs(c, cid, c.index[cid])), "build_ecs searches these derive attributes"


@test
def test_macros_hidden_and_cfg_treatment():
    import rdj_index as ri
    r = synth_macro_crate()
    keep = ri.build_impls(r, classes={"Client"})
    assert "raw" in {m.name for m in keep.methods} and keep.hidden == [("Client", "raw", "kept")]
    skip = ri.build_impls(r, classes={"Client"}, hidden="skip")
    assert "raw" not in {m.name for m in skip.methods} and skip.hidden == [("Client", "raw", "skipped")]
    assert {m.name for m in skip.methods} == {m.name for m in keep.methods} - {"raw"}

    assert "gated" in {m.name for m in skip.methods}
    try:
        ri.build_impls(r, hidden="maybe")
    except ValueError as e:
        assert "hidden" in str(e)
    else:
        raise AssertionError("bad hidden mode accepted")

    for a, want in (("doc(hidden)", True), ({"other": "#[doc( hidden )]"}, True), ({"other": "#[inline]"}, False), ("inline", False), (None, False), (3, False)):
        assert ri.is_hidden({"attrs": [a]}) is want, a
    assert ri.is_hidden({}) is False

    assert rdj_impls().hidden == [] and rdj_impls().macro_notes == []




@test
def test_missing_json_reasons():
    import rdj_index as ri
    fake = ROOT / "harness" / "fake"
    assert ri.workspace_prefix(fixture()) == "fake/"
    assert ri.missing_json(fake, fake / "rustdoc") == ""
    for d, frag in ((None, "no --rustdoc"), (ROOT / "nope", "no rustdoc JSON directory"), (ROOT / "tools", "missing JSON for: azalea")):
        why = ri.missing_json(fake, d)
        assert frag in why, (d, why)


@test
def test_generator_cli_modes():
    """The generator reads rustdoc JSON only: fake output = the committed harness files; a missing/incomplete --rustdoc is one error line."""
    import subprocess
    fake = str(ROOT / "harness" / "fake")
    tmp = tempfile.mkdtemp()
    _cache.setdefault("tmp", []).append(tmp)

    def run(name, *a):
        out = Path(tmp) / name
        (out / "rust").mkdir(parents=True)
        for f in (ROOT / "harness" / "src" / "luau").glob("extra_*.rs"):
            shutil.copy(f, out / "rust")
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "luaxite_gen.py"), "--azalea", fake, "--rust-out", str(out / "rust"),
                            "--luau-out", str(out / "luau"), *a], capture_output=True, text=True)
        return p, out

    p, rd = run("ok", "--rustdoc", str(ROOT / "harness/fake/rustdoc"))
    assert p.returncode == 0 and "Traceback" not in p.stderr, p.stderr
    for f, committed in (("rust/gen_client.rs", "src/luau/gen_client.rs"), ("rust/gen_events.rs", "src/luau/gen_events.rs"),
                         ("rust/gen_types.rs", "src/luau/gen_types.rs"), ("luau/azalea.d.luau", "luau/azalea.d.luau"),
                         ("luau/GEN_REPORT.json", "luau/GEN_REPORT.json"), ("luau/GEN_REPORT.md", "luau/GEN_REPORT.md")):
        assert (rd / f).read_bytes() == (ROOT / "harness" / committed).read_bytes(), f
    assert json.loads((rd / "luau/GEN_REPORT.json").read_text())["front_end"].startswith("rustdoc JSON (rustc ")
    p, _ = run("none")
    assert p.returncode != 0 and "--rustdoc" in p.stderr and "Traceback" not in p.stderr
    p, _ = run("bad", "--rustdoc", str(ROOT / "tools"))
    assert p.returncode != 0 and "missing JSON" in p.stderr and "Traceback" not in p.stderr




WEIRD = ROOT / "tools" / "testdata" / "weird"


def run_generator(azalea_root, rdj_dir, out_dir, extra=()):
    """Run the generator in a subprocess: (CompletedProcess, the parsed GEN_REPORT.json or None). `extra` = more CLI args."""
    import subprocess
    out = Path(out_dir)
    (out / "rust").mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "luaxite_gen.py"), "--azalea", str(azalea_root),
                        "--rustdoc", str(rdj_dir), "--rust-out", str(out / "rust"), "--luau-out", str(out / "luau"), *extra],
                       capture_output=True, text=True)
    rep = out / "luau" / "GEN_REPORT.json"
    return p, json.loads(rep.read_text()) if rep.exists() else None


def weird_copy(mutate=None):
    """A temp copy of tools/testdata/weird whose azalea.json went through `mutate(dict)` (None = untouched): (root, rdj dir)."""
    d = Path(tmpdir())
    shutil.copytree(WEIRD / "azalea", d / "azalea")
    (d / "rustdoc").mkdir()
    raw = json.loads((WEIRD / "rustdoc" / "azalea.json").read_text())
    if mutate:
        mutate(raw)
    (d / "rustdoc" / "azalea.json").write_text(json.dumps(raw))
    shutil.copy(WEIRD / "rustdoc" / "azalea.meta", d / "rustdoc" / "azalea.meta")
    return d, d / "rustdoc"


def item_named(raw, name, kind):
    hits = [it for it in raw["index"].values() if it.get("name") == name and rdj.inner_kind(it) == kind]
    assert len(hits) == 1, (name, kind, len(hits))
    return hits[0]


@test
def test_weird_fixture_fresh():
    import rdj_synth
    meta = rdj.read_meta(WEIRD / "rustdoc" / "azalea.json")
    assert meta.get("source_sha1") == rdj.source_sha1(WEIRD / "azalea"), \
        "tools/testdata/weird/azalea sources changed after the JSON was made: re-run tools/make_rustdoc_json.sh (or rdj_synth.py weird)"
    if meta.get("rustc", "").startswith("hand-built"):
        d = tmpdir()
        for p in rdj_synth.write_weird(d):
            assert p.read_bytes() == (WEIRD / "rustdoc" / p.name).read_bytes(), "committed weird JSON differs from tools/rdj_synth.py weird"
    assert rdj.load_dir(WEIRD / "rustdoc").format_version == rdj.FORMAT_TESTED


@test
def test_weird_constructs_are_read():
    import rdj_index
    ix = rdj_index.RdjIndex(WEIRD, WEIRD / "rustdoc")
    ix.load()
    assert not ix.skipped_items, ix.skipped_items
    by = {}
    for m in ix.methods:
        by.setdefault(m.target, {})[m.name] = m
    assert sorted(by["Client"]) == ["bound", "grid", "hidden", "imp", "mutref", "nested", "r#match", "tick", "waits"], sorted(by["Client"])
    assert "gated" not in by["Client"]
    assert sorted(by["EntityRef"]) == ["health", "hunger"] and all("(via macro)" in m.file for m in by["EntityRef"].values())
    c = by["Client"]
    assert c["waits"].is_async and c["tick"].is_async and c["tick"].is_pub and c["tick"].owner == "Tick"
    assert c["bound"].generics and "where T: Into<u32> + Copy" in c["bound"].sig
    assert c["imp"].ret == ("impl", "impl Iterator<Item = u32>") and c["mutref"].params[0][1][0] == "other"
    assert c["nested"].params[0][1][:2] == ("path", "HashMap") and c["grid"].params[0][1][1] == "Grid"
    assert ix.resolve_path("Deep") == "azalea::Deep" and ix.unique_def("Grid").generics
    assert [f[0] for f in ix.defs["Raw"][0].fields] == ["r#type"]
    assert [v["name"] for v in ix.defs["Kind"][0].variants] == ["r#Loop", "Pair"]
    hid = rdj_index.build_impls(ix.rdj, strip_prefix="", hidden="skip")
    assert [n for t, n, how in hid.hidden] == ["hidden"] and "hidden" not in {m.name for m in hid.methods}


@test
def test_weird_generator_finishes():
    root, rdir = weird_copy()
    p, rep = run_generator(root, rdir, Path(root) / "out")
    assert p.returncode == 0 and "Traceback" not in p.stderr and p.stdout.startswith("generated"), (p.stdout, p.stderr)
    assert rep["front_end_skipped"] == []
    assert rep["classes"] and all("skipped" in c for c in rep["classes"])


@test
def test_skipped_items_reported():
    def mutate(raw):
        item_named(raw, "nested", "function")["inner"]["function"]["sig"]["inputs"] = 5
        item_named(raw, "Kind", "enum")["inner"]["enum"]["variants"] = 7
        uses = [it for it in raw["index"].values() if rdj.inner_kind(it) == "use" and (it["inner"]["use"].get("name") == "DeepAlias")]
        uses[0]["inner"]["use"] = 5
    root, rdir = weird_copy(mutate)
    p, rep = run_generator(root, rdir, Path(root) / "out")
    assert p.returncode == 0 and "Traceback" not in p.stderr and p.stdout.startswith("generated"), (p.stdout, p.stderr)
    items = rep["front_end_skipped"]
    assert len(items) == 3, items
    by = {it["subject"]: it for it in items}
    assert sorted(by) == ["azalea::Client::nested", "azalea::Kind", "azalea::inner::DeepAlias"] or \
        any(k.startswith("azalea#") or k.endswith("DeepAlias") for k in by), sorted(by)
    assert all(it["why"] for it in items)
    generated = {n for c in rep["classes"] for n in c["generated"]}
    assert "nested" not in generated and not any(sk["name"] == "nested" for c in rep["classes"] for sk in c["skipped"])
    assert "waits" in generated


@test
def test_dropped_variants_reported_per_variant():
    import rdj_index

    class C:
        name = "azalea"

        def item(self, i):
            return None if i in (7, 8) else {"name": "V%d" % i, "visibility": "default", "attrs": [], "docs": None,
                                              "inner": {"variant": {"kind": "plain", "discriminant": None}}}
    skips, dropped = [], []
    out = rdj_index._variants(C(), {"variants": [5, 7, 6, 8]}, skips, "azalea::Kind", dropped)
    assert [v["name"] for v in out] == ["V5", "V6"] and dropped == ["variant #7", "variant #8"], (out, dropped)
    assert [p for p, _ in skips] == ["azalea::Kind::variant #7", "azalea::Kind::variant #8"], skips
    assert all("not in the JSON index" in why and "--document-hidden-items" in why for _, why in skips), skips
    assert rdj_index._variants(C(), {"variants": [7]}) == []

    root, rdir = weird_copy(lambda raw: raw["index"].pop("22"))
    p, rep = run_generator(root, rdir, Path(root) / "out")
    assert p.returncode == 0 and "Traceback" not in p.stderr, p.stderr
    assert any(it["subject"] == "azalea::Kind::variant #22" and it["why"].startswith("variant dropped: not in the JSON index")
               for it in rep["front_end_skipped"]), rep["front_end_skipped"]


@test
def test_tagged_enum_with_dropped_variant_is_reported():
    import rdj_index

    g = generator()

    def mapper(mutate):
        root, rdir = weird_copy(mutate)
        ix = rdj_index.RdjIndex(root, rdir)
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            ix.load()
        gen_ = g.Generator(ix)
        gen_.m.cur_class = "Client"
        gen_.m.map_ty(("path", "Kind", ()), "ret")
        return gen_.m
    m = mapper(None)
    assert "Kind" in m.tagged and m.enum_notes == [], m.enum_notes
    m = mapper(lambda raw: raw["index"].pop("19"))
    assert "Kind" in m.tagged and [v["name"] for v in m.tagged["Kind"]["variants"]] == ["Pair"], m.tagged
    assert len(m.enum_notes) == 1 and m.enum_notes[0].startswith("`Kind`: 1 of 2 variants emitted, missing variant #19"), m.enum_notes
    assert "empty table" in m.enum_notes[0], m.enum_notes
    m = mapper(lambda raw: raw["index"].pop("22"))
    assert "Kind" in m.enums and "Kind" not in m.tagged and "1 of 2 variants emitted" in m.enum_notes[0], (m.enums, m.enum_notes)

    def all_gone(raw):
        raw["index"].pop("19")
        raw["index"].pop("22")
    try:
        mapper(all_gone)
        raise AssertionError("an enum without any readable variant must be skipped")
    except g.Skip as e:
        assert "has no variants (2 not in the JSON index)" in e.reason, e.reason


@test
def test_dropped_variant_warning_on_generator_stderr():


    import rdj_synth
    d = Path(tmpdir())
    shutil.copytree(FAKE_CRATE, d / "azalea")
    (d / "rustdoc").mkdir()
    raw = json.loads((FIXTURE / "azalea.json").read_text())
    east = item_named(raw, "East", "variant")
    del raw["index"][next(k for k, v in raw["index"].items() if v is east)]
    (d / "rustdoc" / "azalea.json").write_text(json.dumps(raw))
    shutil.copy(FIXTURE / "azalea.meta", d / "rustdoc" / "azalea.meta")
    p, rep = run_generator(d, d / "rustdoc", d / "out")
    assert p.returncode == 0 and "Traceback" not in p.stderr, p.stderr
    warns = [ln for ln in p.stderr.splitlines() if ln.startswith("warning: enum `Direction`")]
    assert len(warns) == 1 and "5 of 6 variants emitted" in warns[0], p.stderr
    assert any(n.startswith("`Direction`: 5 of 6 variants emitted") for n in rep["enum_notes"]), rep["enum_notes"]
    assert any("variant dropped: not in the JSON index" in it["why"] for it in rep["front_end_skipped"]), rep["front_end_skipped"]


@test
def test_rdj_hidden_cli_flag_and_report():
    import rdj_index

    def hide(raw):
        item_named(raw, "nested", "function")["attrs"] = [{"other": "#[doc(hidden)]"}]
    root, rdir = weird_copy(hide)
    p, keep = run_generator(root, rdir, Path(root) / "o_keep")
    assert p.returncode == 0 and not any("doc(hidden)" in it["why"] for it in keep["front_end_skipped"]), p.stderr
    p, skip = run_generator(root, rdir, Path(root) / "o_skip", extra=("--rdj-hidden", "skip"))
    assert p.returncode == 0 and "Traceback" not in p.stderr, p.stderr
    assert dict(kind="hidden_fn", subject="Client::nested", why="#[doc(hidden)] fn skipped (--rdj-hidden skip)") in skip["front_end_skipped"], skip["front_end_skipped"]
    p, _ = run_generator(root, rdir, Path(root) / "o_bad", extra=("--rdj-hidden", "maybe"))
    assert p.returncode != 0 and "--rdj-hidden" in p.stderr, p.stderr
    ix = rdj_index.RdjIndex(root, rdir, hidden="skip")
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        ix.load()
    assert ("Client", "nested", "skipped") in ix.hidden_fns, ix.hidden_fns


@test
def test_local_paths_module_and_fn_with_one_path():


    from rdj_synth import Synth
    a, b = Synth("a"), Synth("b")
    mod = b.mod("foo", b.root)
    b.struct("Bar", mod)
    fn = b._add("foo", "function", {"sig": {"inputs": [], "output": None, "is_c_variadic": False}, "generics": b.generics(),
                                    "header": {"is_const": False, "is_unsafe": False, "is_async": False, "abi": "Rust"}, "has_body": True},
                "public", b.root)
    b.paths[fn] = {"crate_id": 0, "path": ["b", "foo"], "kind": "function"}
    assert fn > mod
    as_mod, as_fn = a.foreign("b", "foo", kind="module"), a.foreign("b", "foo", kind="function")
    as_bar = a.foreign("b", "foo", "Bar")
    other = a.foreign("b", "foo", kind="constant")
    r = rdj.Rdj()
    r.crates["a"], r.crates["b"] = a.crate(), b.crate()
    assert r.crates["b"].local_paths()[("b", "foo")] == fn
    assert r.resolve("a", as_mod) == ("b", mod) and r.resolve("a", as_fn) == ("b", fn), (r.resolve("a", as_mod), r.resolve("a", as_fn))
    assert r.resolve("a", as_bar) is not None
    assert r.resolve("a", other) == ("b", fn)
    assert r.crates["b"].local_path(("b", "foo")) == fn and r.crates["b"].local_path(("b", "nope"), "module") is None


@test
def test_explicit_names_shadow_glob_reexports():
    import rdj_index
    from rdj_synth import Synth


    def paths(build):
        a = Synth("azalea")
        ids = build(a)
        r = rdj.Rdj()
        r.crates["azalea"] = a.crate()
        pa = rdj_index.RdjPaths(r)
        return {k: {"::".join(p) for p in v} for k, v in pa.public_paths().items()}, ids

    def own_item(a):
        inner = a.mod("inner", a.root)
        glob = a.struct("Name", inner)
        a.use(a.root, "inner", inner, glob=True)
        return glob, a.struct("Name", a.root)
    got, (glob, own) = paths(own_item)
    assert got[("azalea", own)] == {"azalea::Name"} and got[("azalea", glob)] == {"azalea::inner::Name"}, got

    def explicit_use(a):
        inner, other = a.mod("inner", a.root), a.mod("other", a.root)
        glob, expl = a.struct("Name", inner), a.struct("Name", other)
        a.use(a.root, "inner", inner, glob=True)
        a.use(a.root, "other::Name", expl, name="Name")
        return glob, expl
    got, (glob, expl) = paths(explicit_use)
    assert got[("azalea", expl)] == {"azalea::Name", "azalea::other::Name"} and got[("azalea", glob)] == {"azalea::inner::Name"}, got

    def no_clash(a):
        inner = a.mod("inner", a.root)
        a.use(a.root, "inner", inner, glob=True)
        return a.struct("Only", inner), a.struct("Name", a.root)
    got, (only, _) = paths(no_clash)
    assert got[("azalea", only)] == {"azalea::Only", "azalea::inner::Only"}, got

    def other_namespace(a):
        inner = a.mod("inner", a.root)
        glob = a.struct("Name", inner)
        a.use(a.root, "inner", inner, glob=True)
        fn = a._add("Name", "function", {"sig": {"inputs": [], "output": None, "is_c_variadic": False}, "generics": a.generics(),
                                         "header": {"is_const": False, "is_unsafe": False, "is_async": False, "abi": "Rust"},
                                         "has_body": True}, "public", a.root)
        return glob, fn
    got, (glob, _) = paths(other_namespace)
    assert got[("azalea", glob)] == {"azalea::Name", "azalea::inner::Name"}, got


def upgrade_to_61(raw):
    """What rustc 1.101 nightly (format 61) adds to a format-57 crate JSON: Item.stability/const_stability on every item and
    default_unstable on trait fns / assoc consts / assoc types (all null for non-std crates)."""
    raw["format_version"] = 61
    for it in raw["index"].values():
        it["stability"] = None
        it["const_stability"] = None
        p = rdj.payload(it)
        k = rdj.inner_kind(it)
        if k in ("function", "assoc_const", "assoc_type"):
            p["default_unstable"] = None


@test
def test_format_61_same_output_as_57():
    out = {}
    for tag, mutate in (("57", None), ("61", upgrade_to_61)):
        root, rdir = weird_copy(mutate)
        o = Path(root) / "out"
        p, rep = run_generator(root, rdir, o)
        assert p.returncode == 0 and rep is not None, p.stderr
        out[tag] = {f.name: f.read_text() for d in ("rust", "luau") for f in sorted((o / d).iterdir()) if f.is_file()}
    assert out["57"].keys() == out["61"].keys() and out["57"]
    for name, text in out["57"].items():
        t61 = out["61"][name]
        strip = lambda x: "\n".join(l for l in x.splitlines() if "@generated" not in l and "rdj_selftest_" not in l)
        text, t61 = strip(text.replace("format_version 57", "format_version N")), strip(t61.replace("format_version 61", "format_version N"))
        assert text == t61, f"{name} differs between format 57 and 61"


@test
def test_format_version_error_at_the_cli():
    def mutate(raw):
        raw["format_version"] = 99
    root, rdir = weird_copy(mutate)
    (rdir / "azalea.meta").write_text("rustc: rustc 9.99.0 (abcdef 2031-01-01)\nformat_version: 99\nprivate_items: 1\n")
    p, rep = run_generator(root, rdir, Path(root) / "out")
    lines = p.stderr.strip().splitlines()
    assert p.returncode != 0 and len(lines) == 1 and lines[0].startswith("error: "), p.stderr
    assert "format_version 99" in lines[0] and "rustc 9.99.0" in lines[0] and "accepted range 57-61" in lines[0], lines[0]
    assert rep is None and p.stdout == ""


def _mutate(rng, raw, n):
    """Drop `n` random fields: keys of items, of their `inner` payload (one level down, too) and of `paths` entries."""
    items = list(raw["index"].values()) + list(raw["paths"].values())
    for _ in range(n):
        d = rng.choice(items)
        for _ in range(rng.choice((1, 1, 2, 3))):
            keys = [k for k in d if not (d is raw and k in rdj.TOP_KEYS)]
            sub = [k for k in keys if isinstance(d[k], dict) and d[k]]
            if sub and rng.random() < 0.6:
                d = d[rng.choice(sub)]
            else:
                break
        if d:
            del d[rng.choice(sorted(d))]


@test
def test_mutation_never_crashes():
    import random
    rng = random.Random(1234)
    base = json.loads((FIXTURE / "azalea.json").read_text())
    fake = ROOT / "harness" / "fake"
    d = Path(tmpdir())
    (d / "rdj").mkdir()
    shutil.copy(FIXTURE / "azalea.meta", d / "rdj" / "azalea.meta")
    skipped = clean = 0
    for i in range(24):
        raw = json.loads(json.dumps(base))
        _mutate(rng, raw, rng.choice((3, 12, 40, 150)))
        (d / "rdj" / "azalea.json").write_text(json.dumps(raw))
        p, rep = run_generator(fake, d / "rdj", d / f"out{i}")
        err = [ln for ln in p.stderr.strip().splitlines() if not ln.startswith("warning: ")]
        assert "Traceback" not in p.stderr, f"mutation #{i} (seed 1234) crashed:\n{p.stderr[-600:]}"
        if p.returncode == 0:
            assert p.stdout.startswith("generated") and rep, f"mutation #{i}: {p.stdout!r}"
            clean += 1
            skipped += bool(rep["front_end_skipped"])
        else:
            assert len(err) == 1 and err[0].startswith("error: "), f"mutation #{i}: expected a one-line error, got:\n{p.stderr[-600:]}"
    assert clean >= 20, f"only {clean} of 24 mutated JSONs generated bindings"
    assert skipped >= 1, "no mutation produced a skipped-items entry: the mutations are too tame to prove anything"




@test
def test_config_toml_schema_errors():
    import luaxite_gen as g
    base = (ROOT / "bindgen.toml").read_text()
    cfg = g.load_config()
    assert sorted(cfg) == sorted(["DENY_METHODS", "PATH_OVERRIDES", "RENAMES", "HANDWRITTEN_GOALS", "CLASSES", "EVENT_ARG_NAMES",
                                  "HIDDEN_EVENTS", "GOAL_PARAM_NAMES", "SCALAR", "RECORDS", "ACCESSORS", "EXTRA_EVENTS", "EXTRA_EVENT_PAYLOADS", "HAND_CLASSES", "HAND_GLOBALS"])
    assert cfg["CLASSES"]["Client"]["renames"] is cfg["RENAMES"] and list(cfg["CLASSES"]) == ["Client", "EntityRef"]
    assert all(isinstance(r, tuple) and len(r) == 3 for rows in cfg["RECORDS"].values() for r in rows)
    d = Path(tmpdir())

    def bad(text, *needles):
        (d / "c.toml").write_text(text)
        try:
            g.load_config(d / "c.toml")
        except g.ConfigError as e:
            for n in needles:
                assert n in str(e), f"{n!r} not in {e}"
            assert "\n" not in str(e)
            return
        raise AssertionError(f"no ConfigError for {needles}")

    bad(base.replace('luau = "Bot"', "luau = 5"), "classes.Client.luau", "expected str, got int")
    bad(base.replace("emit = true", 'emit = "yes"', 1), "classes.Client.emit", "expected bool")
    bad(base.replace("[renames]", "[renamez]"), "unknown key `renamez`")
    bad(base.replace("[hidden_events]", "[xx]").replace("[xx]", "[hidden_events_]"), "unknown key `hidden_events_`")
    bad(base.replace('update = "Fires', "update = 5 #", 1), "extra_events.update", "expected str")
    bad(base.replace("[extra_events]", ""), "missing key `extra_events`")
    assert cfg["EXTRA_EVENT_PAYLOADS"] == {"packet": "ClientboundPacket"} and "packet" in cfg["EXTRA_EVENTS"]
    bad(base.replace('packet = "ClientboundPacket"', 'nothere = "ClientboundPacket"'), "extra_event_payloads.nothere", "not listed in [extra_events]")
    bad(base.replace('packet = "ClientboundPacket"', 'packet = "Foo"'), "extra_event_payloads.packet", "unknown payload type")
    bad(base.replace('packet = "ClientboundPacket"', "packet = 5"), "extra_event_payloads.packet", "expected str")
    (d / "c.toml").write_text(base.replace("[extra_event_payloads]", "[x]").replace('packet = "ClientboundPacket"', "").replace("[x]", ""))
    assert g.load_config(d / "c.toml")["EXTRA_EVENT_PAYLOADS"] == {}
    bad(base.replace('World = "The bot', "World = 5 #", 1), "hand_classes.World", "expected str")
    bad(base.replace("[hand_classes]", ""), "missing key `hand_classes`")
    assert list(cfg["HAND_CLASSES"]) == ["World", "Goal", "GoalLib", "Swarm", "AzaleaLib", "ProcessLib"] and cfg["HAND_GLOBALS"] == {"goal": "GoalLib", "azalea": "AzaleaLib", "process": "ProcessLib"}
    bad(base.replace('goal = "GoalLib"', "goal = 5"), "hand_globals.goal", "expected str")
    bad(base.replace("[hand_globals]", ""), "missing key `hand_globals`")
    bad(base.replace('goto_block_pos = "goto"', "goto_block_pos = 3"), "renames.goto_block_pos", "expected str")
    bad(base.replace('renames = "@renames"', 'renames = "@other"'), "classes.Client.renames", "@renames")
    bad(base.replace('    ["latency", "number", "v.latency"],', '    ["latency", "number"],'), "records.PlayerInfo[2]", "expected 3 strings")
    bad(base.replace('rust = "LuaClient"\n', ""), "classes.Client.rust", "missing")
    bad(base.replace('["x_rot", "number", "v.x_rot()"],', '["x_rot", "number"],'), "accessors.LookDirection.getters[1]", "expected 3 strings")
    bad(base.replace('fields = ["base"]', 'fields = [1]'), "accessors.AttributeInstance.fields[0]", "expected str")
    bad(base.replace('fields = ["uuid", "name"]', 'fieldz = ["uuid"]'), "accessors.GameProfile.fieldz", "unknown")
    bad(base + '\n[accessors.PlayerInfo]\nfields = ["x"]\n', "accessors.PlayerInfo", "also listed in [records]")
    bad(base + '\n[accessors.Empty]\n', "accessors.Empty", "needs `fields` or `getters`")
    bad(base.replace("fallible = true", "fallible = 1", 1), "scalar.Uuid.fallible", "expected bool")
    bad(base.replace("deny_methods = []", 'deny_methods = [1]'), "deny_methods[0]")
    bad(base.replace("deny_methods = []", ""), "missing key `deny_methods`")
    bad(base + "\n[[", "not valid TOML")
    bad(base.replace('doc = "The `bot` global', 'docs = "The `bot` global', 1), "classes.Client.docs", "unknown")
    try:
        g.load_config(d / "nope.toml")
    except g.ConfigError as e:
        assert "cannot read" in str(e)
    else:
        raise AssertionError("missing file")


@test
def test_config_flag_and_builtin_defaults():
    """`--config PATH` (default <root>/bindgen.toml): same tables as the default; a missing default file = built-in empty
    tables; an explicit missing/invalid PATH is one `error: <file>: ..` line (no traceback)."""
    import subprocess
    import luaxite_gen as g
    assert g.CONFIG_PATH == ROOT / "bindgen.toml" and g.CONFIG_PATH.is_file()
    saved = g.CONFIG_PATH
    try:
        g.CONFIG_PATH = Path(tmpdir()) / "absent.toml"
        cfg = g.load_config()
        assert cfg["CLASSES"] == {} and cfg["RECORDS"] == {} and cfg["DENY_METHODS"] == set() and cfg["EXTRA_EVENT_PAYLOADS"] == {}
        assert sorted(cfg) == sorted(saved_keys := g.load_config(saved)), sorted(set(saved_keys) ^ set(cfg))
        try:
            g.load_config(g.CONFIG_PATH)
        except g.ConfigError as e:
            assert "cannot read" in str(e)
        else:
            raise AssertionError("explicit missing config accepted")
    finally:
        g.CONFIG_PATH = saved
    tmp = Path(tmpdir())

    def run(*a):
        out = tmp / f"o{len(list(tmp.iterdir()))}"
        (out / "rust").mkdir(parents=True)
        for f in (ROOT / "harness" / "src" / "luau").glob("extra_*.rs"):
            shutil.copy(f, out / "rust")
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "luaxite_gen.py"), "--azalea", str(ROOT / "harness" / "fake"),
                            "--rustdoc", str(ROOT / "harness/fake/rustdoc"), "--rust-out", str(out / "rust"), "--luau-out", str(out / "luau"), *a],
                           capture_output=True, text=True)
        return p, out

    p0, o0 = run()
    p1, o1 = run("--config", str(ROOT / "bindgen.toml"))
    assert p0.returncode == 0 and p1.returncode == 0, p0.stderr + p1.stderr
    for f in ("rust/gen_client.rs", "rust/gen_types.rs", "rust/gen_events.rs", "luau/azalea.d.luau", "luau/GEN_REPORT.json", "luau/GEN_REPORT.md"):
        assert (o0 / f).read_bytes() == (o1 / f).read_bytes(), f
    (tmp / "bad.toml").write_text("deny_methods = [\n")
    (tmp / "keys.toml").write_text((ROOT / "bindgen.toml").read_text().replace("[renames]", "[renamez]"))
    for name, needle in (("nope.toml", "cannot read"), ("bad.toml", "not valid TOML"), ("keys.toml", "unknown key `renamez`")):
        p, _ = run("--config", str(tmp / name))
        err = p.stderr.strip().splitlines()
        assert p.returncode == 1 and len(err) == 1 and err[0].startswith(f"error: {name}: ") and needle in err[0], (name, p.stderr)
    p, o = run("--config", str(ROOT / "bindgen.toml"), "--rdj-hidden", "skip")
    assert p.returncode == 0


def toy_project(tmp: Path):
    """A one-crate project root (`toy`, no azalea): Counter (2 pub methods + a private one + a trait impl), Mode (enum, 1 pub method),
    Pair<T> (generic), Plain (no methods). Returns (root dir with toy/src/lib.rs, rustdoc dir)."""
    from rdj_synth import Synth
    S = Synth.span
    toy = Synth("toy")
    u32_, str_ = {"primitive": "u32"}, {"primitive": "str"}
    sr = {"borrowed_ref": {"lifetime": None, "is_mutable": False, "type": {"generic": "Self"}}}
    counter = toy.struct("Counter", toy.root, fields=[("n", u32_, "default")])
    mode = toy.enum("Mode", toy.root, [("On", None), ("Off", None)])
    toy.struct("Pair", toy.root, fields=None)
    toy.index[toy.nid - 1]["inner"]["struct"]["generics"]["params"] = [Synth.ty_param("T")]
    toy.struct("Plain", toy.root, fields=None)
    f = "toy/src/lib.rs"
    ic = toy.impl_(Synth.path_type("Counter", counter), span=S(5, 1, [12, 2], file=f))
    toy.fn("get", ic, [("self", sr)], u32_, doc="Current value.", span=S(6, file=f))
    toy.fn("add", ic, [("self", sr), ("by", u32_)], u32_, span=S(7, file=f))
    toy.fn("secret", ic, [("self", sr)], u32_, vis="default", span=S(8, file=f))
    it = toy.impl_(Synth.path_type("Counter", counter), trait=("Default", 0), span=S(14, 1, [16, 2], file=f))
    toy.fn("default", it, [], Synth.path_type("Counter", counter), vis="default", span=S(15, file=f))
    im = toy.impl_(Synth.path_type("Mode", mode), span=S(18, 1, [20, 2], file=f))
    toy.fn("label", im, [("self", sr)], {"resolved_path": {"path": "String", "id": 0, "args": None}}, span=S(19, file=f))
    toy.free_fn("double", toy.root, [("x", u32_)], u32_, doc="Twice x.")
    toy.free_fn("hidden_fn", toy.root, [("x", u32_)], u32_, vis="default")
    toy.free_fn("later", toy.root, [], None, is_async=True)
    root = tmp / "bind"
    src = root / "toy" / "src"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text("pub struct Counter { n: u32 }\n")
    (root / "toy" / "Cargo.toml").write_text('[package]\nname = "toy"\nversion = "0.1.0"\n')
    d = tmp / "rdj"
    d.mkdir()
    (d / "toy.json").write_text(json.dumps(toy.raw()))
    (d / "toy.meta").write_text(f"rustc: hand-built\nformat_version: {rdj.FORMAT_TESTED}\nprivate_items: 1\nsource_sha1: {rdj.source_sha1(root / 'toy')}\n")
    return root, d


@test
def test_generic_class_discovery_on_toy_crate():
    """No `[classes]` configured and no `azalea` crate: pub non-generic structs/enums with pub inherent methods become classes
    (named after the type, `Lua<Type>` struct), the rest is listed; the azalea config binds exactly its own classes."""
    import luaxite_gen as g
    import rdj_index as ri
    root, d = toy_project(Path(tmpdir()))
    saved = dict(g.CLASSES)
    try:
        g.CLASSES.clear()
        ix = ri.RdjIndex(root, d)
        ix.load()
        assert sorted(ix.discovered) == ["@toy", "Counter", "Mode"], ix.discovered
        assert ix.discovered["Counter"]["rust"] == "LuaCounter" and ix.discovered["Counter"]["luau"] == "Counter"
        assert sorted((m.target, m.name) for m in ix.methods) == [("@toy", "double"), ("@toy", "later"), ("Counter", "add"), ("Counter", "get"), ("Mode", "label")]
        assert ix.discovered["@toy"]["free"] and ix.discovered["@toy"]["luau"] == "toy"
        assert ("Pair", "generic type") in ix.discover_skipped and not any(n == "Plain" for n, _ in ix.discover_skipped)
        assert ix.resolve_path("Counter") == "toy::Counter" and "hand-built" in ix.frontend_label
        notes = "\n".join(ix.report_lines())
        assert "type `Pair`: not bound as a class (generic type)" in notes and "Counter" not in notes
        g.CLASSES.update(ix.discovered)
        gen = g.Generator(ix)
        gen.build()
        assert sorted(w.name for w in gen.classes["Counter"].wrappers) == ["add", "get"]
        assert [w.name for w in gen.classes["@toy"].wrappers] == ["double"] and [r[2] for r in gen.classes["@toy"].skipped] == ["async free fn"]
        assert [w.name for w in gen.classes["Mode"].wrappers] == ["label"]
    finally:
        g.CLASSES.clear()
        g.CLASSES.update(saved)

    assert "Client" in g.CLASSES
    ix2 = ri.RdjIndex(root, d)
    ix2.load()
    assert ix2.discovered == {} and ix2.discover_skipped == [] and ix2.methods == []


@test
def test_generator_cli_on_toy_crate():
    """The CLI end to end on a crate that is not azalea, with a config without `[classes]`: classes + a global table of the free fns,
    no events/packets/ecs files, no `bot`, no azalea imports."""
    import subprocess
    tmp = Path(tmpdir())
    root, d = toy_project(tmp)
    cfg = tmp / "empty.toml"
    cfg.write_text("deny_methods = []\n" + "".join(f"[{k}]\n" for k in ("classes", "scalar", "records", "accessors", "path_overrides", "renames",
                   "handwritten_goals", "event_arg_names", "hidden_events", "goal_param_names", "extra_events", "hand_classes", "hand_globals")))
    out = tmp / "out"
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "luaxite_gen.py"), "--azalea", str(root), "--rustdoc", str(d), "--rust-out", str(out / "rs"),
                        "--luau-out", str(out / "lu"), "--config", str(cfg)], capture_output=True, text=True)
    assert p.returncode == 0 and "Traceback" not in p.stderr, p.stderr
    assert sorted(f.name for f in (out / "rs").iterdir()) == ["gen_client.rs", "gen_types.rs"]
    rs = (out / "rs" / "gen_client.rs").read_text()
    assert "azalea::" not in rs and "Handlers" not in rs and "pub struct LuaCounter" in rs and "inner: toy::Counter" in rs
    assert 'lua.globals().set("toy", t)' in rs and "Ok(toy::double(x))" in rs and "register_toy(lua)?;" in rs
    luau = (out / "lu" / "azalea.d.luau").read_text()
    assert "declare extern type Counter with" in luau and "double: (x: number) -> number," in luau and "declare bot" not in luau
    rep = json.loads((out / "lu" / "GEN_REPORT.json").read_text())
    assert not rep["events"]["enabled"] and any(sk["reason"] == "async free fn" for c in rep["classes"] for sk in c["skipped"]), rep["classes"]
    assert any(it["kind"] == "type" and it["subject"] == "Pair" and it["why"] == "not bound as a class (generic type)" for it in rep["front_end_skipped"])
    p2 = subprocess.run(p.args, capture_output=True, text=True)
    assert p2.returncode == 0 and (out / "rs" / "gen_client.rs").read_text() == rs


@test
def test_format_61_shapes():
    """Shapes of rustdoc-types 0.61.0 (format 61) that the 57 fixture does not contain: unit variants are bare strings
    (`GenericArg::Infer`), `Abi` has no serde rename, `PreciseCapturingArg`, and the structured `Attribute` variants."""
    import rdj_index as ri
    U8 = {"primitive": "u8"}

    for infer in ("infer", {"infer": None}):
        args = {"angle_bracketed": {"args": [infer, {"type": U8}], "constraints": []}}
        assert rdj._render_args(args) == "<_, u8>", infer

        assert rdj.convert_type({"resolved_path": {"path": "Vec", "id": 1, "args": args}}) == ("path", "Vec", [("prim", "u8")])
    assert rdj._render_args("return_type_notation") == ""
    assert rdj.render_type("infer") == "_"

    for abi, text in (("Rust", ""), (None, ""), ({"C": {"unwind": False}}, "C"), ({"C": {"unwind": True}}, "C-unwind"),
                      ({"Cdecl": {"unwind": False}}, "cdecl"), ({"Stdcall": {"unwind": True}}, "stdcall-unwind"),
                      ({"Fastcall": {"unwind": False}}, "fastcall"), ({"Aapcs": {"unwind": False}}, "aapcs"),
                      ({"Win64": {"unwind": False}}, "win64"), ({"SysV64": {"unwind": False}}, "sysv64"),
                      ({"System": {"unwind": True}}, "system-unwind"), ({"Other": "ptx-kernel"}, "ptx-kernel"),
                      ("Cdecl", "cdecl"), ({"a": 1, "b": 2}, "")):
        assert rdj.abi_text(abi) == text, (abi, rdj.abi_text(abi))

    def sig(abi):
        fn = {"name": "f", "visibility": "public", "inner": {"function": {
            "sig": {"inputs": [], "output": None}, "generics": {"params": [], "where_predicates": []},
            "header": {"abi": abi, "is_const": False, "is_async": False, "is_unsafe": False}, "has_body": True}}}
        return ri.fn_sig_text(fn, rdj.payload(fn))
    assert sig("Rust") == "pub fn f()"
    assert sig({"C": {"unwind": True}}) == 'pub extern "C-unwind" fn f()'
    assert sig({"SysV64": {"unwind": False}}) == 'pub extern "sysv64" fn f()'
    assert sig({"Other": "ptx-kernel"}) == 'pub extern "ptx-kernel" fn f()'

    assert rdj._render_bounds([{"use": [{"lifetime": "'a"}, {"param": "T"}]}]) == "use<'a, T>"
    assert rdj.render_type({"impl_trait": [{"use": [{"param": "T"}]}]}) == "impl use<T>"

    at = lambda *a: rdj.attr_texts({"attrs": list(a)})
    assert at("non_exhaustive", "macro_export", "no_mangle", "automatically_derived") == ["#[non_exhaustive]", "#[macro_export]", "#[no_mangle]"]
    assert at({"must_use": {"reason": None}}) == ["#[must_use]"]
    assert at({"must_use": {"reason": "use the \"result\""}}) == ['#[must_use = "use the \\"result\\""]']
    assert at({"export_name": "ex"}, {"link_section": ".sec"}) == ['#[export_name = "ex"]', '#[link_section = ".sec"]']
    assert at({"target_feature": {"enable": ["avx2", "fma"]}}) == ['#[target_feature(enable = "avx2", enable = "fma")]']
    rep = lambda kind, align=None, packed=None, int=None: at({"repr": {"kind": kind, "align": align, "packed": packed, "int": int}})
    assert rep("c") == ["#[repr(C)]"] and rep("transparent") == ["#[repr(transparent)]"] and rep("simd") == ["#[repr(simd)]"]
    assert rep("rust") == ["#[repr(Rust)]"]
    assert rep("c", int="u8") == ["#[repr(C, u8)]"]
    assert rep("rust", align=8) == ["#[repr(align(8))]"] and rep("rust", packed=2) == ["#[repr(packed(2))]"]
    assert rep("c", align=16, int="i32") == ["#[repr(C, i32, align(16))]"]
    assert at({"other": "#[allow(dead_code)]"}, {"other": "#[attr = Inline(Hint)]"}, 7, {"a": 1, "b": 2}, {"brand_new": 1}) == ["#[allow(dead_code)]"]


    class C:
        items = {2: {"name": "x", "visibility": "default", "inner": {"struct_field": U8}},
                 3: {"name": "Plain", "visibility": "default", "attrs": [], "docs": None,
                     "inner": {"variant": {"kind": "plain", "discriminant": None}}}}

        def item(self, i):
            return self.items.get(i)

    def variant(has_stripped):
        C.items[4] = {"name": "V", "visibility": "default", "attrs": [], "docs": None,
                      "inner": {"variant": {"kind": {"struct": {"fields": [2], "has_stripped_fields": has_stripped}}, "discriminant": None}}}
        return ri._variants(C(), {"variants": [3, 4]})
    assert [v["types"] for v in variant(False)] == [[], [("prim", "u8")]]
    assert [v["types"] for v in variant(True)] == [[], [("prim", "u8"), ("other", "_")]]


def main() -> int:
    failed = 0
    try:
        for t in TESTS:
            try:
                t()
            except Exception as e:
                failed += 1
                tb = traceback.extract_tb(e.__traceback__)[-1]
                print(f"FAIL {t.__name__}: {type(e).__name__}: {e} (line {tb.lineno})")
    finally:
        for d in _cache.get("tmp", []):
            shutil.rmtree(d, ignore_errors=True)
    if failed:
        print(f"rdj_selftest: FAILED ({failed} of {len(TESTS)} tests)")
        return 1
    print(f"rdj_selftest: OK ({len(TESTS)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
