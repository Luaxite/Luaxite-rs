// Generated code + embedded scripts, included by mod.rs (the real host; the harness has its own copy of this file with its committed gen files).
// $OUT_DIR/inc/gen_*.rs = the generator's gen_*.rs minus the file-level `#![allow(..)]` (include! cannot take inner attributes; the allow is here).
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
// gen_packets_in: ClientboundGamePacket -> tables. gen_packets_out: Luau table -> ServerboundGamePacket (`bot:write_packet`).
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
// gen_ecs: azalea Component/Resource table + readers; real_ecs.rs lists it (`bot:ecs_names`).
#[cfg(feature = "real")]
#[allow(dead_code, unused_imports, unused_variables, clippy::all)]
mod gen_ecs {
    include!(concat!(env!("OUT_DIR"), "/inc/gen_ecs.rs"));
}
// `scripts::MAIN` = src/main.luau, `scripts::SCRIPTS` = every src/**.luau (module name -> text), written by build.rs.
mod scripts {
    include!(concat!(env!("OUT_DIR"), "/scripts.rs"));
}
