use azalea::protocol::packets::ConnectionProtocol;
use mlua::{Function, Lua, Table};

use super::{convert::lua_err, gen_client::LuaClient, gen_packets_out};

fn state_name(state: ConnectionProtocol) -> &'static str {
    match state {
        ConnectionProtocol::Handshake => "handshake",
        ConnectionProtocol::Game => "game",
        ConnectionProtocol::Status => "status",
        ConnectionProtocol::Login => "login",
        ConnectionProtocol::Configuration => "configuration",
    }
}

fn state_from_name(name: &str) -> mlua::Result<ConnectionProtocol> {
    match name {
        "handshake" => Ok(ConnectionProtocol::Handshake),
        "game" => Ok(ConnectionProtocol::Game),
        "status" => Ok(ConnectionProtocol::Status),
        "login" => Ok(ConnectionProtocol::Login),
        "configuration" => Ok(ConnectionProtocol::Configuration),
        other => Err(lua_err(format!(
            "unknown connection state '{other}' (handshake, game, status, login, configuration)"
        ))),
    }
}

fn snapshot(
    lua: &Lua,
    state: ConnectionProtocol,
    alive: bool,
    injected: Vec<Vec<u8>>,
) -> mlua::Result<Table> {
    let table = lua.create_table()?;
    table.set("state", state_name(state))?;
    table.set("is_alive", alive)?;
    let list = lua.create_table()?;
    for (i, bytes) in injected.into_iter().enumerate() {
        list.set(i + 1, lua.create_string(&bytes)?)?;
    }
    table.set("injected", list)?;
    Ok(table)
}

fn read_injected(conn: &Table) -> mlua::Result<Vec<Vec<u8>>> {
    let list: Table = conn.get("injected")?;
    let mut out = Vec::new();
    for item in list.sequence_values::<mlua::String>() {
        out.push(item?.as_bytes().to_vec());
    }
    Ok(out)
}



fn merge_injected(old: &[Vec<u8>], new: Vec<Vec<u8>>, live: Vec<Vec<u8>>) -> Vec<Vec<u8>> {
    if live == old {
        return new;
    }
    let mut out = live;
    let mut added = new;
    for item in old {
        match added.iter().position(|x| x == item) {
            Some(i) => {
                added.remove(i);
            }
            None => {
                if let Some(i) = out.iter().position(|x| x == item) {
                    out.remove(i);
                }
            }
        }
    }
    out.extend(added);
    out
}

#[cfg(test)]
mod tests {
    use super::merge_injected;

    fn v(items: &[&str]) -> Vec<Vec<u8>> {
        items.iter().map(|s| s.as_bytes().to_vec()).collect()
    }

    #[test]
    fn merge_keeps_concurrent_changes() {
        
        assert_eq!(
            merge_injected(&v(&["a"]), v(&["a", "b"]), v(&["a"])),
            v(&["a", "b"])
        );
        
        assert_eq!(
            merge_injected(&v(&["a"]), v(&["a", "b"]), v(&["a", "x"])),
            v(&["a", "x", "b"])
        );
        
        assert_eq!(
            merge_injected(&v(&["a", "b"]), v(&["b"]), v(&["a", "b", "x"])),
            v(&["b", "x"])
        );
        
        assert_eq!(
            merge_injected(&v(&["a", "b"]), v(&["a"]), v(&["a"])),
            v(&["a"])
        );
    }
}

#[mlua::userdata_impl]
impl LuaClient {
    
    
    fn write_packet(&self, lua: &Lua, kind: String, fields: Option<Table>) -> mlua::Result<()> {
        let fields = match fields {
            Some(t) => t,
            None => lua.create_table()?,
        };
        let packet = gen_packets_out::packet_from_table(&kind, &fields)?;
        self.client.write_packet(packet);
        Ok(())
    }

    
    
    fn raw_connection(&self, lua: &Lua) -> mlua::Result<Table> {
        let (state, alive, injected) = self
            .client
            .with_raw_connection(|c| {
                let injected: Vec<Vec<u8>> = c
                    .injected_clientbound_packets
                    .iter()
                    .map(|p| p.to_vec())
                    .collect();
                (c.state, c.is_alive(), injected)
            })
            .map_err(lua_err)?;
        snapshot(lua, state, alive, injected)
    }

    
    
    async fn raw_connection_mut(&self, lua: Lua, f: Function) -> mlua::Result<()> {
        let conn = self.raw_connection(&lua)?;
        
        let old_state = conn.get::<String>("state")?;
        let old_injected = read_injected(&conn)?;
        f.call_async::<()>(conn.clone()).await?;
        let new_state = conn.get::<String>("state")?;
        let state = if new_state == old_state {
            None
        } else {
            Some(state_from_name(&new_state)?)
        };
        let new_injected = read_injected(&conn)?;
        self.client
            .with_raw_connection_mut(|mut c| {
                if let Some(state) = state {
                    c.state = state;
                }
                if new_injected != old_injected {
                    let live: Vec<Vec<u8>> = c
                        .injected_clientbound_packets
                        .iter()
                        .map(|p| p.to_vec())
                        .collect();
                    c.injected_clientbound_packets =
                        merge_injected(&old_injected, new_injected, live)
                            .into_iter()
                            .map(Vec::into_boxed_slice)
                            .collect();
                }
            })
            .map_err(lua_err)?;
        Ok(())
    }
}
