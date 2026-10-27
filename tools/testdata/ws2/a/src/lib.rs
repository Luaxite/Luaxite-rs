//! ws2 crate `a`: depends on `b` by path. Everything `b` defines shows up here only as `paths` summaries.

pub use b as base;
pub use b::geom::Dir::North;
pub use b::geom::Vec3;

/// Uses three types of `b`.
pub struct Bot {
    pub pos: Vec3,
    pub facing: b::geom::Dir,
    pub marks: Vec<b::Marker>,
}

pub enum Cmd {
    Go(Vec3),
    Face(b::geom::Dir),
}

pub type Facing = b::geom::Dir;
