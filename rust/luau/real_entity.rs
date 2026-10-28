use super::{convert::lua_err, gen_client::LuaEntityRef};

#[mlua::userdata_impl]
impl LuaEntityRef {
    
    
    fn kind(&self) -> mlua::Result<String> {
        Ok(self.entity.kind().map_err(lua_err)?.to_str().to_owned())
    }

    
    
    fn world_name(&self) -> mlua::Result<String> {
        Ok(self.entity.world_name().map_err(lua_err)?.to_string())
    }
}
