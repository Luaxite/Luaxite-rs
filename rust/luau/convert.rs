use azalea::{
    BlockPos, Vec3,
    container::{ContainerHandle, ContainerHandleRef},
    core::entity_id::MinecraftEntityId,
    inventory::{ItemStack, Menu},
    pathfinder::PathfinderOpts,
};
use mlua::{FromLua, IntoLua, Lua, Table, UserData, Value};

pub fn lua_err<E: std::fmt::Display>(e: E) -> mlua::Error {
    mlua::Error::runtime(e.to_string())
}

fn table(value: Value, what: &str) -> mlua::Result<Table> {
    match value {
        Value::Table(t) => Ok(t),
        other => Err(mlua::Error::runtime(format!(
            "expected {what}, got {}",
            other.type_name()
        ))),
    }
}

fn num(t: &Table, key: &str, what: &str) -> mlua::Result<f64> {
    t.get::<f64>(key)
        .map_err(|_| mlua::Error::runtime(format!("{what}: field `{key}` must be a number")))
}

pub struct LBlockPos(pub BlockPos);

impl FromLua for LBlockPos {
    fn from_lua(value: Value, _: &Lua) -> mlua::Result<Self> {
        let t = table(value, "a BlockPos table `{ x, y, z }`")?;
        let c = |k: &str| {
            let n = num(&t, k, "BlockPos")?;
            let f = n.floor();
            if f.is_nan() || f < i32::MIN as f64 || f > i32::MAX as f64 {
                return Err(mlua::Error::runtime(format!(
                    "BlockPos: field `{k}` is {n}, not a usable block coordinate"
                )));
            }
            Ok(f as i32)
        };
        Ok(Self(BlockPos::new(c("x")?, c("y")?, c("z")?)))
    }
}

impl IntoLua for LBlockPos {
    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {
        let t = lua.create_table()?;
        t.set("x", self.0.x)?;
        t.set("y", self.0.y)?;
        t.set("z", self.0.z)?;
        Ok(Value::Table(t))
    }
}

pub struct LVec3(pub Vec3);

impl FromLua for LVec3 {
    fn from_lua(value: Value, _: &Lua) -> mlua::Result<Self> {
        let t = table(value, "a Vec3 table `{ x, y, z }`")?;
        Ok(Self(Vec3::new(
            num(&t, "x", "Vec3")?,
            num(&t, "y", "Vec3")?,
            num(&t, "z", "Vec3")?,
        )))
    }
}

impl IntoLua for LVec3 {
    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {
        let t = lua.create_table()?;
        t.set("x", self.0.x)?;
        t.set("y", self.0.y)?;
        t.set("z", self.0.z)?;
        Ok(Value::Table(t))
    }
}

pub struct LBool(pub bool);

impl FromLua for LBool {
    fn from_lua(value: Value, _: &Lua) -> mlua::Result<Self> {
        match value {
            Value::Boolean(b) => Ok(Self(b)),
            other => Err(lua_err(format!(
                "expected boolean, got {}",
                other.type_name()
            ))),
        }
    }
}

pub struct LMinecraftEntityId(pub MinecraftEntityId);

impl FromLua for LMinecraftEntityId {
    fn from_lua(value: Value, lua: &Lua) -> mlua::Result<Self> {
        let n = <f64 as FromLua>::from_lua(value, lua)?;
        if n.fract() != 0.0 || n < i32::MIN as f64 || n > i32::MAX as f64 {
            return Err(mlua::Error::runtime(format!(
                "expected an integer entity id, got {n}"
            )));
        }
        Ok(Self(MinecraftEntityId(n as i32)))
    }
}

impl IntoLua for LMinecraftEntityId {
    fn into_lua(self, _: &Lua) -> mlua::Result<Value> {
        Ok(Value::Number(self.0.0 as f64))
    }
}

pub struct LPathfinderOpts(pub PathfinderOpts);

