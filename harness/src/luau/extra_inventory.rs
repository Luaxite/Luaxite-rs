use azalea::entity::inventory::Inventory;

use super::{
    convert::{LItem, LSlots, lua_err},
    gen_client::LuaClient,
};

#[mlua::userdata_impl]
impl LuaClient {
    // luau[Bot]: --- The item in the bot's main hand, or nil when the hand is empty.
    // luau[Bot]: function held_item(self): Item?
    fn held_item(&self) -> mlua::Result<LItem> {
        Ok(LItem(self.client.get_held_item().map_err(lua_err)?))
    }

    // luau[Bot]: --- The bot's own inventory (not an open chest) in slot order: crafting, armor, main inventory, hotbar, offhand. An empty slot is `false`.
    // luau[Bot]: function inventory(self): { Item | false }
    fn inventory(&self) -> mlua::Result<LSlots> {
        let inv = self.client.component::<Inventory>().map_err(lua_err)?;
        Ok(LSlots(inv.inventory_menu.slots()))
    }
}
