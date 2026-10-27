--!nocheck
-- e2e: Ctrl-C. A create() child lives in its own process group, so the terminal's SIGINT never reaches it: luaxite must catch
-- SIGINT, kill the child and exit 130. tests/e2e/run.sh runs this under `timeout -s INT` and checks the exit code and that the child
-- (it writes its pid to $SIGINT_PID_FILE) is gone. This script never ends by itself, so it prints no PASS line: run.sh prints
-- "E2E PASS lune_process_sigint" when those checks hold. Unix only.
local process = require("@lune/process")
local task = require("@lune/task")

local pidfile = process.env.SIGINT_PID_FILE
assert(type(pidfile) == "string" and #pidfile > 0, "SIGINT_PID_FILE is set by tests/e2e/run.sh")

process.create("sh", { "-c", string.format('echo $$ > "%s"; exec sleep 100', pidfile) })

while true do
	task.wait(0.1)
end
