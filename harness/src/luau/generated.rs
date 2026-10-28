
mod gen_client;
mod gen_events;
mod gen_types;
#[allow(dead_code)]
mod scripts {
    pub const MAIN: &str = "";
    pub const SCRIPTS: &[(&str, &str)] = &[];
}



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
