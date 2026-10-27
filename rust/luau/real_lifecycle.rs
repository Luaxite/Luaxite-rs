use std::{
    net::SocketAddr,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};

use azalea::{
    Account,
    prelude::{Client, Component, Event, Resource, bevy_ecs},
    protocol::connect::Proxy,
    swarm::{Swarm, SwarmBuilder, SwarmEvent},
};
use mlua::{Lua, Table, UserData, Value};
use tokio::sync::Notify;

use super::{Handlers, convert::lua_err, gen_client::LuaClient, gen_events, real_events};

pub struct Live {
    count: AtomicUsize,
    idle: Notify,
}

impl Live {
    pub(super) fn enter(&self) {
        self.count.fetch_add(1, Ordering::SeqCst);
    }

    pub(super) fn leave(&self) {
        if self.count.fetch_sub(1, Ordering::SeqCst) == 1 {
            self.idle.notify_waiters();
        }
    }

    pub async fn wait_idle(&self) {
        loop {
            let notified = self.idle.notified();
            if self.count.load(Ordering::SeqCst) == 0 {
                return;
            }
            notified.await;
        }
    }
}

async fn account_of(value: Value) -> mlua::Result<Account> {
    match value {
        Value::String(name) => Ok(Account::offline(&name.to_str()?)),
        Value::Table(t) => {
            let key: Option<String> = t.get("microsoft")?;
            if let Some(key) = key {
                return Account::microsoft(&key).await.map_err(lua_err);
            }
            let name: Option<String> = t.get("name")?;
            match name {
                Some(name) => Ok(Account::offline(&name)),
                None => Err(lua_err(
                    "azalea.join: `account` table needs `name` or `microsoft`",
                )),
            }
        }
        _ => Err(lua_err(
            "azalea.join: `account` must be a name or a table `{ name = .. }` / `{ microsoft = .. }`",
        )),
    }
}

/// Running handler tasks of one bot above which the pump warns once. Events are never dropped: the queue stays unbounded.
const BACKLOG_WARN: usize = 10_000;

fn start_event_pump(
    client: &Client,
    lua: Lua,
    handlers: Arc<Handlers>,
    live: Arc<Live>,
    mut rx: tokio::sync::mpsc::UnboundedReceiver<Event>,
) {
    real_events::start_update_pump(client, lua.clone(), handlers.clone());
    live.enter();
    // spawn_local: handlers call task.defer / process.create / net.serve, which need main.rs's LocalSet.
    tokio::task::spawn_local(async move {
        let mut guard = PumpGuard {
            live,
            handlers: handlers.clone(),
            left: false,
        };
        let backlog = Arc::new(AtomicUsize::new(0));
        let mut warned = false;
        while let Some(event) = rx.recv().await {
            if matches!(event, Event::Init) {
                continue;
            }
            let closing = matches!(event, Event::Disconnect(_) | Event::ConnectionFailed(_));
            // One task per event: a handler that parks in `bot:wait_for(..)` or walks (`goto_*`) must not hold up the events
            // that wake it, or `disconnect`. `InFlight` keeps `Live` busy until the task ends, so the process outlives it.
            let in_flight = InFlight::new(guard.live.clone(), backlog.clone());
            if !warned && backlog.load(Ordering::Relaxed) > BACKLOG_WARN {
                warned = true;
                eprintln!(
                    "[luau] event backlog: over {BACKLOG_WARN} handlers running for one bot (events are kept, not dropped)"
                );
            }
            let (task_lua, task_handlers) = (lua.clone(), handlers.clone());
            tokio::task::spawn_local(async move {
                let _in_flight = in_flight;
                #[cfg(feature = "packets")]
                if let Event::Packet(packet) = &event {
                    if let Err(e) =
                        real_events::dispatch_packet(&task_lua, &task_handlers, packet).await
                    {
                        super::note_error();
                        eprintln!("[luau] {e}");
                    }
                    return;
                }
                if let Err(e) = gen_events::dispatch(&task_lua, &task_handlers, event).await {
                    super::note_error();
                    eprintln!("[luau] {e}");
                }
                if closing {
                    // after the event's own waiters got it: the rest can never be woken
                    task_handlers.close_waiters();
                }
            });
            if closing {
                guard.leave();
            }
        }
        // `guard` drops here: waiters closed, `live.leave()` if it has not run yet.
    });
}

