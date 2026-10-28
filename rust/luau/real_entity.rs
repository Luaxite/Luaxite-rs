use super::{convert::lua_err, gen_client::LuaEntityRef};

#[mlua::userdata_impl]
impl LuaEntityRef {
    // luau[Entity]: --- The entity type as its registry name, like "minecraft:zombie" (the form `bot:nearby_entities(kind)` takes).
    // luau[Entity]: function kind(self): string
    fn kind(&self) -> mlua::Result<String> {
        Ok(self.entity.kind().map_err(lua_err)?.to_str().to_owned())
    }

    // luau[Entity]: --- The name of the world (dimension) the entity is in, like "minecraft:overworld"; compare it with `bot:world_name()`.
    // luau[Entity]: function world_name(self): string
    fn world_name(&self) -> mlua::Result<String> {
        Ok(self.entity.world_name().map_err(lua_err)?.to_string())
    }
}
