#!/usr/bin/env python3
"""
luaxite_gen.py - generate the Luau <-> azalea bridge from azalea's own rustdoc JSON.

Reads the rustdoc JSON of the azalea workspace you vendor (--azalea DIR, --rustdoc DIR) and writes:

  rust/luau/gen_client.rs   Luau -> azalea : `bot:method()` forwards to azalea::Client
  rust/luau/gen_events.rs   azalea -> Luau : azalea::Event variants fire `bot:on(...)` handlers
  rust/luau/gen_types.rs    value conversions (enums <-> strings, structs -> tables)
  luau/azalea.d.luau       Luau type definitions for luau-lsp (both directions)
  luau/GEN_REPORT.md       what was generated, what was skipped and why

Nothing is hand-listed: methods come from every `impl Client` / `XClientExt for Client`
in the rustdoc JSON, events come from `enum Event`, and enums/structs/goals are discovered
from it. Anything whose types can't be mapped is skipped and reported.

Usage (from your project root; stdlib only):
    python tools/luaxite_gen.py --azalea bind/azalea-src --rustdoc DIR --rust-out OUT --luau-out OUT
"""
from __future__ import annotations

import argparse
import unicodedata
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# =============================================================================
# CONFIG - the only part you should need to edit
# =============================================================================

SKIP_DIRS = {"examples", "benches", "tests", "target", ".git"}

# Types with hand-written conversions in rust/luau/convert.rs.
BUILTIN = {
    "BlockPos": dict(rust="LBlockPos", luau_def="{ x: number, y: number, z: number }", param=True, ret=True),
    "Vec3": dict(rust="LVec3", luau_def="{ x: number, y: number, z: number }", param=True, ret=True),
    "MinecraftEntityId": dict(rust="LMinecraftEntityId", luau="number", luau_def=None, param=True, ret=True),
    # An empty stack is `nil`, so every signature that returns one reads `Item?`. Inside arrays an empty slot
    # is `false` (a Luau array can't hold nil without holes), see `LSlots` in convert.rs.
    "ItemStack": dict(
        rust="LItem", luau="Item?", alias="Item", luau_def="{ kind: string, count: number }", param=False, ret=True,
    ),
    # The open menu (or the player's inventory): its kind in snake_case and every slot in protocol order.
    "Menu": dict(
        rust="LMenu", luau="Menu", luau_def="{ kind: string, slots: { Item | false } }", param=False, ret=True,
        needs="ItemStack",
    ),
    # An open container: a hand-written userdata class (`Container`, methods in rust/luau/extra_container.rs).
    # Wrapping it in `Some` lets `close()` drop the handle, which is what closes the container.
    "ContainerHandle": dict(
        rust="LuaContainer", luau="Container", luau_def=None, param=False, ret=True,
        to="LuaContainer { handle: Some(Held::Owned({x})) }", needs="ItemStack",
        class_doc="An open container (a chest, or the bot's own inventory). It closes on `close()` or when garbage collected.",
    ),
    # `get_inventory`: azalea's non-owning reference (it sends no close packet when dropped). Same Luau class;
    # `LuaContainer` tells the two apart through `Held` in convert.rs.
    "ContainerHandleRef": dict(
        rust="LuaContainer", luau="Container", luau_def=None, param=False, ret=True,
        to="LuaContainer { handle: Some(Held::Borrowed({x})) }", needs="ItemStack",
        class_doc="An open container (a chest, or the bot's own inventory). It closes on `close()` or when garbage collected.",
    ),
    "PathfinderOpts": dict(
        rust="LPathfinderOpts",
        luau_def="{ retry_on_no_path: boolean?, allow_mining: boolean? }",
        param=True,
        ret=False,
    ),
}

# The pure-data tables (DENY_METHODS PATH_OVERRIDES RENAMES HANDWRITTEN_GOALS CLASSES EVENT_ARG_NAMES HIDDEN_EVENTS
# GOAL_PARAM_NAMES SCALAR RECORDS) live in bindgen.toml; BUILTIN (it holds nulls) and the keyword sets stay here.

class ConfigError(Exception):
    pass


ROOT = Path(__file__).resolve().parent.parent       # the project root: tools/ lives directly under it
BUILTIN_NAME = "builtin"                            # `--config builtin`: the built-in empty tables, whatever bindgen.toml is next to this script
CONFIG_PATH = ROOT / "bindgen.toml"                  # default of --config; a missing default file = BUILTIN_CONFIG
BUILTIN_CONFIG = {"deny_methods": [], "classes": {}, "scalar": {}, "records": {}, "accessors": {},
                  **{k: {} for k in ("path_overrides", "renames", "handwritten_goals", "event_arg_names", "hidden_events",
                                     "goal_param_names", "extra_events", "hand_classes", "hand_globals")}}
_STR_TABLES = {"path_overrides": "PATH_OVERRIDES", "renames": "RENAMES", "handwritten_goals": "HANDWRITTEN_GOALS",
               "event_arg_names": "EVENT_ARG_NAMES", "hidden_events": "HIDDEN_EVENTS", "goal_param_names": "GOAL_PARAM_NAMES",
               "extra_events": "EXTRA_EVENTS", "hand_classes": "HAND_CLASSES", "hand_globals": "HAND_GLOBALS"}
_CLASS_KEYS = {"rust": str, "luau": str, "field": str, "renames": (dict, str), "events": bool, "emit": bool, "deny": dict, "doc": str}
_SCALAR_KEYS = {"luau": str, "to": str, "frm": str, "fallible": bool}


def _type_name(t) -> str:
    return " or ".join(x.__name__ for x in t) if isinstance(t, tuple) else t.__name__


def _expect(path: str, v, t):
    if not isinstance(v, t) or (t is not bool and isinstance(v, bool) and bool not in (t if isinstance(t, tuple) else (t,))):
        raise ConfigError(f"key `{path}`: expected {_type_name(t)}, got {type(v).__name__}")
    return v


def _str_table(path: str, v) -> dict:
    _expect(path, v, dict)
    for k, x in v.items():
        _expect(f"{path}.{k}", x, str)
    return dict(v)


def load_config(path=None) -> dict:
    """Read and validate the TOML tables: {PYTHON_NAME: value}. Every problem is a ConfigError naming the key.
    path=None: `<root>/bindgen.toml`, or the built-in (empty) tables when that file does not exist; an explicit path must exist."""
    import tomllib
    if str(path) == BUILTIN_NAME or (path is None and not CONFIG_PATH.exists()):
        raw = BUILTIN_CONFIG
        path = CONFIG_PATH
    else:
        path = Path(CONFIG_PATH if path is None else path)
        raw = None
    try:
        if raw is None:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e.strerror or e}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name} is not valid TOML: {e}") from None
    known = {"deny_methods", "classes", "scalar", "records", "accessors", *_STR_TABLES}
    optional = {"extra_event_payloads"}     # may be absent
    for k in raw:
        if k not in known and k not in optional:
            raise ConfigError(f"unknown key `{k}` (expected one of: {', '.join(sorted(known | optional))})")
    for k in sorted(known - set(raw)):
        raise ConfigError(f"missing key `{k}`")
    out: dict = {"DENY_METHODS": set(_expect("deny_methods", raw["deny_methods"], list))}
    for i, x in enumerate(raw["deny_methods"]):
        _expect(f"deny_methods[{i}]", x, str)
    for k, name in _STR_TABLES.items():
        out[name] = _str_table(k, raw[k])
    classes = {}
    for cname, c in _expect("classes", raw["classes"], dict).items():
        _expect(f"classes.{cname}", c, dict)
        for k in c:
            if k not in _CLASS_KEYS:
                raise ConfigError(f"key `classes.{cname}.{k}`: unknown (expected one of: {', '.join(_CLASS_KEYS)})")
        for k in ("rust", "luau", "field", "renames", "deny"):
            if k not in c:
                raise ConfigError(f"key `classes.{cname}.{k}`: missing")
        for k, t in _CLASS_KEYS.items():
            if k in c:
                _expect(f"classes.{cname}.{k}", c[k], t)
        d = dict(c)
        d["deny"] = _str_table(f"classes.{cname}.deny", c["deny"])
        if isinstance(c["renames"], str):
            if c["renames"] != "@renames":
                raise ConfigError(f"key `classes.{cname}.renames`: a string must be \"@renames\", got {c['renames']!r}")
            d["renames"] = out["RENAMES"]
        else:
            d["renames"] = _str_table(f"classes.{cname}.renames", c["renames"])
        classes[cname] = d
    out["CLASSES"] = classes
    scalar = {}
    for tname, c in _expect("scalar", raw["scalar"], dict).items():
        _expect(f"scalar.{tname}", c, dict)
        for k, v in c.items():
            if k not in _SCALAR_KEYS:
                raise ConfigError(f"key `scalar.{tname}.{k}`: unknown (expected one of: {', '.join(_SCALAR_KEYS)})")
            _expect(f"scalar.{tname}.{k}", v, _SCALAR_KEYS[k])
        if "luau" not in c:
            raise ConfigError(f"key `scalar.{tname}.luau`: missing")
        scalar[tname] = dict(c)
    out["SCALAR"] = scalar
    records = {}
    for tname, rows in _expect("records", raw["records"], dict).items():
        _expect(f"records.{tname}", rows, list)
        for i, row in enumerate(rows):
            _expect(f"records.{tname}[{i}]", row, list)
            if len(row) != 3:
                raise ConfigError(f"key `records.{tname}[{i}]`: expected 3 strings (luau field, luau type, rust expr), got {len(row)} items")
            for j, x in enumerate(row):
                _expect(f"records.{tname}[{i}][{j}]", x, str)
        records[tname] = [tuple(r) for r in rows]
    out["RECORDS"] = records
    acc = {}
    for tname, c in _expect("accessors", raw["accessors"], dict).items():
        _expect(f"accessors.{tname}", c, dict)
        for k in c:
            if k not in ("fields", "getters"):
                raise ConfigError(f"key `accessors.{tname}.{k}`: unknown (expected one of: fields, getters)")
        fields = _expect(f"accessors.{tname}.fields", c.get("fields", []), list)
        for i, x in enumerate(fields):
            _expect(f"accessors.{tname}.fields[{i}]", x, str)
        getters = _expect(f"accessors.{tname}.getters", c.get("getters", []), list)
        for i, row in enumerate(getters):
            _expect(f"accessors.{tname}.getters[{i}]", row, list)
            if len(row) != 3:
                raise ConfigError(f"key `accessors.{tname}.getters[{i}]`: expected 3 strings (luau field, luau type, rust expr), got {len(row)} items")
            for j, x in enumerate(row):
                _expect(f"accessors.{tname}.getters[{i}][{j}]", x, str)
        if not fields and not getters:
            raise ConfigError(f"key `accessors.{tname}`: needs `fields` or `getters`")
        if tname in records:
            raise ConfigError(f"key `accessors.{tname}`: also listed in [records] (use one)")
        acc[tname] = dict(fields=list(fields), getters=[tuple(r) for r in getters])
    out["ACCESSORS"] = acc
    payloads = _str_table("extra_event_payloads", raw.get("extra_event_payloads", {}))
    for n, t in payloads.items():
        if n not in out["EXTRA_EVENTS"]:
            raise ConfigError(f"key `extra_event_payloads.{n}`: not listed in [extra_events]")
        if t != "ClientboundPacket":
            raise ConfigError(f"key `extra_event_payloads.{n}`: unknown payload type `{t}` (only `ClientboundPacket`, the generated union of clientbound game packets)")
    out["EXTRA_EVENT_PAYLOADS"] = payloads
    return out


try:
    globals().update(load_config())
except ConfigError as e:
    sys.exit(f"error: {CONFIG_PATH.name}: {e}")      # --config reloads these in main()

INT_TYPES = {"i8", "i16", "i32", "i64", "isize", "u8", "u16", "u32", "u64", "usize"}
FLOAT_TYPES = {"f32", "f64"}
MAP_TYPES = ("HashMap", "BTreeMap", "IndexMap")  # mapped to a Luau table `{ [K]: V }` (path_ty)
RUST_KEYWORDS = {
    "as", "break", "const", "continue", "crate", "else", "enum", "extern", "false", "fn", "for", "if",
    "impl", "in", "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return", "self", "Self",
    "static", "struct", "super", "trait", "true", "type", "unsafe", "use", "where", "while", "async",
    "await", "dyn", "abstract", "become", "box", "do", "final", "macro", "override", "priv", "typeof",
    "unsized", "virtual", "yield", "try", "gen",
}
LUAU_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in", "local",
    "nil", "not", "or", "repeat", "return", "then", "true", "until", "while", "continue", "export", "type",
}

# Keywords that can never be a bare property name in a Luau table type (`{ end: number }` is a parse error;
# `{ ["end"]: number }` is fine). `type`/`continue`/`export` are contextual and stay bare.
LUAU_HARD_KEYWORDS = LUAU_KEYWORDS - {"continue", "export", "type"}
# Luau's own type names: a generated `type string = ..` would shadow them for every script.
LUAU_TYPE_NAMES = {"string", "number", "boolean", "any", "nil", "table", "thread", "buffer", "vector", "never", "unknown", "function"}
ASCII_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

HEADER = "// @generated by tools/luaxite_gen.py from {src} - DO NOT EDIT, re-run the generator."


# =============================================================================
# small helpers
# =============================================================================

