use std::fmt::Write as _;

use azalea::{
    core::registry_holder::RegistryHolder, prelude::Client, registry::identifier::Identifier,
};
use mlua::{Lua, Table};

use super::{convert::lua_err, gen_client::LuaClient};

const REGISTRIES: &[&str] = &[
    "enchantment",
    "dimension_type",
    "chat_type",
    "trim_pattern",
    "trim_material",
    "wolf_variant",
    "wolf_sound_variant",
    "pig_variant",
    "frog_variant",
    "cat_variant",
    "cow_variant",
    "chicken_variant",
    "zombie_nautilus_variant",
    "painting_variant",
    "damage_type",
    "enchantment_provider",
    "jukebox_song",
    "instrument",
    "test_environment",
    "test_instance",
    "dialog",
    "timeline",
    "recipe",
    "worldgen/biome",
    "world_clock",
    "pig_sound_variant",
    "cat_sound_variant",
    "cow_sound_variant",
    "chicken_sound_variant",
    "banner_pattern",
];


fn short_name(raw: &str) -> &str {
    let short = raw.strip_prefix("minecraft:").unwrap_or(raw);
    if short == "biome" {
        "worldgen/biome"
    } else {
        short
    }
}


fn holder_extra_names(holder: &RegistryHolder) -> Vec<String> {
    holder
        .extra
        .keys()
        .map(|k| {
            let full = k.to_string();
            full.strip_prefix("minecraft:").unwrap_or(&full).to_string()
        })
        .collect()
}


fn kinds_of(client: &Client) -> Vec<String> {
    let mut kinds: Vec<String> = REGISTRIES.iter().map(|n| n.to_string()).collect();
    if let Ok(extra) = client.with_registry_holder(holder_extra_names) {
        for name in extra {
            if !kinds.contains(&name) {
                kinds.push(name);
            }
        }
    }
    kinds
}



fn registry_name(client: &Client, raw: &str) -> mlua::Result<String> {
    let short = short_name(raw);
    if REGISTRIES.contains(&short) {
        return Ok(short.to_string());
    }
    let sent = client
        .with_registry_holder(|holder| holder.extra.contains_key(&Identifier::new(short)))
        .unwrap_or(false);
    if sent {
        return Ok(short.to_string());
    }
    Err(lua_err(format!(
        "unknown registry `{raw}` (known: {})",
        kinds_of(client).join(", ")
    )))
}



fn visit<'a, K: std::fmt::Display + 'a, T>(
    keys: impl Iterator<Item = &'a K>,
    mut f: impl FnMut(usize, &str) -> Option<T>,
) -> Option<T> {
    let mut buf = String::new();
    for (index, key) in keys.enumerate() {
        buf.clear();
        let _ = write!(buf, "{key}");
        if let Some(found) = f(index, &buf) {
            return Some(found);
        }
    }
    None
}

fn scan_entries<T>(
    holder: &RegistryHolder,
    name: &str,
    f: impl FnMut(usize, &str) -> Option<T>,
) -> Option<T> {
    match name {
        "dimension_type" => visit(holder.dimension_type.map.keys(), f),
        "enchantment" => visit(holder.enchantment.map.keys(), f),
        _ => holder
            .extra
            .get(&Identifier::new(name))
            .and_then(|registry| visit(registry.map.keys(), f)),
    }
}

fn entry_names(holder: &RegistryHolder, name: &str) -> Vec<String> {
    let mut names = Vec::new();
    let _ = scan_entries::<()>(holder, name, |_, entry| {
        names.push(entry.to_string());
        None
    });
    names
}

fn entries_of(client: &Client, registry: &str) -> mlua::Result<Vec<String>> {
    let name = registry_name(client, registry)?;
    client
        .with_registry_holder(|holder| entry_names(holder, &name))
        .map_err(lua_err)
}


fn index_of(client: &Client, registry: &str, wanted: &str) -> mlua::Result<Option<usize>> {
    let name = registry_name(client, registry)?;
    client
        .with_registry_holder(|holder| {
            scan_entries(holder, &name, |index, entry| {
                (entry == wanted).then_some(index)
            })
        })
        .map_err(lua_err)
}

fn full_name(raw: &str) -> String {
    if raw.contains(':') {
        raw.to_string()
    } else {
        format!("minecraft:{raw}")
    }
}

#[mlua::userdata_impl]
impl LuaClient {
    
    
    #[lua(infallible)]
    fn registry_kinds(&self) -> Vec<String> {
        kinds_of(&self.client)
    }

    
    
    fn registry_entries(&self, registry: String) -> mlua::Result<Vec<String>> {
        entries_of(&self.client, &registry)
    }

    
    
    fn registry_resolve(&self, registry: String, name: String) -> mlua::Result<Option<u32>> {
        let wanted = full_name(&name);
        Ok(index_of(&self.client, &registry, &wanted)?.map(|i| i as u32))
    }

    
    
    fn registry_name(&self, registry: String, id: u32) -> mlua::Result<Option<String>> {
        let name = registry_name(&self.client, &registry)?;
        self.client
            .with_registry_holder(|holder| {
                scan_entries(holder, &name, |index, entry| {
                    (index == id as usize).then(|| entry.to_string())
                })
            })
            .map_err(lua_err)
    }

    
    
    fn registry_get(
        &self,
        lua: &Lua,
        registry: String,
        name: String,
    ) -> mlua::Result<Option<Table>> {
        let wanted = full_name(&name);
        let Some(index) = index_of(&self.client, &registry, &wanted)? else {
            return Ok(None);
        };
        let table = lua.create_table()?;
        table.set("name", wanted)?;
        table.set("id", index as u32)?;
        Ok(Some(table))
    }
}
