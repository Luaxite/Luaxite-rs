local swarm = azalea.swarm { address = "localhost" }

for _, name in { "SwarmA", "SwarmB", "SwarmC" } do
	local bot = swarm:add(name)

	bot:on("login", function()
		bot:chat("hello from " .. name)
	end)

	bot:on("disconnect", function()
		print(name .. " left")
	end)
end
