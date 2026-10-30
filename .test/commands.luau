local Commands = require("./modules/register")

local Module = {}

function Module:Parse(command: string): {Name: string, Args: {string}}
    local parts = command:split(" ")
    local name = parts[1]
    local args = {}
    
    for i = 2, #parts do
        table.insert(args, parts[i])
    end
    
    return {
        Name = name,
        Args = args
    }
end

function Module:ExecuteCommand(command: string): any
    local parsed = self:Parse(command)
    local cmd = Commands[parsed.Name]
    if cmd then
        return pcall(cmd.Func, unpack(parsed.Args))
    else
        return false, "Command not found: " .. parsed.Name
    end
end

return Module