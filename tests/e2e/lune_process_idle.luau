-- A child made with process.create must not keep the program alive after the script has finished.
-- run.sh gives this script 30s: the `sleep 30` child below is killed when the script ends, so it finishes at once.
local process = require("@lune/process")

if process.os ~= "windows" then
	local child = process.create("sleep", { "30" })
	assert(child ~= nil, "create returns a child handle")
end

-- No process.exit here on purpose: the program ends by itself.
print("E2E PASS lune_process_idle")
