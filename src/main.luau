local names = { "Alice", "Bob", "Carol" }
local bots = {}

for _, name in names do
	local bot = azalea.join { account = name, address = "localhost" }
	bots[name] = bot

	bot:on("login", function()
		bot:chat("hello from " .. name)
	end)

	bot:on("chat", function(packet)
		print("[" .. name .. " sees]", packet.message)
	end)

	bot:on("disconnect", function()
		print(name .. " left")
	end)
end
