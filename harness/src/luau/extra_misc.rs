use std::fmt::Display;

use azalea::{
    ClientInformation,
    entity::HumanoidArm,
    pathfinder::{PathfinderClientExt as _, goals::ReachBlockPosGoal},
    protocol::common::client_information::{ChatVisibility, ModelCustomization, ParticleStatus},
};
use mlua::{FromLua, Lua, Value};

use super::{
    convert::{LBlockPos, lua_err},
    gen_client::LuaClient,
};

const DEFAULT_REACH: f64 = 4.5;

fn bad(what: impl Display) -> mlua::Error {
    mlua::Error::runtime(format!("ClientInformation: {what}"))
}

fn boolean(v: Value, field: &str) -> mlua::Result<bool> {
    match v {
        Value::Boolean(b) => Ok(b),
        other => Err(bad(format!(
            "`{field}` must be a boolean, got {}",
            other.type_name()
        ))),
    }
}

fn pick<T: Copy>(v: Value, lua: &Lua, field: &str, names: &[(&str, T)]) -> mlua::Result<T> {
    let expected = || names.iter().map(|(n, _)| *n).collect::<Vec<_>>().join(", ");
    let s = match v {
        Value::String(_) => String::from_lua(v, lua)?,
        other => {
            return Err(bad(format!(
                "`{field}` must be a string (one of: {}), got {}",
                expected(),
                other.type_name()
            )));
        }
    };
    names
        .iter()
        .find(|(n, _)| *n == s)
        .map(|(_, t)| *t)
        .ok_or_else(|| {
            bad(format!(
                "invalid {field} '{s}', expected one of: {}",
                expected()
            ))
        })
}

fn model_customization(v: Value) -> mlua::Result<ModelCustomization> {
    let t = match v {
        Value::Table(t) => t,
        other => {
            return Err(bad(format!(
                "`model_customization` must be a table, got {}",
                other.type_name()
            )));
        }
    };
    let mut m = ModelCustomization::default();
    for pair in t.pairs::<String, Value>() {
        let (key, v) = pair?;
        let slot = match key.as_str() {
            "cape" => &mut m.cape,
            "jacket" => &mut m.jacket,
            "left_sleeve" => &mut m.left_sleeve,
            "right_sleeve" => &mut m.right_sleeve,
            "left_pants" => &mut m.left_pants,
            "right_pants" => &mut m.right_pants,
            "hat" => &mut m.hat,
            other => {
                return Err(bad(format!(
                    "unknown model_customization field `{other}` (known: cape, jacket, left_sleeve, right_sleeve, left_pants, right_pants, hat)"
                )));
            }
        };
        *slot = boolean(v, &format!("model_customization.{key}"))?;
    }
    Ok(m)
}

struct LClientInformation(ClientInformation);

impl FromLua for LClientInformation {
    fn from_lua(value: Value, lua: &Lua) -> mlua::Result<Self> {
        let t = match value {
            Value::Table(t) => t,
            other => return Err(bad(format!("expected a table, got {}", other.type_name()))),
        };
        let mut info = ClientInformation::default();
        for pair in t.pairs::<String, Value>() {
            let (key, v) = pair?;
            match key.as_str() {
                "language" => {
                    info.language = match v {
                        Value::String(_) => String::from_lua(v, lua)?,
                        other => {
                            return Err(bad(format!(
                                "`language` must be a string like \"en_us\", got {}",
                                other.type_name()
                            )));
                        }
                    }
                }
                "view_distance" => {
                    let n = match v {
                        Value::Integer(n) => n as f64,
                        Value::Number(n) => n,
                        other => {
                            return Err(bad(format!(
                                "`view_distance` must be a number, got {}",
                                other.type_name()
                            )));
                        }
                    };
                    if n.fract() != 0.0 || !(0.0..=255.0).contains(&n) {
                        return Err(bad(format!(
                            "`view_distance` must be a whole number of chunks from 0 to 255, got {n}"
                        )));
                    }
                    info.view_distance = n as u8;
                }
                "chat_visibility" => {
                    info.chat_visibility = pick(
                        v,
                        lua,
                        "chat_visibility",
                        &[
                            ("full", ChatVisibility::Full),
                            ("system", ChatVisibility::System),
                            ("hidden", ChatVisibility::Hidden),
                        ],
                    )?
                }
                "chat_colors" => info.chat_colors = boolean(v, "chat_colors")?,
                "model_customization" => info.model_customization = model_customization(v)?,
                "main_hand" => {
                    info.main_hand = pick(
                        v,
                        lua,
                        "main_hand",
                        &[("left", HumanoidArm::Left), ("right", HumanoidArm::Right)],
                    )?
                }
                "text_filtering_enabled" => {
                    info.text_filtering_enabled = boolean(v, "text_filtering_enabled")?
                }
                "allows_listing" => info.allows_listing = boolean(v, "allows_listing")?,
                "particle_status" => {
                    info.particle_status = pick(
                        v,
                        lua,
                        "particle_status",
                        &[
                            ("all", ParticleStatus::All),
                            ("decreased", ParticleStatus::Decreased),
                            ("minimal", ParticleStatus::Minimal),
                        ],
                    )?
                }
                other => {
                    return Err(bad(format!(
                        "unknown field `{other}` (known: language, view_distance, chat_visibility, chat_colors, model_customization, main_hand, text_filtering_enabled, allows_listing, particle_status)"
                    )));
                }
            }
        }
        Ok(Self(info))
    }
}

#[mlua::userdata_impl]
impl LuaClient {
    
    
    async fn goto_reach(&self, pos: LBlockPos, distance: Option<f64>) -> mlua::Result<()> {
        let distance = distance.unwrap_or(DEFAULT_REACH);
        if !distance.is_finite() || distance <= 0.0 {
            return Err(lua_err(format!(
                "goto_reach: distance must be a positive number, got {distance}"
            )));
        }
        let world = self.client.world().map_err(lua_err)?;
        let chunks = world.read().chunks.clone();
        self.client
            .goto(ReachBlockPosGoal::new_with_distance(
                pos.0, distance, chunks,
            ))
            .await;
        Ok(())
    }

    
    
    fn set_client_information(&self, info: LClientInformation) -> mlua::Result<()> {
        self.client.set_client_information(info.0).map_err(lua_err)
    }
}
