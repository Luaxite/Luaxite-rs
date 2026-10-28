#![allow(clippy::missing_errors_doc)]

use std::future::Future;

use mlua::prelude::*;


pub struct TableBuilder {
    lua: Lua,
    tab: LuaTable,
}

impl TableBuilder {
    
    pub fn new(lua: Lua) -> LuaResult<Self> {
        let tab = lua.create_table()?;
        Ok(Self { lua, tab })
    }

    
    pub fn with_value<K, V>(self, key: K, value: V) -> LuaResult<Self>
    where
        K: IntoLua,
        V: IntoLua,
    {
        self.tab.raw_set(key, value)?;
        Ok(self)
    }

    
    pub fn with_values<K, V>(self, values: Vec<(K, V)>) -> LuaResult<Self>
    where
        K: IntoLua,
        V: IntoLua,
    {
        for (key, value) in values {
            self.tab.raw_set(key, value)?;
        }
        Ok(self)
    }

    
    pub fn with_sequential_value<V>(self, value: V) -> LuaResult<Self>
    where
        V: IntoLua,
    {
        self.tab.raw_push(value)?;
        Ok(self)
    }

    
    pub fn with_sequential_values<V>(self, values: Vec<V>) -> LuaResult<Self>
    where
        V: IntoLua,
    {
        for value in values {
            self.tab.raw_push(value)?;
        }
        Ok(self)
    }

    
    pub fn with_function<K, A, R, F>(self, key: K, func: F) -> LuaResult<Self>
    where
        K: IntoLua,
        A: FromLuaMulti,
        R: IntoLuaMulti,
        F: Fn(&Lua, A) -> LuaResult<R> + mlua::MaybeSend + 'static,
    {
        let f = self.lua.create_function(func)?;
        self.with_value(key, LuaValue::Function(f))
    }

    
    pub fn with_async_function<K, A, R, F, FR>(self, key: K, func: F) -> LuaResult<Self>
    where
        K: IntoLua,
        A: FromLuaMulti,
        R: IntoLuaMulti,
        F: Fn(Lua, A) -> FR + mlua::MaybeSend + 'static,
        FR: Future<Output = LuaResult<R>> + mlua::MaybeSend + 'static,
    {
        let f = self.lua.create_async_function(func)?;
        self.with_value(key, LuaValue::Function(f))
    }

    
    pub fn with_metatable(self, table: LuaTable) -> LuaResult<Self> {
        self.tab.set_metatable(Some(table))?;
        Ok(self)
    }

    
    pub fn build_readonly(self) -> LuaResult<LuaTable> {
        self.tab.set_readonly(true);
        Ok(self.tab)
    }

    
    pub fn build(self) -> LuaResult<LuaTable> {
        Ok(self.tab)
    }
}
