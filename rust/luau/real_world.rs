use std::collections::{HashMap, HashSet};

use azalea::{
    BlockPos, block::BlockStates, core::position::ChunkPos, prelude::Client,
    registry::builtin::BlockKind,
};
use mlua::{UserData, Value};

use super::{
    convert::{LBlockPos, lua_err},
    gen_client::LuaClient,
};

#[derive(UserData)]
pub struct LuaWorld {
    #[lua(skip)]
    pub client: Client,
    #[lua(skip)]
    pub partial: bool,
}

const TOP_Y: i32 = 319;
const BOTTOM_Y: i32 = -64;
const DEFAULT_LIMIT: usize = 256;
/// Scan cap: `find_block(s)` stops after examining this many hits that already passed the distance and loaded-chunk filters
/// (azalea yields hits roughly nearest chunk first, so this only bounds the time spent in a pathological world). It is also the
/// ceiling for `limit`. Hits in unloaded chunks never count towards it.
const MAX_CANDIDATES: usize = 200_000;

fn nearer(a: &(f64, BlockPos), b: &(f64, BlockPos)) -> std::cmp::Ordering {
    a.0.total_cmp(&b.0)
        .then(a.1.x.cmp(&b.1.x))
        .then(a.1.y.cmp(&b.1.y))
        .then(a.1.z.cmp(&b.1.z))
}

/// The `limit` nearest hits of a scan, without keeping (or sorting) all of them: whenever the buffer reaches twice `limit` it is
/// cut back to the `limit` nearest with `select_nth_unstable_by`, so a scan costs O(hits) time and O(limit) memory.
struct Nearest {
    limit: usize,
    hits: Vec<(f64, BlockPos)>,
}

impl Nearest {
    fn new(limit: usize) -> Self {
        Self {
            limit,
            hits: Vec::new(),
        }
    }

    fn push(&mut self, d: f64, pos: BlockPos) {
        if self.limit == 0 {
            return;
        }
        self.hits.push((d, pos));
        if self.hits.len() >= self.limit.saturating_mul(2).max(16) {
            self.trim();
        }
    }

    fn trim(&mut self) {
        if self.limit > 0 && self.hits.len() > self.limit {
            self.hits.select_nth_unstable_by(self.limit - 1, nearer);
            self.hits.truncate(self.limit);
        }
    }

    /// Nearest first; equal distances ordered by x, y, z so the result doesn't depend on the trimming.
    fn finish(mut self) -> Vec<BlockPos> {
        self.trim();
        self.hits.sort_by(nearer);
        self.hits.into_iter().map(|(_, pos)| pos).collect()
    }
}

/// A block / chunk coordinate argument: floored like `BlockPos` fields (so `bot:position().x` works), an error for NaN or beyond i32.
fn floor_coord(name: &str, n: f64) -> mlua::Result<i32> {
    let f = n.floor();
    if f.is_nan() || f < i32::MIN as f64 || f > i32::MAX as f64 {
        return Err(lua_err(format!("`{name}` is {n}, not a usable coordinate")));
    }
    Ok(f as i32)
}

fn is_air(name: &str) -> bool {
    matches!(
        name,
        "minecraft:air" | "minecraft:cave_air" | "minecraft:void_air"
    )
}

fn block_kinds(value: Value) -> mlua::Result<Vec<BlockKind>> {
    let mut raw: Vec<String> = Vec::new();
    match value {
        Value::String(s) => raw.push(s.to_str()?.to_string()),
        Value::Table(t) => {
            for item in t.sequence_values::<String>() {
                raw.push(item?);
            }
        }
        other => {
            return Err(lua_err(format!(
                "expected a block name or a table of block names, got {}",
                other.type_name()
            )));
        }
    }
    if raw.is_empty() {
        return Err(lua_err("expected at least one block name"));
    }
    let mut kinds = Vec::new();
    for name in raw {
        let kind: BlockKind = name
            .parse()
            .map_err(|_| lua_err(format!("unknown block '{name}'")))?;
        kinds.push(kind);
    }
    Ok(kinds)
}

