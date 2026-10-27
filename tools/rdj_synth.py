#!/usr/bin/env python3
"""
rdj_synth.py - hand-built rustdoc JSON (stdlib dicts shaped like rustdoc's format 57), for the cases the committed
rustc-made fixtures cannot cover and for sandboxes without rustc.

  Synth            builder for one crate (modules, structs with fields, enums with variants, type aliases, `use` items,
                   foreign items that only exist as `paths` summaries)
  synth_ws2()      the two crates of tools/testdata/ws2 (a -> b), written down exactly as the sources there read
  synth_weird()    the crate of tools/testdata/weird (nested generics, impl Trait, where clauses, async fn in trait, macro-made
                   fns, re-export chain + glob, const generics, raw identifiers, &mut, #[doc(hidden)]; the cfg-gated fn is
                   absent, as rustdoc leaves it out when the feature is off)
  python3 tools/rdj_synth.py weird [OUT_DIR]   same for tools/testdata/weird/rustdoc/azalea.json
  python3 tools/rdj_synth.py ws2 [OUT_DIR]   write tools/testdata/ws2/rustdoc/{a,b}.json + .meta (hand-built stand-ins for
                   what `sh tools/make_rustdoc_json.sh tools/testdata/ws2/a OUT` would make with a rustc; the .meta says so)

The selftest (tools/rdj_selftest.py) checks the committed ws2 JSON is exactly this output while its .meta says "hand-built",
and only that its source_sha1 matches the sources once real rustdoc output replaced it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import rdj  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WS2 = ROOT / "tools" / "testdata" / "ws2"
WEIRD = ROOT / "tools" / "testdata" / "weird"
HAND_BUILT = "hand-built by tools/rdj_synth.py (no rustc in the sandbox)"


class Synth:
    """A hand-built crate JSON: modules, structs, enums, `use` items, foreign items in `paths`. The fake is one crate and
    the sandbox has no rustc to document more, so the cross-crate / glob / macro cases are tested on these."""

    def __init__(self, name, version=None):
        self.name, self.index, self.paths, self.ext, self.nid, self.version = name, {}, {}, {}, 1, version
        self.root = self._add(name, "module", {"is_crate": True, "items": [], "is_stripped": False}, "public", None)

    def _add(self, name, kind, payload, vis, parent):
        i = self.nid
        self.nid += 1
        self.index[i] = {"id": i, "crate_id": 0, "name": name, "span": None, "visibility": vis, "docs": None, "links": {},
                         "attrs": [], "deprecation": None, "inner": {kind: payload}}
        if parent is not None:
            self.index[parent]["inner"]["module"]["items"].append(i)
        if name and kind in ("module", "struct", "enum", "trait", "type_alias"):
            self.paths[i] = {"crate_id": 0, "path": (self.paths[parent]["path"] if parent is not None else []) + [name], "kind": kind}
        return i

    def mod(self, name, parent, vis="public"):
        return self._add(name, "module", {"is_crate": False, "items": [], "is_stripped": False}, vis, parent)

    def struct(self, name, parent, vis="public", fields=None, doc=None):
        """`fields`: None = unit struct, [(name, Type, vis)] = plain struct, with names `"0"`, `"1"` = tuple struct."""
        generics = {"params": [], "where_predicates": []}
        if fields is None:
            kind = "unit"
            ids = []
        else:
            ids = [self._add(n, "struct_field", t, v, None) for n, t, v in fields]
            kind = {"tuple": ids} if fields and all(n.isdigit() for n, _, _ in fields) else {"plain": {"fields": ids, "has_stripped_fields": False}}
        sid = self._add(name, "struct", {"kind": kind, "generics": generics, "impls": []}, vis, parent)
        self.index[sid]["docs"] = doc
        return sid

    def enum(self, name, parent, variants, vis="public", doc=None):
        """`variants`: [(name, None | [Type, ..] | [(field, Type), ..])]: unit, tuple (list of types), struct (list of pairs)."""
        vids = []
        eid = self._add(name, "enum", {"generics": {"params": [], "where_predicates": []}, "has_stripped_variants": False,
                                       "variants": vids, "impls": []}, vis, parent)
        self.index[eid]["docs"] = doc
        for vname, spec in variants:
            if spec is None:
                kind = "plain"
            elif spec and isinstance(spec[0], tuple):
                kind = {"struct": {"fields": [self._add(fn, "struct_field", ft, "default", None) for fn, ft in spec], "has_stripped_fields": False}}
            else:
                kind = {"tuple": [self._add(str(k), "struct_field", ft, "default", None) for k, ft in enumerate(spec)]}
            v = self._add(vname, "variant", {"kind": kind, "discriminant": None}, "default", None)
            vids.append(v)
            self.paths[v] = {"crate_id": 0, "path": self.paths[eid]["path"] + [vname], "kind": "variant"}
        return eid

    def type_alias(self, name, parent, ty, vis="public"):
        return self._add(name, "type_alias", {"type": ty, "generics": {"params": [], "where_predicates": []}}, vis, parent)

    def foreign(self, crate, *path, kind="struct"):
        """A `paths` entry for an item of another crate: its id (not in `index`)."""
        cid = next((k for k, v in self.ext.items() if v["name"] == crate), None)
        if cid is None:
            cid = len(self.ext) + 1
            self.ext[cid] = {"name": crate, "html_root_url": None, "path": f"/synth/lib{crate}.rmeta"}
        i = self.nid
        self.nid += 1
        self.paths[i] = {"crate_id": cid, "path": [crate, *path], "kind": kind}
        return i

    def use(self, parent, source, target, name=None, glob=False, vis="public"):
        return self._add(None, "use", {"source": source, "name": name or source.split("::")[-1], "id": target, "is_glob": glob}, vis, parent)

    @staticmethod
    def path_type(path, id, args=None):
        """`resolved_path` Type; `args` = list of Types for `Path<..>`."""
        a = {"angle_bracketed": {"args": [t if "const" in t else {"type": t} for t in args], "constraints": []}} if args else None
        return {"resolved_path": {"path": path, "id": id, "args": a}}

    @staticmethod
    def const_arg(expr):
        """A const generic argument (`Grid<3>`): a GenericArg, not a Type."""
        return {"const": {"expr": expr, "value": expr, "is_literal": True}}

    # ---- impls, fns, traits (slice 10)
    @staticmethod
    def span(line, col=5, end=None, file="azalea/src/lib.rs"):
        return {"filename": file, "begin": [line, col], "end": end or [line, col + 20]}

    @staticmethod
    def generics(params=None, where=None):
        return {"params": params or [], "where_predicates": where or []}

    @staticmethod
    def ty_param(name, bounds=None, synthetic=False):
        return {"name": name, "kind": {"type": {"bounds": bounds or [], "default": None, "is_synthetic": synthetic}}}

    @staticmethod
    def const_param(name, ty, default=None):
        return {"name": name, "kind": {"const": {"type": ty, "default": default}}}

    @staticmethod
    def trait_bound(path, id=0, args=None, assoc=None):
        """`assoc` = {name: Type} for `Iterator<Item = u32>`."""
        cons = [{"name": n, "args": None, "binding": {"equality": {"type": t}}} for n, t in (assoc or {}).items()]
        a = {"angle_bracketed": {"args": [{"type": t} for t in args or []], "constraints": cons}} if args or cons else None
        return {"trait_bound": {"trait": {"path": path, "id": id, "args": a}, "generic_params": [], "modifier": "none"}}

    SELF_REF = {"borrowed_ref": {"lifetime": None, "is_mutable": False, "type": {"generic": "Self"}}}

    def fn(self, name, owner, inputs, output=None, vis="public", generics=None, is_async=False, doc=None, attrs=None, span=None):
        """A function item added to `owner`'s items (an impl or a trait from `impl_` / `trait_`): `inputs` = [(name, Type)]."""
        fid = self._add(name, "function", {"sig": {"inputs": [list(i) for i in inputs], "output": output, "is_c_variadic": False},
                                           "generics": generics or self.generics(),
                                           "header": {"is_const": False, "is_unsafe": False, "is_async": is_async, "abi": "Rust"},
                                           "has_body": True}, vis, None)
        it = self.index[fid]
        it["docs"], it["attrs"], it["span"] = doc, attrs or [], span
        (self.index[owner]["inner"].get("impl") or self.index[owner]["inner"]["trait"])["items"].append(fid)
        return fid

    def free_fn(self, name, parent, inputs, output=None, vis="public", doc=None, is_async=False):
        """A free function item in module `parent`: `inputs` = [(name, Type)]."""
        fid = self._add(name, "function", {"sig": {"inputs": [list(i) for i in inputs], "output": output, "is_c_variadic": False},
                                           "generics": self.generics(),
                                           "header": {"is_const": False, "is_unsafe": False, "is_async": is_async, "abi": "Rust"},
                                           "has_body": True}, vis, parent)
        self.index[fid]["docs"] = doc
        return fid

    def impl_(self, target, trait=None, span=None, generics=None):
        """An `impl` item for the Type `target` (`trait` = (path, id) for `impl Trait for T`); not in any module's items."""
        tr = {"path": trait[0], "id": trait[1], "args": None} if trait else None
        iid = self._add(None, "impl", {"is_unsafe": False, "generics": generics or self.generics(), "provided_trait_methods": [],
                                       "trait": tr, "for": target, "items": [], "is_negative": False, "is_synthetic": False,
                                       "blanket_impl": None}, "default", None)
        self.index[iid]["span"] = span
        return iid

    def trait_(self, name, parent, vis="public"):
        return self._add(name, "trait", {"is_auto": False, "is_unsafe": False, "is_dyn_compatible": True, "items": [],
                                         "generics": self.generics(), "bounds": [], "implementations": []}, vis, parent)

    def raw(self) -> dict:
        return {"root": self.root, "crate_version": self.version, "includes_private": True,
                "index": {str(k): v for k, v in self.index.items()}, "paths": {str(k): v for k, v in self.paths.items()},
                "external_crates": {str(k): v for k, v in self.ext.items()},
                "target": {"triple": "x86_64-unknown-linux-gnu", "target_features": []}, "format_version": rdj.FORMAT_TESTED}

    def crate(self):
        raw = self.raw()
        raw["target"]["triple"] = "x"
        raw["crate_version"] = None
        return rdj.Crate(Path(f"{self.name}.json"), raw, {})


