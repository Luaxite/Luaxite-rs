use futures_util::{Sink, SinkExt, Stream, StreamExt};
use http_body_util::{BodyExt, Full, LengthLimitError, Limited};
use hyper::body::{Bytes, Incoming};
use hyper_util::rt::TokioIo;
use mlua::{Function, IntoLuaMulti, Lua, Table, UserData, UserDataFields, UserDataMethods, Value};
use std::{
    net::SocketAddr,
    pin::Pin,
    sync::{
        Arc, LazyLock,
        atomic::{AtomicU32, Ordering},
    },
    time::Duration,
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{
    TcpStream,
    tcp::{OwnedReadHalf, OwnedWriteHalf},
};
use tokio::sync::{Mutex, oneshot, watch};
use tokio_tungstenite::{
    WebSocketStream,
    tungstenite::{
        Error as WsError, Message,
        handshake::derive_accept_key,
        protocol::{CloseFrame, Role, frame::coding::CloseCode},
    },
};

use super::lune_libs::{DEFAULT_REQUEST_TIMEOUT_SECS, MAX_BYTES, timeout_with_default, too_big};

fn encode_bytes(bytes: &[u8]) -> Vec<u8> {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = Vec::with_capacity(bytes.len());
    for &b in bytes {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(b);
        } else {
            out.extend_from_slice(&[b'%', HEX[usize::from(b >> 4)], HEX[usize::from(b & 15)]]);
        }
    }
    out
}

fn decode_bytes(bytes: &[u8]) -> Vec<u8> {
    let hex = |i: usize| bytes.get(i).and_then(|b| char::from(*b).to_digit(16));
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            if let (Some(h), Some(l)) = (hex(i + 1), hex(i + 2)) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    out
}

fn check_text(func: &str, bytes: Vec<u8>, as_binary: bool) -> mlua::Result<Vec<u8>> {
    if !as_binary && std::str::from_utf8(&bytes).is_err() {
        return Err(mlua::Error::runtime(format!(
            "net.{func}: invalid UTF-8 (pass true as the second argument to work on raw bytes)"
        )));
    }
    Ok(bytes)
}

#[derive(Clone)]
struct Tcp {
    local: Option<SocketAddr>,
    remote: Option<SocketAddr>,
    read: Arc<Mutex<Option<OwnedReadHalf>>>,
    write: Arc<Mutex<Option<OwnedWriteHalf>>>,
}

/// Largest buffer one `read(n)` allocates: a huge `n` (2^40) must not abort the process. A read returns what is available anyway.
const MAX_READ: usize = 64 << 20;

fn tcp_err(name: &str, e: &std::io::Error) -> mlua::Error {
    mlua::Error::runtime(format!("net.tcp.{name}: {e}"))
}

impl UserData for Tcp {
    fn add_fields<F: UserDataFields<Self>>(fields: &mut F) {
        fields.add_field_method_get("localIp", |_, this| {
            Ok(this.local.map(|a| a.ip().to_string()))
        });
        fields.add_field_method_get("localPort", |_, this| Ok(this.local.map(|a| a.port())));
        fields.add_field_method_get("remoteIp", |_, this| {
            Ok(this.remote.map(|a| a.ip().to_string()))
        });
        fields.add_field_method_get("remotePort", |_, this| Ok(this.remote.map(|a| a.port())));
    }

    fn add_methods<M: UserDataMethods<Self>>(methods: &mut M) {
        methods.add_async_method("read", |lua, this, size: Option<usize>| async move {
            let mut guard = this.read.lock().await;
            let mut buf = vec![0u8; size.unwrap_or(8192).clamp(1, MAX_READ)];
            let n = match guard.as_mut() {
                Some(r) => r.read(&mut buf).await.map_err(|e| tcp_err("read", &e))?,
                None => 0,
            };
            lua.create_string(&buf[..n])
        });
        methods.add_async_method("write", |_, this, data: mlua::String| {
            let bytes = data.as_bytes().to_vec();
            async move {
                let mut guard = this.write.lock().await;
                let w = guard
                    .as_mut()
                    .ok_or_else(|| mlua::Error::runtime("net.tcp.write: the stream is closed"))?;
                w.write_all(&bytes)
                    .await
                    .map_err(|e| tcp_err("write", &e))?;
                w.flush().await.map_err(|e| tcp_err("write", &e))
            }
        });
        methods.add_async_method("close", |_, this, ()| async move {
            if let Some(mut w) = this.write.lock().await.take() {
                let _ = w.shutdown().await;
            }
            Ok(())
        });
    }
}

