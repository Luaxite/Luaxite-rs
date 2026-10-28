#!/usr/bin/env python3
"""
rdj.py - loader for rustdoc JSON (`cargo rustdoc -- -Z unstable-options --output-format json`), stdlib only.

The generator front end (tools/rdj_index.py) reads this. This module only loads and navigates the JSON; it does not know about azalea or the generator's data model.

    rdj = load_dir("harness/fake/rustdoc")          # every <crate>.json in the directory
    c = rdj.crate("azalea")                         # Crate: index, root, paths, external_crates, format_version
    rdj.item_path("azalea", 772)                    # ('azalea', 'Client')
    rdj.children("azalea", rdj.root("azalea"))      # ids of the root module's items

Format: rustdoc-json-types `format_version` (57 = stable rustc 1.97; 58-61 ADD `Item::stability`, `Item::const_stability` and
`default_unstable` on Function/AssocConst/AssocType, and 61 (the newest, rustdoc-types 0.61.0) RESHAPES `Stability` to
`{feature, level}` with `level` an externally tagged enum (a breaking change upstream, made so non-self-describing serde formats
work). This front end reads none of these fields, so 57-61 are all accepted). Only versions in ACCEPTED are loaded; anything else
is one RdjError naming the producing rustc (from the `<crate>.meta` sidecar tools/make_rustdoc_json.sh writes) and the
range. Override at your own risk: AZL_RDJ_FORMAT_RANGE=lo-hi (or `accept=(lo, hi)`). Versions in range but not equal to
FORMAT_TESTED load with an entry in `Rdj.warnings`.

CLI: python3 tools/rdj.py DIR        prints a summary of every crate JSON in DIR.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

FORMAT_TESTED = 57
FORMAT_ACCEPTED = (57, 61)
TESTED_RUSTC = "rustc 1.97.0 (2d8144b78 2026-07-07)"
TOP_KEYS = ("root", "index", "paths", "external_crates", "format_version")


class RdjError(Exception):
    """Anything wrong with the JSON input; the message is meant to be shown to the user as is."""






def accepted_range(accept: Optional[tuple] = None) -> tuple:
    if accept is not None:
        return (int(accept[0]), int(accept[1]))
    env = os.environ.get("AZL_RDJ_FORMAT_RANGE", "").strip()
    if env:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", env)
        if not m:
            raise RdjError(f"AZL_RDJ_FORMAT_RANGE={env!r} is not `lo-hi` (or a single number)")
        return (int(m.group(1)), int(m.group(2) or m.group(1)))
    return FORMAT_ACCEPTED


def read_meta(json_path: Path) -> dict:
    """`<stem>.meta` next to the JSON (written by tools/make_rustdoc_json.sh): `key: value` lines, {} if absent."""
    meta = {}
    p = json_path.with_suffix(".meta")
    if p.is_file():
        for line in p.read_text(errors="replace").splitlines():
            k, sep, v = line.partition(":")
            if sep:
                meta[k.strip()] = v.strip()
    return meta


def peek_format_version(path: Path) -> Optional[int]:
    """format_version is the last key rustdoc writes, so a tail read avoids parsing a huge file that will be refused."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 4096))
        tail = f.read().decode("utf-8", "replace")
    m = re.findall(r'"format_version"\s*:\s*(\d+)', tail)
    return int(m[-1]) if m else None


def format_error(path: Path, fv, rng: tuple, meta: dict) -> RdjError:
    rustc = meta.get("rustc") or f"an unknown rustc (no {path.with_suffix('.meta').name} next to it)"
    span = f"{rng[0]}" if rng[0] == rng[1] else f"{rng[0]}-{rng[1]}"
    return RdjError(
        f"{path}: rustdoc JSON format_version {fv} is outside the accepted range {span} "
        f"(this front end is tested with format_version {FORMAT_TESTED}, {TESTED_RUSTC}); "
        f"the JSON was produced by {rustc}. Regenerate it with tools/make_rustdoc_json.sh on the pinned toolchain, "
        f"or at your own risk accept it with AZL_RDJ_FORMAT_RANGE={fv}-{fv}"
    )






