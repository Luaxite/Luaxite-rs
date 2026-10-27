-- e2e: single bot against a flat-world server. Prints "E2E PASS basic" when every check holds.
local bot = azalea.join { account = "E2EBasic", address = "localhost" }

bot:wait_for("spawn")
bot:wait_ticks(40)

local pos = bot:position()
assert(pos.y > -64 and pos.y < 320, "position out of range")
assert(bot:health() > 0, "health")

local world = bot:world()
local below = { x = math.floor(pos.x), y = math.floor(pos.y) - 1, z = math.floor(pos.z) }
assert(world:block_state(below), "no block below the bot")
assert(world:is_chunk_loaded(math.floor(pos.x / 16), math.floor(pos.z / 16)), "own chunk not loaded")
assert(world:find_block("grass_block", nil, 16), "no grass_block within 16")
assert(world:height(math.floor(pos.x), math.floor(pos.z)), "no height")

assert(#bot:ecs_names() > 0, "ecs_names empty")
assert(bot:component("Health") > 0, "Health component")
assert(bot:query_self({ "Health", "Physics" }, function(row)
    return type(row.Physics.on_ground) == "boolean" and row.Health > 0
end), "query_self")
assert(bot:nearest_entity_by({ "Health" }, function(row, entity)
    return entity == bot:entity()
end) == nil, "nearest_entity_by returned the bot")
for _, e in bot:nearest_entities() do
    assert(e ~= bot:entity(), "nearest_entities returned the bot")
end

assert(bot:registry_resolve("enchantment", "sharpness"), "registry_resolve")
assert(#bot:registry_entries("enchantment") > 0, "registry_entries")

local inventory = bot:open_inventory()
assert(inventory and #inventory:slots() > 0, "open_inventory")
inventory:close()

bot:chat("hello e2e")
repeat
    local packet = bot:wait_for("chat")
until packet.content:find("hello e2e", 1, true)

local x = pos.x + 6
bot:goto_goal(goal.any(goal.xz(x, pos.z), goal.xz(x + 1, pos.z)))
assert(math.abs(bot:position().x - x) < 3, "goto_goal did not get near the target")

print("E2E PASS basic")
bot:exit()
