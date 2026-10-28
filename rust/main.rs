mod luau;

use std::{path::PathBuf, sync::Arc};

const USAGE: &str = "usage: luaxite [<script.luau>...]

  <script.luau>...   scripts to run, each in its own Luau state, all in one process.
                     None: the script embedded at build time (src/main.luau) runs.
  -h, --help         print this and exit

A script makes its bots itself (`azalea.join`, `azalea.swarm`). Like a Roblox script, it ending does not stop its handlers: the process runs
until every bot / swarm the scripts started is gone, or a script calls `process.exit(code)`.";

fn parse_args() -> anyhow::Result<Vec<PathBuf>> {
    let mut scripts = Vec::new();
    for a in std::env::args().skip(1) {
        match a.as_str() {
            "-h" | "--help" => {
                println!("{USAGE}");
                std::process::exit(0);
            }
            _ if a.starts_with('-') => anyhow::bail!("unknown option `{a}`\n{USAGE}"),
            _ => scripts.push(PathBuf::from(a)),
        }
    }
    Ok(scripts)
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
    let scripts = parse_args()?;
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
