"""Every Lune function this repo provides: registered in the Rust source and exercised by an e2e script.

The e2e scripts need a built binary (tests/e2e/run.sh); this file keeps them honest without one: a function nobody calls from
tests/e2e/lune*.luau fails here. For the five modules built by Lune's own crates the API is Lune's documented one.
"""
import re
import unittest

from _common import ROOT, read

IN_TREE = {
    "task": ["spawn", "defer", "delay", "wait", "cancel"],
    "stdio": ["color", "style", "format", "write", "ewrite", "readLine", "readToEnd", "prompt"],
    "process": [
        "os", "arch", "endianness", "args", "cwd", "env", "exit", "exec", "create",
        "kill", "status", "stdin", "stdout", "stderr", "read", "readToEnd", "write", "close", "ok", "code",
    ],
    "net": [
        "urlEncode", "urlDecode", "request", "socket", "serve", "tcp", "http", "ws", "connect", "stop",
        "ok", "statusCode", "statusMessage", "headers", "body",
        "ip", "port", "method", "path", "query",
        "send", "next", "close", "closeCode",
        "read", "write", "remoteIp", "remotePort", "localIp", "localPort",
    ],
}

LUNE_CRATES = {
    "fs": ["readFile", "readDir", "writeFile", "writeDir", "removeFile", "removeDir", "metadata", "isFile", "isDir", "move", "copy"],
    "serde": ["encode", "decode", "compress", "decompress", "hash", "hmac"],
    "regex": ["new", "isMatch", "find", "captures", "split", "replace", "replaceAll", "get", "group", "format"],
    "datetime": [
        "now", "fromUnixTimestamp", "fromUniversalTime", "fromLocalTime", "fromIsoDate", "fromRfc3339", "fromRfc2822",
        "toIsoDate", "toRfc3339", "toRfc2822", "toLocalTime", "toUniversalTime", "formatLocalTime", "formatUniversalTime",
        "unixTimestamp", "unixTimestampMillis",
    ],
    "luau": ["compile", "load"],
}

ALL_MODULES = ["fs", "serde", "regex", "datetime", "luau", "task", "stdio", "process", "net"]


def script(name):
    return read(f"tests/e2e/{name}.luau")


def mentions(text, name):
    return re.search(rf"[.:\[\"']{re.escape(name)}\b", text) is not None


class InTreeModules(unittest.TestCase):
    def test_every_name_is_registered_in_rust(self):
        for mod, names in IN_TREE.items():
            src = read(f"rust/luau/lune_{mod}.rs")
            for n in names:
                self.assertIn(f'"{n}"', src, f"@lune/{mod}: `{n}` is not registered in rust/luau/lune_{mod}.rs")

    def test_every_name_is_exercised_by_its_e2e_script(self):
        missing = [f"@lune/{mod}.{n}" for mod, names in IN_TREE.items() for n in names if not mentions(script(f"lune_{mod}"), n)]
        self.assertEqual(missing, [], "never used in tests/e2e/lune_<module>.luau")

    def test_each_module_has_an_error_path_check(self):
        for mod in IN_TREE:
            text = script(f"lune_{mod}")
            self.assertRegex(text, r"pcall", f"tests/e2e/lune_{mod}.luau never checks that bad input raises")


class LuneCrateModules(unittest.TestCase):
    def test_every_documented_function_is_exercised(self):
        missing = [f"@lune/{mod}.{n}" for mod, names in LUNE_CRATES.items() for n in names if not mentions(script(f"lune_{mod}"), n)]
        self.assertEqual(missing, [], "never used in tests/e2e/lune_<module>.luau")


class Wiring(unittest.TestCase):
    def test_require_knows_all_nine_modules_and_roblox_is_unsupported(self):
        libs = read("rust/luau/lune_libs.rs")
        for mod in ALL_MODULES:
            self.assertIn(f'"{mod}"', libs, mod)
        self.assertIn("roblox", libs)
        self.assertIn("not supported", libs)

    def test_run_sh_runs_every_lune_script(self):
        run = read("tests/e2e/run.sh")
        for mod in ["", "_fs", "_serde", "_regex", "_datetime", "_luau", "_task", "_stdio", "_process", "_net"]:
            self.assertIn(f"tests/e2e/lune{mod}.luau", run, f"run.sh does not run tests/e2e/lune{mod}.luau")

    def test_every_lune_script_prints_its_own_pass_line_and_exits(self):
        for f in sorted((ROOT / "tests/e2e").glob("lune*.luau")):
            name = f.stem
            text = f.read_text()
            if name.endswith("_sigint"):
                self.assertIn(f'echo "E2E PASS {name}"', read("tests/e2e/run.sh"), f.name)
                continue
            self.assertIn(f'E2E PASS {name}"', text.replace("'", '"'), f.name)
            if name.endswith("_idle"):
                continue
            self.assertIn("process.exit(0)", text, f"{f.name} must end the process (a server / child would keep it alive)")

    def test_no_forbidden_lune_crates_in_cargo(self):
        cargo = read("Cargo.toml")
        self.assertIsNone(re.search(r"mlua-luau-scheduler|lune-std-(net|task|process|stdio)", cargo))
        self.assertRegex(cargo, r'(?m)^mlua = .*"send"')

    def test_in_tree_modules_are_not_copied_into_the_harness(self):
        for mod in ["task", "stdio", "process", "net"]:
            self.assertFalse((ROOT / f"harness/src/luau/lune_{mod}.rs").exists())

    def test_e2e_scripts_never_use_the_network_beyond_localhost(self):
        for f in (ROOT / "tests/e2e").glob("lune*.luau"):
            for url in re.findall(r"(?:https?|wss?)://[^\s\"')]+", f.read_text()):
                self.assertRegex(url, r"^(?:https?|wss?)://(?:127\.0\.0\.1|localhost)", f"{f.name}: {url}")


if __name__ == "__main__":
    unittest.main()