async fn tcp_connect(_: Lua, (host, port, config): (String, u16, Value)) -> mlua::Result<Tcp> {
    let (mut tls, mut ttl) = (false, None);
    match &config {
        Value::Nil => {}
        Value::Boolean(b) => tls = *b,
        Value::Table(t) => {
            tls = t.get::<Option<bool>>("tls")?.unwrap_or(false);
            ttl = t.get::<Option<u32>>("ttl")?;
        }
        _ => {
            return Err(mlua::Error::runtime(
                "net.tcp.connect: the config must be a boolean or a table { tls?, ttl? }",
            ));
        }
    }
    if tls {
        return Err(mlua::Error::runtime(
            "net.tcp.connect: not implemented yet: tls",
        ));
    }
    let stream = TcpStream::connect((host.as_str(), port))
        .await
        .map_err(|e| tcp_err("connect", &e))?;
    if let Some(ttl) = ttl {
        stream.set_ttl(ttl).map_err(|e| tcp_err("connect", &e))?;
    }
    let (local, remote) = (stream.local_addr().ok(), stream.peer_addr().ok());
    let (r, w) = stream.into_split();
    Ok(Tcp {
        local,
        remote,
        read: Arc::new(Mutex::new(Some(r))),
        write: Arc::new(Mutex::new(Some(w))),
    })
}

/// How long `net.request` waits for the connection to open (TCP and TLS handshake). The whole request is limited by
/// `options.timeout` (default `DEFAULT_REQUEST_TIMEOUT_SECS`; `timeout = 0` removes the limit).
const CONNECT_TIMEOUT: Duration = Duration::from_secs(30);

/// The `timeout` of a `net.request` from its `options.timeout`: absent -> `DEFAULT_REQUEST_TIMEOUT_SECS`, `0` -> `None` (no limit).
fn request_timeout(secs: Option<f64>) -> mlua::Result<Option<Duration>> {
    timeout_with_default("net.request", secs, DEFAULT_REQUEST_TIMEOUT_SECS)
}

fn build_client(decompress: bool) -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .user_agent(concat!("luaxite/", env!("CARGO_PKG_VERSION")))
        .gzip(decompress)
        .deflate(decompress)
        .brotli(decompress)
        .build()
        .expect("reqwest client")
}
static CLIENT: LazyLock<reqwest::Client> = LazyLock::new(|| build_client(true));
static CLIENT_RAW: LazyLock<reqwest::Client> = LazyLock::new(|| build_client(false));

struct ReqSpec {
    url: reqwest::Url,
    method: reqwest::Method,
    body: Option<Vec<u8>>,
    headers: Vec<(String, String)>,
    decompress: bool,
    /// `options.timeout`: from connecting until the whole body has been read; the default when the script gives none. `None` = no limit (`timeout = 0`).
    timeout: Option<Duration>,
}

/// A reqwest failure as a Lua error; a timeout (connect or `options.timeout`) reads `net.request: timed out`.
fn req_err(e: reqwest::Error) -> mlua::Error {
    if e.is_timeout() {
        mlua::Error::runtime("net.request: timed out")
    } else {
        mlua::Error::runtime(format!("net.request: {e}"))
    }
}

fn string_pairs(what: &str, t: &Table) -> mlua::Result<Vec<(String, String)>> {
    t.pairs::<String, String>()
        .collect::<mlua::Result<Vec<_>>>()
        .map_err(|e| {
            mlua::Error::runtime(format!(
                "net.request: {what} must map strings to strings ({e})"
            ))
        })
}

