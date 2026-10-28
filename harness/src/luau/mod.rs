mod convert;
mod extra_block;
mod extra_container;
mod extra_entity;
mod extra_inventory;
mod extra_misc;
mod extra_query;
mod extra_state;
include!("generated.rs");

#[cfg(feature = "lune")]
mod lune_libs;
#[cfg(feature = "lune")]
mod lune_net;
#[cfg(feature = "lune")]
mod lune_process;
#[cfg(feature = "lune")]
mod lune_stdio;
#[cfg(feature = "lune")]
mod lune_task;
#[cfg(feature = "real")]
mod real_ecs;
#[cfg(feature = "real")]
mod real_entity;
#[cfg(feature = "real")]
mod real_events;
#[cfg(feature = "real")]
mod real_goal;
#[cfg(feature = "real")]
mod real_hub;
#[cfg(feature = "real")]
mod real_inventory;
#[cfg(feature = "real")]
mod real_lifecycle;
#[cfg(feature = "packets")]
mod real_packets;
#[cfg(feature = "real")]
mod real_registry;
#[cfg(feature = "real")]
mod real_search;
#[cfg(feature = "real")]
mod real_world;

use std::{
    collections::HashMap,
    path::Path,
    sync::{
        Arc, Mutex, RwLock,
        atomic::{AtomicBool, Ordering},
    },
};

use anyhow::Context;
use mlua::{Function, IntoLuaMulti, Lua, MultiValue};
use tokio::sync::oneshot;

pub use gen_client::LuaClient;



static SCRIPT_ERRORS: AtomicBool = AtomicBool::new(false);

pub fn note_error() {
    SCRIPT_ERRORS.store(true, Ordering::SeqCst);
}

#[allow(dead_code)]
pub fn had_error() -> bool {
    SCRIPT_ERRORS.load(Ordering::SeqCst)
}

#[derive(Default)]
pub struct Handlers {
    map: RwLock<HashMap<String, Vec<Function>>>,
    waiters: Mutex<HashMap<String, Vec<oneshot::Sender<MultiValue>>>>,
    
    closed: AtomicBool,
}

impl Handlers {
    pub fn add(&self, event: String, f: Function) {
        if event == "init" {
            let run = async move {
                if let Err(e) = f.call_async::<()>(()).await {
                    note_error();
                    eprintln!("[luau] error in `init` handler: {e}");
                }
            };
            
            #[cfg(feature = "real")]
            tokio::task::spawn_local(run);
            #[cfg(not(feature = "real"))]
            tokio::spawn(run);
            return;
        }
        self.map.write().unwrap().entry(event).or_default().push(f);
    }

    pub fn has(&self, event: &str) -> bool {
        self.map
            .read()
            .unwrap()
            .get(event)
            .is_some_and(|v| !v.is_empty())
            || self.waiting(event) > 0
    }

    pub fn waiting(&self, event: &str) -> usize {
        self.waiters
            .lock()
            .unwrap()
            .get(event)
            .map_or(0, |v| v.iter().filter(|tx| !tx.is_closed()).count())
    }

    pub async fn wait(&self, event: &str) -> mlua::Result<MultiValue> {
        if event == "init" {
            return Ok(MultiValue::new());
        }
        let disconnected = || {
            mlua::Error::runtime(format!(
                "wait_for(\"{event}\"): the bot disconnected before the event fired"
            ))
        };
        let (tx, rx) = oneshot::channel();
        {
            let mut waiters = self.waiters.lock().unwrap();
            if self.closed.load(Ordering::SeqCst) {
                return Err(disconnected());
            }
            waiters.entry(event.to_owned()).or_default().push(tx);
        }
        rx.await.map_err(|_| disconnected())
    }

    pub fn close_waiters(&self) {
        let mut waiters = self.waiters.lock().unwrap();
        self.closed.store(true, Ordering::SeqCst);
        waiters.clear();
    }

