--!nocheck
-- Run by tests/e2e/run.sh as: luaxite path tests/e2e/lune_process_args.luau debug=true debug true --verbose -x
-- `path` and the script are not arguments; everything else reaches process.args unchanged, in order.
local process = require("@lune/process")

local want = { "debug=true", "debug", "true", "--verbose", "-x" }

assert(type(process.args) == "table", "args is a table")
assert(#process.args == #want, "args: expected " .. #want .. " entries, got " .. #process.args .. " (" .. table.concat(process.args, ", ") .. ")")
for i, v in want do
	assert(process.args[i] == v, "args[" .. i .. "] expected " .. v .. ", got " .. tostring(process.args[i]))
end
assert(not table.find(process.args, "path"), "the `path` keyword is not an argument")
assert(not table.isfrozen(process.args), "args is a plain (writable) table")

print("E2E PASS lune_process_args")
process.exit(0)
