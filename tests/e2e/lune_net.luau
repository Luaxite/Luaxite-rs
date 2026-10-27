--!nocheck
-- e2e: @lune/net, (urlEncode / urlDecode / tcp.connect errors / request errors). Needs no server; the tcp round trip and request / serve come in later slices.
-- Prints "E2E PASS lune_net" when every check holds.
local net = require("@lune/net")

assert(not pcall(function()
	net.nope = 1
end), "the module table is readonly")
assert(type(net.urlEncode) == "function" and type(net.urlDecode) == "function", "url helpers")
assert(type(net.tcp) == "table" and type(net.tcp.connect) == "function", "tcp.connect")
assert(type(net.http) == "table" and type(net.ws) == "table", "http and ws submodules")

-- urlEncode: `A-Za-z0-9-_.~` stay, the rest is %XX (uppercase)
assert(net.urlEncode("hello world!") == "hello%20world%21", "space and !")
assert(net.urlEncode("a-b_c.d~E9") == "a-b_c.d~E9", "unreserved characters stay")
assert(net.urlEncode("a/b?c=d&e") == "a%2Fb%3Fc%3Dd%26e", "reserved characters are escaped")
assert(net.urlEncode("é") == "%C3%A9", "utf-8 bytes")
assert(net.urlEncode("") == "", "empty")
assert(net.urlEncode("\0\255", true) == "%00%FF", "asBinary encodes raw bytes")
assert(not pcall(net.urlEncode, "\255"), "non-binary encode rejects invalid UTF-8")

-- urlDecode
assert(net.urlDecode("hello%20world%21") == "hello world!", "decode")
assert(net.urlDecode("%C3%A9") == "é", "decode utf-8")
assert(net.urlDecode("a+b") == "a+b", "+ stays a plus")
assert(net.urlDecode("100%") == "100%" and net.urlDecode("%zz%4") == "%zz%4", "invalid escapes stay as they are")
assert(net.urlDecode("%c3%a9") == "é", "lowercase hex is accepted")
assert(net.urlDecode("%00%FF", true) == "\0\255", "asBinary decodes to raw bytes")
assert(not pcall(net.urlDecode, "%FF"), "non-binary decode rejects invalid UTF-8")
local sample = "key=va lue&x=ü/~"
assert(net.urlDecode(net.urlEncode(sample)) == sample, "round trip")
local raw = "\0\1\2\254\255 %"
assert(net.urlDecode(net.urlEncode(raw, true), true) == raw, "binary round trip")

-- tcp.connect: bad calls raise (pcall keeps the script going; "e2e-expected" marks the text for run.sh)
local ok, err = pcall(net.tcp.connect, "127.0.0.1", 1) -- nothing listens on port 1
assert(not ok and string.find(tostring(err), "net.tcp.connect", 1, true), "connection refused raises: " .. tostring(err))
ok, err = pcall(net.tcp.connect, "127.0.0.1", 80, true)
assert(not ok and string.find(tostring(err), "not implemented yet: tls", 1, true), "tls is not implemented yet: " .. tostring(err))
ok, err = pcall(net.tcp.connect, "127.0.0.1", 80, { tls = true })
assert(not ok and string.find(tostring(err), "tls", 1, true), "tls in the config table")
ok = pcall(net.tcp.connect, "127.0.0.1", 80, "e2e-expected-nope")
assert(not ok, "a bad config raises")

-- request: only argument / url errors here (no network in the e2e run); the real request goes to our own `serve` in a later slice
assert(type(net.request) == "function" and type(net.http.request) == "function", "request and http.request")
ok, err = pcall(net.request, "e2e-expected not a url")
assert(not ok and string.find(tostring(err), "net.request", 1, true), "a bad url raises: " .. tostring(err))
ok, err = pcall(net.request, {})
assert(not ok and string.find(tostring(err), "url", 1, true), "a config without url raises: " .. tostring(err))
ok = pcall(net.request, 42)
assert(not ok, "a number is not a request")
ok, err = pcall(net.request, { url = "http://127.0.0.1/", method = "e2e expected bad method" })
assert(not ok and string.find(tostring(err), "method", 1, true), "a bad method raises: " .. tostring(err))
ok = pcall(net.http.request, { url = "http://127.0.0.1/", headers = { a = 1 } })
assert(not ok, "headers must map strings to strings")
-- nothing listens on port 1: a refused connection is an error, not a crash
ok, err = pcall(net.request, "http://127.0.0.1:1/")
assert(not ok and string.find(tostring(err), "net.request", 1, true), "a refused connection raises: " .. tostring(err))

