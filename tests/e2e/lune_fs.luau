-- e2e: @lune/fs (Lune's own crate on our Luau state). Needs no server. Prints "E2E PASS lune_fs".
local fs = require("@lune/fs")
local DateTime = require("@lune/datetime")

local root = "luaxite-e2e-fs.tmp"
if fs.isDir(root) then
	fs.removeDir(root)
end

fs.writeDir(root .. "/a/b")
assert(fs.isDir(root) and fs.isDir(root .. "/a/b") and not fs.isFile(root .. "/a/b"), "writeDir makes parents; isDir / isFile")

-- writeFile / readFile / strings and buffers
fs.writeFile(root .. "/one.txt", "hello")
assert(fs.readFile(root .. "/one.txt") == "hello", "readFile")
local buf = buffer.fromstring("bytes\0with\0nul")
fs.writeFile(root .. "/two.bin", buf)
assert(fs.readFile(root .. "/two.bin") == "bytes\0with\0nul", "buffers are written byte for byte")
fs.writeFile(root .. "/one.txt", "again")
assert(fs.readFile(root .. "/one.txt") == "again", "writeFile overwrites")

-- readDir lists names (files and directories), not paths
local names = fs.readDir(root)
table.sort(names)
assert(#names == 3 and names[1] == "a" and names[2] == "one.txt" and names[3] == "two.bin", "readDir: " .. table.concat(names, ","))

-- metadata
local m = fs.metadata(root .. "/one.txt")
assert(m.exists and m.kind == "file" and m.size == 5, "file metadata")
assert(m.permissions.readOnly == false, "permissions.readOnly")
assert(m.createdAt.unixTimestamp > 0 and m.modifiedAt.unixTimestamp > 0, "metadata timestamps are DateTime values")
assert(m.modifiedAt.unixTimestamp <= DateTime.now().unixTimestamp + 5, "modifiedAt is not in the future")
local d = fs.metadata(root .. "/a")
assert(d.exists and d.kind == "dir", "dir metadata")
local gone = fs.metadata(root .. "/missing")
assert(gone.exists == false and gone.kind == nil, "metadata of a missing path")

-- copy / move, with the overwrite rules
fs.copy(root .. "/one.txt", root .. "/copy.txt")
assert(fs.readFile(root .. "/copy.txt") == "again" and fs.isFile(root .. "/one.txt"), "copy keeps the source")
assert(not pcall(fs.copy, root .. "/one.txt", root .. "/copy.txt"), "copy onto an existing file raises")
fs.writeFile(root .. "/copy.txt", "different")
fs.copy(root .. "/one.txt", root .. "/copy.txt", true)
assert(fs.readFile(root .. "/copy.txt") == "again", "copy with overwrite = true")
fs.writeFile(root .. "/copy.txt", "different")
fs.copy(root .. "/one.txt", root .. "/copy.txt", { overwrite = true })
assert(fs.readFile(root .. "/copy.txt") == "again", "copy with { overwrite = true }")

fs.move(root .. "/copy.txt", root .. "/moved.txt")
assert(not fs.isFile(root .. "/copy.txt") and fs.readFile(root .. "/moved.txt") == "again", "move")
assert(not pcall(fs.move, root .. "/one.txt", root .. "/moved.txt"), "move onto an existing file raises")
fs.move(root .. "/one.txt", root .. "/moved.txt", true)
assert(not fs.isFile(root .. "/one.txt"), "move with overwrite")

-- directories copy recursively
fs.writeFile(root .. "/a/b/deep.txt", "deep")
fs.copy(root .. "/a", root .. "/a2")
assert(fs.readFile(root .. "/a2/b/deep.txt") == "deep", "directories copy recursively")

-- errors
assert(not pcall(fs.readFile, root .. "/nope.txt"), "readFile of a missing file raises")
assert(not pcall(fs.readDir, root .. "/nope"), "readDir of a missing dir raises")
assert(not pcall(fs.removeFile, root .. "/nope.txt"), "removeFile of a missing file raises")
assert(not pcall(fs.writeFile, root .. "/no/such/dir/x.txt", "x"), "writeFile without the parent dir raises")
assert(not pcall(fs.readFile, 42), "a number is not a path")

-- removing
fs.removeFile(root .. "/moved.txt")
assert(not fs.isFile(root .. "/moved.txt"), "removeFile")
fs.removeDir(root)
assert(not fs.isDir(root), "removeDir removes everything below")

print("E2E PASS lune_fs")
process.exit(0)
