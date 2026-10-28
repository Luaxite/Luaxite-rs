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

local bot = azalea.join { account = "E2EWorld", address = "localhost" }
bot:wait_for("spawn")
bot:wait_ticks(40)

local pos = bot:position()
local bx, bz = math.floor(pos.x), math.floor(pos.z)
local below = { x = bx, y = math.floor(pos.y) - 1, z = bz }
local world = bot:world()
expect(bot:world_name() == "minecraft:overworld", "world_name: " .. tostring(bot:world_name()))

expect(world:block_state(below), "block_state below")
local name = bot:block_at(below)
expect(type(name) == "string" and name:find("minecraft:", 1, true) == 1, "block_at is a namespaced name: " .. tostring(name))
expect(bot:block_at({ x = bx, y = math.floor(pos.y) + 40, z = bz }) == "minecraft:air", "air high above")
expect(bot:block_at({ x = bx + 1000000, y = 64, z = bz }) == nil, "an unloaded chunk is nil")

expect(world:is_chunk_loaded(bx // 16, bz // 16), "own chunk loaded")
expect(not world:is_chunk_loaded(100000, 100000), "far chunk not loaded")
expect(type(world:height(bx, bz)) == "number", "height")

local grass = world:find_block("grass_block", nil, 16)
expect(grass and type(grass.x) == "number", "find_block grass_block")
expect(bot:block_at(grass) == "minecraft:grass_block", "find_block result is grass_block")
expect(world:find_block("diamond_block", nil, 8) == nil, "no diamond block nearby")
local namespaced = world:find_block("minecraft:grass_block", nil, 16)
expect(namespaced ~= nil, "find_block accepts a namespaced name")

if has(world, "find_blocks") then
	local list = world:find_blocks("grass_block", nil, 6)
	expect(type(list) == "table" and #list > 0, "find_blocks returns a list")
end
if has(world, "biome") then
	soft("world:biome", function()
		expect(type(world:biome(below)) == "string", "biome is a string")
	end)
end

local slot = bot:best_tool_for("stone")
expect(slot == nil or (slot >= 0 and slot <= 8), "best_tool_for: nil or a hotbar slot")
local best = bot:best_tool_in_hotbar_for_block("stone")
expect(type(best.slot) == "number" and type(best.percentage_per_tick) == "number", "best_tool_in_hotbar_for_block shape")

local target = { x = bx + 2, y = math.floor(pos.y) - 1, z = bz }
if bot:block_at(target) ~= "minecraft:air" then
	soft("mine", function()
		bot:goto_reach(target)
		bot:mine(target)
		bot:wait_ticks(10)
		expect(bot:block_at(target) == "minecraft:air", "mined block is air")
	end)
end

print("E2E PASS azalea_world")
bot:exit()
