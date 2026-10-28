

#[allow(dead_code, unused_imports, unused_variables, clippy::all)]
mod gen_client {
    include!(concat!(env!("OUT_DIR"), "/inc/gen_client.rs"));
}
#[allow(dead_code, unused_imports, unused_variables, clippy::all)]
mod gen_events {
    include!(concat!(env!("OUT_DIR"), "/inc/gen_events.rs"));
}
#[allow(dead_code, unused_imports, unused_variables, clippy::all)]
mod gen_types {
    include!(concat!(env!("OUT_DIR"), "/inc/gen_types.rs"));
}

#[cfg(feature = "packets")]
#[allow(dead_code, unused_imports, unused_variables, clippy::all)]
mod gen_packets_in {
    include!(concat!(env!("OUT_DIR"), "/inc/gen_packets_in.rs"));
}
#[cfg(feature = "packets")]
#[allow(dead_code, unused_imports, unused_variables, clippy::all)]
mod gen_packets_out {
    include!(concat!(env!("OUT_DIR"), "/inc/gen_packets_out.rs"));
}

#[cfg(feature = "real")]
#[allow(dead_code, unused_imports, unused_variables, clippy::all)]
mod gen_ecs {
    include!(concat!(env!("OUT_DIR"), "/inc/gen_ecs.rs"));
}

mod scripts {
    include!(concat!(env!("OUT_DIR"), "/scripts.rs"));
}