def inner_kind(item: dict) -> str:
    """`struct`, `enum`, `function`, `impl`, `module`, `use`, `struct_field`, `variant`, ... ('' if the item has none)."""
    inner = item.get("inner")
    if isinstance(inner, dict) and inner:
        return next(iter(inner))
    return inner if isinstance(inner, str) else ""


def payload(item: dict) -> dict:
    inner = item.get("inner")
    if isinstance(inner, dict) and inner:
        v = next(iter(inner.values()))
        return v if isinstance(v, dict) else {}
    return {}


def visibility(item: dict) -> str:
    """'public' | 'default' (private unless the item lives in a trait/trait impl/enum) | 'crate' | 'restricted'."""
    v = item.get("visibility")
    if isinstance(v, dict):
        return "restricted"
    return v if isinstance(v, str) else "default"


def _ids(v) -> list:
    return [i for i in (v or []) if isinstance(i, int)]


def _kind_fields(kind) -> list:
    """Field ids of a StructKind / VariantKind: "unit"/"plain" | {"tuple": [..]} | {"plain"|"struct": {"fields": [..]}}."""
    if isinstance(kind, dict):
        for v in kind.values():
            if isinstance(v, list):
                return _ids(v)
            if isinstance(v, dict):
                return _ids(v.get("fields"))
    return []


def container_children(item: dict) -> list:
    """Structural children in declaration order: module/trait/impl items, struct/union fields, enum variants, variant fields."""
    k, p = inner_kind(item), payload(item)
    if k in ("module", "trait", "impl"):
        return _ids(p.get("items"))
    if k == "struct":
        return _kind_fields(p.get("kind"))
    if k == "union":
        return _ids(p.get("fields"))
    if k == "enum":
        return _ids(p.get("variants"))
    if k == "variant":
        return _kind_fields(p.get("kind"))
    return []