fn parse_request(v: Value) -> mlua::Result<ReqSpec> {
    let parse_url = |s: &str| {
        reqwest::Url::parse(s)
            .map_err(|e| mlua::Error::runtime(format!("net.request: invalid url '{s}' ({e})")))
    };
    match v {
        Value::String(s) => Ok(ReqSpec {
            url: parse_url(&s.to_str()?)?,
            method: reqwest::Method::GET,
            body: None,
            headers: Vec::new(),
            decompress: true,
            timeout: request_timeout(None)?,
        }),
        Value::Table(t) => {
            let url = t.get::<Option<String>>("url")?.ok_or_else(|| {
                mlua::Error::runtime("net.request: the config needs a url string")
            })?;
            let mut url = parse_url(&url)?;
            if let Some(q) = t.get::<Option<Table>>("query")? {
                let mut pairs = url.query_pairs_mut();
                for (k, v) in string_pairs("query", &q)? {
                    pairs.append_pair(&k, &v);
                }
            }
            let method = match t.get::<Option<String>>("method")? {
                Some(m) => {
                    reqwest::Method::from_bytes(m.to_uppercase().as_bytes()).map_err(|_| {
                        mlua::Error::runtime(format!("net.request: invalid method '{m}'"))
                    })?
                }
                None => reqwest::Method::GET,
            };
            let body = t
                .get::<Option<mlua::String>>("body")?
                .map(|b| b.as_bytes().to_vec());
            let headers = match t.get::<Option<Table>>("headers")? {
                Some(h) => string_pairs("headers", &h)?,
                None => Vec::new(),
            };
            let (decompress, timeout) = match t.get::<Option<Table>>("options")? {
                Some(o) => (
                    o.get::<Option<bool>>("decompress")?.unwrap_or(true),
                    request_timeout(o.get::<Option<f64>>("timeout")?)?,
                ),
                None => (true, request_timeout(None)?),
            };
            Ok(ReqSpec {
                url,
                method,
                body,
                headers,
                decompress,
                timeout,
            })
        }
        other => Err(mlua::Error::runtime(format!(
            "net.request: expected a url string or a config table, got {}",
            other.type_name()
        ))),
    }
}

#[derive(Clone)]
struct Response {
    status: u16,
    message: String,
    headers: Vec<(String, Vec<String>)>,
    body: Arc<Vec<u8>>,
}

impl UserData for Response {
    fn add_fields<F: UserDataFields<Self>>(fields: &mut F) {
        fields.add_field_method_get("ok", |_, this| Ok((200..300).contains(&this.status)));
        fields.add_field_method_get("statusCode", |_, this| Ok(this.status));
        fields.add_field_method_get("statusMessage", |_, this| Ok(this.message.clone()));
        fields.add_field_method_get("headers", |lua, this| {
            let t = lua.create_table()?;
            for (name, values) in &this.headers {
                if let [one] = values.as_slice() {
                    t.set(name.as_str(), one.as_str())?;
                } else {
                    t.set(
                        name.as_str(),
                        lua.create_sequence_from(values.iter().map(String::as_str))?,
                    )?;
                }
            }
            Ok(t)
        });
        fields.add_field_method_get("body", |lua, this| lua.create_string(this.body.as_slice()));
    }
}

async fn send_request(spec: ReqSpec) -> mlua::Result<Response> {
    let client = if spec.decompress {
        &*CLIENT
    } else {
        &*CLIENT_RAW
    };
    let mut req = client.request(spec.method, spec.url);
    for (k, v) in spec.headers {
        req = req.header(k, v);
    }
    if let Some(body) = spec.body {
        req = req.body(body);
    }
    if let Some(timeout) = spec.timeout {
        req = req.timeout(timeout);
    }
    let mut resp = req.send().await.map_err(req_err)?;
    let status = resp.status();
    let mut headers: Vec<(String, Vec<String>)> = Vec::new();
    for (name, value) in resp.headers() {
        let Ok(value) = value.to_str() else { continue };
        match headers.iter_mut().find(|(n, _)| n == name.as_str()) {
            Some((_, values)) => values.push(value.to_owned()),
            None => headers.push((name.as_str().to_owned(), vec![value.to_owned()])),
        }
    }
    // The announced length is checked first; the chunks are counted as decoded (gzip/deflate/brotli), so a
    // compressed bomb or a server that lies about its length is stopped too.
    let too_large = || too_big("net.request: response body");
    if resp.content_length().is_some_and(|n| n > MAX_BYTES as u64) {
        return Err(too_large());
    }
    let mut body: Vec<u8> = Vec::new();
    while let Some(chunk) = resp.chunk().await.map_err(req_err)? {
        if body.len() + chunk.len() > MAX_BYTES {
            return Err(too_large());
        }
        body.extend_from_slice(&chunk);
    }
    Ok(Response {
        status: status.as_u16(),
        message: status.canonical_reason().unwrap_or_default().to_owned(),
        headers,
        body: Arc::new(body),
    })
}

