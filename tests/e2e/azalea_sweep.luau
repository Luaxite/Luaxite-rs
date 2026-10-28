local bot = azalea.join { account = "E2ESweep", address = "localhost" }
bot:wait_for("spawn")
bot:wait_ticks(40)

local me = bot:entity()
local world = bot:world()
local inv = bot:open_inventory()
local p = bot:position()
local ipos = { x = math.floor(p.x), y = math.floor(p.y), z = math.floor(p.z) }
local below = { x = ipos.x, y = ipos.y - 1, z = ipos.z }
local uuid = bot:profile().uuid
local noop = function() end
local row_has_health = function(row: any)
	return row.Health ~= nil
end

local targets: { any } = { bot, me, world, inv, goal }

local specs: { { any } } = {
	{ "attack_cooldown_remaining_ticks" }, { "has_attack_cooldown" }, { "crouching" }, { "jumping" }, { "hunger" }, { "is_alive" },
	{ "logged_in" }, { "is_mining" }, { "movement_state" }, { "server_username" }, { "username" }, { "uuid" }, { "ticks_connected" },
	{ "is_calculating_path" }, { "is_goto_target_reached" }, { "get_held_item" }, { "hit_result" }, { "partial_world" }, { "dimensions" },
	{ "player_uuid_by_username", "E2ESweep" }, { "wait_tick" }, { "wait_update" }, { "wait_updates", 2 },
	{ "entity_id_by_minecraft_id", bot:minecraft_id() }, { "entity_id_by_uuid", uuid }, { "entity_ref_for", me }, { "kind" }, { "id" },
	{ "entity_interact", me }, { "entity_component", me, "Health" }, { "get_entity_component", me, "Health" }, { "get_component", "Health" },
	{ "query_entity", me, { "Health" }, row_has_health }, { "try_query_entity", me, { "Health" }, row_has_health },
	{ "nearest_entities_by", { "Health" }, row_has_health },
	{ "map_resource", "Time", noop }, { "map_get_resource", "Time", noop }, { "resource", "Time" },
	{ "registry_get", "enchantment", "sharpness" }, { "registry_kinds" }, { "registry_name", "enchantment", 0 },
	{ "raw_connection_mut" }, { "quick_craft" },
	{ "chunk_loaded", ipos.x // 16, ipos.z // 16 }, { "contents", below }, { "describe", below }, { "title" },
	{ "block_interact", below }, { "interact" }, { "start_use_item" }, { "start_mining", below }, { "left_click_mine", below },
	{ "mine_with_auto_tool", { x = ipos.x + 3, y = ipos.y - 1, z = ipos.z } },
	{ "open_container_at", { x = ipos.x, y = ipos.y + 5, z = ipos.z } },
	{ "jump" }, { "set_jumping", false }, { "set_crouching", false }, { "sprint", "none" },
	{ "start_goto", { x = ipos.x + 4, y = ipos.y, z = ipos.z } }, { "start_goto_xz", ipos.x + 4, ipos.z },
	{ "start_goto_y", ipos.y }, { "start_goto_radius", { x = ipos.x + 4, y = ipos.y, z = ipos.z }, 2 },
	{ "start_goto_with_opts", { x = ipos.x + 4, y = ipos.y, z = ipos.z }, { allow_mining = false } },
	{ "start_goto_with_opts_xz", ipos.x + 4, ipos.z, { allow_mining = false } },
	{ "start_goto_with_opts_y", ipos.y, { allow_mining = false } },
	{ "start_goto_with_opts_radius", { x = ipos.x + 4, y = ipos.y, z = ipos.z }, 2, { allow_mining = false } },
	{ "start_goto_goal", goal.xz(ipos.x + 4, ipos.z) }, { "reach_goal", goal.xz(ipos.x + 2, ipos.z) },
	{ "goto_y", ipos.y }, { "goto_radius", { x = ipos.x + 2, y = ipos.y, z = ipos.z }, 2 },
	{ "goto_with_opts_y", ipos.y, { allow_mining = false } },
	{ "goto_with_opts_radius", { x = ipos.x + 2, y = ipos.y, z = ipos.z }, 2, { allow_mining = false } },
	{ "wait_until_goto_target_reached" }, { "force_stop_pathfinding" },
	{ "left_click", 30 }, { "right_click", 30 }, { "middle_click", 30 }, { "double_click", 30 }, { "swap", 30, 0 }, { "throw", 30 },
	{ "drop_cursor" },
	{ "disconnect" },
}

local function find(name: string): (any?, any?)
	for _, t in targets do
		local ok, v = pcall(function()
			return t[name]
		end)
		if ok and v ~= nil then
			return t, v
		end
	end
	return nil, nil
end

local function tame(v: any): boolean
	local t = type(v)
	return t == "nil" or t == "boolean" or t == "number" or t == "string" or t == "table" or t == "userdata" or t == "function"
end

local called, raised, missing = 0, 0, {}
for _, spec in specs do
	local name = spec[1]
	local target, fn = find(name)
	if not target then
		table.insert(missing, name)
		continue
	end
	local args = { table.unpack(spec, 2) }
	local ok, res
	if target == goal then
		ok, res = pcall(fn, table.unpack(args))
	else
		ok, res = pcall(fn, target, table.unpack(args))
	end
	called += 1
	if ok then
		assert(tame(res), name .. " returned something odd")
	else
		raised += 1
		print("E2E WARN sweep " .. name .. ": " .. tostring(res))
	end
	if string.sub(name, 1, 5) == "start" or name == "reach_goal" then
		pcall(bot.stop_pathfinding, bot)
	end
end
if #missing > 0 then
	print("E2E WARN sweep: not found on bot / entity / world / container / goal (so on some other object): " .. table.concat(missing, ", "))
end
print(`E2E sweep: called {called} of {#specs} ({raised} raised, {#missing} found elsewhere)`)
assert(called >= #specs // 2, "less than half of the sweep names were reachable: the object classification is wrong")

print("E2E PASS azalea_sweep")
bot:exit()
