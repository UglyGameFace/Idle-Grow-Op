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
PHASE 11 VALIDATION FOUND SLASH-LAUNCH REGRESSION — FIX IN PROGRESS

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


## Final Audit Findings
- The observed "weather works while everything else feels broken" behavior had multiple independent causes rather than one weather bug. Background cycles could continue while command publication, callback runtime, persistence, or global-lock contention failed elsewhere.
- Public gameplay command ownership is consolidated on hybrid slash + prefix callbacks. Hidden owner/admin maintenance commands remain intentionally prefix-only.
- The complete advertised public command surface is now checked recursively against the real loaded Discord command tree, including nested subcommands.
- progression_core.py is the single live progression owner; obsolete progression helpers and impossible quest/event paths were removed.
- Scoped persistence now protects concurrent dirty mutations and uses one atomic cross-record Supabase RPC contract.
- Completed legacy migration tooling was removed only after repository history proved the one-time production migration succeeded. Runtime legacy world-mode compatibility remains intentionally retained for pre-world-mode guild data.
- Shared guild, profile-signature, world-mode, and casino escrow persistence contracts have explicit dependency-free owners instead of duplicated literal schemas.
- No public gameplay module retains player-facing !command guidance or the removed /water, /tasks, /appeal, /bail, or /sesh_setup paths.
- Gameplay mutation paths no longer await Discord responses while holding the process-wide database mutation lock.
- High-risk player-value flows now have callback-level failure-path coverage: transfers, theft, auctions, owner/admin mutations, crew exit/disband, and interactive Blackjack escrow.
- Full branch comparison against the audit base is scoped to Idle Grow audit work only: the branch is ahead of the original base and not behind it.
- Source and CI evidence do not prove the deployed Discloud revision or production Supabase schema. Live production resolution remains unverified until those external states are checked.

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

## Active Task Lock
- Active task: close PR #31 through post-merge production validation of the gameplay UX and harvest-consistency overhaul.
- Idle Grow remains the only active implementation task until this Definition of Done is satisfied.
- Unrelated projects, bugs, redesigns, or cleanup are backlog-only unless explicitly force-switched.
- Scope includes exact merged-revision evidence, live command publication, /game and /shop behavior, stable harvest readiness across weather changes, legacy XP reconciliation, representative direct hub actions, cleanup, and final task-record closure.

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

## Phase 4 Checkpoint: Gameplay Progression and Command Runtime
Validated on exact head e6166da99efe4d7f6d3c3c62f794d077d203209e with CI run 723 successful.

Root causes:
- Two incompatible progression generations were live at once.
- Farming called an empty legacy achievement stub from utils.py instead of progression_core.py.
- Legacy daily-quest helpers expected a `type` field while current quests use `event`.
- XP thresholds were duplicated and /growlevel displayed a fourth conflicting formula.
- Several XP award paths could accumulate XP without applying level transitions.
- Daily quests referenced nonexistent breeding and market-contract features.
- Economy /leaderboard treated authoritative backend tuple rows as dictionaries and could crash at runtime.
- /qplant bypassed the canonical plant quest progression path.

Completed:
- Made progression_core.py the single owner of XP thresholds and level transitions.
- Routed daily, achievement, farming, lab, crime, casino, Sesh, support-reward, profile-display, and quick-plant progression through the canonical implementation.
- Wired real quest events to plant, water, harvest, collect_dabs, buy, steal, heist, raid, launder, casino_play, gamble_win, crew_deposit_cash, and Quick Plant.
- Removed impossible breed and market-contract quests from the selectable pool.
- Removed the obsolete progression tables/helpers/stub from utils.py.
- Fixed /leaderboard to consume the backend's (user_id, balance) tuple contract.
- Replaced stale AI guidance for nonexistent /tasks with /growquests.
- Added callback-level runtime regressions for leaderboard, farming, lab collection, laundering, crew deposits, casino progression, and Quick Plant.

Cleanup:
- No compatibility shim preserves the old progression implementation.
- Current progression ownership is explicit and storage-agnostic in progression_core.py.
- The old empty achievement stub and old quest schema are gone.

