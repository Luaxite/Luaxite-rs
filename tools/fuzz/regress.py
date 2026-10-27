"""Regression checks for the generator bugs the fuzz cases found (see FINDINGS.md). Exit 0 = all fixed.
Run: python3 tools/fuzz/regress.py   (needs `rustdoc`, apt rustc-1.91 + AZL_RDJ_FORMAT_RANGE=56-56, or nightly; skipped without it)"""
import re, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuzz, cases, cases2, cases3

ALL = {**cases.CASES, **cases2.CASES, **cases3.CASES}
bad = []

def check(name, ok, why):
    if not ok:
        bad.append(f"{name}: {why}")

if shutil.which("rustdoc"):
    W = Path(tempfile.mkdtemp(prefix="fz_regress_"))
    def rd(name):
        items, var, *rest = ALL[name]
        d = fuzz.build("rd_" + name, items, var, W, rest[0] if rest else None)
        out, _ = fuzz.rdj(d)
        if out is None: return None
        code, last, ro, lo = fuzz.gen(d, "rd", out)
        return code, (lo / "GEN_REPORT.json").read_text() if code == 0 else "", (lo / "azalea.d.luau").read_text() if code == 0 else "", "\n".join(p.read_text() for p in sorted(ro.glob("gen_*.rs")))
    for n in ("type_no_clone_optarc_event", "ev_arc_vec_noclone", "type_no_clone_arc_ret"):
        x = rd(n)
        if x: check("rdj " + n, x[0] == 0 and "LuaT((*v).clone())" not in x[3] and (n == "type_no_clone_arc_ret" or "not `Clone`" in x[1]), "non-Clone Arc not skipped under rustdoc")
    x = rd("type_kw_fields_ret"); x and check("rdj kw fields", "v.r#type" in x[3] and "v.type" not in x[3], "keyword field not raw under rustdoc")
    for n in ("doc_tab", "doc_unicode"):
        x = rd(n); x and check("rdj " + n, x[0] == 0 and not re.search(r"[\x00-\x08\x0b-\x1f\u202e]|\t", x[2]), "control chars in d.luau under rustdoc")
    x = rd("file_dir_named_rs"); x and check("rdj file_dir_named_rs", x[0] == 0, "rustdoc front end crashed on a directory named x.rs")
    x = rd("rec_mutual"); x and check("rdj rec_mutual", x[0] == 0, "rustdoc front end crashed on recursive types")
else:
    print("(rustdoc not installed: rustdoc-path regressions skipped)")
print("\n".join(bad) or f"fuzz regress: OK ({len(ALL)} cases available)")
sys.exit(1 if bad else 0)
