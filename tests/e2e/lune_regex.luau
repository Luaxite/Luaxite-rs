local regex = require("@lune/regex")

local re = regex.new("(\\d+)-(\\d+)")
assert(re:isMatch("10-20") and not re:isMatch("10") and not re:isMatch(""), "isMatch")

local m = re:find("a 10-20 b 30-40")
assert(m ~= nil and m.text == "10-20" and m.len == 5, "find text / len")
assert(m.start == 3 and m.finish == 7, "find start / finish (1-based, inclusive): " .. tostring(m.start) .. ", " .. tostring(m.finish))
assert(re:find("nothing here") == nil, "no match is nil")

local caps = re:captures("x 10-20 y")
assert(caps ~= nil, "captures")
assert(caps:get(1).text == "10" and caps:get(2).text == "20", "numbered groups")
assert(caps:get(0).text == "10-20", "group 0 is the whole match")
assert(caps:get(3) == nil, "missing group is nil")
assert(caps:format("$2-$1") == "20-10", "format")
assert(re:captures("nope") == nil, "captures: no match is nil")

local named = regex.new("(?P<key>\\w+)=(?P<value>\\w+)")
local nc = named:captures("color=red")
assert(nc:group("key").text == "color" and nc:group("value").text == "red", "named groups")
assert(nc:group("nope") == nil, "unknown group is nil")
assert(nc:format("${value}:${key}") == "red:color", "format with names")

local digits = regex.new("\\d+")
local parts = digits:split("a1b22c333d")
assert(#parts == 4 and parts[1] == "a" and parts[2] == "b" and parts[3] == "c" and parts[4] == "d", "split")
assert(#regex.new(","):split("") == 1, "split of an empty string")
assert(digits:replace("a1b22c", "#") == "a#b22c", "replace replaces the first match")
assert(digits:replaceAll("a1b22c", "#") == "a#b#c", "replaceAll")
assert(regex.new("(\\w+) (\\w+)"):replace("hello world", "$2 $1") == "world hello", "replace with group references")
assert(digits:replaceAll("none", "#") == "none", "replaceAll without matches")

assert(regex.new("^abc$"):isMatch("abc") and not regex.new("^abc$"):isMatch("xabc"), "anchors")
assert(regex.new("(?i)AZALEA"):isMatch("azalea"), "case-insensitive flag")
assert(regex.new("é+"):find("caféé").text == "éé", "unicode")

local a, b = regex.new("a"), regex.new("b")
assert(a:isMatch("a") and not a:isMatch("b") and b:isMatch("b"), "independent patterns")

assert(not pcall(regex.new, "("), "an invalid pattern raises")
assert(not pcall(regex.new, {} :: any), "a table is not a pattern")
assert(not pcall(re.isMatch, re, {} :: any), "a table is not text")

print("E2E PASS lune_regex")
process.exit(0)
