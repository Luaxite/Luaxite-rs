//! Fake azalea: just enough surface (same shapes as the real one) to compile-check generated bindings.
#![allow(dead_code)]

use std::{fmt, str::FromStr, sync::Arc, time::Duration};

pub mod ecs {
    pub mod entity {
        #[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
        pub struct Entity(pub u32);
    }
}
pub use ecs::entity::Entity;

pub mod core {
    /// Real: `azalea::core::hit_result` (azalea_core::hit_result).
    pub mod hit_result {
        use crate::{BlockPos, Vec3};
        #[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
        pub enum Direction {
            #[default]
            Down,
            Up,
            North,
            South,
            West,
            East,
        }
        #[derive(Clone, Debug)]
        pub struct BlockHitResult {
            pub location: Vec3,
            pub miss: bool,
            pub direction: Direction,
            pub block_pos: BlockPos,
            pub inside: bool,
            pub world_border: bool,
        }
        #[derive(Clone, Debug)]
        pub struct EntityHitResult {
            pub location: Vec3,
            pub entity: crate::Entity,
        }
        #[derive(Clone, Debug)]
        pub enum HitResult {
            Block(BlockHitResult),
            Entity(EntityHitResult),
        }
    }
    pub mod entity_id {
        /// Minecraft's numeric entity id (real: azalea_core::entity_id).
        #[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
        pub struct MinecraftEntityId(pub i32);
    }
}
pub use core::entity_id::MinecraftEntityId;

pub mod position {
    #[derive(Clone, Copy, Debug, Default, PartialEq)]
    pub struct BlockPos {
        pub x: i32,
        pub y: i32,
        pub z: i32,
    }
    impl BlockPos {
        pub const fn new(x: i32, y: i32, z: i32) -> Self {
            Self { x, y, z }
        }
    }
    #[derive(Clone, Copy, Debug, Default, PartialEq)]
    pub struct Vec3 {
        pub x: f64,
        pub y: f64,
        pub z: f64,
    }
    impl Vec3 {
        pub const fn new(x: f64, y: f64, z: f64) -> Self {
            Self { x, y, z }
        }
    }
}
pub use position::{BlockPos, Vec3};

/// Real: `azalea::registry::builtin::EntityKind` (Copy + PartialEq + FromStr accepting "zombie" or "minecraft:zombie").
pub mod registry {
    pub mod builtin {
        use std::str::FromStr;
        #[derive(Clone, Copy, Debug, PartialEq, Eq)]
        pub enum EntityKind {
            Player,
            Zombie,
            Cow,
        }
        impl FromStr for EntityKind {
            type Err = ();
            fn from_str(s: &str) -> Result<Self, ()> {
                match s.strip_prefix("minecraft:").unwrap_or(s) {
                    "player" => Ok(Self::Player),
                    "zombie" => Ok(Self::Zombie),
                    "cow" => Ok(Self::Cow),
                    _ => Err(()),
                }
            }
        }

        /// Real: `azalea::registry::builtin::BlockKind`. `FromStr` accepts "stone" or "minecraft:stone";
        /// `to_str()` (and `Display`) give `minecraft:<id>`. The fake only knows a handful of blocks.
        #[derive(Clone, Copy, Debug, PartialEq, Eq)]
        pub enum BlockKind {
            Air,
            Stone,
            Dirt,
            GrassBlock,
            Water,
            Lava,
            Bedrock,
            OakLog,
            DiamondOre,
        }
        impl BlockKind {
            pub fn to_str(&self) -> &'static str {
                match self {
                    Self::Air => "minecraft:air",
                    Self::Stone => "minecraft:stone",
                    Self::Dirt => "minecraft:dirt",
                    Self::GrassBlock => "minecraft:grass_block",
                    Self::Water => "minecraft:water",
                    Self::Lava => "minecraft:lava",
                    Self::Bedrock => "minecraft:bedrock",
                    Self::OakLog => "minecraft:oak_log",
                    Self::DiamondOre => "minecraft:diamond_ore",
                }
            }
        }
        impl std::fmt::Display for BlockKind {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                write!(f, "{}", self.to_str())
            }
        }
        impl FromStr for BlockKind {
            type Err = ();
            fn from_str(s: &str) -> Result<Self, ()> {
                match s.strip_prefix("minecraft:").unwrap_or(s) {
                    "air" => Ok(Self::Air),
                    "stone" => Ok(Self::Stone),
                    "dirt" => Ok(Self::Dirt),
                    "grass_block" => Ok(Self::GrassBlock),
                    "water" => Ok(Self::Water),
                    "lava" => Ok(Self::Lava),
                    "bedrock" => Ok(Self::Bedrock),
                    "oak_log" => Ok(Self::OakLog),
                    "diamond_ore" => Ok(Self::DiamondOre),
                    _ => Err(()),
                }
            }
        }
    }
}

/// Real: `azalea::block` (azalea_block). Its `BlockState` is a state id (stone has one state, stairs many);
/// the fake just wraps the kind. `BlockState::from(kind)` is the default state, `BlockKind::from(state)` drops the state.
pub mod block {
    use crate::registry::builtin::BlockKind;
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub struct BlockState(BlockKind);
    impl From<BlockKind> for BlockState {
        fn from(kind: BlockKind) -> Self {
            BlockState(kind)
        }
    }
    impl From<BlockState> for BlockKind {
        fn from(state: BlockState) -> Self {
            state.0
        }
    }
}

