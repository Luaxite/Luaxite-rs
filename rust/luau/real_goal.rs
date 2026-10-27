use std::{fmt, sync::Arc};

use azalea::{
    BlockPos,
    pathfinder::{
        PathfinderClientExt as _,
        goals::{
            AndGoal, AndGoals, BlockPosGoal, Goal, InverseGoal, OrGoal, OrGoals, RadiusGoal,
            ReachBlockPosGoal, XZGoal, YGoal,
        },
    },
};
use mlua::{AnyUserData, Lua, UserData, Variadic};

use super::{
    convert::{LBlockPos, LPathfinderOpts, LVec3, lua_err},
    gen_client::LuaClient,
};

#[derive(Clone)]
pub struct DynGoal(Arc<dyn Goal>);

impl DynGoal {
    fn new(goal: impl Goal + 'static) -> Self {
        DynGoal(Arc::new(goal))
    }
}

impl fmt::Debug for DynGoal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl Goal for DynGoal {
    fn heuristic(&self, n: BlockPos) -> f32 {
        self.0.heuristic(n)
    }
    fn success(&self, n: BlockPos) -> bool {
        self.0.success(n)
    }
}

#[derive(UserData)]
pub struct LuaGoal {
    #[lua(skip)]
    pub goal: DynGoal,
}

#[mlua::userdata_impl]
impl LuaGoal {
    // luau[Goal]: --- The goal as text (azalea's debug form), e.g. for printing while debugging.
    // luau[Goal]: function describe(self): string
    fn describe(&self) -> mlua::Result<String> {
        Ok(format!("{:?}", self.goal))
    }
}

fn block_coord(n: f64) -> mlua::Result<i32> {
    let f = n.floor();
    if f.is_nan() || f < i32::MIN as f64 || f > i32::MAX as f64 {
        return Err(lua_err(format!(
            "goal: {n} is not a usable block coordinate"
        )));
    }
    Ok(f as i32)
}

fn goal_of(value: &AnyUserData) -> mlua::Result<DynGoal> {
    let goal = value
        .borrow::<LuaGoal>()
        .map_err(|_| lua_err("expected a Goal (made by `goal.block(..)`, `goal.all(..)`, ...)"))?;
    Ok(goal.goal.clone())
}

fn goals_of(values: Variadic<AnyUserData>, what: &str) -> mlua::Result<Vec<DynGoal>> {
    if values.is_empty() {
        return Err(lua_err(format!("{what} needs at least one goal")));
    }
    values.iter().map(goal_of).collect()
}

fn made(goal: impl Goal + 'static) -> LuaGoal {
    LuaGoal {
        goal: DynGoal::new(goal),
    }
}

