local bot = azalea.join { account = "GoalsBot", address = "localhost" }

bot:wait_for("spawn")

print(bot:registry_resolve("enchantment", "sharpness"))

local here = bot:position()
local away = goal.inverse(goal.radius(here, 20))
bot:goto_goal(goal.all(away, goal.y(math.floor(here.y))))
