--!nocheck
-- test project: `require` of an embedded module from code that cannot yield. A string.gsub callback is such a place (a C call boundary), and the
-- first load of an embedded module used to run its chunk with call_async, which fails there with a yield error. Needs no server and starts no bot.
-- This is the entry script (src/main.luau) of the test project tests/projects/require_gsub, built as its own binary (tests/projects/run.sh), so it
-- runs with no arguments and its module is the project's own src/probe.luau. Its top level only calls `azalea.join` (exactly once) and `bot:on`
-- (as many times as it registers handlers; this test must not hard-code that number), and `azalea.join` is replaced by a stub below, so loading
-- it joins no server.
local process = require("@lune/process")
local join = azalea.join
local joins, handlers = 0, 0
local stub = {
	on = function(_self, _event, _handler)
		handlers += 1
	end,
}
azalea.join = function(_opts)
	joins += 1
	return stub
end

local first
local callback_yieldable
local ok, err = pcall(string.gsub, "x", "x", function()
	callback_yieldable = coroutine.isyieldable()
	first = require("probe") -- first load of the embedded module, inside a non-yieldable callback
	return "y"
end)
assert(ok, "require of an embedded module inside a string.gsub callback failed: " .. tostring(err))
assert(callback_yieldable == false, "a string.gsub callback is expected to be non-yieldable (the premise of this test)")
assert(first == true, "probe.luau returns nothing, so require gives true, got " .. tostring(first))
-- the top level ran exactly once: one azalea.join call (probe.luau makes exactly one), and it registered at least one handler
assert(joins == 1, "probe.luau must have run its top level once (1 azalea.join call), got " .. joins)
assert(handlers > 0, "probe.luau registers handlers with bot:on, got none")
local loaded_handlers = handlers

-- the module is cached now: the same non-yieldable place and a plain require both get the cached value and do not run it again
local second
ok, err = pcall(string.gsub, "x", "x", function()
	second = require("probe")
	return "y"
end)
assert(ok, "cached require inside a string.gsub callback failed: " .. tostring(err))
assert(second == true and require("probe") == true, "cached require changed the value")
assert(joins == 1 and handlers == loaded_handlers, "the cached module ran its top level again")

azalea.join = join

print("E2E PASS require_gsub")
process.exit(0)