class Crate:
    def __init__(self, path: Path, raw: dict, meta: dict):
        self.stem = path.stem
        self.path = path
        self.meta = meta
        self.format_version: int = raw["format_version"]
        self.root: int = raw["root"]
        self.crate_version = raw.get("crate_version")
        self.includes_private: bool = bool(raw.get("includes_private"))
        self.target_triple = (raw.get("target") or {}).get("triple")
        self.index: dict = {int(k): v for k, v in raw["index"].items()}
        self.paths: dict = {int(k): v for k, v in raw["paths"].items()}
        self.external_crates: dict = {int(k): v for k, v in raw["external_crates"].items()}
        r = self.index.get(self.root)
        if r is None:
            raise RdjError(f"{path}: root item id {self.root} is not in `index` (truncated or not a rustdoc JSON file)")
        self.name: str = r.get("name") or self.stem
        self._parent: Optional[dict] = None
        self._local_paths: Optional[dict] = None

    def item(self, id: int) -> Optional[dict]:
        return self.index.get(id)

    def kind(self, id: int) -> str:
        it = self.index.get(id)
        return inner_kind(it) if it else ""

    def children(self, id: int) -> list:
        """Ids of an item's structural children (see container_children); [] for leaves and unknown ids."""
        it = self.index.get(id)
        return container_children(it) if it else []

    def impls(self, id: int) -> list:
        """Impl ids recorded on a struct/enum/union (`impls`) or trait (`implementations`)."""
        p = payload(self.index.get(id) or {})
        return _ids(p.get("impls") if "impls" in p else p.get("implementations"))

    def derived_traits(self, id: int) -> list:
        """Traits derived on a struct/enum/union, in source order: the `automatically_derived` impls on it (derive order is
        impl order), without the compiler's StructuralPartialEq marker that `derive(PartialEq)` adds."""
        out = []
        for iid in self.impls(id):
            it = self.index.get(iid)
            if not it:
                continue
            p = payload(it)
            tr = (p.get("trait") or {}).get("path") or ""
            if not tr or _last_seg(tr) == "StructuralPartialEq":
                continue
            if "automatically_derived" in (it.get("attrs") or []):
                out.append(_last_seg(tr))
            elif _last_seg(tr) in _BEVY_DERIVES and not (p.get("is_synthetic") or p.get("blanket_impl")):



                out.append(_last_seg(tr))
        return out

    def crate_name(self, crate_id: int) -> Optional[str]:
        """Name of the crate a `crate_id` in this JSON refers to (0 = this crate)."""
        if crate_id == 0:
            return self.name
        ec = self.external_crates.get(crate_id)
        return ec.get("name") if ec else None

    def local_paths(self) -> dict:
        """{path tuple: id} of this crate's own items listed in `paths` (crate_id 0), plus the root module as `(name,)`.
        What a sibling crate's JSON uses to find an item that only appears as a `paths` summary in a dependent crate."""
        if self._local_paths is None:
            lp = {tuple(s["path"]): i for i, s in sorted(self.paths.items())
                  if s.get("crate_id") == 0 and isinstance(s.get("path"), list) and s["path"]}
            lp[(self.name,)] = self.root
            self._local_paths = lp
        return self._local_paths

    def local_path(self, path: tuple, kind: Optional[str] = None) -> Optional[int]:
        """Id of this crate's own item at `path` (see `local_paths`). A module and a fn (or a macro) can share one path (separate
        namespaces) and `local_paths` keeps only the last id, so `kind` (the `paths` kind a dependent crate recorded) picks the one
        of that kind when several items share the path; no match or no `kind` = what `local_paths` holds."""
        best = self.local_paths().get(path)
        if kind is not None and best is not None:
            same = sorted(i for i, s in self.paths.items() if s.get("crate_id") == 0 and s.get("kind") == kind
                          and isinstance(s.get("path"), list) and tuple(s["path"]) == path)
            if same and best not in same:
                return same[-1]
        return best

    def parent(self, id: int) -> Optional[int]:
        """Id of the module/struct/enum/variant/trait/impl whose `children` contain `id` (built once, lazily)."""
        if self._parent is None:
            self._parent = {}
            for pid, it in self.index.items():
                for cid in container_children(it):
                    self._parent.setdefault(cid, pid)
        return self._parent.get(id)

    def item_path(self, id: int, _depth: int = 0) -> Optional[tuple]:
        """Path segments of an item, first segment = its crate (`('azalea', 'position', 'BlockPos')`), or None.

        Items rustdoc lists in `paths` (modules, structs, enums, traits, variants, ... of this crate and of every
        crate it references) use that summary. Everything else is derived from its parent: fields and variants from
        their struct/enum, trait items from the trait, impl items from the impl's `for` type (`Client::chat`), a `use`
        item from its module. Impl blocks themselves have no path."""
        if _depth > 8:
            return None
        s = self.paths.get(id)
        if s is not None and isinstance(s.get("path"), list):
            return tuple(s["path"])
        it = self.index.get(id)
        if it is None:
            return None
        k = inner_kind(it)
        if k == "impl":
            return None
        pid = self.parent(id)
        if pid is None:
            return None
        name = it.get("name")
        if k == "use":
            name = "*" if payload(it).get("is_glob") else (name or payload(it).get("name"))
        if not name:
            return None
        parent = self.index.get(pid)
        if parent is not None and inner_kind(parent) == "impl":
            for_ = payload(parent).get("for")
            tid = for_.get("resolved_path", {}).get("id") if isinstance(for_, dict) else None
            base = self.item_path(tid, _depth + 1) if isinstance(tid, int) else None
        else:
            base = self.item_path(pid, _depth + 1)
        return base + (name,) if base else None






