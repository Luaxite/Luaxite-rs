--!nocheck
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
	first = require("probe")
	return "y"
end)
assert(ok, "require of an embedded module inside a string.gsub callback failed: " .. tostring(err))
assert(callback_yieldable == false, "a string.gsub callback is expected to be non-yieldable (the premise of this test)")
assert(first == true, "probe.luau returns nothing, so require gives true, got " .. tostring(first))
assert(joins == 1, "probe.luau must have run its top level once (1 azalea.join call), got " .. joins)
assert(handlers > 0, "probe.luau registers handlers with bot:on, got none")
local loaded_handlers = handlers

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
