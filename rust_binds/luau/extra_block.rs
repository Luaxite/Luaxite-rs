use azalea::{auto_tool::BestToolResult, block::BlockState, registry::builtin::BlockKind};
use mlua::{IntoLua, Lua, Value};

use super::{
    convert::{LBlockPos, lua_err},
    gen_client::LuaClient,
};

pub(super) fn block_state_named(name: &str) -> mlua::Result<BlockState> {
    let kind: BlockKind = name
        .parse()
        .map_err(|_| mlua::Error::runtime(format!("unknown block '{name}'")))?;
    Ok(BlockState::from(kind))
}

struct LBestTool(BestToolResult);

impl IntoLua for LBestTool {
    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {
        let t = lua.create_table()?;
        t.set("slot", self.0.index)?;
        t.set("percentage_per_tick", self.0.percentage_per_tick)?;
        Ok(Value::Table(t))
    }
}

impl LuaClient {
    fn best_tool(&self, block: &str) -> mlua::Result<BestToolResult> {
        let state = block_state_named(block)?;
        self.client
            .best_tool_in_hotbar_for_block(state)
            .map_err(lua_err)
    }
}

#[mlua::userdata_impl]
impl LuaClient {
    // luau[Bot]: --- The block at `pos` as a name like "minecraft:stone" ("minecraft:air" for air), or nil when that position isn't in a loaded chunk. Reads the loaded world and never yields.
    // luau[Bot]: function block_at(self, pos: BlockPos): string?
    fn block_at(&self, pos: LBlockPos) -> mlua::Result<Option<String>> {
        let world = self.client.world().map_err(lua_err)?;
        let state = world.read().get_block_state(pos.0);
        Ok(state.map(|state| BlockKind::from(state).to_str().to_owned()))
    }

    // luau[Bot]: --- Which hotbar slot mines `block` (a name like "stone" or "minecraft:stone") fastest. `slot` is 0-based, as `set_selected_hotbar_slot` takes it; `percentage_per_tick` is the mining progress per tick with that slot (0 when the block can't be mined, like water or bedrock). Unknown names are an error.
    // luau[Bot]: function best_tool_in_hotbar_for_block(self, block: string): { slot: number, percentage_per_tick: number }
    fn best_tool_in_hotbar_for_block(&self, block: String) -> mlua::Result<LBestTool> {
        self.best_tool(&block).map(LBestTool)
    }

    // luau[Bot]: --- The hotbar slot (0-based, for `set_selected_hotbar_slot`) that mines `block` fastest, or nil when no slot can mine it (water, lava, bedrock). Unknown names are an error.
    // luau[Bot]: function best_tool_for(self, block: string): number?
    fn best_tool_for(&self, block: String) -> mlua::Result<Option<usize>> {
        let best = self.best_tool(&block)?;
        Ok((best.percentage_per_tick > 0.0).then_some(best.index))
    }
}
