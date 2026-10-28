"""Ctrl-C / SIGTERM (slices 1-2): children run in their own process group (`process_group(0)`), so the terminal's SIGINT never
reaches them. rust/main.rs catches SIGINT and SIGTERM, kills the tracked children (`luau::Runtime::kill_children`) and exits 130 /
143. The binary is not built by the harness, so this checks the structure; tests/e2e/lune_process_sigint.luau + run.sh run the
real thing (SIGINT to a running luaxite with a live create() child)."""
import re
import unittest

from _common import read
from test_size_caps import fn_body


class SignalHandler(unittest.TestCase):
    def setUp(self):
        self.main = read("rust/main.rs")
        self.handler = fn_body(self.main, "fn install_signal_handler")

    def test_tokio_signal_feature_is_enabled(self):
        line = re.search(r"(?m)^tokio = \{.*\}", read("Cargo.toml"))
        self.assertIsNotNone(line, "no `tokio = {...}` dependency line")
        self.assertIn('"signal"', line.group(0))

    def test_sigint_and_sigterm_are_handled_on_unix(self):
        unix = self.handler[self.handler.index("#[cfg(unix)]"):self.handler.index("#[cfg(not(unix))]")]
        self.assertIn("SignalKind::interrupt()", unix)
        self.assertIn("SignalKind::terminate()", unix)
        self.assertRegex(unix, r"int\.recv\(\) => 130")
        self.assertRegex(unix, r"term\.recv\(\) => 143")

    def test_windows_ctrl_c_is_handled(self):
        win = self.handler[self.handler.index("#[cfg(not(unix))]"):]
        self.assertIn("tokio::signal::ctrl_c()", win)
        self.assertIn("exit(130)", win)

    def test_children_are_killed_before_every_exit(self):
        self.assertEqual(self.handler.count("luau::Runtime::kill_children()"), 2)
        self.assertEqual(len(re.findall(r"kill_children\(\);\s*std::process::exit\(", self.handler)), 2)

    def test_listeners_are_registered_before_the_task_is_spawned(self):

        unix = self.handler[self.handler.index("#[cfg(unix)]"):self.handler.index("#[cfg(not(unix))]")]
        self.assertLess(unix.index("signal(SignalKind::terminate())"), unix.index("tokio::spawn"))
        self.assertNotIn("spawn_local", self.handler)

    def test_main_installs_the_handler_before_running_scripts(self):
        body = fn_body(self.main, "async fn main")
        self.assertIn("install_signal_handler()?", body)
        self.assertLess(body.index("install_signal_handler()"), body.index("Runtime::new"))
        self.assertLess(body.index("parse_args()"), body.index("install_signal_handler()"))

    def test_kill_children_kills_the_tracked_processes(self):
        body = fn_body(read("rust/luau/mod.rs"), "pub fn kill_children")
        self.assertIn('#[cfg(feature = "lune")]', body)
        self.assertIn("lune_process::kill_all()", body)


class SigintE2e(unittest.TestCase):
    def test_script_makes_a_child_and_waits(self):
        s = read("tests/e2e/lune_process_sigint.luau")
        self.assertIn('process.env.SIGINT_PID_FILE', s)
        self.assertIn("process.create(", s)
        self.assertIn("exec sleep 100", s)
        self.assertIn("while true do", s)

    def test_run_sh_sends_sigint_and_checks_exit_code_and_child(self):
        run = read("tests/e2e/run.sh")
        self.assertRegex(run, r"timeout --preserve-status -k \d+ -s INT \d+ ")
        self.assertIn("tests/e2e/$name.luau", run[run.index("sigint_test()"):])
        self.assertIn("name=lune_process_sigint", run)
        self.assertIn('-eq 130', run)
        self.assertIn('alive "$cpid"', run)
        self.assertIn('echo "E2E PASS lune_process_sigint"', run)
        self.assertIn("MINGW*", run)


if __name__ == "__main__":
    unittest.main()