    pub async fn fire(&self, lua: &Lua, event: &str, args: impl IntoLuaMulti) -> mlua::Result<()> {
        let list = self
            .map
            .read()
            .unwrap()
            .get(event)
            .cloned()
            .unwrap_or_default();
        let waiting = self
            .waiters
            .lock()
            .unwrap()
            .remove(event)
            .unwrap_or_default();
        if list.is_empty() && waiting.is_empty() {
            return Ok(());
        }
        let args = args.into_lua_multi(lua)?;
        for tx in waiting {
            let _ = tx.send(args.clone());
        }
        for f in list {
            if let Err(e) = f.call_async::<()>(args.clone()).await {
                note_error();
                eprintln!("[luau] error in `{event}` handler: {e}");
            }
        }
        Ok(())
    }
}






fn install_coroutine_shim(lua: &Lua) -> mlua::Result<()> {
    let co: mlua::Table = lua.globals().get("coroutine")?;
    let pending = mlua::Value::LightUserData(Lua::poll_pending());
    let patch: Function = lua
        .load(
            r##"
            local pending, co = ...
            local create, resume, yield, status = co.create, co.resume, co.yield, co.status
            local select, error = select, error
            local function forward(thread, ok, ...)
                if ok and select("#", ...) == 1 and (...) == pending and status(thread) == "suspended" then
                    return forward(thread, resume(thread, yield(pending)))
                end
                return ok, ...
            end
            local function plain_resume(thread, ...)
                return forward(thread, resume(thread, ...))
            end
            local function unwrap(ok, ...)
                if not ok then
                    error((...), 0)
                end
                return ...
            end
            co.resume = plain_resume
            co.wrap = function(f)
                local thread = create(f)
                return function(...)
                    return unwrap(plain_resume(thread, ...))
                end
            end
            "##,
        )
        .set_name("=coroutine_shim")
        .into_function()?;
    patch.call::<()>((pending, co))
}



struct Loading {
    table: mlua::Table,
    key: String,
}

impl Drop for Loading {
    fn drop(&mut self) {
        let _ = self.table.set(self.key.as_str(), mlua::Value::Nil);
    }
}




fn begin_embedded(lua: &Lua, key: &str) -> mlua::Result<(Function, Loading)> {
    let Some((_, source)) = scripts::SCRIPTS.iter().find(|(n, _)| *n == key) else {
        return Err(mlua::Error::runtime(format!(
            "module '{key}' not found (embedded modules are src/**.luau)"
        )));
    };
    let loading: mlua::Table = lua.named_registry_value("azalea_loading")?;
    loading.set(key, true)?;
    let guard = Loading {
        table: loading,
        key: key.to_string(),
    };
    let chunk = lua
        .load(*source)
        .set_name(format!("@{key}"))
        .into_function()?;
    Ok((chunk, guard))
}



fn finish_embedded(lua: &Lua, key: &str, value: mlua::Value) -> mlua::Result<mlua::Value> {
    let value = if value.is_nil() {
        mlua::Value::Boolean(true)
    } else {
        value
    };
    let loaded: mlua::Table = lua.named_registry_value("azalea_loaded")?;
    loaded.set(key, value.clone())?;
    Ok(value)
}







