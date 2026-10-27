from fuzz import M
CASES = {}
def case(name, items="", variants=()):
    CASES[name] = (items, list(variants))

U = "unimplemented!()"
def fn(sig, body=U): return f"    {sig} {{ {body} }}"

# ---- A. recursive / cyclic types
case("rec_self_struct", "#[derive(Clone)] pub struct Node { pub val: i32, pub next: Option<Box<Node>> }\n" + M(fn("pub fn node(&self) -> Node")))
case("rec_self_vec", "#[derive(Clone)] pub struct Tree { pub kids: Vec<Tree> }\n" + M(fn("pub fn tree(&self) -> Tree")))
case("rec_mutual", "#[derive(Clone)] pub struct Ping { pub p: Option<Arc<Pong>> }\n#[derive(Clone)] pub struct Pong { pub q: Vec<Ping> }\n" + M(fn("pub fn ping(&self) -> Ping")))
case("rec_event_payload", "#[derive(Clone)] pub struct Node { pub next: Option<Box<Node>> }", ["Rec(Node)"])
case("rec_param", "#[derive(Clone)] pub struct Node { pub next: Option<Box<Node>> }\n" + M(fn("pub fn take(&self, n: Node)")))
# ---- B. names
case("kw_end_and_end_", M(fn("pub fn end(&self)"), fn("pub fn end_(&self)")))
case("kw_raw_ident_method", M(fn("pub fn r#match(&self) -> i32", "0"), fn("pub fn r#fn(&self)"), fn("pub fn r#async(&self)")))
case("kw_luau_method_names", M(*[fn(f"pub fn {k}(&self)") for k in "and break do else elseif end false for function if in local nil not or repeat return then true until while continue export type".split()]))
case("kw_param_names", M(fn("pub fn p(&self, end: i32, function: i32, local: i32, nil: i32, r#type: i32, r#fn: i32)")))
case("kw_param_collide", M(fn("pub fn p(&self, end: i32, end_: i32)")))
case("param_self_name", M(fn("pub fn p(&self, self_: i32)")))
case("method_on", M(fn("pub fn on(&self)")))
case("method_goto_collision", M(fn("pub fn goto(&self)")))
case("method_underscore", M(fn("pub fn _under(&self)"), fn("pub fn __dunder__(&self)"), fn("pub fn m1_(&self)")))
case("method_unicode", M(fn("pub fn héllo(&self)"), fn("pub fn 名前(&self, 引数: i32)")))
case("method_caps", M(fn("pub fn HTTPGet(&self)"), fn("pub fn http_get(&self)")))
case("method_dup_across_impls", M(fn("pub fn twice(&self)")) + M(fn("pub fn twice(&self, x: i32)")))
case("method_dup_trait_inherent", "pub trait Ext { fn twice2(&self); }\nimpl Ext for Client { fn twice2(&self) {} }\n" + M(fn("pub fn twice2(&self)")))
case("method_nonascii_collide", M(fn("pub fn a(&self)"), fn("pub fn A(&self)")))
case("event_snake_collide", "", ["HTTPPing(u32)", "HttpPing(u32)"])
case("event_snake_collide2", "", ["Addplayer(u32)"])
case("event_kw_names", "", ["End", "Function(u32)", "r#Type", "Nil"])
case("event_unit_only_dup_of_builtin", "", ["Chat2(ChatPacket)", "Tick2"])
case("event_empty_name_digit", "", ["V2(u32)", "V2D(u32)", "A1B2(u32)", "X__Y(u32)", "_Lead(u32)"])
# ---- C. signature shapes
SIGS = {
 "self_value": "pub fn f(self)", "self_mut_value": "pub fn f(mut self)", "self_arc": "pub fn f(self: Arc<Self>)",
 "self_typed_ref": "pub fn f(self: &Self)", "self_mutref": "pub fn f(&mut self)", "self_lifetime": "pub fn f<'a>(&'a self)",
 "self_ref_lt": "pub fn f(&'static self)", "no_self": "pub fn f()", "ret_self": "pub fn f(&self) -> Self", "ret_never": "pub fn f(&self) -> !",
 "ret_unit": "pub fn f(&self) -> ()", "ret_tuple": "pub fn f(&self) -> (i32, f64)", "ret_tuple1": "pub fn f(&self) -> (i32,)",
 "ret_str_ref": "pub fn f(&self) -> &str", "ret_static": "pub fn f(&self) -> &'static str", "ret_opt_ref": "pub fn f(&self) -> Option<&str>",
 "ret_slice": "pub fn f(&self) -> &[u8]", "ret_array": "pub fn f(&self) -> [u8; 4]", "ret_array_const": "pub fn f(&self) -> [u8; { 2 + 2 }]",
 "ret_vvv": "pub fn f(&self) -> Vec<Vec<Vec<i32>>>", "ret_oo": "pub fn f(&self) -> Option<Option<i32>>",
 "ret_res_unit": "pub fn f(&self) -> Result<(), MissingComponentError>", "ret_res_box": "pub fn f(&self) -> Result<i32, Box<dyn std::error::Error>>",
 "ret_res_alias": "pub fn f(&self) -> AzaleaResult<i32>", "ret_res_res": "pub fn f(&self) -> Result<Result<i32, MissingComponentError>, MissingComponentError>",
 "ret_res_opt": "pub fn f(&self) -> Result<Option<i32>, MissingComponentError>", "ret_opt_res": "pub fn f(&self) -> Option<Result<i32, MissingComponentError>>",
 "ret_vec_res": "pub fn f(&self) -> Vec<Result<i32, MissingComponentError>>",
 "ret_box": "pub fn f(&self) -> Box<i32>", "ret_arc_i32": "pub fn f(&self) -> Arc<i32>", "ret_arc_vec": "pub fn f(&self) -> Arc<Vec<i32>>",
 "ret_arc_arc_scalar": "pub fn f(&self) -> Arc<Arc<ConnectionError>>", "ret_arc_scalar": "pub fn f(&self) -> Arc<ConnectionError>",
 "ret_arc_uuid": "pub fn f(&self) -> Arc<Uuid>", "ret_arc_opt_scalar": "pub fn f(&self) -> Arc<Option<Uuid>>",
 "ret_opt_arc_scalar": "pub fn f(&self) -> Option<Arc<ConnectionError>>", "ret_vec_arc_scalar": "pub fn f(&self) -> Vec<Arc<ConnectionError>>",
 "ret_arc_vec_scalar": "pub fn f(&self) -> Arc<Vec<ConnectionError>>", "ret_arc_str": "pub fn f(&self) -> Arc<str>", "ret_arc_string": "pub fn f(&self) -> Arc<String>",
 "ret_arc_unit": "pub fn f(&self) -> Arc<()>", "ret_rc": "pub fn f(&self) -> std::rc::Rc<i32>", "ret_cow": "pub fn f(&self) -> std::borrow::Cow<'static, str>",
 "ret_path_qualified": "pub fn f(&self) -> std::string::String", "ret_path_crate": "pub fn f(&self) -> crate::Vec3", "ret_path_self": "pub fn f(&self) -> self::Vec3",
 "ret_hashmap": "pub fn f(&self) -> std::collections::HashMap<String, i32>", "ret_dyn": "pub fn f(&self) -> Box<dyn Fn()>", "ret_impl": "pub fn f(&self) -> impl Iterator<Item = u32>",
 "ret_fnptr": "pub fn f(&self) -> fn(i32) -> i32", "ret_ptr": "pub fn f(&self) -> *const u8", "ret_u128": "pub fn f(&self) -> u128", "ret_i128": "pub fn f(&self) -> i128",
 "ret_usize": "pub fn f(&self) -> usize", "ret_isize": "pub fn f(&self) -> isize", "ret_char": "pub fn f(&self) -> char", "ret_u64": "pub fn f(&self) -> u64", "ret_f32": "pub fn f(&self) -> f32",
 "ret_duration": "pub fn f(&self) -> Duration", "ret_opt_unit": "pub fn f(&self) -> Option<()>", "ret_vec_unit": "pub fn f(&self) -> Vec<()>", "ret_vec_u8": "pub fn f(&self) -> Vec<u8>",
 "ret_assoc": "pub fn f(&self) -> <Vec3 as Default>::Output", "ret_qself_self": "pub fn f(&self) -> Self::Out",
 "p_arc": "pub fn f(&self, c: Arc<ConnectionError>)", "p_ref_str": "pub fn f(&self, s: &str)", "p_refmut": "pub fn f(&self, s: &mut String)",
 "p_impl_into": "pub fn f(&self, s: impl Into<String>)", "p_dyn": "pub fn f(&self, f: Box<dyn Fn(i32) -> i32>)", "p_slice": "pub fn f(&self, s: &[i32])",
 "p_tuple": "pub fn f(&self, t: (i32, i32))", "p_fnptr": "pub fn f(&self, f: fn(i32))", "p_generic": "pub fn f<T: Into<i32>>(&self, t: T)",
 "p_const_generic": "pub fn f<const N: usize>(&self, t: [u8; N])", "p_lifetime": "pub fn f<'a>(&'a self, s: &'a str) -> &'a str",
 "p_pattern_tuple": "pub fn f(&self, (a, b): (i32, i32))", "p_pattern_ref": "pub fn f(&self, &x: &i32)", "p_pattern_mut": "pub fn f(&self, mut x: i32)",
 "p_pattern_wild": "pub fn f(&self, _: i32)", "p_pattern_wild2": "pub fn f(&self, _: i32, _: i32)", "p_pattern_struct": "pub fn f(&self, BlockPos { x, y, z }: BlockPos)",
 "p_attr": "pub fn f(&self, #[allow(unused)] x: i32)", "p_vec_goal": "pub fn f(&self, g: Vec<impl Goal + 'static>)",
 "p_impl_goal_plus": "pub fn f(&self, g: impl Goal + Send + 'static)", "p_dyn_goal": "pub fn f(&self, g: &dyn Goal)", "p_impl_goal_ret": "pub fn f(&self) -> impl Goal",
 "p_option_blockpos": "pub fn f(&self, p: Option<BlockPos>)", "p_vec_blockpos": "pub fn f(&self, p: Vec<BlockPos>)", "p_result": "pub fn f(&self, r: Result<i32, i32>)",
 "p_u128": "pub fn f(&self, x: u128)", "p_default_name": "pub fn f(&self, r#in: i32)", "p_many": "pub fn f(&self, " + ", ".join(f"a{i}: i32" for i in range(120)) + ")",
 "unsafe_fn": "pub unsafe fn f(&self)", "const_fn": "pub const fn f(&self) -> i32", "extern_fn": "pub extern \"C\" fn f(&self)", "async_unsafe": "pub async unsafe fn f(&self)",
 "async_ret": "pub async fn f(&self) -> i32", "async_res": "pub async fn f(&self) -> Result<i32, MissingComponentError>", "async_vec3": "pub async fn f(&self) -> Vec3", "async_arg": "pub async fn f(&self, v: Vec3)",
 "default_fn": "pub default fn f(&self)", "vis_crate": "pub(crate) fn f(&self)", "vis_super": "pub(super) fn f(&self)", "vis_in": "pub(in crate::core) fn f(&self)", "vis_self": "pub(self) fn f(&self)",
 "vis_none": "fn f(&self)", "vis_pub_space": "pub  (  crate  )  fn f(&self)",
 "generic_where": "pub fn f<T>(&self, t: T) where T: Into<u32> + Copy", "generic_unused": "pub fn f<T>(&self)", "generic_lifetime_only": "pub fn f<'a>(&self, s: &'a str)",
 "multi_line": "pub fn\nf\n(\n&self, // c1\n/* c2 */ a: i32,\nb\n:\ni32 ,\n) -> /* r */ i32",
 "name_300": "pub fn " + "n" * 300 + "(&self)", "name_snake_digits": "pub fn f1_2__3(&self)",
}
for k, sig in SIGS.items():
    sig = sig.replace("pub fn f", "pub fn mm", 1) if "pub fn f" in sig else sig
    case("sig_" + k, M(fn(sig, "unimplemented!()")))
