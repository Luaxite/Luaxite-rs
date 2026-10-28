#[cfg(feature = "real")]
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures_util::StreamExt;
use mlua::thread::ThreadStatus;
use mlua::{FromLua, Function, Lua, MultiValue, Table, Thread, Value};

enum ThreadOrFunction {
    Thread(Thread),
    Function(Function),
}

impl ThreadOrFunction {
    fn into_thread(self, lua: &Lua) -> mlua::Result<Thread> {
        match self {
            Self::Thread(t) => Ok(t),
            Self::Function(f) => lua.create_thread(f),
        }
    }
}

impl FromLua for ThreadOrFunction {
    fn from_lua(value: Value, _: &Lua) -> mlua::Result<Self> {
        match value {
            Value::Thread(t) => Ok(Self::Thread(t)),
            Value::Function(f) => Ok(Self::Function(f)),
            value => Err(mlua::Error::FromLuaConversionError {
                from: value.type_name(),
                to: "ThreadOrFunction".to_string(),
                message: Some("Expected thread or function".to_string()),
            }),
        }
    }
}

pub(super) struct LiveGuard {
    #[cfg(feature = "real")]
    live: Option<Arc<super::real_lifecycle::Live>>,
}

impl LiveGuard {
    pub(super) fn new(lua: &Lua) -> Self {
        #[cfg(feature = "real")]
        {
            let live = lua
                .app_data_ref::<Arc<super::real_lifecycle::Live>>()
                .map(|l| l.clone());
            if let Some(live) = &live {
                live.enter();
            }
            Self { live }
        }
        #[cfg(not(feature = "real"))]
        {
            let _ = lua;
            Self {}
        }
    }
}

#[cfg(feature = "real")]
impl Drop for LiveGuard {
    fn drop(&mut self) {
        if let Some(live) = &self.live {
            live.leave();
        }
    }
}

const CANCEL_POLL: Duration = Duration::from_millis(100);

fn is_poll_pending(value: &Value) -> bool {
    value
        .as_light_userdata()
        .is_some_and(|l| l == Lua::poll_pending())
}

fn report(e: &mlua::Error) {
    super::note_error();
    eprintln!("[luau] task error: {e}");
}

pub(super) fn run_thread(lua: &Lua, thread: Thread, args: MultiValue, resume_now: bool) {
    if thread.status() != ThreadStatus::Resumable {
        return;
    }
    if resume_now {
        match thread.resume::<MultiValue>(args.clone()) {
            Ok(v) if v.front().is_some_and(is_poll_pending) => {}
            Ok(_) => return,
            Err(e) => return report(&e),
        }
    }
    let guard = LiveGuard::new(lua);
    tokio::task::spawn_local(async move {
        let _guard = guard;
        if thread.status() != ThreadStatus::Resumable {
            return;
        }
        let watch = thread.clone();
        match thread.into_async::<MultiValue>(args) {
            Ok(mut stream) => loop {
                tokio::select! {
                    next = stream.next() => {
                        if let Some(Err(e)) = next {
                            report(&e);
                        }
                        break;
                    }
                    _ = tokio::time::sleep(CANCEL_POLL) => {
                        if watch.status() != ThreadStatus::Resumable {
                            break;
                        }
                    }
                }
            },
            Err(e) => report(&e),
        }
    });
}

fn spawn(lua: &Lua, (tof, args): (ThreadOrFunction, MultiValue)) -> mlua::Result<Thread> {
    let thread = tof.into_thread(lua)?;
    run_thread(lua, thread.clone(), args, true);
    Ok(thread)
}

fn defer(lua: &Lua, (tof, args): (ThreadOrFunction, MultiValue)) -> mlua::Result<Thread> {
    let thread = tof.into_thread(lua)?;
    run_thread(lua, thread.clone(), args, false);
    Ok(thread)
}

async fn wait(secs: Option<f64>) -> mlua::Result<f64> {
    tokio::task::yield_now().await;
    let secs = secs.unwrap_or(0.0);
    let before = Instant::now();
    if secs.is_nan() || secs <= 0.0 {
        tokio::time::sleep(Duration::from_millis(1)).await;
    } else {
        match Duration::try_from_secs_f64(secs) {
            Ok(dur) => tokio::time::sleep(dur.max(Duration::from_millis(1))).await,
            Err(_) => std::future::pending::<()>().await,
        }
    }
    Ok(before.elapsed().as_secs_f64())
}

const DELAY_SRC: &str =
    "return defer(function(...) wait(select(1, ...)) spawn(select(2, ...)) end, ...)";

pub fn module(lua: Lua) -> mlua::Result<Table> {
    let close: Function = lua.globals().get::<Table>("coroutine")?.get("close")?;
    let close_key = lua.create_registry_value(close)?;
    let wrappers: Table = lua
        .load("return setmetatable({}, { __mode = 'k' })")
        .eval()?;
    let wrappers_cancel = wrappers.clone();
    let cancel = lua.create_function(move |lua, thread: Thread| {
        let close: Function = lua.registry_value(&close_key)?;
        if let Some(wrapper) = wrappers_cancel.get::<Option<Thread>>(thread.clone())? {
            wrappers_cancel.set(thread.clone(), Value::Nil)?;
            let _ = close.call::<()>(wrapper);
        }
        match close.call::<()>(thread) {
            Ok(()) | Err(mlua::Error::CoroutineUnresumable) => Ok(()),
            Err(e) => Err(e),
        }
    })?;
    let spawn_fn = lua.create_function(spawn)?;
    let defer_fn = lua.create_function(defer)?;
    let wait_fn = lua.create_async_function(|_, secs: Option<f64>| wait(secs))?;
    let select: Function = lua.globals().get("select")?;
    let env = lua.create_table_from([
        ("select", select),
        ("spawn", spawn_fn.clone()),
        ("defer", defer_fn.clone()),
        ("wait", wait_fn.clone()),
    ])?;
    env.set_readonly(true);
    let delay_inner = lua
        .load(DELAY_SRC)
        .set_name("=task.delay")
        .set_environment(env)
        .into_function()?;
    let delay = lua.create_function(move |lua, args: MultiValue| {
        let tof = ThreadOrFunction::from_lua(args.get(1).cloned().unwrap_or(Value::Nil), lua)?;
        let thread = tof.into_thread(lua)?;
        let args: MultiValue = args
            .into_iter()
            .enumerate()
            .map(|(i, v)| {
                if i == 1 {
                    Value::Thread(thread.clone())
                } else {
                    v
                }
            })
            .collect();
        let wrapper = delay_inner.call::<Thread>(args)?;
        wrappers.set(thread.clone(), wrapper)?;
        Ok(thread)
    })?;
    let task = lua.create_table()?;
    task.set("spawn", spawn_fn)?;
    task.set("defer", defer_fn)?;
    task.set("cancel", cancel)?;
    task.set("wait", wait_fn)?;
    task.set("delay", delay)?;
    task.set_readonly(true);
    Ok(task)
}
