import json, sys, time, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import fuzz, cases
W = Path("/tmp/fz"); W.mkdir(exist_ok=True)
import importlib
if len(sys.argv) > 1 and sys.argv[1] == "--wave2":
    import cases2; cases.CASES.clear(); cases.CASES.update(cases2.CASES); sys.argv.pop(1)
base = fuzz.evaluate("_base", "", [], W)
print("baseline:", base["status"], base.get("rust_err"), base.get("luau"), flush=True)
only = sys.argv[1:] 
names = [n for n in cases.CASES if not only or any(o in n for o in only)]
t = time.time()
def go(n):
    items, var = cases.CASES[n][:2]
    files = cases.CASES[n][2] if len(cases.CASES[n]) > 2 else None
    try:
        return fuzz.evaluate(n, items, var, W, files)
    except Exception as e:
        return dict(name=n, status="HARNESS-ERR", out=repr(e))
with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(go, names))
json.dump(dict(base=base, res=res), open(os.environ.get("OUT","/tmp/fz_results.json"), "w"))
print("done", len(res), f"{time.time()-t:.0f}s")