type WsSink = Pin<Box<dyn Sink<Message, Error = WsError> + Send>>;
type WsSource = Pin<Box<dyn Stream<Item = Result<Message, WsError>> + Send>>;

const OPEN: u32 = u32::MAX;

#[derive(Clone)]
pub(super) struct Socket {
    sink: Arc<Mutex<WsSink>>,
    source: Arc<Mutex<WsSource>>,
    close_code: Arc<AtomicU32>,
}

impl Socket {
    pub(super) fn new<S>(stream: S) -> Self
    where
        S: Sink<Message, Error = WsError>
            + Stream<Item = Result<Message, WsError>>
            + Send
            + 'static,
    {
        let (sink, source) = stream.split();
        let (sink, source): (WsSink, WsSource) = (Box::pin(sink), Box::pin(source));
        Self {
            sink: Arc::new(Mutex::new(sink)),
            source: Arc::new(Mutex::new(source)),
            close_code: Arc::new(AtomicU32::new(OPEN)),
        }
    }

    fn code(&self) -> Option<u16> {
        u16::try_from(self.close_code.load(Ordering::SeqCst)).ok()
    }

    fn set_code(&self, code: u16) {
        let _ = self.close_code.compare_exchange(
            OPEN,
            u32::from(code),
            Ordering::SeqCst,
            Ordering::SeqCst,
        );
    }
}

fn ws_err(name: &str, e: impl std::fmt::Display) -> mlua::Error {
    mlua::Error::runtime(format!("net.socket.{name}: {e}"))
}

impl UserData for Socket {
    fn add_fields<F: UserDataFields<Self>>(fields: &mut F) {
        fields.add_field_method_get("closeCode", |_, this| Ok(this.code()));
    }

    fn add_methods<M: UserDataMethods<Self>>(methods: &mut M) {
        methods.add_async_method("close", |_, this, code: Option<u16>| {
            let this = this.clone();
            async move {
                let code = code.unwrap_or(1000);
                if this.code().is_some() {
                    return Ok(());
                }
                this.set_code(code);
                let frame = CloseFrame {
                    code: CloseCode::from(code),
                    reason: "".into(),
                };
                let mut sink = this.sink.lock().await;
                let _ = sink.send(Message::Close(Some(frame))).await;
                let _ = sink.flush().await;
                Ok(())
            }
        });
        methods.add_async_method(
            "send",
            |_, this, (msg, as_binary): (mlua::String, Option<bool>)| {
                let bytes = msg.as_bytes().to_vec();
                let this = this.clone();
                async move {
                    if this.code().is_some() {
                        return Err(mlua::Error::runtime(
                            "net.socket.send: the socket is closed",
                        ));
                    }
                    let frame = if as_binary.unwrap_or(false) {
                        Message::binary(bytes)
                    } else {
                        let text = String::from_utf8(bytes).map_err(|_| {
                            ws_err(
                                "send",
                                "text messages must be valid UTF-8 (pass asBinary = true)",
                            )
                        })?;
                        Message::text(text)
                    };
                    this.sink
                        .lock()
                        .await
                        .send(frame)
                        .await
                        .map_err(|e| ws_err("send", e))
                }
            },
        );
        methods.add_async_method("next", |lua, this, ()| {
            let this = this.clone();
            async move {
                if this.code().is_some() {
                    return Ok(None);
                }
                let mut source = this.source.lock().await;
                loop {
                    match source.next().await {
                        None => {
                            this.set_code(1006);
                            return Ok(None);
                        }
                        Some(Err(
                            WsError::ConnectionClosed
                            | WsError::AlreadyClosed
                            | WsError::Io(_)
                            | WsError::Protocol(
                                tokio_tungstenite::tungstenite::error::ProtocolError::ResetWithoutClosingHandshake,
                            ),
                        )) => {
                            // the peer vanished (killed, reset): the stream just ends, like a close with code 1006
                            this.set_code(1006);
                            return Ok(None);
                        }
                        Some(Err(e)) => return Err(ws_err("next", e)),
                        Some(Ok(Message::Text(t))) => {
                            return Ok(Some(lua.create_string(t.as_str().as_bytes())?));
                        }
                        Some(Ok(Message::Binary(b))) => {
                            return Ok(Some(lua.create_string(&b[..])?));
                        }
                        Some(Ok(Message::Close(frame))) => {
                            this.set_code(frame.map_or(1005, |f| u16::from(f.code)));
                            let _ = this.sink.lock().await.flush().await;
                            return Ok(None);
                        }
                        Some(Ok(_)) => {}
                    }
                }
            }
        });
    }
}

