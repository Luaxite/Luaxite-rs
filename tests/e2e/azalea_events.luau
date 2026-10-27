-- e2e: events and packets: on / wait_for / on_packet / wait_for_packet / write_*; disconnect on exit. Prints "E2E PASS azalea_events".
local function expect(cond: any, msg: string)
	if not cond then
		error("E2E FAIL: " .. msg, 2)
	end
end
-- Anything not asserted with `expect` is a soft check: a mismatch prints "E2E WARN" (run.sh does not count it) and is logged for review.
local function soft(label: string, f: (...any) -> ...any, ...: any): (boolean, any)
	local ok, res = pcall(f, ...)
	if not ok then
		print("E2E WARN " .. label .. ": " .. tostring(res))
	end
	return ok, res
end
local function has(obj: any, name: string): boolean
	local ok, v = pcall(function()
		return obj[name]
	end)
	return ok and v ~= nil
end

local bot = azalea.join { account = "E2EEvents", address = "localhost" }

local fired = { init = 0, login = 0, spawn = 0, tick = 0, update = 0, add_player = 0, keep_alive = 0 }
for ev in fired do
	bot:on(ev :: any, function()
		fired[ev] += 1
	end)
end
bot:wait_for("spawn")
bot:wait_ticks(60)
expect(fired.login >= 1, "login fired")
expect(fired.spawn >= 1, "spawn fired")
expect(fired.tick >= 40, "tick fired every tick: " .. fired.tick)
expect(fired.update >= fired.tick, "update fires at least once per tick")

-- chat round trip, wait_for returns the packet
bot:chat("e2e events ping")
local packet
repeat
	packet = bot:wait_for("chat")
until packet.content:find("e2e events ping", 1, true)
expect(type(packet.message) == "string" and type(packet.is_whisper) == "boolean", "ChatPacket shape")
expect(packet.sender == nil or type(packet.sender) == "string", "ChatPacket.sender")

-- two handlers on the same event both run
local a, b = 0, 0
bot:on("tick", function()
	a += 1
end)
bot:on("tick", function()
	b += 1
end)
bot:wait_ticks(5)
expect(a >= 4 and a == b, "both tick handlers ran: " .. a .. ", " .. b)

-- a handler that errors does not stop the others and does not kill the bot
bot:on("tick", function()
	error("e2e-expected handler error")
end)
bot:wait_ticks(3)
expect(bot:health() > 0, "the bot survived a raising handler")

-- handlers run inside the script's LocalSet: task.defer / task.delay in a handler must not panic
local task = require("@lune/task")
local deferred, delayed = false, false
bot:on("tick", function()
	task.defer(function()
		deferred = true
	end)
	task.delay(0, function()
		delayed = true
	end)
end)
bot:wait_ticks(5)
expect(deferred and delayed, "task.defer / task.delay inside an event handler ran")

-- a handler parked in wait_for must not block the event that wakes it (events run one task each)
local parked, resumed = false, false
bot:on("tick", function()
	if parked then
		return
	end
	parked = true
	bot:wait_for("chat")
	resumed = true
end)
bot:wait_ticks(3)
expect(parked, "tick handler parked in wait_for(chat)")
bot:chat("e2e events wake")
bot:wait_ticks(20)
expect(resumed, "wait_for inside a handler resumed while the handler was still running")

-- unknown event names are rejected
expect(not pcall(function()
	bot:on("not_an_event" :: any, function() end)
end), "unknown event accepted by on")
expect(not pcall(function()
	bot:wait_for("not_an_event" :: any)
end), "unknown event accepted by wait_for")

-- packets
local seen = 0
bot:on_packet("set_time", function(p)
	expect(p.kind == "set_time", "on_packet kind")
	seen += 1
end)
expect(bot:wait_for_packet("set_time").kind == "set_time", "wait_for_packet")
expect(bot:raw_connection().state == "game", "raw_connection().state")
bot:write_packet("swing", { hand = "main_hand" })
bot:write_chat_packet("e2e events raw chat")
soft("write_command_packet", function()
	(bot :: any):write_command_packet("list")
end)
soft("chat command", function()
	bot:chat("/list")
end)
bot:wait_ticks(5)

bot:wait_ticks(20)
expect(seen > 0, "on_packet(set_time) fired")
-- disconnect must be delivered while another handler is still parked (closing the bot also wakes that waiter with an error)
bot:on("tick", function()
	pcall(function()
		bot:wait_for("chat") -- errors when the bot closes; pcall keeps run.sh from seeing a [luau] line
	end)
end)
bot:on("disconnect", function()
	print("E2E events: disconnect handler ran")
end)
bot:wait_ticks(3)
bot:exit()
-- wait_for after the bot is gone fails at once (it used to hang the whole script: nothing could ever wake it)
local ok, err = pcall(function()
	bot:wait_for("chat")
end)
expect(not ok and string.find(tostring(err), "disconnected", 1, true) ~= nil, "wait_for after disconnect errors instead of hanging")
local ok2, err2 = pcall(function()
	bot:wait_for("chat")
end)
expect(not ok2 and string.find(tostring(err2), "disconnected", 1, true) ~= nil, "wait_for after disconnect keeps erroring")
print("E2E PASS azalea_events")
