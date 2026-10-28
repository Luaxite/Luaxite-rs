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
    
    
    fn block_at(&self, pos: LBlockPos) -> mlua::Result<Option<String>> {
        let world = self.client.world().map_err(lua_err)?;
        let state = world.read().get_block_state(pos.0);
        Ok(state.map(|state| BlockKind::from(state).to_str().to_owned()))
    }

    
    
    fn best_tool_in_hotbar_for_block(&self, block: String) -> mlua::Result<LBestTool> {
        self.best_tool(&block).map(LBestTool)
    }

    
    
    fn best_tool_for(&self, block: String) -> mlua::Result<Option<usize>> {
        let best = self.best_tool(&block)?;
        Ok((best.percentage_per_tick > 0.0).then_some(best.index))
    }
}