# deep nesting
case("deep_option_400", M(fn("pub fn deep(&self) -> " + "Option<" * 400 + "i32" + ">" * 400)))
case("deep_tuple_400", M(fn("pub fn deep(&self) -> " + "(" * 400 + "i32,)" * 400)))
case("deep_ref_400", M(fn("pub fn deep(&self, x: " + "&" * 400 + "i32)")))
case("deep_array_400", M(fn("pub fn deep(&self) -> " + "[" * 400 + "u8; 1]" + "; 1]" * 399)))
case("deep_mod_400", "".join(f"pub mod m{i} {{ " for i in range(300)) + "pub struct Deep { pub x: i32 }" + " }" * 300 + "\n" + M(fn("pub fn deep(&self) -> m0::m1::Deep")))
# ---- D. impl headers
case("impl_lt", M(fn("pub fn hdr(&self)"), hdr="impl<'a> Client"))
case("impl_where", M(fn("pub fn hdr(&self)"), hdr="impl Client where Client: Sized"))
case("impl_path", M(fn("pub fn hdr(&self)"), hdr="impl crate::Client"))
case("impl_self_path", "pub mod sub { use super::*; " + M(fn("pub fn hdr(&self)"), hdr="impl self::super::Client") + " }")
case("impl_generic_client", "pub struct G<T>(T);\n" + M(fn("pub fn hdr(&self)"), hdr="impl<T> G<T>"))
case("impl_trait_for_client", "pub trait Ext { fn ext_m(&self) -> i32; }\nimpl Ext for Client { fn ext_m(&self) -> i32 { 1 } }")
case("impl_trait_for_ref_client", "pub trait Ext { fn ext_m(&self) -> i32; }\nimpl Ext for &Client { fn ext_m(&self) -> i32 { 1 } }")
case("impl_trait_for_box_client", "pub trait Ext { fn ext_m(&self) -> i32; }\nimpl Ext for Box<Client> { fn ext_m(&self) -> i32 { 1 } }")
case("impl_trait_generic", "pub trait Ext<T> { fn ext_m(&self, t: T) -> i32; }\nimpl Ext<i32> for Client { fn ext_m(&self, t: i32) -> i32 { 1 } }")
case("impl_trait_pub_method", "pub trait Ext { fn ext_m(&self) -> i32; fn ext_def(&self) -> i32 { 3 } }\nimpl Ext for Client { fn ext_m(&self) -> i32 { 1 } }")
case("impl_drop", "impl Drop for Client { fn drop(&mut self) {} }")
case("impl_client_alias", "pub type C2 = Client;\n" + M(fn("pub fn via_alias(&self)"), hdr="impl C2"))
case("impl_dup_struct_name", "pub mod other { pub struct Client; impl Client { pub fn other_only(&self) {} } }")
case("impl_dup_in_cfg", "#[cfg(feature=\"x\")] pub struct Event2;\n#[cfg(feature=\"x\")]\nimpl Client { pub fn cfg_gated(&self) {} }")
case("impl_cfg_test_mod", "#[cfg(test)] mod tests { use super::*; impl Client { pub fn only_in_test(&self) {} } }")
case("impl_in_fn_body", "fn helper() { impl Client { pub fn in_fn(&self) {} } }")
case("impl_negative", "impl !Send for Client {}")
case("impl_unsafe_trait", "pub unsafe trait U {} unsafe impl U for Client {}")
case("impl_const_trait_bound", "impl<const N: usize> Client { }")
case("impl_empty", "impl Client {}")
case("impl_attr_cfg_on_method", M("    #[cfg(feature = \"nope\")] pub fn cfg_feat(&self) {}", "    #[cfg(not(feature = \"nope\"))] pub fn cfg_not(&self) {}", "    #[cfg(test)] pub fn cfg_test(&self) {}", "    #[cfg_attr(feature=\"x\", doc(hidden))] pub fn cfg_attr_m(&self) {}", "    #[doc(hidden)] pub fn hidden(&self) {}", "    #[deprecated] pub fn depr(&self) {}", "    #[must_use] #[inline(always)] pub fn attrs(&self) {}"))
# ---- E. macros
case("macro_client_impl", "macro_rules! m { ($($n:ident => $t:ty),* $(,)?) => { impl Client { $(pub fn $n(&self) -> $t { unimplemented!() })* } } }\nm!(a_one => i32, a_two => Vec<u8>,);")
case("macro_brace", "macro_rules! m { ($($n:ident),*) => { impl Client { $(pub fn $n(&self) {})* } } }\nm! { b_one, b_two }")
case("macro_bracket", "macro_rules! m { ($($n:ident),*) => { impl Client { $(pub fn $n(&self) {})* } } }\nm![c_one, c_two];")
case("macro_nested", "macro_rules! m { ($($n:ident),*) => { $(impl Client { pub fn $n(&self) {} })* } }\nmacro_rules! outer { ($($n:ident),*) => { m!($($n),*); } }\nouter!(d_one, d_two);")
case("macro_no_impl", "macro_rules! m { () => { 1 } }\nconst X: i32 = m!();")
case("macro_garbage", "m!(((((]]]]; ,,, ;;;")
case("macro_path_invocation", "crate::m!(x);")
case("macro_inside_mod", "pub mod mm { macro_rules! mi { ($n:ident) => { impl super::Client { pub fn $n(&self) {} } } } mi!(inmod); }")
case("macro_with_doc", "macro_rules! m { ($(#[$a:meta])* $n:ident) => { impl Client { $(#[$a])* pub fn $n(&self) {} } } }\nm!(#[doc = \"hi\"] with_doc);")
case("macro_impl_entity_dup", "impl_entity_functions! { }")
case("macro_impl_entity_odd", "impl_entity_functions! { weird_one weird_two }")
# ---- F. docs
DOCS = {
 "close_bracket": "/// text ]] and --[[ and ]=] ", "star_slash": "/// ends */ here /* and nests", "quotes": "/// \"double\" 'single' `tick` \\ backslash \\n \\\" ",
 "crlf": "/// crlf\r\n    /// second", "unicode": "/// héllo 名前 🚀 \u202e rtl \u0000nul", "tab": "///\tTAB\there", "empty_doc_lines": "///\n/// after blank",
 "long": "/// " + "word " * 5000, "block": "/** block doc */", "attr": "#[doc = \"attr doc\"]", "inner": "//! inner", "four_slash": "//// not doc", "bang": "/// ```rust\n/// let x = 1;\n/// ```",
 "dollar": "/// ${x} %s {0} {{}} {}", "luau_comment_start": "/// --- triple dash\n/// -- two dash", "link": "/// see [`Foo`](https://x.y/z) and [bar][baz] and [`Vec<u8>`]",
 "ends_backslash": "/// ends with backslash \\", "markdown_heading": "/// # Heading\n/// | a | b |\n/// |---|---|", "format_braces": "/// {self.client} {v}",
}
for k, d in DOCS.items():
    case("doc_" + k, M(f"    {d}\n    pub fn documented(&self) {{}}"))