def synth_ws2() -> dict:
    """{crate name: Synth} for tools/testdata/ws2: `b` defines geom::{Vec3, Dir}, Marker; `a` re-exports and uses them.
    Mirrors b/src/lib.rs and a/src/lib.rs there line for line (ids only exist in the JSON)."""
    b = Synth("b", "0.1.0")
    geom = b.mod("geom", b.root)
    f64_ = {"primitive": "f64"}
    vec3 = b.struct("Vec3", geom, fields=[("x", f64_, "public"), ("y", f64_, "public"), ("z", f64_, "public")], doc="A point in space.")
    b.enum("Dir", geom, [("North", None), ("Offset", [{"primitive": "i32"}]),
                                ("Pos", [("at", Synth.path_type("Vec3", vec3))])], doc="Where something faces.")
    b.struct("Marker", b.root, doc="A unit marker.")

    a = Synth("a", "0.1.0")
    a_b = a.foreign("b", kind="module")
    a_vec3 = a.foreign("b", "geom", "Vec3")
    a_dir = a.foreign("b", "geom", "Dir", kind="enum")
    a_marker = a.foreign("b", "Marker")
    a_north = a.foreign("b", "geom", "Dir", "North", kind="variant")
    a_vec = a.foreign("alloc", "vec", "Vec")                               # std: no JSON loaded for it
    a.use(a.root, "b", a_b, name="base")
    a.use(a.root, "b::geom::Dir::North", a_north, name="North")
    a.use(a.root, "b::geom::Vec3", a_vec3, name="Vec3")
    a.struct("Bot", a.root, fields=[("pos", Synth.path_type("Vec3", a_vec3), "public"),
                                    ("facing", Synth.path_type("b::geom::Dir", a_dir), "public"),
                                    ("marks", Synth.path_type("Vec", a_vec, [Synth.path_type("b::Marker", a_marker)]), "public")],
             doc="Uses three types of `b`.")
    a.enum("Cmd", a.root, [("Go", [Synth.path_type("Vec3", a_vec3)]), ("Face", [Synth.path_type("b::geom::Dir", a_dir)])])
    a.type_alias("Facing", a.root, Synth.path_type("b::geom::Dir", a_dir))
    return {"a": a, "b": b}


