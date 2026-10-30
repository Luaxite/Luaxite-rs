// `menu`: a terminal menu (ratatui) for scripts. This is rust/tui_menu.rs; rust/main.rs declares it (`mod tui_menu;`) and calls
// `tui_menu::register(runtime.lua())` for each script's Luau state, so every script has the `menu` global. It is registered by hand, not through
// `#[bind]`: `#[bind]` fns can only take and return primitives, and this API takes tables and functions.
//
// A menu is a Luau table. Its array part lists the entries in order; each entry is an ITEM (a table with a `Type`) or a nested MENU (a table
// without one, named by its `Name`). String keys are entries too, named by the key (listed after the array part, alphabetically):
//
//   local m = menu.new({
//       { Type = "Button", Name = "About", Func = function() end },
//       config = {                                           -- a named menu (a folder)
//           { Type = "OnCall", Func = function() refresh() end },   -- runs each time this folder is opened; not shown in the list
//           { Type = "Boolean", Name = "debug",   Value = false, Func = function(on) end },
//           { Type = "Number",  Name = "retries", Value = 3 },
//           { Type = "String",  Name = "host",    Value = "localhost" },
//           { Type = "Button",  Name = "Reconnect", Func = function(a, b) end, Args = { "x", "y" } },
//           { Name = "network",                              -- a nested menu named by its `Name`: an array, no Type
//               { Type = "OnCall", Func = function(a) end, Args = { "opened" } },
//               { Type = "Number", Name = "port", Value = 25565 },
//           },
//       },
//   }, { title = "my bot" })
//
//   m:open()                 -- starts the menu on its own thread and returns at once; the script keeps running
//   m:log("connected", 42)   -- append a line to the log (values are joined with spaces, like print)
//   print(#m:logs())         -- the log as an array of strings (the newest 1000 lines are kept)
//   m:clear_logs()
//   m:wait()                 -- yields until the menu is closed (q / Ctrl-C / m:close())
//   m:close()  m:is_open()
//   m:tree()                 -- the menu table itself (the one you passed, or what your function returned; it follows `r`)
//   m:conf()                 -- the options table (the one you passed as 2nd arg, or a new one): `m:conf().title = "x"` retitles the menu at once
//
// Items (`Type` is case-insensitive; field names may be `Name` or `name`, and so on; `Func` may also be spelled `Callback`):
//   Number / String / Boolean   `Value` is shown and edited in the menu (Enter; a Boolean toggles). The new value is written back into `Value`
//                               of your table, then `Func(newValue, table.unpack(Args))` runs if there is one.
//   Button (or Function)        Enter runs `Func(table.unpack(Args))`.
//   OnCall                      `Func(table.unpack(Args))` runs each time the menu it sits in is opened from its parent. It is not listed.
//                               It is only allowed in a nested menu: in the main (root) menu it is shown as an error and never runs.
//                               Several OnCall items in one menu all run.
// Every `Func` runs on its own Luau thread like every callback, so it may yield and may change the table. `Args` is a table (unpacked) or a
// single value; it is optional.
//
// The table you pass IS the menu: edits are written into it, and changes your script makes to it show up in the menu at once.
// `menu.new(function() return tree end)` also works: the function is called when the menu is created and again on `r`.
//
// While the menu is open it owns the terminal (alternate screen): use `m:log` instead of `print`. Callbacks run in their own Luau thread, so
// they may yield (`task.wait`, `bot:...`); an error they raise is logged. Keys are listed in the footer of the menu.

use std::collections::VecDeque;
use std::io::IsTerminal;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use mlua::{Function, Lua, MultiValue, Table, UserData, UserDataMethods, Value, Variadic};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use ratatui::layout::{Constraint, Layout, Position};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{List, ListItem, ListState, Paragraph};
use ratatui::{DefaultTerminal, Frame};

/// Log lines kept; the oldest is dropped first.
const MAX_LOGS: usize = 1000;

/// One terminal, one menu: set while a menu thread owns the screen.
static TERMINAL_BUSY: AtomicBool = AtomicBool::new(false);