## Phase 5 Checkpoint: Gameplay Catalog, Grow Loop, and Configuration Contracts
Validated on exact head ddc7163257d9df965149d835b39f41cc9e515bc5 with CI run 761 successful.

Root causes:
- Weather advertised growth-speed effects but plant grow-time calculation ignored weather.
- Several shop items advertised mechanics or commands that never existed, including thirst/durability/appeal/bail/autoharvest behavior.
- Pager and Lawyer had exact advertised passive effects but no runtime implementation.
- Three selectable world events announced effects the runtime never applied.
- The original skills system left unreachable profile state and a hidden sale multiplier with no way to earn skill levels.
- Watering had never affected growth, yield, survival, or quality; it only mutated timestamps/counters and was still exposed as a command, quest, and onboarding step.
- Shared guild configuration keys were independently re-declared across setup.py, tasks.py, main.py, Sesh, and AI.

Completed:
- Applied WEATHER_TYPES growth modifiers to real plant timing.
- Removed unsupported shop placeholders and corrected live equipment descriptions.
- Prevented repeat purchases of passive equipment/tools/defenses.
- Implemented Pager's exact +20% daily cash/XP multiplier.
- Implemented Lawyer's exact -25% jail duration across solo heists, crew-heist failures, and failed robberies.
- Removed nonfunctional special events and made the remaining market events consume their authoritative declared multiplier.
- Removed dead thirst/event metadata and ownerless legacy skill state/constants.
- Removed the no-op /water command, watering quest, onboarding guidance, and unused hydration/quality fields from new plants.
- Added guild_config.py as the single owner of shared guild-world channel keys.
- Made AI and Sesh own their subsystem config keys; setup imports those contracts instead of redeclaring them.
- Updated main.py and tasks.py to consume the canonical shared guild config keys.
- Added regression coverage for weather timing, shop mechanic contracts, world-event ownership, dead legacy state, watering removal, and configuration-key ownership.

Cleanup:
- No imaginary thirst, durability, sale-speed, or skill subsystem was invented to justify legacy catalog text.
- Existing stored unknown JSON keys remain non-destructively ignored; new state no longer creates those ownerless fields.
- Configuration key strings now have explicit canonical owners instead of synchronized duplicate declarations.

## Phase 6 Checkpoint: Configuration and Persistence Contract Ownership
Validated on exact head ebae7eebd5849b9cadf1fa99e12cb3b532cf8c34 with CI run 781 successful.

Root causes:
- Shared guild channel keys were previously re-declared independently across setup, tasks, and main.
- Sesh and AI subsystem config keys were duplicated in setup instead of being consumed from their owning modules.
- Profile-signature persistence/default schema lived inside the Discord runtime module while persistence and setup needed the same contract.
- The database hardcoded world-mode defaults instead of using the world-mode owner.
- The reserved Open World scope ID and world settings key had duplicate ownership.
- Sesh config reads used setdefault(), mutating world state during a read-only operation.

Completed:
- Added guild_config.py as the pure owner of shared guild-world setting keys.
- Added profile_signature_contracts.py as the Discord-free owner of signature/privacy persistence schema and default builders.
- Added world_mode_contracts.py as the Discord-free owner of world-mode persistence defaults and routing identifiers.
- Routed setup, runtime cogs, tasks, main, and scoped_database through those canonical contracts.
- Made persistence defaults consume canonical world-mode, profile-signature, Open World scope, and guild-settings contracts.
- Made Sesh config reads side-effect free while preserving explicit mutation/dirty tracking on real writes.
- Added runtime/default/ownership regression coverage and linted the extracted contract modules.

Cleanup:
- Setup remains the Discord UI front end, not a second schema owner.
- No persistence module imports Discord UI code.
- Runtime modules may re-export imported constants for compatibility, but the literal definitions now have one source of truth.

## Phase 7 Checkpoint: Global Mutation Lock Reliability
Validated on exact head 4ebab6c237949cd3221b573efb3dd100812fd102 with CI run 808 successful.

