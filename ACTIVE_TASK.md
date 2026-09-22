# Active Task: Idle Grow Master Audit and Legacy Consolidation

## Outcome
Establish one trustworthy, production-ready Idle Grow architecture by tracing every live subsystem, identifying authoritative ownership, removing proven obsolete/conflicting implementations, repairing runtime defects, strengthening behavioral coverage, and validating the exact final build against real deployment behavior.

## Scope
This audit covers the complete Idle Grow repository and deployed behavior:
- startup, shutdown, reconnects, extension loading, slash/prefix command publication, and Discord intents
- command execution and user-facing help/onboarding
- Supabase persistence, cache/dirty tracking, migrations, concurrency, flush/failure behavior, and data ownership
- Solo Grow, Current Server World, Player Choice, and Open World scope routing
- farming, economy, progression, lab, crime, gambling, crews/social, sesh, AI, notifications, profile signatures, setup, admin, weather, market/events, auctions, and scheduled tasks
- CI/tests, Discloud deployment assumptions, stale compatibility logic, temporary artifacts, duplicated ownership, and dead code

## Status
IN PROGRESS

## Phase 1 Complete: Command Surface and Runtime Baseline
Validated on exact head cae20b52d942a6a21137005f53a5778ad03d2149 with CI run 690 successful.

Completed:
- Fixed the confirmed /calc runtime NameError by retaining the resolved GameScope.
- Added a real callback regression proving /calc uses the active scope's effective market multiplier.
- Added a CI undefined-name gate for production modules.
- Converted public gameplay prefix-only commands/groups to hybrid ownership while preserving prefix compatibility.
- Consolidated heist, laundering/heat/stats, concentrate sales/status, auction/bid, crew/district, and related configuration commands onto slash + prefix hybrid callbacks.
- Removed stale player-facing ! command instructions from crime, economy, social, and casino usage surfaces.
- Added regression coverage forbidding future prefix-only top-level gameplay commands and stale prefix guidance.
- Extended real extension-load/tree coverage to require the consolidated gameplay commands.
- Strengthened startup command sync so Discord's returned top-level command set must exactly match the complete local tree, not merely contain five required commands.

Cleanup:
- No duplicate slash wrappers were added.
- Admin maintenance commands remain intentionally prefix-only and hidden/owner-oriented.
- Command consolidation changed existing authoritative callbacks rather than creating parallel implementations.


## Confirmed Findings
- Current main head at audit start: af81d32378afdc46a6da9915b06985d8777d0f79.
- No open pull requests existed at audit start.
- Discord startup loads all configured extensions before bot.start() and uses IdleGrowBot.setup_hook() to globally sync application commands.
- Background weather/market processing is owned by tasks.py and can remain healthy independently of user command execution, explaining the observed half-working bot behavior.
- The previous slash-command incident was real: PR #28 repaired startup publication after Discord had retained a stale remote command set.
- The command architecture is still mixed. Core gameplay contains hybrid/slash commands alongside prefix-only commands and prefix-only groups.
- Confirmed prefix-only gameplay surfaces currently include heist, launder, conc, sellconc, bid, district, crew, and auction entry points/subcommands. These require intent/UX review rather than blind conversion.
- Existing command uniqueness tests only prove duplicate names/aliases are absent; they do not prove every advertised or intended command is slash-accessible or executable.
- Existing CI compiles sources, runs pytest, loads extensions, and grep-rejects selected legacy persistence tokens, but extension loading does not execute the full runtime command surface.
- A concrete runtime defect already exists in quick.py: /calc discards the GameScope value and then references scope when computing the effective market multiplier.
- The repository still contains explicit legacy migration infrastructure and world-mode compatibility behavior. These may be legitimate compatibility paths and must be traced before removal.
- Large modules such as setup.py, profile_signatures.py, and sesh.py contain substantial behavior and asynchronous task ownership, making them high-priority conflict/race audit areas.

## Architecture / Execution Path
1. discloud.config launches main.py under Python 3.11.
2. main.py builds and verifies the scoped Supabase backend before connecting Discord.
3. GAME_EXTENSIONS load into a single commands.Bot instance.
4. IdleGrowBot.setup_hook() publishes the local application-command tree globally.
5. on_ready sets presence only; it does not own command registration.
6. tasks.py starts game_cycle, notification_check, and status_cycle through cog_load().
7. ScopedDatabaseManager owns lazy record caching, dirty tracking, periodic flush, and shutdown flush.
8. Feature cogs resolve game scope through world_modes.py and then read/write scoped profiles/worlds.