/// Adds the `menu` global (`menu.new`) to a Luau state.
pub fn register(lua: &Lua) -> mlua::Result<()> {
    let api = lua.create_table()?;
    api.set(
        "new",
        lua.create_function(|lua, (source, opts): (Value, Option<Table>)| Menu::create(lua, source, opts))?,
    )?;
    lua.globals().set("menu", api)
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

// ---------------------------------------------------------------------------------------------------------------------------------------
// shared state
// ---------------------------------------------------------------------------------------------------------------------------------------

enum Source {
    Tree(Table),
    Make(Function),
}

struct Shared {
    lua: Lua,
    source: Source,
    root: Mutex<Option<Table>>,
    /// The options table (`menu.new`'s 2nd argument): `title` is read from it on every frame.
    conf: Table,
    started: Instant,
    logs: Mutex<VecDeque<(Duration, String)>>,
    open: AtomicBool,
    stop: AtomicBool,
    rt: tokio::runtime::Handle,
}

impl Shared {
    fn log(&self, text: impl Into<String>) {
        let mut logs = lock(&self.logs);
        if logs.len() >= MAX_LOGS {
            logs.pop_front();
        }
        logs.push_back((self.started.elapsed(), text.into()));
    }

    fn load_root(&self) -> mlua::Result<Table> {
        let table = match &self.source {
            Source::Tree(t) => t.clone(),
            Source::Make(f) => f.call::<Table>(())?,
        };
        *lock(&self.root) = Some(table.clone());
        Ok(table)
    }

    fn root(&self) -> Option<Table> {
        lock(&self.root).clone()
    }

    /// The title as the script has it now: a string or a number, else "menu".
    fn title(&self) -> String {
        match self.conf.get::<Value>("title") {
            Ok(Value::String(s)) => s.to_string_lossy(),
            Ok(v @ (Value::Integer(_) | Value::Number(_))) => show(&v),
            _ => "menu".into(),
        }
    }
}

struct Menu(Arc<Shared>);

impl Menu {
    fn create(lua: &Lua, source: Value, opts: Option<Table>) -> mlua::Result<Self> {
        let source = match source {
            Value::Table(t) => Source::Tree(t),
            Value::Function(f) => Source::Make(f),
            other => {
                return Err(mlua::Error::runtime(format!(
                    "menu.new expects a table or a function returning one, got {}",
                    lua_type(&other)
                )));
            }
        };
        // The options table is kept as the script's own instance (`m:conf()`); a missing title is filled in so reading it always works.
        let conf = match opts {
            Some(o) => o,
            None => lua.create_table()?,
        };
        if matches!(conf.get::<Value>("title")?, Value::Nil) {
            conf.set("title", "menu")?;
        }
        let rt = tokio::runtime::Handle::try_current()
            .map_err(|_| mlua::Error::runtime("menu.new must be called from a running script"))?;
        let shared = Arc::new(Shared {
            lua: lua.clone(),
            source,
            root: Mutex::new(None),
            conf,
            started: Instant::now(),
            logs: Mutex::new(VecDeque::new()),
            open: AtomicBool::new(false),
            stop: AtomicBool::new(false),
            rt,
        });
        shared.load_root()?;
        Ok(Menu(shared))
    }

    fn open(&self) -> mlua::Result<()> {
        if self.0.open.load(Ordering::SeqCst) {
            return Ok(());
        }
        if !std::io::stdout().is_terminal() {
            return Err(mlua::Error::runtime("menu:open: stdout is not a terminal"));
        }
        if TERMINAL_BUSY.swap(true, Ordering::SeqCst) {
            return Err(mlua::Error::runtime("menu:open: another menu already owns the terminal"));
        }
        self.0.stop.store(false, Ordering::SeqCst);
        self.0.open.store(true, Ordering::SeqCst);
        let shared = self.0.clone();
        let spawned = std::thread::Builder::new().name("zenpel-menu".into()).spawn(move || {
            if let Err(e) = run_terminal(&shared) {
                shared.log(format!("menu stopped: {e}"));
            }
            shared.open.store(false, Ordering::SeqCst);
            TERMINAL_BUSY.store(false, Ordering::SeqCst);
        });
        if let Err(e) = spawned {
            self.0.open.store(false, Ordering::SeqCst);
            TERMINAL_BUSY.store(false, Ordering::SeqCst);
            return Err(mlua::Error::external(e));
        }
        Ok(())
    }
}

impl UserData for Menu {
    fn add_methods<M: UserDataMethods<Self>>(methods: &mut M) {
        methods.add_method("open", |_, this, ()| this.open());
        methods.add_method("close", |_, this, ()| {
            this.0.stop.store(true, Ordering::SeqCst);
            Ok(())
        });
        methods.add_method("is_open", |_, this, ()| Ok(this.0.open.load(Ordering::SeqCst)));
        methods.add_method("tree", |_, this, ()| this.0.root().ok_or_else(|| mlua::Error::runtime("menu has no tree")));
        methods.add_method("conf", |_, this, ()| Ok(this.0.conf.clone()));
        methods.add_async_method("wait", |_, this, ()| {
            let shared = this.0.clone();
            async move {
                while shared.open.load(Ordering::SeqCst) {
                    tokio::time::sleep(Duration::from_millis(50)).await;
                }
                Ok(())
            }
        });
        methods.add_method("log", |_, this, args: Variadic<Value>| {
            let mut parts = Vec::with_capacity(args.len());
            for v in args.iter() {
                parts.push(match v {
                    Value::String(s) => s.to_string_lossy(),
                    other => other.to_string()?,
                });
            }
            this.0.log(parts.join(" "));
            Ok(())
        });
        methods.add_method("logs", |lua, this, ()| {
            let lines: Vec<String> = lock(&this.0.logs).iter().map(|(_, text)| text.clone()).collect();
            lua.create_sequence_from(lines)
        });
        methods.add_method("clear_logs", |_, this, ()| {
            lock(&this.0.logs).clear();
            Ok(())
        });
    }
}

// ---------------------------------------------------------------------------------------------------------------------------------------
// reading the tree
// ---------------------------------------------------------------------------------------------------------------------------------------

/// Keys of a menu that are not entries.
const RESERVED: [&str; 1] = ["name"];

/// A field that may be spelled `Name` or `name`.
fn field(t: &Table, name: &str) -> Value {
    match t.get::<Value>(name) {
        Ok(Value::Nil) | Err(_) => t.get::<Value>(name.to_ascii_lowercase()).unwrap_or(Value::Nil),
        Ok(v) => v,
    }
}

fn str_field(t: &Table, name: &str) -> Option<String> {
    match field(t, name) {
        Value::String(s) => Some(s.to_string_lossy()),
        _ => None,
    }
}

/// The function of an item: `Func`, or `Callback` when there is no `Func`.
fn func_of(t: &Table) -> Value {
    match field(t, "Func") {
        Value::Nil => field(t, "Callback"),
        v => v,
    }
}

/// The key `Value` is stored under: `value` when that is how the script spelled it.
fn value_key(t: &Table) -> &'static str {
    let has = |k: &str| !matches!(t.raw_get::<Value>(k), Ok(Value::Nil) | Err(_));
    if !has("Value") && has("value") { "value" } else { "Value" }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Kind {
    Number,
    Text,
    Toggle,
    Button,
    /// A hook: runs when the menu it sits in is opened. Never listed.
    OnCall,
}

fn kind_of(name: &str) -> Option<Kind> {
    match name.to_ascii_lowercase().as_str() {
        "number" => Some(Kind::Number),
        "string" => Some(Kind::Text),
        "boolean" => Some(Kind::Toggle),
        "button" | "function" => Some(Kind::Button),
        "oncall" => Some(Kind::OnCall),
        _ => None,
    }
}

/// How an entry is found again in its parent (the menu is read live, so the path is kept as keys, not as tables).
#[derive(Clone)]
enum Selector {
    Index(usize),
    Key(String),
}

#[derive(Clone)]
enum Node {
    Menu(Table),
    Item { table: Table, kind: Kind },
    /// Shown dimmed with the reason; selecting it says why.
    Bad(String),
}

#[derive(Clone)]
struct Entry {
    sel: Selector,
    name: String,
    node: Node,
}

/// `type(v)` as Luau scripts know it (mlua tells integers from floats, Luau does not).
fn lua_type(v: &Value) -> &'static str {
    match v {
        Value::Integer(_) | Value::Number(_) => "number",
        other => other.type_name(),
    }
}

/// An item has a string `Type`; any other table is a nested menu.
fn classify(value: &Value) -> Node {
    let Value::Table(t) = value else {
        return Node::Bad(format!("expected a table, got {}", lua_type(value)));
    };
    match field(t, "Type") {
        Value::String(s) => {
            let s = s.to_string_lossy();
            match kind_of(&s) {
                Some(kind) => Node::Item { table: t.clone(), kind },
                None => Node::Bad(format!("unknown Type \"{s}\" (Number, String, Boolean, Button, OnCall)")),
            }
        }
        _ => Node::Menu(t.clone()),
    }
}

