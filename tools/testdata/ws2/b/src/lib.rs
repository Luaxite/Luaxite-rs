//! ws2 crate `b`: the types crate `a` uses and re-exports (tools/testdata/ws2, slice 9 cross-crate fixture).

pub mod geom {
    /// A point in space.
    pub struct Vec3 {
        pub x: f64,
        pub y: f64,
        pub z: f64,
    }

    /// Where something faces.
    pub enum Dir {
        North,
        Offset(i32),
        Pos { at: Vec3 },
    }
}

/// A unit marker.
pub struct Marker;
