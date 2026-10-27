-- A swarm: cargo run -- src/swarm.luau
-- `azalea.swarm` starts an azalea Swarm and returns it; `swarm:add(account)` adds a bot (its own handlers, like `azalea.join`).

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

-- The script ending does not stop the handlers; the process runs until the swarm ends (`swarm:exit()` or every bot gone).