/// An `oncall` item cannot sit in the main (root) menu: there it is shown as an error.
fn guard_root(node: Node, root: bool) -> Node {
    match node {
        Node::Item { kind: Kind::OnCall, .. } if root => {
            Node::Bad("oncall is not allowed in the main menu (put it in a nested menu)".into())
        }
        other => other,
    }
}

/// All the entries of a menu, hooks (`oncall`) included: the array part in order, then the string keys by name.
/// `root` is true for the main menu.
fn all_entries(menu: &Table, root: bool) -> Vec<Entry> {
    let mut out = Vec::new();
    for i in 1..=menu.raw_len() {
        let Ok(value) = menu.raw_get::<Value>(i) else { continue };
        let node = guard_root(classify(&value), root);
        let named = match &value {
            Value::Table(t) => str_field(t, "Name"),
            _ => None,
        };
        out.push(Entry { sel: Selector::Index(i), name: named.unwrap_or_else(|| format!("#{i}")), node });
    }
    let mut named: Vec<Entry> = menu
        .pairs::<Value, Value>()
        .filter_map(|pair| {
            let (Value::String(key), value) = pair.ok()? else { return None };
            let key = key.to_string_lossy();
            if RESERVED.contains(&key.to_ascii_lowercase().as_str()) {
                return None;
            }
            Some(Entry { sel: Selector::Key(key.clone()), name: key, node: guard_root(classify(&value), root) })
        })
        .collect();
    named.sort_by_key(|e| e.name.to_lowercase());
    out.extend(named);
    out
}

/// The entries a menu lists: everything but the hooks.
fn entries(menu: &Table, root: bool) -> Vec<Entry> {
    let mut all = all_entries(menu, root);
    all.retain(|e| !matches!(e.node, Node::Item { kind: Kind::OnCall, .. }));
    all
}

fn fmt_num(n: f64) -> String {
    if n.is_finite() && n.fract() == 0.0 && n.abs() < 1e15 { format!("{}", n as i64) } else { format!("{n}") }
}

fn show_text(s: &str) -> String {
    let flat = s.replace('\n', "\\n");
    if flat.chars().count() > 48 {
        format!("\"{}…\"", flat.chars().take(47).collect::<String>())
    } else {
        format!("\"{flat}\"")
    }
}

/// How a value reads in the list and in the log.
fn show(value: &Value) -> String {
    match value {
        Value::Boolean(b) => b.to_string(),
        Value::Integer(i) => i.to_string(),
        Value::Number(n) => fmt_num(*n),
        Value::String(s) => show_text(&s.to_string_lossy()),
        other => format!("<{}>", lua_type(other)),
    }
}

/// The `Value` of an item as the list shows it (an item without one shows its type's default).
fn item_text(kind: Kind, value: &Value) -> String {
    match (value, kind) {
        (Value::Nil, Kind::Number) => "0".into(),
        (Value::Nil, Kind::Text) => "\"\"".into(),
        (Value::Nil, _) => "false".into(),
        (v, _) => show(v),
    }
}

fn join_path(path: &[(Selector, String)], name: Option<&str>) -> String {
    let mut parts: Vec<&str> = path.iter().map(|(_, n)| n.as_str()).collect();
    parts.extend(name);
    parts.join("/")
}

/// `Args` of an item: a table is unpacked, any other value is one argument.
fn args_of(t: &Table, name: &str) -> Vec<Value> {
    match field(t, name) {
        Value::Nil => Vec::new(),
        Value::Table(a) => a.sequence_values::<Value>().filter_map(Result::ok).collect(),
        other => vec![other],
    }
}

// ---------------------------------------------------------------------------------------------------------------------------------------
// calling back into the script
// ---------------------------------------------------------------------------------------------------------------------------------------

/// Run `f(args)` in its own Luau thread on the script's runtime (so it may yield or call async functions); an error goes to the log.
fn spawn_call(sh: &Arc<Shared>, label: String, f: Function, args: Vec<Value>) {
    let sh = sh.clone();
    let rt = sh.rt.clone();
    rt.spawn(async move {
        if let Err(e) = f.call_async::<()>(MultiValue::from_iter(args)).await {
            sh.log(format!("error in {label}: {e}"));
        }
    });
}

/// A button was pressed.
fn press(sh: &Arc<Shared>, item: &Table, label: String) -> Result<(), String> {
    match func_of(item) {
        Value::Function(f) => {
            sh.log(format!("run {label}"));
            spawn_call(sh, label, f, args_of(item, "Args"));
            Ok(())
        }
        _ => Err(format!("{label} has no Func")),
    }
}

/// A value was changed in the menu: write it into the script's table, then tell the script.
fn change(sh: &Arc<Shared>, item: &Table, label: String, value: Value) {
    let shown = show(&value);
    if let Err(e) = item.set(value_key(item), value.clone()) {
        return sh.log(format!("could not set {label}: {e}"));
    }
    sh.log(format!("set {label} = {shown}"));
    if let Value::Function(f) = func_of(item) {
        let mut args = vec![value];
        args.extend(args_of(item, "Args"));
        spawn_call(sh, label, f, args);
    }
}

/// A menu was opened: start each `oncall` item in it, in listing order. (Each runs on its own thread, so they are not ordered against each
/// other once started.) The main menu has none: `entries` turns an `oncall` there into an error entry, and this is only called for nested menus.
fn fire_oncalls(sh: &Arc<Shared>, menu: &Table, label: &str) {
    for entry in all_entries(menu, false) {
        let Node::Item { table, kind: Kind::OnCall } = entry.node else { continue };
        let tag = format!("{label}/oncall");
        match func_of(&table) {
            Value::Function(f) => spawn_call(sh, tag, f, args_of(&table, "Args")),
            Value::Nil => sh.log(format!("{tag} has no Func")),
            other => sh.log(format!("{tag}: Func must be a function, got {}", lua_type(&other))),
        }
    }
}

// ---------------------------------------------------------------------------------------------------------------------------------------
// UI state and keys
// ---------------------------------------------------------------------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Default)]
enum Pane {
    #[default]
    Menu,
    Logs,
}

struct Edit {
    item: Table,
    label: String,
    numeric: bool,
    buf: Vec<char>,
    pos: usize,
}

