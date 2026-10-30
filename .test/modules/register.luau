












--[[

Command struct:


local Module = {}

Module.Name string
Module.Desc string
Module.Author string?
Module.Commands Commands

type Commands = {
    Command: {
        Name: string
        Desc: string
        Usage: string
        Func: Function
    }
}

return Module
]]



local Commands = {}

--[[ REGISTER ]]

--[[ END REGISTER ]]

return Commands