-- luau-lsp definitions for the globals bound from demo_binds.rs (//BIND pub). Hand-written; CI passes it with --defs next to types/bindings.d.luau.
declare function demo_add(a: number, b: number): number
declare function demo_greet(name: string?): string
declare function demo_div(a: number, b: number): number
declare function demo_set_global(name: string, value: number): ()
declare answer: number
