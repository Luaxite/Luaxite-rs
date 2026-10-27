--!nocheck
-- The module main.luau requires. Its top level calls `azalea.join` exactly once and registers at least one handler; it returns nothing.
-- main.luau replaces `azalea.join` with a stub, so loading it joins no server.
local bot = azalea.join { account = "RequireProbe", address = "localhost" }

bot:on("login", function() end)
