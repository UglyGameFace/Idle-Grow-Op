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
- Production bootstrap requires `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
- Startup verifies migration version, required tables, and required generated columns before Discord connects.
- Removed the old Database class, global cache, `world_state`, load-all query, global dirty flag, generic `SUPABASE_KEY`, memory fallback, and import-time background task.
- `main.py` is now the sole owner of database startup, assignment, flush, and shutdown.
- Removed AI image generation commands and all image cost/refund/API code.
- Corrected AI chat to require `OPENROUTER_API_KEY`, use a bounded timeout, validate responses, and report authentication, credit, rate-limit, provider, and timeout failures clearly.
- Added a one-time legacy migration tool requiring an explicit target guild, defaulting to dry-run, refusing conflicting overwrites, batching writes, and preserving legacy tables for rollback.
- Added a guarded manual GitHub Actions workflow for mobile-friendly dry-run/apply execution.

## Validation Completed
- Python compilation passes.
- Full pytest suite passes.
- Every canonical game extension loads successfully with an explicit scoped test database.
- Supabase schema/bootstrap tests pass.
- Guild-isolation, routing, dirty-only write, failed-write retry, concurrency, leaderboard, background-task, and migration-tool tests pass.
- AI runtime-contract tests pass.
- Legacy persistence and image-generation regression contracts pass.
- Latest complete CI before the guarded workflow: run 199, green on commit `978aabe6ca7b1f562a6f024bbdf3a51bde222613`.

## Production Rollout Order
1. Stop the currently deployed bot so legacy data cannot change during migration.
2. Back up the existing Supabase `users` and `world` tables.
3. Run `migrations/001_guild_scoped_persistence.sql` in Supabase.
4. Add GitHub repository secrets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
5. Run the `Migrate Legacy Game Data` workflow in `dry-run` mode.
6. Use confirmed home guild ID `1514374173517152418`.
7. Review counts and conflicts. Do not continue if conflicts are reported.
8. Rerun the workflow in `apply` mode using exact confirmation `MIGRATE 1514374173517152418`.
9. Rerun dry-run to confirm all records are identical/skipped and no conflicts remain.
10. Configure Discloud with `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DISCORD_TOKEN`, and a valid funded `OPENROUTER_API_KEY`.
11. Remove obsolete `SUPABASE_KEY` and `OPENAI_API_KEY` variables from the deployment configuration.
12. Deploy the branch only after the migration is applied.
13. Verify startup reports the scoped Supabase backend, all extensions load, and commands work in at least two servers with isolated balances/worlds.
14. Keep legacy tables temporarily for rollback; do not delete them as part of this PR.

## Cleanup Status
- No monkey patches.
- No startup guards.
- No permanent dual-write or compatibility layer.
- No silent cross-scope fallback.
- No public anon-key persistence.
- No image generation.
- Temporary pytest artifact logging remains intentionally in CI for diagnosable failures and is not production code.

## Remaining Before Merge
- Add the two Supabase repository secrets.
- Execute the SQL migration.
- Run and review the guarded dry-run for guild `1514374173517152418`.
- Apply and verify the one-time legacy migration.
- Verify the deployed bot in two servers.

## Backlog Locked Behind This Task
- Player onboarding and Discord-native control panel.
- Admin setup and server customization.
- Solo-world versus open-world gameplay, raids, multiplayer, and item/progression overhaul.
- Cross-server tournaments and global account features.
- Large-scale sharding, distributed cache, and worker deployment.
