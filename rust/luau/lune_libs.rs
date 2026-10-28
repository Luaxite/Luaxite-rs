use lune_utils::process::ProcessJitEnablement;
use mlua::{ErrorContext, Lua, Table, Value};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt};



pub const MAX_BYTES: usize = 64 * 1024 * 1024;


pub fn too_big(what: &str) -> mlua::Error {
    mlua::Error::runtime(format!("{what} exceeds {} MiB", MAX_BYTES >> 20))
}


pub async fn read_capped_to<R: AsyncRead + Unpin>(
    r: &mut R,
    max: usize,
) -> std::io::Result<Option<Vec<u8>>> {
    let mut buf = Vec::new();
    
    r.take(max as u64 + 1).read_to_end(&mut buf).await?;
    Ok((buf.len() <= max).then_some(buf))
}


pub async fn read_capped<R: AsyncRead + Unpin>(r: &mut R) -> std::io::Result<Option<Vec<u8>>> {
    read_capped_to(r, MAX_BYTES).await
}


const MAX_TIMEOUT_SECS: f64 = u32::MAX as f64;



pub fn timeout_from_secs(func: &str, secs: Option<f64>) -> mlua::Result<Option<Duration>> {
    let Some(secs) = secs else { return Ok(None) };
    if secs.is_nan() || secs <= 0.0 {
        return Err(mlua::Error::runtime(format!(
            "{func}: options.timeout must be a positive number of seconds"
        )));
    }
    Duration::try_from_secs_f64(secs.min(MAX_TIMEOUT_SECS))
        .map(Some)
        .map_err(|e| mlua::Error::runtime(format!("{func}: invalid options.timeout ({e})")))
}


pub const DEFAULT_EXEC_TIMEOUT_SECS: f64 = 600.0;



pub const DEFAULT_REQUEST_TIMEOUT_SECS: f64 = 120.0;



pub fn timeout_with_default(
    func: &str,
    secs: Option<f64>,
    default: f64,
) -> mlua::Result<Option<Duration>> {
    match secs {
        None => timeout_from_secs(func, Some(default)),
        Some(secs) if secs == 0.0 => Ok(None),
        Some(secs) => timeout_from_secs(func, Some(secs)),
    }
}

const UNSUPPORTED: &[(&str, &str)] = &[(
    "roblox",
    "it is built on Lune's task scheduler, which luaxite does not run",
)];

pub fn require(lua: &Lua, loaded: &Table, name: &str) -> mlua::Result<Value> {
    let lib = name
        .strip_prefix("@lune/")
        .unwrap_or(name)
        .trim()
        .to_ascii_lowercase();
    let key = format!("@lune/{lib}");
    let hit: Value = loaded.get(key.as_str())?;
    if !hit.is_nil() {
        return Ok(hit);
    }
    if let Some((_, why)) = UNSUPPORTED.iter().find(|(n, _)| *n == lib) {
        return Err(mlua::Error::runtime(format!(
            "module '@lune/{lib}' is not supported by luaxite: {why}"
        )));
    }
    let lua = lua.clone();
    let module: mlua::Result<Table> = match lib.as_str() {
        "datetime" => lune_std_datetime::module(lua),
        "fs" => lune_std_fs::module(lua),
        "luau" => {
            lua.set_app_data(ProcessJitEnablement::new(false));
            lune_std_luau::module(lua)
        }
        "net" => super::lune_net::module(lua),
        "process" => super::lune_process::module(lua),
        "regex" => lune_std_regex::module(lua),
        "serde" => lune_std_serde::module(lua),
        "stdio" => super::lune_stdio::module(lua),
        "task" => super::lune_task::module(lua),
        _ => {
            return Err(mlua::Error::runtime(format!(
                "module '{name}' not found: there is no Lune module '{lib}' (available: {})",
                available()
            )));
        }
    };
    let value = Value::Table(
        module.map_err(|e| e.context(format!("failed to create Lune module '@lune/{lib}'")))?,
    );
    loaded.set(key.as_str(), value.clone())?;
    Ok(value)
}

