local bot = azalea.join { account = "E2EPackets", address = "localhost" }

print("E2E packets: start")
local seen = 0
local kinds = {}
local total = 0
bot:on("packet", function(p)
    total += 1
    if not kinds[p.kind] then
        kinds[p.kind] = true
        print("E2E packets: new kind " .. tostring(p.kind) .. " (total " .. total .. ")")
    end
end)
for _, ev in { "login", "spawn", "add_player", "death", "keep_alive", "disconnect", "connection_failed", "receive_chunk" } do
    bot:on(ev :: any, function() print("E2E packets: event " .. ev) end)
end
local ticks = 0
bot:on("tick", function()
    ticks += 1
    if ticks % 100 == 1 then print("E2E packets: tick " .. ticks .. ", packets " .. total .. ", set_time " .. seen) end
end)
bot:on_packet("set_time", function(packet)
    assert(packet.kind == "set_time" and type(packet.game_time) == "number", "set_time shape")
    seen += 1
end)

bot:wait_for("spawn")
print("E2E packets: spawned")
assert(bot:wait_for_packet("set_time").kind == "set_time", "wait_for_packet")
print("E2E packets: wait_for_packet ok")
bot:wait_ticks(60)
print("E2E packets: ticks ok, seen=" .. seen)
assert(seen > 0, "on_packet never fired")

local any = bot:wait_for("packet")
assert(type(any.kind) == "string", "packet event has no kind")
print("E2E packets: wait_for packet ok")
assert(pcall(function() (bot :: any):on_packet("not_a_packet", function() end) end) == false, "unknown kind accepted")

assert(bot:raw_connection().state == "game", "raw_connection state")
bot:write_packet("swing", { hand = "main_hand" })
assert(pcall(function() bot:write_packet("swing", { hand = "nope" }) end) == false, "bad field accepted")

print("E2E PASS packets")
bot:exit()