/// Keeps `Live` busy while one event's handlers run (also if they panic: `Drop` runs when the task is dropped).
struct InFlight(Arc<Live>, Arc<AtomicUsize>);

impl InFlight {
    fn new(live: Arc<Live>, backlog: Arc<AtomicUsize>) -> Self {
        live.enter();
        backlog.fetch_add(1, Ordering::Relaxed);
        Self(live, backlog)
    }
}

impl Drop for InFlight {
    fn drop(&mut self) {
        self.1.fetch_sub(1, Ordering::Relaxed);
        self.0.leave();
    }
}

/// Ends a bot's life in `Live` however its event pump ends. A panic in the pump drops its future, so `Drop` still runs
/// and `wait_idle` cannot hang on a bot that is gone.
struct PumpGuard {
    live: Arc<Live>,
    handlers: Arc<Handlers>,
    left: bool,
}

impl PumpGuard {
    fn leave(&mut self) {
        if !self.left {
            self.left = true;
            self.live.leave();
        }
    }
}

impl Drop for PumpGuard {
    fn drop(&mut self) {
        self.handlers.close_waiters();
        self.leave();
    }
}

pub fn install(lua: &Lua) -> mlua::Result<Arc<Live>> {
    let live = Arc::new(Live {
        count: AtomicUsize::new(0),
        idle: Notify::new(),
    });
    lua.set_app_data(live.clone());
    let t = lua.create_table()?;

    // luau[AzaleaLib]: --- Joins a server with a new bot and returns it once it is created (yields; the login itself continues in the background, wait for `init`/`login` events as usual). `account` is a name (offline), `{ name }` or `{ microsoft = cache key }`; `address` is "host[:port]"; `proxy` is an optional SOCKS5 "ip:port" (no login). The returned bot has its own `on`/`wait_for` handlers.
    // luau[AzaleaLib]: join: (opts: { account: string | { name: string? , microsoft: string? }, address: string, proxy: string? }) -> Bot
    t.set(
        "join",
        lua.create_async_function(|lua, opts: Table| async move {
            let account = account_of(opts.get("account")?).await?;
            let live: Arc<Live> = match lua.app_data_ref::<Arc<Live>>() {
                Some(l) => l.clone(),
                None => return Err(lua_err("azalea.join: not installed")),
            };
            let address: Option<String> = opts.get("address")?;
            let address = address.ok_or_else(|| lua_err("azalea.join: `address` is required"))?;
            let proxy: Option<String> = opts.get("proxy")?;
            let (client, rx) = match proxy {
                Some(p) => {
                    let addr: SocketAddr = p.parse().map_err(|_| {
                        lua_err(format!("azalea.join: proxy `{p}` is not an `ip:port`"))
                    })?;
                    Client::join_with_proxy(account, address.as_str(), Proxy::new(addr, None))
                        .await
                        .map_err(lua_err)?
                }
                None => Client::join(account, address.as_str())
                    .await
                    .map_err(lua_err)?,
            };
            let handlers = Arc::new(Handlers::default());
            start_event_pump(&client, lua.clone(), handlers.clone(), live, rx);
            Ok(LuaClient { client, handlers })
        })?,
    )?;

    // luau[AzaleaLib]: --- Yields until every bot made by `join` / `swarm:add` has disconnected and every swarm has ended (returns at once when there is none). Only needed to run code after that: the process stays up on its own while they are alive, even after the script has ended.
    // luau[AzaleaLib]: wait: () -> ()
    t.set(
        "wait",
        lua.create_async_function(|lua, ()| async move {
            let live: Arc<Live> = lua
                .app_data_ref::<Arc<Live>>()
                .map(|l| l.clone())
                .ok_or_else(|| lua_err("azalea.wait: not installed"))?;
            live.wait_idle().await;
            Ok(())
        })?,
    )?;

    // luau[AzaleaLib]: --- Starts an azalea Swarm that joins `address` and returns it once it is running (yields). Add bots with `swarm:add(account)`; `swarm:exit()` ends the whole swarm.
    // luau[AzaleaLib]: swarm: (opts: { address: string }) -> Swarm
    t.set(
        "swarm",
        lua.create_async_function(|lua, opts: Table| async move {
            let address: Option<String> = opts.get("address")?;
            let address = address.ok_or_else(|| lua_err("azalea.swarm: `address` is required"))?;
            let live: Arc<Live> = lua
                .app_data_ref::<Arc<Live>>()
                .map(|l| l.clone())
                .ok_or_else(|| lua_err("azalea.swarm: not installed"))?;
            let (tx, rx) = tokio::sync::oneshot::channel::<Swarm>();
            let init = SwarmInit {
                tx: Arc::new(std::sync::Mutex::new(Some(tx))),
            };
            let builder = SwarmBuilder::new()
                .set_handler(on_bot_event)
                .set_swarm_handler(on_swarm_event)
                .set_swarm_state(init);
            live.enter();
            let swarm_live = live.clone();
            tokio::task::spawn_local(async move {
                // a swarm that fails to start (bad address, ...) used to end silently: the caller only saw "ended before it started"
                let exit = builder.start(address.as_str()).await;
                if exit.is_error() {
                    eprintln!("[luau] swarm ended with an error: {exit:?}");
                }
                swarm_live.leave();
            });
            let swarm = rx
                .await
                .map_err(|_| lua_err("azalea.swarm: the swarm ended before it started"))?;
            Ok(LuaSwarm { swarm, lua, live })
        })?,
    )?;

    let process = lua.create_table()?;
    // luau[ProcessLib]: --- Ends the process at once with exit code `code` (default 0), whatever bots / swarms are still running.
    // luau[ProcessLib]: exit: (code: number?) -> ()
    process.set(
        "exit",
        lua.create_function(|_, code: Option<i32>| -> mlua::Result<()> {
            // exit skips destructors, so children from `@lune/process` would be left running (the lune module's own `exit` does the same)
            super::Runtime::kill_children();
            std::process::exit(code.unwrap_or(0))
        })?,
    )?;
    lua.globals().set("process", process)?;

    lua.globals().set("azalea", t)?;
    Ok(live)
}

