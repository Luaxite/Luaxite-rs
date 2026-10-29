mod convert;
// Sample `//BIND pub` file (see its header); its fns are Luau globals through the generated `binds::register`.
#[allow(dead_code)]
mod demo_binds;
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
    path::{Path, PathBuf},
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

/// The Lua state of the most recently created `Runtime` (fallback for `current_lua`).
static CURRENT: Mutex<Option<Lua>> = Mutex::new(None);

tokio::task_local! {
    /// The Lua state of the script running in this task (set around `Runtime::run_standalone`).
    static TASK_LUA: Lua;
}

/// The mlua `Lua` of the running script, for Rust code that is not a `#[bind]` fn (a bound fn can take `&Lua` as its first param instead).
///
/// Rule: inside a script's own task (`Runtime::run_standalone` and everything it awaits) this is that script's state, even with several
/// `Runtime`s in one process. Anywhere else (a `tokio::spawn`ed task, a plain thread) it is the state of the LAST `Runtime` created, so
/// with more than one script pass the handle explicitly. `Lua` is a cheap clone (a handle, `Send` under mlua's `send` feature).
///
/// Panics with `current_lua called before a Runtime exists` when no `Runtime` has been created yet.
#[allow(dead_code)]
pub fn current_lua() -> Lua {
    if let Ok(lua) = TASK_LUA.try_with(|l| l.clone()) {
        return lua;
    }
    CURRENT
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .clone()
        .expect("current_lua called before a Runtime exists")
}

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

/// Chunk name (what errors and `debug.info(level, "s")` show) -> absolute path, for every file module and for the main script.
/// `require` uses it to find the directory of the file that called it.
fn register_path(lua: &Lua, display: &str, path: &Path) -> mlua::Result<()> {
    let paths: mlua::Table = lua.named_registry_value("azalea_paths")?;
    paths.set(display, path.to_string_lossy().into_owned())
}

