"""`require` of embedded modules (slices 15, 10-11): where the caller can yield, the chunk of an embedded src/**.luau module runs
with `call_async`, so its top level may task.wait / net.* / process.*; where it cannot (a string.gsub callback) it runs with a
plain `call` (`load_embedded_sync`), because an async load there fails with a yield error. @lune/* and cache hits stay on a plain
synchronous lookup, a module that is required again while it is still loading errors (instead of running twice) and the cache is
filled only after the chunk returned. mod.rs is built by the harness only without cargo here, so this checks the structure."""
import re
import unittest

from _common import ROOT, read
from test_size_caps import fn_body


class RequireAsync(unittest.TestCase):
    def setUp(self):
        self.src = read("rust/luau/mod.rs")
        self.body = fn_body(self.src, "fn install_require")

    def test_harness_copy_is_in_sync(self):
        self.assertEqual(self.src, read("harness/src/luau/mod.rs"))

    def test_embedded_chunk_runs_with_call_async(self):
        self.assertIn("create_async_function", self.body)
        self.assertIn("call_async(", self.body)
        self.assertIn(".into_function()", self.body)

        self.assertNotIn(".call(())?;", self.body.split("let load_embedded")[1].split("let glue")[0])
        self.assertNotRegex(self.body, r"lua\.load\(\*source\)[^;]*\.call\(\(\)\)")

    def test_lookup_is_synchronous_and_keeps_lune_modules_sync(self):
        resolve = self.body.split("let resolve")[1].split("let load_embedded")[0]
        self.assertIn("lua.create_function(", self.body.split("let resolve")[1][:80])
        self.assertIn("lune_libs::require(lua, &loaded, &name)", resolve)
        self.assertNotIn("create_async_function", resolve)
        self.assertNotIn("call_async", resolve)

        self.assertIn("f.call(name)", resolve)

    def test_cycle_is_an_error_not_a_second_run(self):
        self.assertIn('"azalea_loading"', self.body)
        self.assertIn("module '{key}' is still loading (cyclic require?)", self.body)
        resolve = self.body.split("let resolve")[1].split("let load_embedded")[0]
        self.assertLess(resolve.index("azalea_loaded"), resolve.index("is still loading"))



    def test_loading_mark_is_removed_by_a_drop_guard(self):
        drop = fn_body(self.src, "impl Drop for Loading")
        self.assertIn("Value::Nil", drop)
        begin = fn_body(self.src, "fn begin_embedded")
        self.assertIn("let guard = Loading", begin)
        self.assertLess(begin.index("loading.set(key, true)"), begin.index("let guard"))

        load = self.body.split("let load_embedded =")[1].split("let load_embedded_sync")[0]
        sync = self.body.split("let load_embedded_sync")[1].split("let glue")[0]
        for part in (load, sync):
            self.assertIn("let (chunk, _guard) = begin_embedded(", part)

    def test_loaded_table_set_only_after_the_chunk_returns(self):
        load = self.body.split("let load_embedded =")[1].split("let load_embedded_sync")[0]
        sync = self.body.split("let load_embedded_sync")[1].split("let glue")[0]
        self.assertLess(load.index("call_async(())"), load.index("finish_embedded("))
        self.assertLess(sync.index("chunk.call(())"), sync.index("finish_embedded("))
        self.assertNotIn("loaded.set(", load + sync)
        finish = fn_body(self.src, "fn finish_embedded")
        self.assertEqual(finish.count("loaded.set("), 1)
        self.assertEqual(self.src.count('loaded.set(key, value.clone())'), 1)

        self.assertIn("mlua::Value::Boolean(true)", finish)

    def test_glue_calls_resolve_then_the_async_loader(self):
        glue = self.body.split("let glue")[1]
        self.assertIn("local value, key = resolve(name)", glue)
        self.assertIn("if key == nil then", glue)
        self.assertIn("return load_embedded(key)", glue)
        self.assertIn('lua.globals().set("require", require)', self.body)

    def test_glue_branches_on_isyieldable(self):
        glue = self.body.split("let glue")[1]
        self.assertIn("local resolve, load_embedded, load_embedded_sync = ...", glue)
        self.assertIn("if coroutine.isyieldable() then", glue)
        yielding, other = glue.split("if coroutine.isyieldable() then")[1].split("else", 1)
        self.assertIn("return load_embedded(key)", yielding)
        self.assertNotIn("load_embedded_sync", yielding)
        self.assertIn("return load_embedded_sync(key)", other.split("end", 1)[0])

        self.assertIn("glue.call((resolve, load_embedded, load_embedded_sync))", self.body)

    def test_sync_loader_runs_the_chunk_with_a_plain_call(self):
        sync = self.body.split("let load_embedded_sync")[1].split("let glue")[0]
        self.assertIn("lua.create_function(", sync[:40])
        self.assertNotIn("create_async_function", sync)
        self.assertNotIn("call_async", sync)
        self.assertNotIn(".await", sync)
        self.assertIn("chunk.call(())?", sync)

        load = self.body.split("let load_embedded =")[1].split("let load_embedded_sync")[0]
        self.assertIn("create_async_function", load)
        self.assertIn("chunk.call_async(()).await?", load)
        self.assertNotIn("chunk.call(())", load)

    def test_sync_loader_shares_the_loaded_and_loading_tables(self):
        sync = self.body.split("let load_embedded_sync")[1].split("let glue")[0]

        self.assertIn("begin_embedded(lua, &key)", sync)
        self.assertIn("finish_embedded(lua, &key, value)", sync)
        begin = fn_body(self.src, "fn begin_embedded")
        finish = fn_body(self.src, "fn finish_embedded")
        self.assertIn('named_registry_value("azalea_loading")', begin)
        self.assertIn('named_registry_value("azalea_loaded")', finish)

        glue = self.body.split("let glue")[1]
        self.assertLess(glue.index("resolve(name)"), glue.index("isyieldable"))

        loaders = self.body.split("let load_embedded =")[1].split("let glue")[0]
        self.assertNotIn("azalea_loaded", loaders)
        self.assertNotIn("azalea_loading", loaders)

    def test_modules_are_not_preloaded_at_startup(self):

        self.assertEqual(self.src.count("scripts::SCRIPTS"), 2)
        self.assertIn("scripts::SCRIPTS", fn_body(self.src, "fn begin_embedded"))
        self.assertIn("scripts::SCRIPTS", self.body.split("let resolve")[1].split("let load_embedded =")[0])
        self.assertNotIn("begin_embedded(", self.src.replace(fn_body(self.src, "fn begin_embedded"), "").split("fn install_require")[0])

    def test_gsub_project_exists_and_is_hooked_into_ci(self):
        main = read("tests/projects/require_gsub/src/main.luau")
        self.assertIn("string.gsub", main)
        self.assertIn('require("probe")', main)
        self.assertIn("coroutine.isyieldable()", main)
        self.assertIn('E2E PASS require_gsub"', main)
        self.assertIn("process.exit(0)", main)

        self.assertIn("azalea.join = function", main)
        self.assertTrue((ROOT / "tests/projects/require_gsub/src/probe.luau").exists())


        self.assertNotRegex(main, r"handlers\s*==\s*\d")
        self.assertIn("joins == 1", main)
        probe = "\n".join(l for l in read("tests/projects/require_gsub/src/probe.luau").splitlines() if not l.lstrip().startswith("--"))
        self.assertEqual(len(re.findall(r"azalea\.join\b", probe)), 1)
        self.assertIn("bot:on(", probe)

        self.assertIn("tests/projects/run.sh", read(".github/workflows/rust.yml"))
        self.assertNotIn("lune_require_gsub", read("tests/e2e/run.sh"))


