"""Request-body cap and timeouts of the Lune glue (slice 13): net.serve replies 413 to a request body over
lune_libs::MAX_BYTES (and keeps serving), net.request has a 30 s connect timeout and `options.timeout` (default 120 s, 0 = none),
process.exec `options.timeout` (default 600 s, 0 = none) that kills the child. The lune_*.rs files are not built by the harness, so
this checks their structure; the Rust unit tests in lune_libs.rs cover timeout_from_secs."""
import re
import unittest

from _common import read
from test_size_caps import fn_body


class Timeouts(unittest.TestCase):
    def setUp(self):
        self.libs = read("rust/luau/lune_libs.rs")
        self.process = read("rust/luau/lune_process.rs")
        self.net = read("rust/luau/lune_net.rs")


    def test_timeout_helper(self):
        body = fn_body(self.libs, "pub fn timeout_from_secs")
        self.assertIn("secs.is_nan() || secs <= 0.0", body)
        self.assertIn("options.timeout must be a positive number of seconds", body)
        self.assertIn("secs.min(MAX_TIMEOUT_SECS)", body)
        self.assertIn("Duration::try_from_secs_f64", body)
        self.assertNotIn("Duration::from_secs_f64", self.libs)

    def test_rust_unit_test_present(self):
        self.assertIn("fn timeout_from_secs_validates", self.libs)

    def test_imports(self):
        for name, src in (("net", self.net), ("process", self.process)):
            m = re.search(r"use super::lune_libs::\{([^}]*)\};", src)
            self.assertIsNotNone(m, name)
            self.assertIn("timeout_with_default", m.group(1), name)
            self.assertNotIn("timeout_from_secs", src, name)
        self.assertIn("DEFAULT_REQUEST_TIMEOUT_SECS", re.search(r"use super::lune_libs::\{([^}]*)\};", self.net).group(1))
        self.assertIn("DEFAULT_EXEC_TIMEOUT_SECS", re.search(r"use super::lune_libs::\{([^}]*)\};", self.process).group(1))


    def test_serve_body_is_capped(self):
        body = fn_body(self.net, "async fn handle(")
        self.assertIn("Limited::new(body, MAX_BYTES).collect().await", body)
        self.assertNotIn("body.collect().await", body)
        self.assertIn("LengthLimitError", body)
        self.assertIn("payload_too_large()", body)
        self.assertIn("CONTENT_LENGTH", body)
        self.assertIn("n > MAX_BYTES as u64", body)
        m = re.search(r"use http_body_util::\{([^}]*)\};", self.net)
        self.assertIsNotNone(m)
        for n in ("Limited", "LengthLimitError"):
            self.assertIn(n, m.group(1))

    def test_serve_over_cap_is_a_413_not_a_script_error(self):
        reply = fn_body(self.net, "fn payload_too_large")
        self.assertIn("PAYLOAD_TOO_LARGE", reply)
        self.assertIn("CONNECTION", reply)
        body = fn_body(self.net, "async fn handle(")
        branch = body[body.index("Limited::new"):body.index("let data = ServeRequest")]
        self.assertNotIn("eprintln!", branch)
        self.assertNotIn("note_error", branch)
        self.assertNotIn("note_error", self.net)


    def test_connect_timeout(self):
        self.assertRegex(self.net, r"const CONNECT_TIMEOUT: Duration = Duration::from_secs\(30\);")
        body = fn_body(self.net, "fn build_client")
        self.assertIn(".connect_timeout(CONNECT_TIMEOUT)", body)

    def test_request_timeout_option(self):
        helper = fn_body(self.net, "fn request_timeout")
        self.assertIn('timeout_with_default("net.request", secs, DEFAULT_REQUEST_TIMEOUT_SECS)', helper)
        body = fn_body(self.net, "fn parse_request")
        self.assertIn('request_timeout(o.get::<Option<f64>>("timeout")?)', body)
        self.assertIn("None => (true, request_timeout(None)?),", body)
        self.assertRegex(body, r"decompress: true,\s*timeout: request_timeout\(None\)\?,")
        self.assertNotIn("timeout: None", body)
        self.assertIn("timeout: Option<Duration>", fn_body(self.net, "struct ReqSpec"))

    def test_request_timeout_applied_and_reported(self):
        body = fn_body(self.net, "async fn send_request")
        self.assertIn("req.timeout(timeout)", body)
        self.assertEqual(body.count(".map_err(req_err)"), 2)
        err = fn_body(self.net, "fn req_err")
        self.assertIn("e.is_timeout()", err)
        self.assertIn('"net.request: timed out"', err)

    def test_default_has_no_overall_timeout(self):
        body = fn_body(self.net, "async fn send_request")
        self.assertEqual(body.count(".timeout("), 1)
        self.assertIn("if let Some(timeout) = spec.timeout", body)


    def test_exec_timeout_parsed_only_for_exec(self):
        body = fn_body(self.process, "fn parse_opts")
        self.assertIn('timeout_with_default("process.exec", raw_timeout, DEFAULT_EXEC_TIMEOUT_SECS)', body)
        self.assertRegex(body, r'if func == "exec" \{[^}]*timeout_with_default[^}]*\} else if raw_timeout\.is_some\(\) \{\s*return Err')
        self.assertIn("options.timeout is only supported by process.exec", body)
        self.assertLess(body.index("timeout_with_default"), body.index("let Some(t) = options else"))
        self.assertNotIn("timeout_from_secs", body)
        self.assertIn("timeout: Option<Duration>", fn_body(self.process, "struct Opts"))

    def test_exec_timeout_covers_output_and_exit(self):
        body = fn_body(self.process, "let exec = ")
        run = body[body.index("let run = async"):body.index("let outcome")]
        self.assertIn("try_join!(", run)
        self.assertRegex(run, r"child\s*\.wait\(\)")
        self.assertIn("tokio::time::timeout(limit, run)", body)
        self.assertIn("process.exec: timed out after {}s", body)

    def test_exec_kills_the_child_on_timeout(self):
        body = fn_body(self.process, "let exec = ")
        self.assertRegex(body, r"Err\(e\) => \{\s*(?:if let Some\(pid\) = child\.id\(\) \{\s*kill_tree\(pid\);\s*\}\s*)?let _ = child\.kill\(\)\.await;\s*return Err\(e\);")
        outcome = body[body.index("let outcome"):body.index("let (status, stdout, stderr)")]
        self.assertIn("Err(mlua::Error::runtime(", outcome)
        self.assertNotIn("return", outcome)

    def test_exec_with_timeout_zero_waits_forever(self):
        body = fn_body(self.process, "let exec = ")
        self.assertIn("None => run.await,", body)


    def test_default_constants_and_helper_shape(self):
        self.assertRegex(self.libs, r"pub const DEFAULT_EXEC_TIMEOUT_SECS: f64 = 600\.0;")
        self.assertRegex(self.libs, r"pub const DEFAULT_REQUEST_TIMEOUT_SECS: f64 = 120\.0;")
        body = fn_body(self.libs, "pub fn timeout_with_default")
        self.assertIn("default: f64", body)
        self.assertIn("None => timeout_from_secs(func, Some(default))", body)
        self.assertIn("Some(secs) if secs == 0.0 => Ok(None)", body)
        self.assertIn("Some(secs) => timeout_from_secs(func, Some(secs))", body)
        self.assertIn("fn timeout_with_default_applies_the_default_and_zero_disables", self.libs)
        self.assertIn("fn default_timeouts_are_the_documented_values", self.libs)

    def test_exec_and_request_defaults_come_from_the_constants(self):
        self.assertIn("DEFAULT_EXEC_TIMEOUT_SECS)", fn_body(self.process, "fn parse_opts"))
        self.assertIn("DEFAULT_REQUEST_TIMEOUT_SECS)", fn_body(self.net, "fn request_timeout"))

    def test_timeout_is_documented_with_default_and_zero(self):
        for name, secs in (("net", "120"), ("process", "600")):
            stub = read(f"tools/lune-stubs/{name}.luau")
            self.assertIn(f"Absent = {secs} (default limit); 0 = no limit.", stub, name)
            self.assertIn("Negative or NaN raises", stub, name)
            self.assertNotIn("Absent = no limit", stub, name)
        self.assertIn("rejects options.timeout (0 included)", read("tools/lune-stubs/process.luau"))

    def test_e2e_covers_timeout_zero_default_and_create(self):
        proc = read("tests/e2e/lune_process.luau")
        self.assertIn('{ timeout = 0 })', proc)
        self.assertIn("only supported by process.exec", proc)
        self.assertIn("{ 0, 5 }", proc)
        self.assertIn("process.exec: timed out", proc)
        self.assertIn("options.timeout must be a positive number of seconds", proc)
        net = read("tests/e2e/lune_net.luau")
        self.assertIn("options = { timeout = 0 }", net)
        self.assertIn("net.request: timed out", net)
        self.assertIn("options.timeout must be a positive number of seconds", net)
        self.assertLess(proc.index("timeout = 0"), proc.index('print("E2E PASS lune_process")'))
        self.assertLess(net.index("timeout = 0"), net.index('print("E2E PASS lune_net")'))


if __name__ == "__main__":
    unittest.main()
