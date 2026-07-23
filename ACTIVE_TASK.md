# Active Task: Guild-Scoped Persistence Architecture

## Scope
Replace the single global in-memory user/world cache with an explicit hybrid model that can scale across many Discord servers without cross-server economy leakage or full-database rewrites.

## Confirmed Findings
- Player records are keyed only by Discord user ID, so balances, inventory, plants, crews, heat, jail, and progression leak across every server.
- One `__world__` record is shared globally, so weather, markets, crews, districts, auctions, and events are unintentionally shared by all guilds.
- Startup eagerly loads every user row into RAM.
- Any mutation marks one global dirty flag.
- Every sync rewrites every cached user plus the world record.
- The current schema has no explicit global-account, guild-profile, or guild-world boundary.
- Leaderboards and background tasks iterate the complete cache instead of a guild scope.

## Architecture Decision
Use a hybrid model:
- Global account: cross-server identity and future collection/cosmetic/prestige metadata.
- Guild profile: all current economy, garden, inventory, crime, lab, quest, and local progression state.
- Guild world: weather, market, events, crews, district, auctions, and server configuration.

## Implementation Sequence
1. Add canonical scope/key helpers and schema contracts.
2. Replace load-all/save-all persistence with lazy record loading and per-record dirty tracking.
3. Add explicit global-account, guild-profile, and guild-world accessors.
4. Migrate every command and background caller to pass its guild scope.
5. Add legacy migration tooling and database schema SQL.
6. Remove the old global cache and compatibility paths.
7. Run compilation, full tests, extension registration, migration tests, conflict inspection, and cleanup.

## Current Status
- Branch created from validated `main`.
- Root storage execution path inspected.
- No production code changed yet.

## Constraints
- No monkey patches.
- No startup guards or silent compatibility shims.
- No permanent dual-write path.
- No command may silently fall back from guild state to another guild or global economy.

## Backlog Locked Behind This Task
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
- Large-scale sharding, distributed cache, and worker deployment.
