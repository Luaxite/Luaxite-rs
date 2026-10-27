use azalea::{ecs::entity::Entity, prelude::Client};
use mlua::{AnyUserData, Function, Lua, Table, Value};

use super::{
    convert::lua_err,
    gen_client::{LuaClient, LuaEntityRef},
    gen_ecs,
};

fn entity_of(e: &AnyUserData) -> mlua::Result<Entity> {
    Ok(e.borrow::<LuaEntityRef>()?.entity.id())
}

fn missing(what: &str, name: &str) -> mlua::Error {
    lua_err(format!("{what} has no component `{name}`"))
}

pub(super) fn build_row(
    lua: &Lua,
    names: &[String],
    mut read: impl FnMut(&str) -> mlua::Result<Option<Value>>,
) -> mlua::Result<Result<Table, String>> {
    let row = lua.create_table()?;
    for name in names {
        match read(name)? {
            Some(v) => row.set(name.as_str(), v)?,
            None => return Ok(Err(name.clone())),
        }
    }
    Ok(Ok(row))
}

async fn run_query(
    what: &str,
    row: Result<Table, String>,
    f: Function,
    strict: bool,
) -> mlua::Result<Value> {
    match row {
        Ok(t) => f.call_async::<Value>(t).await,
        Err(name) if strict => Err(missing(what, &name)),
        Err(_) => Ok(Value::Nil),
    }
}

fn client_row(
    lua: &Lua,
    client: &Client,
    entity: Entity,
    names: &[String],
) -> mlua::Result<Result<Table, String>> {
    build_row(lua, names, |n| {
        gen_ecs::read_component(lua, client, entity, n)
    })
}

#[mlua::userdata_impl]
impl LuaClient {
    // luau[Bot]: --- Every ECS component and resource a script can name: `{ name, kind = "component" | "resource", luau (the Luau type of its value), readable }`, in name order. Types with `readable = false` exist in azalea but have no Luau conversion. Never yields.
    // luau[Bot]: function ecs_names(self): { { name: string, kind: string, luau: string, readable: boolean } }
    fn ecs_names(&self, lua: &Lua) -> mlua::Result<Vec<Table>> {
        let mut out = Vec::with_capacity(gen_ecs::ECS_ENTRIES.len());
        for e in gen_ecs::ECS_ENTRIES {
            let t = lua.create_table()?;
            t.set("name", e.name)?;
            t.set("kind", e.kind)?;
            t.set("luau", e.luau)?;
            t.set("readable", e.readable)?;
            out.push(t);
        }
        Ok(out)
    }

    // luau[Bot]: --- The value of a component of the bot's own entity (name from `ecs_names`, e.g. "Health"). Errors when the bot lacks it or the name is unknown/unreadable. Never yields.
    // luau[Bot]: function component(self, name: string): any
    fn component(&self, lua: &Lua, name: String) -> mlua::Result<Value> {
        gen_ecs::read_component(lua, &self.client, self.client.entity, &name)?
            .ok_or_else(|| missing("the bot", &name))
    }

    // luau[Bot]: --- Like `component`, but nil when the bot lacks the component. Never yields.
    // luau[Bot]: function get_component(self, name: string): any?
    fn get_component(&self, lua: &Lua, name: String) -> mlua::Result<Option<Value>> {
        gen_ecs::read_component(lua, &self.client, self.client.entity, &name)
    }

    // luau[Bot]: --- The value of a component of another entity. Errors when the entity lacks it. Never yields.
    // luau[Bot]: function entity_component(self, entity: Entity, name: string): any
    fn entity_component(
        &self,
        lua: &Lua,
        entity: AnyUserData,
        name: String,
    ) -> mlua::Result<Value> {
        let id = entity_of(&entity)?;
        gen_ecs::read_component(lua, &self.client, id, &name)?
            .ok_or_else(|| missing("the entity", &name))
    }

    // luau[Bot]: --- Like `entity_component`, but nil when the entity lacks the component. Never yields.
    // luau[Bot]: function get_entity_component(self, entity: Entity, name: string): any?
    fn get_entity_component(
        &self,
        lua: &Lua,
        entity: AnyUserData,
        name: String,
    ) -> mlua::Result<Option<Value>> {
        let id = entity_of(&entity)?;
        gen_ecs::read_component(lua, &self.client, id, &name)
    }

    // luau[Bot]: --- The value of an ECS resource (name from `ecs_names`). Errors when the resource is missing. Never yields.
    // luau[Bot]: function resource(self, name: string): any
    fn resource(&self, lua: &Lua, name: String) -> mlua::Result<Value> {
        gen_ecs::read_resource(lua, &self.client, &name)?
            .ok_or_else(|| lua_err(format!("no resource `{name}` in the ECS")))
    }