#[derive(Default)]
struct Ui {
    path: Vec<(Selector, String)>,
    cursor: usize,
    list: ListState,
    pane: Pane,
    edit: Option<Edit>,
    status: Option<String>,
    /// Log lines scrolled up from the newest.
    log_back: usize,
    quit: bool,
}

/// What one frame shows of the tree, read in one go so drawing does not touch Luau.
struct Snapshot {
    title: String,
    crumbs: String,
    entries: Vec<Entry>,
}

impl Ui {
    /// The menu the UI is in. A path that no longer exists (the script removed it) is cut back to what does.
    fn snapshot(&mut self, sh: &Shared) -> Snapshot {
        let Some(root) = sh.root() else {
            return Snapshot { title: sh.title(), crumbs: String::new(), entries: Vec::new() };
        };
        let mut dir = root;
        let mut depth = 0;
        for (sel, _) in &self.path {
            let next = match sel {
                Selector::Index(i) => dir.raw_get::<Value>(*i),
                Selector::Key(k) => dir.get::<Value>(k.as_str()),
            };
            match next.map(|v| classify(&v)) {
                Ok(Node::Menu(t)) => {
                    dir = t;
                    depth += 1;
                }
                _ => break,
            }
        }
        self.path.truncate(depth);
        let list = entries(&dir, self.path.is_empty());
        self.cursor = self.cursor.min(list.len().saturating_sub(1));
        Snapshot { title: sh.title(), crumbs: format!("/{}", join_path(&self.path, None)), entries: list }
    }

    fn key(&mut self, sh: &Arc<Shared>, ev: KeyEvent) {
        self.status = None;
        let ctrl = ev.modifiers.contains(KeyModifiers::CONTROL);
        if self.edit.is_some() {
            return self.edit_key(sh, ev, ctrl);
        }
        if ctrl && ev.code == KeyCode::Char('c') {
            self.quit = true;
            return;
        }
        match self.pane {
            Pane::Logs => self.logs_key(sh, ev),
            Pane::Menu => self.menu_key(sh, ev),
        }
    }

    fn logs_key(&mut self, sh: &Shared, ev: KeyEvent) {
        match ev.code {
            KeyCode::Char('q') => self.quit = true,
            KeyCode::Esc | KeyCode::Char('l') | KeyCode::Tab => self.pane = Pane::Menu,
            KeyCode::Up | KeyCode::Char('k') => self.log_back += 1,
            KeyCode::Down | KeyCode::Char('j') => self.log_back = self.log_back.saturating_sub(1),
            KeyCode::PageUp => self.log_back += 10,
            KeyCode::PageDown => self.log_back = self.log_back.saturating_sub(10),
            KeyCode::Home | KeyCode::Char('g') => self.log_back = usize::MAX,
            KeyCode::End | KeyCode::Char('G') => self.log_back = 0,
            KeyCode::Char('c') => lock(&sh.logs).clear(),
            _ => {}
        }
    }

    fn menu_key(&mut self, sh: &Arc<Shared>, ev: KeyEvent) {
        let snap = self.snapshot(sh);
        let last = snap.entries.len().saturating_sub(1);
        match ev.code {
            KeyCode::Char('q') => self.quit = true,
            KeyCode::Esc => {
                if self.path.is_empty() {
                    self.quit = true;
                } else {
                    self.ascend(sh);
                }
            }
            KeyCode::Char('l') | KeyCode::Tab => {
                self.pane = Pane::Logs;
                self.log_back = 0;
            }
            KeyCode::Char('r') => match sh.load_root() {
                Ok(_) => sh.log("reloaded"),
                Err(e) => sh.log(format!("reload failed: {e}")),
            },
            KeyCode::Up | KeyCode::Char('k') => self.cursor = self.cursor.saturating_sub(1),
            KeyCode::Down | KeyCode::Char('j') => self.cursor = (self.cursor + 1).min(last),
            KeyCode::PageUp => self.cursor = self.cursor.saturating_sub(10),
            KeyCode::PageDown => self.cursor = (self.cursor + 10).min(last),
            KeyCode::Home | KeyCode::Char('g') => self.cursor = 0,
            KeyCode::End | KeyCode::Char('G') => self.cursor = last,
            KeyCode::Left | KeyCode::Backspace | KeyCode::Char('h') => self.ascend(sh),
            KeyCode::Right => {
                if let Some(e) = snap.entries.get(self.cursor).filter(|e| matches!(e.node, Node::Menu(_))) {
                    self.activate(sh, e.clone());
                }
            }
            KeyCode::Enter | KeyCode::Char(' ') => {
                if let Some(e) = snap.entries.get(self.cursor) {
                    self.activate(sh, e.clone());
                }
            }
            _ => {}
        }
    }

    /// Go up one menu, with the cursor on the menu just left.
    fn ascend(&mut self, sh: &Shared) {
        let Some((_, left)) = self.path.pop() else { return };
        let snap = self.snapshot(sh);
        self.cursor = snap.entries.iter().position(|e| e.name == left).unwrap_or(0);
    }

    /// Enter on an entry: open a menu, press a button, toggle a boolean, edit a number or a string.
    fn activate(&mut self, sh: &Arc<Shared>, entry: Entry) {
        let label = join_path(&self.path, Some(&entry.name));
        match entry.node {
            Node::Menu(table) => {
                self.path.push((entry.sel, entry.name));
                self.cursor = 0;
                fire_oncalls(sh, &table, &label);
            }
            Node::Bad(why) => self.status = Some(format!("{label}: {why}")),
            // hooks are never listed, so there is nothing to activate
            Node::Item { kind: Kind::OnCall, .. } => {}
            Node::Item { table, kind: Kind::Button } => {
                if let Err(why) = press(sh, &table, label) {
                    self.status = Some(why);
                }
            }
            Node::Item { table, kind: Kind::Toggle } => {
                let on = matches!(field(&table, "Value"), Value::Boolean(true));
                change(sh, &table, label, Value::Boolean(!on));
            }
            Node::Item { table, kind } => {
                let text = match field(&table, "Value") {
                    Value::Nil => String::new(),
                    Value::String(s) => s.to_string_lossy(),
                    Value::Integer(i) => i.to_string(),
                    Value::Number(n) => fmt_num(n),
                    other => show(&other),
                };
                let buf: Vec<char> = if kind == Kind::Number && text.is_empty() { vec!['0'] } else { text.chars().collect() };
                let pos = buf.len();
                self.edit = Some(Edit { item: table, label, numeric: kind == Kind::Number, buf, pos });
            }
        }
    }

