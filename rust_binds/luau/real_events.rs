use std::sync::Arc;

use azalea::prelude::Client;
use mlua::Lua;
use tokio::sync::broadcast::error::RecvError;

use super::{Handlers, gen_client::LuaClient};
#[cfg(feature = "packets")]
use super::{convert::lua_err, gen_packets_in};

pub fn start_update_pump(client: &Client, lua: Lua, handlers: Arc<Handlers>) {
    let mut updates = client.get_update_broadcaster();
    tokio::task::spawn_local(async move {
        loop {
            match updates.recv().await {
                Ok(()) | Err(RecvError::Lagged(_)) => {}
                Err(RecvError::Closed) => break,
            }
            if handlers.has("update") {
                if let Err(e) = handlers.fire(&lua, "update", ()).await {
                    super::note_error();
                    eprintln!("[luau] error in `update` handler: {e}");
                }
            }
        }
    });
}

#[mlua::userdata_impl]
impl LuaClient {
    // luau[Bot]: --- Yields until the next game tick (20 per second).
    // luau[Bot]: function wait_tick(self): ()
    #[lua(infallible)]
    async fn wait_tick(&self) {
        let mut ticks = self.client.get_tick_broadcaster();
        let _ = ticks.recv().await;
    }

    // luau[Bot]: --- Yields until the next ECS update (at least once per tick, usually faster).
    // luau[Bot]: function wait_update(self): ()
    #[lua(infallible)]
    async fn wait_update(&self) {
        let mut updates = self.client.get_update_broadcaster();
        let _ = updates.recv().await;
    }
}

#[cfg(feature = "packets")]
fn kind_key(kind: &str) -> String {
    format!("packet:{kind}")
}

#[cfg(feature = "packets")]
fn check_kind(kind: &str) -> mlua::Result<()> {
    if gen_packets_in::PACKET_KINDS.contains(&kind) {
        Ok(())
    } else {
        Err(lua_err(format!(
            "unknown packet kind '{kind}' (see the `ClientboundPacket` type in azalea.d.luau)"
        )))
    }
}

#[cfg(feature = "packets")]
pub async fn dispatch_packet(
    lua: &Lua,
    handlers: &Handlers,
    packet: &azalea::protocol::packets::game::ClientboundGamePacket,
) -> anyhow::Result<()> {
    let key = kind_key(gen_packets_in::packet_kind(packet));
    if handlers.has(&key) {
        let table = gen_packets_in::packet_to_table(lua, packet)?;
        handlers.fire(lua, &key, (table,)).await?;
    }
    if handlers.has("packet") {
        let table = gen_packets_in::packet_to_table(lua, packet)?;
        handlers.fire(lua, "packet", (table,)).await?;
    }
    Ok(())
}

#[cfg(feature = "packets")]
#[mlua::userdata_impl]
impl LuaClient {
    fn on_packet(&self, kind: String, handler: mlua::Function) -> mlua::Result<()> {
        check_kind(&kind)?;
        self.handlers.add(kind_key(&kind), handler);
        Ok(())
    }

    async fn wait_for_packet(&self, kind: String) -> mlua::Result<mlua::MultiValue> {
        check_kind(&kind)?;
        self.handlers.wait(&kind_key(&kind)).await
    }
}
