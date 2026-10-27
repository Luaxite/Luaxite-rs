# lune-utils 0.4.0 (patched copy)

Upstream: https://crates.io/crates/lune-utils/0.4.0 (https://github.com/lune-org/lune), licensed MPL-2.0.

The only change is in `src/table_builder.rs`: `TableBuilder::with_function`, `with_async_function` (and their future type) gain a
`mlua::MaybeSend` bound. luaxite builds mlua with its `send` feature, which turns `MaybeSend` into `Send`; upstream's closures have no such
bound, so the crate does not compile with `send` ("the trait bound `F: MaybeSend` is not satisfied"). Without `send` the bound is empty, so this
copy behaves exactly like upstream there.

Wired in with `[patch.crates-io]` in the root Cargo.toml. Remove both once upstream adds the bound.
