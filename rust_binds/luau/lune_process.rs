use lune_utils::{
    path::get_current_dir,
    process::{ProcessArgs, ProcessEnv},
};
use mlua::{Lua, Table, UserData, UserDataMethods, Value};
use std::process::Stdio;
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWriteExt};
use tokio::process::Command;
use tokio::sync::{Mutex, Notify, watch};

use super::lune_libs::{
    DEFAULT_EXEC_TIMEOUT_SECS, MAX_BYTES, read_capped, timeout_with_default, too_big,
};

const STDIO_KINDS: &str = "default, inherit, forward, none";

struct Entry {
    pid: u32,
    exited: bool,
    group: bool,
}

const MAX_TRACKED: usize = 1024;

static CHILDREN: StdMutex<Vec<Entry>> = StdMutex::new(Vec::new());

struct Tracked(Option<u32>);

impl Tracked {
    fn new(pid: Option<u32>, group: bool) -> Self {
        if let Some(pid) = pid {
            if let Ok(mut c) = CHILDREN.lock() {
                c.push(Entry {
                    pid,
                    exited: false,
                    group,
                });
                while c.len() > MAX_TRACKED {
                    match c.iter().position(|e| e.exited) {
                        Some(i) => c.remove(i),
                        None => break,
                    };
                }
            }
        }
        Self(pid)
    }
}

impl Drop for Tracked {
    fn drop(&mut self) {
        if let (Some(pid), Ok(mut c)) = (self.0, CHILDREN.lock()) {
            c.retain_mut(|e| {
                if e.pid != pid || e.exited {
                    return true;
                }
                e.exited = true;
                e.group
            });
        }
    }
}

#[cfg(unix)]
fn kill_group_cmd(pid: u32) -> String {
    format!("kill -9 -{pid} 2>/dev/null; kill -9 {pid} 2>/dev/null")
}

fn kill_tree(pid: u32) {
    #[cfg(unix)]
    let _ = std::process::Command::new("sh")
        .args(["-c", &kill_group_cmd(pid)])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    #[cfg(windows)]
    let _ = std::process::Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(unix)]