/// The path shown in errors for a module file: relative to the working directory when it lies below it, else absolute.
fn display_path(canon: &Path) -> String {
    let cwd = std::env::current_dir().ok().and_then(|d| std::fs::canonicalize(d).ok());
    let rel = cwd.as_deref().and_then(|d| canon.strip_prefix(d).ok());
    let shown = rel.unwrap_or(canon).to_string_lossy().into_owned();
    shown.strip_prefix(r"\\?\").map(str::to_owned).unwrap_or(shown)
}

/// The directory of the script file that called `require` (`from` is its chunk name), if it is one we loaded from disk.
fn caller_dir(lua: &Lua, from: Option<&str>) -> Option<PathBuf> {
    let paths: mlua::Table = lua.named_registry_value("azalea_paths").ok()?;
    let path: String = paths.get::<Option<String>>(from?).ok()??;
    Path::new(&path).parent().map(Path::to_path_buf)
}

/// `name` below `base` as a module file: `name.luau`, `name.lua`, `name/init.luau`, `name/init.lua` (or `name` itself when it already
/// ends in .luau / .lua). `Err` carries every path tried.
fn find_module_file(base: &Path, name: &str) -> Result<PathBuf, Vec<PathBuf>> {
    let joined = base.join(name);
    let mut tried = Vec::new();
    if matches!(joined.extension().and_then(|e| e.to_str()), Some("luau" | "lua")) {
        tried.push(joined.clone());
    }
    for ext in ["luau", "lua"] {
        let mut with_ext = joined.clone().into_os_string();
        with_ext.push(format!(".{ext}"));
        tried.push(PathBuf::from(with_ext));
    }
    for ext in ["luau", "lua"] {
        tried.push(joined.join(format!("init.{ext}")));
    }
    match tried.iter().find(|p| p.is_file()) {
        Some(found) => Ok(found.clone()),
        None => Err(tried),
    }
}

/// Starts loading module `key`: an embedded `src/**.luau` key, or the canonical absolute path of a module file (see `install_require`).
fn begin_module(lua: &Lua, key: &str) -> mlua::Result<(Function, Loading)> {
    let chunk = if let Some((_, source)) = scripts::SCRIPTS.iter().find(|(n, _)| *n == key) {
        lua.load(*source).set_name(format!("@{key}"))
    } else if Path::new(key).is_absolute() {
        let path = Path::new(key);
        let source = std::fs::read_to_string(path)
            .map_err(|e| mlua::Error::runtime(format!("cannot read module '{key}': {e}")))?;
        let display = display_path(path);
        register_path(lua, &display, path)?;
        lua.load(source).set_name(format!("@{display}"))
    } else {
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
    Ok((chunk.into_function()?, guard))
}

fn finish_module(lua: &Lua, key: &str, value: mlua::Value) -> mlua::Result<mlua::Value> {
    let value = if value.is_nil() {
        mlua::Value::Boolean(true)
    } else {
        value
    };
    let loaded: mlua::Table = lua.named_registry_value("azalea_loaded")?;
    loaded.set(key, value.clone())?;
    Ok(value)
}

/// `require(name)`:
/// - `@lune/<n>`: Lune's built-in modules (feature `lune`).
/// - `./x`, `../x`, `x/y`: a file relative to the script (or module) that calls `require`: `x.luau`, `x.lua`, `x/init.luau`, `x/init.lua`.
///   Relative names look for the file first and then for an embedded `src/` module of that name; bare names the other way round.
/// - anything else starting with `@` goes to mlua's own `require` (`.luaurc` aliases).
///
/// A module runs once; later requires get the cached value, whichever relative path reached the same file.
fn install_require(lua: &Lua) -> mlua::Result<()> {
    let fallback: Option<Function> = lua.globals().get("require")?;
    lua.set_named_registry_value("azalea_loaded", lua.create_table()?)?;
    lua.set_named_registry_value("azalea_loading", lua.create_table()?)?;
    lua.set_named_registry_value("azalea_paths", lua.create_table()?)?;
    let resolve = lua.create_function(
        move |lua, (name, from): (String, Option<String>)| -> mlua::Result<(mlua::Value, Option<String>)> {
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
            if name.starts_with('@') {
                return match &fallback {
                    Some(f) => Ok((f.call(name)?, None)),
                    None => Err(mlua::Error::runtime(format!("module '{name}' not found"))),
                };
            }
            let relative = name.starts_with("./") || name.starts_with("../") || name == "." || name == "..";
            let base = caller_dir(lua, from.as_deref()).or_else(|| {
                // A script that was not loaded from a file (the embedded main) has no directory of its own: relative names use the working directory.
                if relative { std::env::current_dir().ok() } else { None }
            });
            let embedded_key = {
                let k = name.trim_start_matches("./").replace('/', ".");
                k.strip_suffix(".luau").unwrap_or(&k).to_string()
            };
            let mut tried = Vec::new();
            let by_file = |tried: &mut Vec<PathBuf>| -> Option<String> {
                match find_module_file(base.as_deref()?, &name) {
                    Ok(found) => std::fs::canonicalize(found).ok().map(|c| c.to_string_lossy().into_owned()),
                    Err(t) => {
                        tried.extend(t);
                        None
                    }
                }
            };
            let by_embedded = || scripts::SCRIPTS.iter().any(|(n, _)| *n == embedded_key).then(|| embedded_key.clone());
            let key = if relative {
                by_file(&mut tried).or_else(by_embedded)
            } else {
                by_embedded().or_else(|| by_file(&mut tried))
            };
            let Some(key) = key else {
                let mut msg = format!("module '{name}' not found (embedded modules are src/**.luau");
                if !tried.is_empty() {
                    let list: Vec<_> = tried.iter().map(|p| p.display().to_string()).collect();
                    msg.push_str(&format!("; tried files: {}", list.join(", ")));
                }
                msg.push(')');
                return Err(mlua::Error::runtime(msg));
            };
            let loaded: mlua::Table = lua.named_registry_value("azalea_loaded")?;
            let hit: mlua::Value = loaded.get(key.as_str())?;
            if !hit.is_nil() {
                return Ok((hit, None));
            }
            let loading: mlua::Table = lua.named_registry_value("azalea_loading")?;
            if loading.get::<bool>(key.as_str())? {
                return Err(mlua::Error::runtime(format!(
                    "module '{name}' is still loading (cyclic require?)"
                )));
            }
            Ok((mlua::Value::Nil, Some(key)))
        },
    )?;
    let load_module = lua.create_async_function(|lua, key: String| async move {
        let (chunk, _guard) = begin_module(&lua, &key)?;
        let value: mlua::Value = chunk.call_async(()).await?;
        finish_module(&lua, &key, value)
    })?;
    let load_module_sync = lua.create_function(|lua, key: String| {
        let (chunk, _guard) = begin_module(lua, &key)?;
        let value: mlua::Value = chunk.call(())?;
        finish_module(lua, &key, value)
    })?;
    let glue: Function = lua
        .load(
            r#"
            local resolve, load_module, load_module_sync = ...
            local info = debug.info
            return function(name)
                -- the script or module that called require: the first caller that is not a C function (pcall(require, ...) has one in between)
                local from
                local level = 2
                while true do
                    local source = info(level, "s")
                    if source == nil then
                        break
                    end
                    if source ~= "[C]" then
                        from = source
                        break
                    end
                    level += 1
                end
                local value, key = resolve(name, from)
                if key == nil then
                    return value
                end
                if coroutine.isyieldable() then
                    return load_module(key)
                else
                    return load_module_sync(key)
                end
            end
            "#,
        )
        .set_name("=require_shim")
        .into_function()?;
    let require: Function = glue.call((resolve, load_module, load_module_sync))?;
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
        let canon = std::fs::canonicalize(script)
            .with_context(|| format!("resolving {}", script.display()))?;
        // The script's name is its path as given: it is what errors show, and what `require` maps back to the script's directory.
        let name = script.display().to_string();
        let runtime = Self::with_source(name.clone(), source)?;
        register_path(&runtime.lua, &name, &canon).context("registering the script path")?;
        Ok(runtime)
    }

    #[allow(dead_code)]
    pub fn embedded() -> anyhow::Result<Self> {
        Self::with_source("main.luau".into(), scripts::MAIN.to_string())
    }

    /// The mlua state of this script, to do whatever you want with it (load chunks, set globals, create functions, ...).
    #[allow(dead_code)]
    pub fn lua(&self) -> &Lua {
        &self.lua
    }

    fn with_source(name: String, source: String) -> anyhow::Result<Self> {
        let lua = Lua::new();
        install_coroutine_shim(&lua).context("installing coroutine shim")?;
        install_require(&lua).context("installing require")?;
        binds::register(&lua).context("registering #[bind] functions")?;
        *CURRENT.lock().unwrap_or_else(|e| e.into_inner()) = Some(lua.clone());
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
        TASK_LUA.scope(self.lua.clone(), self.run_scoped()).await
    }

    #[cfg(feature = "real")]
    async fn run_scoped(&self) -> anyhow::Result<()> {
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