class Rdj:
    def __init__(self):
        self.crates: dict = {}
        self.warnings: list = []
        self.not_found: set = set()

    def crate(self, name) -> Crate:
        if isinstance(name, Crate):
            return name
        c = self.crates.get(name)
        if c is None:
            raise RdjError(f"no JSON loaded for crate `{name}` (have: {', '.join(sorted(self.crates)) or 'none'})")
        return c

    @property
    def format_version(self) -> int:
        fvs = {c.format_version for c in self.crates.values()}
        if len(fvs) != 1:
            raise RdjError(f"the crate JSONs mix format_versions {sorted(fvs)}; regenerate them all with one toolchain")
        return fvs.pop()

    def root(self, crate) -> int:
        return self.crate(crate).root

    def item(self, crate, id: int) -> Optional[dict]:
        return self.crate(crate).item(id)

    def children(self, crate, id: int) -> list:
        return self.crate(crate).children(id)

    def item_path(self, crate, id: int) -> Optional[tuple]:
        return self.crate(crate).item_path(id)

    def external_crates(self, crate) -> dict:
        return self.crate(crate).external_crates


    def summary(self, crate, id) -> Optional[dict]:
        """The `paths` entry of an id of `crate` (what rustdoc keeps of an item defined elsewhere), or None."""
        s = self.crate(crate).paths.get(id) if isinstance(id, int) else None
        return s if s and isinstance(s.get("path"), list) and s["path"] else None

    def resolve(self, crate, id, miss: Optional[list] = None) -> Optional[tuple]:
        """(crate name, item id) of the item `id` of `crate`'s JSON refers to, wherever it is defined.

        A local item (`crate_id` 0 and present in `index`) is itself. Anything else is a `paths` summary: {crate_id, path,
        kind}. Its crate is looked up by `external_crates[crate_id].name` (then by `path[0]`) among the loaded sibling
        JSONs and the path in that crate's own `paths` (`Crate.local_paths`). Not found by path: rustdoc's alias quirk
        (a variant reached through a type alias carries the enum's crate_id with the alias path, `['a','Alias','Ok']`) is
        resolved by crate_id + last segment + kind when exactly one item of that crate matches. None for crates that are
        not loaded (std, core, ...) or items the sibling JSON does not list; `miss` (a list) then gets `(crate, 'a::b::C')`, and
        `self.not_found` too when the target crate is loaded (the path is missing from its JSON, not the whole crate)."""
        if not isinstance(id, int):
            return None
        c = self.crate(crate)
        it = c.index.get(id)
        if it is not None and it.get("crate_id") == 0:
            return (c.name, id)
        s = self.summary(c, id)
        if s is None:
            return None
        path = tuple(s["path"])
        names = []
        for n in (c.crate_name(s.get("crate_id")), path[0]):
            if n and n not in names:
                names.append(n)
        for n in names:
            sib = self.crates.get(n)
            if sib is None:
                continue
            tid = sib.local_path(path, s.get("kind"))
            if tid is not None:
                return (n, tid)
        for n in names[:1]:
            sib = self.crates.get(n)
            if sib is None or len(path) < 2:
                continue
            hits = [i for p, i in sib.local_paths().items() if p[-1] == path[-1] and sib.kind(i) == s.get("kind")]
            if len(hits) == 1:
                return (n, hits[0])
        if miss is not None:
            miss.append((c.name, "::".join(path)))
            if any(n in self.crates for n in names):
                self.not_found.add((c.name, "::".join(path)))
        return None


def load_file(path, accept: Optional[tuple] = None) -> Crate:
    path = Path(path)
    lo, hi = accepted_range(accept)
    meta = read_meta(path)
    try:
        fv = peek_format_version(path)
    except OSError as e:
        raise RdjError(f"{path}: cannot read: {e}") from None
    if fv is not None and not lo <= fv <= hi:
        raise format_error(path, fv, (lo, hi), meta)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise RdjError(f"{path}: not valid JSON ({e})") from None
    if not isinstance(raw, dict):
        raise RdjError(f"{path}: not a rustdoc JSON file (top level is {type(raw).__name__}, expected an object)")
    missing = [k for k in TOP_KEYS if k not in raw]
    if missing:
        raise RdjError(f"{path}: not a rustdoc JSON file (missing key{'s' if len(missing) > 1 else ''}: {', '.join(missing)})")
    fv = raw["format_version"]
    if not isinstance(fv, int) or not lo <= fv <= hi:
        raise format_error(path, fv, (lo, hi), meta)
    for k in ("index", "paths", "external_crates"):
        if not isinstance(raw[k], dict):
            raise RdjError(f"{path}: `{k}` should be an object (not a rustdoc JSON file or a different format)")
    return Crate(path, raw, meta)