impl LuaWorld {
    /// Whether one chunk is loaded. Takes the partial-world lock (partial worlds) or the world read lock, one at a time:
    /// never hold both locks. Never call this while a world guard is held; a scan over many chunks uses `loaded_chunk_map`.
    fn chunk_is_loaded(&self, chunk_x: i32, chunk_z: i32) -> mlua::Result<bool> {
        let pos = ChunkPos::new(chunk_x, chunk_z);
        if self.partial {
            let partial = self.client.partial_world().map_err(lua_err)?;
            let guard = partial.read();
            return Ok(guard.chunks.in_range(&pos) && guard.chunks.has(&pos));
        }
        let world = self.client.world().map_err(lua_err)?;
        let state = world.read().get_block_state(BlockPos::new(
            chunk_x.saturating_mul(16),
            64,
            chunk_z.saturating_mul(16),
        ));
        Ok(state.is_some())
    }

    /// Whether each of `keys` (chunk x, z) is loaded in the partial world, answered under ONE partial-world read guard
    /// that is dropped before returning (so a caller can take the world guard before or after, never inside).
    fn loaded_chunk_map(
        &self,
        keys: &HashSet<(i32, i32)>,
    ) -> mlua::Result<HashMap<(i32, i32), bool>> {
        let partial = self.client.partial_world().map_err(lua_err)?;
        let guard = partial.read();
        let map: HashMap<(i32, i32), bool> = keys
            .iter()
            .map(|&(x, z)| {
                let pos = ChunkPos::new(x, z);
                (
                    (x, z),
                    guard.chunks.in_range(&pos) && guard.chunks.has(&pos),
                )
            })
            .collect();
        drop(guard);
        Ok(map)
    }

    fn block_chunk_loaded(&self, pos: BlockPos) -> mlua::Result<bool> {
        self.chunk_is_loaded(pos.x.div_euclid(16), pos.z.div_euclid(16))
    }

    fn state_name(&self, pos: BlockPos) -> mlua::Result<Option<String>> {
        if self.partial && !self.block_chunk_loaded(pos)? {
            return Ok(None);
        }
        let world = self.client.world().map_err(lua_err)?;
        let state = world.read().get_block_state(pos);
        Ok(state.map(|state| BlockKind::from(state).to_str().to_owned()))
    }

