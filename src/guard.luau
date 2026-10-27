-- cargo run -- src/guard.luau   (joins the `address` given to azalea.join below)
-- Stands guard: when a player is within 4 blocks it attacks; after dying it waits for the next spawn.
-- Chat "!guard off" / "!guard on" to pause or resume.
local bot = azalea.join { account = "GuardBot", address = "localhost" }

local REACH = 4
local guarding = true

bot:on("chat", function(packet)
	if packet.content == "!guard off" then
		guarding = false
		bot:chat("standing down")
	elseif packet.content == "!guard on" then
		guarding = true
		bot:chat("on guard")
	end
end)

bot:on("death", function(info)
	-- `info` is nil when the server sent no death message
	print("died:", info and info.message or "(no message)")
end)

bot:wait_for("spawn")
bot:chat("on guard")

while true do
	bot:wait_ticks(10) -- yields; the handlers above keep running meanwhile
	local target = guarding and bot:nearest_player() or nil
	if target and target:exists() and target:distance_to_client() <= REACH then
		bot:look_at(target:eye_position())
		bot:attack(target)
	end
end
