-- e2e: the API that exists before any bot does (the `azalea` and `goal` globals, process, every Lune module). Needs no server and starts no
-- bot, so it runs on every OS the binary is built for (.github/workflows/compile.yml). Prints "E2E PASS offline_api".
local function expect(cond: any, msg: string)
	if not cond then
		error("E2E FAIL: " .. msg, 2)
	end
end

for _, name in { "join", "swarm", "wait" } do
	expect(type(azalea[name]) == "function", "azalea." .. name .. " is not a function")
end
for _, name in { "xz", "y", "radius", "inverse", "block", "all", "any" } do
	expect(type(goal[name]) == "function", "goal." .. name .. " is not a function")
end
expect(type(process.exit) == "function", "process.exit")

-- goals are plain values: they can be built and combined without a bot
local here = { x = 0, y = 64, z = 0 }
local near = goal.radius(here, 5)
expect(near ~= nil, "goal.radius")
expect(goal.xz(10, 20) ~= nil, "goal.xz")
expect(goal.y(64) ~= nil, "goal.y")
expect(goal.block(here) ~= nil, "goal.block")
expect(goal.all(goal.inverse(near), goal.y(64)) ~= nil, "goal.all(goal.inverse(..), ..)")
expect(goal.any(goal.xz(1, 2), goal.xz(3, 4)) ~= nil, "goal.any")

-- a wrong argument is a Lua error, not a crash
local ok = pcall(goal.xz, "not a number" :: any, 1)
expect(not ok, "goal.xz accepted a string")

-- azalea.wait returns at once when no bot exists (it runs on the async runtime, so this proves the runtime works on this OS)
azalea.wait()

for _, name in { "fs", "serde", "regex", "datetime", "luau", "net", "process", "stdio", "task" } do
	local loaded, err = pcall(require, "@lune/" .. name)
	expect(loaded, "require(@lune/" .. name .. "): " .. tostring(err))
end

print("E2E PASS offline_api")
process.exit(0)
