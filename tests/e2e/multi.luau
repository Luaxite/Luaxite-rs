-- e2e: two bots from one script, each with its own handlers. Prints "E2E PASS multi".

-- A joined bot's events are dispatched as they arrive, and `wait_for` only sees events that fire after it is called: remember the spawn
-- from a handler made right after each join, so a bot that spawned while the other one was still joining is not waited for forever.
local alice = azalea.join { account = "E2EAlice", address = "localhost" }
local alice_up = false
alice:on("spawn", function() alice_up = true end)
local bob = azalea.join { account = "E2EBob", address = "localhost" }
local bob_up = false
bob:on("spawn", function() bob_up = true end)
print("E2E multi: joined")
if not alice_up then alice:wait_for("spawn") end
if not bob_up then bob:wait_for("spawn") end
print("E2E multi: both spawned")

local heard = false
bob:on("chat", function(packet)
    heard = heard or packet.content:find("from alice", 1, true) ~= nil
end)
alice:chat("from alice")
for _ = 1, 100 do
    if heard then
        break
    end
    bob:wait_ticks(1)
end
assert(heard, "bob did not hear alice")
print("E2E multi: chat ok")

-- Packet events must reach bots made by azalea.join too.
assert(bob:wait_for_packet("set_time").kind == "set_time", "no packet event on a joined bot")

print("E2E PASS multi")
alice:exit()
bob:exit()