async fn socket_connect(_: Lua, url: String) -> mlua::Result<Socket> {
    let (stream, _response) = tokio_tungstenite::connect_async(url)
        .await
        .map_err(|e| mlua::Error::runtime(format!("net.socket: {e}")))?;
    Ok(Socket::new(stream))
}

struct Reply {
    status: u16,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
}

fn parse_reply(v: Value) -> mlua::Result<Reply> {
    match v {
        Value::Nil => Ok(Reply {
            status: 200,
            headers: Vec::new(),
            body: Vec::new(),
        }),
        Value::String(s) => Ok(Reply {
            status: 200,
            headers: Vec::new(),
            body: s.as_bytes().to_vec(),
        }),
        Value::Table(t) => {
            let status = t.get::<Option<u16>>("status")?.unwrap_or(200);
            let headers = match t.get::<Option<Table>>("headers")? {
                Some(h) => h
                    .pairs::<String, String>()
                    .collect::<mlua::Result<Vec<_>>>()
                    .map_err(|e| {
                        mlua::Error::runtime(format!(
                            "net.serve: reply headers must map strings to strings ({e})"
                        ))
                    })?,
                None => Vec::new(),
            };
            let body = t
                .get::<Option<mlua::String>>("body")?
                .map(|b| b.as_bytes().to_vec())
                .unwrap_or_default();
            Ok(Reply {
                status,
                headers,
                body,
            })
        }
        _ => Err(mlua::Error::runtime(
            "net.serve: the handler must return a string or a table { status?, headers?, body? }",
        )),
    }
}

fn build_response(reply: Option<Reply>) -> hyper::Response<Full<Bytes>> {
    let fail = || {
        let mut r = hyper::Response::new(Full::new(Bytes::from_static(b"Internal Server Error")));
        *r.status_mut() = hyper::StatusCode::INTERNAL_SERVER_ERROR;
        r
    };
    let Some(reply) = reply else { return fail() };
    let mut b = hyper::Response::builder().status(reply.status);
    for (k, v) in &reply.headers {
        b = b.header(k.as_str(), v.as_str());
    }
    b.body(Full::new(Bytes::from(reply.body)))
        .unwrap_or_else(|_| fail())
}

/// The reply to a request whose body is over `MAX_BYTES`. `Connection: close`: the unread rest of the body
/// must not be parsed as the next request.
fn payload_too_large() -> hyper::Response<Full<Bytes>> {
    let mut r = hyper::Response::new(Full::new(Bytes::from_static(b"Payload Too Large")));
    *r.status_mut() = hyper::StatusCode::PAYLOAD_TOO_LARGE;
    r.headers_mut().insert(
        hyper::header::CONNECTION,
        hyper::header::HeaderValue::from_static("close"),
    );
    r
}

struct ServeRequest {
    ip: String,
    port: u16,
    method: String,
    path: String,
    query: Vec<(String, String)>,
    headers: Vec<(String, String)>,
    body: Arc<Vec<u8>>,
}