/// Stand-in for `parking_lot::RwLock`, which `Client::world()` really returns inside an `Arc`: `read()` gives a
/// guard directly (no `Result`), which is how real code calls `world.read().get_block_state(..)`.
pub struct RwLock<T>(std::sync::RwLock<T>);
impl<T> RwLock<T> {
    pub fn new(value: T) -> Self {
        RwLock(std::sync::RwLock::new(value))
    }
    pub fn read(&self) -> std::sync::RwLockReadGuard<'_, T> {
        self.0.read().unwrap()
    }
}

/// Real: `azalea::world` (azalea_world).
pub mod world {
    use crate::{BlockPos, block::BlockState, registry::builtin::BlockKind};
    /// Real: `azalea_world::ChunkStorage` (a boxed `ChunkStorageTrait`, `Clone`). `ReachBlockPosGoal` takes its own copy.
    #[derive(Clone, Debug)]
    pub struct ChunkStorage;
    /// Real: `azalea_world::World`, whose `chunks` field is public.
    pub struct World {
        pub chunks: ChunkStorage,
    }
    impl World {
        pub fn new() -> Self {
            World { chunks: ChunkStorage }
        }
        /// Real: `Some(state)` for any loaded position, `None` outside the loaded world. The fake world: nothing
        /// below y=0, bedrock at 0, stone up to 62 (one diamond ore), dirt at 63 (one water block), air above.
        pub fn get_block_state(&self, pos: BlockPos) -> Option<BlockState> {
            let kind = match (pos.x, pos.y, pos.z) {
                (_, y, _) if y < 0 => return None,
                (5, 10, 5) => BlockKind::DiamondOre,
                (3, 63, 3) => BlockKind::Water,
                (_, 0, _) => BlockKind::Bedrock,
                (_, 1..=62, _) => BlockKind::Stone,
                (_, 63, _) => BlockKind::Dirt,
                _ => BlockKind::Air,
            };
            Some(kind.into())
        }
    }
}

/// Real: `azalea::auto_tool`.
pub mod auto_tool {
    #[derive(Debug)]
    pub struct BestToolResult {
        pub index: usize,
        pub percentage_per_tick: f32,
    }
}

/// Real: `azalea::inventory` (azalea_inventory, re-exported through azalea_client).
pub mod inventory {
    use std::fmt;
    /// Real: `azalea_registry::builtin::ItemKind`; `Display` gives `minecraft:<id>`.
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub struct ItemKind(pub &'static str);
    impl fmt::Display for ItemKind {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "minecraft:{}", self.0)
        }
    }
    #[derive(Clone, Debug, PartialEq)]
    pub struct ItemStackData {
        pub kind: ItemKind,
        pub count: i32,
    }
    #[derive(Clone, Debug, Default, PartialEq)]
    pub enum ItemStack {
        #[default]
        Empty,
        Present(ItemStackData),
    }
    impl ItemStack {
        pub fn new(kind: &'static str, count: i32) -> Self {
            ItemStack::Present(ItemStackData { kind: ItemKind(kind), count })
        }
        pub fn as_present(&self) -> Option<&ItemStackData> {
            match self {
                ItemStack::Present(d) => Some(d),
                ItemStack::Empty => None,
            }
        }
    }
    /// Real: `azalea::inventory::operations` (azalea_inventory). Same shapes minus `QuickCraft`, which nothing binds.
    pub mod operations {
        #[derive(Clone, Debug)]
        pub enum ClickOperation {
            Pickup(PickupClick),
            QuickMove(QuickMoveClick),
            Swap(SwapClick),
            Clone(CloneClick),
            Throw(ThrowClick),
            PickupAll(PickupAllClick),
        }
        #[derive(Clone, Debug)]
        pub enum PickupClick {
            Left { slot: Option<u16> },
            Right { slot: Option<u16> },
            LeftOutside,
            RightOutside,
        }
        #[derive(Clone, Debug)]
        pub enum QuickMoveClick {
            Left { slot: u16 },
            Right { slot: u16 },
        }
        #[derive(Clone, Debug)]
        pub struct SwapClick {
            pub source_slot: u16,
            pub target_slot: u8,
        }
        #[derive(Clone, Debug)]
        pub struct CloneClick {
            pub slot: u16,
        }
        #[derive(Clone, Debug)]
        pub enum ThrowClick {
            Single { slot: u16 },
            All { slot: u16 },
        }
        #[derive(Clone, Debug)]
        pub struct PickupAllClick {
            pub slot: u16,
            pub reversed: bool,
        }
        macro_rules! into_click {
            ($($t:ident => $v:ident),*) => {$(
                impl From<$t> for ClickOperation {
                    fn from(click: $t) -> Self {
                        ClickOperation::$v(click)
                    }
                }
            )*};
        }
        into_click!(PickupClick => Pickup, QuickMoveClick => QuickMove, SwapClick => Swap, CloneClick => Clone, ThrowClick => Throw, PickupAllClick => PickupAll);
    }
    /// Real: a big enum with one struct variant per menu kind (`Player { .. }`, `Generic9x3 { contents, player }`, ...),
    /// `Debug`-derived, with `slots()` = every slot in protocol order.
    #[derive(Clone, Debug)]
    pub enum Menu {
        Player { inventory: Vec<ItemStack> },
        Generic9x3 { contents: Vec<ItemStack>, player: Vec<ItemStack> },
        BrewingStand { contents: Vec<ItemStack> },
    }
    impl Menu {
        pub fn slots(&self) -> Vec<ItemStack> {
            match self {
                Menu::Player { inventory } => inventory.clone(),
                Menu::Generic9x3 { contents, player } => contents.iter().chain(player).cloned().collect(),
                Menu::BrewingStand { contents } => contents.clone(),
            }
        }
    }
}

