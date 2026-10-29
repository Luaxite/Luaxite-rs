// PATCHED (luaxite): upstream asks the Android Java VM for the DNS servers through
// `ndk_context::android_context()`, which *panics* ("android context was not initialized")
// in a plain native executable such as one run from Termux (there is no JavaVM / Activity).
// This version never touches JNI: it reads the first `resolv.conf` it can find and, when none
// has a usable `nameserver`, returns an error so callers can fall back to a built-in resolver
// config (azalea falls back to Google DNS).

use std::fs;
use std::io;
use std::net::IpAddr;
use std::path::PathBuf;
use std::str::FromStr;

use tracing::{trace, warn};

use crate::config::{NameServerConfig, ResolverConfig, ResolverOpts};
use crate::net::NetError;

/// Places a `resolv.conf` can live in a native Android process, most specific first.
fn candidate_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    // Termux keeps it under its prefix (`$PREFIX/etc/resolv.conf`).
    if let Some(prefix) = std::env::var_os("PREFIX") {
        paths.push(PathBuf::from(prefix).join("etc/resolv.conf"));
    }
    paths.push(PathBuf::from("/data/data/com.termux/files/usr/etc/resolv.conf"));
    paths.push(PathBuf::from("/etc/resolv.conf"));
    paths.push(PathBuf::from("/system/etc/resolv.conf"));
    paths
}

/// Collects the `nameserver` entries of a `resolv.conf`. Comments, other directives and
/// addresses that do not parse (such as scoped IPv6 like `fe80::1%wlan0`) are skipped.
fn parse_nameservers(data: &str) -> Vec<IpAddr> {
    data.lines()
        .filter_map(|line| {
            let line = line.split(['#', ';']).next().unwrap_or("").trim();
            let mut parts = line.split_whitespace();
            if parts.next()? != "nameserver" {
                return None;
            }
            IpAddr::from_str(parts.next()?).ok()
        })
        .collect()
}

pub fn read_system_conf() -> Result<(ResolverConfig, ResolverOpts), NetError> {
    for path in candidate_paths() {
        let Ok(data) = fs::read(&path) else {
            continue;
        };
        let ips = parse_nameservers(&String::from_utf8_lossy(&data));
        if ips.is_empty() {
            continue;
        }
        trace!("Got DNS servers from {}: {:?}", path.display(), ips);
        let nameservers = ips
            .into_iter()
            .map(|ip| NameServerConfig::udp_and_tcp(ip))
            .collect::<Vec<_>>();
        return Ok((
            ResolverConfig::from_parts(None, vec![], nameservers),
            ResolverOpts::default(),
        ));
    }

    warn!("no usable resolv.conf found on Android");
    Err(io::Error::new(
        io::ErrorKind::NotFound,
        "no resolv.conf with a nameserver found on Android",
    )
    .into())
}

#[cfg(test)]
mod tests {
    use super::parse_nameservers;

    #[test]
    fn parses_nameservers() {
        let ips = parse_nameservers(
            "# comment\nnameserver 8.8.8.8\nnameserver 2001:4860:4860::8844 # v6\nsearch lan\nnameserver fe80::1%wlan0\nnameserver\n",
        );
        assert_eq!(ips.len(), 2);
        assert_eq!(ips[0].to_string(), "8.8.8.8");
        assert_eq!(ips[1].to_string(), "2001:4860:4860::8844");
    }
}