fn pairs_table(lua: &Lua, pairs: &[(String, String)]) -> mlua::Result<Table> {
    let t = lua.create_table()?;
    for (k, v) in pairs {
        let v = match t.get::<Option<String>>(k.as_str())? {
            Some(old) => format!("{old}, {v}"),
            None => v.clone(),
        };
        t.set(k.as_str(), v)?;
    }
    Ok(t)
}

impl UserData for ServeRequest {
    fn add_fields<F: UserDataFields<Self>>(fields: &mut F) {
        fields.add_field_method_get("ip", |_, this| Ok(this.ip.clone()));
        fields.add_field_method_get("port", |_, this| Ok(this.port));
        fields.add_field_method_get("method", |_, this| Ok(this.method.clone()));
        fields.add_field_method_get("path", |_, this| Ok(this.path.clone()));
        fields.add_field_method_get("query", |lua, this| pairs_table(lua, &this.query));
        fields.add_field_method_get("headers", |lua, this| pairs_table(lua, &this.headers));
        fields.add_field_method_get("body", |lua, this| lua.create_string(this.body.as_slice()));
    }
}

fn parse_query(q: Option<&str>) -> Vec<(String, String)> {
    // form decoding: `+` is a space (what the client's query encoder writes); `%2B` stays a plus
    let dec = |s: &str| {
        let spaced: Vec<u8> = s
            .bytes()
            .map(|b| if b == b'+' { b' ' } else { b })
            .collect();
        String::from_utf8_lossy(&decode_bytes(&spaced)).into_owned()
    };
    q.unwrap_or("")
        .split('&')
        .filter(|p| !p.is_empty())
        .map(|p| match p.split_once('=') {
            Some((k, v)) => (dec(k), dec(v)),
            None => (dec(p), String::new()),
        })
        .collect()
}

const HANDLER_SRC: &str = "local handler, request, done = ...\nlocal ok, result = pcall(handler, request)\ndone(ok, result)";

#[derive(Clone)]
struct Handlers {
    request: Option<Function>,
    web_socket: Option<Function>,
    wrapper: Function,
}

fn header_has(req: &hyper::Request<Incoming>, name: &str, token: &str) -> bool {
    req.headers().get_all(name).iter().any(|v| {
        v.to_str()
            .is_ok_and(|v| v.split(',').any(|t| t.trim().eq_ignore_ascii_case(token)))
    })
}

fn is_upgrade(req: &hyper::Request<Incoming>) -> bool {
    req.method() == hyper::Method::GET
        && header_has(req, "upgrade", "websocket")
        && header_has(req, "connection", "upgrade")
        && req.headers().contains_key("sec-websocket-key")
}

fn upgrade_web_socket(
    lua: Lua,
    handler: Function,
    req: &mut hyper::Request<Incoming>,
) -> hyper::Response<Full<Bytes>> {
    let Some(accept) = req
        .headers()
        .get("sec-websocket-key")
        .map(|k| derive_accept_key(k.as_bytes()))
    else {
        return build_response(None);
    };
    let Ok(accept) = hyper::header::HeaderValue::from_str(&accept) else {
        return build_response(None);
    };
    let on_upgrade = hyper::upgrade::on(req);
    tokio::task::spawn_local(async move {
        let upgraded = match on_upgrade.await {
            Ok(u) => u,
            Err(e) => return eprintln!("[luau] net.serve: websocket upgrade failed: {e}"),
        };
        let ws = WebSocketStream::from_raw_socket(TokioIo::new(upgraded), Role::Server, None).await;
        let started = (|| -> mlua::Result<()> {
            let thread = lua.create_thread(handler)?;
            let args = Socket::new(ws).into_lua_multi(&lua)?;
            super::lune_task::run_thread(&lua, thread, args, true);
            Ok(())
        })();
        if let Err(e) = started {
            eprintln!("[luau] net.serve: {e}");
        }
    });
    let mut resp = hyper::Response::new(Full::new(Bytes::new()));
    *resp.status_mut() = hyper::StatusCode::SWITCHING_PROTOCOLS;
    resp.headers_mut().insert(
        hyper::header::UPGRADE,
        hyper::header::HeaderValue::from_static("websocket"),
    );
    resp.headers_mut().insert(
        hyper::header::CONNECTION,
        hyper::header::HeaderValue::from_static("Upgrade"),
    );
    resp.headers_mut().insert("sec-websocket-accept", accept);
    resp
}

