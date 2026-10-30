# Fuzzing tools/zenpel_gen.py: what broke and how it was fixed

To run it: `cd tools/fuzz && python3 run.py` (510 cases), `python3 run.py --wave2` (105 more), and `cases3.py` (6 more).
Each case is the fake azalea crate plus one piece of ugly Rust. `python3 tools/fuzz/regress.py` checks that every fix below still holds, and check.sh runs it.

Not checked yet: the generated code was never built with cargo while this was written, and no Luau analyzer was run on the output.
One gap that was open at first: the rustdoc front end's `RdjIndex.is_clone` returned None (unknown), so the non-Clone `Arc` skip didn't work there. That is fixed now, see the last section.

| # | Was | Fix |
|---|-----|-----|
| 1 | RecursionError on recursive types (`Tree{kids:Vec<Tree>}`, Ping/Pong) | `Mapper.building` guard -> Skip "contains itself" |
| 2 | IsADirectoryError for a dir named `x.rs` | `is_file()` |
| 3 | "could not find enum Event" with two pub ones | prefer the one in the crate root / re-exported there; else error lists them |
| 4 | generated method == hand-written extra name (profile, physics, ...) -> duplicate fn + d.luau entry; struct `Item`/`string` -> duplicate/shadowed `type` | `extras_reserved()` (extra_*.rs impl blocks + `// luau[..]` lines), `on`/`wait_for`, `__*`; `taken_luau_names()` for types |
| 5 | `(*v).clone()` on non-Clone T through Arc (`Option<Arc<T>>`, `Arc<Vec<ConnectionError>>`) | `Mapper.not_clone` + `Index.is_clone` (derive/`impl Clone`); Skip with reason |
| 6 | `r#` leaked into Luau names/params/keys | `bare()` everywhere on the Luau side; Rust call sites keep `r#` |
| 7 | Luau keywords as record fields (`{ end: number }`) | `luau_field()` -> `["end"]: number` |
| 8 | goal structs with the same snake name -> duplicate `goto_sg` | goals() skips the later one (goal note) |
| 9 | events snaking to the same name | later one skipped, note in GEN_REPORT; enums with colliding variant strings skipped |
| 10 | `m!(..);` macros writing `impl Client`, `type C2 = Client; impl C2` dropped silently | indexed: macro_rules with `impl <class>` reported under "Macros not expanded"; alias impls resolved |
| 11 | non-ASCII names, NUL/bidi controls copied to d.luau | non-ASCII method/param/field names Skipped; docs sanitised |

Correction to an earlier version of this file: events whose payload can't be converted were never silent. GEN_REPORT "Events > Notes" lists them.
Left as is: u64/i64/usize become Luau numbers (precision above 2^53); two pub `enum Event` in the same crate root stay a (now accurate) error.

## Rustdoc front end
I ran every case through the old source-parsing front end and through rustdoc 1.91 JSON (`AZL_RDJ_FORMAT_RANGE=56-56`) and compared:
506 came out identical, 69 were rejected by rustdoc (invalid Rust), and 46 differed. Fixed, in code both front ends share:
- `RdjIndex.is_clone` implemented (derived impls via `def_attrs` + hand-written `impl Clone`); non-Clone `Arc<T>` is skipped under rustdoc too.
- Rustdoc JSON drops `r#`: record fields / goal fields are emitted through `rust_ident()` (`v.r#type`, not the uncompilable `v.type`).
- Docs from rustdoc skipped the sanitiser: `clean_doc()` now runs at emit time. Struct names written `r#T` no longer vanish.
- `source_digest` crashed on a directory named `x.rs` (rustdoc path).
What still differs is just how the two front ends see the code, not bugs: rustdoc expands macros (finds `impl Client` macro methods, unions, cfg-selected
items, `impl` inside fn bodies, `self: &Self`) and drops `#[doc(hidden)]` variants. `r#Loop` vs `Loop` is the same identifier.
Still unchecked: real azalea through rustdoc (AZALEA_RDJ), and any cargo build of the generated code.
