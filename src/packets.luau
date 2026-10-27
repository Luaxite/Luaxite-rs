-- cargo run -- src/packets.luau   (joins the `address` given to azalea.join below)
-- Reads clientbound packets and writes a serverbound one.
local bot = azalea.join { account = "PacketsBot", address = "localhost" }

bot:on_packet("set_health", function(packet)
    print("health", packet.health, "food", packet.food)
end)

bot:on("packet", function(packet)
    if packet.kind == "set_time" then
        print("game time", packet.game_time)
    end
end)

bot:wait_for("spawn")
bot:write_packet("swing", { hand = "main_hand" })
print(bot:raw_connection().state)
