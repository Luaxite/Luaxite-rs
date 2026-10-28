use azalea::entity::inventory::Inventory;

use super::{
    convert::{LItem, LSlots, lua_err},
    gen_client::LuaClient,
};

#[mlua::userdata_impl]
impl LuaClient {
    
    
    fn held_item(&self) -> mlua::Result<LItem> {
        Ok(LItem(self.client.get_held_item().map_err(lua_err)?))
    }

    
    
    fn inventory(&self) -> mlua::Result<LSlots> {
        let inv = self.client.component::<Inventory>().map_err(lua_err)?;
        Ok(LSlots(inv.inventory_menu.slots()))
    }
}
