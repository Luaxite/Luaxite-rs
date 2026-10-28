"""Process-group kill of the Lune glue (slice 14): on unix every child that exec/create spawns leads its own process
group (unless it inherits the terminal's stdin), and `kill_all` / the exec timeout+cap path / the create handle's kill()
SIGKILL the whole group, so grandchildren of a `shell = true` command do not survive. lune_*.rs is not built by the
harness, so this checks the structure; the kill command line itself is run against a real process group below."""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from _common import read
from test_size_caps import fn_body


def gone(pid):
    """Dead or a zombie (a container without an init reaper leaves reparented zombies behind)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except FileNotFoundError:
        return True
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


class KillGroup(unittest.TestCase):
    def setUp(self):
        self.src = read("rust/luau/lune_process.rs")

    def test_children_lead_their_own_group_on_unix(self):
        body = fn_body(self.src, "fn build_command")
        self.assertIn("#[cfg(unix)]", body)
        self.assertIn("cmd.process_group(0)", body)
        self.assertIn("StdinKind::Inherit", body[body.index("process_group") - 200:body.index("process_group")])

    def test_kill_all_kills_the_group(self):
        cmd = fn_body(self.src, "fn kill_group_cmd")
        self.assertIn("kill -9 -{pid}", cmd)
        self.assertNotIn("--", cmd.split("format!")[1])
        self.assertIn("kill -9 {pid}", cmd)
        self.assertLess(cmd.index("kill -9 -{pid}"), cmd.index("; kill -9 {pid}"))
        self.assertIn("#[cfg(unix)]\nfn kill_group_cmd", self.src)
        all_ = fn_body(self.src, "pub(super) fn kill_all")
        self.assertIn("kill_tree(e.pid)", all_)
        self.assertNotIn('"kill -9 {pid}"', self.src)

    def test_registry_entries_carry_exited_and_group(self):
        entry = fn_body(self.src, "struct Entry")
        for field in ("pid: u32", "exited: bool", "group: bool"):
            self.assertIn(field, entry)
        self.assertIn("static CHILDREN: StdMutex<Vec<Entry>>", self.src)
        self.assertIn("const MAX_TRACKED: usize = 1024;", self.src)

    def test_tracked_new_takes_the_group_flag(self):
        body = fn_body(self.src, "fn new(pid: Option<u32>, group: bool) -> Self")
        self.assertIn("Entry {", body)
        self.assertIn("exited: false", body)
        self.assertRegex(body, r"\bgroup,")

    def test_tracked_drop_keeps_exited_group_entries_only(self):
        body = fn_body(self.src, "fn drop(&mut self)")
        self.assertIn("c.retain_mut(", body)
        self.assertIn("e.exited = true;", body)
        self.assertRegex(body, r"e\.exited = true;\s*e\.group\s*\}\);")
        self.assertIn("e.pid != pid || e.exited", body)

    def test_registry_is_capped_dropping_oldest_exited_first(self):
        body = fn_body(self.src, "fn new(pid: Option<u32>, group: bool) -> Self")
        self.assertIn("c.len() > MAX_TRACKED", body)
        self.assertIn("c.iter().position(|e| e.exited)", body)
        self.assertIn("c.remove(i)", body)
        self.assertLess(body.index("c.push("), body.index("MAX_TRACKED"))

    def test_both_call_sites_pass_the_group_flag(self):
        call = "Tracked::new(child.id(), cfg!(unix) && o.shell.is_some())"
        self.assertEqual(self.src.count("Tracked::new("), 2)
        self.assertEqual(self.src.count(call), 2)

    def test_kill_all_leaves_exited_groups_a_group_only_kill(self):
        body = fn_body(self.src, "pub(super) fn kill_all")
        self.assertIn("if !e.exited {\n            kill_tree(e.pid);", body)
        self.assertRegex(body, r"else if e\.group \{\s*#\[cfg\(unix\)\]\s*kill_leftover_group\(e\.pid\);")
        self.assertEqual(body.count("kill_tree("), 1)
        leftover = fn_body(self.src, "fn kill_leftover_group")
        self.assertIn("kill -9 -{pid}", leftover)
        self.assertNotIn("kill -9 {pid}", leftover)
        self.assertNotIn(";", leftover.split("format!")[1].split(")")[0])
        self.assertIn("#[cfg(unix)]\nfn kill_leftover_group", self.src)

    def test_exec_tracks_the_child_for_every_exit_path(self):
        body = fn_body(self.src, "let exec = lua.create_async_function(")
        spawn = body.index(".spawn()")
        tracked = body.index("let _tracked = Tracked::new(child.id(), cfg!(unix) && o.shell.is_some());")
        self.assertLess(spawn, tracked)
        self.assertLess(tracked, body.index("let run = async"))
        self.assertNotIn("drop(", body)
        self.assertNotIn("mem::forget", body)
        rest = body[tracked:body.index("let res = lua.create_table()")]
        self.assertEqual(rest.count("return "), 1)
        self.assertLess(rest.index("kill_tree(pid)"), rest.index("return Err(e)"))
        self.assertEqual(body.count("Tracked::new("), 1)

    def test_create_tracked_is_dropped_after_the_wait(self):
        i = self.src.index("let tracked = Tracked::new(")
        task = self.src[i:self.src.index("let info = match status", i)]
        self.assertIn("let _tracked = tracked;", task)
        self.assertLess(task.index("let _tracked = tracked;"), task.index("child.wait()"))

    @unittest.skipIf(os.name != "posix" or not shutil.which("sh"), "needs sh")
    def test_leftover_group_kill_takes_a_grandchild_of_an_exited_leader(self):
        """The exact command line kill_leftover_group builds, against a group whose leader already exited."""
        fn = fn_body(self.src, "fn kill_leftover_group")
        line = fn[fn.index('&format!("') + len('&format!("'):fn.index('")])')]
        with tempfile.TemporaryDirectory() as d:
            pidfile = os.path.join(d, "grandchild.pid")
            leader = subprocess.Popen(
                ["sh", "-c", f"sleep 60 >/dev/null 2>&1 & echo $! > {pidfile}"],
                start_new_session=True,
            )
            try:
                leader.wait(timeout=5)
                with open(pidfile) as f:
                    grand = int(f.read())
                self.assertFalse(gone(grand), "grandchild should still run before the kill")
                subprocess.run(["sh", "-c", line.replace("{pid}", str(leader.pid))], check=False)
                time.sleep(0.2)
                self.assertTrue(gone(grand), "grandchild survived the leftover-group kill")
            finally:
                try:
                    os.killpg(leader.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    def test_orphan_e2e_covers_create_and_exec_with_a_background_grandchild(self):
        e2e = read("tests/e2e/lune_process_orphan.luau")
        self.assertIn("process.env.ORPHAN_PID_DIR", e2e)
        self.assertEqual(e2e.count("sleep 100 & echo $!"), 2)
        self.assertRegex(e2e, r"process\.create\(.*\{ shell = true \}\)")
        self.assertRegex(e2e, r"process\.exec\(.*\{ shell = true, stdio = \"none\" \}\)")
        self.assertIn("kill\", { \"-0\"", e2e)
        self.assertIn("process.exit(0)", e2e)
        self.assertIn("kill_all();", fn_body(self.src, 'lua.create_function(|_, code: Option<i32>|'))

    def test_run_sh_checks_both_grandchildren_are_dead_after_luaxite_exits(self):
        run = read("tests/e2e/run.sh")
        self.assertIn("name=lune_process_orphan", run)
        body = run[run.index("orphan_test() {"):]
        self.assertIn("ORPHAN_PID_DIR=$dir; export ORPHAN_PID_DIR", body)
        self.assertIn("run $name 30 tests/e2e/$name.luau", body)
        self.assertIn("for kind in create exec; do", body)
        self.assertIn('while alive "$spid"; do', body)
        self.assertIn("still running after luaxite exited", body)
        self.assertIn("MINGW*", body[body.index("orphan_test ;;") - 200:])
        self.assertGreater(body.index("orphan_test ;;"), body.index("orphan_test() {"))

    def test_windows_branch_kept(self):
        tree = fn_body(self.src, "fn kill_tree")
        self.assertIn("#[cfg(windows)]", tree)
        self.assertIn('"/F", "/T", "/PID"', tree)

    def test_exec_error_path_kills_the_group(self):
        i = self.src.index("let (status, stdout, stderr) = match outcome")
        err = self.src[i:self.src.index("let res = lua.create_table()", i)]
        self.assertLess(err.index("kill_tree(pid)"), err.index("child.kill().await"))

    def test_create_kill_handle_kills_the_group(self):
        i = self.src.index("kill_wait.notified()")
        arm = self.src[i:i + 300]
        self.assertLess(arm.index("kill_tree(pid)"), arm.index("child.kill().await"))

    @unittest.skipIf(os.name != "posix" or not shutil.which("sh"), "needs sh")
    def test_kill_command_line_takes_grandchildren(self):
        """Run the exact command line kill_group_cmd builds against a real group leader with a grandchild."""
        fmt = fn_body(self.src, "fn kill_group_cmd")
        line = fmt[fmt.index('format!("') + len('format!("'):fmt.index('")')]
        with tempfile.TemporaryDirectory() as d:
            pidfile = os.path.join(d, "grandchild.pid")
            leader = subprocess.Popen(
                ["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"],
                start_new_session=True,
            )
            try:
                for _ in range(100):
                    if os.path.exists(pidfile) and os.path.getsize(pidfile) > 1:
                        break
                    time.sleep(0.05)
                with open(pidfile) as f:
                    grand = int(f.read())
                subprocess.run(["sh", "-c", line.replace("{pid}", str(leader.pid))], check=False)
                leader.wait(timeout=5)
                time.sleep(0.2)
                self.assertTrue(gone(grand), "grandchild survived the group kill")
            finally:
                try:
                    os.killpg(leader.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                leader.wait()


if __name__ == "__main__":
    unittest.main()
