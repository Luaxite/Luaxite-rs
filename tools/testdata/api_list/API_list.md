# Luaxite Luau API

Declarations for everything scripts can use. Generated; do not edit by hand.

## Types

- `type BlockPos = { x: number, y: number, z: number }`
- `type Item = { kind: string, count: number }`
- `type Menu = { kind: string, slots: { Item | false } }`
- `type PathfinderOpts = { retry_on_no_path: boolean?, allow_mining: boolean? }`
- `type Vec3 = { x: number, y: number, z: number }`
- `type Direction = "down" | "up" | "north" | "south" | "west" | "east"`
- `type WalkDirection = "none" | "forward" | "backward"`
- `type AttributeInstance = { base: number, value: number }`
- `type Attributes = { movement_speed: AttributeInstance, sneaking_speed: AttributeInstance, attack_speed: AttributeInstance, water_movement_efficiency: AttributeInstance, mining_efficiency: AttributeInstance, block_break_speed: AttributeInstance, block_interaction_range: AttributeInstance, entity_interaction_range: AttributeInstance, step_height: AttributeInstance }`
- `type BlockHitResult = { location: Vec3, miss: boolean, direction: Direction, block_pos: BlockPos, inside: boolean, world_border: boolean }`
- `type ChatPacket = { message: string, sender: string?, content: string, is_whisper: boolean }`
- `type ClientboundPlayerCombatKill = { player_id: number, message: string }`
- `type EntityHitResult = { location: Vec3, entity: Entity }`
- `type Experience = { progress: number, level: number, total: number }`
- `type GameProfile = { uuid: string, name: string }`
- `type LookDirection = { y_rot: number, x_rot: number }`
- `type Physics = { velocity: Vec3, horizontal_collision: boolean, vertical_collision: boolean, was_touching_water: boolean, fall_distance: number, remaining_fire_ticks: number, on_ground: boolean }`
- `type PlayerInfo = { name: string, uuid: string, latency: number, gamemode: string }`
- `type HitResult = { kind: "block", location: Vec3, miss: boolean, direction: Direction, block_pos: BlockPos, inside: boolean, world_border: boolean } | { kind: "entity", location: Vec3, entity: Entity }`

## Globals

- `declare azalea: AzaleaLib`
- `declare bot: Bot`
- `declare goal: GoalLib`
- `declare process: ProcessLib`

## `azalea`

- `declare function azalea.join(opts: { account: string | { name: string?, microsoft: string? }, address: string, proxy: string? }): Bot`
- `declare function azalea.swarm(opts: { address: string }): Swarm`
- `declare function azalea.wait(): ()`

## `goal`

- `declare function goal.all(...Goal): Goal`
- `declare function goal.any(...Goal): Goal`
- `declare function goal.block(pos: BlockPos): Goal`
- `declare function goal.inverse(goal: Goal): Goal`
- `declare function goal.radius(pos: Vec3, radius: number): Goal`
- `declare function goal.xz(x: number, z: number): Goal`
- `declare function goal.y(y: number): Goal`

## `process`

- `declare function process.exit(code: number?): ()`

## Bot

