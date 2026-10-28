use azalea::{entity::EntityKindComponent, registry::builtin::EntityKind};
use mlua::{Function, Lua, Value};

use super::{
    convert::lua_err,
    gen_client::{LuaClient, LuaEntityRef},
    gen_ecs,
    real_ecs::build_row,
};

impl LuaClient {
    async fn search(
        &self,
        lua: &Lua,
        names: &[String],
        pred: &Function,
        limit: Option<usize>,
    ) -> mlua::Result<Vec<LuaEntityRef>> {
        let candidates = self.client.nearest_entities::<()>().map_err(lua_err)?;
        let me = self.client.entity;
        let mut found = Vec::new();
        for er in Vec::from(candidates).into_iter().filter(|e| e.id() != me) {
            let row = build_row(lua, names, |n| gen_ecs::read_ref_component(lua, &er, n))?;
            let Ok(row) = row else { continue };
            let verdict: Value = pred
                .call_async((row, LuaEntityRef { entity: er.clone() }))
                .await?;
            if matches!(verdict, Value::Nil | Value::Boolean(false)) {
                continue;
            }
            found.push(LuaEntityRef { entity: er });
            if limit.is_some_and(|l| found.len() >= l) {
                break;
            }
        }
        Ok(found)
    }
}

#[mlua::userdata_impl]
impl LuaClient {
    
    
    fn nearest_entities(&self, kind: Option<String>) -> mlua::Result<Vec<LuaEntityRef>> {
        let found = match kind {
            None => self.client.nearest_entities::<()>().map_err(lua_err)?,
            Some(name) => {
                let kind: EntityKind = name
                    .parse()
                    .map_err(|_| lua_err(format!("unknown entity kind '{name}'")))?;
                self.client
                    .nearest_entities_by::<&EntityKindComponent, ()>(
                        move |k: &EntityKindComponent| k.0 == kind,
                    )
                    .map_err(lua_err)?
            }
        };
        Ok(self.others(found))
    }

    
    
    async fn any_entity_by(
        &self,
        lua: Lua,
        names: Vec<String>,
        pred: Function,
    ) -> mlua::Result<Option<LuaEntityRef>> {
        Ok(self
            .search(&lua, &names, &pred, Some(1))
            .await?
            .into_iter()
            .next())
    }

    
    
    async fn nearest_entity_by(
        &self,
        lua: Lua,
        names: Vec<String>,
        pred: Function,
    ) -> mlua::Result<Option<LuaEntityRef>> {
        Ok(self
            .search(&lua, &names, &pred, Some(1))
            .await?
            .into_iter()
            .next())
    }

    
    
    async fn nearest_entities_by(
        &self,
        lua: Lua,
        names: Vec<String>,
        pred: Function,
    ) -> mlua::Result<Vec<LuaEntityRef>> {
        self.search(&lua, &names, &pred, None).await
    }
}