## Audit Rules
- One authoritative implementation per behavior.
- Do not delete code merely because it appears old; verify callers, persistence impact, config/dynamic usage, tests, and compatibility first.
- Prefer repairing/consolidating existing behavior over adding guards, fallbacks, duplicate handlers, or replacement systems.
- Runtime behavior outranks static source-contract tests.
- No unrelated redesign while a defect/ownership question is unresolved.
- Preserve unrelated user work and existing production data semantics unless an intentional migration is proven necessary.

## Validation Required Before Completion
- Every production module compiles.
- Full pytest passes on the exact final head.
- All extensions load together.
- Complete command inventory is generated from the real bot tree and compared with intended help/setup surfaces.
- Representative command callbacks from every subsystem execute against controlled runtime fixtures.
- Known failure paths and permission/context handling are exercised.
- Persistence read/write/flush/retry and scope isolation behavior are tested.
- Background task lifecycle and reconnect behavior are tested.
- Async tasks/views/listeners in profile signatures, sesh, setup, and tasks receive focused lifecycle/race review.
- Legacy/duplicate code removals have reference checks and regression coverage.
- Final diff contains no unrelated changes, secrets, temporary scripts, generated junk, conflict artifacts, or abandoned compatibility layers.
- Exact final head receives CI and deployment/runtime validation.

## Phase 2 Checkpoint: Persistence Flush Correctness
Validated on exact head 6075976ec969da74b2d3e04389597442386ed742 with CI run 693 successful.

Root cause:
- ScopedRecordStore.flush() snapshotted dirty records, awaited backend I/O, then blindly cleared every snapshotted dirty key.
- A newer mutation to the same cached record during that await could call mark_dirty(), but because the key was already in the dirty set, the older flush later removed the only dirty marker.
- The newer in-memory state could therefore remain unsaved indefinitely until another mutation happened to mark it dirty again.

Completed:
- Added per-cache-record mutation versions.
- Every dirty mark advances the record version.
- Flush captures the version alongside each saved snapshot.
- A successful older write clears a dirty key only when its version is unchanged.
- Failed writes preserve dirty state exactly as before.
- Eviction cleans the associated version state.
- Added a deterministic blocked-backend concurrency regression proving v1 can save while v2 remains dirty and is persisted by the next flush.

Cleanup:
- No second persistence implementation or network-wide gameplay lock was added.
- Existing flush serialization remains authoritative.
- Change is limited to persistence_store.py and its focused tests.

## Phase 2 Checkpoint: Completed Legacy Migration Cleanup
Validated on exact head e4371540643a443c37800fae21b98eaf1a4a5e1b with CI run 698 successful.

Evidence:
- Git history commit 64bc1404e14511acca32afd79b521d07ef5bc73b records the successful production migration: 39 legacy profiles copied, 39 scoped profiles verified, zero profile mismatches, scoped world present, zero world mismatches.
- Runtime code has no references to legacy Supabase users/world tables.
- The old tables are referenced only by the completed one-time migration tool.
- world_modes.py legacy compatibility remains runtime-active and is covered by tests; it protects guilds whose stored world predates world_mode_config.

Removed as completed scaffolding:
- tools/migrate_legacy_global_data.py
- .github/workflows/migrate-legacy-data.yml
- tests/test_legacy_global_migration.py
- tests/test_legacy_migration_workflow_contract.py

Preserved:
- production scoped migrations and schema verification
- runtime legacy world-mode compatibility
- legacy Supabase data itself; repository cleanup does not delete rollback data

## Phase 2 Checkpoint: Atomic Cross-Record Persistence
Validated on exact head 5cd54dcea66a99955fdcc91797010c62d47ddf90 with CI run 705 successful.

Root cause:
- SupabaseScopedBackend.save_many() grouped dirty records by table and executed one upsert request per table.
- One logical game action can dirty both a profile and world state, such as auction listing or crew creation.
- A failure between table requests could persist only half of that logical action.

