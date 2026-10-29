print("deep loading")
local sibling = require("./sibling")
local up = require("../util_data")
return { name = "deep", sibling = sibling.name, up = up.value }
