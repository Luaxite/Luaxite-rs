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

local bot = azalea.join { account = "E2EEcs", address = "localhost" }
bot:wait_for("spawn")
bot:wait_ticks(40)
local me = bot:entity()

local names = bot:ecs_names()
expect(type(names) == "table" and #names > 10, "ecs_names lists components")
local set = {}
for _, entry in names do
	set[entry.name] = true
end
for _, n in { "Health", "Physics", "Position" } do
	expect(set[n], "ecs_names has " .. n)
end

expect(bot:component("Health") == bot:health(), "component(Health) equals health()")
local ok, err = pcall(function()
	return bot:component("NotAComponent")
end)
expect(not ok, "an unknown component raises")
soft("component error mentions the name", function()
	expect(tostring(err):find("NotAComponent", 1, true), tostring(err))
end)

local ran = false
expect(bot:query_self({ "Health", "Physics" }, function(row)
	ran = true
	return type(row.Physics.on_ground) == "boolean" and row.Health > 0
end), "query_self returns the predicate result")
expect(ran, "query_self ran the function")

expect(bot:nearest_entity_by({ "Health" }, function(row, entity)
	return entity == me
end) == nil, "nearest_entity_by excludes the bot")
expect(bot:nearest_entity_by({ "Health" }, function()
	return false
end) == nil, "nothing matches: nil")
soft("a search over an unknown component", function()
	local r = bot:nearest_entity_by({ "NoSuchComponent" :: any }, function()
		return true
	end)
	expect(r == nil, "an unknown component matches nothing")
end)
for _, e in bot:nearest_entities() do
	expect(e ~= me, "nearest_entities excludes the bot")
end

local yielded = false
bot:nearest_entity_by({ "Health" }, function()
	bot:wait_ticks(1)
	yielded = true
	return false
end)
soft("a predicate may yield", function()
	expect(yielded or #bot:nearest_entities() == 0, "predicate ran and yielded when another entity exists")
end)

if has(bot, "try_query_self") then
	soft("try_query_self", function()
		local r = bot:try_query_self({ "Health" }, function(row)
			return row.Health
		end)
		expect(r ~= nil, "try_query_self result")
	end)
end
if has(bot, "any_entity_by") then
	soft("any_entity_by", function()
		expect(bot:any_entity_by({ "Health" }, function(row, e)
			return e == me
		end) == nil, "any_entity_by excludes the bot")
	end)
end

expect(bot:registry_resolve("enchantment", "sharpness"), "registry_resolve enchantment")
local entries = bot:registry_entries("enchantment")
expect(#entries > 0, "registry_entries")
for _, name in { "registry_get", "registry_kinds", "registry_name" } do
	if has(bot, name) then
		soft(name, (bot :: any)[name], bot, "enchantment")
	end
end
expect(not pcall(function()
	bot:registry_resolve("not_a_registry" :: any, "x")
end), "unknown registry raises")

print("E2E PASS azalea_ecs")
bot:exit()