Root cause:
- Gameplay modules shared one global database mutation lock.
- Multiple commands performed Discord response awaits while holding that lock.
- A slow Discord API response in one command/server could therefore block unrelated state mutations across the process.

Completed:
- Moved Discord response delivery outside the database lock for economy transfers, purchases, sales, auctions, heists, crew-heists, crime failures, crew management, and turf-war paths.
- Preserved validation and all state mutation under the lock.
- Removed a duplicated auction mutation block found during the refactor.
- Added runtime auction coverage for buyout atomicity, seller-load failure safety, and first-bid starting-price behavior.
- Tightened bid validation so the first bidder may meet the listing start price while later bids must increase it.
- Re-scanned gameplay modules after the refactor and found no remaining Discord/network response awaits inside self.bot.db.lock blocks.

Cleanup:
- The global mutation lock remains authoritative for state serialization.
- No lock was removed from mutation code; only external/network awaits were moved out.
- Intermediate CI failures from the staged refactor are resolved; exact head is green.

## Phase 8 Checkpoint: High-Risk Value Flows and Player Exit Paths
Validated on exact head bdf511a348fd2702570468af474f6b98ba14bece with CI run 826 successful.

Root causes:
- Auction buyout could mutate bidder state before all participant profiles were successfully loaded.
- The first auction bidder could not meet the listed starting price because all bids were forced strictly above current_bid.
- Admin !wipeuser reset non-game control metadata such as notification settings, signature privacy, and world-mode selection.
- Crew users were told to leave before joining another crew, but no crew-leave command existed.
- New/unowned districts stored a +10% multiplier and /district could advertise a bonus when no active owner existed.
- Interactive Blackjack deducted and dirtied a wager before message creation and had no crash/reload recovery state.

Completed:
- Preloaded auction participants before mutation and added buyout/expiry atomicity regressions.
- Allowed the first bid to meet the starting price while preserving strict increases for later bids.
- Added callback-level owner/admin mutation tests.
- Added a canonical gameplay reset helper that preserves profile control/privacy preferences.
- Added callback-level cross-player conservation tests for /give and /steal, including prerequisite-load and poor-target failure paths.
- Added /crew leave with member exit, owner handoff, stale-membership repair, last-member disband, crew-bank conservation, and district cleanup.
- Neutralized unowned district defaults and only display district bonuses while ownership is active.
- Added persistent Blackjack escrow with stale recovery, timeout refund, send-failure refund, and double-settlement protection.
- Added casino_contracts.py and lint/runtime coverage for the escrow contract.

Cleanup:
- Existing active game state and user preferences are preserved through admin gameplay resets.
- Crew users now have a complete join/leave lifecycle instead of a one-way membership trap.
- Interactive casino money can survive message failure, extension reload, or process crash without silently disappearing.

## Phase 9 Checkpoint: Command, Help, and UI Surface Consistency
Validated on exact head 05971e806fb16382ee7084bec97163714237c918 with CI run 828 successful.

Root causes:
- Player-facing command copy had historically drifted from the loaded command tree.
- Nested command paths were not covered by the original top-level sync/runtime contract.
- Previous residue included impossible guidance such as prefix-only/public mismatches and missing command paths.

Completed:
- Added recursive loaded-tree validation for the full advertised public command surface.
- Covered nested paths including /auction list, /crew create, /crew join, /crew leave, /crew info, /crew deposit, /crew war, and /seshconfig disable.
- Explicitly guarded removed/nonexistent public paths including /water, /tasks, /appeal, /bail, and /sesh_setup.
- Re-scanned player-facing source copy for stale prefix-only guidance and removed command names.
- Verified no current player-facing !command residue remains in audited public modules.

Cleanup:
- User-facing slash guidance now has a direct loaded-tree contract instead of relying on decorator/source-text assumptions.
- Removed command names are protected from accidental reintroduction into the published command tree.

## Phase 10 Checkpoint: Supabase Egress Hardening
Validated on exact head 43e1d2ffb3632844dc3cd449fddec269397a203c with CI run 851 successful.