/// Real: `azalea::container` (azalea/src/container.rs). `ContainerHandle` derefs to `ContainerHandleRef` and
/// closes the container when dropped; the fake prints when that happens.
pub mod container {
    use crate::{
        Client,
        entity::inventory::Inventory,
        inventory::{
            ItemStack,
            operations::{ClickOperation, PickupClick, QuickMoveClick},
        },
    };

    pub struct ContainerHandleRef {
        id: i32,
        client: Client,
    }
    impl ContainerHandleRef {
        pub fn new(id: i32, client: Client) -> Self {
            Self { id, client }
        }
        /// Real: triggers a `CloseContainerEvent` for this container id.
        pub fn close(&self) {
            println!("[fake] container {} close requested", self.id);
        }
        /// Returns the contents of the menu, including the player's inventory. `None` if the container is closed
        /// (the fake handle is always open until dropped).
        pub fn slots(&self) -> Option<Vec<ItemStack>> {
            Some(if self.id == 0 { Inventory::fake().inventory_menu.slots() } else { self.client.menu().ok()?.slots() })
        }
        /// A shortcut for [`Self::click`] with `PickupClick::Left`.
        pub fn left_click(&self, slot: impl Into<usize>) {
            self.click(PickupClick::Left { slot: Some(slot.into() as u16) });
        }
        /// A shortcut for [`Self::click`] with `QuickMoveClick::Left`.
        pub fn shift_click(&self, slot: impl Into<usize>) {
            self.click(QuickMoveClick::Left { slot: slot.into() as u16 });
        }
        /// A shortcut for [`Self::click`] with `PickupClick::Right`.
        pub fn right_click(&self, slot: impl Into<usize>) {
            self.click(PickupClick::Right { slot: Some(slot.into() as u16) });
        }
        /// Simulate a click in the container and send the packet to perform the action.
        pub fn click(&self, operation: impl Into<ClickOperation>) {
            println!("[fake] container {} click {:?}", self.id, operation.into());
        }
    }

    pub struct ContainerHandle(ContainerHandleRef);
    impl std::ops::Deref for ContainerHandle {
        type Target = ContainerHandleRef;
        fn deref(&self) -> &ContainerHandleRef {
            &self.0
        }
    }
    impl Drop for ContainerHandle {
        fn drop(&mut self) {
            println!("[fake] container {} closed", self.0.id);
        }
    }
    impl ContainerHandle {
        pub(crate) fn new(id: i32, client: Client) -> Self {
            Self(ContainerHandleRef::new(id, client))
        }
    }
}

/// Real: `azalea::entity` is `azalea_entity` (`EntityKindComponent(pub EntityKind)` derefs to the kind).
pub mod entity {
    /// Real: `azalea_entity::HumanoidArm`.
    #[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
    pub enum HumanoidArm {
        Left = 0,
        #[default]
        Right = 1,
    }

    /// Real: `azalea_entity::inventory`.
    pub mod inventory {
        use crate::inventory::{ItemStack, Menu};
        #[derive(Clone, Debug)]
        pub struct Inventory {
            pub inventory_menu: Menu,
            pub container_menu: Option<Menu>,
        }
        impl Inventory {
            pub fn fake() -> Self {
                Inventory {
                    inventory_menu: Menu::Player {
                        inventory: vec![ItemStack::Empty, ItemStack::new("iron_sword", 1), ItemStack::Empty, ItemStack::new("cobblestone", 64)],
                    },
                    container_menu: None,
                }
            }
        }
    }
    use crate::registry::builtin::EntityKind;
    #[derive(Clone, Copy, Debug, PartialEq)]
    pub struct EntityKindComponent(pub EntityKind);
}

/// Real: `azalea::protocol` is `azalea_protocol`.
pub mod protocol {
    pub mod common {
        pub mod client_information {
            use crate::entity::HumanoidArm;

            /// Same fields as the real `ClientInformation` (a Component there; the fake needs no ECS).
            #[derive(Clone, Debug, Eq, PartialEq)]
            pub struct ClientInformation {
                pub language: String,
                pub view_distance: u8,
                pub chat_visibility: ChatVisibility,
                pub chat_colors: bool,
                pub model_customization: ModelCustomization,
                pub main_hand: HumanoidArm,
                pub text_filtering_enabled: bool,
                pub allows_listing: bool,
                pub particle_status: ParticleStatus,
            }
            impl Default for ClientInformation {
                fn default() -> Self {
                    Self {
                        language: "en_us".to_owned(),
                        view_distance: 8,
                        chat_visibility: ChatVisibility::default(),
                        chat_colors: true,
                        model_customization: ModelCustomization::default(),
                        main_hand: HumanoidArm::Right,
                        text_filtering_enabled: false,
                        allows_listing: false,
                        particle_status: ParticleStatus::default(),
                    }
                }
            }

            #[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
            pub enum ChatVisibility {
                #[default]
                Full = 0,
                System = 1,
                Hidden = 2,
            }

