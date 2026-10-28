

pub mod geom {
    
    pub struct Vec3 {
        pub x: f64,
        pub y: f64,
        pub z: f64,
    }

    
    pub enum Dir {
        North,
        Offset(i32),
        Pos { at: Vec3 },
    }
}


pub struct Marker;
