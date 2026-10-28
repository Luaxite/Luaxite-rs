Task: luaxite project (root of this ZIP).

1. Fix paths/bugs. The harness stays where it is (harness/); do NOT move it into tests/.

2. rust/ (root) holds main.rs and its deps (rust/luau/*.rs). In main.rs and those deps, an attribute

#[bind]
pub fn Name() {
...
}

binds the function to mlua.

If line 1 of a file starts with a comment

//BIND *Type

then Type = pub (only public fns), all, macro (default).

3. Add a way to fetch the mlua instance so the script can do whatever it wants.
