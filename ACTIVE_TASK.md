# Active Task: Guild-Scoped Persistence Architecture

## Scope
Replace the single global in-memory user/world cache with an explicit hybrid model that scales across Discord servers without cross-server economy leakage, startup-wide user loading, or full-database rewrites.

## Root Cause and Confirmed Findings
- Player records were keyed only by Discord user ID, causing balances, inventory, plants, crews, heat, jail, and progression to leak across servers.
- One global world record shared weather, markets, crews, districts, auctions, events, and configuration across every guild.
- Startup loaded every user into RAM.
- One global dirty flag caused every cached user and the world record to be rewritten.
- Leaderboards and background tasks scanned the complete cache.
- The old Supabase path accepted a generic key, could not verify schema version, and silently fell back to volatile memory.
- Generic Supabase environment names could collide with Dank Shield or another bot's database configuration.
- AI chat accepted an OpenAI key but always called OpenRouter, causing authentication failures.
- AI image generation was unwanted and added unnecessary balance/refund persistence paths.

## Architecture Decision
Use a hybrid model:
- Global account: cross-server identity and future collection, cosmetic, reputation, and prestige metadata.
- Guild profile: local economy, garden, inventory, crime, lab, quests, crew membership, and progression.
- Guild world: weather, market, events, crews, districts, auctions, and server configuration.

Local assets stay local unless a future feature explicitly defines a cross-server system.

## Implementation Completed
- Added canonical typed keys and strict Discord snowflake validation.
- Added lazy loading and concurrent first-read deduplication.
- Added exact per-record dirty tracking and retry-safe flushes.
- Added a scoped database manager with explicit account/profile/world accessors.
- Added strict guild-context helpers; ambiguous DM gameplay is rejected.
- Migrated Admin, Economy, Farming, Lab, Crime, Social, Tasks, and AI to explicit guild scopes.
- Added guild-local indexed wealth and heist leaderboards.
- Added indexed background-notification candidate queries so Tasks does not scan every player.
- Made active heist/session state include guild identity where required.
- Added idempotent Supabase migration `001_guild_scoped_persistence` with a migration ledger.
- Added `global_accounts`, `guild_profiles`, and `guild_worlds` tables.
- Enabled RLS, revoked `anon` and `authenticated`, and restricted server persistence to `service_role`.
- Production bootstrap requires `IDLE_SUPABASE_URL` and `IDLE_SUPABASE_SERVICE_ROLE_KEY` only.
- Generic Supabase variables and the legacy `IDLE_SUPABASE_KEY` are intentionally ignored.
- Startup verifies migration version, required tables, and required generated columns before Discord connects.
- Removed the old Database class, global cache, `world_state`, load-all query, global dirty flag, generic `SUPABASE_KEY`, memory fallback, and import-time background task.
- `main.py` is now the sole owner of database startup, assignment, flush, and shutdown.
- Removed AI image generation commands and all image cost/refund/API code.
- Corrected AI chat to require `OPENROUTER_API_KEY`, use a bounded timeout, validate responses, and report authentication, credit, rate-limit, provider, and timeout failures clearly.
- Added a one-time legacy migration tool requiring an explicit target guild, defaulting to dry-run, refusing conflicting overwrites, batching writes, and preserving legacy tables for rollback.
- Added a guarded manual GitHub Actions workflow for mobile-friendly dry-run/apply execution using Idle Grow-specific secrets.

## Validation Completed
- Python compilation passes.
- Full pytest suite passes.
- Every canonical game extension loads successfully with an explicit scoped test database.
- Supabase schema/bootstrap tests pass.
- Guild-isolation, routing, dirty-only write, failed-write retry, concurrency, leaderboard, background-task, and migration-tool tests pass.
- AI runtime-contract tests pass.
- Legacy persistence and image-generation regression contracts pass.
- Supabase migration `001_guild_scoped_persistence` executed successfully in production.
- Legacy dry-run for home guild `1514374173517152418` reported 39 profiles to copy, 0 conflicts, 0 invalid IDs, and no world conflict.
- Legacy data apply completed successfully.
- Post-copy verification reported 39 legacy profiles, 39 scoped profiles, 0 profile mismatches, a scoped world present, and 0 world mismatches.
- Legacy `users` and `world` tables remain untouched for rollback.

## Production Rollout Status
Completed:
1. Stopped the deployed bot during migration.
2. Installed `migrations/001_guild_scoped_persistence.sql`.
3. Confirmed home guild ID `1514374173517152418`.
4. Dry-ran the legacy copy with zero conflicts.
5. Copied 39 profiles and the legacy world into scoped tables.
6. Verified exact data parity with zero mismatches.

Still required:
1. Configure Discloud with `IDLE_SUPABASE_URL`, `IDLE_SUPABASE_SERVICE_ROLE_KEY`, `DISCORD_TOKEN`, and a valid funded `OPENROUTER_API_KEY`.
2. Remove obsolete `IDLE_SUPABASE_KEY` and `OPENAI_API_KEY` deployment variables.
3. Leave any Dank Shield Supabase variables untouched; Idle Grow does not read them.
4. Merge/deploy the scoped branch.
5. Verify startup reports the scoped Supabase backend and every extension loads.
6. Verify balances and worlds are isolated in at least two Discord servers.
7. Keep legacy tables temporarily for rollback.

## Cleanup Status
- No monkey patches.
- No startup guards.
- No permanent dual-write or compatibility layer.
- No silent cross-scope fallback.
- No public anon-key persistence.
- No cross-bot generic Supabase configuration.
- No image generation.
- Temporary pytest artifact logging remains intentionally in CI for diagnosable failures and is not production code.

## Remaining Before Task Completion
- Final CI on the namespaced-environment commit.
- Configure production environment variables.
- Merge and deploy PR #3.
- Verify the live bot in two servers.

## Backlog Locked Behind This Task
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
- Solo-world versus open-world gameplay, raids, multiplayer, and item/progression overhaul.
- Cross-server tournaments and global account features.
- Large-scale sharding, distributed cache, and worker deployment.
