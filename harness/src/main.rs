mod luau;

use std::{path::Path, sync::Arc, time::Duration};

use azalea::{
    ChatPacket, Client, Event, FormattedText, MinecraftEntityId, protocol::packets::game::ClientboundPlayerCombatKill,
};
use tokio::task::JoinHandle;

type Task = JoinHandle<anyhow::Result<()>>;

/// `tokio::spawn` needs Send + 'static: the same bound azalea puts on `set_handler` futures. azalea runs every
/// event in its own task, so a script parked in `bot:wait_for(..)` never blocks the events that wake it.
fn fire(rt: &Arc<luau::Runtime>, bot: &Client, ev: Event) -> Task {
    let (rt, bot) = (rt.clone(), bot.clone());
    tokio::spawn(async move { rt.handle(bot, ev).await })
}

/// Wait until `task` has parked in `bot:wait_for(event)` (or ended, e.g. after a script error).
async fn parked(rt: &luau::Runtime, event: &str, task: &Task) {
    for _ in 0..500 {
        if rt.waiting(event) > 0 || task.is_finished() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    eprintln!("[harness] nothing parked in wait_for(\"{event}\")");
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let rt = Arc::new(luau::Runtime::new(Path::new("test.luau"))?);
    let bot = Client::fake();
    // The script body ends in `bot:wait_for("keep_alive")`, so Init stays running until that event.
    let init = fire(&rt, &bot, Event::Init);
    parked(&rt, "keep_alive", &init).await;
    for ev in [Event::Login, Event::Chat(ChatPacket("!pos".into())), Event::KeepAlive(5)] {
        fire(&rt, &bot, ev).await??;
    }
    init.await??;
    // A `death` handler that parks in `wait_for("tick")`; the payload is the combat-kill packet.
    let kill = ClientboundPlayerCombatKill { player_id: MinecraftEntityId(7), message: FormattedText("you died".into()) };
    let death = fire(&rt, &bot, Event::Death(Some(Arc::new(kill))));
    parked(&rt, "tick", &death).await;
    fire(&rt, &bot, Event::Tick).await??;
    death.await??;
    fire(&rt, &bot, Event::Death(None)).await??;
    Ok(())
}
