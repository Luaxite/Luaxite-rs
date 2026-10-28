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

alice:on("disconnect", function()
	print("Alice left; Bob stays until he leaves too")
end)