    /// Shared scan of `find_block` / `find_blocks`. Never hold both locks (the world read guard and the partial-world
    /// lock): a partial world is scanned in two passes, the world guard is dropped before `loaded_chunk_map` takes the
    /// partial-world guard, and the second pass only reads the map it returned.
    fn search(
        &self,
        kinds: &[BlockKind],
        from: Option<LBlockPos>,
        max_distance: Option<f64>,
        limit: usize,
    ) -> mlua::Result<Vec<BlockPos>> {
        let center = match from {
            Some(p) => p.0,
            None => {
                let p = self.client.position().map_err(lua_err)?;
                BlockPos::new(p.x.floor() as i32, p.y.floor() as i32, p.z.floor() as i32)
            }
        };
        let max_sq = match max_distance {
            Some(d) if d.is_finite() && d >= 0.0 => d * d,
            Some(_) => return Err(lua_err("max_distance must be a number >= 0")),
            None => f64::INFINITY,
        };
        let limit = limit.min(MAX_CANDIDATES);
        if limit == 0 {
            return Ok(Vec::new());
        }
        let states = BlockStates::from(kinds);
        let world = self.client.world().map_err(lua_err)?;
        let dist_sq = |pos: BlockPos| {
            let (dx, dy, dz) = (
                (pos.x as i64 - center.x as i64) as f64,
                (pos.y as i64 - center.y as i64) as f64,
                (pos.z as i64 - center.z as i64) as f64,
            );
            dx * dx + dy * dy + dz * dz
        };
        let chunk_key = |pos: BlockPos| (pos.x.div_euclid(16), pos.z.div_euclid(16));
        // Partial world: look up which chunks are loaded without ever holding the world guard and the partial-world lock
        // together. Pass 1 (world guard only) collects the chunks of the in-range hits, the guard is dropped, then one
        // partial-world guard answers for all of them; pass 2 below takes the world guard again and only reads the map.
        let loaded_chunks = if self.partial {
            let mut keys: HashSet<(i32, i32)> = HashSet::new();
            {
                let guard = world.read();
                for pos in guard.find_blocks(center, &states) {
                    if dist_sq(pos) <= max_sq {
                        keys.insert(chunk_key(pos));
                    }
                }
            }
            Some(self.loaded_chunk_map(&keys)?)
        } else {
            None
        };
        let mut nearest = Nearest::new(limit);
        let mut examined = 0usize;
        let guard = world.read();
        for pos in guard.find_blocks(center, &states) {
            let d = dist_sq(pos);
            if d > max_sq {
                continue;
            }
            if let Some(loaded_chunks) = &loaded_chunks {
                // Filter before the hit counts towards the scan cap, so unloaded chunks can't push real hits out.
                // A chunk missing from the map (it arrived after pass 1) counts as not loaded.
                let loaded = loaded_chunks.get(&chunk_key(pos)).copied().unwrap_or(false);
                if !loaded {
                    continue;
                }
            }
            nearest.push(d, pos);
            examined += 1;
            if examined >= MAX_CANDIDATES {
                break;
            }
        }
        drop(guard);
        Ok(nearest.finish())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pos(x: i32) -> BlockPos {
        BlockPos::new(x, 0, 0)
    }

    #[test]
    fn nearest_keeps_the_closest_in_order() {
        for limit in [1usize, 3, 20] {
            let mut n = Nearest::new(limit);
            for i in (0..100).rev() {
                n.push((i * i) as f64, pos(i));
            }
            let got: Vec<i32> = n.finish().into_iter().map(|p| p.x).collect();
            assert_eq!(got, (0..limit as i32).collect::<Vec<_>>());
        }
    }

    #[test]
    fn nearest_limit_zero_and_ties() {
        let mut n = Nearest::new(0);
        n.push(1.0, pos(1));
        assert!(n.finish().is_empty());
        let mut n = Nearest::new(2);
        for x in [5, 3, 4, 1, 2] {
            n.push(1.0, pos(x));
        }
        let got: Vec<i32> = n.finish().into_iter().map(|p| p.x).collect();
        assert_eq!(got, vec![1, 2]);
    }
}

#[mlua::userdata_impl]
impl LuaWorld {
    // luau[World]: --- The block at `pos` as a name like "minecraft:stone" ("minecraft:air" for air), or nil when that position isn't in a loaded chunk. Never yields.
    // luau[World]: function block_state(self, pos: BlockPos): string?
    fn block_state(&self, pos: LBlockPos) -> mlua::Result<Option<String>> {
        self.state_name(pos.0)
    }

    // luau[World]: --- Whether the chunk with chunk coordinates `chunk_x`, `chunk_z` (block coordinate // 16) is loaded.
    // luau[World]: function is_chunk_loaded(self, chunk_x: number, chunk_z: number): boolean
    fn is_chunk_loaded(&self, chunk_x: f64, chunk_z: f64) -> mlua::Result<bool> {
        self.chunk_is_loaded(
            floor_coord("chunk_x", chunk_x)?,
            floor_coord("chunk_z", chunk_z)?,
        )
    }

    // luau[World]: --- Whether the chunk that contains the block position `pos` is loaded.
    // luau[World]: function chunk_loaded(self, pos: BlockPos): boolean
    fn chunk_loaded(&self, pos: LBlockPos) -> mlua::Result<bool> {
        self.block_chunk_loaded(pos.0)
    }

