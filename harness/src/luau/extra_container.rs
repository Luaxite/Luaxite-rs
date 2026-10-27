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
    // luau[Container]: --- Every slot of the container followed by the bot's inventory, in slot order (an empty slot is `false`). nil once closed.
    // luau[Container]: function slots(self): { Item | false }?
    #[lua(infallible)]
    fn slots(&self) -> Option<LSlots> {
        self.handle.as_ref()?.slots().map(LSlots)
    }

    // luau[Container]: --- Close the container. Closing twice does nothing.
    // luau[Container]: function close(self): ()
    #[lua(infallible)]
    fn close(&mut self) {
        if let Some(held) = self.handle.take() {
            held.release();
        }
    }
}

#[mlua::userdata_impl]
impl LuaContainer {
    // luau[Container]: --- Left-click a slot: pick up or put down the whole stack.
    // luau[Container]: function left_click(self, slot: number): ()
    fn left_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.left_click(slot);
        Ok(())
    }

    // luau[Container]: --- Right-click a slot: pick up half the stack or put down one item.
    // luau[Container]: function right_click(self, slot: number): ()
    fn right_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.right_click(slot);
        Ok(())
    }

    // luau[Container]: --- Shift-click a slot: move its stack to the other part of the menu.
    // luau[Container]: function shift_click(self, slot: number): ()
    fn shift_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.shift_click(slot);
        Ok(())
    }

    // luau[Container]: --- Middle-click a slot: copy its stack onto the cursor. Only works in creative mode.
    // luau[Container]: function middle_click(self, slot: number): ()
    fn middle_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?
            .click(CloneClick { slot: slot as u16 });
        Ok(())
    }

    // luau[Container]: --- Double-click a slot: gather matching items onto the cursor stack.
    // luau[Container]: function double_click(self, slot: number): ()
    fn double_click(&self, slot: usize) -> mlua::Result<()> {
        self.open(Some(slot))?.click(PickupAllClick {
            slot: slot as u16,
            reversed: false,
        });
        Ok(())
    }

    // luau[Container]: --- Swap a slot with a hotbar slot (`target` 0-8) or the offhand (`target` 40), like pressing a number key or F.
    // luau[Container]: function swap(self, slot: number, target: number): ()
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

    // luau[Container]: --- Drop the item in a slot (the Q key): one item, or the whole stack with `whole_stack`.
    // luau[Container]: function throw(self, slot: number, whole_stack: boolean?): ()
    fn throw(&self, slot: usize, whole_stack: Option<LBool>) -> mlua::Result<()> {
        self.open(Some(slot))?
            .click(if whole_stack.is_some_and(|b| b.0) {
                ThrowClick::All { slot: slot as u16 }
            } else {
                ThrowClick::Single { slot: slot as u16 }
            });
        Ok(())
    }

    // luau[Container]: --- Click outside the menu to drop the item on the cursor: one item, or the whole stack with `whole_stack`.
    // luau[Container]: function drop_cursor(self, whole_stack: boolean?): ()
    fn drop_cursor(&self, whole_stack: Option<LBool>) -> mlua::Result<()> {
        self.open(None)?.click(if whole_stack.is_some_and(|b| b.0) {
            PickupClick::Left { slot: None }
        } else {
            PickupClick::Right { slot: None }
        });
        Ok(())
    }
}
