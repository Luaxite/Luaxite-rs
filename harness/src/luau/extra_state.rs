use mlua::Lua;

use super::{convert::lua_err, gen_client::LuaClient, gen_types::LuaPlayerInfo};

#[mlua::userdata_impl]
impl LuaClient {
    
    
    fn account(&self, lua: &Lua) -> mlua::Result<mlua::Table> {
        let a = self.client.account();
        let t = lua.create_table()?;
        t.set("username", a.username().to_string())?;
        t.set("uuid", a.uuid().to_string())?;
        Ok(t)
    }

    
    
    fn tab_list(&self) -> mlua::Result<Vec<LuaPlayerInfo>> {
        let mut v: Vec<_> = self
            .client
            .tab_list()
            .map_err(lua_err)?
            .into_values()
            .collect();
        v.sort_by(|a, b| a.profile.name.cmp(&b.profile.name));
        Ok(v.into_iter().map(LuaPlayerInfo).collect())
    }
}