-- socket: bad / refused urls raise (the real round trip is against our own `serve`, a later slice)
assert(type(net.socket) == "function" and type(net.ws.connect) == "function", "socket and ws.connect")
ok, err = pcall(net.socket, "e2e-expected not a url")
assert(not ok and string.find(tostring(err), "net.socket", 1, true), "a bad socket url raises: " .. tostring(err))
ok, err = pcall(net.ws.connect, "ws://127.0.0.1:1") -- nothing listens on port 1
assert(not ok and string.find(tostring(err), "net.socket", 1, true), "a refused websocket raises: " .. tostring(err))
ok = pcall(net.socket, 42)
assert(not ok, "a number is not a url")

-- serve (http): our own server, request / tcp round trips against it
assert(type(net.serve) == "function" and type(net.http.serve) == "function", "serve and http.serve")
ok, err = pcall(net.serve, 18081, 42)
assert(not ok and string.find(tostring(err), "net.serve", 1, true), "serve needs a function or a table: " .. tostring(err))
ok, err = pcall(net.serve, 18081, {})
assert(not ok and string.find(tostring(err), "handleRequest", 1, true), "serve needs handleRequest: " .. tostring(err))

local seen
local server = net.serve(18080, {
	handleRequest = function(req)
		seen = req
		if req.path == "/json" then
			return { status = 201, headers = { ["X-Test"] = "yes" }, body = "created:" .. req.method .. ":" .. req.body }
		elseif req.path == "/boom" then
			error("e2e-expected handler error")
		end
		return "hello"
	end,
})
assert(server.ip == "127.0.0.1" and server.port == 18080, "handle ip/port")

local r = net.request("http://127.0.0.1:18080/?a=1&b=x%20y")
assert(r.ok and r.statusCode == 200 and r.body == "hello", "plain string reply")
assert(r.statusMessage == "OK", "statusMessage of a 200: " .. tostring(r.statusMessage))
assert(seen.method == "GET" and seen.path == "/" and seen.query.a == "1" and seen.query.b == "x y", "request fields")
assert(seen.ip == "127.0.0.1" and type(seen.port) == "number" and type(seen.headers) == "table" and seen.body == "", "ip/port/headers/body")

r = net.request({ url = "http://127.0.0.1:18080/json", method = "POST", body = "ping" })
assert(r.statusCode == 201 and r.headers["x-test"] == "yes" and r.body == "created:POST:ping", "table reply")
assert(r.statusMessage == "Created", "statusMessage of a 201: " .. tostring(r.statusMessage))

r = net.http.request("http://127.0.0.1:18080/boom")
assert(not r.ok and r.statusCode == 500, "a raising handler is a 500")
assert(r.statusMessage == "Internal Server Error", "statusMessage of a 500: " .. tostring(r.statusMessage))

