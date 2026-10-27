-- e2e: the bound API surface. Every name here must exist on the object the bindings put it on; names not listed as "known" are
-- looked up on every object and only reported when nowhere. Prints "E2E PASS azalea_surface".
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

local bot = azalea.join { account = "E2ESurface", address = "localhost" }
bot:wait_for("spawn")

local entity = bot:entity()
local world = bot:world()
local inventory = bot:open_inventory()
expect(inventory ~= nil, "open_inventory")

-- known: generated from azalea (the fixture mirrors them), hand-written (rust/luau/extra_*.rs) or used by the other e2e scripts
local BOT = {
	"on", "wait_for", "chat", "write_chat_packet", "attack", "attributes", "direction", "entity", "entity_by_minecraft_id", "entity_by_uuid",
	"entity_id_by_minecraft_id", "entity_id_by_uuid", "entity_interact", "entity_ref_for", "experience", "get_held_item", "get_inventory",
	"goto", "goto_with_opts", "goto_with_opts_xz", "goto_xz", "health", "hit_result", "look_at", "menu", "mine", "mine_with_auto_tool",
	"minecraft_id", "nearby_players", "open_container_at", "open_container_at_with_timeout_ticks", "open_inventory", "physics", "position",
	"profile", "set_direction", "start_goto", "start_goto_with_opts", "start_goto_with_opts_xz", "start_goto_xz", "stop_pathfinding",
	"wait_for_container_open", "wait_ticks", "walk",
	-- hand-written
	"block_at", "best_tool_for", "best_tool_in_hotbar_for_block", "held_item", "inventory", "goto_reach", "set_client_information",
	"nearest_player", "nearby_entities", "account", "tab_list",
	-- real-only glue, used by basic / packets / multi
	"world", "ecs_names", "component", "query_self", "nearest_entity_by", "nearest_entities", "registry_resolve", "registry_entries",
	"goto_goal", "on_packet", "wait_for_packet", "write_packet", "raw_connection", "exit", "wait_tick", "wait_update",
}
for _, name in BOT do
	expect(has(bot, name), "Bot is missing :" .. name .. "()")
end

local ENTITY = { "position", "health", "attack", "physics", "attributes", "minecraft_id", "distance_to" }
for _, name in ENTITY do
	expect(has(entity, name), "Entity is missing :" .. name .. "()")
end
local WORLD = { "block_state", "find_block", "height", "is_chunk_loaded" }
for _, name in WORLD do
	expect(has(world, name), "World is missing :" .. name .. "()")
end
local CONTAINER = { "slots", "close", "left_click", "right_click", "shift_click", "middle_click", "double_click", "swap", "throw", "drop_cursor" }
for _, name in CONTAINER do
	expect(has(inventory, name), "Container is missing :" .. name .. "()")
end
for _, name in { "xz", "y", "radius", "inverse", "block", "all", "any" } do
	expect(has(goal, name), "goal." .. name .. " is missing")
end
for _, name in { "join", "swarm", "wait" } do
	expect(has(azalea, name), "azalea." .. name .. " is missing")
end
expect(has(process, "exit"), "process.exit")

-- the rest of the real API (tools/baseline_api.txt): found on any object, else reported
local OTHERS = {
	"all", "any", "any_entity_by", "attack_cooldown_remaining_ticks", "biome", "block_interact", "chunk_loaded", "contents", "crouching",
	"describe", "dimensions", "disconnect", "distance_to_client", "exists", "eye_position", "find_blocks", "force_stop_pathfinding",
	"get_component", "get_entity_component", "goto_radius", "goto_with_opts_radius", "goto_with_opts_y", "goto_y", "has_attack_cooldown",
	"hunger", "interact", "is_alive", "is_calculating_path", "is_executing_path", "is_goto_target_reached", "is_mining", "jump", "jumping",
	"kind", "left_click_mine", "logged_in", "map_get_resource", "map_resource", "movement_state", "nearest_entities_by", "partial_world",
	"player_uuid_by_username", "quick_craft", "reach_goal", "registry_get", "registry_kinds", "registry_name", "resource",
	"selected_hotbar_slot", "server_username", "set_crouching", "set_jumping", "set_selected_hotbar_slot", "sprint", "start_goto_goal",
	"start_goto_radius", "start_goto_with_opts_radius", "start_goto_with_opts_y", "start_goto_y", "start_mining", "start_use_item",
	"ticks_connected", "title", "try_query_entity", "try_query_self", "query_entity", "username", "uuid", "wait_until_goto_target_reached",
	"wait_updates", "write_command_packet", "raw_connection_mut", "entity_component", "id", "name",
}
local objects = { bot, entity, world, inventory, goal, azalea }
local missing = {}
for _, name in OTHERS do
	local found = false
	for _, obj in objects do
		if has(obj, name) then
			found = true
			break
		end
	end
	if not found then
		table.insert(missing, name)
	end
end
if #missing > 0 then
	print("E2E WARN azalea_surface: not found on bot / entity / world / container / goal / azalea: " .. table.concat(missing, ", "))
end

print("E2E PASS azalea_surface")
bot:exit()
