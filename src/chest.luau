-- cargo run -- src/chest.luau   (joins the `address` given to azalea.join below)
-- Chat "!chest X Y Z" and the bot walks to that chest and moves every stack from it into its own inventory.
local bot = azalea.join { account = "ChestBot", address = "localhost" }

bot:on("chat", function(packet)
	local x, y, z = packet.content:match("^!chest (-?%d+) (-?%d+) (-?%d+)$")
	if not x then
		return
	end
	local pos = { x = tonumber(x), y = tonumber(y), z = tonumber(z) }

	bot:goto_reach(pos) -- yields until the chest is within reach
	local chest = bot:open_container_at_with_timeout_ticks(pos, 100) -- nil if it doesn't open in time
	if not chest then
		bot:chat("couldn't open the chest")
		return
	end

	-- slots() lists the chest first, then the bot's inventory; an empty slot is `false`.
	-- Clicks take 0-based slot numbers, so Lua index i is slot i - 1. A single chest has 27 slots.
	local function count_in_chest()
		local total = 0
		for i, item in ipairs(chest:slots() or {}) do
			if i > 27 then
				break
			end
			if item then
				total += item.count
			end
		end
		return total
	end

	local before = count_in_chest()
	for i, item in ipairs(chest:slots() or {}) do
		if i > 27 then
			break
		end
		if item then
			chest:shift_click(i - 1)
		end
	end
	bot:wait_ticks(5) -- let the server confirm the moves before looking again
	-- shift-clicking a stack that doesn't fit leaves it in the chest, so count what is really gone instead of what was clicked
	local left = count_in_chest()
	chest:close()
	local moved = before - left
	if left > 0 then
		bot:chat(`took {moved} of {before} items, {left} left in the chest (inventory full?)`)
	else
		bot:chat(`took {moved} items`)
	end
end)
