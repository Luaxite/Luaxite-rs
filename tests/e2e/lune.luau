local serde = require("@lune/serde")
local regex = require("@lune/regex")
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local DateTime = require("@lune/datetime")

assert(require("@lune/serde") == serde, "require did not cache @lune/serde")
assert((require :: any)("@lune/SERDE") == serde, "@lune names should be case-insensitive")

assert(serde.decode("json", serde.encode("json", { a = 1 })).a == 1, "serde json round trip")
assert(regex.new("(\\d+)-(\\d+)"):isMatch("10-20"), "regex isMatch")
assert(not regex.new("(\\d+)-(\\d+)"):isMatch("10"), "regex isMatch (no match)")
assert(luau.load("return 1 + 1")() == 2, "luau.load")
assert(DateTime.now().unixTimestamp > 0, "datetime.now")

local path = "zenpel-e2e-lune.tmp"
fs.writeFile(path, "hello")
assert(fs.isFile(path), "fs.isFile after writeFile")
assert(fs.readFile(path) == "hello", "fs.readFile")
fs.removeFile(path)
assert(not fs.isFile(path), "fs.isFile after removeFile")

for _, name in { "roblox" } do
	local ok, err = pcall(require, "@lune/" .. name)
	assert(not ok and tostring(err):find("not supported", 1, true), `@lune/{name} should be reported as unsupported: {err}`)
end
local ok, err = pcall(require, "@lune/nope")
assert(not ok and tostring(err):find("not found", 1, true), `an unknown @lune module should be "not found": {err}`)

print("E2E PASS lune")
process.exit(0)
