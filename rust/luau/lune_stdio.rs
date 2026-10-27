use lune_utils::fmt::{ValueFormatConfig, pretty_format_multi_value};
use mlua::{Lua, MultiValue, Table, Value};
use std::sync::{Arc, LazyLock};
use tokio::io::{AsyncBufReadExt, AsyncWrite, AsyncWriteExt, BufReader, Stdin};
use tokio::sync::Mutex;

use super::lune_libs::{read_capped, too_big};

static STDIN: LazyLock<Arc<Mutex<BufReader<Stdin>>>> =
    LazyLock::new(|| Arc::new(Mutex::new(BufReader::new(tokio::io::stdin()))));

const COLORS: &[(&str, &str)] = &[
    ("reset", "\x1b[0m"),
    ("black", "\x1b[30m"),
    ("red", "\x1b[31m"),
    ("green", "\x1b[32m"),
    ("yellow", "\x1b[33m"),
    ("blue", "\x1b[34m"),
    ("magenta", "\x1b[35m"),
    ("purple", "\x1b[35m"),
    ("cyan", "\x1b[36m"),
    ("white", "\x1b[37m"),
];
const STYLES: &[(&str, &str)] = &[
    ("reset", "\x1b[0m"),
    ("bold", "\x1b[1m"),
    ("dim", "\x1b[2m"),
];

fn lookup(
    func: &str,
    what: &str,
    table: &'static [(&'static str, &'static str)],
    name: &str,
) -> mlua::Result<&'static str> {
    match table.iter().find(|(n, _)| *n == name) {
        Some((_, code)) => Ok(*code),
        None => {
            let valid: Vec<&str> = table.iter().map(|(n, _)| *n).collect();
            Err(mlua::Error::runtime(format!(
                "stdio.{func}: invalid {what} '{name}', valid: {}",
                valid.join(", ")
            )))
        }
    }
}

fn io_err(name: &str, e: &std::io::Error) -> mlua::Error {
    mlua::Error::runtime(format!("stdio.{name}: {e}"))
}

async fn write_flush<W: AsyncWrite + Unpin>(
    name: &str,
    mut out: W,
    bytes: Vec<u8>,
) -> mlua::Result<()> {
    out.write_all(&bytes).await.map_err(|e| io_err(name, &e))?;
    out.flush().await.map_err(|e| io_err(name, &e))
}

const PROMPT_KINDS: &str = "text, confirm, select, multiselect";

enum Answer {
    Text(String),
    Bool(bool),
    Index(usize),
    Indexes(Vec<usize>),
    Cancelled,
}

fn options_of(v: &Value) -> mlua::Result<Vec<String>> {
    let Value::Table(t) = v else {
        return Err(mlua::Error::runtime(
            "stdio.prompt: this kind needs an options table as the third argument",
        ));
    };
    let opts = t
        .sequence_values::<String>()
        .collect::<mlua::Result<Vec<_>>>()?;
    if opts.is_empty() {
        return Err(mlua::Error::runtime(
            "stdio.prompt: the options table is empty",
        ));
    }
    Ok(opts)
}

fn ask(
    kind: String,
    message: String,
    default: Option<String>,
    default_bool: bool,
    opts: Vec<String>,
) -> Result<Answer, Box<dyn std::error::Error>> {
    use dialoguer::{Confirm, Input, MultiSelect, Select, theme::ColorfulTheme};
    let theme = ColorfulTheme::default();
    Ok(match kind.as_str() {
        "text" => {
            let mut input = Input::<String>::with_theme(&theme)
                .with_prompt(message)
                .allow_empty(true);
            if let Some(d) = default {
                input = input.default(d);
            }
            Answer::Text(input.interact_text()?)
        }
        "confirm" => Confirm::with_theme(&theme)
            .with_prompt(message)
            .default(default_bool)
            .interact_opt()?
            .map_or(Answer::Cancelled, Answer::Bool),
        "select" => Select::with_theme(&theme)
            .with_prompt(message)
            .items(&opts)
            .interact_opt()?
            .map_or(Answer::Cancelled, Answer::Index),
        _ => MultiSelect::with_theme(&theme)
            .with_prompt(message)
            .items(&opts)
            .interact_opt()?
            .map_or(Answer::Cancelled, Answer::Indexes),
    })
}

