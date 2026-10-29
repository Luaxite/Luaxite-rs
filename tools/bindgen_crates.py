#!/usr/bin/env python3
"""bindgen_crates.py - which crates does `bind/` ask us to bind? (stdlib only; PROMPT item I3)

Layout (root R): roots = what sits directly in `R/bind/`: (a) a child `R/bind/<n>/` whose Cargo.toml has a `[package]`; (b) a child
`R/bind/<n>-src/` that is a workspace checkout: its member `R/bind/<n>-src/<n>/` (the checkout's own manifest is not read). Nothing else is a root:
the dependencies in R/Cargo.toml decide what the host links, not what gets bindings. The crate set is the roots plus the closure over `path` dependencies, read with
`cargo metadata --no-deps --format-version 1 --manifest-path <dir>/Cargo.toml` (never a full resolve, never the network).
Output: library packages only, dependencies first (Kahn's algorithm, ties alphabetical, like tools/make_rustdoc_json_ws.sh).

    python3 tools/bindgen_crates.py [--root R]         # prints a JSON list: name lib dir manifest workspace_root
    BINDGEN_CARGO=/path/to/cargo-shim                  # overrides the cargo binary (tests)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

LIB_KINDS = {"lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro"}


class CrateError(Exception):
    """One-line reason; the CLI prints `error: <reason>` and exits 1."""


def _real(p) -> str:
    return os.path.realpath(str(p))


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CrateError(f"cannot read {path}: {' '.join(str(e).split())[:160]}") from None


def roots(root: Path) -> list[str]:
    """Crate directories (realpaths) named by the layout: bind/<n>/ with a [package]; bind/<n>-src/<n>/ of a workspace checkout bind/<n>-src/."""
    found: list[str] = []
    bind = root / "bind"
    if bind.is_dir():
        for d in sorted(bind.iterdir()):
            m = d / "Cargo.toml"
            if not (d.is_dir() and m.is_file()):
                continue
            member = d / d.name[:-4] if d.name.endswith("-src") and len(d.name) > 4 else None
            if member and (member / "Cargo.toml").is_file() and "package" in _load_toml(member / "Cargo.toml"):
                found.append(_real(member))  # a workspace checkout bind/<n>-src/: its crate <n>/ (the checkout's root manifest is not looked at)
            elif "package" in _load_toml(m):
                found.append(_real(d))
    return list(dict.fromkeys(found))


class _Metadata:
    """`cargo metadata --no-deps` per manifest, cached; every package seen is indexed by its manifest realpath."""

    def __init__(self, cargo: str):
        self.cargo = cargo
        self.packages: dict[str, dict] = {}
        self.done: set[str] = set()

    def load(self, manifest: str) -> None:
        if manifest in self.done:
            return
        if not os.path.isfile(manifest):
            raise CrateError(f"no Cargo.toml at {os.path.dirname(manifest)}")
        try:
            p = subprocess.run([self.cargo, "metadata", "--no-deps", "--format-version", "1", "--manifest-path", manifest],
                               capture_output=True, text=True)
        except OSError:
            raise CrateError(f"cannot run cargo ({self.cargo!r}); install it or set BINDGEN_CARGO") from None
        if p.returncode != 0:
            why = next((l for l in p.stderr.splitlines() if l.strip()), "no output")
            raise CrateError(f"cargo metadata failed for {manifest}: {why.strip()[:200]}")
        try:
            meta = json.loads(p.stdout)
        except ValueError:
            raise CrateError(f"cargo metadata printed no JSON for {manifest}") from None
        for pkg in meta.get("packages", []):
            self.packages[_real(pkg["manifest_path"])] = {**pkg, "_ws": meta.get("workspace_root", os.path.dirname(manifest))}
        self.done.add(manifest)
        self.done.update(_real(p["manifest_path"]) for p in meta.get("packages", []))

    def package(self, crate_dir: str) -> dict:
        manifest = os.path.join(crate_dir, "Cargo.toml")
        self.load(manifest)
        if manifest not in self.packages:
            raise CrateError(f"{manifest} is not a package (a virtual workspace has no [package] to bind)")
        return self.packages[manifest]


def _is_lib(pkg: dict) -> bool:
    return any(k in LIB_KINDS for t in pkg.get("targets", []) for k in t.get("kind", []))


def resolve(root, cargo: str | None = None) -> list[dict]:
    """Crate set for `root`, dependencies first. Raises CrateError."""
    root = Path(root)
    md = _Metadata(cargo or os.environ.get("BINDGEN_CARGO") or "cargo")
    seen: dict[str, dict] = {}
    stack = list(reversed(roots(root)))
    while stack:
        d = stack.pop()
        pkg = md.package(d)
        m = _real(pkg["manifest_path"])
        if m in seen:
            continue
        seen[m] = pkg
        for dep in pkg.get("dependencies", []):
            if dep.get("path"):
                stack.append(_real(dep["path"]))
    libs = {m: p for m, p in seen.items() if _is_lib(p)}
    names: dict[str, str] = {}
    for m, p in libs.items():
        key = p["name"].replace("-", "_")
        if key in names:
            raise CrateError(f"two crates named {p['name']}: {os.path.dirname(names[key])} and {os.path.dirname(m)}")
        names[key] = m
    deps = {m: {_real(os.path.join(d["path"], "Cargo.toml")) for d in p.get("dependencies", []) if d.get("path")} & (libs.keys() - {m})
            for m, p in libs.items()}
    order: list[str] = []
    while len(order) < len(libs):
        ready = sorted((m for m in libs if m not in order and deps[m] <= set(order)), key=lambda m: (libs[m]["name"].replace("-", "_"), m))
        if not ready:
            left = sorted(libs[m]["name"] for m in libs if m not in order)
            raise CrateError("dependency cycle among: " + ", ".join(left))
        order.append(ready[0])
    out = []
    for m in order:
        p = libs[m]
        lib = next((t["name"] for t in p["targets"] if any(k in LIB_KINDS for k in t["kind"])), p["name"]).replace("-", "_")
        out.append({"name": p["name"], "lib": lib, "dir": os.path.dirname(m), "manifest": m, "workspace_root": _real(p["_ws"])})
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = "."
    if argv[:1] == ["--root"] and len(argv) == 2:
        root = argv[1]
    elif argv:
        print("usage: bindgen_crates.py [--root R]", file=sys.stderr)
        return 2
    try:
        crates = resolve(root)
    except CrateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    json.dump(crates, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
