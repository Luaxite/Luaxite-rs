use azalea::{entity::EntityKindComponent, registry::builtin::EntityKind};

use super::{
    convert::lua_err,
    gen_client::{LuaClient, LuaEntityRef},
};

impl LuaClient {
    pub(super) fn others(&self, entities: Box<[azalea::EntityRef]>) -> Vec<LuaEntityRef> {
        let me = self.client.entity;
        Vec::from(entities)
            .into_iter()
            .filter(|e| e.id() != me)
            .map(|entity| LuaEntityRef { entity })
            .collect()
    }
}

#[mlua::userdata_impl]
impl LuaClient {
    // luau[Bot]: --- The closest other player in render distance, or nil when nobody is around.
    // luau[Bot]: function nearest_player(self): Entity?
    fn nearest_player(&self) -> mlua::Result<Option<LuaEntityRef>> {
        let players = self.client.nearby_players().map_err(lua_err)?;
        Ok(self.others(players).into_iter().next())
    }

    // luau[Bot]: --- Entities in render distance (nearest first, not including the bot). With `kind` (like "zombie" or "minecraft:zombie") only entities of that type are returned. Unknown kinds are an error.
    // luau[Bot]: function nearby_entities(self, kind: string?): { Entity }
    fn nearby_entities(&self, kind: Option<String>) -> mlua::Result<Vec<LuaEntityRef>> {
        let found = match kind {
            None => self.client.nearest_entities::<()>().map_err(lua_err)?,
            Some(name) => {
                let kind: EntityKind = name
                    .parse()
                    .map_err(|_| mlua::Error::runtime(format!("unknown entity kind '{name}'")))?;
                self.client
                    .nearest_entities_by::<&EntityKindComponent, ()>(
                        move |k: &EntityKindComponent| k.0 == kind,
                    )
                    .map_err(lua_err)?
            }
        };
        Ok(self.others(found))
    }
}
