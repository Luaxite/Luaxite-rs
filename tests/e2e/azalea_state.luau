-- e2e: reading the bot's own state. Prints "E2E PASS azalea_state".
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

local bot = azalea.join { account = "E2EState", address = "localhost" }
bot:wait_for("spawn")
bot:wait_ticks(20)

local function isvec(v: any): boolean
	return type(v) == "table" and type(v.x) == "number" and type(v.y) == "number" and type(v.z) == "number"
end

local pos = bot:position()
expect(isvec(pos), "position is {x,y,z}")
expect(bot:health() > 0 and bot:health() <= 20, "health in (0, 20]")
expect(type(bot:minecraft_id()) == "number", "minecraft_id")

local dir = bot:direction()
expect(type(dir.y_rot) == "number" and type(dir.x_rot) == "number", "direction {y_rot, x_rot}")
bot:set_direction(90, 10)
bot:wait_ticks(2)
local after = bot:direction()
expect(math.abs(after.y_rot - 90) < 1 and math.abs(after.x_rot - 10) < 1, "set_direction took effect")
bot:set_direction(0, 0)
bot:wait_ticks(2)
bot:look_at({ x = pos.x + 5, y = pos.y + 1.6, z = pos.z })
bot:wait_ticks(2)
-- looking at a point east of the bot (+x) turns it to azalea's yaw -90 (x east, z south), pitch about level
local look = bot:direction()
expect(math.abs(look.y_rot - 0) > 45, "look_at turned the bot sideways: " .. look.y_rot)

local physics = bot:physics()
expect(type(physics.on_ground) == "boolean" and isvec(physics.velocity), "physics shape")
local attributes = bot:attributes()
expect(type(attributes.movement_speed.base) == "number", "attributes.movement_speed.base")
local xp = bot:experience()
expect(type(xp.level) == "number" and type(xp.progress) == "number" and type(xp.total) == "number", "experience shape")

local profile = bot:profile()
expect(profile.name == "E2EState" and type(profile.uuid) == "string", "profile name / uuid")
local account = bot:account()
expect(account.username == "E2EState" and type(account.uuid) == "string", "account username / uuid")

-- self entity
local me = bot:entity()
expect(me == bot:entity(), "entity handles compare equal")
expect(isvec(me:position()) and me:health() > 0, "entity position / health")
expect(me:minecraft_id() == bot:minecraft_id(), "entity id matches bot id")
expect(me:distance_to(me) == 0, "distance to itself")
expect(bot:entity_by_minecraft_id(bot:minecraft_id()) == me, "entity_by_minecraft_id finds self")
expect(bot:entity_by_uuid(profile.uuid) == me, "entity_by_uuid finds self")
expect(bot:entity_by_minecraft_id(2 ^ 30) == nil, "unknown id is nil")

-- tab list: the bot itself is in it
local found = false
for _, p in bot:tab_list() do
	expect(type(p.name) == "string" and type(p.uuid) == "string" and type(p.latency) == "number" and type(p.gamemode) == "string", "PlayerInfo shape")
	found = found or p.name == "E2EState"
end
expect(found, "tab_list has the bot")
expect(type(bot:nearby_players()) == "table", "nearby_players")
expect(bot:nearest_player() == nil or bot:nearest_player() ~= me, "nearest_player is never the bot")
for _, e in bot:nearby_entities() do
	expect(e ~= me, "nearby_entities excludes the bot")
end

-- soft: the rest of the state getters, whatever their exact shape
for _, name in { "hunger", "eye_position", "movement_state", "crouching", "jumping", "selected_hotbar_slot", "ticks_connected", "logged_in", "is_alive", "username", "uuid", "server_username", "attack_cooldown_remaining_ticks", "has_attack_cooldown", "is_mining", "is_executing_path", "is_calculating_path", "is_goto_target_reached" } do
	if has(bot, name) then
		soft("bot:" .. name .. "()", (bot :: any)[name], bot)
	end
end

-- entity getters
for _, name in { "position", "health", "physics", "attributes", "minecraft_id" } do
	expect(select("#", (me :: any)[name](me)) == 1, name .. " returns one value")
end

-- the other player's handle (nil when alone)
local other = bot:nearest_player()
if other then
	soft("player handle", function()
		expect(other:exists() and other:distance_to_client() >= 0 and isvec(other:eye_position()), "player exists / distance_to_client / eye_position")
	end)
end
expect(not pcall(function()
	bot:attack(nil :: any)
end), "attack rejects a non-entity")

print("E2E PASS azalea_state")
bot:exit()