case("doc_on_event", "", ["/// docs with ]] and */ and {}\n    Documented(u32)"])
case("doc_on_struct_field_hidden", "#[derive(Clone)] pub struct Rec { /// doc\n pub a: i32, #[doc(hidden)] pub b: i32 }\n" + M(fn("pub fn rec(&self) -> Rec")))
# ---- G. type shapes
TYPES = {
 "kw_fields": "#[derive(Clone)] pub struct T { pub r#type: i32, pub end: i32, pub local: String, pub nil: bool, pub function: f64, pub r#fn: u8 }",
 "unicode_fields": "#[derive(Clone)] pub struct T { pub héllo: i32, pub 名前: String }",
 "dup_field_snake": "#[derive(Clone)] pub struct T { pub fooBar: i32, pub foo_bar: i32 }",
 "empty_braces": "#[derive(Clone)] pub struct T {}", "empty_tuple": "#[derive(Clone)] pub struct T();", "unit": "#[derive(Clone)] pub struct T;",
 "generic": "#[derive(Clone)] pub struct T<X> { pub x: X }", "lifetime": "#[derive(Clone)] pub struct T<'a> { pub s: &'a str }", "const_generic": "#[derive(Clone)] pub struct T<const N: usize> { pub a: [u8; N] }",
 "array_fields": "#[derive(Clone)] pub struct T { pub a: [u8; 4], pub t: (i32, f64), pub u: (), pub s: &'static str, pub f: fn(i32) -> i32 }",
 "private_field": "#[derive(Clone)] pub struct T { pub a: i32, b: i32 }", "crate_vis_field": "#[derive(Clone)] pub struct T { pub a: i32, pub(crate) b: i32 }",
 "all_private": "#[derive(Clone)] pub struct T { a: i32 }", "crate_vis_struct": "#[derive(Clone)] pub(crate) struct T { pub a: i32 }",
 "no_clone": "pub struct T { pub a: i32 }", "no_clone_arc": "pub struct T { pub a: i32 }", "union": "pub union T { pub a: u32, pub b: f32 }",
 "disc_enum": "#[derive(Clone, Copy)] pub enum T { A = 1, B = 5, C }", "enum_named": "#[derive(Clone)] pub enum T { A { x: i32 }, B }", "enum_empty": "#[derive(Clone)] pub enum T {}",
 "enum_kw": "#[derive(Clone, Copy)] pub enum T { r#Loop, End, Nil, Function }", "enum_snake_dup": "#[derive(Clone, Copy)] pub enum T { FooBar, Foobar, Foo_Bar }",
 "enum_unicode": "#[derive(Clone, Copy)] pub enum T { Ünï, 名前 }", "enum_single": "#[derive(Clone, Copy)] pub enum T { Only }",
 "enum_quote_variant": "#[derive(Clone, Copy)] pub enum T { A, B }", "enum_non_exhaustive": "#[derive(Clone, Copy)] #[non_exhaustive] pub enum T { A, B }",
 "struct_named_like_class": "#[derive(Clone)] pub struct Bot { pub a: i32 }", "struct_named_entity": "#[derive(Clone)] pub struct Entity2 { pub a: i32 }",
 "struct_named_luauish": "#[derive(Clone)] pub struct string { pub a: i32 }", "struct_named_number": "#[derive(Clone)] pub struct number { pub a: i32 }",
 "struct_named_vector": "#[derive(Clone)] pub struct vector { pub a: i32 }", "struct_named_table": "#[derive(Clone)] pub struct table { pub a: i32 }", "struct_named_any": "#[derive(Clone)] pub struct any { pub a: i32 }",
 "struct_named_Lua": "#[derive(Clone)] pub struct LuaClient { pub a: i32 }", "struct_named_Container": "#[derive(Clone)] pub struct Container { pub a: i32 }",
 "struct_named_BlockPos2": "#[derive(Clone)] pub struct Blockpos { pub a: i32 }", "struct_type_alias_clash": "#[derive(Clone)] pub struct Item { pub a: i32 }",
 "struct_raw_name": "#[derive(Clone)] pub struct r#T { pub a: i32 }", "struct_huge_field_count": "#[derive(Clone)] pub struct T { " + ", ".join(f"pub f{i}: i32" for i in range(300)) + " }",
 "field_nested_vec": "#[derive(Clone)] pub struct T { pub a: Vec<Vec<Option<Vec3>>> }", "field_arc_scalar": "#[derive(Clone)] pub struct T { pub a: Arc<ConnectionError> }",
 "field_ref": "#[derive(Clone)] pub struct T<'a> { pub a: &'a Vec3 }", "field_box": "#[derive(Clone)] pub struct T { pub a: Box<Vec3> }",
 "field_hashmap": "#[derive(Clone)] pub struct T { pub a: std::collections::HashMap<String, i32> }", "field_dyn": "pub struct T { pub a: Box<dyn Fn()> }",
 "field_result": "#[derive(Clone)] pub struct T { pub a: Result<i32, MissingComponentError> }", "field_unit": "#[derive(Clone)] pub struct T { pub a: () }",
 "field_never": "pub struct T { pub a: ! }", "field_u64": "#[derive(Clone)] pub struct T { pub a: u64, pub b: i128, pub c: usize }",
 "field_self": "#[derive(Clone)] pub struct T { pub a: Self }",
}
for k, d in TYPES.items():
    nm = "T"
    if k.startswith("struct_named_") or k in ("struct_type_alias_clash",): nm = re.sub(r"^struct (\S+) .*", r"\1", d.split("pub struct ")[1] and "struct " + d.split("pub struct ")[1]) if False else d.split("pub struct ")[1].split(" ")[0]
    ret = f"pub fn t(&self) -> {nm}"
    par = f"pub fn t2(&self, v: {nm})"
    ev = [f"Ev({nm})"] if "<" not in nm else []
    case("type_" + k + "_ret", d + "\n" + M(fn(ret)))
    case("type_" + k + "_param", d + "\n" + M(fn(par)))
    case("type_" + k + "_event", d, ev)
    case("type_" + k + "_arc_ret", d + "\n" + M(fn(f"pub fn t3(&self) -> Arc<{nm}>")))
    case("type_" + k + "_arc_event", d, [f"EvA(Arc<{nm}>)"])
    case("type_" + k + "_optarc_event", d, [f"EvO(Option<Arc<{nm}>>)"])
