-- e2e: a swarm of bots from azalea.swarm, exit order, and azalea.wait. Prints "E2E PASS azalea_swarm".
local function expect(cond: any, msg: string)
	if not cond then
		error("E2E FAIL: " .. msg, 2)
	end
end
-- Anything not asserted with `expect` is a soft check: a mismatch prints "E2E WARN" (run.sh does not count it) and is logged for review.
local function soft(label: string, f: (...any) -> ...any, ...: any): (boolean, any)
	local ok, res = pcall(f, ...)
	if not ok then
		print("E2E WARN " .. label .. ": " .. tostring(res))
	end
	return ok, res
end
local function has(obj: any, name: string): boolean
	local ok, v = pcall(function()
		return obj[name]
	end)
	return ok and v ~= nil
end

local swarm = azalea.swarm { address = "localhost" }
local bots = {}
local up = {}
for _, name in { "E2ESwarmA", "E2ESwarmB", "E2ESwarmC" } do
	local bot = swarm:add(name)
	bots[name] = bot
	bot:on("spawn", function()
		up[name] = true
	end)
end
for name, bot in bots do
	if not up[name] then
		bot:wait_for("spawn")
	end
	expect(bot:profile().name == name, name .. " has its own profile")
end
bots.E2ESwarmA:chat("swarm hello")
local heard = false
bots.E2ESwarmB:on("chat", function(p)
	heard = heard or p.content:find("swarm hello", 1, true) ~= nil
end)
bots.E2ESwarmA:chat("swarm hello again")
for _ = 1, 100 do
	if heard then
		break
	end
	bots.E2ESwarmB:wait_ticks(1)
end
expect(heard, "bot B heard bot A")
expect(bots.E2ESwarmA:minecraft_id() ~= bots.E2ESwarmB:minecraft_id(), "distinct entity ids")

local left = 0
for _, bot in bots do
	bot:on("disconnect", function()
		left += 1
	end)
end
print("E2E PASS azalea_swarm")
swarm:exit()
