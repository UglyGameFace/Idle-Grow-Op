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
- The old Supabase path accepts a generic key, cannot verify schema version, and silently falls back to volatile memory.

## Architecture Decision
Use a hybrid model:
- Global account: cross-server identity and future collection/cosmetic/prestige metadata.
- Guild profile: all current economy, garden, inventory, crime, lab, quest, and local progression state.
- Guild world: weather, market, events, crews, district, auctions, and server configuration.

## Changes Completed So Far
- Added canonical typed keys for global accounts, guild profiles, and guild worlds.
- Added strict Discord snowflake validation and rejection of ambiguous legacy cache keys.
- Added an idempotent Supabase schema for `global_accounts`, `guild_profiles`, and `guild_worlds`.
- Added a migration ledger requiring `001_guild_scoped_persistence`.
- Enabled RLS and revoked direct access from Supabase `anon` and `authenticated` roles.
- Added a production bootstrap that requires `SUPABASE_SERVICE_ROLE_KEY`; generic anon keys are unsupported.
- Added startup schema verification with exact missing-migration/table errors.
- Added a lazy scoped record store that loads only requested records.
- Added exact per-record dirty tracking instead of one global dirty flag.
- Added retry-safe flushing: failed writes remain dirty.
- Added concurrent first-read deduplication so one record is loaded only once.
- Added a Supabase backend that routes each scope to its correct table and batches only supplied dirty rows.
- Added a scoped database manager with explicit account/profile/world accessors and clean shutdown flushing.
- Added one strict Discord guild-context boundary; DM commands cannot touch ambiguous game state.
- Migrated the Admin cog to guild-scoped profiles and exact dirty marking.
- Added regression tests for guild isolation, lazy loading, dirty-only writes, failed-write retries, concurrent reads, Supabase routing, schema verification, service-role configuration, and Admin legacy-path rejection.

## Remaining Work
1. Migrate Economy, Farming, Lab, Crime, Social, Tasks, and AI callers to explicit guild scopes.
2. Wire `main.py` to the verified production Supabase bootstrap.
3. Add guild-scoped leaderboard queries without loading every player into RAM.
4. Add legacy data migration tooling with an explicit target guild and dry-run reporting.
5. Remove the old global cache, load-all query, global dirty flag, generic `SUPABASE_KEY`, and memory fallback.
6. Run compilation, full tests, extension registration, migration tests, conflict inspection, and cleanup.

## Validation Status
- PR #3 remains draft and mergeable.
- Scoped manager tests passed on the previous implementation head.
- Supabase hardening and bootstrap checks are running on the latest head.
- Production gameplay callers still partly use the legacy database manager, so the task is not merge-ready.

## Constraints
- No monkey patches.
- No startup guards or silent compatibility shims.
- No permanent dual-write path.
- No command may silently fall back from guild state to another guild or global economy.
- No live deployment may use a public Supabase anon key or volatile memory as its economy database.

## Backlog Locked Behind This Task
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
- Solo-world versus open-world gameplay and item/progression overhaul.
- Large-scale sharding, distributed cache, and worker deployment.
