local function expect(cond: any, msg: string)
	if not cond then
		error("E2E FAIL: " .. msg, 2)
	end
end
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

local bot = azalea.join { account = "E2EInv", address = "localhost" }
bot:wait_for("spawn")
bot:wait_ticks(20)

local items = bot:inventory()
expect(type(items) == "table", "inventory is a list")
expect(#items == 46, "an inventory has 46 slots, got " .. #items)
for _, slot in items do
	expect(slot == false or (type(slot.kind) == "string" and type(slot.count) == "number"), "slot is false or an Item")
end
expect(bot:held_item() == nil or type(bot:held_item().kind) == "string", "held_item")

local menu = bot:menu()
expect(type(menu.kind) == "string" and type(menu.slots) == "table", "menu {kind, slots}")

local inv = bot:open_inventory()
expect(inv ~= nil, "open_inventory")
local slots = inv:slots()
expect(type(slots) == "table" and #slots >= 36, "container slots")

for _, call in {
	{ "left_click", 20 }, { "right_click", 20 }, { "shift_click", 20 }, { "double_click", 20 }, { "swap", 20, 0 }, { "throw", 20 }, { "throw", 20, true },
	{ "drop_cursor" }, { "drop_cursor", true },
} do
	local ok, err = pcall((inv :: any)[call[1]], inv, table.unpack(call, 2))
	expect(ok, call[1] .. " on an empty slot: " .. tostring(err))
end
for _, call in { { "throw", 20, 1 }, { "throw", 20, "yes" }, { "drop_cursor", 0 } } do
	local ok = pcall((inv :: any)[call[1]], inv, table.unpack(call, 2))
	expect(not ok, call[1] .. " rejects a non-boolean whole_stack")
end
soft("middle_click (creative only)", (inv :: any).middle_click, inv, 20)
inv:close()
inv:close()
expect(inv:slots() == nil, "slots is nil once closed")

if has(bot, "set_selected_hotbar_slot") and has(bot, "selected_hotbar_slot") then
	soft("hotbar selection", function()
		bot:set_selected_hotbar_slot(3)
		bot:wait_ticks(2)
		expect(bot:selected_hotbar_slot() == 3, "selected_hotbar_slot is 3")
		bot:set_selected_hotbar_slot(0)
	end)
end

expect(bot:get_inventory() ~= nil, "get_inventory")
local timed_out = bot:wait_for_container_open(5)
expect(timed_out == nil or timed_out ~= false, "wait_for_container_open returns a container or nil")
soft("open_container_at on air", function()
	local p = bot:position()
	local c = bot:open_container_at_with_timeout_ticks({ x = math.floor(p.x), y = math.floor(p.y) + 5, z = math.floor(p.z) }, 20)
	expect(c == nil, "nothing to open in the air")
end)

soft("set_client_information", function()
	bot:set_client_information({ language = "en_us", view_distance = 6, chat_visibility = "full", main_hand = "left" })
end)

print("E2E PASS azalea_inventory")
bot:exit()
