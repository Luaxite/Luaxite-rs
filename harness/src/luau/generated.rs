// Harness copy of generated.rs: the committed gen_*.rs (tools/zenpel_gen.py on harness/fake) and no embedded scripts.
mod gen_client;
mod gen_events;
mod gen_types;
// The host's `binds` (OUT_DIR/binds.rs from tools/bind_gen.py) has nothing to bind in the harness: an empty register, same signature.
mod binds {
    pub fn register(lua: &mlua::Lua) -> mlua::Result<()> {
        let _ = lua;
        Ok(())
    }
}
#[allow(dead_code)]
mod scripts {
    pub const MAIN: &str = "";
    pub const SCRIPTS: &[(&str, &str)] = &[];
}

// Harness only (the real host runs scripts through `run_standalone` and has no `Runtime::handle`): feeds the fake azalea's events
// to harness/test.luau. `Init` runs the script with the `bot` global set; every other event goes to the generated dispatcher.
impl Runtime {
    pub async fn handle(
        &self,
        bot: azalea::prelude::Client,
        event: azalea::prelude::Event,
    ) -> anyhow::Result<()> {
        use azalea::prelude::Event;
        if matches!(event, Event::Init) {
            self.lua.globals().set(
                "bot",
                LuaClient {
                    client: bot,
                    handlers: self.handlers.clone(),
                },
            )?;
            let chunk = self
                .lua
                .load(self.source.as_str())
                .set_name(format!("@{}", self.name));
            if let Err(e) = chunk.exec_async().await {
                eprintln!("[luau] script error: {e}");
            }
            return Ok(());
        }
        let closing = matches!(event, Event::Disconnect(_) | Event::ConnectionFailed(_));
        let fired = gen_events::dispatch(&self.lua, &self.handlers, event).await;
        if closing {
            self.handlers.close_waiters();
        }
        fired?;
        Ok(())
    }
}