# dup names across modules
case("dup_type_two_mods", "pub mod a { #[derive(Clone)] pub struct Dup { pub x: i32 } }\npub mod b { #[derive(Clone)] pub struct Dup { pub y: String } }\n" + M(fn("pub fn da(&self) -> a::Dup"), fn("pub fn db(&self) -> b::Dup")))
case("dup_type_pub_and_private", "pub mod a { #[derive(Clone)] pub struct Dup { pub x: i32 } }\nmod b { #[derive(Clone)] pub struct Dup { pub y: String } }\n" + M(fn("pub fn da(&self) -> a::Dup")))
case("dup_type_cfg_branches", "#[cfg(feature=\"a\")] #[derive(Clone)] pub struct Dup { pub x: i32 }\n#[cfg(not(feature=\"a\"))] #[derive(Clone)] pub struct Dup { pub x: i64 }\n" + M(fn("pub fn dd(&self) -> Dup")))
case("type_shadow_prelude", "#[derive(Clone)] pub struct Option { pub x: i32 }\n#[derive(Clone)] pub struct Vec { pub x: i32 }\n" + M(fn("pub fn so(&self) -> Option"), fn("pub fn sv(&self) -> Vec")))
case("type_shadow_string", "#[derive(Clone)] pub struct String { pub x: i32 }\n" + M(fn("pub fn ss(&self) -> String")))
case("type_shadow_result", "#[derive(Clone)] pub struct Result { pub x: i32 }\n" + M(fn("pub fn sr(&self) -> Result")))
case("type_shadow_arc", "#[derive(Clone)] pub struct Arc { pub x: i32 }\n" + M(fn("pub fn sa(&self) -> Arc")))
case("type_alias_ret", "pub type Al = Vec3;\n" + M(fn("pub fn al(&self) -> Al")))
case("type_alias_generic", "pub type Al<T> = Vec<T>;\n" + M(fn("pub fn al(&self) -> Al<i32>")))
case("reexport_chain_cycle", "pub mod a { pub use super::b::*; } pub mod b { pub use super::a::*; pub struct Cyc { pub x: i32 } }\n" + M(fn("pub fn cy(&self) -> b::Cyc")))
case("reexport_self_glob", "pub mod a { pub use self::*; pub struct Cyc2 { pub x: i32 } }")
case("reexport_rename_cycle", "pub mod a { pub use super::b::X as Y; } pub mod b { pub use super::a::Y as X; }")
case("reexport_alias_collision", "pub mod a { #[derive(Clone)] pub struct Q { pub x: i32 } } pub mod b { pub use super::a::Q as Z; } pub mod c { pub use super::a::Q as Z; }\n" + M(fn("pub fn qq(&self) -> a::Q")))
case("use_nested_braces", "pub mod a { pub struct A1; pub struct A2; pub mod n { pub struct A3; } }\npub use a::{A1, A2 as Two, n::{self, A3}};")
case("use_crate_root_glob", "pub use crate::*;")
case("use_extern", "pub use ::std::string::String as Str;")
case("use_empty_braces", "pub use a::{};")
