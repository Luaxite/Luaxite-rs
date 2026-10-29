print("util loading")
local M = { name = "util" }
M.nested = require("./sub/deep")
function M.double(n) return n * 2 end
return M
