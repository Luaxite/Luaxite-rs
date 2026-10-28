use azalea::{
    container::ContainerHandleRef,
    inventory::operations::{CloneClick, PickupAllClick, PickupClick, SwapClick, ThrowClick},
};

use super::convert::{LBool, LSlots, LuaContainer, lua_err};

impl LuaContainer {
    pub(super) fn open(&self, slot: Option<usize>) -> mlua::Result<&ContainerHandleRef> {
        let closed = || lua_err("container is closed");
        let handle: &ContainerHandleRef = self.handle.as_deref().ok_or_else(closed)?;
        let len = handle.slots().ok_or_else(closed)?.len();
        match slot {
            Some(slot) if slot >= len => Err(lua_err(format!(
                "slot {slot} out of range (the container has {len} slots, numbered from 0)"
            ))),
            _ => Ok(handle),
        }
    }
}

#[mlua::userdata_impl]
impl LuaContainer {
    
    
    #[lua(infallible)]
    fn slots(&self) -> Option<LSlots> {
        self.handle.as_ref()?.slots().map(LSlots)
    }

    
    
    #[lua(infallible)]
    fn close(&mut self) {
        if let Some(held) = self.handle.take() {
            held.release();
        }
    }
}

#[mlua::userdata_impl]
impl LuaContainer {
    
    
    fn left_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.left_click(slot);
        Ok(())
    }

    
    
    fn right_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.right_click(slot);
        Ok(())
    }

    
    
    fn shift_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.shift_click(slot);
        Ok(())
    }

    
    
    fn middle_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?
            .click(CloneClick { slot: slot as u16 });
        Ok(())
    }

    
    
    fn double_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.click(PickupAllClick {
            slot: slot as u16,
            reversed: false,
        });
        Ok(())
    }

    
    
    fn swap(&self, slot: usize, target: u8) -> mlua::Result<()> {
        if target > 8 && target != 40 {
            return Err(lua_err(format!(
                "swap target {target} must be a hotbar slot 0-8 or 40 (offhand)"
            )));
        }
        self.open(Some(slot))?.click(SwapClick {
            source_slot: slot as u16,
            target_slot: target,
        });
        Ok(())
    }

    
    
    fn throw(&self, slot: usize, whole_stack: Option<LBool>) -> mlua::Result<()> {
        self.open(Some(slot))?
            .click(if whole_stack.is_some_and(|b| b.0) {
                ThrowClick::All { slot: slot as u16 }
            } else {
                ThrowClick::Single { slot: slot as u16 }
            });
        Ok(())
    }

    
    
    fn drop_cursor(&self, whole_stack: Option<LBool>) -> mlua::Result<()> {
        self.open(None)?.click(if whole_stack.is_some_and(|b| b.0) {
            PickupClick::Left { slot: None }
        } else {
            PickupClick::Right { slot: None }
        });
        Ok(())
    }
}
