CASES = {}
def case(name, items="", variants=(), files=None): CASES[name] = (items, list(variants), files)
case("event_private_other_mod", "mod hidden { enum Event { A } }")
case("event_in_cfg_test", "#[cfg(test)] mod tests { pub enum Event { A } }")
case("event_in_fn_body", "fn f() { enum Event { A } }")
case("event_private_root_sibling", "pub mod m { pub(crate) enum Event { A } }")
case("two_client_structs_private", "mod p { struct Client; impl Client { pub fn nope(&self) {} } }")
case("ev_arc_vec_noclone", "pub struct NC { pub a: i32 }", ["AVN(Arc<Vec<NC>>)", "OAN(Option<Arc<NC>>)"])