            #[derive(Clone, Copy, Debug, Eq, PartialEq)]
            pub struct ModelCustomization {
                pub cape: bool,
                pub jacket: bool,
                pub left_sleeve: bool,
                pub right_sleeve: bool,
                pub left_pants: bool,
                pub right_pants: bool,
                pub hat: bool,
            }
            impl Default for ModelCustomization {
                fn default() -> Self {
                    Self { cape: true, jacket: true, left_sleeve: true, right_sleeve: true, left_pants: true, right_pants: true, hat: true }
                }
            }

            #[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
            pub enum ParticleStatus {
                #[default]
                All,
                Decreased,
                Minimal,
            }
        }
    }

    pub mod packets {
        pub mod game {
            use crate::{FormattedText, MinecraftEntityId};

            /// Real: `azalea_protocol::packets::game::ClientboundPlayerCombatKill`, which the protocol crate's
            /// `declare_state_packets!` macro re-exports (hence the generator's PATH_OVERRIDES entry).
            #[derive(Clone, Debug)]
            pub struct ClientboundPlayerCombatKill {
                pub player_id: MinecraftEntityId,
                pub message: FormattedText,
            }
        }
    }
}
pub use protocol::common::client_information::ClientInformation;

pub mod prelude {
    pub use crate::pathfinder::PathfinderClientExt;
    pub use crate::{Client, Event};
}

#[derive(Debug)]
pub struct MissingComponentError;
impl fmt::Display for MissingComponentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "missing component")
    }
}
pub type AzaleaResult<T> = Result<T, MissingComponentError>;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Uuid(pub String);
impl FromStr for Uuid {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, String> {
        if s.len() >= 4 { Ok(Uuid(s.into())) } else { Err(format!("invalid uuid '{s}'")) }
    }
}
impl fmt::Display for Uuid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(Clone, Debug)]
pub struct FormattedText(pub String);
impl fmt::Display for FormattedText {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}
#[derive(Clone, Debug)]
pub struct ConnectionError(pub String);
impl fmt::Display for ConnectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(Clone, Debug)]
pub struct GameProfile {
    pub uuid: Uuid,
    pub name: String,
    /// Real: `Arc<GameProfileProperties>` whose `map` is an `IndexMap`, which the generator can't map, so
    /// (as with the real azalea) `Client::profile` is skipped and hand-written in extra_state.rs.
    pub properties: Arc<GameProfileProperties>,
}
#[derive(Clone, Debug, Default)]
pub struct GameProfileProperties {
    pub map: indexmap_like::IndexMap<String, String>,
}
/// Stand-in with the same generic shape as `indexmap::IndexMap<K, V>`.
pub mod indexmap_like {
    #[derive(Clone, Debug, Default)]
    pub struct IndexMap<K, V>(pub Vec<(K, V)>);
}
#[derive(Clone, Copy, Debug)]
pub enum GameMode {
    Survival,
    Creative,
}
#[derive(Clone, Debug)]
pub struct PlayerInfo {
    pub profile: GameProfile,
    pub uuid: Uuid,
    pub gamemode: GameMode,
    pub latency: i32,
}

#[derive(Clone, Debug)]
pub struct ChatPacket(pub String);
impl ChatPacket {
    pub fn message(&self) -> FormattedText {
        FormattedText(format!("<Steve> {}", self.0))
    }
    pub fn sender(&self) -> Option<String> {
        Some("Steve".into())
    }
    pub fn content(&self) -> String {
        self.0.clone()
    }
    pub fn is_whisper(&self) -> bool {
        false
    }
}

#[derive(Clone, Copy, Debug)]
pub enum WalkDirection {
    None,
    Forward,
    Backward,
}
#[derive(Clone, Debug)]
pub struct Experience {
    pub progress: f32,
    pub level: i32,
    pub total: i32,
}

#[derive(Clone)]
#[non_exhaustive]
pub enum Event {
    /// Right after the client is created.
    Init,
    Login,
    Chat(ChatPacket),
    Tick,
    AddPlayer(PlayerInfo),
    KeepAlive(u64),
    Disconnect(Option<FormattedText>),
    ConnectionFailed(ConnectionError),
    Death(Option<Arc<protocol::packets::game::ClientboundPlayerCombatKill>>),
}

/// Real: `azalea_entity::LookDirection` (fields private, read through `y_rot()` / `x_rot()`).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct LookDirection {
    y_rot: f32,
    x_rot: f32,
}
impl LookDirection {
    pub fn new(y_rot: f32, x_rot: f32) -> Self {
        Self { y_rot, x_rot }
    }
    pub fn y_rot(&self) -> f32 {
        self.y_rot
    }
    pub fn x_rot(&self) -> f32 {
        self.x_rot
    }
}

/// Real: `azalea_entity::Physics` (plain pub fields, `on_ground()` is a method).
#[derive(Clone, Debug, Default)]
pub struct Physics {
    pub velocity: Vec3,
    pub horizontal_collision: bool,
    pub vertical_collision: bool,
    pub was_touching_water: bool,
    pub fall_distance: f64,
    pub remaining_fire_ticks: i32,
    on_ground: bool,
}
impl Physics {
    pub fn on_ground(&self) -> bool {
        self.on_ground
    }
}