fn kill_leftover_group(pid: u32) {
    let _ = std::process::Command::new("sh")
        .args(["-c", &format!("kill -9 -{pid} 2>/dev/null")])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

pub(super) fn kill_all() {
    let entries = match CHILDREN.lock() {
        Ok(mut c) => std::mem::take(&mut *c),
        Err(_) => return,
    };
    for e in entries {
        if !e.exited {
            kill_tree(e.pid);
        } else if e.group {
            #[cfg(unix)]
            kill_leftover_group(e.pid);
        }
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Default,
    Inherit,
    Forward,
    None,
}

fn kind_of(func: &str, name: &str) -> mlua::Result<Kind> {
    Ok(match name {
        "default" => Kind::Default,
        "inherit" => Kind::Inherit,
        "forward" => Kind::Forward,
        "none" => Kind::None,
        _ => {
            return Err(mlua::Error::runtime(format!(
                "process.{func}: invalid stdio kind '{name}', valid kinds: {STDIO_KINDS}"
            )));
        }
    })
}

enum StdinKind {
    Null,
    Inherit,
    Data(Vec<u8>),
}

struct Opts {
    cwd: Option<String>,
    env: Vec<(String, String)>,
    shell: Option<String>,
    stdin: StdinKind,
    out: Kind,
    err: Kind,
    timeout: Option<Duration>,
}

fn parse_opts(func: &str, options: Option<Table>) -> mlua::Result<Opts> {
    let mut o = Opts {
        cwd: None,
        env: Vec::new(),
        shell: None,
        stdin: StdinKind::Null,
        out: Kind::Default,
        err: Kind::Default,
        timeout: None,
    };
    let raw_timeout = match &options {
        Some(t) => t.get::<Option<f64>>("timeout")?,
        None => None,
    };
    if func == "exec" {
        o.timeout = timeout_with_default("process.exec", raw_timeout, DEFAULT_EXEC_TIMEOUT_SECS)?;
    } else if raw_timeout.is_some() {
        return Err(mlua::Error::runtime(format!(
            "process.{func}: options.timeout is only supported by process.exec (use the handle's kill())"
        )));
    }
    let Some(t) = options else { return Ok(o) };
    o.cwd = t.get::<Option<String>>("cwd")?;
    if let Some(env) = t.get::<Option<Table>>("env")? {
        for pair in env.pairs::<String, String>() {
            o.env.push(pair?);
        }
    }
    o.shell = match t.get::<Value>("shell")? {
        Value::Boolean(true) => Some(String::new()),
        Value::String(s) => Some(s.to_str()?.to_string()),
        _ => None,
    };
    match t.get::<Value>("stdio")? {
        Value::Nil => {}
        Value::String(s) => {
            let k = kind_of(func, &s.to_str()?)?;
            (o.out, o.err) = (k, k);
            if matches!(k, Kind::Inherit | Kind::Forward) {
                o.stdin = StdinKind::Inherit;
            }
        }
        Value::Table(st) => {
            if let Some(data) = st.get::<Option<mlua::String>>("stdin")? {
                o.stdin = StdinKind::Data(data.as_bytes().to_vec());
            }
            if let Some(k) = st.get::<Option<String>>("stdout")? {
                o.out = kind_of(func, &k)?;
            }
            if let Some(k) = st.get::<Option<String>>("stderr")? {
                o.err = kind_of(func, &k)?;
            }
        }
        _ => {
            return Err(mlua::Error::runtime(format!(
                "process.{func}: stdio must be a string ({STDIO_KINDS}) or a table"
            )));
        }
    }
    Ok(o)
}

fn out_stdio(k: Kind) -> Stdio {
    match k {
        Kind::Default | Kind::Forward => Stdio::piped(),
        Kind::Inherit => Stdio::inherit(),
        Kind::None => Stdio::null(),
    }
}

async fn read_all<R: AsyncRead + Unpin>(
    reader: Option<R>,
    forward: bool,
    to_stderr: bool,
) -> mlua::Result<Vec<u8>> {
    let mut all = Vec::new();
    let Some(mut r) = reader else { return Ok(all) };
    let mut chunk = [0u8; 8192];
    while let Ok(n) = r.read(&mut chunk).await {
        if n == 0 {
            break;
        }
        if all.len() + n > MAX_BYTES {
            return Err(too_big(if to_stderr {
                "process.exec: stderr"
            } else {
                "process.exec: stdout"
            }));
        }
        all.extend_from_slice(&chunk[..n]);
        if forward {
            if to_stderr {
                let mut e = tokio::io::stderr();
                let _ = e.write_all(&chunk[..n]).await;
                let _ = e.flush().await;
            } else {
                let mut o = tokio::io::stdout();
                let _ = o.write_all(&chunk[..n]).await;
                let _ = o.flush().await;
            }
        }
    }
    Ok(all)
}

fn build_command(program: &str, args: &[String], o: &Opts) -> Command {
    let mut cmd = if let Some(shell) = &o.shell {
        let name = if shell.is_empty() {
            if cfg!(windows) { "cmd" } else { "sh" }
        } else {
            shell.as_str()
        };
        let lower = name.to_lowercase();
        let flag = if lower.starts_with("cmd") {
            "/C"
        } else if lower.starts_with("powershell") || lower.starts_with("pwsh") {
            "-Command"
        } else {
            "-c"
        };
        let mut c = Command::new(name);
        c.arg(flag).arg(
            std::iter::once(program)
                .chain(args.iter().map(String::as_str))
                .collect::<Vec<_>>()
                .join(" "),
        );
        c
    } else {
        let mut c = Command::new(program);
        c.args(args);
        c
    };
    if let Some(cwd) = &o.cwd {
        cmd.current_dir(cwd);
    }
    cmd.envs(o.env.iter().map(|(k, v)| (k, v)));
    cmd.stdin(match o.stdin {
        StdinKind::Null => Stdio::null(),
        StdinKind::Inherit => Stdio::inherit(),
        StdinKind::Data(_) => Stdio::piped(),
    });
    cmd.stdout(out_stdio(o.out)).stderr(out_stdio(o.err));
    cmd.kill_on_drop(true);
    #[cfg(unix)]
    if !matches!(o.stdin, StdinKind::Inherit) {
        cmd.process_group(0);
    }
    cmd
}

#[derive(Clone, Copy)]
struct ExitInfo {
    ok: bool,
    code: i32,
}

#[derive(Clone)]
struct Writer(Arc<Mutex<Option<tokio::process::ChildStdin>>>);
#[derive(Clone)]
struct Reader(Arc<Mutex<Option<Box<dyn AsyncRead + Send + Unpin>>>>);

fn stream_err(name: &str, e: &std::io::Error) -> mlua::Error {
    mlua::Error::runtime(format!("process.create: {name}: {e}"))
}

impl UserData for Writer {
    fn add_methods<M: UserDataMethods<Self>>(methods: &mut M) {
        methods.add_async_method("write", |_, this, data: mlua::String| {
            let bytes = data.as_bytes().to_vec();
            async move {
                let mut guard = this.0.lock().await;
                let w = guard
                    .as_mut()
                    .ok_or_else(|| mlua::Error::runtime("process.create: stdin is closed"))?;
                w.write_all(&bytes)
                    .await
                    .map_err(|e| stream_err("write", &e))?;
                w.flush().await.map_err(|e| stream_err("write", &e))
            }
        });
        methods.add_async_method("close", |_, this, ()| async move {
            let mut guard = this.0.lock().await;
            if let Some(mut w) = guard.take() {
                let _ = w.shutdown().await;
            }
            Ok(())
        });
    }
}

const MAX_READ: usize = 64 << 20;

impl UserData for Reader {
    fn add_methods<M: UserDataMethods<Self>>(methods: &mut M) {
        methods.add_async_method("read", |lua, this, size: Option<usize>| async move {
            let mut guard = this.0.lock().await;
            let Some(r) = guard.as_mut() else {
                return Ok(None);
            };
            let mut buf = vec![0u8; size.unwrap_or(8192).clamp(1, MAX_READ)];
            let n = r.read(&mut buf).await.map_err(|e| stream_err("read", &e))?;
            if n == 0 {
                return Ok(None);
            }
            buf.truncate(n);
            Ok(Some(lua.create_string(&buf)?))
        });
        methods.add_async_method("readToEnd", |lua, this, ()| async move {
            let mut guard = this.0.lock().await;
            let buf = match guard.as_mut() {
                Some(r) => read_capped(r)
                    .await
                    .map_err(|e| stream_err("readToEnd", &e))?
                    .ok_or_else(|| too_big("process.create: readToEnd"))?,
                None => Vec::new(),
            };
            lua.create_string(&buf)
        });
    }
}

pub fn module(lua: Lua) -> mlua::Result<Table> {
    let process = lua.create_table()?;
    process.set("os", std::env::consts::OS.to_lowercase())?;
    process.set("arch", std::env::consts::ARCH.to_lowercase())?;
    process.set(
        "endianness",
        if cfg!(target_endian = "big") {
            "big"
        } else {
            "little"
        },
    )?;
    process.set(
        "args",
        ProcessArgs::empty().into_plain_lua_table(lua.clone())?,
    )?;
    let mut cwd = get_current_dir().to_string_lossy().into_owned();
    if !cwd.ends_with(std::path::MAIN_SEPARATOR) {
        cwd.push(std::path::MAIN_SEPARATOR);
    }
    process.set("cwd", cwd)?;
    process.set(
        "env",
        ProcessEnv::current().into_plain_lua_table(lua.clone())?,
    )?;
    process.set(
        "exit",
        lua.create_function(|_, code: Option<i32>| -> mlua::Result<()> {
            kill_all();
            std::process::exit(code.unwrap_or(0))
        })?,
    )?;
    let exec = lua.create_async_function(
        |lua, (program, args, options): (String, Option<Vec<String>>, Option<Table>)| async move {
            let args = args.unwrap_or_default();
            let o = parse_opts("exec", options)?;
            let mut child = build_command(&program, &args, &o).spawn().map_err(|e| {
                mlua::Error::runtime(format!("process.exec: failed to run '{program}': {e}"))
            })?;
            let _tracked = Tracked::new(child.id(), cfg!(unix) && o.shell.is_some());
            let stdin = child.stdin.take();
            let data = if let StdinKind::Data(d) = o.stdin {
                Some(d)
            } else {
                None
            };
            let feed = async move {
                if let (Some(mut si), Some(d)) = (stdin, data) {
                    let _ = si.write_all(&d).await;
                    let _ = si.shutdown().await;
                }
            };
            let (timeout, out_kind, err_kind) = (o.timeout, o.out, o.err);
            let (out_reader, err_reader) = (child.stdout.take(), child.stderr.take());
            let run = async {
                let (_, stdout, stderr) = tokio::try_join!(
                    async {
                        feed.await;
                        Ok::<(), mlua::Error>(())
                    },
                    read_all(out_reader, out_kind == Kind::Forward, false),
                    read_all(err_reader, err_kind == Kind::Forward, true)
                )?;
                let status = child
                    .wait()
                    .await
                    .map_err(|e| mlua::Error::runtime(format!("process.exec: {e}")))?;
                Ok::<_, mlua::Error>((status, stdout, stderr))
            };
            let outcome = match timeout {
                Some(limit) => tokio::time::timeout(limit, run).await.unwrap_or_else(|_| {
                    Err(mlua::Error::runtime(format!(
                        "process.exec: timed out after {}s",
                        limit.as_secs_f64()
                    )))
                }),
                None => run.await,
            };
            let (status, stdout, stderr) = match outcome {
                Ok(v) => v,
                Err(e) => {
                    if let Some(pid) = child.id() {
                        kill_tree(pid);
                    }
                    let _ = child.kill().await;
                    return Err(e);
                }
            };
            let res = lua.create_table()?;
            res.set("ok", status.success())?;
            res.set(
                "code",
                status
                    .code()
                    .unwrap_or_else(|| i32::from(!stderr.is_empty())),
            )?;
            res.set("stdout", lua.create_string(&stdout)?)?;
            res.set("stderr", lua.create_string(&stderr)?)?;
            Ok(res)
        },
    )?;
    process.set("exec", exec)?;
    let create = lua.create_function(
        |lua, (program, args, options): (String, Option<Vec<String>>, Option<Table>)| {
            let args = args.unwrap_or_default();
            let o = parse_opts("create", options)?;
            let mut cmd = build_command(&program, &args, &o);
            cmd.stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            let mut child = cmd.spawn().map_err(|e| {
                mlua::Error::runtime(format!("process.create: failed to run '{program}': {e}"))
            })?;
            let stdin = Writer(Arc::new(Mutex::new(child.stdin.take())));
            let boxed =
                |r: Option<Box<dyn AsyncRead + Send + Unpin>>| Reader(Arc::new(Mutex::new(r)));
            let stdout = boxed(
                child
                    .stdout
                    .take()
                    .map(|r| Box::new(r) as Box<dyn AsyncRead + Send + Unpin>),
            );
            let stderr = boxed(
                child
                    .stderr
                    .take()
                    .map(|r| Box::new(r) as Box<dyn AsyncRead + Send + Unpin>),
            );
            let kill = Arc::new(Notify::new());
            let (tx, rx) = watch::channel(None);
            let tracked = Tracked::new(child.id(), cfg!(unix) && o.shell.is_some());
            let kill_wait = kill.clone();
            let guard = super::lune_task::LiveGuard::new(lua);
            tokio::task::spawn_local(async move {
                let _guard = guard;
                let _tracked = tracked;
                let status = tokio::select! {
                    r = child.wait() => r,
                    () = kill_wait.notified() => {
                        if let Some(pid) = child.id() {
                            kill_tree(pid);
                        }
                        let _ = child.kill().await;
                        child.wait().await
                    }
                };
                let info = match status {
                    Ok(st) => ExitInfo {
                        ok: st.success(),
                        code: st.code().unwrap_or(9),
                    },
                    Err(_) => ExitInfo { ok: false, code: 9 },
                };
                let _ = tx.send(Some(info));
            });
            let handle = lua.create_table()?;
            handle.set("stdin", stdin)?;
            handle.set("stdout", stdout)?;
            handle.set("stderr", stderr)?;
            handle.set(
                "kill",
                lua.create_function(move |_, ()| {
                    kill.notify_one();
                    Ok(())
                })?,
            )?;
            handle.set(
                "status",
                lua.create_async_function(move |lua, ()| {
                    let mut rx = rx.clone();
                    async move {
                        let info = {
                            let seen = rx.wait_for(|v| v.is_some()).await.map_err(|_| {
                                mlua::Error::runtime("process.create: the child's status is gone")
                            })?;
                            (*seen).unwrap_or(ExitInfo { ok: false, code: 9 })
                        };
                        let t = lua.create_table()?;
                        t.set("ok", info.ok)?;
                        t.set("code", info.code)?;
                        Ok(t)
                    }
                })?,
            )?;
            Ok(handle)
        },
    )?;
    process.set("create", create)?;
    process.set_readonly(true);
    Ok(process)
}
