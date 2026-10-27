--!nocheck
-- e2e: @lune/process basics (os / arch / endianness / args / cwd / env / exit / exec / create). Needs no server. Prints "E2E PASS lune_process" when every check holds.
local process = require("@lune/process")

assert(not pcall(function()
	process.nope = 1
end), "the module table is readonly")

assert(type(process.os) == "string" and process.os == string.lower(process.os) and #process.os > 0, "os: " .. tostring(process.os))
assert(type(process.arch) == "string" and process.arch == string.lower(process.arch) and #process.arch > 0, "arch: " .. tostring(process.arch))
assert(process.endianness == "little" or process.endianness == "big", "endianness: " .. tostring(process.endianness))

assert(type(process.args) == "table" and #process.args == 0, "args is an empty plain table")
assert(not table.isfrozen(process.args), "args is a plain (writable) table")

local sep = string.sub(process.cwd, -1)
assert(type(process.cwd) == "string" and (sep == "/" or sep == "\\"), "cwd ends with a path separator: " .. tostring(process.cwd))

assert(type(process.env) == "table", "env is a table")
local seen = 0
for k, v in process.env do
	assert(type(k) == "string" and type(v) == "string", "env holds strings")
	seen += 1
end
assert(seen > 0, "env is not empty")
if process.os ~= "windows" then
	assert(type(process.env.PATH) == "string", "env.PATH on unix")
end

assert(type(process.exit) == "function", "exit is a function")

assert(type(process.exec) == "function", "exec is a function")
-- exec: errors raised before / while starting (they are caught here)
local ok, err = pcall(process.exec, "sh", {}, { stdio = "e2e-expected-nope" })
assert(not ok and string.find(tostring(err), "forward", 1, true), "bad stdio kind lists the valid ones: " .. tostring(err))
ok, err = pcall(process.exec, "e2e-expected-no-such-program-xyz")
assert(not ok and string.find(tostring(err), "e2e-expected-no-such-program-xyz", 1, true), "a missing program raises: " .. tostring(err))

if process.os ~= "windows" then
	local r = process.exec("sh", { "-c", "echo hi" })
	assert(r.ok == true and r.code == 0 and r.stdout == "hi\n" and r.stderr == "", "echo: " .. r.stdout)

	r = process.exec("sh", { "-c", "echo oops >&2; exit 3" })
	assert(r.ok == false and r.code == 3 and r.stderr == "oops\n" and r.stdout == "", "exit code 3")

	r = process.exec("cat", nil, { stdio = { stdin = "round trip" } })
	assert(r.ok and r.stdout == "round trip", "stdin string is written then closed: " .. r.stdout)

	r = process.exec("pwd", {}, { cwd = "/" })
	assert(r.stdout == "/\n", "cwd option: " .. r.stdout)

	r = process.exec("sh", { "-c", "echo $E2E_X" }, { env = { E2E_X = "yes" } })
	assert(r.stdout == "yes\n", "env option is merged over the environment: " .. r.stdout)
	r = process.exec("sh", { "-c", "test -n \"$PATH\"" }, { env = { E2E_X = "1" } })
	assert(r.ok, "the current environment is kept")

	r = process.exec("echo", { "hi", "there" }, { shell = true })
	assert(r.ok and r.stdout == "hi there\n", "shell = true: " .. r.stdout)
	r = process.exec("echo shell-name", nil, { shell = "sh" })
	assert(r.ok and r.stdout == "shell-name\n", "shell = name: " .. r.stdout)

	r = process.exec("sh", { "-c", "echo gone; echo gone2 >&2" }, { stdio = "none" })
	assert(r.ok and r.stdout == "" and r.stderr == "", "stdio none captures nothing")
	r = process.exec("sh", { "-c", "echo fwd" }, { stdio = "forward" })
	assert(r.stdout == "fwd\n", "stdio forward still captures")
	r = process.exec("sh", { "-c", "echo only-err >&2" }, { stdio = { stderr = "none" } })
	assert(r.stderr == "", "per-stream kind")
end

-- create: spawns at once, status() yields until the child exits, kill() ends a long-running child
assert(type(process.create) == "function", "create is a function")
ok, err = pcall(process.create, "e2e-expected-no-such-program-xyz")
assert(not ok, "create of a missing program raises: " .. tostring(err))
if process.os ~= "windows" then
	local quick = process.create("sh", { "-c", "exit 4" })
	local qs = quick.status()
	assert(qs.ok == false and qs.code == 4, "status of a finished child: code " .. tostring(qs.code))
	local fine = process.create("true").status()
	assert(fine.ok == true and fine.code == 0, "status ok for exit 0")

	local child = process.create("sleep", { "30" })
	assert(type(child.stdin) == "userdata" and type(child.stdout) == "userdata" and type(child.stderr) == "userdata", "stream fields")
	child.kill()
	local st = child.status()
	assert(st.ok == false and st.code == 9, "killed child: ok false, code 9, got " .. tostring(st.code))
	child.kill() -- killing a dead child is a no-op
	assert(child.status().ok == false, "status can be asked again")

	-- streams: a `cat` round trip (write, close = EOF, read everything back)
	local cat = process.create("cat")
	cat.stdin:write("ping ")
	cat.stdin:write("pong")
	cat.stdin:close()
	cat.stdin:close() -- closing twice is fine
	assert(not pcall(cat.stdin.write, cat.stdin, "late"), "write after close raises")
	assert(cat.stdout:readToEnd() == "ping pong", "cat echoes its stdin")
	assert(cat.stdout:readToEnd() == "" and cat.stdout:read() == nil, "readToEnd is empty and read is nil at EOF")
	local cs = cat.status()
	assert(cs.ok and cs.code == 0, "cat exits 0 after EOF")

	-- read(size) chunks, then nil at EOF
	local chunky = process.create("sh", { "-c", "printf abcde" })
	local got = ""
	local first = chunky.stdout:read(2)
	assert(first ~= nil and #first >= 1 and #first <= 2, "read(2) returns at most 2 bytes")
	got = first
	while true do
		local part = chunky.stdout:read(2)
		if part == nil then
			break
		end
		assert(#part <= 2, "chunk size")
		got ..= part
	end
	assert(got == "abcde", "chunks join up: " .. got)

	-- stderr is its own stream
	local errp = process.create("sh", { "-c", "echo err >&2; echo out" })
	assert(errp.stderr:readToEnd() == "err\n" and errp.stdout:readToEnd() == "out\n", "stdout and stderr are separate")
	assert(errp.status().ok, "status after reading")
end

-- a huge read size must not abort the process (the buffer is capped; a read returns what is there)
do
	local big = process.create("sh", { "-c", "printf short" })
	local got = ""
	while true do
		local part = big.stdout:read(1e12)
		if part == nil then
			break
		end
		got ..= part
	end
	assert(got == "short", "read(1e12) on a short stream: " .. got)
end

-- options.timeout: exec has a default limit (600 s) that `timeout = 0` removes; a given value is used, a bad one raises; create takes none
if process.os ~= "windows" then
	local r0 = process.exec("sh", { "-c", "echo t0" }, { timeout = 0 })
	assert(r0.ok == true and r0.stdout == "t0\n", "exec with timeout = 0 runs without a limit: " .. r0.stdout)
	r0 = process.exec("sh", { "-c", "echo t5" }, { timeout = 5 })
	assert(r0.ok == true and r0.stdout == "t5\n", "exec with timeout = 5: " .. r0.stdout)
	r0 = process.exec("sh", { "-c", "echo tdef" }, { cwd = "/" })
	assert(r0.ok == true and r0.stdout == "tdef\n", "exec with options but no timeout still runs (default limit): " .. r0.stdout)
	local okT, errT = pcall(process.exec, "sh", { "-c", "exit 0" }, { timeout = -1 })
	assert(not okT and string.find(tostring(errT), "options.timeout must be a positive number of seconds", 1, true), "negative timeout raises: " .. tostring(errT))
	okT, errT = pcall(process.exec, "sleep", { "30" }, { timeout = 0.3 })
	assert(not okT and string.find(tostring(errT), "process.exec: timed out", 1, true), "a short timeout still kills the child: " .. tostring(errT))
	for _, t in { 0, 5 } do
		okT, errT = pcall(process.create, "sh", { "-c", "exit 0" }, { timeout = t })
		assert(not okT and string.find(tostring(errT), "only supported by process.exec", 1, true), "create rejects timeout = " .. t .. ": " .. tostring(errT))
	end
end

print("E2E PASS lune_process")
process.exit(0)
