--!nocheck
local task = require("@lune/task")
local fs = require("@lune/fs")

local log = {}
local function push(s)
	table.insert(log, s)
end

local function yield_until(cond)
	for _ = 1, 200 do
		if cond() then
			return
		end
		fs.isFile(".")
	end
	error("timed out waiting for a background thread")
end

assert(type(task.spawn) == "function" and type(task.defer) == "function" and type(task.cancel) == "function", "task functions")
assert(type(task.wait) == "function" and type(task.delay) == "function", "task.wait / task.delay exist")

local t = task.spawn(function(a, b)
	push("spawn:" .. a .. b)
end, "x", "y")
assert(type(t) == "thread", "spawn returns a thread")
assert(log[1] == "spawn:xy", "spawn must run the function at once")
assert(coroutine.status(t) == "dead", "a finished thread is dead")

local co = task.spawn(function()
	push("co1")
	coroutine.yield()
	push("co2")
end)
assert(log[2] == "co1" and #log == 2, "spawn runs up to the first manual yield")
assert(coroutine.status(co) == "suspended", "manual yield leaves the thread suspended")
coroutine.resume(co)
assert(log[3] == "co2", "the thread continues when resumed")

local given = coroutine.create(function(v)
	push("thread:" .. v)
end)
assert(task.spawn(given, "t") == given and log[4] == "thread:t", "spawn(thread, ...)")

local deferred = false
local dt = task.defer(function(v)
	deferred = v
end, "dv")
assert(type(dt) == "thread" and deferred == false, "defer must not run at once")
yield_until(function()
	return deferred ~= false
end)
assert(deferred == "dv", "defer passes its arguments and runs later")

local done = false
task.spawn(function()
	fs.isFile(".")
	fs.isFile(".")
	done = true
end)
assert(done == false, "the thread yielded inside an async call, it is not finished yet")
yield_until(function()
	return done
end)

local ticks = 0
local looping = task.spawn(function()
	while true do
		fs.isFile(".")
		ticks += 1
	end
end)
yield_until(function()
	return ticks >= 2
end)
task.cancel(looping)
assert(coroutine.status(looping) == "dead", "cancel closes the thread")
local seen = ticks
for _ = 1, 20 do
	fs.isFile(".")
end
assert(ticks == seen, "a cancelled thread must not run again")
task.cancel(looping)
task.cancel(t)

local elapsed = task.wait(0.05)
assert(type(elapsed) == "number" and elapsed >= 0.05, "wait returns >= the requested time")
assert(type(task.wait()) == "number", "wait() without an argument")

local ran = false
task.defer(function()
	ran = true
end)
assert(ran == false, "defer must not run before the yield")
local e0 = task.wait(0)
assert(ran == true and e0 > 0, "wait(0) must yield")

local order = {}
task.delay(0.12, function(v)
	table.insert(order, v)
end, "late")
task.delay(0.04, function(v)
	table.insert(order, v)
end, "early")
task.delay(0.08, coroutine.create(function(v)
	table.insert(order, v)
end), "thread")
assert(type(task.delay(0, function() end)) == "thread", "delay returns a thread")
assert(#order == 0, "delay must not run at once")
task.wait(0.4)
assert(#order == 3 and order[1] == "early" and order[2] == "thread" and order[3] == "late", "delay order: " .. table.concat(order, ","))

local fired = false
local dthr = task.delay(0.05, function()
	fired = true
end)
task.cancel(dthr)
assert(coroutine.status(dthr) == "dead", "cancel closes a delayed thread")
task.wait(0.2)
assert(fired == false, "a cancelled delay must not fire")

local fired2 = false
local parked = task.delay(0.15, function()
	fired2 = true
end)
task.wait(0.03)
assert(coroutine.status(parked) == "suspended", "a delay thread that is waiting is suspended")
task.cancel(parked)
assert(coroutine.status(parked) == "dead", "cancel closes a thread parked in wait")
task.wait(0.35)
assert(fired2 == false, "a delay cancelled while waiting must not fire")

for name, call in {
	spawn = function()
		return task.spawn(5)
	end,
	defer = function()
		return task.defer("x")
	end,
	delay = function()
		return task.delay(0.01, 5)
	end,
	delay_missing = function()
		return task.delay(0.01)
	end,
} do
	local ok, err = pcall(call)
	assert(not ok and string.find(tostring(err), "Expected thread or function", 1, true), name .. " must raise: " .. tostring(err))
end

local dthread = false
local given2 = coroutine.create(function(v)
	dthread = v
end)
assert(task.defer(given2, "dt") == given2 and dthread == false, "defer(thread, ...) must not run at once")
task.wait(0.02)
assert(dthread == "dt", "defer(thread, ...) runs it later with its arguments")
assert(task.defer(t) == t and task.spawn(t) == t, "spawn / defer of a dead thread is a no-op")

task.spawn(function()
	error("e2e-expected: spawn")
end)
task.defer(function()
	error("e2e-expected: defer")
end)
task.delay(0.01, function()
	error("e2e-expected: delay")
end)
task.spawn(function()
	fs.isFile(".")
	error("e2e-expected: after an async yield")
end)
local survived = false
task.defer(function()
	survived = true
end)
task.wait(0.1)
assert(survived == true, "other threads keep running after a thread errored")

local passed = coroutine.create(function() end)
assert(task.delay(0.01, passed) == passed, "delay returns the thread that was passed")
local made = task.delay(0.01, function() end)
assert(type(made) == "thread" and coroutine.status(made) == "suspended", "delay returns the thread made from the function")
task.wait(0.05)

task.cancel(task.delay(3600, function()
	error("e2e: a cancelled delay fired")
end))

local woke = false
local forever = task.spawn(function()
	task.wait(math.huge)
	woke = true
end)
task.wait(0.15)
assert(woke == false, "wait(math.huge) must not return")
assert(coroutine.status(forever) == "suspended", "wait(math.huge) leaves the thread parked")
task.cancel(forever)
assert(coroutine.status(forever) == "dead", "cancel closes a thread parked in wait(math.huge)")
assert(type(task.wait(0 / 0)) == "number" and type(task.wait(-1)) == "number", "NaN and negative waits just yield")

task.delay(0.3, function()
	print("E2E PASS lune_task")
	process.exit(0)
end)