class TestsOwnTheirModules(unittest.TestCase):
    """No test depends on the repo's src/, and the binary build has no test options: a test that needs an embedded module is a project under
    tests/projects with its own src/, built as its own binary by tests/projects/run.sh."""

    def test_e2e_scripts_use_no_modules_of_their_own(self):

        for path in sorted((ROOT / "tests/e2e").glob("*.luau")):
            for name in re.findall(r'require\(\s*"([^"@][^"]*)"\s*\)', path.read_text()):
                self.fail(f"{path.name} requires {name!r}: a test that needs its own module is a project in tests/projects")

    def test_no_test_names_src(self):
        for path in sorted((ROOT / "tests").glob("**/*.luau")):
            code = "\n".join(l for l in path.read_text().splitlines() if not l.lstrip().startswith("--"))
            self.assertNotIn("src/", code.replace("/src/", "").replace("tests/projects", ""), f"{path} reads from src/")

    def test_every_project_has_its_own_entry_script(self):
        projects = [d for d in (ROOT / "tests/projects").iterdir() if d.is_dir()]
        self.assertTrue(projects)
        for d in projects:
            self.assertTrue((d / "src/main.luau").is_file(), f"{d.name}: no src/main.luau")
            self.assertIn(f'E2E PASS {d.name}"', (d / "src/main.luau").read_text(), f"{d.name}: main.luau must print its PASS line")

    def test_the_binary_build_has_no_test_options(self):
        build = read("build.rs")
        self.assertNotIn("tests/", build)
        self.assertNotRegex(build, r'var_os\("LUAXITE_[A-Z_]*"\)')
        run = read("tests/projects/run.sh")

        self.assertIn('cp -R "$proj/src" "$scratch/src"', run)
        self.assertNotIn('"$root/src"', run)


if __name__ == "__main__":
    unittest.main()
