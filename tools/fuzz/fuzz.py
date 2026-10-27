"""Fuzz driver for the rustdoc-JSON generator: Rust source case -> rustdoc JSON -> generator -> sanity checks.
Needs `rustdoc` (nightly/-Z unstable-options or RUSTC_BOOTSTRAP=1) and AZL_RDJ_FORMAT_RANGE matching it."""
import os, re, shutil, subprocess, sys, json, time
from pathlib import Path

ROOT = Path(os.environ.get("LUAXITE", Path(__file__).resolve().parents[2]))
BASE = (ROOT / "harness/fake/azalea/src/lib.rs").read_text()
EXTRAS = list((ROOT / "harness/src/luau").glob("extra_*.rs"))
ENV = {**os.environ, "RUSTC_BOOTSTRAP": "1"}
LUAU_KW = set("and break do else elseif end false for function if in local nil not or repeat return then true until while".split())
INJECT = "    Death(Option<Arc<protocol::packets::game::ClientboundPlayerCombatKill>>),\n"
assert INJECT in BASE

def M(*bodies, hdr="impl Client"):
    return hdr + " {\n" + "\n".join(bodies) + "\n}\n"

def build(name, items, variants, workdir, files=None):
    d = workdir / name
    shutil.rmtree(d, ignore_errors=True)
    (d / "azalea/src").mkdir(parents=True)
    shutil.copy(ROOT / "harness/fake/azalea/Cargo.toml", d / "azalea/Cargo.toml")
    src = BASE.replace(INJECT, "".join(f"    {v},\n" for v in variants) + INJECT) + "\n" + items
    (d / "azalea/src/lib.rs").write_text(src)
    for rel, data in (files or {}).items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return d

def rdj(d):
    out = d / "rdj"; shutil.rmtree(out, ignore_errors=True); out.mkdir()
    p = subprocess.run(["rustdoc", "--edition", "2024", "-Z", "unstable-options", "--output-format", "json", "--document-private-items",
                        "--crate-type", "lib", "--crate-name", "azalea", "src/lib.rs", "-o", str(out)],
                       cwd=d / "azalea", capture_output=True, text=True, timeout=90, env=ENV)
    return (out if p.returncode == 0 and (out / "azalea.json").exists() else None), p.stderr

def gen(d, tag, out):
    ro, lo = d / f"rust_{tag}", d / f"luau_{tag}"
    for x in (ro, lo): shutil.rmtree(x, ignore_errors=True); x.mkdir()
    for e in EXTRAS: shutil.copy(e, ro)
    p = subprocess.run([sys.executable, str(ROOT / "tools/luaxite_gen.py"), "--azalea", str(d), "--rustdoc", str(out),
                        "--rust-out", str(ro), "--luau-out", str(lo)], capture_output=True, text=True, timeout=60, cwd=ROOT, env=ENV)
    return p.returncode, (p.stdout + p.stderr).strip(), ro, lo

def run_gen(d):
    out, err = rdj(d)
    if out is None:
        return "REJECT", err.strip()[-300:], d / "rust", d / "luau"
    try:
        code, text, ro, lo = gen(d, "rd", out)
    except subprocess.TimeoutExpired:
        return "HANG", "", d / "rust_rd", d / "luau_rd"
    return ("OK" if code == 0 else "CRASH"), text, ro, lo

def rust_errors(ro):
    """Cheap syntax sanity (no Rust syntax tree available): balanced () [] {} outside strings/comments."""
    errs = []
    for f in sorted(ro.glob("gen_*.rs")):
        t = re.sub(r"//[^\n]*|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])'", "", f.read_text()); st = []
        for ch in t:
            if ch in "([{": st.append(ch)
            elif ch in ")]}":
                if not st or "([{".index(st.pop()) != ")]}".index(ch): errs.append(f"{f.name}: unbalanced {ch}"); break
        else:
            if st: errs.append(f"{f.name}: unclosed {st[-1]}")
    return errs

def luau_problems(lo):
    probs = []
    txt = (lo / "azalea.d.luau").read_text()
    cls = None; seen = {}
    names = re.findall(r"^declare extern type (\S+)", txt, re.M)
    if len(names) != len(set(names)): probs.append(f"duplicate class names {names}")
    tnames = re.findall(r"^type (\S+) =", txt, re.M)
    if len(tnames) != len(set(tnames)): probs.append("duplicate type alias: " + str([n for n in set(tnames) if tnames.count(n) > 1]))
    for ln in txt.splitlines():
        m = re.match(r"declare extern type (\S+)", ln)
        if m: cls = m.group(1); seen = {}; continue
        if ln == "end": cls = None; continue
        m = re.match(r"\s+function (\S+?)\(", ln)
        if m and cls:
            n = m.group(1)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n): probs.append(f"{cls}: invalid method name {n!r}")
            elif n in LUAU_KW: probs.append(f"{cls}: keyword method name {n}")
            if n in seen and n != "on": probs.append(f"{cls}: duplicate method {n}")
            seen[n] = 1
        if cls and ln.strip().startswith("function "):
            i = ln.index("(") + 1; depth = 1; j = i; parts = []; cur = ""
            while j < len(ln) and depth:
                c = ln[j]
                if c in "({[<": depth += 1
                elif c in ")}]>": depth -= 1
                if depth == 1 and c == "," or depth == 0: parts.append(cur); cur = ""
                else: cur += c
                j += 1
            for part in parts:
                pn = part.strip().split(":")[0].strip()
                if not pn or pn == "self": continue
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", pn) or pn in LUAU_KW: probs.append(f"{cls}: bad param name {pn!r}")
    return probs

def evaluate(name, items, variants, workdir, files=None):
    d = build(name, items, variants, workdir, files)
    st, out, ro, lo = run_gen(d)
    res = dict(name=name, status=st, out=out)
    if st == "OK":
        res["rust_err"] = rust_errors(ro)
        res["luau"] = luau_problems(lo)
        res["dir"] = str(d)
    return res
