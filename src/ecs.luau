-- cargo run -- src/ecs.luau   (joins the `address` given to azalea.join below)
-- Reads ECS components by name (`bot:ecs_names()` lists them) and finds the nearest entity by a predicate.
local bot = azalea.join { account = "EcsBot", address = "localhost" }

bot:wait_for("spawn")

print("my health:", bot:component("Health"))

-- The row is a snapshot of the named components; the predicate may yield.
local hurt = bot:nearest_entity_by({ "Health" }, function(row, entity)
    return entity ~= bot:entity() and row.Health < 10
end)
if hurt then
    print("nearest hurt entity:", hurt:kind(), hurt:position())
end

bot:query_self({ "Health", "Physics" }, function(row)
    print("health", row.Health, "on ground", row.Physics.on_ground)
end)