    fn edit_key(&mut self, sh: &Arc<Shared>, ev: KeyEvent, ctrl: bool) {
        let Some(edit) = self.edit.as_mut() else { return };
        match ev.code {
            KeyCode::Esc => self.edit = None,
            KeyCode::Char('c') if ctrl => self.edit = None,
            KeyCode::Enter => {
                let text: String = edit.buf.iter().collect();
                let value = if edit.numeric {
                    match text.trim().parse::<f64>() {
                        Ok(n) if n.is_finite() => Value::Number(n),
                        _ => {
                            self.status = Some(format!("not a number: {}", text.trim()));
                            return;
                        }
                    }
                } else {
                    match sh.lua.create_string(&text) {
                        Ok(s) => Value::String(s),
                        Err(e) => {
                            self.status = Some(e.to_string());
                            return;
                        }
                    }
                };
                let Edit { item, label, .. } = self.edit.take().expect("edit is set");
                change(sh, &item, label, value);
            }
            KeyCode::Char(c) if !ctrl => {
                edit.buf.insert(edit.pos, c);
                edit.pos += 1;
            }
            KeyCode::Backspace if edit.pos > 0 => {
                edit.pos -= 1;
                edit.buf.remove(edit.pos);
            }
            KeyCode::Delete if edit.pos < edit.buf.len() => {
                edit.buf.remove(edit.pos);
            }
            KeyCode::Left => edit.pos = edit.pos.saturating_sub(1),
            KeyCode::Right => edit.pos = (edit.pos + 1).min(edit.buf.len()),
            KeyCode::Home => edit.pos = 0,
            KeyCode::End => edit.pos = edit.buf.len(),
            _ => {}
        }
    }
}

// ---------------------------------------------------------------------------------------------------------------------------------------
// drawing
// ---------------------------------------------------------------------------------------------------------------------------------------

fn fmt_elapsed(d: Duration) -> String {
    let s = d.as_secs();
    format!("{:02}:{:02}", s / 60 % 100, s % 60)
}

fn draw(f: &mut Frame, ui: &mut Ui, sh: &Shared, snap: &Snapshot) {
    let [head, body, foot] = Layout::vertical([Constraint::Length(1), Constraint::Min(1), Constraint::Length(1)]).areas(f.area());

    let where_ = match ui.pane {
        Pane::Menu => snap.crumbs.clone(),
        Pane::Logs => "logs".to_string(),
    };
    f.render_widget(
        Line::from(vec![
            Span::styled(format!(" {} ", snap.title), Style::new().add_modifier(Modifier::BOLD).fg(Color::Black).bg(Color::Cyan)),
            Span::raw(format!(" {where_}")),
        ]),
        head,
    );

    match ui.pane {
        Pane::Menu => draw_menu(f, ui, snap, body),
        Pane::Logs => draw_logs(f, ui, sh, body),
    }

    let dim = Style::new().fg(Color::DarkGray);
    if let Some(edit) = &ui.edit {
        let prefix = format!(" {} = ", edit.label);
        let text: String = edit.buf.iter().collect();
        f.render_widget(Line::from(vec![Span::styled(prefix.clone(), dim), Span::raw(text)]), foot);
        let x = foot.x + (prefix.chars().count() + edit.pos) as u16;
        f.set_cursor_position(Position::new(x.min(foot.right().saturating_sub(1)), foot.y));
    } else if let Some(status) = &ui.status {
        f.render_widget(Line::from(Span::styled(format!(" {status}"), Style::new().fg(Color::Red))), foot);
    } else {
        let help = match ui.pane {
            Pane::Menu => " ↑↓ move  ⏎ open/run/edit  ← back  l logs  r reload  q quit",
            Pane::Logs => " ↑↓ PgUp PgDn scroll  g/G top/end  c clear  l back  q quit",
        };
        f.render_widget(Line::from(Span::styled(help, dim)), foot);
    }
}

fn draw_menu(f: &mut Frame, ui: &mut Ui, snap: &Snapshot, area: ratatui::layout::Rect) {
    if snap.entries.is_empty() {
        f.render_widget(Paragraph::new(Span::styled("  (empty)", Style::new().fg(Color::DarkGray))), area);
        return;
    }
    let width = snap.entries.iter().map(|e| e.name.chars().count()).max().unwrap_or(0);
    let dim = Style::new().fg(Color::DarkGray);
    let items: Vec<ListItem> = snap
        .entries
        .iter()
        .map(|e| {
            let name = format!("{:<width$}", e.name);
            ListItem::new(match &e.node {
                Node::Menu(t) => Line::from(vec![
                    Span::styled(format!("{}/", e.name), Style::new().fg(Color::Blue).add_modifier(Modifier::BOLD)),
                    Span::styled(format!("  {}", entries(t, false).len()), dim),
                ]),
                Node::Item { kind: Kind::OnCall, .. } => Line::from(Span::styled(name, dim)),
                Node::Item { kind: Kind::Button, .. } => {
                    Line::from(vec![Span::styled(name, Style::new().fg(Color::Green)), Span::styled("  ()", dim)])
                }
                Node::Item { table, kind } => Line::from(vec![
                    Span::raw(name),
                    Span::raw(" = "),
                    Span::styled(item_text(*kind, &field(table, "Value")), Style::new().fg(Color::Yellow)),
                ]),
                Node::Bad(why) => Line::from(vec![Span::styled(name, dim), Span::styled(format!("  ! {why}"), Style::new().fg(Color::Red))]),
            })
        })
        .collect();
    ui.list.select(Some(ui.cursor));
    f.render_stateful_widget(
        List::new(items).highlight_symbol("▶ ").highlight_style(Style::new().add_modifier(Modifier::REVERSED)),
        area,
        &mut ui.list,
    );
}

fn draw_logs(f: &mut Frame, ui: &mut Ui, sh: &Shared, area: ratatui::layout::Rect) {
    let lines: Vec<String> = lock(&sh.logs)
        .iter()
        .flat_map(|(at, text)| {
            let stamp = format!("[{}] ", fmt_elapsed(*at));
            text.lines()
                .enumerate()
                .map(move |(i, l)| if i == 0 { format!("{stamp}{l}") } else { format!("        {l}") })
                .collect::<Vec<_>>()
        })
        .collect();
    if lines.is_empty() {
        f.render_widget(Paragraph::new(Span::styled("  (no logs)", Style::new().fg(Color::DarkGray))), area);
        return;
    }
    let height = area.height as usize;
    ui.log_back = ui.log_back.min(lines.len().saturating_sub(height));
    let end = lines.len() - ui.log_back;
    let start = end.saturating_sub(height);
    let shown: Vec<Line> = lines[start..end].iter().map(|l| Line::from(l.as_str())).collect();
    f.render_widget(Paragraph::new(shown), area);
}