def write_ws2(out) -> list:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, syn in synth_ws2().items():
        (out / f"{name}.json").write_text(json.dumps(syn.raw(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        (out / f"{name}.meta").write_text("\n".join([f"rustc: {HAND_BUILT}", f"format_version: {rdj.FORMAT_TESTED}", "private_items: 1",
                                                      f"source_sha1: {rdj.source_sha1(WS2 / name)}"]) + "\n", encoding="utf-8")
        written.append(out / f"{name}.json")
    return written


def synth_weird() -> Synth:
    """The crate of tools/testdata/weird (azalea/src/lib.rs there, line numbers = that file's): what a JSON reader trips over."""
    P, G, S = Synth.path_type, Synth.generics, Synth.span
    u8, u16, u32_, usize_ = ({"primitive": n} for n in ("u8", "u16", "u32", "usize"))
    a = Synth("azalea", "0.0.0")
    # re-export chain + glob: inner::deep::Deep, inner::DeepAlias (renamed), chain::* (glob), root `pub use chain::Deep`
    inner = a.mod("inner", a.root)
    deep = a.mod("deep", inner)
    deep_s = a.struct("Deep", deep, fields=[("n", u32_, "public")], doc="Reached through a re-export chain and a glob.")
    a.use(inner, "self::deep::Deep", deep_s, name="DeepAlias")
    chain = a.mod("chain", a.root)
    a.use(chain, "crate::inner::deep", deep, name="deep", glob=True)
    a.use(a.root, "chain::Deep", deep_s, name="Deep")
    # const generics, raw identifiers
    grid = a.struct("Grid", a.root, fields=[("cells", {"array": {"type": u8, "len": "W"}}, "public")], doc="Const generics.")
    a.index[grid]["inner"]["struct"]["generics"] = G([Synth.const_param("W", usize_), Synth.const_param("H", usize_, "4")])
    a.struct("Raw", a.root, fields=[("r#type", u32_, "public")], doc="Raw identifier field and variant.")
    hm = a.foreign("std", "collections", "hash", "map", "HashMap")
    vec = a.foreign("alloc", "vec", "Vec")
    opt = a.foreign("core", "option", "Option", kind="enum")
    string = a.foreign("alloc", "string", "String")
    nest = P("HashMap", hm, [P("String", string), P("Vec", vec, [P("Option", opt, [{"tuple": [u8, u16]}])])])
    a.enum("Kind", a.root, [("r#Loop", None), ("Pair", [u8, P("HashMap", hm, [P("String", string), P("Vec", vec, [P("Option", opt, [u32_])])])])])
    client = a.struct("Client", a.root)
    entity = a.struct("EntityRef", a.root)
    tick = a.trait_("Tick", a.root)
    a.fn("tick", tick, [("self", Synth.SELF_REF)], u32_, is_async=True, doc="async fn in trait", span=S(33))
    # impl Client
    ic = a.impl_(P("Client", client), span=S(38, 1, [58, 2]))
    sr = Synth.SELF_REF
    a.fn("nested", ic, [("self", sr), ("m", nest)], P("Option", opt, [P("Vec", vec, [u32_])]), doc="nested generics", span=S(40))
    a.fn("imp", ic, [("self", sr), ("f", {"generic": "impl Fn(u32) -> u32 + Send"})],
         {"impl_trait": [Synth.trait_bound("Iterator", 0, None, {"Item": u32_})]}, doc="impl Trait argument and return", span=S(42),
         generics=G([Synth.ty_param("impl Fn(u32) -> u32 + Send", [Synth.trait_bound("Fn"), Synth.trait_bound("Send")], synthetic=True)]))
    a.fn("bound", ic, [("self", sr), ("t", {"generic": "T"})], u32_, doc="where clause", span=S(44),
         generics=G([Synth.ty_param("T")], [{"bound_predicate": {"type": {"generic": "T"}, "generic_params": [],
                                                                  "bounds": [Synth.trait_bound("Into", 0, [u32_]), Synth.trait_bound("Copy")]}}]))
    a.fn("mutref", ic, [("self", sr), ("v", {"borrowed_ref": {"lifetime": None, "is_mutable": True, "type": P("Vec", vec, [u8])}})],
         doc="mutable reference", span=S(46))
    a.fn("r#match", ic, [("self", sr)], u32_, doc="raw identifier method", span=S(48))
    a.fn("grid", ic, [("self", sr), ("g", P("Grid", grid, [Synth.const_arg("3"), Synth.const_arg("4")]))], u32_, doc="const generic argument", span=S(50))
    a.fn("hidden", ic, [("self", sr)], u32_, doc="hidden", attrs=[{"other": "#[doc(hidden)]"}], span=S(55))   # `gated` (cfg feature off) is absent
    a.fn("waits", ic, [("self", sr)], u32_, is_async=True, span=S(57))
    # macro-made impl: every fn has the span of the impl (the macro call site)
    site = S(64, 1, [64, 28])
    ie = a.impl_(P("EntityRef", entity), span=site)
    for n in ("health", "hunger"):
        a.fn(n, ie, [("self", sr)], u32_, span=site)
    it = a.impl_(P("Client", client), trait=("Tick", tick), span=S(66, 1, [68, 2]))
    a.fn("tick", it, [("self", sr)], u32_, vis="default", is_async=True, span=S(67))
    a.enum("Event", a.root, [("Init", None), ("Login", None), ("Tick", None), ("Odd", [nest])], doc=None)
    return a


def write_weird(out) -> list:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "azalea.json").write_text(json.dumps(synth_weird().raw(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "azalea.meta").write_text("\n".join([f"rustc: {HAND_BUILT}", f"format_version: {rdj.FORMAT_TESTED}", "private_items: 1",
                                                f"source_sha1: {rdj.source_sha1(WEIRD / 'azalea')}"]) + "\n", encoding="utf-8")
    return [out / "azalea.json"]


def main(argv) -> int:
    kinds = {"ws2": (write_ws2, WS2), "weird": (write_weird, WEIRD)}
    if not argv or argv[0] not in kinds or len(argv) > 2:
        print("usage: python3 tools/rdj_synth.py ws2|weird [OUT_DIR]   (default tools/testdata/<name>/rustdoc)", file=sys.stderr)
        return 2
    write, base = kinds[argv[0]]
    for p in write(argv[1] if len(argv) > 1 else base / "rustdoc"):
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