#[derive(Clone, Component, Default)]
struct BotSink {
    tx: Option<tokio::sync::mpsc::UnboundedSender<Event>>,
}

#[derive(Clone, Default, Resource)]
struct SwarmInit {
    tx: Arc<std::sync::Mutex<Option<tokio::sync::oneshot::Sender<Swarm>>>>,
}

async fn on_bot_event(_bot: Client, event: Event, state: BotSink) -> anyhow::Result<()> {
    if let Some(tx) = &state.tx {
        let _ = tx.send(event);
    }
    Ok(())
}

async fn on_swarm_event(swarm: Swarm, event: SwarmEvent, state: SwarmInit) -> anyhow::Result<()> {
    if matches!(event, SwarmEvent::Init) {
        if let Some(tx) = state.tx.lock().ok().and_then(|mut g| g.take()) {
            let _ = tx.send(swarm);
        }
    }
    Ok(())
}

#[derive(UserData)]
pub struct LuaSwarm {
    #[lua(skip)]
    swarm: Swarm,
    #[lua(skip)]
    lua: Lua,
    #[lua(skip)]
    live: Arc<Live>,
}

#[mlua::userdata_impl]
impl LuaSwarm {
    // luau[Swarm]: --- Adds a bot to the swarm and returns it once it exists (yields). `account` is a name (offline), `{ name }` or `{ microsoft = cache key }`. The bot has its own `on`/`wait_for` handlers, like one from `azalea.join`.
    // luau[Swarm]: function add(self, account: string | { name: string?, microsoft: string? }): Bot
    async fn add(&self, account: Value) -> mlua::Result<LuaClient> {
        let account = account_of(account).await?;
        let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
        let client = self.swarm.add(&account, BotSink { tx: Some(tx) }).await;
        let handlers = Arc::new(Handlers::default());
        start_event_pump(
            &client,
            self.lua.clone(),
            handlers.clone(),
            self.live.clone(),
            rx,
        );
        Ok(LuaClient { client, handlers })
    }

    // luau[Swarm]: --- Ends the whole swarm (every bot in it).
    // luau[Swarm]: function exit(self): ()
    fn exit(&self) -> mlua::Result<()> {
        self.swarm.exit();
        Ok(())
    }
}