fn available() -> &'static str {
    "datetime, fs, luau, net, process, regex, serde, stdio, task"
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block_on<F: std::future::Future>(f: F) -> F::Output {
        tokio::runtime::Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(f)
    }

    #[test]
    fn read_capped_to_stops_one_byte_past_the_cap() {
        let mut exact: &[u8] = b"abcd";
        assert_eq!(
            block_on(read_capped_to(&mut exact, 4)).unwrap(),
            Some(b"abcd".to_vec())
        );
        let mut over: &[u8] = b"abcde";
        assert_eq!(block_on(read_capped_to(&mut over, 4)).unwrap(), None);
        let mut empty: &[u8] = b"";
        assert_eq!(
            block_on(read_capped_to(&mut empty, 0)).unwrap(),
            Some(Vec::new())
        );
        
        let mut endless = tokio::io::repeat(7);
        assert_eq!(block_on(read_capped_to(&mut endless, 1000)).unwrap(), None);
    }

    #[test]
    fn timeout_from_secs_validates() {
        assert_eq!(timeout_from_secs("net.request", None).unwrap(), None);
        assert_eq!(
            timeout_from_secs("net.request", Some(2.5)).unwrap(),
            Some(Duration::from_millis(2500))
        );
        
        assert_eq!(
            timeout_from_secs("net.request", Some(f64::INFINITY)).unwrap(),
            Some(Duration::from_secs(u64::from(u32::MAX)))
        );
        for bad in [0.0, -1.0, f64::NAN, f64::NEG_INFINITY] {
            assert_eq!(
                timeout_from_secs("process.exec", Some(bad))
                    .unwrap_err()
                    .to_string(),
                "runtime error: process.exec: options.timeout must be a positive number of seconds"
            );
        }
    }

    #[test]
    fn timeout_with_default_applies_the_default_and_zero_disables() {
        
        assert_eq!(
            timeout_with_default("process.exec", None, 7.5).unwrap(),
            Some(Duration::from_millis(7500))
        );
        assert_eq!(
            timeout_with_default("process.exec", None, DEFAULT_EXEC_TIMEOUT_SECS).unwrap(),
            Some(Duration::from_secs(600))
        );
        assert_eq!(
            timeout_with_default("net.request", None, DEFAULT_REQUEST_TIMEOUT_SECS).unwrap(),
            Some(Duration::from_secs(120))
        );
        
        assert_eq!(
            timeout_with_default("net.request", Some(0.0), 120.0).unwrap(),
            None
        );
        assert_eq!(
            timeout_with_default("net.request", Some(-0.0), 120.0).unwrap(),
            None
        );
        
        assert_eq!(
            timeout_with_default("net.request", Some(2.5), 120.0).unwrap(),
            Some(Duration::from_millis(2500))
        );
        assert_eq!(
            timeout_with_default("net.request", Some(1000.0), 120.0).unwrap(),
            Some(Duration::from_secs(1000))
        );
        
        for big in [1e300, f64::INFINITY] {
            assert_eq!(
                timeout_with_default("net.request", Some(big), 120.0).unwrap(),
                Some(Duration::from_secs(u64::from(u32::MAX)))
            );
        }
        
        for bad in [-1.0, -0.001, f64::NAN, f64::NEG_INFINITY] {
            assert_eq!(
                timeout_with_default("process.exec", Some(bad), 600.0)
                    .unwrap_err()
                    .to_string(),
                timeout_from_secs("process.exec", Some(bad))
                    .unwrap_err()
                    .to_string()
            );
            assert_eq!(
                timeout_with_default("process.exec", Some(bad), 600.0)
                    .unwrap_err()
                    .to_string(),
                "runtime error: process.exec: options.timeout must be a positive number of seconds"
            );
        }
    }

    #[test]
    fn default_timeouts_are_the_documented_values() {
        assert_eq!(DEFAULT_EXEC_TIMEOUT_SECS, 600.0);
        assert_eq!(DEFAULT_REQUEST_TIMEOUT_SECS, 120.0);
    }

    #[test]
    fn too_big_names_the_limit() {
        assert_eq!(
            too_big("net.request: response body").to_string(),
            "runtime error: net.request: response body exceeds 64 MiB"
        );
    }
}