def load_dir(directory, accept: Optional[tuple] = None) -> Rdj:
    """Load every `*.json` in `directory` (one per crate, named after the crate: `azalea.json`)."""
    d = Path(directory)
    if not d.is_dir():
        raise RdjError(f"rustdoc JSON directory {d} does not exist (make it with tools/make_rustdoc_json.sh)")
    files = sorted(d.glob("*.json"))
    if not files:
        raise RdjError(f"no *.json files in {d} (make them with tools/make_rustdoc_json.sh)")
    rdj = Rdj()
    for f in files:
        c = load_file(f, accept)
        if c.name in rdj.crates:
            raise RdjError(f"{f}: crate `{c.name}` is already loaded from {rdj.crates[c.name].path}")
        if c.format_version != FORMAT_TESTED:
            rdj.warnings.append(f"{f.name}: format_version {c.format_version} is accepted but only {FORMAT_TESTED} is tested")
        if c.name != c.stem:
            rdj.warnings.append(f"{f.name}: file name differs from the crate name `{c.name}`")
        if c.name == "azalea_entity" and not any(c.kind(i) == "module" and (c.item(i) or {}).get("name") == "metadata"
                                                 for i in c.children(c.root)):

            rdj.warnings.append(f"{f.name}: no `metadata` module (azalea-entity documented without its `bevy_ecs` feature): "
                                "gen_ecs.rs will lose the entity-metadata components; re-make the JSON with AZL_RDJ_FEATURES=--all-features")
        rdj.crates[c.name] = c
    fvs = {n: c.format_version for n, c in rdj.crates.items()}
    if len(set(fvs.values())) > 1:
        rdj.warnings.append(f"the crate JSONs mix format_versions ({', '.join(f'{n} {v}' for n, v in sorted(fvs.items()))}); "
                            "re-make them all with one toolchain")
    return rdj








_BEVY_DERIVES = ("Component", "Resource")


def _last_seg(path: str) -> str:
    return path.rsplit("::", 1)[-1]


def _generic_args(args) -> tuple:
    """GenericArgs -> (type args as Type dicts / raw texts in source order, constraint texts). Lifetimes are dropped;
    consts and `Name = Type` constraints become ('other', text)."""
    out: list = []
    if not isinstance(args, dict):
        return out
    ab = args.get("angle_bracketed")
    if isinstance(ab, dict):
        for a in ab.get("args") or []:
            if not isinstance(a, dict):
                continue
            if "type" in a:
                out.append(a["type"])
            elif "const" in a:
                c = a["const"]
                out.append({"__text__": (c.get("expr") or c.get("value") or "_") if isinstance(c, dict) else str(c)})

        for c in ab.get("constraints") or []:
            if not isinstance(c, dict):
                continue
            b = c.get("binding")
            if isinstance(b, dict) and "equality" in b:
                eq = b["equality"]
                out.append({"__text__": f"{c.get('name', '_')} = {render_type(eq['type']) if isinstance(eq, dict) and 'type' in eq else '_'}"})
            else:
                out.append({"__text__": f"{c.get('name', '_')}: {_render_bounds(b['constraint']) if isinstance(b, dict) and 'constraint' in b else '_'}"})
    return out


