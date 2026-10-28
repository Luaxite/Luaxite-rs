--!nocheck
local process = require("@lune/process")

if process.os ~= "windows" then
	local dir = process.env.ORPHAN_PID_DIR
	assert(type(dir) == "string" and #dir > 0, "ORPHAN_PID_DIR is set by tests/e2e/run.sh")

	local created = process.create(string.format('sleep 100 & echo $! > "%s/create.pid"', dir), nil, { shell = true })
	assert(created.status().ok, "the create shell exits by itself")
	local execd = process.exec(string.format('sleep 100 & echo $! > "%s/exec.pid"', dir), nil, { shell = true, stdio = "none" })
	assert(execd.ok, "the exec shell exits by itself")

	for _, case in { "create", "exec" } do
		local pid = process.exec("cat", { string.format("%s/%s.pid", dir, case) }).stdout:gsub("%s", "")
		assert(#pid > 0, case .. ": the shell wrote the sleep's pid")
		assert(process.exec("kill", { "-0", pid }, { stdio = "none" }).ok, case .. ": the sleep outlives its shell")
	end
end

print("E2E PASS lune_process_orphan")
process.exit(0)
