//! weird: constructs that make a rustdoc JSON reader earn its keep (slice 10). Hand-built JSON in ../rustdoc (no rustc here).
#![allow(dead_code)]

use std::collections::HashMap;

pub mod inner {
    pub mod deep {
        /// Reached through a re-export chain and a glob.
        pub struct Deep {
            pub n: u32,
        }
    }
    pub use self::deep::Deep as DeepAlias;
}
pub mod chain {
    pub use crate::inner::deep::*;
}
pub use chain::Deep;

/// Const generics.
pub struct Grid<const W: usize, const H: usize = 4> {
    pub cells: [u8; W],
}

/// Raw identifier field and variant.
pub struct Raw {
    pub r#type: u32,
}
pub enum Kind {
    r#Loop,
    Pair(u8, HashMap<String, Vec<Option<u32>>>),
}

pub trait Tick {
    /// async fn in trait
    async fn tick(&self) -> u32;
}

pub struct Client;
pub struct EntityRef;

impl Client {
    /// nested generics
    pub fn nested(&self, m: HashMap<String, Vec<Option<(u8, u16)>>>) -> Option<Vec<u32>> { None }
    /// impl Trait argument and return
    pub fn imp(&self, f: impl Fn(u32) -> u32 + Send) -> impl Iterator<Item = u32> { std::iter::empty() }
    /// where clause
    pub fn bound<T>(&self, t: T) -> u32 where T: Into<u32> + Copy { t.into() }
    /// mutable reference
    pub fn mutref(&self, v: &mut Vec<u8>) {}
    /// raw identifier method
    pub fn r#match(&self) -> u32 { 0 }
    /// const generic argument
    pub fn grid(&self, g: Grid<3, 4>) -> u32 { 0 }
    /// feature-gated: absent from the JSON when `extra` is off
    #[cfg(feature = "extra")]
    pub fn gated(&self) -> u32 { 0 }
    /// hidden
    #[doc(hidden)]
    pub fn hidden(&self) -> u32 { 0 }
    pub async fn waits(&self) -> u32 { 0 }
}

macro_rules! entity_fns {
    ($($n:ident),*) => { impl EntityRef { $(pub fn $n(&self) -> u32 { 0 })* } };
}
entity_fns!(health, hunger);

impl Tick for Client {
    async fn tick(&self) -> u32 { 0 }
}

pub enum Event {
    Init,
    Login,
    Tick,
    /// payload the bindings cannot convert
    Odd(HashMap<String, Vec<Option<u32>>>),
}
