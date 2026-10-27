-- e2e: async functions inside plain coroutine.wrap / coroutine.create threads (they used to never resume). Needs no server and starts no bot.
-- Prints "E2E PASS coroutine_async" when every check holds.
local task = require("@lune/task")
local fs = require("@lune/fs")

-- coroutine.wrap: the async call inside suspends the wrapped thread; the wrap function returns once the work is done
local t0 = os.clock()
local r = coroutine.wrap(function()
	task.wait(0.05)
	return "wrapped"
end)()
assert(r == "wrapped", "coroutine.wrap must return after the async call finished, got " .. tostring(r))

-- values pass through the wrap in both directions, and plain yields still work
local gen = coroutine.wrap(function(a)
	local b = coroutine.yield(a + 1)
	fs.isFile(".")
	local c = coroutine.yield(b + 1)
	return c + 1
end)
assert(gen(1) == 2, "first yield")
assert(gen(10) == 11, "second yield, after an async call")
assert(gen(20) == 21, "return value")

-- coroutine.create + coroutine.resume
local co = coroutine.create(function(x)
	local waited = task.wait(0.01)
	assert(type(waited) == "number", "task.wait result")
	return x * 2, "done"
end)
local ok, a, b = coroutine.resume(co, 21)
assert(ok and a == 42 and b == "done", "resume result after an async call: " .. tostring(ok) .. " " .. tostring(a))
assert(coroutine.status(co) == "dead", "finished coroutine is dead")

-- nested plain coroutines chain
local nested = coroutine.wrap(function()
	local inner = coroutine.wrap(function()
		task.wait(0.01)
		return "inner"
	end)
	return inner() .. "+outer"
end)()
assert(nested == "inner+outer", "nested coroutines: " .. tostring(nested))

-- errors still propagate
local eok, err = pcall(coroutine.wrap(function()
	task.wait(0.01)
	error("boom", 0)
end))
assert(not eok and err == "boom", "error through wrap: " .. tostring(err))
local rok, rerr = coroutine.resume(coroutine.create(function()
	task.wait(0.01)
	error("bang", 0)
end))
assert(rok == false and rerr == "bang", "error through resume: " .. tostring(rerr))

-- inside a task.spawn thread too
local done = false
task.spawn(function()
	local v = coroutine.wrap(function()
		task.wait(0.01)
		return 7
	end)()
	assert(v == 7, "wrap inside task.spawn")
	done = true
end)
for _ = 1, 200 do
	if done then
		break
	end
	task.wait(0.01)
end
assert(done, "task.spawn thread with a nested wrap never finished")

print("E2E PASS coroutine_async")
process.exit(0)