def convert_type(t) -> tuple:
    """rustdoc JSON `Type` -> the generator's type AST tuple (see the block comment above).

    resolved_path -> ('path', last segment, args)   primitive -> ('prim', n)   tuple [] -> ('unit',), else ('tuple', ..)
    slice / array -> ('slice', t)   borrowed_ref immutable -> ('ref', t), mutable -> ('other', '&mut T')
    impl_trait / dyn_trait -> ('impl', text)   generic / Self / qualified_path / function_pointer / raw_pointer /
    infer / pat -> ('other', text). Never raises on an unknown variant: it comes back as ('other', '<variant>')."""
    if isinstance(t, dict):
        if "__text__" in t:
            return ("other", t["__text__"])
        if len(t) == 1:
            k, v = next(iter(t.items()))
            if k == "primitive" and isinstance(v, str):
                return ("prim", v)
            if k == "resolved_path" and isinstance(v, dict):
                return ("path", _last_seg(v.get("path") or ""), [convert_type(a) for a in _generic_args(v.get("args"))])
            if k == "tuple" and isinstance(v, list):
                return ("tuple", [convert_type(a) for a in v]) if v else ("unit",)
            if k in ("slice", "array"):
                inner = v if k == "slice" else (v or {}).get("type")
                return ("slice", convert_type(inner))
            if k == "borrowed_ref" and isinstance(v, dict):
                if v.get("is_mutable"):
                    return ("other", render_type(t))
                return ("ref", convert_type(v.get("type")))
            if k in ("impl_trait", "dyn_trait"):
                return ("impl", render_type(t))
            return ("other", render_type(t))
    return ("other", render_type(t))


def _render_args(args) -> str:
    if not isinstance(args, dict):
        return ""
    ab = args.get("angle_bracketed")
    if isinstance(ab, dict):
        parts = []
        for a in ab.get("args") or []:
            if a == "infer":
                parts.append("_")
                continue
            if not isinstance(a, dict):
                continue
            if "type" in a:
                parts.append(render_type(a["type"]))
            elif "lifetime" in a:
                parts.append(str(a["lifetime"]))
            elif "const" in a:
                c = a["const"]
                parts.append(str((c.get("expr") or c.get("value")) if isinstance(c, dict) else c))
            elif "infer" in a:
                parts.append("_")
        for c in ab.get("constraints") or []:
            if not isinstance(c, dict):
                continue
            b = c.get("binding") or {}
            if "equality" in b:
                eq = b["equality"]
                parts.append(f"{c.get('name')} = {render_type(eq['type']) if isinstance(eq, dict) and 'type' in eq else '_'}")
            elif "constraint" in b:
                parts.append(f"{c.get('name')}: {_render_bounds(b['constraint'])}")
        return f"<{', '.join(parts)}>" if parts else ""
    pa = args.get("parenthesized")
    if isinstance(pa, dict):
        ins = ", ".join(render_type(i) for i in pa.get("inputs") or [])
        out = pa.get("output")
        return f"({ins})" + (f" -> {render_type(out)}" if out is not None else "")
    return ""


def _precise_arg(u) -> str:
    """PreciseCapturingArg: {"lifetime": "'a"} | {"param": "T"} (a bare string is taken as is)."""
    if isinstance(u, dict) and len(u) == 1:
        return str(next(iter(u.values())))
    return str(u)


def _render_bounds(bounds) -> str:
    parts = []
    for b in bounds or []:
        if not isinstance(b, dict):
            continue
        if "trait_bound" in b:
            tb = b["trait_bound"]
            tr = tb.get("trait") or {}
            gp = [g.get("name", "") for g in tb.get("generic_params") or [] if isinstance(g, dict)]
            mod = {"maybe": "?", "maybe_const": "~const "}.get(tb.get("modifier"), "")
            parts.append((f"for<{', '.join(gp)}> " if gp else "") + mod + (tr.get("path") or "") + _render_args(tr.get("args")))
        elif "outlives" in b:
            parts.append(str(b["outlives"]))
        elif "use" in b:
            parts.append(f"use<{', '.join(_precise_arg(u) for u in b['use'])}>")
    return " + ".join(parts)




_ABI_NAMES = {"C": "C", "Cdecl": "cdecl", "Stdcall": "stdcall", "Fastcall": "fastcall", "Aapcs": "aapcs", "Win64": "win64",
              "SysV64": "sysv64", "System": "system"}