- `declare function Bot:account(): { username: string, uuid: string }`
- `declare function Bot:any_entity_by(names: { string }, pred: (row: { [string]: any }, entity: Entity) -> boolean?): Entity?`
- `declare function Bot:attack(entity: Entity): ()`
- `declare function Bot:attributes(): Attributes`
- `declare function Bot:best_tool_for(block: string): number?`
- `declare function Bot:best_tool_in_hotbar_for_block(block: string): { slot: number, percentage_per_tick: number }`
- `declare function Bot:block_at(pos: BlockPos): string?`
- `declare function Bot:broken(): number`
- `declare function Bot:chat(content: string): ()`
- `declare function Bot:component(name: string): any`
- `declare function Bot:direction(): LookDirection`
- `declare function Bot:ecs_names(): { { name: string, kind: string, luau: string, readable: boolean } }`
- `declare function Bot:entity(): Entity`
- `declare function Bot:entity_by_minecraft_id(id: number): Entity?`
- `declare function Bot:entity_by_uuid(uuid: string): Entity?`
- `declare function Bot:entity_component(entity: Entity, name: string): any`
- `declare function Bot:entity_id_by_minecraft_id(id: number): Entity?`
- `declare function Bot:entity_id_by_uuid(uuid: string): Entity?`
- `declare function Bot:entity_interact(entity: Entity): ()`
- `declare function Bot:entity_ref_for(entity: Entity): Entity`
- `declare function Bot:experience(): Experience`
- `declare function Bot:get_component(name: string): any?`
- `declare function Bot:get_entity_component(entity: Entity, name: string): any?`
- `declare function Bot:get_held_item(): Item?`
- `declare function Bot:get_inventory(): Container`
- `declare function Bot:goto(pos: BlockPos): ()`
- `declare function Bot:goto_goal(goal: Goal, opts: PathfinderOpts?): ()`
- `declare function Bot:goto_reach(pos: BlockPos, distance: number?): ()`
- `declare function Bot:goto_with_opts(pos: BlockPos, opts: PathfinderOpts): ()`
- `declare function Bot:goto_with_opts_xz(x: number, z: number, opts: PathfinderOpts): ()`
- `declare function Bot:goto_xz(x: number, z: number): ()`
- `declare function Bot:health(): number`
- `declare function Bot:held_item(): Item?`
- `declare function Bot:hit_result(): HitResult`
- `declare function Bot:inventory(): { Item | false }`
- `declare function Bot:look_at(position: Vec3): ()`
- `declare function Bot:map_get_resource(name: string, f: (value: any?) -> any): any`
- `declare function Bot:map_resource(name: string, f: (value: any) -> any): any`
- `declare function Bot:menu(): Menu`
- `declare function Bot:mine(position: BlockPos): ()`
- `declare function Bot:mine_with_auto_tool(block_pos: BlockPos): ()`
- `declare function Bot:minecraft_id(): number`
- `declare function Bot:nearby_entities(kind: string?): { Entity }`
- `declare function Bot:nearby_players(): { Entity }`
- `declare function Bot:nearest_entities(kind: string?): { Entity }`
- `declare function Bot:nearest_entities_by(names: { string }, pred: (row: { [string]: any }, entity: Entity) -> boolean?): { Entity }`
- `declare function Bot:nearest_entity_by(names: { string }, pred: (row: { [string]: any }, entity: Entity) -> boolean?): Entity?`
- `declare function Bot:nearest_player(): Entity?`
- `declare function Bot:on(event: "init", handler: () -> ()): ()`
- `declare function Bot:on(event: "login", handler: () -> ()): ()`
- `declare function Bot:on(event: "chat", handler: (packet: ChatPacket) -> ()): ()`
- `declare function Bot:on(event: "tick", handler: () -> ()): ()`
- `declare function Bot:on(event: "add_player", handler: (player: PlayerInfo) -> ()): ()`
- `declare function Bot:on(event: "keep_alive", handler: (id: number) -> ()): ()`
- `declare function Bot:on(event: "disconnect", handler: (reason: string?) -> ()): ()`
- `declare function Bot:on(event: "connection_failed", handler: (error: string) -> ()): ()`
- `declare function Bot:on(event: "death", handler: (info: ClientboundPlayerCombatKill?) -> ()): ()`
- `declare function Bot:on(event: "update", handler: () -> ()): ()`
- `declare function Bot:open_container_at(pos: BlockPos): Container?`
- `declare function Bot:open_container_at_with_timeout_ticks(pos: BlockPos, timeout_ticks: number?): Container?`
- `declare function Bot:open_inventory(): Container?`
- `declare function Bot:partial_world(): World`
- `declare function Bot:physics(): Physics`
- `declare function Bot:position(): Vec3`
- `declare function Bot:profile(): GameProfile`
- `declare function Bot:query_entity(entity: Entity, names: { string }, f: (row: { [string]: any }) -> any): any`
- `declare function Bot:query_self(names: { string }, f: (row: { [string]: any }) -> any): any`
- `declare function Bot:raw_connection(): { state: string, is_alive: boolean, injected: { string } }`
- `declare function Bot:raw_connection_mut(f: (conn: { state: string, is_alive: boolean, injected: { string } }) -> ()): ()`
- `declare function Bot:reach_goal(pos: BlockPos, distance: number?): Goal`
- `declare function Bot:registry_entries(registry: string): { string }`
- `declare function Bot:registry_get(registry: string, name: string): { name: string, id: number }?`
- `declare function Bot:registry_kinds(): { string }`
- `declare function Bot:registry_name(registry: string, id: number): string?`
- `declare function Bot:registry_resolve(registry: string, name: string): number?`
- `declare function Bot:resource(name: string): any`
- `declare function Bot:set_client_information(info: { language: string?, view_distance: number?, chat_visibility: ("full" | "system" | "hidden")?, chat_colors: boolean?, model_customization: { cape: boolean?, jacket: boolean?, left_sleeve: boolean?, right_sleeve: boolean?, left_pants: boolean?, right_pants: boolean?, hat: boolean? }?, main_hand: ("left" | "right")?, text_filtering_enabled: boolean?, allows_listing: boolean?, particle_status: ("all" | "decreased" | "minimal")? }): ()`
- `declare function Bot:set_direction(y_rot: number, x_rot: number): ()`
- `declare function Bot:start_goto(pos: BlockPos): ()`
- `declare function Bot:start_goto_goal(goal: Goal, opts: PathfinderOpts?): ()`
- `declare function Bot:start_goto_with_opts(pos: BlockPos, opts: PathfinderOpts): ()`
- `declare function Bot:start_goto_with_opts_xz(x: number, z: number, opts: PathfinderOpts): ()`
- `declare function Bot:start_goto_xz(x: number, z: number): ()`
- `declare function Bot:stop_pathfinding(): ()`
- `declare function Bot:tab_list(): { PlayerInfo }`
- `declare function Bot:tab_names(): { string }`
- `declare function Bot:test_all_entities(): { Entity }`
- `declare function Bot:test_count_boxed(list: { Entity }): number`
- `declare function Bot:test_count_entities(first: Entity, maybe: Entity?, rest: { Entity }): number`
- `declare function Bot:try_query_entity(entity: Entity, names: { string }, f: (row: { [string]: any }) -> any): any?`
- `declare function Bot:try_query_self(names: { string }, f: (row: { [string]: any }) -> any): any?`
- `declare function Bot:wait_for(event: "init"): ()`
- `declare function Bot:wait_for(event: "login"): ()`
- `declare function Bot:wait_for(event: "chat"): ChatPacket`
- `declare function Bot:wait_for(event: "tick"): ()`
- `declare function Bot:wait_for(event: "add_player"): PlayerInfo`
- `declare function Bot:wait_for(event: "keep_alive"): number`
- `declare function Bot:wait_for(event: "disconnect"): string?`
- `declare function Bot:wait_for(event: "connection_failed"): string`
- `declare function Bot:wait_for(event: "death"): ClientboundPlayerCombatKill?`
- `declare function Bot:wait_for(event: "update"): ()`
- `declare function Bot:wait_for_container_open(timeout_ticks: number?): Container?`
- `declare function Bot:wait_tick(): ()`
- `declare function Bot:wait_ticks(n: number): ()`
- `declare function Bot:wait_update(): ()`
- `declare function Bot:walk(direction: WalkDirection): ()`
- `declare function Bot:world(): World`
- `declare function Bot:write_chat_packet(message: string): ()`
- `declare function Bot:write_packet(kind: OutPacketKind, fields: { [string]: any }?): ()`

