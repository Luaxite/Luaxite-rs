-- Entry script: runs when the executable is started with no arguments (embedded at build time).
-- The executable only provides the functions and runs this script: every `azalea.join` starts one more bot. Like a Roblox
-- script, this file ending does not stop the handlers: the process runs until every bot is gone.

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
