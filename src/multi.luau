-- Two bots from one script: cargo run -- src/multi.luau
-- The script ending does not stop the handlers; the process ends when both bots are gone.

local alice = azalea.join { account = "Alice", address = "localhost" }
local bob = azalea.join { account = "Bob", address = "localhost" }

alice:on("login", function()
	alice:chat("hello from Alice")
end)

bob:on("chat", function(packet)
	print("[bob sees]", packet.message)
end)

bob:on("login", function()
	bob:chat("hello from Bob")
end)

-- Each bot has its own handlers: this only runs for Alice.
alice:on("disconnect", function()
	print("Alice left; Bob stays until he leaves too")
end)
