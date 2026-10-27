# Changelog

## Unreleased

### Breaking

- `Bot:nearest_entities`, `Bot:nearest_entities_by`, `Bot:nearest_entity_by` and `Bot:any_entity_by` no longer return the bot itself; older versions included it. `Bot:nearby_entities` already excluded it.
- Default timeouts: `process.exec` is killed after 600 s and `net.request` fails after 120 s unless the script passes `options.timeout`; `timeout = 0` disables the limit. Before, both waited forever without an `options.timeout`.

### Fixed

- `Bot:goto_reach(pos)` without a distance uses 4.5 blocks again, as before it switched to azalea's default reach.
