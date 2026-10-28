local luau = require("@lune/luau")

assert(luau.load("return 1 + 1")() == 2, "load")
local add = luau.load("local a, b = ... return a + b")
assert(add(2, 3) == 5, "loaded chunks take arguments")
local multi = { luau.load("return 1, 'two', nil, 4")() }
assert(multi[1] == 1 and multi[2] == "two" and multi[4] == 4, "loaded chunks return several values")

local bytecode = luau.compile("return 6 * 7")
assert(type(bytecode) == "string" and #bytecode > 0, "compile returns a string")
assert(luau.load(bytecode)() == 42, "load accepts bytecode")
assert(luau.compile("return 1", { optimizationLevel = 2 }) ~= nil, "compile options: optimizationLevel")
assert(luau.compile("return 1", { debugLevel = 1, coverageLevel = 0 }) ~= nil, "compile options: debugLevel / coverageLevel")

assert(luau.load("return x", { environment = { x = 7 } })() == 7, "environment option")
local ok, err = pcall(luau.load("error('boom')", { debugName = "my-chunk" }))
assert(not ok and tostring(err):find("boom", 1, true), "errors from loaded chunks propagate")
assert(tostring(err):find("my-chunk", 1, true), "debugName shows up in error positions: " .. tostring(err))

local bad_ok, bad_err = pcall(luau.load, "return +")
assert(not bad_ok and #tostring(bad_err) > 0, "a syntax error raises")
assert(not pcall(luau.compile, "local = 1"), "compile of a syntax error raises")
assert(not pcall(luau.load, 42 :: any), "a number is not source")

print("E2E PASS lune_luau")
process.exit(0)