async fn handle(
    lua: Lua,
    handlers: Handlers,
    peer: SocketAddr,
    mut req: hyper::Request<Incoming>,
) -> Result<hyper::Response<Full<Bytes>>, std::convert::Infallible> {
    if let Some(ws) = &handlers.web_socket {
        if is_upgrade(&req) {
            return Ok(upgrade_web_socket(lua, ws.clone(), &mut req));
        }
    }
    let Some(handler) = handlers.request.clone() else {
        let mut r = hyper::Response::new(Full::new(Bytes::from_static(b"Not Found")));
        *r.status_mut() = hyper::StatusCode::NOT_FOUND;
        return Ok(r);
    };
    let wrapper = handlers.wrapper.clone();
    let (parts, body) = req.into_parts();
    // Over the cap: 413, and the server keeps running. Not a script error, so the exit code stays as it was.
    let announced = parts
        .headers
        .get(hyper::header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.trim().parse::<u64>().ok());
    if announced.is_some_and(|n| n > MAX_BYTES as u64) {
        return Ok(payload_too_large());
    }
    let body = match Limited::new(body, MAX_BYTES).collect().await {
        Ok(b) => b,
        Err(e) if e.downcast_ref::<LengthLimitError>().is_some() => {
            return Ok(payload_too_large());
        }
        Err(_) => return Ok(build_response(None)),
    };
    let data = ServeRequest {
        ip: peer.ip().to_string(),
        port: peer.port(),
        method: parts.method.as_str().to_owned(),
        path: parts.uri.path().to_owned(),
        query: parse_query(parts.uri.query()),
        headers: parts
            .headers
            .iter()
            .map(|(k, v)| {
                (
                    k.as_str().to_owned(),
                    String::from_utf8_lossy(v.as_bytes()).into_owned(),
                )
            })
            .collect(),
        body: Arc::new(body.to_bytes().to_vec()),
    };
    let (tx, rx) = oneshot::channel::<Reply>();
    let tx = Arc::new(std::sync::Mutex::new(Some(tx)));
    let started = (|| -> mlua::Result<()> {
        let done = lua.create_function(move |_, (ok, v): (bool, Value)| {
            let Some(tx) = tx.lock().ok().and_then(|mut g| g.take()) else {
                return Ok(());
            };
            if !ok {
                let why = match &v {
                    Value::String(s) => s.to_string_lossy().to_string(),
                    other => format!("{other:?}"),
                };
                eprintln!("[luau] net.serve: handler error: {why}");
                return Ok(());
            }
            let _ = tx.send(parse_reply(v)?);
            Ok(())
        })?;
        let thread = lua.create_thread(wrapper)?;
        let args = (handler, data, done).into_lua_multi(&lua)?;
        super::lune_task::run_thread(&lua, thread, args, true);
        Ok(())
    })();
    if let Err(e) = started {
        eprintln!("[luau] net.serve: {e}");
        return Ok(build_response(None));
    }
    Ok(build_response(rx.await.ok()))
}

struct ServeHandle {
    ip: String,
    port: u16,
    stop: Arc<watch::Sender<bool>>,
}

impl UserData for ServeHandle {
    fn add_fields<F: UserDataFields<Self>>(fields: &mut F) {
        fields.add_field_method_get("ip", |_, this| Ok(this.ip.clone()));
        fields.add_field_method_get("port", |_, this| Ok(this.port));
        fields.add_field_method_get("stop", |lua, this| {
            let stop = this.stop.clone();
            lua.create_function(move |_, ()| {
                stop.send_replace(true);
                Ok(())
            })
        });
    }
}