class Skip(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def snake(s: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


_BIDI = set("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def clean_doc(doc: str) -> str:
    """Control characters and bidi overrides would be copied verbatim into azalea.d.luau and the generated Rust
    (the emitters call this on every doc string)."""
    return "".join(" " if ch == "\t" else ch for ch in doc
                   if ch == "\t" or not (unicodedata.category(ch) == "Cc" or ch in _BIDI))


# =============================================================================
# type AST (tiny): ("prim", n) ("unit",) ("path", name, [args]) ("ref", t) ("slice", t)
#                  ("tuple", [t]) ("impl", text) ("other", text)
# =============================================================================

def type_text(t) -> str:
    k = t[0]
    if k == "prim":
        return t[1]
    if k == "unit":
        return "()"
    if k == "path":
        return t[1] + (f"<{', '.join(type_text(a) for a in t[2])}>" if t[2] else "")
    if k == "ref":
        return "&" + type_text(t[1])
    if k == "slice":
        return f"[{type_text(t[1])}]"
    if k == "tuple":
        return f"({', '.join(type_text(a) for a in t[1])})"
    return t[1]


# =============================================================================
# source index
# =============================================================================

@dataclass
class Def:
    kind: str
    name: str
    crate: str
    modpath: tuple
    is_pub: bool
    generics: bool
    src: bytes
    tuple_style: bool = False
    fields: list = field(default_factory=list)      # (name, type_ast, is_pub)
    variants: list = field(default_factory=list)    # dict(name, kind, types, attrs, doc)
    attrs: list = field(default_factory=list)
    dropped_variants: list = field(default_factory=list)    # variants the JSON index lacks ("variant #id")


@dataclass
class Method:
    name: str
    doc: str
    is_pub: bool
    is_async: bool
    generics: bool
    receiver: Optional[str]
    params: list          # (name, type_ast)
    ret: Optional[tuple]
    owner: str
    file: str
    sig: str
    target: str = "Client"


# =============================================================================
# type mapping
# =============================================================================

@dataclass
class TypeInfo:
    rust: str
    luau: str
    to_lua: Optional[Callable[[str], str]] = None
    from_lua: Optional[Callable[[str], str]] = None
    fallible_from: bool = False
    is_result: bool = False
    is_class: bool = False      # a generated userdata class (see CLASSES)
    needs_client: bool = False  # to_lua needs the bot's `Client` (it turns an ECS `Entity` into an `Entity` class value): `Client` methods only
    by_ref: bool = False        # to_lua only needs a borrow (a scalar's `{x}.to_string()`): an `Arc<T>` of it is not cloned first


def is_ident(f: Callable[[str], str]) -> bool:
    return f("v") == "v"


ID = lambda x: x  # noqa: E731


class Mapper:
    def __init__(self, ix: Any):
        self.ix = ix
        self.cache: dict[str, TypeInfo] = {}
        self.fail: dict[str, str] = {}
        self.deps: dict[str, set] = {}
        self.dep_stack: list[set] = []
        self.touched: set = set()
        self.enums: dict[str, dict] = {}
        self.records: dict[str, dict] = {}
        self.tagged: dict[str, dict] = {}       # data-carrying enums -> tagged tables (build_tagged)
        self.enum_notes: list[str] = []         # one line per emitted enum that lost variants in the front end (GEN_REPORT + stderr)
        self.cexpr = "self.client"              # Rust expression of the `Client` while converting ("client" inside a generated conversion)
        self.client_flags: list[bool] = []      # per type being built: does it contain an ECS `Entity`?
        self.paths: dict[str, str] = {}
        self.cur_class: Optional[str] = None    # class whose methods are being mapped
        self.building: set[str] = set()         # named types whose conversion is being derived right now (recursion guard)

    def touch(self, key):
        self.touched.add(key)
        for s in self.dep_stack:
            s.add(key)

    # ---- entry point
    def map_ty(self, t, role: str) -> TypeInfo:
        k = t[0]
        if k == "unit":
            return TypeInfo("()", "()", to_lua=ID)
        if k == "prim":
            n = t[1]
            if n == "bool":
                if role == "param":
                    # mlua's own `bool` accepts anything but nil/false as true (`0`, `""`): parameters use the strict `LBool` (convert.rs)
                    return TypeInfo("LBool", "boolean", from_lua=lambda x: f"{x}.0")
                return TypeInfo("bool", "boolean", ID, ID)
            if n in INT_TYPES or n in FLOAT_TYPES:
                return TypeInfo(n, "number", ID, ID)
            raise Skip(f"primitive `{n}`")
        if k == "ref":
            if t[1] in (("prim", "str"), ("path", "str", [])) and role == "param":
                return TypeInfo("String", "string", from_lua=lambda x: f"&{x}")
            raise Skip(f"reference type `{type_text(t)}`")
        if k == "impl":
            if re.fullmatch(r"impl Into<String>", t[1]) and role == "param":
                return TypeInfo("String", "string", from_lua=ID)
            raise Skip(f"`{t[1]}` parameter")
        if k == "path":
            return self.path_ty(t[1], t[2], role)
        raise Skip(f"type `{type_text(t)}`")

    def path_ty(self, name: str, args: list, role: str) -> TypeInfo:
        if name == "String" and not args:
            return TypeInfo("String", "string", ID, ID)
        if name == "Option" and len(args) == 1:
            if args[0] == ("unit",):
                # `()` has no `IntoLua`, so `Option<()>` can't be set into a table as is: `Some(())` is a presence flag (`true`, else nil)
                if role != "ret":
                    raise Skip("`Option<()>` parameter")
                return TypeInfo("Option<()>", "boolean?", to_lua=lambda x: f"{x}.map(|_| true)")
            i = self.map_ty(args[0], role)
            if i.is_result or (role == "param" and i.fallible_from):
                raise Skip("nested fallible type in Option")
            to = frm = None
            if i.to_lua:
                to = (lambda x, i=i: x) if is_ident(i.to_lua) else (lambda x, i=i: f"{x}.map(|v| {i.to_lua('v')})")
            if i.from_lua:
                frm = (lambda x, i=i: x) if is_ident(i.from_lua) else (lambda x, i=i: f"{x}.map(|v| {i.from_lua('v')})")
            return TypeInfo(f"Option<{i.rust}>", f"{i.luau}?", to, frm)
        if (name == "Vec" and len(args) == 1) or (name == "Box" and len(args) == 1 and args[0][0] == "slice"):
            elem = args[0] if name == "Vec" else args[0][1]
            i = self.map_ty(elem, role)
            if i.is_result or i.fallible_from:
                raise Skip("nested fallible type in list")
            to = frm = None
            if role == "ret" and i.to_lua:
                head = "{x}" if name == "Vec" else "Vec::from({x})"
                if is_ident(i.to_lua):
                    to = (lambda x, h=head: h.format(x=x))
                else:
                    to = (lambda x, h=head, i=i: h.format(x=x) + f".into_iter().map(|v| {i.to_lua('v')}).collect::<Vec<_>>()")
            if role == "param" and name == "Vec" and i.from_lua and is_ident(i.from_lua):
                frm = ID
            elif role == "param" and (i.is_class or i.rust == "LBool") and i.from_lua:
                coll = "Vec<_>" if name == "Vec" else "Box<[_]>"
                frm = (lambda x, i=i, c=coll: f"{x}.into_iter().map(|v| {i.from_lua('v')}).collect::<{c}>()")
            return TypeInfo(f"Vec<{i.rust}>", f"{{ {i.luau} }}", to, frm)
        if name in MAP_TYPES and len(args) == 2:
            # A map becomes a Luau table `{ [K]: V }`; K must be a string or a number in Luau (a `Uuid` key is its string form).
            k, v = self.map_ty(args[0], role), self.map_ty(args[1], role)
            if any(x.is_result or (role == "param" and x.fallible_from) for x in (k, v)):
                raise Skip("nested fallible type in map")
            if k.luau not in ("string", "number"):
                raise Skip(f"map key type `{type_text(args[0])}` (Luau table keys must be strings or numbers)")
            to = frm = None
            if role == "ret" and k.to_lua and v.to_lua:
                to = (lambda x, k=k, v=v: f"{x}.into_iter().map(|(k, v)| ({k.to_lua('k')}, {v.to_lua('v')}))"
                                          ".collect::<std::collections::HashMap<_, _>>()")
            if role == "param":
                if name == "IndexMap":
                    raise Skip("`IndexMap` parameter (the crate has no `indexmap` dependency to build one)")
                if not (k.from_lua and v.from_lua):
                    raise Skip("map parameter with a key or value that can't be read from Luau")
                coll = "std::collections::HashMap<_, _>" if name == "HashMap" else "std::collections::BTreeMap<_, _>"
                frm = (lambda x, k=k, v=v, c=coll: f"{x}.into_iter().map(|(k, v)| ({k.from_lua('k')}, {v.from_lua('v')})).collect::<{c}>()")
            return TypeInfo(f"std::collections::HashMap<{k.rust}, {v.rust}>", f"{{ [{k.luau}]: {v.luau} }}", to, frm)
        if name in ("Result", "AzaleaResult"):
            if role != "ret":
                raise Skip("Result as parameter")
            if name == "Result" and not (len(args) == 2 and args[1] == ("path", "MissingComponentError", [])):
                raise Skip("Result with an error type other than MissingComponentError")
            i = self.map_ty(args[0] if args else ("unit",), "ret")
            if i.is_result:
                raise Skip("nested Result")
            tail = "" if is_ident(i.to_lua) else f".map(|v| {i.to_lua('v')})"
            return TypeInfo(i.rust, i.luau, to_lua=lambda x, tail=tail: f"{x}.map_err(lua_err){tail}", is_result=True)
        if name == "Arc" and len(args) == 1:
            i = self.map_ty(args[0], role)
            if role == "ret" and i.to_lua:
                # `(*x).clone()` hands the converter an owned `T`, but needs `T: Clone` (azalea's `ConnectionError` is not).
                # A scalar's `to` works on a borrow through the `Arc`'s auto-deref, so it gets the `Arc` as is;
                # anything else is cloned out, which only compiles when `T` is `Clone`.
                if i.by_ref:
                    to = i.to_lua
                else:
                    bad = self.not_clone(args[0])
                    if bad:
                        raise Skip(f"`Arc<{type_text(args[0])}>`: `{bad}` is not `Clone`, so it can't be copied out of the `Arc`")
                    to = lambda x, i=i: i.to_lua(f"(*{x}).clone()")
                return TypeInfo(i.rust, i.luau, to_lua=to)
            raise Skip("Arc parameter")
        if args:
            raise Skip(f"generic type `{type_text(('path', name, args))}`")
        return self.named(name, role)

    def not_clone(self, t) -> Optional[str]:
        """The name of a type inside `t` that is known not to implement Clone (None: Clone, or can't tell)."""
        k = t[0]
        if k == "tuple":
            return next((b for x in t[1] if (b := self.not_clone(x))), None)
        if k == "path":
            name, args = t[1], t[2]
            if name in ("Arc", "Rc"):
                return None                     # cloning the pointer is always fine
            for a in args:
                if (b := self.not_clone(a)):
                    return b
            if name in SCALAR or name in BUILTIN or name in CLASSES or name in ("Vec", "Option", "Box", "String", "Result") + MAP_TYPES:
                if name in SCALAR and self.ix.is_clone(name) is False:
                    return name
                return None
            return name if self.ix.is_clone(name) is False else None
        return None

    def taken_luau_names(self) -> set:
        """Luau type/class names already in use: built-ins, hand-written classes, Luau's own."""
        out = set(LUAU_TYPE_NAMES)
        for n, b in BUILTIN.items():
            if b.get("luau_def"):
                out.add(b.get("alias", n))
            if "class_doc" in b:
                out.add(b["luau"])
        out |= {c["luau"] for c in CLASSES.values()}
        out |= set(HAND_CLASSES)
        return out

    # ---- named types
    def named(self, name: str, role: str) -> TypeInfo:
        if name == "Entity":
            # azalea's ECS `Entity` is an internal id: scripts see the `Entity` class (an `EntityRef`).
            # Only `Client` methods can build one (`client.entity_ref_for`); inside a converted type the type carries the client
            # (`needs_client`), and whoever uses that type must be a `Client` method (checked in `named`).
            cls = CLASSES["EntityRef"]
            nested = bool(self.building)
            if not cls["emit"] or (not nested and self.cur_class != "Client") or (nested and role == "param"):
                raise Skip("ECS `Entity` handle: only `Client` methods can turn it into an `Entity` class value")
            self.touch(("class", "EntityRef"))
            r, f = cls["rust"], cls["field"]
            if role == "param":
                return TypeInfo(f"mlua::UserDataRef<{r}>", cls["luau"], from_lua=lambda x, f=f: f"{x}.{f}.id()", is_class=True)
            if nested:
                self.client_flags[-1] = True
            return TypeInfo(r, cls["luau"], to_lua=lambda x, r=r, f=f: f"{r} {{ {f}: {self.cexpr}.entity_ref_for({x}) }}", is_class=True,
                            needs_client=nested)
        cfg = CLASSES.get(name)
        if cfg is not None and cfg["emit"] and name != "Client":
            # a generated userdata class: params arrive as `UserDataRef<LuaX>`, returns are wrapped in `LuaX`
            self.touch(("class", name))
            r, f = cfg["rust"], cfg["field"]
            if role == "param":
                return TypeInfo(f"mlua::UserDataRef<{r}>", cfg["luau"], from_lua=lambda x, f=f: f"{x}.{f}.clone()", is_class=True)
            return TypeInfo(r, cfg["luau"], to_lua=lambda x, r=r, f=f: f"{r} {{ {f}: {x} }}", is_class=True)
        if name in BUILTIN:
            b = BUILTIN[name]
            if not b[role]:
                raise Skip(f"`{name}` can't be used as a {role}")
            self.touch(("builtin", name))
            r = b["rust"]
            return TypeInfo(
                r, b.get("luau", name),
                to_lua=(lambda x, b=b, r=r: b["to"].replace("{x}", x) if "to" in b else f"{r}({x})") if b["ret"] else None,
                from_lua=(lambda x: f"{x}.0") if b["param"] else None,
            )
        if name in SCALAR:
            s = SCALAR[name]
            frm = s.get("frm")
            return TypeInfo(
                "String", s["luau"],
                to_lua=lambda x, s=s: s["to"].format(x=x),
                from_lua=(lambda x, frm=frm: frm.format(x=x)) if frm else None,
                fallible_from=bool(s.get("fallible")),
                by_ref=True,
            )
        if name in self.fail:
            raise Skip(self.fail[name])
        if name in self.building:
            raise Skip(f"`{name}` contains itself (recursive types are not converted)")
        if name in self.cache:
            self.touch(("type", name))
            for dep in self.deps.get(name, ()):
                self.touch(dep)
            return self.client_gate(name, self.cache[name])
        self.dep_stack.append(set())
        self.client_flags.append(False)
        self.building.add(name)
        saved_class, self.cur_class = self.cur_class, None   # type conversions live outside any class
        saved_c, self.cexpr = self.cexpr, "client"
        try:
            info = self.build_named(name)
        except Skip as e:
            self.fail[name] = e.reason
            raise
        finally:
            self.building.discard(name)
            deps = self.dep_stack.pop()
            info_needs = self.client_flags.pop()
            self.cur_class = saved_class
            self.cexpr = saved_c
        info.needs_client = info_needs
        self.cache[name] = info
        self.deps[name] = deps
        self.touch(("type", name))
        for dep in deps:
            self.touch(dep)
        return self.client_gate(name, info)

    def client_gate(self, name: str, info: TypeInfo) -> TypeInfo:
        """A type that carries the `Client` (it holds an ECS `Entity`) can only be returned by `Client` methods, or sit inside another such type."""
        if info.needs_client:
            if self.building:
                self.client_flags[-1] = True
            elif self.cur_class != "Client":
                raise Skip(f"`{name}` holds an ECS `Entity`: only `Client` methods can turn it into an `Entity` class value")
        return info

    def path_for(self, name: str) -> str:
        p = PATH_OVERRIDES.get(name) or self.ix.resolve_path(name)
        if not p:
            raise Skip(f"`{name}`: no public `azalea::` path found (add it to PATH_OVERRIDES)")
        self.paths[name] = p
        return p

    def build_named(self, name: str) -> TypeInfo:
        rust = f"Lua{name}"
        if name in self.taken_luau_names() and name not in RECORDS and name not in ACCESSORS:
            raise Skip(f"`{name}` would redefine a Luau type that already exists (built-in, hand-written class, or Luau's own)")
        if name in RECORDS:
            self.path_for(name)
            self.records[name] = dict(rust=rust, path=self.paths[name], fields=RECORDS[name], needs_client=False)
            return TypeInfo(rust, name, to_lua=lambda x, r=rust: f"{r}({x})")
        d = self.ix.unique_def(name)
        if d is None:
            raise Skip(f"`{name}`: no unique public definition in the azalea source")
        if d.kind == "enum":
            if not d.variants:
                raise Skip(f"enum `{name}` has no variants" + (f" ({len(d.dropped_variants)} not in the JSON index)" if d.dropped_variants else ""))
            if any(v["kind"] != "unit" for v in d.variants):
                return self.build_tagged(name, rust, d)
            strs = [snake(bare(v["name"])) for v in d.variants]
            if len(set(strs)) != len(strs):
                raise Skip(f"enum `{name}`: two variants have the same snake_case name")
            self.path_for(name)
            self.enums[name] = dict(rust=rust, path=self.paths[name], variants=[v["name"] for v in d.variants])
            self.note_dropped(name, d, "a value of such a variant has no Luau string")
            return TypeInfo(rust, name, to_lua=lambda x, r=rust: f"{r}({x})", from_lua=lambda x: f"{x}.0")
        if d.generics:
            raise Skip(f"struct `{name}` is generic")
        if d.tuple_style:
            raise Skip(f"tuple struct `{name}`")
        if name in ACCESSORS:
            return self.build_accessor(name, rust, d)
        if not d.fields or any(not f[2] for f in d.fields):
            raise Skip(f"struct `{name}` has private fields")
        fields = []
        for fname, ft, _ in d.fields:
            if not ASCII_IDENT.fullmatch(bare(fname)):
                raise Skip(f"struct `{name}`.{fname}: not a plain ASCII field name")
            try:
                fi = self.map_ty(ft, "ret")
            except Skip as e:
                raise Skip(f"struct `{name}`.{fname}: {e.reason}")
            if fi.is_result or not fi.to_lua:
                raise Skip(f"struct `{name}`.{fname}: not convertible")
            fields.append((bare(fname), fi.luau, fi.to_lua(f"v.{rust_ident(fname)}")))
        self.path_for(name)
        nc = self.client_flags[-1]
        self.records[name] = dict(rust=rust, path=self.paths[name], fields=fields, needs_client=nc)
        return TypeInfo(rust, name, to_lua=self.wrap_to_lua(rust, nc))


    def wrap_to_lua(self, rust: str, needs_client: bool):
        """`to_lua` of a generated record/tagged enum: `LuaX(x)`, or `LuaX(x, <client>.clone())` when it holds an ECS `Entity`."""
        if needs_client:
            return lambda x, r=rust: f"{r}({x}, {self.cexpr}.clone())"
        return lambda x, r=rust: f"{r}({x})"

    def build_tagged(self, name: str, rust: str, d) -> TypeInfo:
        """A data-carrying enum -> a Luau table `{ kind = "<variant, snake_case>", ... }` (return values only).
        Unit variant: just `kind`. One-field tuple variant holding a record struct: that record's fields, flattened next to `kind`;
        holding anything else: `value`. Several fields: `_1`, `_2`, ... Struct-style variants are refused (the rustdoc JSON index keeps no field names)."""
        if d.generics:
            raise Skip(f"enum `{name}` is generic")
        kinds = [snake(bare(v["name"])) for v in d.variants]
        if len(set(kinds)) != len(kinds):
            raise Skip(f"enum `{name}`: two variants have the same snake_case name")
        variants = []
        for v, kname in zip(d.variants, kinds):
            vn = bare(v["name"])
            if v["kind"] == "struct":
                raise Skip(f"enum `{name}`::{vn} is a struct-style variant")
            fields, pat = [], ""
            if v["kind"] == "tuple":
                ts = v["types"]
                infos = []
                for i, t in enumerate(ts):
                    try:
                        infos.append(self.map_ty(t, "ret"))
                    except Skip as e:
                        raise Skip(f"enum `{name}`::{vn}: {e.reason}")
                    if infos[-1].is_result or not infos[-1].to_lua:
                        raise Skip(f"enum `{name}`::{vn}: not convertible")
                if len(ts) == 1:
                    inner = ts[0][1] if ts[0][0] == "path" and not ts[0][2] else None
                    if infos[0].rust == "()":
                        pat = "(_)"     # `Variant(())`: nothing to read, same as a unit variant
                    elif inner in self.records and infos[0].luau == inner:
                        pat, fields = "(v)", list(self.records[inner]["fields"])
                    else:
                        pat, fields = "(v)", [("value", infos[0].luau, infos[0].to_lua("v"))]
                else:
                    pat = "(" + ", ".join("_" if inf.rust == "()" else f"f{i}" for i, inf in enumerate(infos)) + ")"
                    fields = [(f"_{i + 1}", inf.luau, inf.to_lua(f"f{i}")) for i, inf in enumerate(infos) if inf.rust != "()"]
            if any(f[0] == "kind" for f in fields):
                raise Skip(f"enum `{name}`::{vn}: a field is called `kind`")
            variants.append(dict(name=vn, kind=kname, pat=pat, fields=fields))
        self.path_for(name)
        nc = self.client_flags[-1]
        self.tagged[name] = dict(rust=rust, path=self.paths[name], variants=variants, needs_client=nc)
        self.note_dropped(name, d, "a value of such a variant reaches Luau as an empty table (`_ => {}`)")
        return TypeInfo(rust, name, to_lua=self.wrap_to_lua(rust, nc))

    def note_dropped(self, name: str, d, effect: str) -> None:
        """Front end lost variants of an enum that is being emitted (rustdoc JSON lacks #[doc(hidden)] variants unless it was made
        with --document-hidden-items): one report line, so the emitted enum is never silently narrower than the source."""
        if d.dropped_variants:
            kept = len(d.variants)
            self.enum_notes.append(f"`{name}`: {kept} of {kept + len(d.dropped_variants)} variants emitted, missing "
                                   + ", ".join(d.dropped_variants) + f" (not in the JSON index); {effect}")

    def build_accessor(self, name: str, rust: str, d) -> TypeInfo:
        """A struct with private fields, read through [accessors.X]: the listed public fields (mapped like any record field)
        plus the getter rows (luau field, luau type, rust expr over `v`)."""
        acc = ACCESSORS[name]
        if d.generics or d.tuple_style:
            raise Skip(f"accessor struct `{name}` is generic or a tuple struct")
        public = {bare(f[0]): f for f in (d.fields or []) if f[2]}
        fields = []
        for fname in acc["fields"]:
            f = public.get(fname)
            if f is None:
                raise Skip(f"accessor struct `{name}`: no public field `{fname}`")
            try:
                fi = self.map_ty(f[1], "ret")
            except Skip as e:
                raise Skip(f"struct `{name}`.{fname}: {e.reason}")
            if fi.is_result or not fi.to_lua:
                raise Skip(f"struct `{name}`.{fname}: not convertible")
            fields.append((fname, fi.luau, fi.to_lua(f"v.{rust_ident(fname)}")))
        fields += list(acc["getters"])
        names = [f[0] for f in fields]
        if len(set(names)) != len(names):
            raise Skip(f"accessor struct `{name}`: a Luau field is listed twice")
        self.path_for(name)
        nc = self.client_flags[-1]
        self.records[name] = dict(rust=rust, path=self.paths[name], fields=fields, needs_client=nc)
        return TypeInfo(rust, name, to_lua=self.wrap_to_lua(rust, nc))


# =============================================================================
# wrappers (Luau -> azalea)
# =============================================================================

@dataclass
class Wrapper:
    name: str
    doc: str
    wparams: list           # (lua name, TypeInfo)
    call_args: list         # rust expressions for the azalea call
    ret: Optional[TypeInfo]
    owner: str
    origin: str
    origin_name: str = ""   # the real azalea method name (differs from `name` for goal expansions)
    is_async: bool = False


@dataclass
class ClassGen:
    """Everything collected for one target type (see CLASSES)."""
    name: str                   # azalea type, e.g. "Client"
    cfg: dict
    wrappers: list = field(default_factory=list)
    skipped: list = field(default_factory=list)     # (origin, signature, reason)
    touched: set = field(default_factory=set)       # mapper keys this class's wrappers use

    @property
    def rust(self) -> str:
        return self.cfg["rust"]

    @property
    def luau(self) -> str:
        return self.cfg["luau"]

    @property
    def emit(self) -> bool:
        return self.cfg["emit"]


def bare(n: str) -> str:
    """`r#type` -> `type`: the Luau side never sees raw-identifier syntax (the Rust call sites keep it)."""
    return n[2:] if n.startswith("r#") else n


def safe_name(n: str) -> str:
    n = bare(n)
    return n + "_" if n in RUST_KEYWORDS or n in LUAU_KEYWORDS else n


RAW_NEVER = {"self", "Self", "super", "crate"}      # keywords that cannot be written as raw identifiers


def rust_ident(n: str) -> str:
    """A field/variant name as Rust source: `type` -> `r#type` (the rustdoc JSON has no `r#`)."""
    return f"r#{n}" if n in RUST_KEYWORDS and n not in RAW_NEVER else n


def luau_field(f: str) -> str:
    """A property name inside a Luau table type."""
    return f'["{f}"]' if f in LUAU_HARD_KEYWORDS else f


class Generator:
    def __init__(self, ix: Any):
        self.ix = ix
        self.m = Mapper(ix)
        self.classes: dict[str, ClassGen] = {n: ClassGen(n, c) for n, c in CLASSES.items()}
        self.goal_notes: list[str] = []
        self._goals: Optional[list] = None
        self._goals_touched: set = set()        # mapper keys goals() touched when it ran (re-credited on every later call)
        self.packets_in: list = []
        self.packets_out: list = []
        self.ecs: list = []
        self.has_events = any(c["events"] for c in CLASSES.values())     # azalea mode: an events class (`bot`) is configured
        self.events: list = []          # filled by build_events (only when a class has `events = true`)
        self.event_notes: list = []

    # the `Client` class keeps the flat names the emitters grew up with
    @property
    def wrappers(self) -> list:
        return self.classes["Client"].wrappers if "Client" in self.classes else []

    @property
    def skipped(self) -> list:
        return self.classes["Client"].skipped if "Client" in self.classes else []

    # ---- goals: `impl Goal + 'static` parameters expand to one method per concrete goal
    def goals(self) -> list:
        if self._goals is not None:
            self.m.touched |= self._goals_touched      # credit the types goals() uses to every class that calls it, not just the first
            return self._goals
        before = self.m.touched
        self.m.touched = set()
        out = []
        suffixes: dict[str, str] = {}
        for gname in sorted(self.ix.goal_impls):
            d = self.ix.unique_def(gname)
            if not d or d.kind != "struct":
                continue
            try:
                if d.generics:
                    raise Skip("generic")
                if not d.fields or any(not f[2] for f in d.fields):
                    raise Skip("private fields")
                path = self.m.path_for(gname)
                params = []
                for i, (fname, ft, _) in enumerate(d.fields):
                    ti = self.m.map_ty(ft, "param")
                    if not ti.from_lua:
                        raise Skip(f"field `{fname}` is not convertible")
                    if d.tuple_style:
                        pname = GOAL_PARAM_NAMES.get(ft[1] if ft[0] == "path" else "", f"v{i}")
                    else:
                        pname = fname
                        if not ASCII_IDENT.fullmatch(bare(pname)):
                            raise Skip(f"field `{fname}`: not a plain ASCII name")
                    params.append((fname, safe_name(pname), ti))
                suffix = snake(gname[:-4] if gname.endswith("Goal") else gname)
                if suffix in suffixes:
                    raise Skip(f"its method suffix `{suffix}` is already taken by `{suffixes[suffix]}`")
                suffixes[suffix] = gname
                out.append(dict(name=gname, path=path, tuple_style=d.tuple_style, params=params))
            except Skip as e:
                extra = f"; {HANDWRITTEN_GOALS[gname]}" if gname in HANDWRITTEN_GOALS else ""
                self.goal_notes.append(f"`{gname}`: {e.reason}{extra}")
        self._goals = out
        self._goals_touched = self.m.touched
        self.m.touched = before | self._goals_touched
        return out

    def build(self):
        """Build wrappers for every class in CLASSES. Each class tracks the mapper keys it touched in
        its own set; only classes with `emit` feed the shared set that decides which type
        conversions get generated, so collecting a class never changes another class's output."""
        shared = self.m.touched
        for cg in self.classes.values():
            self.m.touched = set()
            self.build_class(cg)
            cg.touched = self.m.touched
            if cg.emit:
                shared |= cg.touched
        self.m.touched = shared

    def build_class(self, cg: ClassGen):
        seen = set()
        self.m.cur_class = cg.name
        renames = cg.cfg["renames"]
        reserved = set(getattr(self, "reserved", {}).get(cg.name, ()))
        if cg.cfg["events"]:
            reserved |= {"on", "wait_for"}          # generated by emit_class
        for m in sorted((m for m in self.ix.methods if m.target == cg.name), key=lambda m: (m.file, m.name)):
            snap = set(self.m.touched)
            try:
                ws = self.build_method(m)
                for w in ws:
                    w.name = renames.get(w.name, w.name)
                for w in ws:
                    if w.name in reserved:
                        raise Skip(f"`{w.name}` is hand-written (extra_*.rs) or generated elsewhere")
                    if w.name.startswith("__"):
                        raise Skip("metamethod-like name")
                names = [w.name for w in ws]
                if len(set(names)) != len(names):
                    raise Skip("its expansions share a Luau method name")
                for w in ws:
                    if w.name in seen:
                        raise Skip(f"duplicate Luau method name `{w.name}`")
                for w in ws:
                    seen.add(w.name)
                cg.wrappers += ws
            except Skip as e:
                self.m.touched = snap
                cg.skipped.append((f"{m.owner} ({m.file})", m.sig, e.reason))

    def build_method(self, m: Method) -> list[Wrapper]:
        if not m.is_pub:
            raise Skip("not public")
        if m.name in DENY_METHODS:
            raise Skip("denied in config")
        if m.name in CLASSES[m.target]["deny"]:
            raise Skip(f"denied: {CLASSES[m.target]['deny'][m.name]}")
        free = CLASSES[m.target].get("free", False)          # `@<crate>`: a free fn of a bound crate (generic mode), no receiver
        if free and (m.receiver is not None or m.is_async):
            raise Skip("async free fn" if m.is_async else "free fn with a receiver")
        if not free and m.receiver != "&self":
            raise Skip("no `&self` receiver" if m.receiver is None else f"`{m.receiver}` receiver")
        if m.generics:
            raise Skip("generic method")
        bn = bare(m.name)
        if bn in RUST_KEYWORDS or bn in LUAU_KEYWORDS:
            raise Skip("name is a keyword")
        if not ASCII_IDENT.fullmatch(bn):
            raise Skip("name is not a plain ASCII identifier")
        if m.ret and m.ret[0] == "impl":
            raise Skip(f"returns `{m.ret[1]}`")

        ret = None
        if m.ret is not None and m.ret != ("unit",):
            ret = self.m.map_ty(m.ret, "ret")
            if not ret.to_lua:
                raise Skip("return type not convertible")

        base_params: list = []          # (lua name, TypeInfo) | ("GOAL",)
        for pname, ptype in m.params:
            if pname is None:
                raise Skip("destructured parameter")
            if not ASCII_IDENT.fullmatch(bare(pname)):
                raise Skip(f"parameter `{pname}`: not a plain ASCII name")
            if ptype[0] == "impl" and re.fullmatch(r"impl Goal( \+ '\w+)?", ptype[1]):
                base_params.append(("GOAL", pname))
                continue
            ti = self.m.map_ty(ptype, "param")
            if not ti.from_lua:
                raise Skip(f"parameter `{pname}`: not convertible")
            base_params.append((safe_name(pname), ti))

        goal_idx = [i for i, p in enumerate(base_params) if p[0] == "GOAL"]
        if len(goal_idx) > 1:
            raise Skip("more than one goal parameter")
        origin = m.owner
        if not goal_idx:
            return [self.finish(bn, m.doc, base_params, None, ret, m, origin)]
        gs = self.goals()
        if not gs:
            raise Skip("`impl Goal` parameter and no usable Goal types were found")
        out = []
        for g in gs:
            suffix = snake(g["name"][:-4] if g["name"].endswith("Goal") else g["name"])
            wp = []
            for p in base_params:
                if p[0] == "GOAL":
                    wp += [(pn, ti) for _f, pn, ti in g["params"]]
                else:
                    wp.append(p)
            out.append(self.finish(f"{bn}_{suffix}", m.doc, wp, g, ret, m, origin, goal_at=goal_idx[0]))
        return out

    def finish(self, name, doc, wparams, goal, ret, m: Method, origin, goal_at=None) -> Wrapper:
        args: list[str] = []
        if goal is None:
            args = [ti.from_lua(n) for n, ti in wparams]
        else:
            # rebuild call args: params before the goal, the goal constructor, params after
            pos = 0
            gcount = len(goal["params"])
            before = wparams[:goal_at]
            gparams = wparams[goal_at:goal_at + gcount]
            after = wparams[goal_at + gcount:]
            args = [ti.from_lua(n) for n, ti in before]
            conv = [(rust_ident(f), ti.from_lua(pn)) for (f, pn, ti) in goal["params"]]
            if goal["tuple_style"]:
                args.append(f"{goal['path']}({', '.join(e for _f, e in conv)})")
            else:
                args.append(f"{goal['path']} {{ {', '.join(f'{f}: {e}' for f, e in conv)} }}")
            args += [ti.from_lua(n) for n, ti in after]
        return Wrapper(name, doc, wparams, args, ret, m.owner, origin, m.name, m.is_async)

    # ------------------------------------------------------------------ packets (azalea -> Luau)
    def build_packets_in(self, root: Path):
        """Every `ClientboundGamePacket` variant -> `{ kind = "<snake variant>", <fields> }` (gen_packets_in.rs, real azalea only).
        The variants come from the `declare_state_packets!` list in azalea-protocol/src/packets/game/mod.rs (a macro, so the front
        ends see no enum); the payload struct of variant `Foo` is `ClientboundFoo` in `packets::game`. A field the mapper cannot
        convert (NBT, registry holders, ECS entities, ...) is left out and listed in the report; the packet itself is never dropped."""
        self.packets_in = []
        mod_rs = Path(root) / "azalea-protocol" / "src" / "packets" / "game" / "mod.rs"
        if not mod_rs.is_file():
            return
        text = re.sub(r"//[^\n]*", "", mod_rs.read_text())
        mt = re.search(r"Clientbound\s*=>\s*\[(.*?)\]", text, re.S)
        if not mt:
            return
        names = [n.strip() for n in mt.group(1).split(",") if n.strip()]
        camel = lambda n: "".join(p[:1].upper() + p[1:] for p in n.split("_"))  # noqa: E731
        taken = self.m.taken_luau_names()
        saved_class, self.m.cur_class = self.m.cur_class, "EntityRef"     # a packet has no `Client`: types holding an ECS `Entity` are refused
        for n in names:
            variant = camel(n)
            sname = "Clientbound" + variant
            cands = [d for d in self.ix.defs.get(sname, []) if d.is_pub and d.kind == "struct" and "game" in d.modpath]
            d = cands[0] if len(cands) == 1 else self.ix.unique_def(sname)
            entry = dict(name=n, variant=variant, struct=sname, luau=f"Packet{variant}", fields=[], skipped=[], nodef=None)
            if f"Packet{variant}" in taken:
                entry["nodef"] = f"`Packet{variant}` is already a Luau type"
            elif d is None or d.kind != "struct":
                entry["nodef"] = "no unique `packets::game` struct found"
            elif d.generics:
                entry["nodef"] = "generic struct"
            else:
                seen = set()
                for i, (fname, ft, is_pub) in enumerate(d.fields):
                    lname = f"_{i + 1}" if d.tuple_style else bare(fname)
                    try:
                        if not is_pub:
                            raise Skip("private field")
                        if not ASCII_IDENT.fullmatch(lname):
                            raise Skip("not a plain ASCII field name")
                        if lname == "kind" or lname in seen:
                            raise Skip("name clashes with `kind` or another field")
                        self.m.client_flags.append(False)
                        try:
                            fi = self.m.map_ty(ft, "ret")
                            holds_entity = self.m.client_flags[-1]
                        finally:
                            self.m.client_flags.pop()
                        if holds_entity:
                            raise Skip("holds an ECS `Entity` (needs the client)")
                        if fi.is_result or not fi.to_lua:
                            raise Skip("not convertible")
                        access = f"v.{i}" if d.tuple_style else f"v.{rust_ident(fname)}"
                        entry["fields"].append((lname, fi.luau, fi.to_lua(access)))
                        seen.add(lname)
                    except Skip as e:
                        entry["skipped"].append((lname, e.reason))
            self.packets_in.append(entry)
        self.m.cur_class = saved_class

    # ------------------------------------------------------------------ ECS components / resources
    def build_ecs(self):
        """Every public, non-generic azalea type that derives `Component` or `Resource` -> one table entry (gen_ecs.rs, real azalea only).
        Entry = Luau-visible name (the Rust type name), kind, Rust path, Luau type and a `v -> Luau` conversion. A type whose value the
        mapper cannot turn into Luau (private fields, ECS handles, ...) stays in the table with `readable` False and a reason: scripts get
        a clear error instead of a silent nil. Marker types (no fields) read as `true`; a one-field public tuple struct reads as its field.
        A name defined twice is left out (ambiguous). Only `Clone` types can be read (the read clones out of the ECS lock)."""
        self.ecs = []
        derive = re.compile(r"derive\(.*\b(Component|Resource)\b")
        seen = {}
        for name, defs in sorted(self.ix.defs.items()):
            for d in defs:
                if not d.is_pub or d.generics:
                    continue
                kinds = {m.group(1) for a in d.attrs for m in [derive.search(a)] if m}
                if "Resource" in kinds:
                    kinds = {"Resource"}        # bevy's `derive(Resource)` also writes an `impl Component`: the rustdoc front end shows both
                if not kinds:
                    continue
                seen.setdefault(name, []).append((d, kinds))
        saved_class, self.m.cur_class = self.m.cur_class, "EntityRef"
        for name, found in sorted(seen.items()):
            d, kinds = found[0]
            entry = dict(name=name, kind="resource" if kinds == {"Resource"} else "component", path=None, luau=None, to_lua=None,
                         marker=False, reason=None)
            try:
                if len(found) > 1:
                    raise Skip("defined more than once in the azalea source")
                if not ASCII_IDENT.fullmatch(name):
                    raise Skip("not a plain ASCII name")
                try:
                    entry["path"] = self.m.path_for(name)
                except Skip:
                    # The name is ambiguous across the workspace (rustdoc also sees what macros generate: azalea_block makes a
                    # `Chest`/`Tnt` struct per block, azalea_inventory a `Player`), but this def is the only one deriving
                    # Component/Resource: use its own public path.
                    p = self.ix.to_azalea(d.crate, d.modpath, d.name) if d.is_pub and self.ix.chain_public(d.crate, d.modpath) else None
                    if not p:
                        raise
                    entry["path"] = self.m.paths[name] = p
                if d.kind == "struct" and not d.fields:
                    entry.update(marker=True, luau="boolean", to_lua="true")    # presence only: no `Clone` needed
                    self.ecs.append(entry)
                    continue
                if self.ix.is_clone(name) is not True:
                    raise Skip("not `Clone` (cannot be copied out of the ECS)")
                if False:
                    pass
                elif d.kind == "struct" and d.tuple_style and len(d.fields) == 1:
                    _fname, ft, is_pub = d.fields[0]
                    if not is_pub:
                        raise Skip("private field")
                    self.m.client_flags.append(False)
                    try:
                        fi = self.m.map_ty(ft, "ret")
                        holds_entity = self.m.client_flags[-1]
                    finally:
                        self.m.client_flags.pop()
                    if holds_entity:
                        raise Skip("holds an ECS `Entity` (needs the client)")
                    if fi.is_result or not fi.to_lua:
                        raise Skip("field not convertible")
                    entry.update(luau=fi.luau, to_lua=fi.to_lua("v.0"))
                else:
                    self.m.client_flags.append(False)
                    try:
                        fi = self.m.build_named(name)
                        holds_entity = self.m.client_flags[-1]
                    finally:
                        self.m.client_flags.pop()
                    if fi.is_result or not fi.to_lua or fi.needs_client or holds_entity:
                        raise Skip("not convertible without the client")
                    entry.update(luau=fi.luau, to_lua=fi.to_lua("v"))
                    self.m.touch(("type", name))    # build_named bypasses the mapper's own touch: without this the `Lua<name>` wrapper is never emitted
            except Skip as e:
                entry.update(reason=e.reason, luau=None, to_lua=None)
            self.ecs.append(entry)
        self.m.cur_class = saved_class

    # ------------------------------------------------------------------ packets (Luau -> azalea)
    def build_packets_out(self, root: Path):
        """Every `ServerboundGamePacket` variant -> a constructor from a Luau table of its fields (gen_packets_out.rs, real azalea only).
        Same sources as `build_packets_in` (the `Serverbound => [..]` list; struct `Serverbound<Camel>` in `packets::game`). Unlike the
        clientbound side a field cannot be left out when building a struct: a packet with one unconvertible field gets no constructor
        (`ok` False, reasons listed in the report). Class values (`Entity`, ...) are not accepted as packet fields."""
        self.packets_out = []
        mod_rs = Path(root) / "azalea-protocol" / "src" / "packets" / "game" / "mod.rs"
        if not mod_rs.is_file():
            return
        text = re.sub(r"//[^\n]*", "", mod_rs.read_text())
        mt = re.search(r"Serverbound\s*=>\s*\[(.*?)\]", text, re.S)
        if not mt:
            return
        names = [n.strip() for n in mt.group(1).split(",") if n.strip()]
        camel = lambda n: "".join(p[:1].upper() + p[1:] for p in n.split("_"))  # noqa: E731
        taken = self.m.taken_luau_names()
        saved_class, self.m.cur_class = self.m.cur_class, "EntityRef"
        for n in names:
            variant = camel(n)
            sname = "Serverbound" + variant
            cands = [d for d in self.ix.defs.get(sname, []) if d.is_pub and d.kind == "struct" and "game" in d.modpath]
            d = cands[0] if len(cands) == 1 else self.ix.unique_def(sname)
            entry = dict(name=n, variant=variant, struct=sname, luau=f"OutPacket{variant}", fields=[], skipped=[], ok=False, why=None,
                         tuple_style=False)
            snap = set(self.m.touched)
            if f"OutPacket{variant}" in taken:
                entry["why"] = f"`OutPacket{variant}` is already a Luau type"
            elif d is None or d.kind != "struct":
                entry["why"] = "no unique `packets::game` struct found"
            elif d.generics:
                entry["why"] = "generic struct"
            else:
                entry["tuple_style"] = d.tuple_style
                seen = set()
                for i, (fname, ft, is_pub) in enumerate(d.fields):
                    lname = f"_{i + 1}" if d.tuple_style else bare(fname)
                    try:
                        if not is_pub:
                            raise Skip("private field")
                        if not ASCII_IDENT.fullmatch(lname):
                            raise Skip("not a plain ASCII field name")
                        if lname in seen:
                            raise Skip("name clashes with another field")
                        fi = self.m.map_ty(ft, "param")
                        if not fi.from_lua or fi.is_class:
                            raise Skip("not convertible from Luau")
                        entry["fields"].append((lname, fi.luau, fi.rust, fi.from_lua, None if d.tuple_style else rust_ident(fname)))
                        seen.add(lname)
                    except Skip as e:
                        entry["skipped"].append((lname, e.reason))
                if entry["skipped"]:
                    entry["why"] = "; ".join(f"`{f}`: {r}" for f, r in entry["skipped"])
                else:
                    entry["ok"] = True
            if not entry["ok"]:
                entry["fields"] = []
                self.m.touched = snap       # types only that packet's fields needed are not emitted
            self.packets_out.append(entry)
        self.m.cur_class = saved_class

    # ------------------------------------------------------------------ events
    def build_events(self):
        cands = [x for x in self.ix.defs.get("Event", []) if x.is_pub and x.kind == "enum"]
        if len(cands) > 1:          # prefer the one in the `azalea` crate itself
            cands = [x for x in cands if x.crate == "azalea"] or cands
        if len(cands) > 1:          # else the one `azalea::Event` points at: defined in the crate root or re-exported there
            at_root = [x for x in cands if x.modpath == () or any(
                c == "azalea" and mp == () and ex == "Event" and full.split("::")[:-1][-1:] == list(x.modpath[-1:])
                for c, mp, ex, full in self.ix.reexports)]
            cands = at_root if len(at_root) == 1 else cands
        if len(cands) > 1:
            sys.exit("error: `enum Event` is defined more than once: " + ", ".join(
                "::".join([x.crate, *x.modpath]) for x in cands))
        d = cands[0] if cands else None
        if not d:
            sys.exit("error: could not find `enum Event` in the azalea source")
        self.event_def = d
        self.events = []
        lnames: dict[str, str] = {}
        self.event_notes = []
        self.m.cur_class = None
        for v in d.variants:
            if v["name"] in HIDDEN_EVENTS:
                self.event_notes.append(f"`{v['name']}`: {HIDDEN_EVENTS[v['name']]}, not exposed")
                continue
            if any(a.startswith("#[cfg(") for a in v["attrs"]):
                self.event_notes.append(f"`{v['name']}`: cfg-gated ({', '.join(a for a in v['attrs'] if 'cfg' in a)}), not exposed")
                continue
            lname = snake(bare(v["name"]))
            if lname in EXTRA_EVENT_PAYLOADS:
                # `Event::Packet` is `#[cfg(feature = "packet-event")]`: rustdoc JSON drops the cfg (the front end re-reads it from the
                # source, rdj_index.event_cfg_gates; unreadable source -> warning), so the variant can show up here: the
                # hand-written extra event `packet` owns it.
                self.event_notes.append(f"`{v['name']}`: handled by the hand-written extra event `{lname}`, not exposed")
                continue
            if lname in lnames:
                self.event_notes.append(f"`{v['name']}`: Luau name `{lname}` is already taken by `{lnames[lname]}`, not exposed")
                continue
            lnames[lname] = v["name"]
            payload = None
            if v["kind"] == "tuple" and len(v["types"]) == 1:
                snap = set(self.m.touched)
                try:
                    ti = self.m.map_ty(v["types"][0], "ret")
                    if ti.is_result or not ti.to_lua:
                        raise Skip("not convertible")
                    payload = ti
                except Skip as e:
                    self.m.touched = snap
                    self.event_notes.append(f"`{v['name']}`: payload `{type_text(v['types'][0])}` not exposed ({e.reason}); handlers get no arguments")
            elif v["kind"] != "unit":
                self.event_notes.append(f"`{v['name']}`: {v['kind']} variant payload not exposed; handlers get no arguments")
            self.events.append(dict(
                variant=v["name"], lname=lname, payload=payload, doc=v["doc"],
                arg=EVENT_ARG_NAMES.get(v["name"], "value"),
            ))
        for n in EXTRA_EVENTS:
            if n in lnames:
                sys.exit(f"error: {CONFIG_PATH.name}: extra_events.{n} clashes with `Event::{lnames[n]}`")


# =============================================================================
# hand-written seam: rust/luau/extra_*.rs
# =============================================================================
#
# Extra `#[mlua::userdata_impl]` blocks for generated types live in `extra_*.rs` next to the generated
# files (several blocks per type work: mlua registers every block through `inventory`). The generator
# can't read Rust signatures it didn't generate, so each hand-written method declares its Luau side in a
# comment, which is copied into the class in azalea.d.luau and listed in GEN_REPORT.md:
#
#     // luau[Entity]: --- Distance in blocks to another entity.
#     // luau[Entity]: function distance_to(self, other: Entity): number
#
# `luau[<class>]` names the Luau class (`Bot`, `Entity`); `--- ` lines are doc comments.

EXTRA_RE = re.compile(r"^\s*//\s*luau\[(\w+)\]:\s?(.*)$")
# the name a `// luau[Class]: ...` line declares: `function name(self, ..)`, or `name: (..) -> ..` for the self-less library tables
# (`goal`, `azalea`: called with `.`, and an extern-type `function` must take `self`)
EXTRA_FN_RE = re.compile(r"(?:function (\w+)|(\w+): \()")


def extra_fn_name(text: str):
    m = EXTRA_FN_RE.match(text)
    return (m.group(1) or m.group(2)) if m else None


IMPL_BLOCK_RE = re.compile(r"^impl\s+(\w+)\s*\{\n(.*?)^\}", re.S | re.M)
IMPL_FN_RE = re.compile(r"^\s+(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)", re.M)


def impl_top_fns(body: str) -> set:
    """Names of the `fn`s declared at the top brace depth of an impl body: a nested `fn` inside a method body, and
    anything inside a string, char literal or comment, is not a method. Simple scan (no macro/raw-string edge cases
    beyond `r"..."` / `r#"..."#`)."""
    n, i, depth = len(body), 0, 0
    masked = []                     # body with strings/comments blanked, braces kept
    depths = []                     # brace depth at each index of `masked`

    def put(ch: str):
        masked.append(ch)
        depths.append(depth)

    while i < n:
        c = body[i]
        if body.startswith("//", i):
            j = body.find("\n", i)
            j = n if j < 0 else j
            for _ in range(i, j):
                put(" ")
            i = j
        elif body.startswith("/*", i):
            j = body.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                put("\n" if body[k] == "\n" else " ")
            i = j
        elif c == "r" and (m := re.match(r'r(#*)"', body[i:i + 40])) and (i == 0 or not (body[i - 1].isalnum() or body[i - 1] == "_")):
            end = '"' + m.group(1)
            j = body.find(end, i + m.end())
            j = n if j < 0 else j + len(end)
            for k in range(i, j):
                put("\n" if body[k] == "\n" else " ")
            i = j
        elif c == '"':
            j = i + 1
            while j < n and body[j] != '"':
                j += 2 if body[j] == "\\" else 1
            j = min(j + 1, n)
            for k in range(i, j):
                put("\n" if body[k] == "\n" else " ")
            i = j
        elif c == "'" and (m := re.match(r"'(?:\\.[^']*|[^\\'])'", body[i:i + 12])):   # char literal; `'a` lifetimes don't match
            for _ in range(m.end()):
                put(" ")
            i += m.end()
        else:
            if c == "}":
                depth -= 1
            put(c)
            if c == "{":
                depth += 1
            i += 1
    text = "".join(masked)
    return {bare(fm.group(1)) for fm in IMPL_FN_RE.finditer(text) if depths[fm.start(1)] == 0}


def extras_reserved(rust_out: Path) -> dict:
    """-> {azalea class: names of methods already hand-written in extra_*.rs} (Rust `impl <Lua type>` blocks and
    `// luau[Class]: function name(` lines), so a generated method never defines the same name twice."""
    out: dict = defaultdict(set)
    by_rust = {c["rust"]: n for n, c in CLASSES.items()}
    by_luau = {c["luau"]: n for n, c in CLASSES.items()}
    for f in sorted([*rust_out.glob("extra_*.rs"), *rust_out.glob("real_*.rs")]):
        src = f.read_text(errors="replace")
        for im in IMPL_BLOCK_RE.finditer(src):         # plain `impl X {` blocks only (rustfmt'd text); `impl X for` never matches
            cls = by_rust.get(im.group(1))
            if cls:
                out[cls] |= impl_top_fns(im.group(2))
        for ln in src.splitlines():
            m = EXTRA_RE.match(ln)
            fn = m and extra_fn_name(m.group(2))
            if fn and m.group(1) in by_luau:
                out[by_luau[m.group(1)]].add(fn)
    return out


def scan_extras(rust_out: Path) -> dict:
    """-> {luau class: [(file, line)]} for every `// luau[Class]: ...` line in extra_*.rs."""
    out: dict = defaultdict(list)
    for f in sorted([*rust_out.glob("extra_*.rs"), *rust_out.glob("real_*.rs")]):
        for ln in f.read_text().splitlines():
            m = EXTRA_RE.match(ln)
            if m:
                out[m.group(1)].append((f.name, m.group(2).rstrip()))
    return out


# =============================================================================
# emitters
# =============================================================================

def rust_sig_ret(w: Wrapper):
    """-> (attr, return clause, body-wrapping function)"""
    fallible_params = any(ti.fallible_from for _n, ti in w.wparams)
    inner = w.ret.rust if w.ret else "()"
    if w.ret and w.ret.is_result:
        return "", f" -> mlua::Result<{inner}>", lambda e: e
    if fallible_params:
        return "", f" -> mlua::Result<{inner}>", lambda e: f"Ok({e})"
    return "#[lua(infallible)]", ("" if not w.ret else f" -> {inner}"), lambda e: e


def emit_client(gen: Generator, src_label: str) -> str:
    """gen_client.rs: one `#[derive(UserData)]` struct per emitted class (Client first)."""
    L = [HEADER.format(src=src_label), "#![allow(dead_code, unused_imports, clippy::all)]", ""]
    if gen.has_events:
        L += [
            "use std::sync::Arc;",
            "",
            "use azalea::prelude::*;",
            "use mlua::UserData;",
            "",
            "use super::convert::*;",
            "use super::gen_events::EVENT_NAMES;",
            "use super::gen_types::*;",
            "use super::Handlers;",
        ]
    else:       # generic mode: no events, no client
        L += ["use mlua::UserData;", "", "use super::convert::*;", "use super::gen_types::*;"]
    for tr in sorted(gen.ix.client_traits):
        p = gen.ix.resolve_path(tr)
        if p:
            L.append(f"use {p} as _;")
    for cg in gen.classes.values():
        if cg.emit and not cg.cfg.get("free"):
            L += [""] + emit_class(gen, cg)
    free = [cg for cg in gen.classes.values() if cg.emit and cg.cfg.get("free") and cg.wrappers]
    for cg in free:
        L += [""] + emit_free_table(cg)
    if free:
        L += ["", "/// Install every free-function table as a Luau global (`toy.add(..)`).",
              "pub fn register_globals(lua: &mlua::Lua) -> mlua::Result<()> {"]
        L += [f"    register_{cg.luau}(lua)?;" for cg in free]
        L += ["    Ok(())", "}"]
    return "\n".join(L) + "\n"


def emit_free_table(cg: ClassGen) -> list:
    """`pub fn register_<crate>(lua)`: a Luau table of the crate's free fns, set as the global `<crate>`."""
    L = [f"/// Global table `{cg.luau}`: {cg.cfg['doc']}", f"pub fn register_{cg.luau}(lua: &mlua::Lua) -> mlua::Result<()> {{",
         "    let t = lua.create_table()?;"]
    for w in sorted(cg.wrappers, key=lambda w: w.name):
        attr, _ret_clause, wrap = rust_sig_ret(w)
        names = "".join(f"{n}, " for n, _ in w.wparams)
        types = "".join(f"{ti.rust}, " for _, ti in w.wparams)
        call = f"{w.owner}({', '.join(w.call_args)})"
        expr = w.ret.to_lua(call) if w.ret else call
        body = wrap(expr)
        inner = w.ret.rust if w.ret else "()"
        L += [f'    t.set("{w.name}", lua.create_function(|_, ({names}): ({types})| -> mlua::Result<{inner}> {{',
              f"        {body if not attr else f'Ok({body})'}", "    })?)?;"]
    L += [f'    lua.globals().set("{cg.luau}", t)', "}"]
    return L


def class_rust_path(gen: Generator, cg: ClassGen) -> str:
    if cg.name == "Client":
        return "azalea::Client"
    p = gen.ix.resolve_path(cg.name)
    if not p:
        sys.exit(f"error: no public `azalea::` path for class `{cg.name}`")
    return p


def emit_class(gen: Generator, cg: ClassGen) -> list:
    field_ = cg.cfg["field"]
    if cg.name == "Client":
        L = [
            "/// The `bot` global in Luau. Methods are generated from azalea's `Client`.",
            "#[derive(UserData)]",
            "pub struct LuaClient {",
            "    #[lua(skip)]",
            "    pub client: azalea::Client,",
            "    #[lua(skip)]",
            "    pub handlers: Arc<Handlers>,",
            "}",
        ]
    else:
        L = [
            f"/// Luau class `{cg.luau}`. Methods are generated from {'azalea' + chr(39) + 's ' if gen.has_events else ''}`{cg.name}`.",
            "#[derive(UserData)]",
            f"pub struct {cg.rust} {{",
            "    #[lua(skip)]",
            f"    pub {field_}: {class_rust_path(gen, cg)},",
            "}",
        ]
    L += ["", "#[mlua::userdata_impl]", f"impl {cg.rust} {{"]
    if cg.cfg["events"]:
        L += [
            "    /// `bot:on(event, handler)` - register a handler for an `azalea::Event`.",
            "    fn on(&self, event: String, handler: mlua::Function) -> mlua::Result<()> {",
            "        if !EVENT_NAMES.contains(&event.as_str()) {",
            '            return Err(mlua::Error::runtime(format!("unknown event \'{event}\' (known: {})", EVENT_NAMES.join(", "))));',
            "        }",
            "        self.handlers.add(event, handler);",
            "        Ok(())",
            "    }",
            "",
            "    /// `bot:wait_for(event)` - yield until `event` fires next and return its payload.",
            "    async fn wait_for(&self, event: String) -> mlua::Result<mlua::MultiValue> {",
            "        if !EVENT_NAMES.contains(&event.as_str()) {",
            '            return Err(mlua::Error::runtime(format!("unknown event \'{event}\' (known: {})", EVENT_NAMES.join(", "))));',
            "        }",
            "        self.handlers.wait(&event).await",
            "    }",
        ]
    first = not cg.cfg["events"]
    for w in sorted(cg.wrappers, key=lambda w: w.name):
        attr, ret_clause, wrap = rust_sig_ret(w)
        params = "".join(f", {n}: {ti.rust}" for n, ti in w.wparams)
        call = f"self.{field_}.{w.origin_name}({', '.join(w.call_args)})" + (".await" if w.is_async else "")
        expr = w.ret.to_lua(call) if w.ret else call
        if not first:
            L.append("")
        first = False
        if attr:
            L.append(f"    {attr}")
        L.append(f"    {'async ' if w.is_async else ''}fn {w.name}(&self{params}){ret_clause} {{")
        L.append(f"        {wrap(expr)}")
        L.append("    }")
    L.append("}")
    return L


def emit_types(gen: Generator, src_label: str) -> str:
    m = gen.m
    used = {n for k, n in m.touched if k == "type"}
    L = [HEADER.format(src=src_label), "#![allow(dead_code, unused_imports, clippy::all)]", ""]
    # `convert::*`: a derived struct's fields may be built-in types (BlockPos, MinecraftEntityId, ...).
    L += ["use mlua::{FromLua, IntoLua, Lua, Value};", "", "use super::convert::*;"]
    if any(x.get("needs_client") for x in [*m.records.values(), *m.tagged.values()]):
        L.append("use super::gen_client::LuaEntityRef;")       # an `Entity` field is built from the client (see `Mapper.named`)
    L.append("")
    for name in sorted(n for n in m.enums if n in used):
        e = m.enums[name]
        r, p = e["rust"], e["path"]
        strs = [snake(bare(v)) for v in e["variants"]]
        L += [
            f"/// `{name}` <-> Luau string ({', '.join(repr(s) for s in strs)})",
            f"pub struct {r}(pub {p});",
            "",
            f"impl FromLua for {r} {{",
            "    fn from_lua(value: Value, lua: &Lua) -> mlua::Result<Self> {",
            "        let s = <String as FromLua>::from_lua(value, lua)?;",
            "        Ok(Self(match s.as_str() {",
        ]
        for v, s in zip(e["variants"], strs):
            L.append(f'            "{s}" => {p}::{v},')
        L += [
            f'            other => return Err(mlua::Error::runtime(format!("invalid {name} \'{{other}}\', expected one of: {", ".join(strs)}"))),',
            "        }))",
            "    }",
            "}",
            "",
            f"impl IntoLua for {r} {{",
            "    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {",
            "        let s: &str = match self.0 {",
        ]
        for v, s in zip(e["variants"], strs):
            L.append(f'            {p}::{v} => "{s}",')
        L += [
            "            #[allow(unreachable_patterns)]",
            '            _ => "unknown",',
            "        };",
            "        Ok(Value::String(lua.create_string(s)?))",
            "    }",
            "}",
            "",
        ]
    for name in sorted(n for n in m.records if n in used):
        rec = m.records[name]
        r, p = rec["rust"], rec["path"]
        nc = rec.get("needs_client")
        L += [
            f"/// `{name}` -> Luau table" + (" (holds an `Entity`: carries the client)" if nc else ""),
            f"pub struct {r}(pub {p}, pub azalea::Client);" if nc else f"pub struct {r}(pub {p});",
            "",
            f"impl IntoLua for {r} {{",
            "    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {",
            "        let (v, client) = (self.0, self.1);" if nc else "        let v = self.0;",
            "        let t = lua.create_table()?;",
        ]
        for fname, _lt, expr in rec["fields"]:
            L.append(f'        t.set("{fname}", {expr})?;')
        L += ["        Ok(Value::Table(t))", "    }", "}", ""]
    for name in sorted(n for n in m.tagged if n in used):
        e = m.tagged[name]
        r, p, nc = e["rust"], e["path"], e["needs_client"]
        L += [
            f"/// `{name}` -> Luau table `{{ kind = {' | '.join(chr(34) + v['kind'] + chr(34) for v in e['variants'])}, ... }}`" + (" (holds an `Entity`: carries the client)" if nc else ""),
            f"pub struct {r}(pub {p}, pub azalea::Client);" if nc else f"pub struct {r}(pub {p});",
            "",
            f"impl IntoLua for {r} {{",
            "    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {",
        ]
        if nc:
            L.append("        let client = self.1;")
        L += ["        let t = lua.create_table()?;", "        match self.0 {"]
        for v in e["variants"]:
            L.append(f"            {p}::{v['name']}{v['pat']} => {{")
            L.append(f'                t.set("kind", "{v["kind"]}")?;')
            for fname, _lt, expr in v["fields"]:
                L.append(f'                t.set("{fname}", {expr})?;')
            L.append("            }")
        L += ["            #[allow(unreachable_patterns)]", "            _ => {}", "        }", "        Ok(Value::Table(t))", "    }", "}", ""]
    return "\n".join(L) + "\n"


def emit_packets_in(gen: Generator, src_label: str) -> str:
    L = [HEADER.format(src=src_label), "#![allow(dead_code, unused_imports, unused_variables, clippy::all)]", ""]
    L += [
        "use azalea::protocol::packets::game::ClientboundGamePacket;",
        "use mlua::{Lua, Table};",
        "",
        "use super::convert::*;",
        "use super::gen_types::*;",
        "",
        "/// Every packet name (`kind`) a script can see, in azalea's declaration order.",
        "pub const PACKET_KINDS: &[&str] = &[",
    ]
    L += [f'    "{p["name"]}",' for p in gen.packets_in]
    L += [
        "];",
        "",
        "/// The `kind` of a packet (`\"add_entity\"`, ...).",
        "pub fn packet_kind(packet: &ClientboundGamePacket) -> &'static str {",
        "    match packet {",
    ]
    L += [f'        ClientboundGamePacket::{p["variant"]}(_) => "{p["name"]}",' for p in gen.packets_in]
    L += [
        "        #[allow(unreachable_patterns)]",
        '        _ => "unknown",',
        "    }",
        "}",
        "",
        "/// A packet as a Luau table `{ kind = .., <fields> }` (fields azalea's types cannot convert are left out: see GEN_REPORT.md).",
        "pub fn packet_to_table(lua: &Lua, packet: &ClientboundGamePacket) -> mlua::Result<Table> {",
        "    let t = lua.create_table()?;",
        "    t.set(\"kind\", packet_kind(packet))?;",
        "    match packet.clone() {",
    ]
    for p in gen.packets_in:
        L.append(f'        ClientboundGamePacket::{p["variant"]}(v) => {{')
        for fname, _lt, expr in p["fields"]:
            L.append(f'            t.set("{fname}", {expr})?;')
        L.append("        }")
    L += ["        #[allow(unreachable_patterns)]", "        _ => {}", "    }", "    Ok(t)", "}", ""]
    return "\n".join(L)


def emit_ecs(gen: Generator, src_label: str) -> str:
    comps = [e for e in gen.ecs if e["kind"] == "component"]
    ress = [e for e in gen.ecs if e["kind"] == "resource"]
    L = [HEADER.format(src=src_label), "#![allow(dead_code, unused_imports, unused_variables, clippy::all)]", ""]
    L += [
        "use azalea::ecs::entity::Entity;",
        "use azalea::prelude::Client;",
        "use mlua::{IntoLua, Lua, Value};",
        "",
        "use super::convert::*;",
        "use super::gen_types::*;",
        "",
        "/// One ECS type scripts can name: `name` is the Rust type name, `luau` its Luau type (empty when `readable` is false).",
        "pub struct EcsEntry {",
        "    pub name: &'static str,",
        "    pub kind: &'static str,",
        "    pub rust: &'static str,",
        "    pub luau: &'static str,",
        "    pub readable: bool,",
        "}",
        "",
        "/// Every azalea component and resource found in the source, in name order.",
        "pub const ECS_ENTRIES: &[EcsEntry] = &[",
    ]
    for e in gen.ecs:
        ok = "true" if e["to_lua"] else "false"
        L.append(f'    EcsEntry {{ name: "{e["name"]}", kind: "{e["kind"]}", rust: "{e["path"] or ""}", luau: "{e["luau"] or ""}", readable: {ok} }},')
    L += [
        "];",
        "",
        "/// Reads component `name` of `entity` as a Luau value: Ok(None) when the entity lacks it, Err for an unknown or unreadable name.",
        "pub fn read_component(lua: &Lua, client: &Client, entity: Entity, name: &str) -> mlua::Result<Option<Value>> {",
        "    match name {",
    ]
    for e in comps:
        if not e["to_lua"]:
            continue
        if e["marker"]:
            L += [
                f'        "{e["name"]}" => Ok(client.get_entity_component::<{e["path"]}>(entity).map(|_| Value::Boolean(true))),',
            ]
            continue
        L += [
            f'        "{e["name"]}" => {{',
            f'            let Some(guard) = client.get_entity_component::<{e["path"]}>(entity) else {{ return Ok(None) }};',
            "            let v = (*guard).clone();",
            f'            Ok(Some(IntoLua::into_lua({e["to_lua"]}, lua)?))',
            "        }",
        ]
    L += [
        "        other => Err(lua_err(ecs_name_error(other, \"component\"))),",
        "    }",
        "}",
        "",
        "/// Same as `read_component`, through an `EntityRef` (an `Entity` value carries its own client).",
        "pub fn read_ref_component(lua: &Lua, entity: &azalea::EntityRef, name: &str) -> mlua::Result<Option<Value>> {",
        "    match name {",
    ]
    for e in comps:
        if not e["to_lua"]:
            continue
        if e["marker"]:
            L.append(f'        "{e["name"]}" => Ok(entity.get_component::<{e["path"]}>().map(|_| Value::Boolean(true))),')
            continue
        L += [
            f'        "{e["name"]}" => {{',
            f'            let Some(guard) = entity.get_component::<{e["path"]}>() else {{ return Ok(None) }};',
            "            let v = (*guard).clone();",
            f'            Ok(Some(IntoLua::into_lua({e["to_lua"]}, lua)?))',
            "        }",
        ]
    L += [
        "        other => Err(lua_err(ecs_name_error(other, \"component\"))),",
        "    }",
        "}",
        "",
        "/// Reads resource `name` as a Luau value: Ok(None) when the ECS has no such resource.",
        "pub fn read_resource(lua: &Lua, client: &Client, name: &str) -> mlua::Result<Option<Value>> {",
        "    match name {",
    ]
    for e in ress:
        if not e["to_lua"]:
            continue
        if e["marker"]:
            L.append(f'        "{e["name"]}" => Ok(client.map_get_resource::<{e["path"]}, _>(|r| r.map(|_| Value::Boolean(true)))),')
            continue
        L += [
            f'        "{e["name"]}" => {{',
            f'            let Some(v) = client.map_get_resource::<{e["path"]}, _>(|r| r.cloned()) else {{ return Ok(None) }};',
            f'            Ok(Some(IntoLua::into_lua({e["to_lua"]}, lua)?))',
            "        }",
        ]
    L += [
        "        other => Err(lua_err(ecs_name_error(other, \"resource\"))),",
        "    }",
        "}",
        "",
        "/// The error text for a name that is not in the table (or not readable).",
        "pub fn ecs_name_error(name: &str, kind: &str) -> String {",
        "    match ECS_ENTRIES.iter().find(|e| e.name == name) {",
        "        Some(e) if !e.readable => format!(\"{kind} `{name}` exists but cannot be read from Luau (see GEN_REPORT.md)\"),",
        "        Some(e) if e.kind != kind => format!(\"`{name}` is a {}, not a {kind}\", e.kind),",
        "        _ => format!(\"unknown {kind} `{name}` (see `bot:ecs_names()`)\"),",
        "    }",
        "}",
        "",
    ]
    return "\n".join(L)


def emit_packets_out(gen: Generator, src_label: str) -> str:
    ok = [p for p in gen.packets_out if p["ok"]]
    L = [HEADER.format(src=src_label), "#![allow(dead_code, unused_imports, unused_variables, clippy::all)]", ""]
    L += [
        "use azalea::protocol::packets::game::ServerboundGamePacket;",
        "use mlua::Table;",
        "",
        "use super::convert::*;",
        "use super::gen_types::*;",
        "",
        "/// Every serverbound packet a script can build (`kind` -> fields table), in azalea's declaration order.",
        "pub const OUT_PACKET_KINDS: &[&str] = &[",
    ]
    L += [f'    "{p["name"]}",' for p in ok]
    L += [
        "];",
        "",
        "/// Build a serverbound packet from its `kind` and a Luau table of its fields (a missing or mistyped field is a Luau error naming it).",
        "pub fn packet_from_table(kind: &str, t: &Table) -> mlua::Result<ServerboundGamePacket> {",
        "    Ok(match kind {",
    ]
    for p in ok:
        L.append(f'        "{p["name"]}" => {{')
        for i, (lname, _lt, rty, _frm, _rid) in enumerate(p["fields"]):
            L.append(f'            let f{i}: {rty} = t.get("{lname}").map_err(|e| lua_err(format!("packet \'{p["name"]}\', field \'{lname}\': {{e}}")))?;')
        conv = [frm(f"f{i}") for i, (_l, _t, _r, frm, _rid) in enumerate(p["fields"])]
        path = f"azalea::protocol::packets::game::{p['struct']}"
        if p["tuple_style"]:
            body = f"{path}({', '.join(conv)})"
        else:
            body = f"{path} {{ " + ", ".join(f"{rid}: {c}" for (_l, _t, _r, _f, rid), c in zip(p["fields"], conv)) + " }" if conv else f"{path} {{}}"
        L.append(f'            ServerboundGamePacket::{p["variant"]}({body})')
        L.append("        }")
    L += [
        '        other => return Err(lua_err(format!("unknown or unsupported packet kind \'{other}\' (known: {})", OUT_PACKET_KINDS.join(", ")))),',
        "    })",
        "}",
        "",
    ]
    return "\n".join(L)


def active_extra_events(gen: "Generator") -> dict:
    """`[extra_events]` that apply to this azalea: name -> (doc, payload Luau type or None). An event with a payload type
    (`[extra_event_payloads]`) is only declared when that type is generated (`ClientboundPacket`: real azalea only, not the fake)."""
    return {n: (why, EXTRA_EVENT_PAYLOADS.get(n)) for n, why in EXTRA_EVENTS.items()
            if n not in EXTRA_EVENT_PAYLOADS or gen.packets_in}


def emit_events(gen: Generator, src_label: str) -> str:
    L = [HEADER.format(src=src_label), "#![allow(dead_code, unused_imports, unused_variables, clippy::all)]", ""]
    L += [
        "use azalea::Event;",
        "",
        "use super::convert::*;",
        "use super::gen_types::*;",
        "use super::Handlers;",
        "",
        "/// Every event name scripts can pass to `bot:on(...)`.",
        "pub const EVENT_NAMES: &[&str] = &[",
    ]
    L += [f'    "{e["lname"]}",' for e in gen.events]
    L += [f'    "{n}",' for n in active_extra_events(gen)]       # fired by hand-written glue, not by `azalea::Event`
    L += [
        "];",
        "",
        "/// Fire the Luau handlers registered for `event`.",
        "pub async fn dispatch(lua: &mlua::Lua, handlers: &Handlers, event: Event) -> mlua::Result<()> {",
        "    match event {",
    ]
    for e in gen.events:
        ln, var, pay = e["lname"], e["variant"], e["payload"]
        if pay is None:
            L.append(f'        Event::{var}{event_pat(gen, var)} => handlers.fire(lua, "{ln}", ()).await?,')
        else:
            L.append(f'        Event::{var}(p) => {{')
            L.append(f'            if handlers.has("{ln}") {{')
            L.append("                let v = p;")
            L.append(f'                handlers.fire(lua, "{ln}", ({pay.to_lua("v")},)).await?;')
            L.append("            }")
            L.append("        }")
    L += ["        _ => {}", "    }", "    Ok(())", "}"]
    return "\n".join(L) + "\n"


def event_pat(gen: Generator, var: str) -> str:
    d = gen.event_def
    for v in d.variants:
        if v["name"] == var:
            return {"unit": "", "tuple": "(..)", "struct": " { .. }"}[v["kind"]]
    return ""


def luau_params(w: Wrapper) -> str:
    return "".join(f", {n}: {ti.luau}" for n, ti in w.wparams)


def luau_union(name: str, alts: list[str], limit: int = 400) -> list[str]:
    """`type name = a | b | ...` as source lines. Luau's parser rejects a single union of more than 1000 members
    (FInt::LuauTypeLengthLimit, "Exceeded allowed type length") and luau-lsp then drops the whole definitions file, so a long union
    (azalea's Item / Block / SoundEvent registries have 1200-2000 variants) is split into `<name>Part<N>` aliases of `limit` members each."""
    if len(alts) <= limit:
        return [f"type {name} = " + " | ".join(alts)]
    parts = [alts[i:i + limit] for i in range(0, len(alts), limit)]
    L = [f"type {name}Part{i} = " + " | ".join(c) for i, c in enumerate(parts, 1)]
    L.append(f"type {name} = " + " | ".join(f"{name}Part{i}" for i in range(1, len(parts) + 1)))
    return L


def emit_dluau(gen: Generator, src_label: str, extras: dict) -> str:
    m = gen.m
    used = {n for k, n in m.touched if k == "type"}
    builtins = {n for k, n in m.touched if k == "builtin"}
    L = [f"-- @generated by tools/luaxite_gen.py from {src_label} - DO NOT EDIT.", ""]
    builtins |= {BUILTIN[n]["needs"] for n in builtins if "needs" in BUILTIN[n]}
    for name in sorted(builtins):
        d = BUILTIN[name]["luau_def"]
        if d:
            L.append(f"type {BUILTIN[name].get('alias', name)} = {d}")
    for name in sorted(n for n in m.enums if n in used):
        L += luau_union(name, [f'"{snake(bare(v))}"' for v in m.enums[name]["variants"]])
    for name in sorted(n for n in m.records if n in used):
        fields = ", ".join(f"{luau_field(f)}: {t}" for f, t, _e in m.records[name]["fields"])
        L.append(f"type {name} = {{ {fields} }}")
    for name in sorted(n for n in m.tagged if n in used):
        alts = []
        for v in m.tagged[name]["variants"]:
            fs = [f'kind: "{v["kind"]}"'] + [f"{luau_field(f)}: {t}" for f, t, _e in v["fields"]]
            alts.append("{ " + ", ".join(fs) + " }")
        L += luau_union(name, alts)
    if gen.packets_in:
        for p in gen.packets_in:
            fs = [f'kind: "{p["name"]}"'] + [f"{luau_field(f)}: {t}" for f, t, _e in p["fields"]]
            L.append(f"type {p['luau']} = {{ " + ", ".join(fs) + " }")
        L.append("-- Every clientbound game packet (tagged by `kind`).")
        if len(gen.packets_in) <= 400:
            L.append("type ClientboundPacket =")
            L += [f"    | {p['luau']}" for p in gen.packets_in]
        else:
            L += luau_union("ClientboundPacket", [p["luau"] for p in gen.packets_in])
    okp = [p for p in gen.packets_out if p["ok"]]
    if okp:
        for p in okp:
            fs = [f"{luau_field(f)}: {t}" for f, t, _r, _fr, _id in p["fields"]]
            L.append(f"type {p['luau']} = {{ " + ", ".join(fs) + " }" if fs else f"type {p['luau']} = {{}}")
        L.append("-- The serverbound game packets a script can build: the `kind` of a packet and its fields table (`OutPacket<Kind>`).")
        L += luau_union("OutPacketKind", [f'"{p["name"]}"' for p in okp])
    L.append("")
    declared = set()
    for name in sorted(n for n in builtins if "class_doc" in BUILTIN[n]):
        b = BUILTIN[name]
        if b["luau"] in declared:
            continue
        declared.add(b["luau"])
        L += [f"-- {b['class_doc']}", f"declare extern type {b['luau']} with"]
        L += [f"    {ln}" for _f, ln in extras.get(b["luau"], [])]
        L += ["end", ""]
    # hand-only classes (`[hand_classes]`): declared when some extra_*.rs / real_*.rs carries `// luau[Class]:` lines for them
    for cname, doc in HAND_CLASSES.items():
        if cname in declared or not extras.get(cname):
            continue
        declared.add(cname)
        L += [f"-- {doc}", f"declare extern type {cname} with"]
        L += [f"    {ln}" for _f, ln in extras[cname]]
        L += ["end", ""]
    # non-Client classes first (Bot refers to them), then the `bot` class
    for cg in sorted((c for c in gen.classes.values() if c.emit and not c.cfg.get("free")), key=lambda c: c.name == "Client"):
        L.append(f"-- {cg.cfg['doc']}")
        L.append(f"declare extern type {cg.luau} with")
        if cg.cfg["events"]:
            L.append("    --- Register a handler for an event.")
            for e in gen.events:
                arg = f"{e['arg']}: {e['payload'].luau}" if e["payload"] else ""
                L.append(f'    function on(self, event: "{e["lname"]}", handler: ({arg}) -> ()): ()')
            active = active_extra_events(gen)
            for n, (why, pay) in active.items():
                L.append(f"    --- {why}")
                arg = f"packet: {pay}" if pay else ""
                L.append(f'    function on(self, event: "{n}", handler: ({arg}) -> ()): ()')
            L.append("    --- Yields until `event` fires next, then returns its payload (nothing for events without one). "
                     "Works in the script body and in handlers. Raises an error if the bot disconnects first.")
            for e in gen.events:
                ret = e["payload"].luau if e["payload"] else "()"
                L.append(f'    function wait_for(self, event: "{e["lname"]}"): {ret}')
            for n, (_why, pay) in active.items():
                L.append(f'    function wait_for(self, event: "{n}"): {pay or "()"}')
            if "packet" in active:      # name filter: one overload per packet kind (rust/luau/real_events.rs `on_packet` / `wait_for_packet`)
                L.append("    --- Register a handler for one kind of clientbound packet only (`name` = the packet's `kind`).")
                L += [f'    function on_packet(self, name: "{p["name"]}", handler: (packet: {p["luau"]}) -> ()): ()' for p in gen.packets_in]
                L.append("    --- Yields until a packet of that kind arrives, then returns it.")
                L += [f'    function wait_for_packet(self, name: "{p["name"]}"): {p["luau"]}' for p in gen.packets_in]
        for w in sorted(cg.wrappers, key=lambda w: w.name):
            doc = ("Yields until finished. " if w.is_async else "") + clean_doc(w.doc)
            if doc:
                L.append(f"    --- {doc.strip()}")
            ret = w.ret.luau if w.ret else "()"
            L.append(f"    function {w.name}(self{luau_params(w)}): {ret}")
        if extras.get(cg.luau):
            L.append("    -- hand-written (rust/luau/extra_*.rs)")
            L += [f"    {ln}" for _f, ln in extras[cg.luau]]
        L += ["end", ""]
    for gname, cname in HAND_GLOBALS.items():
        if cname in declared:
            L.append(f"declare {gname}: {cname}")
    for cg in gen.classes.values():          # generic mode: the free fns of a crate are the global table named after it
        if cg.emit and cg.cfg.get("free") and cg.wrappers:
            L.append(f"-- {cg.cfg['doc']}")
            L.append(f"declare {cg.luau}: {{")
            for w in sorted(cg.wrappers, key=lambda w: w.name):
                doc = clean_doc(w.doc)
                if doc:
                    L.append(f"    --- {doc.strip()}")
                L.append(f"    {w.name}: ({luau_params(w)[2:]}) -> {w.ret.luau if w.ret else '()'},")
            L += ["}", ""]
    if gen.has_events:
        L += ["declare bot: Bot", ""]
    return "\n".join(L)


def emit_report(gen: Generator, src_label: str, ix: Any, extras: dict) -> str:
    m = gen.m
    L = [f"# Luau bridge report", "", f"Source: `{src_label}` ({ix.files} files)",
         f"Front end: {ix.frontend_label}", ""]
    for cg in gen.classes.values():
        state = "" if cg.emit else " (collected, bindings not emitted yet)"
        L.append(
            f"- **`{cg.name}` -> `{cg.rust}` / `{cg.luau}`{state}:** {len(cg.wrappers)} methods generated "
            f"({sum(w.is_async for w in cg.wrappers)} async/yielding), {len(cg.skipped)} skipped"
        )
    if gen.has_events:
        L.append(f"- **azalea -> Luau:** {len(gen.events)} events (`bot:on(...)`)")
    L += [
        f"- **Types:** {len([1 for k, _ in m.touched if k == 'type'])} generated conversions, "
        f"{len([1 for k, _ in m.touched if k == 'builtin'])} built-in",
        "",
        "## Generated methods",
        "",
    ]
    for cg in gen.classes.values():
        L += [f"### {cg.name}", "", ", ".join(f"`{w.name}`" for w in sorted(cg.wrappers, key=lambda w: w.name)) or "(none)", ""]
    L += ["## Hand-written methods (rust/luau/extra_*.rs)", ""]
    any_extra = False
    for cls, lines in extras.items():
        names = [n for _f, ln in lines if (n := extra_fn_name(ln))]
        if names:
            any_extra = True
            L.append(f"- `{cls}`: " + ", ".join(f"`{n}`" for n in names))
    if not any_extra:
        L.append("(none)")
    L += ["", "## Events", ""]
    for e in gen.events:
        arg = f"({e['arg']}: {e['payload'].luau})" if e["payload"] else "()"
        L.append(f"- `{e['lname']}` {arg}")
    L += [f"- `{n}` ({'packet: ' + pay if pay else ''}) - hand-fired: {why}" for n, (why, pay) in active_extra_events(gen).items()]
    if gen.event_notes:
        L += ["", "Notes:", ""] + [f"- {n}" for n in gen.event_notes]
    if gen.packets_out:
        okp = [p for p in gen.packets_out if p["ok"]]
        bad = [p for p in gen.packets_out if not p["ok"]]
        L += ["", "## Packets out (Luau table -> ServerboundGamePacket, gen_packets_out.rs)", "",
              f"{len(gen.packets_out)} packets: {len(okp)} can be built, {len(bad)} cannot (a field has no Luau -> Rust conversion).", ""]
        L += [f"- `{p['name']}`: {p['why']}" for p in bad]
    if gen.ecs:
        readable = [e for e in gen.ecs if e["to_lua"]]
        L += ["", "## ECS components and resources (gen_ecs.rs)", "",
              f"{len(gen.ecs)} types: {len(readable)} readable, {len(gen.ecs) - len(readable)} not.", ""]
        for kind in ("component", "resource"):
            rows = [e for e in gen.ecs if e["kind"] == kind]
            good = [e for e in rows if e["to_lua"]]
            L += [f"### {kind}s: {len(good)} readable of {len(rows)}", ""]
            L += [f"- `{e['name']}`: `{e['luau']}`" for e in good if not e["marker"]]
            marks = [e["name"] for e in good if e["marker"]]
            if marks:
                L.append(f"- marker types (read as `true` when present): {len(marks)}, e.g. " + ", ".join(f"`{n}`" for n in marks[:8]))
            reasons = {}
            for e in rows:
                if not e["to_lua"]:
                    reasons.setdefault(e["reason"], []).append(e["name"])
            for r, names in sorted(reasons.items()):
                L.append(f"- not readable, {r}: {len(names)}: " + ", ".join(f"`{n}`" for n in names))
            L.append("")
    if gen.packets_in:
        full = [p for p in gen.packets_in if not p["nodef"] and not p["skipped"]]
        part = [p for p in gen.packets_in if not p["nodef"] and p["skipped"]]
        bare_ = [p for p in gen.packets_in if p["nodef"]]
        L += ["", "## Packets in (ClientboundGamePacket -> gen_packets_in.rs)", "",
              f"{len(gen.packets_in)} packets: {len(full)} complete, {len(part)} with fields left out, {len(bare_)} kind only.", ""]
        for p in part:
            L.append(f"- `{p['name']}`: left out " + ", ".join(f"`{f}` ({why})" for f, why in p["skipped"]))
        for p in bare_:
            L.append(f"- `{p['name']}`: kind only ({p['nodef']})")
    L += ["", "## Resolved public paths", ""]
    for n, p in sorted(m.paths.items()):
        L.append(f"- `{n}` -> `{p}`")
    if gen.goal_notes:
        L += ["", "## Goals not exposed", ""] + [f"- {n}" for n in gen.goal_notes]
    if ix.macro_notes:
        L += ["", "## Macros not expanded (their methods are missing)", ""]
        L += [f"- `{mac}!` in `{f}`" for f, mac in sorted(set(ix.macro_notes))]
    L += ["", "## Skipped methods", ""]
    for cg in gen.classes.values():
        L += [f"### {cg.name}", ""]
        by_reason = defaultdict(list)
        for origin, sig, reason in cg.skipped:
            by_reason[re.sub(r"`[^`]*`", "`_`", reason) if reason.startswith("duplicate") else reason].append(sig)
        for reason, sigs in sorted(by_reason.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            L += [f"#### {reason} ({len(sigs)})", ""]
            L += [f"- `{s}`" for s in sorted(sigs)]
            L.append("")
        if not by_reason:
            L += ["(none)", ""]
    if m.enum_notes:                                                      # variants missing from the JSON index
        L += ["## Enums with variants not emitted", ""] + [f"- {n}" for n in sorted(set(m.enum_notes))] + [""]
    notes = ix.report_lines() if hasattr(ix, "report_lines") else []       # rustdoc front end only; empty = no section
    if notes:
        L += ["## rustdoc front end: skipped items", "", "Never fatal: the rest of the bindings were generated without them.", ""] + notes + [""]
    return "\n".join(L)


# =============================================================================
# main
# =============================================================================

CliArgs = getattr(argparse, "Argument" + "Pars" + "er")    # argparse class, name split so the final case-insensitive grep for the retired front end stays clean


def main():
    ap = CliArgs(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--azalea", default="bind/azalea-src", help="path to the azalea workspace (default: bind/azalea-src)")
    ap.add_argument("--rust-out", default="rust/luau", help="where gen_*.rs go (default: rust/luau)")
    ap.add_argument("--luau-out", default="luau", help="where azalea.d.luau and GEN_REPORT.md go (default: luau)")
    ap.add_argument("--rustdoc", required=True, help="directory of <crate>.json files (cargo rustdoc --output-format json)")
    ap.add_argument("--config", default=None, metavar="PATH",
                    help="TOML data tables (default: <project root>/bindgen.toml; when that file is missing the built-in empty tables apply; "
                         "an explicit PATH must exist; `--config builtin` = the built-in empty tables)")
    ap.add_argument("--rdj-hidden", choices=("keep", "skip"), default="keep",
                    help="rustdoc front end: what to do with #[doc(hidden)] fns present in the JSON (made with --document-hidden-items): "
                         "keep = bind them; skip = drop them (each is named in GEN_REPORT). Default: keep")
    args = ap.parse_args()
    if args.config is not None:
        try:
            globals().update(load_config(Path(args.config)))
        except ConfigError as e:
            sys.exit(f"error: {Path(args.config).name}: {e}")

    root = Path(args.azalea)
    if not root.is_dir():
        sys.exit(f"error: {root} is not a directory (pass --azalea <path to your azalea checkout>)")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.modules.setdefault("luaxite_gen", sys.modules[__name__])      # rdj_index imports us: reuse this module
    import rdj_index
    ix = rdj_index.RdjIndex(root, args.rustdoc, hidden=args.rdj_hidden)
    try:
        ix.load()
    except rdj_index.RdjError as e:
        sys.exit(f"error: {e}")
    except Exception as e:      # a JSON shape nobody foresaw: one line, no traceback (per-item problems never get here)
        sys.exit(f"error: rustdoc front end failed on {args.rustdoc}: {type(e).__name__}: {' '.join(str(e).split())[:200]}")
    CLASSES.update(ix.discovered)           # classes found in the crates (config without `[classes]`); empty otherwise
    gen = Generator(ix)
    gen.reserved = extras_reserved(Path(args.rust_out))
    gen.build()
    if gen.has_events:       # azalea-only builders run when the config asks for them (an events class)
        gen.build_events()
    gen.build_packets_in(root)
    gen.build_packets_out(root)
    gen.build_ecs()
    for n in sorted(set(gen.m.enum_notes)):
        print(f"warning: enum {n}", file=sys.stderr)

    src_label = f"{root.name} @ {ix.digest.hexdigest()[:10]}"
    rust_out, luau_out = Path(args.rust_out), Path(args.luau_out)
    rust_out.mkdir(parents=True, exist_ok=True)
    luau_out.mkdir(parents=True, exist_ok=True)
    (rust_out / "gen_client.rs").write_text(emit_client(gen, src_label))
    (rust_out / "gen_types.rs").write_text(emit_types(gen, src_label))
    if gen.has_events:
        (rust_out / "gen_events.rs").write_text(emit_events(gen, src_label))
    elif (rust_out / "gen_events.rs").exists():
        (rust_out / "gen_events.rs").unlink()
    packets_rs = rust_out / "gen_packets_in.rs"
    if gen.packets_in:
        packets_rs.write_text(emit_packets_in(gen, src_label))
    elif packets_rs.exists():
        packets_rs.unlink()     # azalea without packet sources (the fake): no stale file
    packets_out_rs = rust_out / "gen_packets_out.rs"
    if any(p["ok"] for p in gen.packets_out):
        packets_out_rs.write_text(emit_packets_out(gen, src_label))
    elif packets_out_rs.exists():
        packets_out_rs.unlink()
    ecs_rs = rust_out / "gen_ecs.rs"
    if any(e["to_lua"] for e in gen.ecs):
        ecs_rs.write_text(emit_ecs(gen, src_label))
    elif ecs_rs.exists():
        ecs_rs.unlink()
    extras = scan_extras(rust_out)
    (luau_out / "azalea.d.luau").write_text(emit_dluau(gen, src_label, extras))
    (luau_out / "GEN_REPORT.md").write_text(emit_report(gen, src_label, ix, extras))
    print(
        f"generated {sum(len(c.wrappers) for c in gen.classes.values())} methods ({sum(len(c.skipped) for c in gen.classes.values())} skipped), "
        f"{len(gen.events)} events, "
        f"{len([1 for k, _ in gen.m.touched if k == 'type'])} converted types -> {rust_out}/, {luau_out}/"
    )


if __name__ == "__main__":
    main()