pub fn module(lua: Lua) -> mlua::Result<Table> {
    let write = lua.create_async_function(|_, s: mlua::String| {
        let bytes = s.as_bytes().to_vec();
        async move { write_flush("write", tokio::io::stdout(), bytes).await }
    })?;
    let ewrite = lua.create_async_function(|_, s: mlua::String| {
        let bytes = s.as_bytes().to_vec();
        async move { write_flush("ewrite", tokio::io::stderr(), bytes).await }
    })?;
    let format = lua.create_function(|_, args: MultiValue| {
        Ok(pretty_format_multi_value(
            &args,
            &ValueFormatConfig::new()
                .with_max_depth(4)
                .with_colors_enabled(false),
        ))
    })?;
    let color = lua.create_function(|_, name: String| lookup("color", "color", COLORS, &name))?;
    let style = lua.create_function(|_, name: String| lookup("style", "style", STYLES, &name))?;
    let read_line = lua.create_async_function(|lua, ()| async move {
        let mut buf = Vec::new();
        STDIN
            .lock()
            .await
            .read_until(b'\n', &mut buf)
            .await
            .map_err(|e| io_err("readLine", &e))?;
        lua.create_string(&buf)
    })?;
    let read_to_end = lua.create_async_function(|lua, ()| async move {
        let buf = read_capped(&mut *STDIN.lock().await)
            .await
            .map_err(|e| io_err("readToEnd", &e))?
            .ok_or_else(|| too_big("stdio.readToEnd"))?;
        lua.create_string(&buf)
    })?;
    let prompt = lua.create_async_function(
        |lua, (kind, message, extra): (Option<String>, Option<String>, Value)| async move {
            let kind = kind.unwrap_or_else(|| "text".into());
            if !["text", "confirm", "select", "multiselect"].contains(&kind.as_str()) {
                return Err(mlua::Error::runtime(format!(
                    "stdio.prompt: invalid kind '{kind}', valid kinds: {PROMPT_KINDS}"
                )));
            }
            if kind == "confirm" && message.is_none() {
                return Err(mlua::Error::runtime(
                    "stdio.prompt: the confirm kind needs a message",
                ));
            }
            let (mut default, mut default_bool, mut opts) = (None, false, Vec::new());
            match kind.as_str() {
                "text" => {
                    default = if let Value::String(s) = &extra {
                        Some(s.to_str()?.to_string())
                    } else {
                        None
                    }
                }
                "confirm" => default_bool = matches!(extra, Value::Boolean(true)),
                _ => opts = options_of(&extra)?,
            }
            let message = message.unwrap_or_default();
            let answer = tokio::task::spawn_blocking(move || {
                ask(kind, message, default, default_bool, opts).map_err(|e| e.to_string())
            })
            .await
            .map_err(|e| mlua::Error::runtime(format!("stdio.prompt: {e}")))?
            .map_err(|e| mlua::Error::runtime(format!("stdio.prompt: {e}")))?;
            Ok(match answer {
                Answer::Text(s) => Value::String(lua.create_string(&s)?),
                Answer::Bool(b) => Value::Boolean(b),
                Answer::Index(i) => Value::Integer((i + 1) as mlua::Integer),
                Answer::Indexes(v) => Value::Table(
                    lua.create_sequence_from(v.into_iter().map(|i| (i + 1) as mlua::Integer))?,
                ),
                Answer::Cancelled => Value::Nil,
            })
        },
    )?;
    let stdio = lua.create_table()?;
    stdio.set("write", write)?;
    stdio.set("ewrite", ewrite)?;
    stdio.set("format", format)?;
    stdio.set("color", color)?;
    stdio.set("style", style)?;
    stdio.set("readLine", read_line)?;
    stdio.set("readToEnd", read_to_end)?;
    stdio.set("prompt", prompt)?;
    stdio.set_readonly(true);
    Ok(stdio)
}
