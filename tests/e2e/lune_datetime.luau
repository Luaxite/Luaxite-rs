-- e2e: @lune/datetime. Needs no server. Prints "E2E PASS lune_datetime".
local DateTime = require("@lune/datetime")

local Y2K = 946684800 -- 2000-01-01T00:00:00Z

local epoch = DateTime.fromUnixTimestamp(0)
assert(epoch.unixTimestamp == 0 and epoch.unixTimestampMillis == 0, "epoch")
assert(epoch:toIsoDate() == "1970-01-01T00:00:00+00:00", "toIsoDate: " .. epoch:toIsoDate())

local y2k = DateTime.fromIsoDate("2000-01-01T00:00:00Z")
assert(y2k.unixTimestamp == Y2K, "fromIsoDate")
assert(DateTime.fromIsoDate("2000-01-01T01:00:00+01:00").unixTimestamp == Y2K, "fromIsoDate with an offset")

-- fractional seconds are milliseconds
local frac = DateTime.fromUnixTimestamp(1.5)
assert(frac.unixTimestampMillis == 1500 and frac.unixTimestamp == 1, "unixTimestamp is whole seconds, millis are exact")

-- toUniversalTime / fromUniversalTime
local v = y2k:toUniversalTime()
assert(v.year == 2000 and v.month == 1 and v.day == 1 and v.hour == 0 and v.minute == 0 and v.second == 0 and v.millisecond == 0, "toUniversalTime")
local built = DateTime.fromUniversalTime({ year = 2024, month = 2, day = 29, hour = 12, minute = 30, second = 15, millisecond = 250 })
assert(built:toUniversalTime().day == 29 and built:toUniversalTime().millisecond == 250, "fromUniversalTime (leap day)")
assert(DateTime.fromUniversalTime({ year = 2000, month = 1, day = 1, hour = 0, minute = 0, second = 0 }).unixTimestamp == Y2K, "fromUniversalTime without millisecond")
assert(not pcall(DateTime.fromUniversalTime, { year = 2000, month = 13, day = 1, hour = 0, minute = 0, second = 0 }), "month 13 raises")

-- local time round trips whatever the time zone is
local lt = y2k:toLocalTime()
assert(DateTime.fromLocalTime(lt).unixTimestamp == Y2K, "local time round trip")

-- formatting
assert(y2k:formatUniversalTime("%Y-%m-%d %H:%M:%S") == "2000-01-01 00:00:00", "formatUniversalTime")
assert(y2k:formatUniversalTime("%B", "en") == "January", "month name in English")
assert(y2k:formatUniversalTime("%B", "de") == "Januar", "month name in German")
assert(type(y2k:formatLocalTime("%Y")) == "string", "formatLocalTime")
assert(type(y2k:formatUniversalTime()) == "string", "default format")

-- RFC 3339 / RFC 2822
assert(DateTime.fromRfc3339("2000-01-01T00:00:00+00:00").unixTimestamp == Y2K, "fromRfc3339")
assert(DateTime.fromRfc3339(y2k:toRfc3339()).unixTimestamp == Y2K, "toRfc3339 round trip")
assert(DateTime.fromRfc2822("Sat, 01 Jan 2000 00:00:00 +0000").unixTimestamp == Y2K, "fromRfc2822")
assert(DateTime.fromRfc2822(y2k:toRfc2822()).unixTimestamp == Y2K, "toRfc2822 round trip")

-- now
local now = DateTime.now()
assert(math.abs(now.unixTimestamp - os.time()) <= 2, "now matches os.time")
assert(now.unixTimestampMillis // 1000 == now.unixTimestamp, "millis and seconds agree")

-- errors
assert(not pcall(DateTime.fromIsoDate, "not a date"), "bad iso date raises")
assert(not pcall(DateTime.fromRfc3339, "2000-01-01"), "bad rfc3339 raises")
assert(not pcall(DateTime.fromRfc2822, "yesterday"), "bad rfc2822 raises")
assert(not pcall(DateTime.fromUnixTimestamp, "x" :: any), "a string is not a timestamp")

print("E2E PASS lune_datetime")
process.exit(0)
