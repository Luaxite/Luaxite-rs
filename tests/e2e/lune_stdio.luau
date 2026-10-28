local stdio = require("@lune/stdio")

assert(type(stdio.write) == "function" and type(stdio.ewrite) == "function" and type(stdio.format) == "function", "stdio functions")
assert(not pcall(function()
	stdio.nope = 1
end), "the module table is readonly")

assert(stdio.format("hello") == "hello", "a string is formatted raw")
local plain = stdio.format("a", 1, true, nil)
assert(plain == "a 1 true nil", "plain values: " .. plain)
assert(stdio.format({}) == "{ }", "an empty table")
assert(stdio.format(1, 2) == "1 2", "values are joined by a space")
assert(not string.find(plain, "\27", 1, true), "format never emits ANSI colors")

local flat = stdio.format({ name = "bob", age = 3 })
for _, part in { "name", "bob", "age", "3" } do
	assert(string.find(flat, part, 1, true), "table text has " .. part .. ": " .. flat)
end
assert(not string.find(flat, "\27", 1, true), "tables are not colored either")

local deep = { level1 = { level2 = { level3 = { level4 = { level5 = { leaf = "DEEPLEAF" } } } } }, shallow = "SHALLOW" }
local nested = stdio.format(deep)
assert(string.find(nested, "SHALLOW", 1, true), "a top-level value is shown: " .. nested)
assert(string.find(nested, "level1", 1, true) and string.find(nested, "level4", 1, true), "the first levels are shown: " .. nested)
assert(string.find(nested, "{ ... }", 1, true), "the cut-off table is shown as { ... }: " .. nested)
assert(not string.find(nested, "level5", 1, true) and not string.find(nested, "DEEPLEAF", 1, true), "values below depth 4 are cut off: " .. nested)

assert(stdio.write("stdio.write ok\n") == nil, "write returns nothing")
assert(stdio.ewrite("stdio.ewrite ok\n") == nil, "ewrite returns nothing")
assert(stdio.write("") == nil and stdio.ewrite("") == nil, "writing an empty string is fine")
assert(not pcall(stdio.write, {}), "write rejects a table")

local colors = { reset = 0, black = 30, red = 31, green = 32, yellow = 33, blue = 34, magenta = 35, purple = 35, cyan = 36, white = 37 }
for name, code in colors do
	assert(stdio.color(name) == "\27[" .. code .. "m", "color " .. name)
end
assert(stdio.style("reset") == "\27[0m" and stdio.style("bold") == "\27[1m" and stdio.style("dim") == "\27[2m", "style codes")
local ok, err = pcall(stdio.color, "e2e-expected-nope")
assert(not ok and string.find(tostring(err), "valid", 1, true), "unknown color raises: " .. tostring(err))
ok, err = pcall(stdio.style, "e2e-expected-nope")
assert(not ok and string.find(tostring(err), "valid", 1, true), "unknown style raises: " .. tostring(err))

assert(type(stdio.readLine) == "function" and type(stdio.readToEnd) == "function", "stdin functions")
assert(stdio.readLine() == "", "readLine is empty at EOF")
assert(stdio.readToEnd() == "", "readToEnd is empty at EOF")

assert(type(stdio.prompt) == "function", "prompt is a function")
ok, err = pcall(stdio.prompt, "e2e-expected-nope", "msg")
assert(not ok and string.find(tostring(err), "multiselect", 1, true), "unknown kind lists the valid kinds: " .. tostring(err))
ok, err = pcall(stdio.prompt, "confirm")
assert(not ok and string.find(tostring(err), "message", 1, true), "confirm without message raises: " .. tostring(err))
ok, err = pcall(stdio.prompt, "select", "pick")
assert(not ok and string.find(tostring(err), "options", 1, true), "select without options raises: " .. tostring(err))
ok, err = pcall(stdio.prompt, "multiselect", "pick", {})
assert(not ok and string.find(tostring(err), "options", 1, true), "multiselect with an empty table raises: " .. tostring(err))

print("E2E PASS lune_stdio")
process.exit(0)
