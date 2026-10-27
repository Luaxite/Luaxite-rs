--!nocheck
-- e2e: grandchildren of an exited child. A `shell = true` command can exit on its own while a background grandchild (`sleep 100 &`)
-- keeps running in the child's process group. luaxite must still kill that group when it exits (process.exit -> kill_all), for
-- process.create and for process.exec. Each shell writes the sleep's pid to $ORPHAN_PID_DIR/<case>.pid; tests/e2e/run.sh checks that
-- both sleeps are gone once luaxite has exited. Unix only.
local process = require("@lune/process")

if process.os ~= "windows" then
	local dir = process.env.ORPHAN_PID_DIR
	assert(type(dir) == "string" and #dir > 0, "ORPHAN_PID_DIR is set by tests/e2e/run.sh")

	local created = process.create(string.format('sleep 100 & echo $! > "%s/create.pid"', dir), nil, { shell = true })
	assert(created.status().ok, "the create shell exits by itself")
	-- exec must not pipe stdout / stderr (stdio none): the sleep would hold the pipe open and exec would wait for it
	local execd = process.exec(string.format('sleep 100 & echo $! > "%s/exec.pid"', dir), nil, { shell = true, stdio = "none" })
	assert(execd.ok, "the exec shell exits by itself")

	-- both sleeps outlive their shell now (otherwise run.sh would prove nothing)
	for _, case in { "create", "exec" } do
		local pid = process.exec("cat", { string.format("%s/%s.pid", dir, case) }).stdout:gsub("%s", "")
		assert(#pid > 0, case .. ": the shell wrote the sleep's pid")
		assert(process.exec("kill", { "-0", pid }, { stdio = "none" }).ok, case .. ": the sleep outlives its shell")
	end
end

print("E2E PASS lune_process_orphan")
process.exit(0)