// ---------------------------------------------------------------------------------------------------------------------------------------
// the menu thread
// ---------------------------------------------------------------------------------------------------------------------------------------

fn run_terminal(sh: &Arc<Shared>) -> std::io::Result<()> {
    let mut terminal = ratatui::try_init()?;
    let result = event_loop(&mut terminal, sh);
    ratatui::restore();
    result
}

fn event_loop(terminal: &mut DefaultTerminal, sh: &Arc<Shared>) -> std::io::Result<()> {
    let mut ui = Ui::default();
    while !ui.quit && !sh.stop.load(Ordering::SeqCst) {
        let snap = ui.snapshot(sh);
        terminal.draw(|f| draw(f, &mut ui, sh, &snap))?;
        if event::poll(Duration::from_millis(100))?
            && let Event::Key(key) = event::read()?
            && key.kind == KeyEventKind::Press
        {
            ui.key(sh, key);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::{Terminal, backend::TestBackend};

    fn press_key(code: KeyCode) -> KeyEvent {
        KeyEvent::new(code, KeyModifiers::NONE)
    }

    struct Rig {
        lua: Lua,
        sh: Arc<Shared>,
        ui: Ui,
    }

    impl Rig {
        fn new(script: &str) -> Rig {
            let lua = Lua::new();
            register(&lua).unwrap();
            lua.load(script).exec().unwrap();
            let sh = lua.globals().get::<mlua::AnyUserData>("m").unwrap().borrow::<Menu>().unwrap().0.clone();
            Rig { lua, sh, ui: Ui::default() }
        }

        fn keys(&mut self, codes: &[KeyCode]) {
            for c in codes {
                self.ui.key(&self.sh, press_key(*c));
            }
        }

        fn type_text(&mut self, s: &str) {
            for c in s.chars() {
                self.ui.key(&self.sh, press_key(KeyCode::Char(c)));
            }
        }

        /// Put the cursor on the entry called `name` in the current menu.
        fn select(&mut self, name: &str) {
            let snap = self.ui.snapshot(&self.sh);
            self.ui.cursor = snap.entries.iter().position(|e| e.name == name).unwrap_or_else(|| panic!("no entry {name}"));
        }

        fn screen(&mut self) -> String {
            let mut terminal = Terminal::new(TestBackend::new(50, 12)).unwrap();
            let snap = self.ui.snapshot(&self.sh);
            terminal.draw(|f| draw(f, &mut self.ui, &self.sh, &snap)).unwrap();
            let buf = terminal.backend().buffer().clone();
            (0..buf.area.height)
                .map(|y| (0..buf.area.width).map(|x| buf[(x, y)].symbol().to_string()).collect::<String>().trim_end().to_string())
                .collect::<Vec<_>>()
                .join("\n")
        }

        fn eval<T: mlua::FromLua>(&self, expr: &str) -> T {
            self.lua.load(format!("return {expr}")).eval().unwrap()
        }

        async fn until(&self, expr: &str) {
            for _ in 0..100 {
                if self.eval::<bool>(expr) {
                    return;
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
            panic!("timed out waiting for {expr}");
        }
    }

    const TREE: &str = r#"
        tree = {
            { Type = "Button", Name = "Hello", Callback = function() ran = (ran or 0) + 1 end },
            { Type = "Button", Name = "Boom", Func = function() error("kaboom") end },
            config = {
                { Type = "OnCall", Func = function(a, b) config_opened = (config_opened or 0) + 1; config_args = tostring(a) .. tostring(b) end, Args = { "p", "q" } },
                { Type = "Boolean", Name = "debug", Value = false, Func = function(v, tag) changed = { v, tag } end, Args = { "dbg" } },
                { Type = "Number", Name = "retries", Value = 3 },
                { Type = "String", Name = "host", Value = "localhost" },
                { Type = "Button", Name = "Reconnect", Callback = function(a, b) pressed = a .. b end, Args = { "x", "y" } },
                { Name = "network",
                    { Type = "oncall", Func = function() net_opened = true end },
                    { Type = "Number", Name = "port", Value = 25565 },
                },
            },
        }
        m = menu.new(tree, { title = "test" })
    "#;

    #[tokio::test(flavor = "multi_thread")]
    async fn array_order_nested_menus_and_navigation() {
        let mut r = Rig::new(TREE);
        let s = r.screen();
        let lines: Vec<&str> = s.lines().collect();
        assert!(lines[0].contains("test"), "{s}");
        assert!(lines[1].contains("Hello") && lines[2].contains("Boom") && lines[3].contains("config/"), "array part first, then named: {s}");

        r.select("config");
        r.keys(&[KeyCode::Enter]);
        let s = r.screen();
        let lines: Vec<&str> = s.lines().collect();
        assert!(lines[0].contains("/config"), "{s}");
        // the order the script wrote them in
        let order: Vec<usize> = ["debug", "retries", "host", "Reconnect", "network/"]
            .iter()
            .map(|n| lines.iter().position(|l| l.contains(n)).unwrap_or_else(|| panic!("{n} missing: {s}")))
            .collect();
        assert!(order.windows(2).all(|w| w[0] < w[1]), "{s}");
        assert!(s.contains("= false") && s.contains("= 3") && s.contains("\"localhost\""), "{s}");

        r.select("network");
        r.keys(&[KeyCode::Enter]);
        let s = r.screen();
        assert!(s.contains("/config/network") && s.contains("port") && s.contains("25565"), "{s}");

        r.keys(&[KeyCode::Left]);
        assert!(r.screen().contains("/config"));
        assert_eq!(r.ui.cursor, 4, "cursor is back on the menu we left");
        r.keys(&[KeyCode::Esc]);
        assert!(r.ui.path.is_empty());
        assert!(!r.ui.quit);
        r.keys(&[KeyCode::Esc]);
        assert!(r.ui.quit, "Esc at the root quits");
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn oncall_runs_when_a_menu_is_opened() {
        let mut r = Rig::new(TREE);
        assert!(r.eval::<bool>("config_opened == nil"), "nothing runs until the menu is opened");

        r.select("config");
        r.keys(&[KeyCode::Enter]);
        r.until("config_opened == 1").await;
        assert!(r.eval::<bool>("config_args == 'pq'"), "Args are passed");
        let s = r.screen();
        assert!(s.contains("debug") && !s.contains("#1") && !s.contains("oncall"), "an oncall item is not listed: {s}");

        r.select("network");
        r.keys(&[KeyCode::Right]); // `Type` is case-insensitive
        r.until("net_opened == true").await;
        assert!(r.eval::<bool>("config_opened == 1"), "opening a child does not re-run the parent's");

        // opened again
        r.keys(&[KeyCode::Left, KeyCode::Left]);
        r.select("config");
        r.keys(&[KeyCode::Right]);
        r.until("config_opened == 2").await;
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn oncall_is_not_allowed_in_the_main_menu() {
        let mut r = Rig::new(
            "tree = { { Type = 'OnCall', Func = function() bad = true end }, hook = { Type = 'oncall', Func = function() bad = true end }, { Type = 'Button', Name = 'b', Func = function() end } }; m = menu.new(tree)",
        );
        let s = r.screen();
        assert!(s.contains("oncall is not allowed in the main menu"), "shown as an error, not hidden: {s}");
        assert!(s.contains("#1") && s.contains("hook"), "{s}");

        r.select("#1");
        r.keys(&[KeyCode::Enter]);
        assert!(r.ui.status.as_deref().unwrap_or("").contains("main menu"));
        r.select("hook");
        r.keys(&[KeyCode::Enter]);
        assert!(r.ui.status.as_deref().unwrap_or("").contains("main menu"));
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert!(r.eval::<bool>("bad == nil"), "it never runs");
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn every_oncall_in_a_menu_runs_and_problems_are_logged() {
        let mut r = Rig::new(
            "tree = { sub = { { Type = 'oncall', Func = function() a = true end }, { Type = 'oncall', Func = function() b = true end, Args = 7 }, { Type = 'oncall' }, { Type = 'oncall', Func = function() error('oops') end }, { Type = 'Button', Name = 'x', Func = function() end } } }; m = menu.new(tree)",
        );
        r.select("sub");
        r.keys(&[KeyCode::Enter]);
        r.until("a == true and b == true").await;
        r.until("#m:logs() >= 2").await;
        let logs: Vec<String> = r.eval("m:logs()");
        assert!(logs.iter().any(|l| l == "sub/oncall has no Func"), "{logs:?}");
        assert!(logs.iter().any(|l| l.starts_with("error in sub/oncall") && l.contains("oops")), "{logs:?}");
        let s = r.screen();
        assert!(s.contains("x") && !s.contains("#"), "only the button is listed: {s}");
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn values_are_edited_in_place_and_callbacks_get_the_new_value() {
        let mut r = Rig::new(TREE);
        r.select("config");
        r.keys(&[KeyCode::Enter]);

        r.select("debug");
        r.keys(&[KeyCode::Enter]);
        assert!(r.eval::<bool>("tree.config[2].Value == true"), "written into the caller's table");
        r.until("changed ~= nil").await;
        assert!(r.eval::<bool>("changed[1] == true and changed[2] == 'dbg'"), "Func(newValue, table.unpack(Args))");
        assert!(r.screen().contains("debug") && r.screen().contains("= true"));

        r.select("retries");
        r.keys(&[KeyCode::Enter]);
        assert!(r.ui.edit.is_some());
        r.keys(&[KeyCode::Backspace]);
        r.type_text("12");
        r.keys(&[KeyCode::Enter]);
        assert!(r.ui.edit.is_none());
        assert!(r.eval::<bool>("tree.config[3].Value == 12"));

        // a bad number stays in the editor and writes nothing
        r.keys(&[KeyCode::Enter, KeyCode::Backspace, KeyCode::Backspace]);
        r.type_text("x1");
        r.keys(&[KeyCode::Enter]);
        assert!(r.ui.edit.is_some() && r.ui.status.as_deref().unwrap_or("").contains("not a number"));
        assert!(r.eval::<bool>("tree.config[3].Value == 12"));
        r.keys(&[KeyCode::Esc]);
        assert!(r.ui.edit.is_none());

        r.select("host");
        r.keys(&[KeyCode::Enter, KeyCode::Home, KeyCode::Delete]);
        r.type_text("L");
        r.keys(&[KeyCode::Enter]);
        assert!(r.eval::<bool>("tree.config[4].Value == 'Localhost'"));
        assert!(r.eval::<bool>("m:logs()[#m:logs()] == 'set config/host = \"Localhost\"'"));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn buttons_run_their_callback_with_args_and_errors_are_logged() {
        let mut r = Rig::new(TREE);
        r.select("Hello");
        r.keys(&[KeyCode::Enter]);
        r.until("ran == 1").await;
        r.select("Boom");
        r.keys(&[KeyCode::Enter]);
        r.until("#m:logs() >= 3").await;
        let logs: Vec<String> = r.eval("m:logs()");
        assert_eq!(logs[0], "run Hello");
        assert_eq!(logs[1], "run Boom");
        assert!(logs[2].starts_with("error in Boom") && logs[2].contains("kaboom"), "{logs:?}");

        r.select("config");
        r.keys(&[KeyCode::Enter]);
        r.select("Reconnect");
        r.keys(&[KeyCode::Enter]);
        r.until("pressed == 'xy'").await;
        assert!(r.eval::<bool>("m:logs()[#m:logs()] == 'run config/Reconnect'"));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_callback_may_yield_and_call_async_functions() {
        let mut r = Rig::new(
            "tree = { { Type = 'Button', Name = 'Later', Callback = function() ok = 1; asleep(); ok = 2 end } }; m = menu.new(tree)",
        );
        let sleep = r.lua.create_async_function(|_, ()| async { tokio::time::sleep(Duration::from_millis(60)).await; Ok(()) }).unwrap();
        r.lua.globals().set("asleep", sleep).unwrap();
        r.keys(&[KeyCode::Enter]);
        r.until("ok == 1").await;
        r.until("ok == 2").await;
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn field_names_and_types_are_case_insensitive_and_keep_the_scripts_spelling() {
        // (`func` here; `Callback` is the other spelling and is used in TREE)
        let mut r = Rig::new(
            "tree = { { type = 'number', name = 'n', value = 1 }, { Type = 'Function', Name = 'f', func = function() fired = true end } }; m = menu.new(tree)",
        );
        let s = r.screen();
        assert!(s.contains("n = 1") && s.contains("f"), "{s}");
        r.keys(&[KeyCode::Enter, KeyCode::Backspace]);
        r.type_text("5");
        r.keys(&[KeyCode::Enter]);
        assert!(r.eval::<bool>("tree[1].value == 5 and tree[1].Value == nil"), "written to the key the script used");
        r.keys(&[KeyCode::Down, KeyCode::Enter]);
        r.until("fired == true").await;
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn defaults_and_bad_entries_are_shown_not_hidden() {
        let mut r = Rig::new(
            "tree = { { Type = 'Number', Name = 'n' }, { Type = 'Boolean', Name = 'b' }, { Type = 'Slider', Name = 'x' }, 7, stray = true, { Type = 'Button', Name = 'nocb' } }; m = menu.new(tree)",
        );
        let s = r.screen();
        assert!(s.contains("n") && s.contains("= 0") && s.contains("= false"), "defaults: {s}");
        assert!(s.contains("unknown Type \"Slider\""), "{s}");
        assert!(s.contains("expected a table, got number"), "{s}");
        assert!(s.contains("stray") && s.contains("expected a table, got boolean"), "{s}");

        r.select("x");
        r.keys(&[KeyCode::Enter]);
        assert!(r.ui.status.as_deref().unwrap_or("").contains("unknown Type"));
        r.select("nocb");
        r.keys(&[KeyCode::Enter]);
        assert!(r.ui.status.as_deref().unwrap_or("").contains("has no Func"));

        r.select("n"); // Number with no Value: edit starts at 0
        r.keys(&[KeyCode::Enter]);
        r.type_text("1");
        r.keys(&[KeyCode::Enter]);
        assert!(r.eval::<bool>("tree[1].Value == 1"));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn logs_are_an_array_capped_clearable_and_viewable() {
        let mut r = Rig::new(TREE);
        r.lua.load("m:log('a'); m:log('b', 2, true, nil)").exec().unwrap();
        let logs: Vec<String> = r.eval("m:logs()");
        assert_eq!(logs, ["a", "b 2 true nil"]);

        r.keys(&[KeyCode::Char('l')]);
        let s = r.screen();
        assert!(s.contains("logs") && s.contains("] a") && s.contains("] b 2 true nil"), "{s}");
        r.keys(&[KeyCode::Char('c')]);
        assert!(r.screen().contains("(no logs)"));
        r.keys(&[KeyCode::Char('l')]);
        assert!(r.ui.pane == Pane::Menu);

        r.lua.load("for i = 1, 1500 do m:log('line ' .. i) end").exec().unwrap();
        assert_eq!(r.eval::<usize>("#m:logs()"), MAX_LOGS);
        assert_eq!(r.eval::<String>("m:logs()[1]"), "line 501");
        r.lua.load("m:clear_logs()").exec().unwrap();
        assert_eq!(r.eval::<usize>("#m:logs()"), 0);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn follows_changes_the_script_makes_and_survives_a_vanished_menu() {
        let mut r = Rig::new(TREE);
        r.select("config");
        r.keys(&[KeyCode::Enter]);
        r.select("network");
        r.keys(&[KeyCode::Enter]); // /config/network
        r.lua
            .load("table.insert(tree.config[6], { Type = 'String', Name = 'added', Value = 'late' }); tree.config[6][2].Value = 99")
            .exec()
            .unwrap();
        let s = r.screen();
        assert!(s.contains("added") && s.contains("late") && s.contains("= 99"), "{s}");
        r.lua.load("tree.config = nil").exec().unwrap();
        let s = r.screen();
        assert!(r.ui.path.is_empty(), "path cut back to what exists");
        assert!(s.contains("Hello") && !s.contains("added"), "{s}");
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_function_source_is_called_on_new_and_on_reload() {
        let mut r = Rig::new(
            "count = 0; m = menu.new(function() count += 1; return { { Type = 'Button', Name = 'gen ' .. count, Callback = function() end } } end)",
        );
        assert!(r.screen().contains("gen 1"));
        r.keys(&[KeyCode::Char('r')]);
        assert!(r.screen().contains("gen 2"));
        assert!(r.eval::<bool>("m:logs()[1] == 'reloaded'"));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn tree_and_conf_are_the_live_tables() {
        let mut r = Rig::new(
            "tree = { { Type = 'Button', Name = 'a', Func = function() end } }; opts = { title = 'one' }; m = menu.new(tree, opts)",
        );
        assert!(r.eval::<bool>("m:tree() == tree"), "the very table that was passed");
        assert!(r.eval::<bool>("m:conf() == opts"), "the very options table");
        assert!(r.screen().lines().next().unwrap().contains("one"));

        r.lua.load("m:conf().title = 'two'").exec().unwrap();
        let s = r.screen();
        assert!(s.lines().next().unwrap().contains("two") && !s.contains("one"), "retitled at once: {s}");

        r.lua.load("table.insert(m:tree(), { Type = 'Number', Name = 'added', Value = 5 })").exec().unwrap();
        assert!(r.screen().contains("added"), "changes to m:tree() show up");

        // no options table: one is made, with the default title; a bad title falls back
        let mut r = Rig::new("m = menu.new({ { Type = 'Button', Name = 'a', Func = function() end } })");
        assert!(r.eval::<bool>("m:conf().title == 'menu'"));
        r.lua.load("m:conf().title = 7").exec().unwrap();
        assert!(r.screen().lines().next().unwrap().contains(" 7 "));
        r.lua.load("m:conf().title = nil").exec().unwrap();
        assert!(r.screen().lines().next().unwrap().contains("menu"));

        // a function source: m:tree() is what it returned last, also after `r`
        let mut r = Rig::new(
            "count = 0; m = menu.new(function() count += 1; last = { { Type = 'Button', Name = 'gen ' .. count, Func = function() end } }; return last end)",
        );
        assert!(r.eval::<bool>("m:tree() == last and count == 1"));
        r.keys(&[KeyCode::Char('r')]);
        assert!(r.eval::<bool>("m:tree() == last and count == 2"));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn bad_arguments_are_errors() {
        let lua = Lua::new();
        register(&lua).unwrap();
        assert!(lua.load("menu.new(3)").exec().is_err());
        assert!(lua.load("menu.new(function() return 1 end)").exec().is_err());
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn open_without_a_terminal_is_a_clear_error() {
        // `cargo test` captures stdout, which is not a terminal.
        let r = Rig::new(TREE);
        let err = r.lua.load("m:open()").exec();
        if !std::io::stdout().is_terminal() {
            assert!(err.unwrap_err().to_string().contains("not a terminal"));
        }
        assert!(!r.eval::<bool>("m:is_open()"));
    }
}