    // luau[World]: --- The biome at `pos` as a name like "minecraft:plains", or nil when the position isn't loaded or the server never sent that biome's name. Never yields.
    // luau[World]: function biome(self, pos: BlockPos): string?
    #[allow(deprecated)]
    fn biome(&self, pos: LBlockPos) -> mlua::Result<Option<String>> {
        if self.partial && !self.block_chunk_loaded(pos.0)? {
            return Ok(None);
        }
        let world = self.client.world().map_err(lua_err)?;
        let biome = world.read().get_biome(pos.0);
        let Some(biome) = biome else { return Ok(None) };
        let name = self.client.resolve_registry_name(&biome).map_err(lua_err)?;
        Ok(name.map(|n| n.to_string()))
    }

    // luau[World]: --- The y of the highest block in the column at block coordinates `x`, `z` that isn't air, or nil when the column isn't loaded (or holds only air). Looks from y=319 down to y=-64.
    // luau[World]: function height(self, x: number, z: number): number?
    fn height(&self, x: f64, z: f64) -> mlua::Result<Option<i32>> {
        let (x, z) = (floor_coord("x", x)?, floor_coord("z", z)?);
        if !self.block_chunk_loaded(BlockPos::new(x, 64, z))? {
            return Ok(None);
        }
        let world = self.client.world().map_err(lua_err)?;
        let guard = world.read();
        for y in (BOTTOM_Y..=TOP_Y).rev() {
            if let Some(state) = guard.get_block_state(BlockPos::new(x, y, z)) {
                if !is_air(BlockKind::from(state).to_str()) {
                    return Ok(Some(y));
                }
            }
        }
        Ok(None)
    }

    // luau[World]: --- The loaded block nearest to `from` (default: the bot's block) whose name is `block` (a name like "stone" or "minecraft:stone", or a table of names), no further than `max_distance` blocks away (default: no limit), or nil. Unknown names are an error. Never yields; searching a large loaded area takes a moment.
    // luau[World]: function find_block(self, block: string | { string }, from: BlockPos?, max_distance: number?): BlockPos?
    fn find_block(
        &self,
        block: Value,
        from: Option<LBlockPos>,
        max_distance: Option<f64>,
    ) -> mlua::Result<Option<LBlockPos>> {
        let kinds = block_kinds(block)?;
        let found = self.search(&kinds, from, max_distance, 1)?;
        Ok(found.into_iter().next().map(LBlockPos))
    }

    // luau[World]: --- Loaded blocks named `block` (see `find_block`) within `max_distance` of `from`, nearest first, at most `limit` (default 256).
    // luau[World]: function find_blocks(self, block: string | { string }, from: BlockPos?, max_distance: number?, limit: number?): { BlockPos }
    fn find_blocks(
        &self,
        block: Value,
        from: Option<LBlockPos>,
        max_distance: Option<f64>,
        limit: Option<usize>,
    ) -> mlua::Result<Vec<LBlockPos>> {
        let kinds = block_kinds(block)?;
        let found = self.search(&kinds, from, max_distance, limit.unwrap_or(DEFAULT_LIMIT))?;
        Ok(found.into_iter().map(LBlockPos).collect())
    }
}

#[mlua::userdata_impl]
impl LuaClient {
    // luau[Bot]: --- A handle on the bot's world, for block reads and block searches (see `World`). Never yields.
    // luau[Bot]: function world(self): World
    fn world(&self) -> mlua::Result<LuaWorld> {
        self.client.world().map_err(lua_err)?;
        Ok(LuaWorld {
            client: self.client.clone(),
            partial: false,
        })
    }

    // luau[Bot]: --- Like `world()`, but only the chunks this bot itself has loaded (inside its view distance) count as loaded. It differs from `world()` only when several bots share one world.
    // luau[Bot]: function partial_world(self): World
    fn partial_world(&self) -> mlua::Result<LuaWorld> {
        self.client.partial_world().map_err(lua_err)?;
        Ok(LuaWorld {
            client: self.client.clone(),
            partial: true,
        })
    }

    // luau[Bot]: --- The name of the world (dimension) the bot is in, like "minecraft:overworld". Two bots or entities with the same name are in the same world.
    // luau[Bot]: function world_name(self): string
    fn world_name(&self) -> mlua::Result<String> {
        Ok(self.client.world_name().map_err(lua_err)?.to_string())
    }
}