Observed production concern:
- Supabase organization usage showed prior-cycle egress overage and current-cycle egress already materially consumed.
- The Idle Grow notification loop previously issued one Supabase candidate query per active scope every two minutes.
- At large guild counts, request fan-out scales with guild count even when most scopes have no actionable notifications.

Completed:
- Added migration 004_batched_notification_candidates.sql.
- Added an additive generated column, has_pending_notification_work, that respects global and per-category notification preferences and excludes already-notified work.
- Added an indexed batched RPC, idle_grow_list_notification_candidates(bigint[]), returning only guild_id/user_id pairs for active scopes.
- Replaced per-guild notification candidate reads with one batched scope query.
- Added an in-memory notification candidate set in ScopedDatabaseManager.
- Candidate scopes are primed from Supabase only once per process lifetime; subsequent two-minute scans reuse memory.
- Profile loads and every dirty profile mutation keep the candidate set synchronized locally.
- Cached profile state wins over stale database prime rows, preventing a mutation-vs-prime race.
- Notification world records are loaded lazily only for scopes that actually have candidates.
- Added schema, backend, task-loop, and manager runtime regressions proving batching and no-repeat reads after prime.

Deployment requirement:
- Production Supabase must apply migrations/004_batched_notification_candidates.sql after migration 003 and before deploying this exact audited head.

## Phase 11 Follow-up: Gameplay UX Overhaul and Harvest Consistency

Production baseline:
- Master audit PR #30 is merged to main at 52aef9cff0662946d0a6b2327a670e48c6034093.
- Production Supabase migrations 003 and 004 were applied successfully.
- Live Discloud startup verified schema 004, all audited extensions, global command sync, and guild-scoped Supabase.

Root causes addressed in PR #31:
- Plant readiness was recalculated against current weather, allowing a crop to become ready and later appear unready after weather changed.
- /shop was a static catalog and required players to remember /buy item names.
- Player-facing help surfaces still treated dozens of slash commands as the primary game interface.
- Legacy stored progression could contain XP above the current level threshold, producing impossible displays such as 9,802/8,944 XP.

Completed:
- Added plant_lifecycle.py as the canonical owner of fixed plant ready_at timing.
- New plants snapshot weather/equipment growth modifiers once at planting; all readiness consumers share the same helper.
- Legacy plants use a deterministic weather-independent fallback so readiness never moves backward.
- Converted /shop into an interactive category/item/purchase panel using the same Economy purchase path as /buy.
- Added game_hub.py and /game (/menu, /play) as the private all-in-one player command center.
- Added Home, Grow, Inventory, Market, Lab, Crime, Progress, Social, Casino, and Settings pages.
- Added one-tap recommended next move without silent spending.
- Added direct seed planting, harvesting, selling, lab processing, lab collection, auctions, bidding, listing, heists, robbery target selection, laundering, crew lifecycle actions, progression controls, notification/settings panels, and adaptive casino game launch.
- Hub actions invoke existing commands through an explicit safe allowlist with their existing checks, cooldowns, persistence, and error reporting.
- Added state-aware disabled controls so unavailable actions are not presented as live buttons.
- Added timeout cleanup so expired Shop and Game panels visibly disable their controls.
- Reworked onboarding, setup, farming, lab, crew, and AI guidance to lead with /game while retaining slash commands as optional shortcuts.
- Added canonical reconcile_level_xp() and first-load persistence repair for legacy XP overflow without dirtifying unrelated partial records.
- Added regression coverage for stable readiness, shop purchases, game-hub state, direct controls, casino selection, Keno wager disambiguation, and legacy XP repair.

Validation:
- Repeated PR CI checkpoints are green through the direct hub, casino, guidance, and timeout work.
- Exact gameplay UX code/test head 5948e859f87f573f29ae0ad513d7316b64972e87 passed PR CI run 892.

## Phase 11 Validation Finding: Slash Launch Aliases