## Entity

- `declare function Entity:attack(): ()`
- `declare function Entity:attributes(): Attributes`
- `declare function Entity:component(name: string): any`
- `declare function Entity:distance_to(other: Entity): number`
- `declare function Entity:get_component(name: string): any?`
- `declare function Entity:health(): number`
- `declare function Entity:kind(): string`
- `declare function Entity:minecraft_id(): number`
- `declare function Entity:physics(): Physics`
- `declare function Entity:position(): Vec3`
- `declare function Entity:query_self(names: { string }, f: (row: { [string]: any }) -> any): any`
- `declare function Entity:try_query_self(names: { string }, f: (row: { [string]: any }) -> any): any?`

## Container

- `declare function Container:close(): ()`
- `declare function Container:contents(): { Item | false }?`
- `declare function Container:double_click(slot: number): ()`
- `declare function Container:drop_cursor(whole_stack: boolean?): ()`
- `declare function Container:id(): number?`
- `declare function Container:left_click(slot: number): ()`
- `declare function Container:middle_click(slot: number): ()`
- `declare function Container:quick_craft(kind: "left" | "right" | "middle", slots: { number }): ()`
- `declare function Container:right_click(slot: number): ()`
- `declare function Container:shift_click(slot: number): ()`
- `declare function Container:slots(): { Item | false }?`
- `declare function Container:swap(slot: number, target: number): ()`
- `declare function Container:throw(slot: number, whole_stack: boolean?): ()`
- `declare function Container:title(): string?`

## World

- `declare function World:biome(pos: BlockPos): string?`
- `declare function World:block_state(pos: BlockPos): string?`
- `declare function World:chunk_loaded(pos: BlockPos): boolean`
- `declare function World:find_block(block: string | { string }, from: BlockPos?, max_distance: number?): BlockPos?`
- `declare function World:find_blocks(block: string | { string }, from: BlockPos?, max_distance: number?, limit: number?): { BlockPos }`
- `declare function World:height(x: number, z: number): number?`
- `declare function World:is_chunk_loaded(chunk_x: number, chunk_z: number): boolean`

## Goal

- `declare function Goal:describe(): string`

## Swarm

- `declare function Swarm:add(account: string | { name: string?, microsoft: string? }): Bot`
- `declare function Swarm:exit(): ()`
