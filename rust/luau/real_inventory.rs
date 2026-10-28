use azalea::inventory::operations::{
    ClickOperation, QuickCraftClick, QuickCraftKind, QuickCraftStatus,
};

use std::panic::{AssertUnwindSafe, catch_unwind};

use azalea::container::ContainerHandleRef;

use super::convert::{Held, LSlots, LuaContainer, lua_err};

impl Held {
    
    
    
    
    
    
    
    
    
    
    
    pub(super) fn release(self) {
        let outcome = catch_unwind(AssertUnwindSafe(move || {
            let alive = {
                let handle: &ContainerHandleRef = &self;
                handle.menu().is_ok()
            };
            match self {
                Held::Owned(handle) if alive => drop(handle),
                Held::Owned(handle) => std::mem::forget(handle),
                Held::Borrowed(handle) => {
                    if alive {
                        handle.close();
                    }
                }
            }
        }));
        if outcome.is_err() {
            eprintln!(
                "[luaxite] warning: closing a container panicked (the bot's world is probably gone); ignored"
            );
        }
    }
}



impl Drop for LuaContainer {
    fn drop(&mut self) {
        if let Some(held @ Held::Owned(_)) = self.handle.take() {
            held.release();
        }
    }
}

#[mlua::userdata_impl]
impl LuaContainer {
    
    
    fn quick_craft(&self, kind: String, slots: Vec<usize>) -> mlua::Result<()> {
        let kind = match kind.as_str() {
            "left" => QuickCraftKind::Left,
            "right" => QuickCraftKind::Right,
            "middle" => QuickCraftKind::Middle,
            other => {
                return Err(lua_err(format!(
                    "quick_craft kind must be \"left\", \"right\" or \"middle\", got \"{other}\""
                )));
            }
        };
        if slots.is_empty() {
            return Err(lua_err("quick_craft needs at least one slot"));
        }
        let handle = self.open(None)?;
        for slot in &slots {
            self.open(Some(*slot))?;
        }
        handle.click(ClickOperation::QuickCraft(QuickCraftClick {
            kind: kind.clone(),
            status: QuickCraftStatus::Start,
        }));
        for slot in slots {
            handle.click(ClickOperation::QuickCraft(QuickCraftClick {
                kind: kind.clone(),
                status: QuickCraftStatus::Add { slot: slot as u16 },
            }));
        }
        handle.click(ClickOperation::QuickCraft(QuickCraftClick {
            kind,
            status: QuickCraftStatus::End,
        }));
        Ok(())
    }

    
    
    #[lua(infallible)]
    fn id(&self) -> Option<i32> {
        self.handle.as_ref().map(|handle| handle.id())
    }

    
    
    #[lua(infallible)]
    fn title(&self) -> Option<String> {
        self.handle.as_ref()?.title().map(|title| title.to_string())
    }

    
    
    #[lua(infallible)]
    fn contents(&self) -> Option<LSlots> {
        self.handle.as_ref()?.contents().map(LSlots)
    }
}
