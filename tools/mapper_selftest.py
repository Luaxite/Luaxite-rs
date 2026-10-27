#!/usr/bin/env python3
"""Selftest of the generator's type mapper (container types), stdlib only: `python3 tools/mapper_selftest.py`.

Uses the rustdoc index of harness/fake (harness/fake/rustdoc). Every container the
generator maps must turn into the Luau type and the Rust conversion written here; every one it must refuse must raise `Skip` with the reason.
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import luaxite_gen as g  # noqa: E402
import rdj_index  # noqa: E402

ix = rdj_index.RdjIndex(HERE.parent / "harness" / "fake", HERE.parent / "harness" / "fake" / "rustdoc")
ix.load()
M = g.Mapper(ix)


def P(name, *args):
    return ("path", name, list(args))


def ok(t, role):
    i = M.map_ty(t, role)
    return i, (i.to_lua("x") if i.to_lua else None), (i.from_lua("x") if i.from_lua else None)


def skips(t, role, why):
    try:
        M.map_ty(t, role)
    except g.Skip as e:
        assert why in str(e), f"{g.type_text(t)} ({role}): wanted `{why}`, got `{e}`"
        return
    raise AssertionError(f"{g.type_text(t)} ({role}) should have been skipped (`{why}`)")


def main():
    n = 0
    # return values: HashMap / IndexMap / BTreeMap -> `{ [K]: V }`, converted into a HashMap of Luau values
    for name in g.MAP_TYPES:
        i, to, frm = ok(P(name, P("String"), P("String")), "ret")
        assert i.luau == "{ [string]: string }" and i.rust == "std::collections::HashMap<String, String>", (name, i)
        assert to == "x.into_iter().map(|(k, v)| (k, v)).collect::<std::collections::HashMap<_, _>>()" and frm is None, (name, to, frm)
        n += 1
    # a `Uuid` key is its string form (the scalar's `to`), a numeric key stays a number, a record value is converted
    i, to, _ = ok(P("HashMap", P("Uuid"), P("PlayerInfo")), "ret")
    assert i.luau == "{ [string]: PlayerInfo }" and i.rust == "std::collections::HashMap<String, LuaPlayerInfo>", i
    assert to == "x.into_iter().map(|(k, v)| (k.to_string(), LuaPlayerInfo(v))).collect::<std::collections::HashMap<_, _>>()", to
    i, to, _ = ok(P("BTreeMap", ("prim", "u32"), P("String")), "ret")
    assert i.luau == "{ [number]: string }", i
    n += 2
    # parameters: HashMap / BTreeMap rebuilt from what Luau gave
    i, _, frm = ok(P("BTreeMap", ("prim", "u32"), P("String")), "param")
    assert frm == "x.into_iter().map(|(k, v)| (k, v)).collect::<std::collections::BTreeMap<_, _>>()", frm
    i, _, frm = ok(P("HashMap", P("String"), ("prim", "f64")), "param")
    assert frm.endswith("collect::<std::collections::HashMap<_, _>>()"), frm
    n += 2
    # bool parameters are the strict `LBool` (mlua's `bool` takes `0` as true); results stay plain bool
    i, to, frm = ok(("prim", "bool"), "param")
    assert i.rust == "LBool" and i.luau == "boolean" and to is None and frm == "x.0", (i, to, frm)
    i, to, frm = ok(("prim", "bool"), "ret")
    assert i.rust == "bool" and to == "x" and frm == "x", (i, to, frm)
    i, _, frm = ok(P("Option", ("prim", "bool")), "param")
    assert i.rust == "Option<LBool>" and i.luau == "boolean?" and frm == "x.map(|v| v.0)", (i, frm)
    i, _, frm = ok(P("Vec", ("prim", "bool")), "param")
    assert i.rust == "Vec<LBool>" and ".0" in frm, (i, frm)
    n += 4
    # `Option<()>` has no IntoLua: it is a presence flag (`true` / nil), never a parameter
    i, to, frm = ok(P("Option", ("unit",)), "ret")
    assert i.luau == "boolean?" and i.rust == "Option<()>" and to == "x.map(|_| true)" and frm is None, (i, to, frm)
    skips(P("Option", ("unit",)), "param", "`Option<()>` parameter")
    n += 2
    # refusals
    skips(P("HashMap", P("Vec3"), P("String")), "ret", "map key type")
    skips(P("IndexMap", P("String"), P("String")), "param", "`IndexMap` parameter")
    skips(P("HashMap", P("String"), P("PlayerInfo")), "param", "can't be read from Luau")
    skips(P("HashMap", P("Uuid"), P("String")), "param", "nested fallible type in map")  # Uuid keys parse: fallible
    n += 4
    # lists still work (unchanged by the map branch)
    i, to, _ = ok(P("Vec", P("String")), "ret")
    assert i.luau == "{ string }", i
    n += 1
    # accessor records ([accessors.X]): public fields mapped like record fields + getter rows, private fields never read directly
    i, to, _ = ok(P("LookDirection"), "ret")
    assert i.luau == "LookDirection" and i.rust == "LuaLookDirection" and to == "LuaLookDirection(x)", (i, to)
    assert M.records["LookDirection"]["fields"] == [("y_rot", "number", "v.y_rot()"), ("x_rot", "number", "v.x_rot()")]
    ok(P("Physics"), "ret")
    f = {a: (b, c) for a, b, c in M.records["Physics"]["fields"]}
    assert f["velocity"] == ("Vec3", "LVec3(v.velocity)") and f["on_ground"] == ("boolean", "v.on_ground()"), f
    assert list(f)[-1] == "on_ground" and "last_on_ground" not in f
    ok(P("Attributes"), "ret")
    f = {a: (b, c) for a, b, c in M.records["Attributes"]["fields"]}
    assert f["step_height"] == ("AttributeInstance", "LuaAttributeInstance(v.step_height)") and len(f) == 9, f
    assert M.records["AttributeInstance"]["fields"] == [("base", "number", "v.base"), ("value", "number", "v.calculate()")]
    ok(P("GameProfile"), "ret")
    assert [a for a, _b, _c in M.records["GameProfile"]["fields"]] == ["uuid", "name"]
    n += 7
    # a missing public field, or a duplicate Luau field, skips the type with a reason (never silently wrong)
    saved = dict(g.ACCESSORS)
    try:
        g.ACCESSORS["Physics"] = dict(fields=["nope"], getters=[])
        M2 = g.Mapper(ix)
        try:
            M2.map_ty(P("Physics"), "ret")
            raise AssertionError("missing field not refused")
        except g.Skip as e:
            assert "no public field `nope`" in str(e), e
        g.ACCESSORS["Physics"] = dict(fields=["velocity"], getters=[("velocity", "number", "1")])
        try:
            g.Mapper(ix).map_ty(P("Physics"), "ret")
            raise AssertionError("duplicate field not refused")
        except g.Skip as e:
            assert "listed twice" in str(e), e
        g.ACCESSORS["Physics"] = dict(fields=["on_ground"], getters=[])     # private in the fake: not readable as a field
        try:
            g.Mapper(ix).map_ty(P("Physics"), "ret")
            raise AssertionError("private field read")
        except g.Skip as e:
            assert "no public field `on_ground`" in str(e), e
    finally:
        g.ACCESSORS.clear()
        g.ACCESSORS.update(saved)
    n += 3
    # tagged enums (data-carrying): unit -> `kind`, one-field tuple -> record fields flattened or `value`, several -> `_1`.., struct-style refused
    def enum_def(name, variants):
        return g.Def("enum", name, "azalea", (), True, False, b"", variants=variants)

    def var(name, kind, types=()):
        return dict(name=name, kind=kind, types=list(types), attrs=[], doc="")

    M3 = g.Mapper(ix)
    defs = {
        "Shape": enum_def("Shape", [var("Empty", "unit"), var("Count", "tuple", [("prim", "u32")]),
                                    var("Pair", "tuple", [P("String"), ("prim", "bool")]), var("Who", "tuple", [P("PlayerInfo")])]),
        "Bad": enum_def("Bad", [var("Empty", "unit"), var("Named", "struct", [("prim", "u32")])]),
        "Clash": enum_def("Clash", [var("A", "unit"), var("a", "unit")]),
    }
    real_unique, real_resolve = ix.unique_def, ix.resolve_path
    ix.unique_def = lambda n: defs.get(n) or real_unique(n)
    ix.resolve_path = lambda n: f"azalea::x::{n}" if n in defs else real_resolve(n)
    try:
        i = M3.map_ty(P("Shape"), "ret")
        assert i.luau == "Shape" and i.rust == "LuaShape" and i.to_lua("x") == "LuaShape(x)" and not i.needs_client, i
        vs = {v["name"]: v for v in M3.tagged["Shape"]["variants"]}
        assert vs["Empty"]["kind"] == "empty" and vs["Empty"]["fields"] == [] and vs["Empty"]["pat"] == ""
        assert vs["Count"]["fields"] == [("value", "number", "v")] and vs["Count"]["pat"] == "(v)"
        assert vs["Pair"]["fields"] == [("_1", "string", "f0"), ("_2", "boolean", "f1")] and vs["Pair"]["pat"] == "(f0, f1)"
        assert [f[0] for f in vs["Who"]["fields"]] == ["name", "uuid", "latency", "gamemode"], vs["Who"]
        for bad, why in (("Bad", "struct-style variant"), ("Clash", "same snake_case name")):
            try:
                g.Mapper(ix).map_ty(P(bad), "ret")
                raise AssertionError(f"{bad} not refused")
            except g.Skip as e:
                assert why in str(e), e
        # an enum holding an ECS `Entity` (the fake's HitResult) carries the client and is only returned by `Client` methods
        M4 = g.Mapper(ix)
        M4.cur_class = "Client"
        i = M4.map_ty(P("HitResult"), "ret")
        assert i.needs_client and i.to_lua("x") == "LuaHitResult(x, self.client.clone())", (i.needs_client, i.to_lua("x"))
        assert M4.tagged["HitResult"]["needs_client"] and M4.records["EntityHitResult"]["needs_client"]
        assert not M4.records["BlockHitResult"]["needs_client"]
        assert [v["kind"] for v in M4.tagged["HitResult"]["variants"]] == ["block", "entity"]
        M4.cur_class = "EntityRef"
        try:
            M4.map_ty(P("HitResult"), "ret")
            raise AssertionError("cached client type reached an Entity method")
        except g.Skip as e:
            assert "only `Client` methods" in str(e), e
        M5 = g.Mapper(ix)
        M5.cur_class = "EntityRef"                      # first use from an Entity method: refused, and not remembered as a failure
        try:
            M5.map_ty(P("HitResult"), "ret")
            raise AssertionError("HitResult built for an Entity method")
        except g.Skip:
            pass
        M5.cur_class = "Client"
        assert M5.map_ty(P("HitResult"), "ret").needs_client
    finally:
        ix.unique_def, ix.resolve_path = real_unique, real_resolve
    n += 11
    # packets in (Generator.build_packets_in): variants from the `declare_state_packets!` list, per-field tolerance, `kind` clash
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        pk = Path(tmp) / "azalea-protocol" / "src" / "packets" / "game"
        pk.mkdir(parents=True)
        (pk / "mod.rs").write_text("declare_state_packets!(GamePacket,\n    Clientbound => [\n        foo, // a comment\n        bar_baz,\n        tup,\n    ],\n    Serverbound => [ zed ]\n);\n")
        mk = lambda name, fields, tuple_style=False, mod="game": g.Def(  # noqa: E731
            kind="struct", name=name, crate="azalea_protocol", modpath=("packets", mod, "c"), is_pub=True, generics=False,
            src=b"", tuple_style=tuple_style, fields=fields)
        added = [
            mk("ClientboundFoo", [("id", P("MinecraftEntityId"), True), ("blob", P("NoSuchType"), True), ("kind", ("prim", "u8"), True),
                                  ("hidden", ("prim", "u8"), False), ("count", ("prim", "u32"), True)]),
            mk("ClientboundTup", [("0", ("prim", "u8"), True), ("1", P("String"), True)], tuple_style=True),
            mk("ClientboundFoo", [("other", ("prim", "u8"), True)], mod="config"),   # same name in another state: ignored
        ]
        for d in added:
            ix.defs[d.name].append(d)
        try:
            gp = g.Generator(ix)
            gp.build_packets_in(Path(tmp))
            by = {p["name"]: p for p in gp.packets_in}
            assert list(by) == ["foo", "bar_baz", "tup"], list(by)     # `zed` is serverbound, comments are stripped
            foo = by["foo"]
            assert foo["variant"] == "Foo" and foo["luau"] == "PacketFoo" and not foo["nodef"], foo
            assert [f[0] for f in foo["fields"]] == ["id", "count"], foo["fields"]
            assert [f[0] for f in foo["skipped"]] == ["blob", "kind", "hidden"], foo["skipped"]
            assert foo["fields"][0][2] == "LMinecraftEntityId(v.id)", foo["fields"][0]
            assert by["bar_baz"]["variant"] == "BarBaz" and by["bar_baz"]["nodef"] and not by["bar_baz"]["fields"], by["bar_baz"]
            assert [f[0] for f in by["tup"]["fields"]] == ["_1", "_2"] and by["tup"]["fields"][0][2] == "v.0", by["tup"]["fields"]
            out = g.emit_packets_in(gp, "test")
            assert "ClientboundGamePacket::BarBaz(v) => {" in out and 't.set("count", v.count)?;' in out, out
            gp2 = g.Generator(ix)
            gp2.build_packets_in(Path(tmp) / "nowhere")                # azalea without packet sources (the fake): nothing
            assert gp2.packets_in == []
        finally:
            for d in added:
                ix.defs[d.name].remove(d)
    n += 8
    # packets out (Generator.build_packets_out): one unconvertible field = no constructor (the struct needs every field)
    with tempfile.TemporaryDirectory() as tmp:
        pk = Path(tmp) / "azalea-protocol" / "src" / "packets" / "game"
        pk.mkdir(parents=True)
        (pk / "mod.rs").write_text("declare_state_packets!(GamePacket,\n    Clientbound => [ foo ],\n    Serverbound => [\n        ok_one, // c\n        bad_one,\n        tup_out,\n        empty,\n    ]\n);\n")
        mk = lambda name, fields, tuple_style=False: g.Def(  # noqa: E731
            kind="struct", name=name, crate="azalea_protocol", modpath=("packets", "game", "s"), is_pub=True, generics=False,
            src=b"", tuple_style=tuple_style, fields=fields)
        added = [
            mk("ServerboundOkOne", [("id", P("MinecraftEntityId"), True), ("n", ("prim", "u32"), True)]),
            mk("ServerboundBadOne", [("id", P("MinecraftEntityId"), True), ("blob", P("NoSuchType"), True)]),
            mk("ServerboundTupOut", [("0", ("prim", "u8"), True), ("1", P("String"), True)], tuple_style=True),
            mk("ServerboundEmpty", []),
        ]
        for d in added:
            ix.defs[d.name].append(d)
        try:
            gp = g.Generator(ix)
            gp.build_packets_out(Path(tmp))
            by = {p["name"]: p for p in gp.packets_out}
            assert list(by) == ["ok_one", "bad_one", "tup_out", "empty"], list(by)     # clientbound `foo` is not listed
            assert by["ok_one"]["ok"] and by["ok_one"]["luau"] == "OutPacketOkOne" and [f[0] for f in by["ok_one"]["fields"]] == ["id", "n"]
            assert not by["bad_one"]["ok"] and not by["bad_one"]["fields"] and "`blob`" in by["bad_one"]["why"], by["bad_one"]
            assert by["tup_out"]["ok"] and by["tup_out"]["tuple_style"] and [f[0] for f in by["tup_out"]["fields"]] == ["_1", "_2"]
            assert by["empty"]["ok"] and by["empty"]["fields"] == []
            out = g.emit_packets_out(gp, "test")
            assert '"ok_one" => {' in out and "ServerboundOkOne { id: f0.0, n: f1 }" in out, out
            assert "ServerboundGamePacket::TupOut(azalea::protocol::packets::game::ServerboundTupOut(f0, f1))" in out, out
            assert "ServerboundEmpty {}" in out and '"bad_one"' not in out, out
            gp2 = g.Generator(ix)
            gp2.build_packets_out(Path(tmp) / "nowhere")
            assert gp2.packets_out == []
        finally:
            for d in added:
                ix.defs[d.name].remove(d)
    n += 9
    # ECS table (Generator.build_ecs): Component/Resource derives -> entries; markers, newtypes, records, unreadable
    mk = lambda name, derive, fields, tuple_style=False: g.Def(  # noqa: E731
        kind="struct", name=name, crate="azalea_entity", modpath=("x",), is_pub=True, generics=False,
        src=b"", tuple_style=tuple_style, fields=fields, attrs=[derive])
    added = [
        mk("EcsMarker", "#[derive(Component)]", []),
        mk("EcsCount", "#[derive(Component, Clone)]", [("0", ("prim", "u32"), True)], tuple_style=True),
        mk("EcsHidden", "#[derive(Component, Clone)]", [("0", ("prim", "u32"), False)], tuple_style=True),
        mk("EcsNoClone", "#[derive(Component)]", [("0", ("prim", "u32"), True)], tuple_style=True),
        mk("EcsRes", "#[derive(Resource, Clone)]", [("0", ("prim", "bool"), True)], tuple_style=True),
        mk("EcsPlain", "#[derive(Debug, Clone)]", [("0", ("prim", "bool"), True)], tuple_style=True),
        # rustdoc front end: derive(Resource) also writes an `impl Component`, so def_attrs shows both
        mk("EcsResBoth", "#[derive(Clone, Component, Resource)]", [("0", ("prim", "bool"), True)], tuple_style=True),
    ]
    for d in added:
        ix.defs[d.name].append(d)
    # a component whose NAME is also a pub struct elsewhere (rustdoc sees macro-made ones: azalea_block `Chest`, azalea_inventory `Player`)
    dup_c = mk("EcsDup", "#[derive(Component, Clone)]", [("0", ("prim", "bool"), True)], tuple_style=True)
    dup_o = g.Def(kind="struct", name="EcsDup", crate="azalea_block", modpath=("y",), is_pub=True, generics=False, src=b"", fields=[])
    added += [dup_c, dup_o]
    for d in (dup_c, dup_o):
        ix.defs[d.name].append(d)
    saved_paths = g.PATH_OVERRIDES.copy()
    saved_ix = (ix.chain_public, ix.to_azalea)
    try:
        ix.chain_public = lambda crate, modpath: True
        ix.to_azalea = lambda crate, modpath, name: "::".join(["azalea", *modpath, name])
        for d in added:
            if d.name != "EcsDup":
                g.PATH_OVERRIDES[d.name] = "azalea::x::" + d.name
        ge = g.Generator(ix)
        ge.build_ecs()
        by = {e["name"]: e for e in ge.ecs}
        assert "EcsPlain" not in by, "a type without a Component/Resource derive is not in the table"
        assert by["EcsMarker"]["marker"] and by["EcsMarker"]["luau"] == "boolean" and by["EcsMarker"]["to_lua"] == "true", by["EcsMarker"]
        assert by["EcsCount"]["luau"] == "number" and by["EcsCount"]["to_lua"] == "v.0" and by["EcsCount"]["kind"] == "component", by["EcsCount"]
        assert by["EcsHidden"]["to_lua"] is None and "private" in by["EcsHidden"]["reason"], by["EcsHidden"]
        assert by["EcsNoClone"]["to_lua"] is None and "Clone" in by["EcsNoClone"]["reason"], by["EcsNoClone"]
        assert by["EcsRes"]["kind"] == "resource" and by["EcsRes"]["luau"] == "boolean", by["EcsRes"]
        assert by["EcsResBoth"]["kind"] == "resource", by["EcsResBoth"]
        assert by["EcsDup"]["path"] == "azalea::x::EcsDup" and by["EcsDup"]["to_lua"] == "v.0", by["EcsDup"]
        out = g.emit_ecs(ge, "test")
        assert 'EcsEntry { name: "EcsCount", kind: "component", rust: "azalea::x::EcsCount"' in out, out
        assert '"EcsMarker" => Ok(client.get_entity_component::<azalea::x::EcsMarker>(entity).map(|_| Value::Boolean(true))),' in out, out
        assert "pub fn read_ref_component(lua: &Lua, entity: &azalea::EntityRef" in out and "entity.get_component::<azalea::x::EcsCount>()" in out, out
        assert "map_get_resource::<azalea::x::EcsRes, _>" in out and '"EcsHidden" =>' not in out.split("read_component")[1].split("read_ref_component")[0], out
    finally:
        ix.chain_public, ix.to_azalea = saved_ix
        g.PATH_OVERRIDES.clear()
        g.PATH_OVERRIDES.update(saved_paths)
        for d in added:
            ix.defs[d.name].remove(d)
    n += 9
    # the ECS name-error template reads "is a resource, not a component" (it once had a stray space before the comma)
    assert "is a {}, not a {kind}" in out and " , not a" not in out, out
    # goals(): the mapper keys it touches are credited to EVERY class that calls it, not only the first
    gg = g.Generator(ix)
    gg.m.touched = set()
    gl = gg.goals()
    first = set(gg.m.touched)
    assert gl and first, "the fake azalea must have usable Goal types that touch mapper keys"
    gg.m.touched = {("type", "Other")}
    assert gg.goals() is gl
    assert gg.m.touched == first | {("type", "Other")}, (gg.m.touched, first)
    n += 3
    # extras_reserved(): only fns at the impl block's own brace depth are methods; a nested `fn` in a method body
    # (or text inside a string/comment) is not
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "extra_entity.rs").write_text(
            "impl LuaEntityRef {\n"
            "    pub fn outer(&self) -> u8 {\n"
            "        fn nested_helper(x: u8) -> u8 {\n"
            "            x + 1\n"
            "        }\n"
            "        let s = \"{ fn in_string() }\"; // fn in_comment() {\n"
            "        nested_helper(1)\n"
            "    }\n"
            "    pub async fn second(&self) {}\n"
            "}\n"
        )
        res = g.extras_reserved(Path(tmp))
        names = res["EntityRef"]
        assert names == {"outer", "second"}, names
    n += 1
    print(f"mapper_selftest: OK ({n} checks)")


if __name__ == "__main__":
    main()
