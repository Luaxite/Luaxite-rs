local bot = azalea.join { account = "ChestBot", address = "localhost" }

bot:on("chat", function(packet)
	local x, y, z = packet.content:match("^!chest (-?%d+) (-?%d+) (-?%d+)$")
	if not x then
		return
	end
	local pos = { x = tonumber(x), y = tonumber(y), z = tonumber(z) }

	bot:goto_reach(pos)
	local chest = bot:open_container_at_with_timeout_ticks(pos, 100)
	if not chest then
		bot:chat("couldn't open the chest")
		return
	end

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
	bot:wait_ticks(5)
	local left = count_in_chest()
	chest:close()
	local moved = before - left
	if left > 0 then
		bot:chat(`took {moved} of {before} items, {left} left in the chest (inventory full?)`)
	else
		bot:chat(`took {moved} items`)
	end
end)
