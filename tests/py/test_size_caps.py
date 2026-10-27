"""Size caps of the Lune glue (slice 12): readToEnd (process.create stream, stdio), process.exec output and HTTP response
bodies stop at lune_libs::MAX_BYTES (64 MiB) with a Lua error instead of growing without bound. The lune_*.rs files are not
built by the harness, so this checks their structure; the Rust unit tests in lune_libs.rs cover read_capped_to."""
import re
import unittest

from _common import read


def fn_body(src, marker):
    """Text from `marker` to the end of the brace-balanced block that follows it."""
    i = src.index(marker)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(f"unbalanced block after {marker!r}")


class SizeCaps(unittest.TestCase):
    def setUp(self):
        self.libs = read("rust/luau/lune_libs.rs")
        self.process = read("rust/luau/lune_process.rs")
        self.stdio = read("rust/luau/lune_stdio.rs")
        self.net = read("rust/luau/lune_net.rs")

    def test_shared_constant(self):
        self.assertRegex(self.libs, r"pub const MAX_BYTES: usize = 64 \* 1024 \* 1024;")
        self.assertIn("pub fn too_big(what: &str) -> mlua::Error", self.libs)
        self.assertIn("exceeds {} MiB", self.libs)  # "<what> exceeds 64 MiB"
        self.assertIn("pub async fn read_capped<", self.libs)

    def test_read_capped_reads_one_byte_past_the_cap(self):
        body = fn_body(self.libs, "pub async fn read_capped_to")
        self.assertIn("take(max as u64 + 1)", body)
        self.assertIn("buf.len() <= max", body)

    def test_rust_unit_tests_present(self):
        self.assertIn("#[cfg(test)]", self.libs)
        self.assertIn("fn read_capped_to_stops_one_byte_past_the_cap", self.libs)
        self.assertIn("fn too_big_names_the_limit", self.libs)

    def test_process_create_read_to_end(self):
        body = fn_body(self.process, '"readToEnd", |lua, this, ()|')
        self.assertIn("read_capped(r)", body)
        self.assertIn('too_big("process.create: readToEnd")', body)
        self.assertNotIn("read_to_end", body)

    def test_process_exec_output(self):
        body = fn_body(self.process, "async fn read_all<")
        self.assertIn("all.len() + n > MAX_BYTES", body)
        self.assertIn('"process.exec: stdout"', body)
        self.assertIn('"process.exec: stderr"', body)
        self.assertIn("mlua::Result<Vec<u8>>", self.process)
        # the first stream over the cap ends the exec, and the child is killed (it could block on a pipe nobody reads)
        self.assertIn("tokio::try_join!(", self.process)
        self.assertNotIn("tokio::join!(", self.process)
        self.assertRegex(self.process, r"Err\(e\) => \{\s*(?:if let Some\(pid\) = child\.id\(\) \{\s*kill_tree\(pid\);\s*\}\s*)?let _ = child\.kill\(\)\.await;\s*return Err\(e\);")

    def test_stdio_read_to_end(self):
        body = fn_body(self.stdio, "let read_to_end = ")
        self.assertIn("read_capped(", body)
        self.assertIn('too_big("stdio.readToEnd")', body)
        self.assertNotIn("read_to_end(&mut", body)

    def test_http_response_body(self):
        body = fn_body(self.net, "let mut resp = req")
        self.assertNotRegex(self.net, r"resp\s*\.bytes\(\)")
        self.assertIn("resp.content_length()", self.net)
        self.assertRegex(self.net, r"resp\s*\.chunk\(\)")
        self.assertIn("body.len() + chunk.len() > MAX_BYTES", self.net)
        self.assertIn('too_big("net.request: response body")', self.net)
        self.assertTrue(body)

    def test_imports(self):
        for name, src, names in (
            ("process", self.process, ("MAX_BYTES", "read_capped", "too_big")),
            ("stdio", self.stdio, ("read_capped", "too_big")),
            ("net", self.net, ("MAX_BYTES", "too_big")),
        ):
            m = re.search(r"use super::lune_libs::\{([^}]*)\};", src)
            self.assertIsNotNone(m, name)
            for n in names:
                self.assertIn(n, m.group(1), f"{name}: {n}")
        # stdio no longer reads to end by hand: AsyncReadExt would be an unused import
        self.assertNotIn("AsyncReadExt", self.stdio)


if __name__ == "__main__":
    unittest.main()