async fn serve_fn(lua: Lua, (port, cfg): (u16, Value)) -> mlua::Result<ServeHandle> {
    let (handler, ws, address) = match cfg {
        Value::Function(f) => (Some(f), None, None),
        Value::Table(t) => (
            t.get::<Option<Function>>("handleRequest")?,
            t.get::<Option<Function>>("handleWebSocket")?,
            t.get::<Option<String>>("address")?,
        ),
        _ => {
            return Err(mlua::Error::runtime(
                "net.serve: expected a function or a config table { handleRequest?, handleWebSocket?, address? }",
            ));
        }
    };
    if handler.is_none() && ws.is_none() {
        return Err(mlua::Error::runtime(
            "net.serve: the config needs a handleRequest (or handleWebSocket) function",
        ));
    }
    let address = address.unwrap_or_else(|| "127.0.0.1".to_owned());
    let listener = tokio::net::TcpListener::bind((address.as_str(), port))
        .await
        .map_err(|e| mlua::Error::runtime(format!("net.serve: {e}")))?;
    let port = listener.local_addr().map_or(port, |a| a.port()); // port 0 asks the OS for a free one
    let wrapper = lua
        .load(HANDLER_SRC)
        .set_name("=net.serve")
        .into_function()?;
    let handlers = Handlers {
        request: handler,
        web_socket: ws,
        wrapper,
    };
    let stop = Arc::new(watch::channel(false).0);
    let guard = super::lune_task::LiveGuard::new(&lua);
    let (task_lua, task_stop) = (lua.clone(), stop.clone());
    tokio::task::spawn_local(async move {
        let _guard = guard;
        let mut stop_rx = task_stop.subscribe();
        loop {
            tokio::select! {
                _ = stop_rx.changed() => break,
                accepted = listener.accept() => match accepted {
                    Ok((stream, peer)) => spawn_connection(task_lua.clone(), handlers.clone(), stream, peer, task_stop.subscribe()),
                    Err(e) => eprintln!("[luau] net.serve: accept failed: {e}"),
                },
            }
        }
    });
    Ok(ServeHandle {
        ip: address,
        port,
        stop,
    })
}

fn spawn_connection(
    lua: Lua,
    handlers: Handlers,
    stream: TcpStream,
    peer: SocketAddr,
    mut stop: watch::Receiver<bool>,
) {
    tokio::task::spawn_local(async move {
        let svc =
            hyper::service::service_fn(move |req| handle(lua.clone(), handlers.clone(), peer, req));
        let conn = hyper::server::conn::http1::Builder::new()
            .serve_connection(TokioIo::new(stream), svc)
            .with_upgrades();
        tokio::pin!(conn);
        tokio::select! {
            _ = conn.as_mut() => {}
            _ = stop.changed() => {
                conn.as_mut().graceful_shutdown();
                let _ = conn.await;
            }
        }
    });
}

pub fn module(lua: Lua) -> mlua::Result<Table> {
    let url_encode = lua.create_function(|lua, (s, as_binary): (mlua::String, Option<bool>)| {
        let bytes = check_text(
            "urlEncode",
            s.as_bytes().to_vec(),
            as_binary.unwrap_or(false),
        )?;
        lua.create_string(encode_bytes(&bytes))
    })?;
    let url_decode = lua.create_function(|lua, (s, as_binary): (mlua::String, Option<bool>)| {
        let decoded = check_text(
            "urlDecode",
            decode_bytes(&s.as_bytes()),
            as_binary.unwrap_or(false),
        )?;
        lua.create_string(&decoded)
    })?;

    let tcp = lua.create_table()?;
    tcp.set("connect", lua.create_async_function(tcp_connect)?)?;
    tcp.set_readonly(true);
    let request = lua.create_async_function(|_, req: Value| {
        let spec = parse_request(req);
        async move { send_request(spec?).await }
    })?;
    let socket = lua.create_async_function(socket_connect)?;
    let serve = lua.create_async_function(serve_fn)?;
    let http = lua.create_table()?;
    http.set("request", request.clone())?;
    http.set("serve", serve.clone())?;
    http.set_readonly(true);
    let ws = lua.create_table()?;
    ws.set("connect", socket.clone())?;
    ws.set_readonly(true);

    let net = lua.create_table()?;
    net.set("urlEncode", url_encode)?;
    net.set("urlDecode", url_decode)?;
    net.set("request", request)?;
    net.set("socket", socket)?;
    net.set("serve", serve)?;
    net.set("tcp", tcp)?;
    net.set("http", http)?;
    net.set("ws", ws)?;
    net.set_readonly(true);
    Ok(net)
}