def abi_text(abi) -> str:
    """The string of `extern "<abi>"` for a FunctionHeader `abi` ('' for the default `Rust`): `C`, `C-unwind`, `sysv64`, or the
    free text of `Other`. A plain string of another shape is lowercased."""
    if abi is None or abi in ("Rust", "rust"):
        return ""
    if isinstance(abi, dict):
        if len(abi) != 1:
            return ""
        k, v = next(iter(abi.items()))
        if k == "Other":
            return str(v)
        return _ABI_NAMES.get(k, str(k).lower()) + ("-unwind" if isinstance(v, dict) and v.get("unwind") else "")
    return str(abi).lower()


def render_type(t) -> str:
    """Source-like text of a rustdoc `Type` (paths as written, whitespace-normalised): what the
    source says for `impl`/`other` types. Unknown variants render as `<variant>`."""
    if not isinstance(t, dict):
        return "()" if t is None else "_"
    if "__text__" in t:
        return t["__text__"]
    if len(t) != 1:
        return "_"
    k, v = next(iter(t.items()))
    if k == "primitive":
        return str(v)
    if k == "generic":
        return str(v)
    if k == "resolved_path" and isinstance(v, dict):
        return (v.get("path") or "") + _render_args(v.get("args"))
    if k == "tuple" and isinstance(v, list):
        return "(" + ", ".join(render_type(a) for a in v) + ("," if len(v) == 1 else "") + ")"
    if k == "slice":
        return f"[{render_type(v)}]"
    if k == "array" and isinstance(v, dict):
        return f"[{render_type(v.get('type'))}; {v.get('len')}]"
    if k == "borrowed_ref" and isinstance(v, dict):
        lt = v.get("lifetime")
        return "&" + (f"{lt} " if lt else "") + ("mut " if v.get("is_mutable") else "") + render_type(v.get("type"))
    if k == "raw_pointer" and isinstance(v, dict):
        return ("*mut " if v.get("is_mutable") else "*const ") + render_type(v.get("type"))
    if k == "impl_trait":
        return "impl " + _render_bounds(v)
    if k == "dyn_trait" and isinstance(v, dict):
        parts = []
        for pt in v.get("traits") or []:
            tr = pt.get("trait") or {}
            gp = [g.get("name", "") for g in pt.get("generic_params") or [] if isinstance(g, dict)]
            parts.append((f"for<{', '.join(gp)}> " if gp else "") + (tr.get("path") or "") + _render_args(tr.get("args")))
        if v.get("lifetime"):
            parts.append(str(v["lifetime"]))
        return "dyn " + " + ".join(parts)
    if k == "function_pointer" and isinstance(v, dict):
        sig = v.get("sig") or {}
        ins = ", ".join(render_type(i[1] if isinstance(i, list) and len(i) == 2 else i) for i in sig.get("inputs") or [])
        out = sig.get("output")
        return f"fn({ins})" + (f" -> {render_type(out)}" if out is not None else "")
    if k == "qualified_path" and isinstance(v, dict):
        tr = v.get("trait") or {}
        tpath = tr.get("path") or ""
        slf = render_type(v.get("self_type"))
        name = (v.get("name") or "") + _render_args(v.get("args"))
        if tpath:
            return f"<{slf} as {tpath}{_render_args(tr.get('args'))}>::{name}"
        return f"{slf}::{name}"
    if k == "infer":
        return "_"
    return f"<{k}>"






def doc_summary(docs) -> str:
    """First paragraph of an item's `docs` on one line, intra-doc links flattened: what the
    `///` lines make (lines up to the first blank one, each stripped, joined by a space, [`Foo`] / [`Foo`](..) -> `Foo`)."""
    if not isinstance(docs, str):
        return ""
    out = []
    for ln in docs.splitlines():
        ln = ln.strip()
        if not ln:
            break
        out.append(ln)
    return re.sub(r"\[`([^`]+)`\](\([^)]*\))?", r"`\1`", " ".join(out))


def _quoted(s) -> str:
    return json.dumps(str(s), ensure_ascii=False)


