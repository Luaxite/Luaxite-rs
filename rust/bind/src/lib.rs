//! `#[bind]`: marks a fn under `rust/` to be bound to the Luau state as a global of the same name.
//!
//! The attribute itself does nothing: it returns the item untouched. The binding is generated at build time, outside the compiler:
//! `build.rs` runs `tools/bind_gen.py` (which reads the fns `tools/bind_scan.py` selects) and `rust/luau/mod.rs` includes the result.
//! A file whose line 1 is `//BIND *pub` / `//BIND *all` selects its fns without needing this attribute.

use proc_macro::TokenStream;

/// Marks the fn for binding. Passthrough: the fn is emitted exactly as written.
#[proc_macro_attribute]
pub fn bind(_args: TokenStream, item: TokenStream) -> TokenStream {
    item
}