fn install_require(lua: &Lua) -> mlua::Result<()> {
    let fallback: Option<Function> = lua.globals().get("require")?;
    lua.set_named_registry_value("azalea_loaded", lua.create_table()?)?;
    lua.set_named_registry_value("azalea_loading", lua.create_table()?)?;
    
    let resolve = lua.create_function(
        move |lua, name: String| -> mlua::Result<(mlua::Value, Option<String>)> {
            if name.starts_with("@lune/") {
                #[cfg(feature = "lune")]
                {
                    let loaded: mlua::Table = lua.named_registry_value("azalea_loaded")?;
                    return Ok((lune_libs::require(lua, &loaded, &name)?, None));
                }
                #[cfg(not(feature = "lune"))]
                return Err(mlua::Error::runtime(format!(
                    "module '{name}' not available: luaxite was built without the `lune` cargo feature"
                )));
            }
            let key = name.trim_start_matches("./").replace('/', ".");
            let key = key.strip_suffix(".luau").unwrap_or(&key).to_string();
            let loaded: mlua::Table = lua.named_registry_value("azalea_loaded")?;
            let hit: mlua::Value = loaded.get(key.as_str())?;
            if !hit.is_nil() {
                return Ok((hit, None));
            }
            if !scripts::SCRIPTS.iter().any(|(n, _)| *n == key) {
                return match &fallback {
                    Some(f) => Ok((f.call(name)?, None)),
                    None => Err(mlua::Error::runtime(format!(
                        "module '{name}' not found (embedded modules are src/**.luau)"
                    ))),
                };
            }
            let loading: mlua::Table = lua.named_registry_value("azalea_loading")?;
            if loading.get::<bool>(key.as_str())? {
                return Err(mlua::Error::runtime(format!(
                    "module '{key}' is still loading (cyclic require?)"
                )));
            }
            Ok((mlua::Value::Nil, Some(key)))
        },
    )?;
    let load_embedded = lua.create_async_function(|lua, key: String| async move {
        let (chunk, _guard) = begin_embedded(&lua, &key)?;
        let value: mlua::Value = chunk.call_async(()).await?;
        finish_embedded(&lua, &key, value)
    })?;
    let load_embedded_sync = lua.create_function(|lua, key: String| {
        let (chunk, _guard) = begin_embedded(lua, &key)?;
        let value: mlua::Value = chunk.call(())?;
        finish_embedded(lua, &key, value)
    })?;
    let glue: Function = lua
        .load(
            r#"
            local resolve, load_embedded, load_embedded_sync = ...
            return function(name)
                local value, key = resolve(name)
                if key == nil then
                    return value
                end
                if coroutine.isyieldable() then
                    return load_embedded(key)
                else
                    return load_embedded_sync(key)
                end
            end
            "#,
        )
        .set_name("=require_shim")
        .into_function()?;
    let require: Function = glue.call((resolve, load_embedded, load_embedded_sync))?;
    lua.globals().set("require", require)
}

pub struct Runtime {
    lua: Lua,
    handlers: Arc<Handlers>,
    name: String,
    source: String,
}

impl Runtime {
    pub fn new(script: &Path) -> anyhow::Result<Self> {
        let source = std::fs::read_to_string(script)
            .with_context(|| format!("reading {}", script.display()))?;
        let name = script
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "script".into());
        Self::with_source(name, source)
    }

    #[allow(dead_code)]
    pub fn embedded() -> anyhow::Result<Self> {
        Self::with_source("main.luau".into(), scripts::MAIN.to_string())
    }

    fn with_source(name: String, source: String) -> anyhow::Result<Self> {
        let lua = Lua::new();
        install_coroutine_shim(&lua).context("installing coroutine shim")?;
        install_require(&lua).context("installing require")?;
        Ok(Self {
            lua,
            handlers: Arc::new(Handlers::default()),
            name,
            source,
        })
    }

    #[allow(dead_code)]
    pub fn waiting(&self, event: &str) -> usize {
        self.handlers.waiting(event)
    }

    
    pub fn kill_children() {
        #[cfg(feature = "lune")]
        lune_process::kill_all();
    }

    #[cfg(feature = "real")]
    pub async fn run_standalone(&self) -> anyhow::Result<()> {
        real_goal::install(&self.lua)?;
        let live = real_lifecycle::install(&self.lua)?;
        let chunk = self
            .lua
            .load(self.source.as_str())
            .set_name(format!("@{}", self.name));
        let script_err = chunk.exec_async().await.err();
        
        
        if let Some(e) = &script_err {
            eprintln!("[luau] script error: {e}");
        }
        live.wait_idle().await;
        match script_err {
            Some(_) => Err(anyhow::anyhow!("script failed (error printed above)")),
            None if had_error() => Err(anyhow::anyhow!(
                "a handler or task raised an error (printed above)"
            )),
            None => Ok(()),
        }
    }
}