/// Real: `azalea_entity::attributes::AttributeInstance` (`base` is pub, `calculate()` applies modifiers).
#[derive(Clone, Debug)]
pub struct AttributeInstance {
    pub base: f64,
    bonus: f64,
}
impl AttributeInstance {
    pub fn new(base: f64) -> Self {
        Self { base, bonus: 0.0 }
    }
    pub fn calculate(&self) -> f64 {
        self.base + self.bonus
    }
}
/// Real: `azalea_entity::Attributes`, one pub `AttributeInstance` field per attribute.
#[derive(Clone, Debug)]
pub struct Attributes {
    pub movement_speed: AttributeInstance,
    pub sneaking_speed: AttributeInstance,
    pub attack_speed: AttributeInstance,
    pub water_movement_efficiency: AttributeInstance,
    pub mining_efficiency: AttributeInstance,
    pub block_break_speed: AttributeInstance,
    pub block_interaction_range: AttributeInstance,
    pub entity_interaction_range: AttributeInstance,
    pub step_height: AttributeInstance,
}
fn fake_attributes() -> Attributes {
    let a = AttributeInstance::new;
    Attributes {
        movement_speed: AttributeInstance { base: 0.1, bonus: 0.03 },
        sneaking_speed: a(0.3),
        attack_speed: a(4.0),
        water_movement_efficiency: a(0.0),
        mining_efficiency: a(0.0),
        block_break_speed: a(1.0),
        block_interaction_range: a(4.5),
        entity_interaction_range: a(3.0),
        step_height: a(0.6),
    }
}

/// Real: `azalea::Account` (a cloneable handle that derefs to `dyn AccountTrait`).
pub trait AccountTrait: Send + Sync {
    fn username(&self) -> &str;
    fn uuid(&self) -> Uuid;
}
struct OfflineAccount;
impl AccountTrait for OfflineAccount {
    fn username(&self) -> &str {
        "LuauBot"
    }
    fn uuid(&self) -> Uuid {
        Uuid("0000-luau".into())
    }
}
#[derive(Clone)]
pub struct Account(Arc<dyn AccountTrait>);
impl std::ops::Deref for Account {
    type Target = dyn AccountTrait;
    fn deref(&self) -> &Self::Target {
        &*self.0
    }
}

#[derive(Clone)]
pub struct Client {
    pub entity: Entity,
}

