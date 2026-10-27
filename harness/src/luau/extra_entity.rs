use mlua::UserDataRef;

use super::{convert::lua_err, gen_client::LuaEntityRef};

#[mlua::userdata_impl]
impl LuaEntityRef {
    #[lua(meta, infallible)]
    fn __eq(&self, other: UserDataRef<LuaEntityRef>) -> bool {
        self.entity.id() == other.entity.id()
    }

    #[lua(meta)]
    fn __tostring(&self) -> mlua::Result<String> {
        Ok(format!("Entity({:?})", self.entity.id()))
    }
}

// luau[Entity]: --- Distance in blocks between the feet of this entity and another one.
// luau[Entity]: function distance_to(self, other: Entity): number
#[mlua::userdata_impl]
impl LuaEntityRef {
    fn distance_to(&self, other: UserDataRef<LuaEntityRef>) -> mlua::Result<f64> {
        let (a, b) = (
            self.entity.position().map_err(lua_err)?,
            other.entity.position().map_err(lua_err)?,
        );
        Ok(((a.x - b.x).powi(2) + (a.y - b.y).powi(2) + (a.z - b.z).powi(2)).sqrt())
    }
}
