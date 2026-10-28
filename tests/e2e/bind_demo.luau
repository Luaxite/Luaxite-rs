-- The globals bound from rust_binds/luau/demo_binds.rs (`//BIND pub`). Needs no bot.
local function expect(cond: any, msg: string)
	if not cond then
		error("E2E FAIL: " .. msg, 2)
	end
end

expect(demo_add(2, 3) == 5, "demo_add")
expect(demo_greet("Bob") == "hello, Bob!", "demo_greet with an argument")
expect(demo_greet(nil) == "hello, world!", "demo_greet with nil")
expect(demo_div(7, 2) == 3.5, "demo_div")

local ok, err = pcall(demo_div, 1, 0)
expect(not ok and string.find(tostring(err), "division by zero", 1, true) ~= nil, "demo_div(1, 0) raises: " .. tostring(err))

demo_set_global("answer", 42)
expect(answer == 42, "demo_set_global set a global through the mlua handle")

print("E2E PASS bind_demo")
process.exit(0)
