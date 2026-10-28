<p align="left"> <img src="https://raw.githubusercontent.com/Luaxite/Luaxite-rs/main/logo.svg" width="100"> </p>

# Luaxite /luˈæk.saɪt/

A small project that lets you code Minecraft bots in Luau instead of Rust, using [Azalea](https://github.com/azalea-rs/azalea).

It uses a generator to create Azalea bindings, though some bindings need to be handwritten.
You can add extra Cargo dependencies.

## Installation

### Linux, macOS, and Termux

```bash
curl -fsSL https://raw.githubusercontent.com/Luaxite/Luaxite-rs/HEAD/install.sh | sh
```

### Windows

Run in PowerShell 5.1+:

```powershell
irm https://raw.githubusercontent.com/Luaxite/Luaxite-rs/HEAD/install.ps1 | iex
```

## Running a script

```bash
luaxite bot.luau
```

The process runs until every bot has disconnected.

## Example

```luau
local bot = azalea.join { account = "Luaxide", address = "localhost" }

bot:on("spawn", function()
    bot:chat("spawned")
end)

bot:on("chat", function(packet)
    if packet.content == "foo" then
        bot:chat("bar")
    end
end)

bot:on("disconnect", function(reason)
    print("disconnected:", reason)
end)
```

## Luau

Scripts are plain Luau. `azalea` is a global, and `require` works for
modules in `src/` (embedded at build time) and for `@lune/*`.

## Binding your own Rust

Rust code under `rust/` (`main.rs` and any module it declares) can be exposed to scripts as Luau globals, with no glue:

```rust
use luaxite_bind::bind;

#[bind]
pub fn Name() {
    // ...
}
```

`#[bind]` binds that fn. Or put a comment on **line 1** of a file to choose which fns it binds: `//BIND pub` (only `pub fn`s), `//BIND all` (every fn), `//BIND macro` (only `#[bind]` fns; the default). See `rust_binds/luau/demo_binds.rs`.
Arguments and returns can be integers, floats, `bool`, `String` or `Option` of those; a `Result<T, E: Display>` return raises a Luau error. Generic, `self`, `async`, nested and test fns, fns inside an `impl` / `trait` / inline `mod`, and private fns of files other than `main.rs` and `rust_binds/luau/mod.rs` (the generated code cannot call them) are skipped with a build warning. A `#[cfg(..)]` on the fn or on the `mod x;` that declares its file is copied to the binding.

To use the mlua instance itself, take `&mlua::Lua` as the first parameter (Luau does not see it); other Rust code can call `luau::current_lua()`, and a `Runtime` has `lua()`.

## Lune

`require("@lune/<name>")` supports nine of Lune's modules:

- **Lune's own crates:** `fs`, `serde`, `regex`, `datetime`, `luau`
- **Reimplemented here:** `net`, `process`, `stdio`, `task`

The second group is rewritten because Lune's versions depend on its
task scheduler, which doesn't build with mlua's `send` feature.
Their edge cases may differ from real Lune.
`@lune/roblox` is not supported. Requires the `lune` cargo feature
(on by default).

## API Documentation

The API documentation contains signatures, types, and definitions, but no usage examples.
Refer to the [Azalea documentation](https://azalea.rs/azalea/) for usage examples.

[View the API documentation](https://github.com/Luaxite/Luaxite-rs/releases/tag/api-latest).

## License

This project is licensed under the [MIT License](LICENSE.md).

## Slop?

yes, i made this entirely with Claude desktop app.
there wasn't an existing project that did this or any bindings gen for mlua. ):