pub fn install(lua: &Lua) -> mlua::Result<()> {
    let t = lua.create_table()?;

    // luau[GoalLib]: --- Goal: stand on this block.
    // luau[GoalLib]: block: (pos: BlockPos) -> Goal
    t.set(
        "block",
        lua.create_function(|_, pos: LBlockPos| Ok(made(BlockPosGoal(pos.0))))?,
    )?;

    // luau[GoalLib]: --- Goal: reach this x and z, at any height.
    // luau[GoalLib]: xz: (x: number, z: number) -> Goal
    t.set(
        "xz",
        lua.create_function(|_, (x, z): (f64, f64)| {
            Ok(made(XZGoal {
                x: block_coord(x)?,
                z: block_coord(z)?,
            }))
        })?,
    )?;

    // luau[GoalLib]: --- Goal: reach this height (y), anywhere.
    // luau[GoalLib]: y: (y: number) -> Goal
    t.set(
        "y",
        lua.create_function(|_, y: f64| Ok(made(YGoal { y: block_coord(y)? })))?,
    )?;

    // luau[GoalLib]: --- Goal: get within `radius` blocks of `pos`.
    // luau[GoalLib]: radius: (pos: Vec3, radius: number) -> Goal
    t.set(
        "radius",
        lua.create_function(|_, (pos, radius): (LVec3, f32)| {
            Ok(made(RadiusGoal { pos: pos.0, radius }))
        })?,
    )?;

    // luau[GoalLib]: --- Goal reached when every given goal is reached at once (at least one goal).
    // luau[GoalLib]: all: (...Goal) -> Goal
    t.set(
        "all",
        lua.create_function(|_, goals: Variadic<AnyUserData>| {
            let mut goals = goals_of(goals, "goal.all")?;
            Ok(if goals.len() == 2 {
                let b = goals.pop().unwrap();
                let a = goals.pop().unwrap();
                made(AndGoal(a, b))
            } else {
                made(AndGoals(goals))
            })
        })?,
    )?;

    // luau[GoalLib]: --- Goal reached when any one of the given goals is reached (at least one goal).
    // luau[GoalLib]: any: (...Goal) -> Goal
    t.set(
        "any",
        lua.create_function(|_, goals: Variadic<AnyUserData>| {
            let mut goals = goals_of(goals, "goal.any")?;
            Ok(if goals.len() == 2 {
                let b = goals.pop().unwrap();
                let a = goals.pop().unwrap();
                made(OrGoal(a, b))
            } else {
                made(OrGoals(goals))
            })
        })?,
    )?;

    // luau[GoalLib]: --- Goal reached everywhere the given goal is not (e.g. "get away from this block").
    // luau[GoalLib]: inverse: (goal: Goal) -> Goal
    t.set(
        "inverse",
        lua.create_function(|_, goal: AnyUserData| Ok(made(InverseGoal(goal_of(&goal)?))))?,
    )?;

    lua.globals().set("goal", t)
}

#[mlua::userdata_impl]
impl LuaClient {
    // luau[Bot]: --- Yields until the pathfinder has reached `goal` (see the `goal` functions) or pathfinding is canceled.
    // luau[Bot]: function goto_goal(self, goal: Goal, opts: PathfinderOpts?): ()
    async fn goto_goal(
        &self,
        goal: AnyUserData,
        opts: Option<LPathfinderOpts>,
    ) -> mlua::Result<()> {
        let goal = goal_of(&goal)?;
        match opts {
            Some(opts) => self.client.goto_with_opts(goal, opts.0).await,
            None => self.client.goto(goal).await,
        }
        Ok(())
    }

    // luau[Bot]: --- Start pathfinding to `goal` and return at once (it does not wait; see `is_goto_target_reached`).
    // luau[Bot]: function start_goto_goal(self, goal: Goal, opts: PathfinderOpts?): ()
    fn start_goto_goal(
        &self,
        goal: AnyUserData,
        opts: Option<LPathfinderOpts>,
    ) -> mlua::Result<()> {
        let goal = goal_of(&goal)?;
        match opts {
            Some(opts) => self.client.start_goto_with_opts(goal, opts.0),
            None => self.client.start_goto(goal),
        }
        Ok(())
    }

    // luau[Bot]: --- Goal: be able to reach the block at `pos` (stand next to it, or see it and hit it from within `distance` blocks, default azalea's reach). Needs the world to be loaded.
    // luau[Bot]: function reach_goal(self, pos: BlockPos, distance: number?): Goal
    fn reach_goal(&self, pos: LBlockPos, distance: Option<f64>) -> mlua::Result<LuaGoal> {
        if let Some(d) = distance {
            if !d.is_finite() || d <= 0.0 {
                return Err(lua_err(format!(
                    "reach_goal: distance must be a positive number, got {d}"
                )));
            }
        }
        let world = self.client.world().map_err(lua_err)?;
        let chunks = world.read().chunks.clone();
        Ok(match distance {
            Some(d) => made(ReachBlockPosGoal::new_with_distance(pos.0, d, chunks)),
            None => made(ReachBlockPosGoal::new(pos.0, chunks)),
        })
    }
}
