mod luau;

use std::{path::Path, sync::Arc, time::Duration};

use azalea::{
    ChatPacket, Client, Event, FormattedText, MinecraftEntityId, protocol::packets::game::ClientboundPlayerCombatKill,
};
use tokio::task::JoinHandle;

type Task = JoinHandle<anyhow::Result<()>>;



fn fire(rt: &Arc<luau::Runtime>, bot: &Client, ev: Event) -> Task {
    let (rt, bot) = (rt.clone(), bot.clone());
    tokio::spawn(async move { rt.handle(bot, ev).await })
}


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
    
    let init = fire(&rt, &bot, Event::Init);
    parked(&rt, "keep_alive", &init).await;
    for ev in [Event::Login, Event::Chat(ChatPacket("!pos".into())), Event::KeepAlive(5)] {
        fire(&rt, &bot, ev).await??;
    }
    init.await??;
    
    let kill = ClientboundPlayerCombatKill { player_id: MinecraftEntityId(7), message: FormattedText("you died".into()) };
    let death = fire(&rt, &bot, Event::Death(Some(Arc::new(kill))));
    parked(&rt, "tick", &death).await;
    fire(&rt, &bot, Event::Tick).await??;
    death.await??;
    fire(&rt, &bot, Event::Death(None)).await??;
    Ok(())
}
