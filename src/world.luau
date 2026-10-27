-- cargo run -- src/world.luau   (joins the `address` given to azalea.join below)
-- Chat "!find <block>" and the bot reports the nearest such block within 64 blocks and walks next to it.
local bot = azalea.join { account = "WorldBot", address = "localhost" }

bot:wait_for("spawn")

bot:on("chat", function(packet)
    local name = packet.content:match("^!find (%S+)$")
    if not name then
        return
    end
    local pos = bot:world():find_block(name, nil, 64)
    if not pos then
        bot:chat(`no {name} within 64 blocks`)
        return
    end
    bot:chat(`{name} at {pos.x} {pos.y} {pos.z}, biome {bot:world():biome(pos) or "unknown"}`)
    bot:goto_reach(pos)
end)