Completed:
- Added migration 003_atomic_scoped_record_batch.sql.
- Added one PostgreSQL function, idle_grow_save_scoped_records, that upserts global accounts, guild profiles, and guild worlds inside one database transaction.
- SupabaseScopedBackend now sends one RPC per dirty flush instead of separate table writes.
- Schema verification requires migration 003 and verifies the atomic RPC is callable.
- Added backend tests proving a mixed account/profile/world batch produces exactly one RPC.
- Added migration contract coverage for transaction framing, all three upserts, permissions, and schema version.

Deployment blocker:
- Production Supabase must apply migrations/003_atomic_scoped_record_batch.sql before deploying this branch. The bot intentionally refuses startup against schema version 002.

Scalability risk retained for later architecture work:
- ScopedRecordStore caches every loaded mutable record for process lifetime.
- Safe eviction cannot be added naively because callers hold live mutable record references across awaits; eviction could orphan an active object before mark_dirty().
- No heuristic LRU/TTL eviction was added during this correctness phase.

## Phase 3 Checkpoint: Background and Async Lifecycle Reliability
Validated on exact head 36285d1e99df22858716f4bbdf65e68bec2b8f48 with CI run 717 successful.

Root causes:
- Scheduled Discord loops could still allow unexpected top-level exceptions to escape. One loop could terminate while unrelated loops continued, producing a misleading half-working bot.
- Notification delivery committed ready flags outside the per-user failure boundary, so a commit error could abort the rest of that notification iteration.
- Profile-signature privacy cleanup spawned detached tasks that were not owned or cancelled by cog unload.
- Profile-signature startup reconciliation used one global boolean set before work completed; a transient per-guild failure was never retried on reconnect.
- Sesh private-room cleanup could surface unhandled detached-task exceptions.
- Sesh restart reconciliation attempted each guild once and then ended permanently, leaving stale descriptors/rooms after transient startup failures.

Completed:
- Wrapped each scheduled game/notification/status iteration in an exception boundary that logs the failure and preserves future iterations.
- Isolated Open World routing failures so local world processing continues.
- Moved notification flag commits inside the per-user failure boundary.
- Added owned profile-signature cleanup task tracking and cancellation on cog unload.
- Replaced one-shot profile reconciliation with per-guild successful reconciliation tracking and reconnect retry behavior.
- Added guild-join reconciliation for profile signatures.
- Contained private Sesh cleanup failures.
- Added bounded Sesh restart reconciliation retries for only failed guilds.
- Added behavioral async lifecycle tests for scheduled-loop containment, cleanup cancellation, profile reconnect retry, private Sesh cleanup failure containment, and Sesh restart retry behavior.
- Replaced obsolete source-shape assertions with direct Open World single-processing assertions.

Cleanup:
- No watchdog process, duplicate scheduler, or second reconciliation system was added.
- Existing discord.py cog/task ownership remains authoritative.
- Obsolete open_world_processed scaffolding was removed rather than retained for tests.

## Cleanup / Conflict Review
Pending. Every affected subsystem will be checked after its behavioral audit for obsolete, duplicate, conflicting, partial, temporary, and superseded logic.

## Blockers / Risks
- GitHub source and CI are available, but live Discloud runtime logs/deployed file fingerprint are not yet attached to this conversation. Production deployment state must be validated before claiming the live incident resolved.
- Existing tests contain many source-text contracts, so a green suite alone is not sufficient evidence of runtime correctness.

## Backlog Within This Master Audit
- Resolve slash/hybrid versus prefix-only command ownership and advertised UX.
- Fix /calc undefined scope through the authoritative quick-command path with runtime regression coverage.
- Audit all commands for equivalent runtime-only failures.
- Audit setup/profile-signature/sesh async lifecycle and duplicated ownership.
- Determine whether legacy migration workflow/tooling is still required or is completed residue.
- Determine whether legacy world-mode compatibility remains necessary for production data.
- Expand CI from mostly structural contracts toward behavioral command/runtime coverage.
- Validate the deployed Discloud revision and startup command-sync output.

## Git State
- Base: main @ af81d32378afdc46a6da9915b06985d8777d0f79
- Audit branch: fix/idle-grow-master-audit
- No open PR at audit start.

## Next Step
Audit real command callbacks and their error paths across farming, economy, progression, lab, crime, gambling, social, setup, and optional systems. Add runtime coverage where static command/tree contracts currently provide false confidence.
