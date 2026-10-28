local process = require("@lune/process")

if process.os ~= "windows" then
	local child = process.create("sleep", { "30" })
	assert(child ~= nil, "create returns a child handle")
end

print("E2E PASS lune_process_idle")
