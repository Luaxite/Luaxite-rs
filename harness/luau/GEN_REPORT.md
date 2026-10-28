# Luau bridge report

Source: `fake @ 61bcab3d72` (1 files)
Front end: rustdoc JSON (rustc 1.97.0 (2d8144b78 2026-07-07), format_version 57)

- **`Client` -> `LuaClient` / `Bot`:** 47 methods generated (10 async/yielding), 9 skipped
- **`EntityRef` -> `LuaEntityRef` / `Entity`:** 6 methods generated (0 async/yielding), 2 skipped
- **azalea -> Luau:** 9 events (`bot:on(...)`)
- **Types:** 14 generated conversions, 8 built-in

## Generated methods

### Client

`attack`, `attributes`, `broken`, `chat`, `direction`, `entity`, `entity_by_minecraft_id`, `entity_by_uuid`, `entity_id_by_minecraft_id`, `entity_id_by_uuid`, `entity_interact`, `entity_ref_for`, `experience`, `get_held_item`, `get_inventory`, `goto`, `goto_with_opts`, `goto_with_opts_xz`, `goto_xz`, `health`, `hit_result`, `look_at`, `menu`, `mine`, `mine_with_auto_tool`, `minecraft_id`, `nearby_players`, `open_container_at`, `open_container_at_with_timeout_ticks`, `open_inventory`, `physics`, `position`, `profile`, `set_direction`, `start_goto`, `start_goto_with_opts`, `start_goto_with_opts_xz`, `start_goto_xz`, `stop_pathfinding`, `tab_names`, `test_all_entities`, `test_count_boxed`, `test_count_entities`, `wait_for_container_open`, `wait_ticks`, `walk`, `write_chat_packet`

### EntityRef

`attack`, `attributes`, `health`, `minecraft_id`, `physics`, `position`

## Hand-written methods (rust_binds/luau/extra_*.rs)

- `Bot`: `block_at`, `best_tool_in_hotbar_for_block`, `best_tool_for`, `held_item`, `inventory`, `goto_reach`, `set_client_information`, `nearest_player`, `nearby_entities`, `account`, `tab_list`
- `Container`: `slots`, `close`, `left_click`, `right_click`, `shift_click`, `middle_click`, `double_click`, `swap`, `throw`, `drop_cursor`
- `Entity`: `distance_to`

## Events

- `init` ()
- `login` ()
- `chat` (packet: ChatPacket)
- `tick` ()
- `add_player` (player: PlayerInfo)
- `keep_alive` (id: number)
- `disconnect` (reason: string?)
- `connection_failed` (error: string)
- `death` (info: ClientboundPlayerCombatKill?)
- `update` () - hand-fired: Fires on every ECS update (at least once per game tick, usually faster). Only handlers that finish quickly should use it.

## Resolved public paths

- `AttributeInstance` -> `azalea::AttributeInstance`
- `Attributes` -> `azalea::Attributes`
- `BestToolResult` -> `azalea::auto_tool::BestToolResult`
- `BlockHitResult` -> `azalea::core::hit_result::BlockHitResult`
- `BlockPosGoal` -> `azalea::pathfinder::goals::BlockPosGoal`
- `ChatPacket` -> `azalea::ChatPacket`
- `ChatVisibility` -> `azalea::protocol::common::client_information::ChatVisibility`
- `ClientInformation` -> `azalea::ClientInformation`
- `ClientboundPlayerCombatKill` -> `azalea::protocol::packets::game::ClientboundPlayerCombatKill`
- `Direction` -> `azalea::core::hit_result::Direction`
- `EntityHitResult` -> `azalea::core::hit_result::EntityHitResult`
- `Experience` -> `azalea::Experience`
- `GameProfile` -> `azalea::GameProfile`
- `HitResult` -> `azalea::core::hit_result::HitResult`
- `HumanoidArm` -> `azalea::entity::HumanoidArm`
- `LookDirection` -> `azalea::LookDirection`
- `ModelCustomization` -> `azalea::protocol::common::client_information::ModelCustomization`
- `ParticleStatus` -> `azalea::protocol::common::client_information::ParticleStatus`
- `Physics` -> `azalea::Physics`
- `PlayerInfo` -> `azalea::PlayerInfo`
- `WalkDirection` -> `azalea::WalkDirection`
- `XZGoal` -> `azalea::pathfinder::goals::XZGoal`

## Goals not exposed

- `ReachBlockPosGoal`: private fields; covered by `bot:goto_reach(pos, distance?)` in rust_binds/luau/extra_misc.rs

## Skipped methods

### Client

#### generic method (3)

- `pub fn component<T: FakeComponent>(&self) -> Result<T, MissingComponentError>`
- `pub fn nearest_entities<F>(&self) -> AzaleaResult<Box<[EntityRef]>>`
- `pub fn nearest_entities_by<Q: FakeQuery, F>(&self, predicate: impl Fn(Q::Item<'_>) -> bool) -> AzaleaResult<Box<[EntityRef]>>`

#### `tab_list` is hand-written (extra_*.rs) or generated elsewhere (1)

- `pub fn tab_list(&self) -> AzaleaResult<std::collections::HashMap<Uuid, PlayerInfo>>`

#### generic type `RwLock<World>` (1)

- `pub fn world(&self) -> AzaleaResult<Arc<RwLock<world::World>>>`

#### no `&self` receiver (1)

- `pub fn fake() -> Self`

#### parameter `client_information`: not convertible (1)

- `pub fn set_client_information(&self, client_information: ClientInformation) -> AzaleaResult<()>`

#### tuple struct `Account` (1)

- `pub fn account(&self) -> Account`

#### tuple struct `BlockState` (1)

- `pub fn best_tool_in_hotbar_for_block(&self, block: block::BlockState) -> AzaleaResult<auto_tool::BestToolResult>`

### EntityRef

#### denied: the raw ECS id is internal; scripts hold `Entity` handles instead (1)

- `pub fn id(&self) -> Entity`

#### no `&self` receiver (1)

- `pub fn new(client: Client, entity: Entity) -> Self`