impl FromLua for LPathfinderOpts {
    fn from_lua(value: Value, _: &Lua) -> mlua::Result<Self> {
        let mut opts = PathfinderOpts::new();
        match value {
            Value::Nil => {}
            Value::Table(t) => {
                for pair in t.pairs::<Value, Value>() {
                    let (key, _) = pair?;
                    match &key {
                        Value::String(k)
                            if matches!(&*k.to_str()?, "allow_mining" | "retry_on_no_path") => {}
                        Value::String(k) => {
                            return Err(mlua::Error::runtime(format!(
                                "unknown PathfinderOpts field `{}` (known: allow_mining, retry_on_no_path)",
                                k.to_string_lossy()
                            )));
                        }
                        other => {
                            return Err(mlua::Error::runtime(format!(
                                "PathfinderOpts keys must be strings, got {}",
                                other.type_name()
                            )));
                        }
                    }
                }
                if let Some(b) = t.get::<Option<LBool>>("allow_mining")? {
                    opts = opts.allow_mining(b.0);
                }
                if let Some(b) = t.get::<Option<LBool>>("retry_on_no_path")? {
                    opts = opts.retry_on_no_path(b.0);
                }
            }
            other => {
                return Err(mlua::Error::runtime(format!(
                    "expected a PathfinderOpts table, got {}",
                    other.type_name()
                )));
            }
        }
        Ok(Self(opts))
    }
}

pub struct LItem(pub ItemStack);

impl IntoLua for LItem {
    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {
        let Some(stack) = self.0.as_present() else {
            return Ok(Value::Nil);
        };
        let t = lua.create_table()?;
        t.set("kind", stack.kind.to_string())?;
        t.set("count", stack.count)?;
        Ok(Value::Table(t))
    }
}

pub struct LSlots(pub Vec<ItemStack>);

impl IntoLua for LSlots {
    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {
        let t = lua.create_table_with_capacity(self.0.len(), 0)?;
        for (i, stack) in self.0.into_iter().enumerate() {
            t.raw_set(
                i + 1,
                match LItem(stack).into_lua(lua)? {
                    Value::Nil => Value::Boolean(false),
                    item => item,
                },
            )?;
        }
        Ok(Value::Table(t))
    }
}

pub struct LMenu(pub Menu);

fn menu_kind(menu: &Menu) -> String {
    let dbg = format!("{menu:?}");
    let name = dbg
        .split(|c: char| !c.is_alphanumeric())
        .next()
        .unwrap_or("");
    let mut out = String::new();
    let (mut prev, mut prev2): (Option<char>, Option<char>) = (None, None);
    for c in name.chars() {
        let dims_x = prev == Some('x') && prev2.is_some_and(|p| p.is_ascii_digit());
        let boundary = prev.is_some_and(|p| {
            (c.is_uppercase() && !p.is_uppercase())
                || (c.is_ascii_digit() && p.is_alphabetic() && !dims_x)
        });
        if boundary {
            out.push('_');
        }
        out.extend(c.to_lowercase());
        (prev2, prev) = (prev, Some(c));
    }
    out
}

impl IntoLua for LMenu {
    fn into_lua(self, lua: &Lua) -> mlua::Result<Value> {
        let t = lua.create_table()?;
        t.set("kind", menu_kind(&self.0))?;
        t.set("slots", LSlots(self.0.slots()))?;
        Ok(Value::Table(t))
    }
}

pub enum Held {
    Owned(ContainerHandle),
    Borrowed(ContainerHandleRef),
}

impl std::ops::Deref for Held {
    type Target = ContainerHandleRef;

    fn deref(&self) -> &ContainerHandleRef {
        match self {
            Held::Owned(handle) => &**handle,
            Held::Borrowed(handle) => handle,
        }
    }
}

impl Held {
    #[cfg(not(feature = "real"))]
    pub fn release(self) {
        match self {
            Held::Owned(handle) => drop(handle),
            Held::Borrowed(handle) => handle.close(),
        }
    }
}

#[derive(UserData)]
pub struct LuaContainer {
    #[lua(skip)]
    pub handle: Option<Held>,
}
