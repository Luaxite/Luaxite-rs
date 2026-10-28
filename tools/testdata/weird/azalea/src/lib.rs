
#![allow(dead_code)]

use std::collections::HashMap;

pub mod inner {
    pub mod deep {
        
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


pub struct Grid<const W: usize, const H: usize = 4> {
    pub cells: [u8; W],
}


pub struct Raw {
    pub r#type: u32,
}
pub enum Kind {
    r#Loop,
    Pair(u8, HashMap<String, Vec<Option<u32>>>),
}

pub trait Tick {
    
    async fn tick(&self) -> u32;
}

pub struct Client;
pub struct EntityRef;

impl Client {
    
    pub fn nested(&self, m: HashMap<String, Vec<Option<(u8, u16)>>>) -> Option<Vec<u32>> { None }
    
    pub fn imp(&self, f: impl Fn(u32) -> u32 + Send) -> impl Iterator<Item = u32> { std::iter::empty() }
    
    pub fn bound<T>(&self, t: T) -> u32 where T: Into<u32> + Copy { t.into() }
    
    pub fn mutref(&self, v: &mut Vec<u8>) {}
    
    pub fn r#match(&self) -> u32 { 0 }
    
    pub fn grid(&self, g: Grid<3, 4>) -> u32 { 0 }
    
    #[cfg(feature = "extra")]
    pub fn gated(&self) -> u32 { 0 }
    
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
    
    Odd(HashMap<String, Vec<Option<u32>>>),
}
