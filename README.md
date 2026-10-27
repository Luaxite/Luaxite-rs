# Luaxite

## Installation

### Linux, macOS and Termux

```bash
curl -fsSL https://raw.githubusercontent.com/Luaxite/Luaxite-rs/HEAD/install.sh | sh
```

### Windows

In PowerShell (5.1 or newer):

```powershell
irm https://raw.githubusercontent.com/Luaxite/Luaxite-rs/HEAD/install.ps1 | iex
```

Release zips: Linux (`x86_64`, `aarch64`; static musl), Termux (`aarch64`, `x86_64`), macOS (`aarch64`, `x86_64`), Windows (`x86_64`, `aarch64`).

## Luau API

The list of everything scripts can call, generated from the bindings: the [`api-latest` release](https://github.com/Luaxite/Luaxite-rs/releases/tag/api-latest) (take `API_list.md`; run the `api-docs` workflow once if the page is missing, or run `cargo build` and read `types/API_list.md`; each binary release `vX` also has an `api-vX` one). `bindings.d.luau` in the same release is the definitions file for luau-lsp.

## Notes

- Async functions (`task.wait`, `bot:goto`, `net.*`, `process.*`, ...) work in the main script, in threads started with `task.spawn`, `task.defer` or `task.delay`, and inside plain `coroutine.wrap` / `coroutine.create` threads too: `coroutine.resume` / `coroutine.wrap` hand the wait up to whichever thread drives them, so the resuming code simply waits until the async call is done. (A thread you create yourself and never resume from such a thread stays suspended, as in any Luau runtime.)
- `require` of a module embedded in the binary may yield at its top level (`task.wait`, `net.*`, `process.*`). Requiring a module that is still loading (a cycle, or a second thread while the first one is waiting inside it) errors with `module '<key>' is still loading (cyclic require?)`. `@lune/*` modules load synchronously.
- Size and time limits: reads that collect everything (`stdio.readToEnd`, a child's `readToEnd`, `process.exec` stdout/stderr, `net.request` response bodies) fail with `<what> exceeds 64 MiB` past 64 MiB. `net.serve` answers a request body over 64 MiB with `413` and keeps serving. `net.request` and `process.exec` accept `options.timeout` (seconds) and have default limits: 120 s for the whole `net.request` and 600 s for `process.exec`; `timeout = 0` disables the limit. `process.create` takes no `timeout`. Child processes run in their own process group on Unix, and killing one kills its whole group.
- Breaking changes are listed in [CHANGELOG.md](CHANGELOG.md). Latest: `Bot:nearest_entities`, `nearest_entities_by`, `nearest_entity_by` and `any_entity_by` no longer include the bot itself.
