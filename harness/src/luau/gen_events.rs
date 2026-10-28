
#![allow(dead_code, unused_imports, unused_variables, clippy::all)]

use azalea::Event;

use super::convert::*;
use super::gen_types::*;
use super::Handlers;


pub const EVENT_NAMES: &[&str] = &[
    "init",
    "login",
    "chat",
    "tick",
    "add_player",
    "keep_alive",
    "disconnect",
    "connection_failed",
    "death",
    "update",
];


pub async fn dispatch(lua: &mlua::Lua, handlers: &Handlers, event: Event) -> mlua::Result<()> {
    match event {
        Event::Init => handlers.fire(lua, "init", ()).await?,
        Event::Login => handlers.fire(lua, "login", ()).await?,
        Event::Chat(p) => {
            if handlers.has("chat") {
                let v = p;
                handlers.fire(lua, "chat", (LuaChatPacket(v),)).await?;
            }
        }
        Event::Tick => handlers.fire(lua, "tick", ()).await?,
        Event::AddPlayer(p) => {
            if handlers.has("add_player") {
                let v = p;
                handlers.fire(lua, "add_player", (LuaPlayerInfo(v),)).await?;
            }
        }
        Event::KeepAlive(p) => {
            if handlers.has("keep_alive") {
                let v = p;
                handlers.fire(lua, "keep_alive", (v,)).await?;
            }
        }
        Event::Disconnect(p) => {
            if handlers.has("disconnect") {
                let v = p;
                handlers.fire(lua, "disconnect", (v.map(|v| v.to_string()),)).await?;
            }
        }
        Event::ConnectionFailed(p) => {
            if handlers.has("connection_failed") {
                let v = p;
                handlers.fire(lua, "connection_failed", (v.to_string(),)).await?;
            }
        }
        Event::Death(p) => {
            if handlers.has("death") {
                let v = p;
                handlers.fire(lua, "death", (v.map(|v| LuaClientboundPlayerCombatKill((*v).clone())),)).await?;
            }
        }
        _ => {}
    }
    Ok(())
}
