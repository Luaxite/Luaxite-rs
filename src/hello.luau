-- cargo run -- src/hello.luau   (joins the `address` given to azalea.join below)
-- `bot` is the azalea client. Everything it can do is listed in types/bindings.d.luau.
local bot = azalea.join { account = "HelloBot", address = "localhost" }

bot:on("spawn", function()
	bot:chat("hello from luau!")
end)

bot:on("chat", function(packet)
	print(`<{packet.sender or "server"}> {packet.content}`)

	if packet.content == "!pos" then
		local p = bot:position()
		bot:chat(string.format("I'm at %.1f %.1f %.1f", p.x, p.y, p.z))
	end

	local x, z = packet.content:match("^!goto (-?%d+) (-?%d+)$")
	local gx, gz = tonumber(x), tonumber(z)
	if gx and gz then
		bot:chat("on my way")
		bot:goto_xz(gx, gz) -- yields until the pathfinder is done
		-- the pathfinder can give up (no path, unloaded chunks): only say "arrived" when the bot is really there
		local p = bot:position()
		if math.abs(p.x - gx) < 3 and math.abs(p.z - gz) < 3 then
			bot:chat("arrived")
		else
			bot:chat("couldn't get there")
		end
	end
end)

bot:on("disconnect", function(reason)
	print("disconnected:", reason)
end)
