local bot = azalea.join { account = "EcsBot", address = "localhost" }

bot:wait_for("spawn")

print("my health:", bot:component("Health"))

local hurt = bot:nearest_entity_by({ "Health" }, function(row, entity)
    return entity ~= bot:entity() and row.Health < 10
end)
if hurt then
    print("nearest hurt entity:", hurt:kind(), hurt:position())
end

bot:query_self({ "Health", "Physics" }, function(row)
    print("health", row.Health, "on ground", row.Physics.on_ground)
end)