Root cause:
- PR #31 declared `@commands.hybrid_command(name="game", aliases=["menu", "play"])`.
- In discord.py, a HybridCommand constructs one application command using the wrapped command's single `name`; `aliases` belong to the text-command command map and do not create additional slash commands.
- The loaded application-command tree regression only advertised `game`, so CI could pass while the task record incorrectly claimed `/menu` and `/play` existed.

Required fix:
- Register `game`, `menu`, and `play` as distinct hybrid commands that delegate to one shared hub-send implementation.
- Add `menu` and `play` to the real loaded application-command tree contract so this cannot regress silently.
- Preserve the single authoritative Game Hub implementation; do not duplicate gameplay or persistence behavior.

## Current Follow-up Next Step
PR #31 is already merged to main at `4e9a100335e933efed3a570f058b7bc000632059`. Its exact source head `270c7e9a03173f550293368bdfdb268bcbe27e73` passed CI, and GitHub reports `discloud/commit` success for the merge commit. Continue with live Discord validation only: confirm the deployed bot publishes /game, /menu, /play, and /shop; exercise the interactive panels; verify a planted crop remains ready across a weather change; verify one legacy XP-overflow profile reconciles and persists correctly; and exercise representative direct hub actions before closing Phase 11.

## Cleanup / Conflict Review
COMPLETE for repository source and CI scope.

Verified:
- Full branch comparison against base af81d32378afdc46a6da9915b06985d8777d0f79 shows only audit-related production, migration, contract, test, and audit-document changes.
- Completed one-time migration workflow/tooling is removed; runtime legacy world-mode compatibility is intentionally retained.
- Obsolete persistence-context wrappers, dead progression/game constants, ownerless skill state, fake watering behavior, unsupported catalog entries, and nonfunctional special events are removed.
- Temporary Sesh channel markers/cleanup paths are intentional live lifecycle behavior, not abandoned scaffolding.
- Remaining bare pass statements are limited to intentional best-effort exception suppression or asyncio cancellation handling.
- Ruff now rejects unused imports/locals and undefined runtime names across production modules.
- No unrelated repository, generated artifact, secret file, local database, backup file, or conflict artifact was introduced by the audit.

## Blockers / Risks
- **LIVE VALIDATION BLOCKER:** The connected GitHub tooling exposes Discloud's successful commit deployment status but not the authenticated Discloud startup log or a live Discord client session. Source/CI evidence therefore cannot by itself prove the new interactions work in the deployed guild.
- ScopedRecordStore still caches every loaded mutable record for process lifetime. Naive LRU/TTL eviction is unsafe because callers retain live mutable references across awaits; this remains a scalability architecture item rather than a correctness patch.
- Runtime legacy world-mode compatibility is intentionally retained until production data can prove no pre-world-mode guild records remain.

## Backlog Within This Master Audit
Repository/source audit work is complete. Production Supabase migrations 003 and 004 were already applied before PR #31. Remaining Phase 11 closure work is live behavior validation:
- confirm the deployed bot exposes /game, /menu, /play, and the interactive /shop
- verify stable harvest readiness across a real weather change
- verify one legacy XP-overflow profile reconciles and persists correctly
- exercise representative direct game-hub actions across Grow, Lab, Market, Crime, Social/Crew, and Casino
- capture live startup/command evidence when available before marking Phase 11 complete
- treat mutable-record cache eviction/scalability as a separate follow-up architecture task after production correctness is verified

## Git State
- PR #31 gameplay merge commit: `4e9a100335e933efed3a570f058b7bc000632059`.
- PR #31 source head: `270c7e9a03173f550293368bdfdb268bcbe27e73`.
- Exact PR #31 source head CI: successful.
- PR #31 gameplay merge-commit Discloud status: successful.
- PR #32 merged the post-merge task-state correction; subsequent documentation-only commits do not change the validated PR #31 gameplay revision.

## Next Step
Finish and validate the /menu and /play slash-publication fix, deploy it, then resume the remaining live Discord/Discloud validation checklist for PR #31. Do not start another project or unrelated Idle Grow redesign before this Phase 11 closure task is either completed or explicitly force-switched.
