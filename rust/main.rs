// The Luau glue (azalea bindings, Lune libs, #[bind] registration) lives in rust_binds/, so this folder holds only what you edit.
#[path = "../rust_binds/luau/mod.rs"]
mod luau;

// `#[bind]` for fns in this file (a bare `#[bind]`, as the scanner accepts, needs the import; `#[zenpel_bind::bind]` does not).
#[allow(unused_imports)]
use zenpel_bind::bind;
use std::{path::PathBuf, sync::Arc};

const USAGE: &str = r#"usage: zenpel [<arg>...]
       zenpel path <script.luau>... [<arg>...]

  <arg>...             every argument is passed, unchanged and in order, to the scripts as `process.args`
                       (`require("@lune/process")`): `zenpel debug=true`, `zenpel debug true`, `zenpel --verbose`.
  path <script.luau>...  run these scripts instead of the embedded main (src/main.luau), each in its own Luau state, all
                       in one process. After `path`, every argument ending in .luau or .lua is a script; the others
                       are still passed to `process.args`.
  -h, --help           print this and exit (only as the first argument; anywhere else it is passed on like any other).

With no `path` the script embedded at build time (src/main.luau) runs. A script can `require("./other")` files relative to
itself (see README). A script makes its bots itself (`azalea.join`, `azalea.swarm`). Like a Roblox script, it ending does
not stop its handlers: the process runs until every bot / swarm the scripts started is gone, or a script calls
`process.exit(code)`."#;

/// What the command line asks for.
#[derive(Debug, Default, PartialEq, Eq)]
struct Cli {
    /// Scripts named after `path`. Empty: the embedded main runs.
    scripts: Vec<PathBuf>,
    /// Everything else, for `process.args`.
    args: Vec<String>,
}

fn is_script(arg: &str) -> bool {
    arg.ends_with(".luau") || arg.ends_with(".lua")
}

/// `zenpel [<arg>...]` / `zenpel path <script>... [<arg>...]`. `Ok(None)` = help was asked for.
fn parse_cli(argv: impl IntoIterator<Item = String>) -> anyhow::Result<Option<Cli>> {
    let mut cli = Cli::default();
    let mut in_path = false;
    let mut seen_path = false;
    for (i, a) in argv.into_iter().enumerate() {
        if i == 0 && (a == "-h" || a == "--help") {
            return Ok(None);
        }
        if !seen_path && a == "path" {
            seen_path = true;
            in_path = true;
        } else if in_path && is_script(&a) {
            cli.scripts.push(PathBuf::from(a));
        } else {
            cli.args.push(a);
        }
    }
    if seen_path && cli.scripts.is_empty() {
        anyhow::bail!("`path` needs at least one .luau script\n{USAGE}");
    }
    Ok(Some(cli))
}

fn parse_args() -> anyhow::Result<Cli> {
    // Not `std::env::args`: it panics on an argument that is not valid unicode.
    let argv = std::env::args_os()
        .skip(1)
        .map(|a| a.to_string_lossy().into_owned());
    match parse_cli(argv)? {
        Some(cli) => Ok(cli),
        None => {
            println!("{USAGE}");
            std::process::exit(0);
        }
    }
}

fn install_signal_handler() -> anyhow::Result<()> {
    #[cfg(unix)]
    {
        use tokio::signal::unix::{SignalKind, signal};
        let mut int = signal(SignalKind::interrupt())?;
        let mut term = signal(SignalKind::terminate())?;
        tokio::spawn(async move {
            let code = tokio::select! {
                _ = int.recv() => 130,
                _ = term.recv() => 143,
            };
            luau::Runtime::kill_children();
            std::process::exit(code);
        });
    }
    #[cfg(not(unix))]
    tokio::spawn(async {
        if tokio::signal::ctrl_c().await.is_ok() {
            luau::Runtime::kill_children();
            std::process::exit(130);
        }
    });
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let Cli { scripts, args } = parse_args()?;
    luau::set_process_args(args);
    install_signal_handler()?;
    let mut runtimes = Vec::new();
    for script in &scripts {
        runtimes.push(Arc::new(luau::Runtime::new(script)?));
    }
    if runtimes.is_empty() {
        runtimes.push(Arc::new(luau::Runtime::embedded()?));
    }

    let local = tokio::task::LocalSet::new();
    let ok = local.run_until(run(runtimes)).await?;
    luau::Runtime::kill_children();
    std::process::exit(if ok { 0 } else { 1 })
}

#[cfg(feature = "real")]
async fn run(runtimes: Vec<Arc<luau::Runtime>>) -> anyhow::Result<bool> {
    let mut tasks: Vec<tokio::task::JoinHandle<anyhow::Result<()>>> = Vec::new();
    for runtime in runtimes {
        tasks.push(tokio::task::spawn_local(async move {
            runtime.run_standalone().await
        }));
    }
    let mut ok = true;
    for task in tasks {
        match task.await {
            Ok(Ok(())) => {}
            Ok(Err(e)) => {
                eprintln!("[luau] {e}");
                ok = false;
            }
            Err(e) => {
                eprintln!("[luau] a script task failed: {e}");
                ok = false;
            }
        }
    }
    Ok(ok)
}

#[cfg(not(feature = "real"))]
async fn run(_runtimes: Vec<Arc<luau::Runtime>>) -> anyhow::Result<bool> {
    anyhow::bail!(
        "scripts start their bots with `azalea.join`, which needs the `real` cargo feature (a default one)"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cli(args: &[&str]) -> Cli {
        parse_cli(args.iter().map(|a| a.to_string()))
            .unwrap()
            .unwrap()
    }

    fn strings(v: &[&str]) -> Vec<String> {
        v.iter().map(|a| a.to_string()).collect()
    }

    #[test]
    fn no_args_runs_the_embedded_main() {
        assert_eq!(cli(&[]), Cli::default());
    }

    #[test]
    fn every_arg_goes_to_process_args() {
        let c = cli(&["debug=true", "debug", "true", "--verbose", "-x", "a.luau"]);
        assert!(c.scripts.is_empty());
        assert_eq!(c.args, strings(&["debug=true", "debug", "true", "--verbose", "-x", "a.luau"]));
    }

    #[test]
    fn path_runs_the_scripts_instead_of_main() {
        let c = cli(&["path", "path.luau", "path1.luau"]);
        assert_eq!(c.scripts, vec![PathBuf::from("path.luau"), PathBuf::from("path1.luau")]);
        assert!(c.args.is_empty());
    }

    #[test]
    fn path_mixes_with_args() {
        let c = cli(&["debug=true", "path", "a.luau", "debug", "true", "b.lua"]);
        assert_eq!(c.scripts, vec![PathBuf::from("a.luau"), PathBuf::from("b.lua")]);
        assert_eq!(c.args, strings(&["debug=true", "debug", "true"]));
    }

    #[test]
    fn only_the_first_path_is_a_keyword() {
        let c = cli(&["path", "a.luau", "path"]);
        assert_eq!(c.scripts, vec![PathBuf::from("a.luau")]);
        assert_eq!(c.args, strings(&["path"]));
    }

    #[test]
    fn path_without_a_script_is_an_error() {
        assert!(parse_cli(strings(&["path"])).is_err());
        assert!(parse_cli(strings(&["path", "debug=true"])).is_err());
    }

    #[test]
    fn help_only_as_the_first_arg() {
        assert!(parse_cli(strings(&["--help"])).unwrap().is_none());
        assert!(parse_cli(strings(&["-h", "x"])).unwrap().is_none());
        assert_eq!(cli(&["debug", "--help"]).args, strings(&["debug", "--help"]));
    }
}