    // luau[Bot]: --- Calls `fn(value)` with an ECS resource and returns what it returns. Errors when the resource is missing.
    // luau[Bot]: function map_resource(self, name: string, f: (value: any) -> any): any
    async fn map_resource(&self, lua: Lua, name: String, f: Function) -> mlua::Result<Value> {
        let v = gen_ecs::read_resource(&lua, &self.client, &name)?
            .ok_or_else(|| lua_err(format!("no resource `{name}` in the ECS")))?;
        f.call_async::<Value>(v).await
    }

    // luau[Bot]: --- Calls `fn(value)` with an ECS resource, or `fn(nil)` when it is missing, and returns what it returns.
    // luau[Bot]: function map_get_resource(self, name: string, f: (value: any?) -> any): any
    async fn map_get_resource(&self, lua: Lua, name: String, f: Function) -> mlua::Result<Value> {
        let v = gen_ecs::read_resource(&lua, &self.client, &name)?.unwrap_or(Value::Nil);
        f.call_async::<Value>(v).await
    }

    // luau[Bot]: --- Read-only snapshot query on the bot's entity: `fn({ [name] = value })` is called with the named components and its result returned. Errors when a component is missing.
    // luau[Bot]: function query_self(self, names: { string }, f: (row: { [string]: any }) -> any): any
    async fn query_self(&self, lua: Lua, names: Vec<String>, f: Function) -> mlua::Result<Value> {
        let row = client_row(&lua, &self.client, self.client.entity, &names)?;
        run_query("the bot", row, f, true).await
    }

    // luau[Bot]: --- Like `query_self`, but returns nil (without calling `fn`) when a component is missing.
    // luau[Bot]: function try_query_self(self, names: { string }, f: (row: { [string]: any }) -> any): any?
    async fn try_query_self(
        &self,
        lua: Lua,
        names: Vec<String>,
        f: Function,
    ) -> mlua::Result<Value> {
        let row = client_row(&lua, &self.client, self.client.entity, &names)?;
        run_query("the bot", row, f, false).await
    }

    // luau[Bot]: --- Read-only snapshot query on another entity (see `query_self`). Errors when a component is missing.
    // luau[Bot]: function query_entity(self, entity: Entity, names: { string }, f: (row: { [string]: any }) -> any): any
    async fn query_entity(
        &self,
        lua: Lua,
        entity: AnyUserData,
        names: Vec<String>,
        f: Function,
    ) -> mlua::Result<Value> {
        let id = entity_of(&entity)?;
        let row = client_row(&lua, &self.client, id, &names)?;
        run_query("the entity", row, f, true).await
    }

    // luau[Bot]: --- Like `query_entity`, but returns nil (without calling `fn`) when a component is missing.
    // luau[Bot]: function try_query_entity(self, entity: Entity, names: { string }, f: (row: { [string]: any }) -> any): any?
    async fn try_query_entity(
        &self,
        lua: Lua,
        entity: AnyUserData,
        names: Vec<String>,
        f: Function,
    ) -> mlua::Result<Value> {
        let id = entity_of(&entity)?;
        let row = client_row(&lua, &self.client, id, &names)?;
        run_query("the entity", row, f, false).await
    }
}

#[mlua::userdata_impl]
impl LuaEntityRef {
    // luau[Entity]: --- The value of a component of this entity (name from `bot:ecs_names()`). Errors when the entity lacks it. Never yields.
    // luau[Entity]: function component(self, name: string): any
    fn component(&self, lua: &Lua, name: String) -> mlua::Result<Value> {
        gen_ecs::read_ref_component(lua, &self.entity, &name)?
            .ok_or_else(|| missing("the entity", &name))
    }

    // luau[Entity]: --- Like `component`, but nil when the entity lacks the component. Never yields.
    // luau[Entity]: function get_component(self, name: string): any?
    fn get_component(&self, lua: &Lua, name: String) -> mlua::Result<Option<Value>> {
        gen_ecs::read_ref_component(lua, &self.entity, &name)
    }

    // luau[Entity]: --- Read-only snapshot query on this entity: `fn({ [name] = value })` is called with the named components and its result returned. Errors when a component is missing.
    // luau[Entity]: function query_self(self, names: { string }, f: (row: { [string]: any }) -> any): any
    async fn query_self(&self, lua: Lua, names: Vec<String>, f: Function) -> mlua::Result<Value> {
        let entity = self.entity.clone();
        let row = build_row(&lua, &names, |n| {
            gen_ecs::read_ref_component(&lua, &entity, n)
        })?;
        run_query("the entity", row, f, true).await
    }

    // luau[Entity]: --- Like `query_self`, but returns nil (without calling `fn`) when a component is missing.
    // luau[Entity]: function try_query_self(self, names: { string }, f: (row: { [string]: any }) -> any): any?
    async fn try_query_self(
        &self,
        lua: Lua,
        names: Vec<String>,
        f: Function,
    ) -> mlua::Result<Value> {
        let entity = self.entity.clone();
        let row = build_row(&lua, &names, |n| {
            gen_ecs::read_ref_component(&lua, &entity, n)
        })?;
        run_query("the entity", row, f, false).await
    }
}
