--!nocheck
local process = require("@lune/process")
local task = require("@lune/task")

local pidfile = process.env.SIGINT_PID_FILE
assert(type(pidfile) == "string" and #pidfile > 0, "SIGINT_PID_FILE is set by tests/e2e/run.sh")

process.create("sh", { "-c", string.format('echo $$ > "%s"; exec sleep 100', pidfile) })

while true do
	task.wait(0.1)
end
