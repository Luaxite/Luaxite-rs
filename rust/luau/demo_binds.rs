//BIND pub
// Sample of the `//BIND` header: line 1 of a file under rust/ selects its fns (`pub` = only `pub fn`, `all` = every fn, `macro` = only `#[bind]` ones).
// Every selected fn becomes a Luau global of the same name (tools/bind_gen.py, run by build.rs). Types: ints, floats, bool, String, Option<those>;
// return: nothing, one of those, or Result<T, E: Display> (Err raises a Luau error). A first `&mlua::Lua` param is the state itself, hidden from Luau.
// Copy this file's pattern for your own: it is the whole recipe. (`demo_*` names keep the globals clear of the API.)

/// `demo_add(2, 3) --> 5`
pub fn demo_add(a: i64, b: i64) -> i64 {
    a + b
}

/// `demo_greet("Bob") --> "hello, Bob!"`, `demo_greet(nil) --> "hello, world!"`
pub fn demo_greet(name: Option<String>) -> String {
    format!("hello, {}!", name.as_deref().unwrap_or("world"))
}

/// `demo_div(7, 2) --> 3.5`; dividing by zero raises a Luau error.
pub fn demo_div(a: f64, b: f64) -> Result<f64, String> {
    if b == 0.0 { Err("division by zero".to_string()) } else { Ok(a / b) }
}

/// The mlua instance: `demo_set_global("answer", 42)` then `print(answer)`. Rust can do anything with `lua` here.
pub fn demo_set_global(lua: &mlua::Lua, name: String, value: f64) -> mlua::Result<()> {
    lua.globals().set(name, value)
}
