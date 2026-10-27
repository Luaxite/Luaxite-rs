-- cargo run -- src/goals.luau   (joins the `address` given to azalea.join below)
-- Goal combinators and registries.
local bot = azalea.join { account = "GoalsBot", address = "localhost" }

bot:wait_for("spawn")

print(bot:registry_resolve("enchantment", "sharpness"))

-- Walk at least 20 blocks away from here, staying at this height (a goal.y the bot can never reach, like 64 on a flat world, makes the
-- pathfinder retry forever).
local here = bot:position()
local away = goal.inverse(goal.radius(here, 20))
bot:goto_goal(goal.all(away, goal.y(math.floor(here.y))))
