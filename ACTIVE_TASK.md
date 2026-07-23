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

## Changes Completed So Far
- Added canonical typed keys for global accounts, guild profiles, and guild worlds.
- Added strict Discord snowflake validation and rejection of ambiguous legacy cache keys.
- Added a non-destructive Supabase schema for `global_accounts`, `guild_profiles`, and `guild_worlds`.
- Added a lazy scoped record store that loads only requested records.
- Added exact per-record dirty tracking instead of one global dirty flag.
- Added retry-safe flushing: failed writes remain dirty.
- Added concurrent first-read deduplication so one record is loaded only once.
- Added a Supabase backend that routes each scope to its correct table and batches only supplied dirty rows.
- Added regression tests for guild isolation, lazy loading, dirty-only writes, failed-write retries, concurrent reads, and Supabase table routing.

## Remaining Work
1. Integrate the scoped store into the production database manager.
2. Add explicit global-account, guild-profile, and guild-world accessors.
3. Migrate every command and background caller to pass its guild scope.
4. Add legacy data migration tooling.
5. Remove the old global cache, load-all query, global dirty flag, and save-all sync path.
6. Run compilation, full tests, extension registration, migration tests, conflict inspection, and cleanup.

## Validation Status
- PR #3 remains draft.
- New scoped-store and backend tests are awaiting CI on the latest head.
- Production callers still use the legacy database manager, so the task is not merge-ready.

## Constraints
- No monkey patches.
- No startup guards or silent compatibility shims.
- No permanent dual-write path.
- No command may silently fall back from guild state to another guild or global economy.

## Backlog Locked Behind This Task
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
- Large-scale sharding, distributed cache, and worker deployment.
