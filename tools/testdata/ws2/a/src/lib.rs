

pub use b as base;
pub use b::geom::Dir::North;
pub use b::geom::Vec3;


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