def _repr_text(r) -> str:
    """`repr(C, u8, align(4))` of an AttributeRepr {kind: rust|c|transparent|simd, align, packed, int}."""
    r = r if isinstance(r, dict) else {}
    kind = r.get("kind")
    parts = []
    if kind in ("c", "transparent", "simd"):
        parts.append("C" if kind == "c" else kind)
    elif kind == "rust" and not any(r.get(k) is not None for k in ("align", "packed", "int")):
        parts.append("Rust")
    if r.get("int") is not None:
        parts.append(str(r["int"]))
    if r.get("align") is not None:
        parts.append(f"align({r['align']})")
    if r.get("packed") is not None:
        parts.append(f"packed({r['packed']})")
    return f"repr({', '.join(parts)})"


def _attr_text(a) -> Optional[str]:
    """One Attribute as `#[...]` text, None when it has no source form here (see attr_texts)."""
    if isinstance(a, str):
        return None if a == "automatically_derived" else f"#[{a}]"
    if not isinstance(a, dict) or len(a) != 1:
        return None
    k, v = next(iter(a.items()))
    if k == "other" and isinstance(v, str):
        t = " ".join(v.split())
        return t if t.startswith("#[") and not t.startswith("#[attr =") else None
    if k == "must_use":
        reason = v.get("reason") if isinstance(v, dict) else None
        return f"#[must_use = {_quoted(reason)}]" if reason is not None else "#[must_use]"
    if k in ("export_name", "link_section") and isinstance(v, str):
        return f"#[{k} = {_quoted(v)}]"
    if k == "repr":
        return f"#[{_repr_text(v)}]"
    if k == "target_feature" and isinstance(v, dict):
        return f"#[target_feature({', '.join('enable = ' + _quoted(f) for f in v.get('enable') or [])})]"
    return None


def attr_texts(item: dict) -> list:
    """An item's attributes as `#[...]` text (whitespace-normalised).
    Formats 57-61 list the known attributes as the `Attribute` enum: unit variants by name (`non_exhaustive`, `macro_export`,
    `no_mangle`), `must_use` / `export_name` / `link_section` / `repr` / `target_feature` as structured data (rebuilt here;
    rustdoc may reorder a repr's parts: `repr(i8, C)` reads `repr(C, i8)`), and the rest as {"other": "#[..]"}. Not in the
    JSON, so not here: `#[derive]` (see derived_traits), `#[cfg]`/`#[doc]` (resolved/consumed by rustc), `automatically_derived`
    (marks derive-generated impls), `#[attr = ..]` compiler-internal renderings."""
    out = []
    for a in item.get("attrs") or []:
        t = _attr_text(a)
        if t:
            out.append(t)
    return out


def source_sha1(crate_dir) -> str:
    """sha1 over a crate's src/**/*.rs (C-locale path order) then Cargo.toml: what make_rustdoc_json.sh records as
    `source_sha1` in the .meta sidecar, so a committed JSON can be checked against the sources it was made from."""
    import hashlib
    d = Path(crate_dir)
    h = hashlib.sha1()
    for f in sorted((p for p in (d / "src").rglob("*.rs") if p.is_file()), key=lambda p: os.fsencode(str(p))):
        h.update(f.read_bytes())
    h.update((d / "Cargo.toml").read_bytes())
    return h.hexdigest()


def main(argv: Iterable[str]) -> int:
    argv = list(argv)
    if len(argv) != 1:
        print(__doc__.strip().split("CLI:")[-1].strip(), file=sys.stderr)
        return 2
    try:
        rdj = load_dir(argv[0])
    except RdjError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for name, c in sorted(rdj.crates.items()):
        kinds: dict = {}
        for it in c.index.values():
            kinds[inner_kind(it)] = kinds.get(inner_kind(it), 0) + 1
        top = [(c.kind(i), (c.item(i) or {}).get("name")) for i in c.children(c.root)]
        print(f"{name}: format_version {c.format_version}, {len(c.index)} items, {len(c.paths)} paths, "
              f"{len(c.external_crates)} external crates, private items: {c.includes_private}, {c.meta.get('rustc', 'rustc unknown')}")
        print("  kinds:", ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
        print("  root:", ", ".join(f"{k} {n}" for k, n in top))
    for w in rdj.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