impl Client {
    pub fn fake() -> Self {
        Self { entity: Entity(7) }
    }
    /// Send a message in chat.
    pub fn chat(&self, content: impl Into<String>) {
        println!("[fake] chat: {}", content.into());
    }
    /// Send a raw chat packet.
    pub fn write_chat_packet(&self, message: &str) {
        println!("[fake] raw chat: {message}");
    }
    pub fn walk(&self, direction: WalkDirection) {
        println!("[fake] walk {direction:?}");
    }
    pub fn set_direction(&self, y_rot: f32, x_rot: f32) {
        println!("[fake] dir {y_rot} {x_rot}");
    }
    pub fn look_at(&self, position: Vec3) {
        println!("[fake] look_at {position:?}");
    }
    pub fn attack(&self, entity: Entity) {
        println!("[fake] attack {entity:?}");
    }
    pub fn entity_id_by_uuid(&self, uuid: Uuid) -> Option<Entity> {
        println!("[fake] lookup {uuid}");
        Some(Entity(42))
    }
    /// Get an `EntityRef` for the client's own entity.
    pub fn entity(&self) -> EntityRef {
        EntityRef::new(self.clone(), self.entity)
    }
    /// Get an `EntityRef` for an entity with the given UUID, if it's in render distance.
    pub fn entity_by_uuid(&self, uuid: Uuid) -> Option<EntityRef> {
        println!("[fake] entity_by_uuid {uuid}");
        if uuid.0 == "none" { None } else { Some(EntityRef::new(self.clone(), Entity(42))) }
    }
    /// Create an `EntityRef` for the given ECS entity.
    pub fn entity_ref_for(&self, entity: Entity) -> EntityRef {
        EntityRef::new(self.clone(), entity)
    }
    /// Get an `Entity` in the world by its `MinecraftEntityId`.
    pub fn entity_id_by_minecraft_id(&self, id: MinecraftEntityId) -> AzaleaResult<Option<Entity>> {
        Ok(if id.0 == 12 { Some(Entity(42)) } else { None })
    }
    /// Get an `EntityRef` in the world by its `MinecraftEntityId`.
    pub fn entity_by_minecraft_id(&self, id: MinecraftEntityId) -> AzaleaResult<Option<EntityRef>> {
        Ok(self.entity_id_by_minecraft_id(id)?.map(|e| EntityRef::new(self.clone(), e)))
    }
    /// Right-click an entity.
    pub fn entity_interact(&self, entity: Entity) {
        println!("[fake] entity_interact {entity:?}");
    }
    /// Returns the direction the client is looking.
    pub fn direction(&self) -> AzaleaResult<LookDirection> {
        Ok(LookDirection::new(90.0, -15.5))
    }
    /// Returns the `GameProfile` for our client.
    pub fn profile(&self) -> AzaleaResult<GameProfile> {
        Ok(GameProfile { uuid: Uuid("0000-luau".into()), name: "LuauBot".into(), properties: Default::default() })
    }
    /// Returns the `Account` for our client (infallible, like the real one).
    pub fn account(&self) -> Account {
        Account(Arc::new(OfflineAccount))
    }
    /// Get a map of player UUIDs to their information in the tab list.
    pub fn tab_list(&self) -> AzaleaResult<std::collections::HashMap<Uuid, PlayerInfo>> {
        let mut m = std::collections::HashMap::new();
        for (uuid, name, latency) in [("0000-zed", "Zed", 40), ("0000-luau", "LuauBot", 5)] {
            let p = PlayerInfo {
                profile: GameProfile { uuid: Uuid(uuid.into()), name: name.into(), properties: Default::default() },
                uuid: Uuid(uuid.into()),
                gamemode: GameMode::Creative,
                latency,
            };
            m.insert(p.uuid.clone(), p);
        }
        Ok(m)
    }
    /// Returns the current `HitResult`: the block or entity in the client's crosshair.
    /// The fake alternates: block first, entity from the second call on.
    pub fn hit_result(&self) -> AzaleaResult<crate::core::hit_result::HitResult> {
        use crate::core::hit_result::*;
        use std::sync::atomic::{AtomicUsize, Ordering};
        static CALLS: AtomicUsize = AtomicUsize::new(0);
        Ok(if CALLS.fetch_add(1, Ordering::SeqCst) == 0 {
            HitResult::Block(BlockHitResult {
                location: Vec3::new(1.5, 63.0, 2.5),
                miss: false,
                direction: Direction::Up,
                block_pos: BlockPos::new(1, 62, 2),
                inside: false,
                world_border: false,
            })
        } else {
            HitResult::Entity(EntityHitResult { location: Vec3::new(3.0, 64.0, 3.0), entity: Entity(42) })
        })
    }
    /// Get a component from this client. Real: `component<T: Component>` returning a `MappedRwLockReadGuard<T>`
    /// (derefs to `T`); the fake only knows `Inventory` and returns a clone.
    pub fn component<T: FakeComponent>(&self) -> Result<T, MissingComponentError> {
        Ok(T::fake())
    }
    /// Return the menu that is currently open, or the player's inventory if no menu is open.
    pub fn menu(&self) -> AzaleaResult<inventory::Menu> {
        use inventory::{ItemStack, Menu};
        Ok(Menu::Generic9x3 {
            contents: vec![ItemStack::new("diamond", 3), ItemStack::Empty],
            player: vec![ItemStack::new("stick", 2)],
        })
    }
    /// Get the item in the bot's hotbar that is currently being held in its main hand.
    /// The fake holds a stack on the first call and nothing afterwards.
    pub fn get_held_item(&self) -> AzaleaResult<inventory::ItemStack> {
        use std::sync::atomic::{AtomicUsize, Ordering};
        static CALLS: AtomicUsize = AtomicUsize::new(0);
        Ok(if CALLS.fetch_add(1, Ordering::SeqCst) == 0 {
            inventory::ItemStack::new("iron_sword", 1)
        } else {
            inventory::ItemStack::Empty
        })
    }
    /// Open a container in the world, like a chest. Times out after 5 seconds (100 ticks).
    pub async fn open_container_at(&self, pos: BlockPos) -> AzaleaResult<Option<container::ContainerHandle>> {
        self.open_container_at_with_timeout_ticks(pos, Some(20 * 5)).await
    }
    /// Open a container in the world, or time out after a specified amount of ticks. The fake errors below y=0
    /// (real: the world read fails).
    pub async fn open_container_at_with_timeout_ticks(
        &self,
        pos: BlockPos,
        timeout_ticks: Option<usize>,
    ) -> AzaleaResult<Option<container::ContainerHandle>> {
        if pos.y < 0 {
            return Err(MissingComponentError);
        }
        self.wait_for_container_open(timeout_ticks).await
    }
    /// Wait until a container is open, up to the specified number of ticks. `None` on timeout. The fake opens one
    /// straight away, except that `Some(0)` times out.
    pub async fn wait_for_container_open(
        &self,
        timeout_ticks: Option<usize>,
    ) -> AzaleaResult<Option<container::ContainerHandle>> {
        if timeout_ticks == Some(0) {
            return Ok(None);
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
        Ok(Some(container::ContainerHandle::new(1, self.clone())))
    }
    /// Returns a `ContainerHandleRef` to the client's open container, or their inventory. The fake has no open
    /// container, so this is the inventory. Dropping it sends nothing (unlike `ContainerHandle`).
    pub fn get_inventory(&self) -> AzaleaResult<container::ContainerHandleRef> {
        Ok(container::ContainerHandleRef::new(0, self.clone()))
    }
    /// Change the client information; the real one also sends a packet when logged in. The fake prints it.
    pub fn set_client_information(&self, client_information: ClientInformation) -> AzaleaResult<()> {
        println!("[fake] set_client_information {client_information:?}");
        Ok(())
    }
    /// Open the player's inventory. Returns `None` if another container is open (the fake never has one).
    pub fn open_inventory(&self) -> AzaleaResult<Option<container::ContainerHandle>> {
        Ok(Some(container::ContainerHandle::new(0, self.clone())))
    }
    /// Returns every player entity in render distance.
    pub fn nearby_players(&self) -> AzaleaResult<Box<[EntityRef]>> {
        Ok(vec![EntityRef::new(self.clone(), Entity(1)), EntityRef::new(self.clone(), Entity(2))].into_boxed_slice())
    }
    /// Returns an array of `EntityRef` for all known entities that match the given filter, sorted by nearest first.
    /// (Real: generic over `F: QueryFilter`; the fake has the same shape.)
    pub fn nearest_entities<F>(&self) -> AzaleaResult<Box<[EntityRef]>> {
        self.nearest_entities_by::<(), F>(|_| true)
    }
    /// Returns every entity that matches the predicate, nearest first. Real: `Q: QueryData, F: QueryFilter`,
    /// `predicate: impl EntityPredicate<Q, F>` (any `Fn(ROQueryItem<Q>) -> bool`). The fake world holds the
    /// bot (id 7), two players (1, 2), a zombie (3) and a cow (4); `Q` is `()` or `&EntityKindComponent`.
    pub fn nearest_entities_by<Q: FakeQuery, F>(
        &self,
        predicate: impl Fn(Q::Item<'_>) -> bool,
    ) -> AzaleaResult<Box<[EntityRef]>> {
        use crate::registry::builtin::EntityKind::*;
        let world = [(7, Player), (1, Player), (3, Zombie), (2, Player), (4, Cow)];
        Ok(world
            .into_iter()
            .filter(|(_, k)| predicate(Q::item(k)))
            .map(|(id, _)| EntityRef::new(self.clone(), Entity(id)))
            .collect())
    }
    // ---- generator tests only (no real counterpart): class types as params and in lists
    pub fn test_all_entities(&self) -> Vec<EntityRef> {
        vec![self.entity(), EntityRef::new(self.clone(), Entity(3))]
    }
    pub fn test_count_entities(&self, first: EntityRef, maybe: Option<EntityRef>, rest: Vec<EntityRef>) -> usize {
        println!("[fake] test_count_entities first={:?}", first.id());
        1 + maybe.is_some() as usize + rest.len()
    }
    pub fn test_count_boxed(&self, list: Box<[EntityRef]>) -> usize {
        list.len()
    }
    pub fn experience(&self) -> AzaleaResult<Experience> {
        Ok(Experience { progress: 0.5, level: 3, total: 40 })
    }
    pub fn tab_names(&self) -> Vec<String> {
        vec!["a".into(), "b".into()]
    }
    pub fn broken(&self) -> AzaleaResult<f32> {
        Err(MissingComponentError)
    }
    pub async fn wait_ticks(&self, n: usize) {
        tokio::time::sleep(Duration::from_millis(5 * n as u64)).await;
    }
    pub async fn mine(&self, position: BlockPos) {
        println!("[fake] mine {position:?}");
    }
    pub async fn mine_with_auto_tool(&self, block_pos: BlockPos) -> AzaleaResult<()> {
        println!("[fake] mine_with_auto_tool {block_pos:?}");
        Ok(())
    }
    /// Get an `RwLock` with a reference to our (potentially shared) Minecraft world.
    pub fn world(&self) -> AzaleaResult<Arc<RwLock<world::World>>> {
        Ok(Arc::new(RwLock::new(world::World::new())))
    }
    /// The fake hotbar: slot 1 shovel, slot 2 pickaxe, slot 3 axe, everything else bare hand. Like the real one it
    /// answers `index: 0, percentage_per_tick: 0` for fluids and for blocks nothing can mine (bedrock).
    pub fn best_tool_in_hotbar_for_block(&self, block: block::BlockState) -> AzaleaResult<auto_tool::BestToolResult> {
        use registry::builtin::BlockKind::{self, *};
        let kind: BlockKind = block.into();
        let (index, percentage_per_tick) = match kind {
            Water | Lava | Bedrock => (0, 0.0),
            Dirt | GrassBlock => (1, 0.12),
            Stone | DiamondOre => (2, 0.08),
            OakLog => (3, 0.05),
            Air => (0, 1.0),
        };
        Ok(auto_tool::BestToolResult { index, percentage_per_tick })
    }
}

/// Stand-in for bevy's `Component` bound on `Client::component`.
pub trait FakeComponent {
    fn fake() -> Self;
}
impl FakeComponent for entity::inventory::Inventory {
    fn fake() -> Self {
        Self::fake()
    }
}

/// Stand-in for bevy's `QueryData` in the fake: how to turn a world row into the predicate's argument.
pub trait FakeQuery {
    type Item<'a>;
    fn item(kind: &registry::builtin::EntityKind) -> Self::Item<'_>;
}
impl FakeQuery for () {
    type Item<'a> = ();
    fn item(_: &registry::builtin::EntityKind) {}
}
impl FakeQuery for &entity::EntityKindComponent {
    type Item<'a> = &'a entity::EntityKindComponent;
    fn item(kind: &registry::builtin::EntityKind) -> &entity::EntityKindComponent {
        // The fake world only has three kinds, so hand out static components.
        use registry::builtin::EntityKind::*;
        static PLAYER: entity::EntityKindComponent = entity::EntityKindComponent(Player);
        static ZOMBIE: entity::EntityKindComponent = entity::EntityKindComponent(Zombie);
        static COW: entity::EntityKindComponent = entity::EntityKindComponent(Cow);
        match kind {
            Player => &PLAYER,
            Zombie => &ZOMBIE,
            Cow => &COW,
        }
    }
}

/// A reference to an entity in a world (real: `azalea::entity_ref::EntityRef`, re-exported at the root).
#[derive(Clone)]
pub struct EntityRef {
    client: Client,
    entity: Entity,
}

impl EntityRef {
    pub fn new(client: Client, entity: Entity) -> Self {
        Self { client, entity }
    }
    /// Returns the ECS identifier for the entity.
    pub fn id(&self) -> Entity {
        self.entity
    }
}

impl EntityRef {
    /// Attack this entity from the client that created this `EntityRef`.
    pub fn attack(&self) {
        println!("[fake] entity attack {:?} (client {:?})", self.entity, self.client.entity);
    }
}

macro_rules! impl_entity_functions {
    ( $(
        Client:
        $(#[$client_doc:meta])*
        EntityRef:
        $(#[$entityref_doc:meta])*
        pub fn $fn_name:ident (&$fn_self:ident) -> $fn_returns:ty $fn_impl:block
    )* ) => {
        $(
            impl Client {
                $(#[$client_doc])*
                pub fn $fn_name(&$fn_self) -> $fn_returns $fn_impl
            }
            impl EntityRef {
                $(#[$entityref_doc])*
                pub fn $fn_name(&$fn_self) -> $fn_returns $fn_impl
            }
        )*
    };
}

impl_entity_functions! {
    Client:
    /// Get the client's position in the world.
    EntityRef:
    /// Get the entity's position in the world.
    pub fn position(&self) -> AzaleaResult<Vec3> {
        Ok(Vec3::new(1.0, 64.0, 2.0))
    }

    Client:
    /// Get the Minecraft ID of this client.
    EntityRef:
    /// Get the Minecraft ID of this entity.
    pub fn minecraft_id(&self) -> AzaleaResult<MinecraftEntityId> {
        Ok(MinecraftEntityId(7))
    }

    Client:
    /// Returns the attribute values of our player.
    EntityRef:
    /// Returns the attribute values of the entity.
    pub fn attributes(&self) -> AzaleaResult<Attributes> {
        Ok(fake_attributes())
    }

    Client:
    /// Returns the complete `Physics` data for this client.
    EntityRef:
    /// Returns the complete `Physics` data for this entity.
    pub fn physics(&self) -> AzaleaResult<Physics> {
        Ok(Physics { velocity: Vec3::new(0.0, -0.08, 0.0), on_ground: true, fall_distance: 1.5, ..Default::default() })
    }

    Client:
    /// Get the health of this client.
    EntityRef:
    /// Get the health of this entity.
    pub fn health(&self) -> AzaleaResult<f32> {
        Ok(20.0)
    }
}

pub mod pathfinder {
    use crate::{BlockPos, Client};

    pub trait Goal: Send + Sync {
        fn describe(&self) -> String;
    }

    pub mod goals {
        use super::Goal;
        use crate::BlockPos;

        pub struct BlockPosGoal(pub BlockPos);
        /// Real: has a private `max_check_distance`, so the generator skips it (`bot:goto_reach` is hand-written).
        pub struct ReachBlockPosGoal {
            pub pos: BlockPos,
            pub distance: f64,
            pub chunk_storage: crate::world::ChunkStorage,
            max_check_distance: i32,
        }
        impl ReachBlockPosGoal {
            pub fn new(pos: BlockPos, chunk_storage: crate::world::ChunkStorage) -> Self {
                Self::new_with_distance(pos, 4.5, chunk_storage)
            }
            pub fn new_with_distance(pos: BlockPos, distance: f64, chunk_storage: crate::world::ChunkStorage) -> Self {
                Self { pos, distance, chunk_storage, max_check_distance: (distance + 2.).ceil() as i32 }
            }
        }
        impl Goal for ReachBlockPosGoal {
            fn describe(&self) -> String {
                format!("reach {:?} within {} (check {})", self.pos, self.distance, self.max_check_distance)
            }
        }
        pub struct XZGoal {
            pub x: i32,
            pub z: i32,
        }
        impl Goal for BlockPosGoal {
            fn describe(&self) -> String {
                format!("{:?}", self.0)
            }
        }
        impl Goal for XZGoal {
            fn describe(&self) -> String {
                format!("xz {} {}", self.x, self.z)
            }
        }
    }

    #[derive(Clone, Debug)]
    pub struct PathfinderOpts {
        pub(crate) allow_mining: bool,
        pub(crate) retry_on_no_path: bool,
    }
    impl PathfinderOpts {
        pub const fn new() -> Self {
            Self { allow_mining: true, retry_on_no_path: true }
        }
        pub fn allow_mining(mut self, allow_mining: bool) -> Self {
            self.allow_mining = allow_mining;
            self
        }
        pub fn retry_on_no_path(mut self, retry_on_no_path: bool) -> Self {
            self.retry_on_no_path = retry_on_no_path;
            self
        }
    }

    pub trait PathfinderClientExt {
        fn start_goto(&self, goal: impl Goal + 'static);
        fn start_goto_with_opts(&self, goal: impl Goal + 'static, opts: PathfinderOpts);
        async fn goto(&self, goal: impl Goal + 'static);
        async fn goto_with_opts(&self, goal: impl Goal + 'static, opts: PathfinderOpts);
        fn stop_pathfinding(&self);
    }

    impl PathfinderClientExt for Client {
        fn start_goto(&self, goal: impl Goal + 'static) {
            println!("[fake] start_goto {}", goal.describe());
        }
        fn start_goto_with_opts(&self, goal: impl Goal + 'static, opts: PathfinderOpts) {
            println!("[fake] start_goto_with_opts {} {opts:?}", goal.describe());
        }
        async fn goto(&self, goal: impl Goal + 'static) {
            println!("[fake] goto {}", goal.describe());
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }
        async fn goto_with_opts(&self, goal: impl Goal + 'static, opts: PathfinderOpts) {
            println!("[fake] goto_with_opts {} {opts:?}", goal.describe());
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }
        fn stop_pathfinding(&self) {
            println!("[fake] stop_pathfinding");
        }
    }
}
