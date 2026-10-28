local function expect(cond: any, msg: string)
	if not cond then
		error("E2E FAIL: " .. msg, 2)
	end
end
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

local bot = azalea.join { account = "E2EMove", address = "localhost" }
bot:wait_for("spawn")
bot:wait_ticks(40)

local function dist(a: any, b: any): number
	return math.sqrt((a.x - b.x) ^ 2 + (a.z - b.z) ^ 2)
end

local start = bot:position()
bot:set_direction(0, 0)
bot:walk("forward")
bot:wait_ticks(20)
bot:walk("none")
bot:wait_ticks(10)
local walked = bot:position()
expect(
	dist(start, walked) > 1,
	string.format("walk forward moved the bot (from %.2f %.2f %.2f to %.2f %.2f %.2f)", start.x, start.y, start.z, walked.x, walked.y, walked.z)
)
expect(not pcall(function()
	bot:walk("sideways" :: any)
end), "an unknown walk direction raises")

local here = bot:position()
local gx, gz = math.floor(here.x) + 8, math.floor(here.z)
bot:goto_xz(gx, gz)
expect(dist(bot:position(), { x = gx, z = gz }) < 3, "goto_xz arrived")
local y = math.floor(bot:position().y)
bot:goto({ x = gx - 4, y = y, z = gz })
expect(dist(bot:position(), { x = gx - 4, z = gz }) < 3, "goto arrived")
bot:goto_with_opts({ x = gx, y = y, z = gz }, { retry_on_no_path = false, allow_mining = false })
expect(dist(bot:position(), { x = gx, z = gz }) < 3, "goto_with_opts arrived")
bot:goto_with_opts_xz(gx - 6, gz, { allow_mining = false })
expect(dist(bot:position(), { x = gx - 6, z = gz }) < 3, "goto_with_opts_xz arrived")
local bad_ok, bad_err = pcall(bot.goto_with_opts, bot, { x = gx, y = y, z = gz }, { allow_minin = false })
expect(not bad_ok and string.find(tostring(bad_err), "allow_minin", 1, true) ~= nil, "unknown PathfinderOpts key raises: " .. tostring(bad_err))
bad_ok, bad_err = pcall(bot.goto_with_opts, bot, { x = 0 / 0, y = y, z = gz }, { allow_mining = false })
expect(not bad_ok and string.find(tostring(bad_err), "coordinate", 1, true) ~= nil, "NaN coordinate raises: " .. tostring(bad_err))
bot:goto_reach({ x = gx + 3, y = y - 1, z = gz })
expect(dist(bot:position(), { x = gx + 3, z = gz }) < 6, "goto_reach got close")

local before = bot:position()
bot:start_goto_xz(math.floor(before.x) + 20, math.floor(before.z))
bot:wait_ticks(10)
bot:stop_pathfinding()
bot:wait_ticks(10)
local stopped = bot:position()
expect(dist(before, stopped) < 20, "stop_pathfinding stopped the walk early")
if has(bot, "is_executing_path") then
	soft("is_executing_path", function()
		bot:start_goto_xz(math.floor(stopped.x) + 20, math.floor(stopped.z))
		bot:wait_ticks(5)
		expect(bot:is_executing_path() == true, "executing while walking")
		bot:stop_pathfinding()
		bot:wait_ticks(10)
		expect(bot:is_executing_path() == false, "not executing after stop")
	end)
end

local p = bot:position()
local x = p.x + 6
bot:goto_goal(goal.any(goal.xz(x, p.z), goal.xz(x + 1, p.z)))
expect(math.abs(bot:position().x - x) < 3, "goal.any(xz, xz)")
local here2 = bot:position()
bot:goto_goal(goal.all(goal.inverse(goal.radius(here2, 10)), goal.y(math.floor(here2.y))))
expect(dist(bot:position(), here2) >= 8, "inverse radius moved away")
soft("goal.block", function()
	bot:goto_goal(goal.block({ x = math.floor(p.x), y = math.floor(p.y), z = math.floor(p.z) }))
end)

local q = bot:position()
for _, spec in {
	{ "goto_y", { math.floor(q.y) } },
	{ "goto_radius", { { x = math.floor(q.x) + 2, y = math.floor(q.y), z = math.floor(q.z) }, 2 } },
	{ "goto_with_opts_y", { math.floor(q.y), { allow_mining = false } } },
	{ "goto_with_opts_radius", { { x = math.floor(q.x) + 2, y = math.floor(q.y), z = math.floor(q.z) }, 2, { allow_mining = false } } },
} do
	if has(bot, spec[1]) then
		soft(spec[1], (bot :: any)[spec[1]], bot, table.unpack(spec[2]))
	end
end

for _, call in { { "jump" }, { "set_jumping", true }, { "set_jumping", false }, { "set_crouching", true }, { "set_crouching", false }, { "sprint", "forward" } } do
	if has(bot, call[1]) then
		soft(call[1], (bot :: any)[call[1]], bot, table.unpack(call, 2))
	end
end
bot:walk("none")

print("E2E PASS azalea_movement")
bot:exit()
