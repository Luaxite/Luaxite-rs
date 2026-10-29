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

The process exits when nothing is left to run (bots, swarms, tasks, servers, child processes), or when `process.exit` is called.

## Example

```luau
local bot = azalea.join { account = "Luaxite", address = "localhost" }

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

Scripts have access to azalea global and require `@lune/*` modules.
main.luau is required.

## Binding your own Rust code

### Macro
Rust code under `rust/` (`main.rs` and any module it declares) can be exposed to scripts as Luau globals, with no glue:

`#[bind]` binds this function.
```rust
use luaxite_bind::bind;

#[bind]
pub fn Name() {
    // code here
}
```

### Flags

To set bindings config place a comment in
**line 1** of a file,
`//BIND *Type`

#### Types

all - All the top level functions.
pub - Only public functions
macro - Only macro (`#[bind]`)

To use the mlua instance itself, take `&mlua::Lua` as the first parameter (Luau does not see it);
other Rust code can call `luau::current_lua()`,
and a `Runtime` has `lua()`.

main (not required) runs on start once. cannot be binded.

## Binding other crates

Crates get Luau bindings by sitting in `bind/`, nothing else: `bind/<name>/` with its own `Cargo.toml`, or a workspace checkout `bind/<name>-src/` that holds the crate `<name>/` (azalea is `bind/azalea-src/azalea`). Path crates those depend on are bound too.

## Lune

`require("@lune/<name>")` supports nine of Lune's modules:

- **Lune's own crates:** `fs`, `serde`, `regex`, `datetime`, `luau`
- **Reimplemented:** `net`, `process`, `stdio`, `task`

The second group is rewritten because Lune's versions depend on its
task scheduler, which doesn't build with mlua's `send` feature.
Their edge cases may differ from real Lune.
`@lune/roblox` is not supported. Requires the `lune` cargo feature
(on by default).

## API Documentation

The API documentation contains signatures, types, and definitions, but no usage examples.
Refer to the [Azalea documentation](https://azalea.matdoes.dev/azalea/) for usage examples.

[View the API documentation](https://github.com/Luaxite/Luaxite-rs/releases/tag/api-latest).

## License

This project is licensed under the [MIT License](LICENSE.md).

## Slop?

yes, i made this entirely with Claude desktop app.
there wasn't an existing project that did this or any bindings gen for mlua.