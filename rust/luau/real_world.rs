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



const MAX_CANDIDATES: usize = 200_000;

fn nearer(a: &(f64, BlockPos), b: &(f64, BlockPos)) -> std::cmp::Ordering {
    a.0.total_cmp(&b.0)
        .then(a.1.x.cmp(&b.1.x))
        .then(a.1.y.cmp(&b.1.y))
        .then(a.1.z.cmp(&b.1.z))
}



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

    
    fn finish(mut self) -> Vec<BlockPos> {
        self.trim();
        self.hits.sort_by(nearer);
        self.hits.into_iter().map(|(_, pos)| pos).collect()
    }
}


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
    
    
    fn block_state(&self, pos: LBlockPos) -> mlua::Result<Option<String>> {
        self.state_name(pos.0)
    }

    
    
    fn is_chunk_loaded(&self, chunk_x: f64, chunk_z: f64) -> mlua::Result<bool> {
        self.chunk_is_loaded(
            floor_coord("chunk_x", chunk_x)?,
            floor_coord("chunk_z", chunk_z)?,
        )
    }

    
    
    fn chunk_loaded(&self, pos: LBlockPos) -> mlua::Result<bool> {
        self.block_chunk_loaded(pos.0)
    }

    
    
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
    
    
    fn world(&self) -> mlua::Result<LuaWorld> {
        self.client.world().map_err(lua_err)?;
        Ok(LuaWorld {
            client: self.client.clone(),
            partial: false,
        })
    }

    
    
    fn partial_world(&self) -> mlua::Result<LuaWorld> {
        self.client.partial_world().map_err(lua_err)?;
        Ok(LuaWorld {
            client: self.client.clone(),
            partial: true,
        })
    }

    
    
    fn world_name(&self) -> mlua::Result<String> {
        Ok(self.client.world_name().map_err(lua_err)?.to_string())
    }
}