local c = net.tcp.connect("127.0.0.1", 18080)
assert(c.remoteIp == "127.0.0.1" and c.remotePort == 18080, "tcp remote address: " .. tostring(c.remoteIp) .. ":" .. tostring(c.remotePort))
assert(c.localIp == "127.0.0.1" and type(c.localPort) == "number" and c.localPort ~= 18080, "tcp local address")
c:write("GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
local raw = ""
repeat
	local chunk = c:read()
	raw ..= chunk
until chunk == ""
assert(string.sub(raw, 1, 12) == "HTTP/1.1 200", "raw status line: " .. string.sub(raw, 1, 20))
c:close()

server.stop()
server.stop() -- twice is fine

-- serve (websocket): our own `socket` against our own `serve`
local wsServer = net.serve(18082, {
	handleRequest = function()
		return "plain"
	end,
	handleWebSocket = function(socket)
		while true do
			local m = socket:next()
			if m == nil then
				break
			end
			if m == "bye" then
				socket:close(4000)
				break
			end
			socket:send("echo:" .. m)
		end
	end,
})
local s = net.socket("ws://127.0.0.1:18082")
assert(s.closeCode == nil, "open socket has no closeCode")
s:send("hi")
assert(s:next() == "echo:hi", "text echo")
s:send("bin", true)
assert(s:next() == "echo:bin", "binary in, text out")
s:close()
assert(s.closeCode == 1000, "client close code")
assert(s:next() == nil, "next after close is nil")
ok = pcall(s.send, s, "late")
assert(not ok, "send after close raises")
s:close() -- twice is fine

local s2 = net.ws.connect("ws://127.0.0.1:18082")
s2:send("bye")
assert(s2:next() == nil, "server close ends next")
assert(s2.closeCode == 4000, "peer close code: " .. tostring(s2.closeCode))
assert(net.request("http://127.0.0.1:18082/").body == "plain", "plain requests still reach handleRequest")
wsServer.stop()

-- query decoding: `+` is a space, `%2B` a plus; the client's own query encoder round-trips
local task = require("@lune/task")
local qSeen
local qServer = net.serve(0, function(req)
	qSeen = req
	return "q"
end)
assert(qServer.port > 0 and qServer.port ~= 0, "serve(0) reports the real bound port: " .. tostring(qServer.port))
net.request("http://127.0.0.1:" .. qServer.port .. "/?q=a+b&r=a%2Bb")
assert(qSeen.query.q == "a b" and qSeen.query.r == "a+b", "+ is a space in a query: " .. tostring(qSeen.query.q) .. "|" .. tostring(qSeen.query.r))
net.request({ url = "http://127.0.0.1:" .. qServer.port .. "/", query = { s = "x y+z" } })
assert(qSeen.query.s == "x y+z", "client query round trip: " .. tostring(qSeen.query.s))
qServer.stop()

-- an abruptly closed client ends `socket:next()` with nil instead of raising
local abrupt = nil
local abruptServer = net.serve(0, {
	handleWebSocket = function(socket)
		local okNext, m = pcall(socket.next, socket)
		abrupt = okNext and m == nil
	end,
})
local raw = net.tcp.connect("127.0.0.1", abruptServer.port)
raw:write(
	"GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
		.. "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
)
local head = ""
repeat
	head ..= raw:read()
until string.find(head, "\r\n\r\n", 1, true)
raw:close() -- no close frame
for _ = 1, 20 do
	if abrupt ~= nil then
		break
	end
	task.wait(0.1)
end
assert(abrupt == true, "next() after an abrupt disconnect returns nil, got: " .. tostring(abrupt))
abruptServer.stop()

-- a huge read size must not abort the process
local bigServer = net.serve(0, function()
	return "ok"
end)
local bigConn = net.tcp.connect("127.0.0.1", bigServer.port)
bigConn:write("GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
local bigFirst = bigConn:read(2 ^ 40)
assert(string.sub(bigFirst, 1, 12) == "HTTP/1.1 200", "read(2^40) returns the available bytes: " .. string.sub(bigFirst, 1, 20))
bigConn:close()
bigServer.stop()

-- options.timeout: absent = a 120 s default, 0 = no limit, a negative value raises, a short one times out (the server below answers late)
local tServer = net.serve(0, function(req)
	if req.path == "/slow" then
		task.wait(1.5)
	end
	return "timeout-ok"
end)
local tUrl = "http://127.0.0.1:" .. tServer.port
assert(net.request(tUrl .. "/").body == "timeout-ok", "request without options.timeout works (default limit)")
assert(net.request({ url = tUrl .. "/", options = { decompress = true } }).body == "timeout-ok", "options without timeout works")
assert(net.request({ url = tUrl .. "/", options = { timeout = 0 } }).body == "timeout-ok", "timeout = 0 removes the limit and the request works")
assert(net.request({ url = tUrl .. "/", options = { timeout = 5 } }).body == "timeout-ok", "timeout = 5 works")
ok, err = pcall(net.request, { url = tUrl .. "/", options = { timeout = -1 } })
assert(not ok and string.find(tostring(err), "options.timeout must be a positive number of seconds", 1, true), "negative timeout raises: " .. tostring(err))
ok, err = pcall(net.request, { url = tUrl .. "/slow", options = { timeout = 0.3 } })
assert(not ok and string.find(tostring(err), "net.request: timed out", 1, true), "a short timeout still fires: " .. tostring(err))
tServer.stop()

print("E2E PASS lune_net")
process.exit(0)
