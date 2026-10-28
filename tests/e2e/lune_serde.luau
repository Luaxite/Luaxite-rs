local serde = require("@lune/serde")

local function same(a: any, b: any): boolean
	if type(a) ~= type(b) then
		return false
	end
	if type(a) ~= "table" then
		return a == b
	end
	for k, v in a do
		if not same(v, b[k]) then
			return false
		end
	end
	for k in b do
		if a[k] == nil then
			return false
		end
	end
	return true
end

local value = { name = "azalea", n = 42, pi = 3.5, ok = true, list = { 1, 2, 3 }, nested = { a = { b = "c" } } }

for _, format in { "json", "yaml", "toml" } do
	local text = serde.encode(format :: any, value)
	assert(type(text) == "string" and #text > 0, format .. " encode")
	assert(same(serde.decode(format :: any, text), value), format .. " round trip")
	assert(type(serde.encode(format :: any, value, true)) == "string", format .. " pretty")
end
assert(serde.encode("json", { a = 1 }) == '{"a":1}', "compact json")
assert(select(2, string.gsub(serde.encode("json", { a = 1, b = 2 }, true), "\n", "")) >= 3, "pretty json has lines")
assert(serde.decode("json", "[1,2,3]")[3] == 3, "json array")
assert(serde.decode("json", buffer.fromstring('{"b":true}')).b == true, "decode takes a buffer")
assert(serde.decode("jsonc", '{ /* c */ "a": 1, // x\n "b": 2 }').b == 2, "jsonc comments")
assert(serde.decode("yaml", "a: 1\nb:\n  - x\n  - y\n").b[2] == "y", "yaml")
assert(serde.decode("toml", 'a = 1\n[t]\nb = "x"\n').t.b == "x", "toml")
assert(not pcall(serde.decode, "json", "{ nope"), "bad json raises")
assert(not pcall(serde.encode, "nope" :: any, {}), "unknown format raises")
assert(not pcall(serde.encode, "json", { f = function() end }), "functions are not serializable")

local text = string.rep("luaxite lune ", 200)
for _, format in { "brotli", "gzip", "lz4", "zlib", "zstd" } do
	local packed = serde.compress(format :: any, text)
	assert(type(packed) == "string" and #packed < #text, format .. " shrinks repetitive text")
	assert(serde.decompress(format :: any, packed) == text, format .. " round trip")
	assert(serde.decompress(format :: any, buffer.fromstring(packed)) == text, format .. " decompress takes a buffer")
end
assert(serde.decompress("gzip", serde.compress("gzip", "")) == "", "empty input")
assert(not pcall(serde.decompress, "gzip", "not gzip data"), "garbage raises")

local abc = {
	md5 = "900150983cd24fb0d6963f7d28e17f72",
	sha1 = "a9993e364706816aba3e25717850c26c9cd0d89d",
	sha256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
}
for algo, expected in abc do
	assert(serde.hash(algo :: any, "abc") == expected, algo .. " of abc")
	assert(serde.hash(algo :: any, buffer.fromstring("abc")) == expected, algo .. " of a buffer")
end
assert(serde.hash("sha256", "") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "sha256 of nothing")
for _, algo in { "sha224", "sha384", "sha512", "sha3-256", "sha3-512", "blake3" } do
	local h = serde.hash(algo :: any, "abc")
	assert(type(h) == "string" and #h >= 56 and h:match("^%x+$"), algo .. " is a hex digest")
	assert(h ~= serde.hash(algo :: any, "abd"), algo .. " depends on the input")
end
assert(not pcall(serde.hash, "nope" :: any, "x"), "unknown algorithm raises")

assert(
	serde.hmac("sha256", "The quick brown fox jumps over the lazy dog", "key") == "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8",
	"hmac sha256"
)
assert(serde.hmac("sha1", "msg", "k1") ~= serde.hmac("sha1", "msg", "k2"), "hmac depends on the key")

print("E2E PASS lune_serde")
process.exit(0)
