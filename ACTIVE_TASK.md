# Active Task: World Mode Controls

## Scope
Add safe, simple server-owner controls for Solo Grow and real Open World play without mixing economies or deleting existing progress. Solo Grow stays server-local and blocks player-vs-player systems. Open World uses one shared cross-server economy/world so crews, raids, auctions, trading, territory, and leaderboards can work across participating servers. Servers may also allow players to choose between the two while keeping completely separate saves.

## User Requirements Carried Forward
- Solo Grow must be a real private operation, not merely PvP with a different label.
- Solo Grow must not become the easiest or richest path; multiplayer retains meaningful advantages.
- Open World must preserve real multiplayer systems including crews, raids, trading, auctions, and territory.
- Solo progress remains confined to the Discord server; Open World progress can follow the player across participating servers.
- Switching must never merge balances, inventories, plants, crews, auctions, cooldowns, or achievements between modes.
- Setup must be extremely simple for ordinary server owners and must not require copying IDs or editing environment variables.

## Confirmed Current Architecture
- Existing gameplay profiles and worlds are keyed by `guild_id`; every current command previously assumed one guild-local scope.
- The normalized Supabase schema permits a reserved internal positive scope ID, so cross-server Open World reuses the proven profile/world persistence path without a parallel database system.
- Existing guilds may already contain local multiplayer profiles, crews, auctions, district ownership, and leaderboards. Those records cannot be silently reclassified, merged, or deleted.
- Shared interactions exist in `economy.py` (`give`, auctions, leaderboard), `social.py` (crews, crew bank, district war), and `crime.py` (crew heists, raids, stealing).
- The background world loop currently advances every connected guild world and would advance a global Open World more than once unless explicitly deduplicated.
- Existing notification queries are indexed by scope ID and can support Open World cleanly if the global scope is processed once and local scopes are filtered by each player’s active mode.

## Architecture Decision
- Use one canonical `world_modes.py` module for policy normalization, player selection, scope resolution, feature gates, dirty-record routing, and mode labels.
- Reserve internal scope `1` for the shared Open World; do not create duplicate economy/profile implementations.
- Preserve current guild-local behavior as compatibility policy until a manager deliberately chooses another policy.
- Server choices:
  - **Solo Grow:** server-local save; no transfers, theft, auctions, crews, crew banks, crew heists, raids, district wars, or shared leaderboards.
  - **Open World:** shared cross-server save and world; full multiplayer systems enabled.
  - **Player Choice:** each player chooses Solo Grow or Open World; saves remain separate and switching is cooldown-protected.
  - **Current Server World:** compatibility mode preserving existing guild-local multiplayer progress.
- Server configuration remains in the real guild world. Player choice metadata remains in the real guild profile. Gameplay records resolve to the guild scope or reserved Open World scope.
- Mode transitions never copy or merge gameplay records. Returning to a prior mode restores that mode’s existing save.
- Existing local auctions and crews become dormant—not deleted—when a server leaves Current Server World.

## Implementation Status
Completed on the feature branch:
- Verified PR #14 is merged and created draft PR #15 from current `main`.
- Added canonical policy/scope resolver, errors, labels, dirty helpers, multiplayer gates, Solo caps, player selection, setup confirmation UI, and `/world-mode`.
- Added safe Solo defaults for newly created worlds and missing-config compatibility behavior for existing worlds.
- Added first-choice-free and seven-day switch-cooldown behavior with completely separate saves.
- Added `/setup` World Mode entry and status presentation.
- Routed progression, farming, quick commands, owner tools, and AI/help wording through the active save.
- Added non-destructive Solo grow capacity and market caps.
- Updated permanent CI persistence guards for the canonical module.
- Phase 2 passed compilation, focused tests, the complete pre-integration regression suite, cleanup, and push.

In progress:
- Phase 3 routes lab queues/valuation, all casino settlements, Sesh participant XP, and profile/signature rendering through each target player’s active save.
- The first Phase 3 run stopped before editing because the lab file contains six—not five—profile dirty writes. No failed-run production edits landed.
- The corrected Phase 3 workflow is installed as a branch-push, self-reporting runner. This task-record commit is the clean post-install trigger; on failure it publishes only an exact diagnostic log, never partial source.

Still required:
- Complete Phase 3 and remove its temporary workflow.
- Route and gate economy transfers, auctions, and leaderboards.
- Route and gate crews, crew banking, district wars, crew heists, raids, stealing, and their leaderboards.
- Deduplicate Open World cycles, auction settlement, announcements, and notifications in background jobs.
- Finish target-aware profile/signature behavior and stale-card invalidation validation.
- Make the full integration contract and all migrated persistence contracts green.
- Run compilation, complete pytest, all-extension loading, command uniqueness, cleanup, review, and conflict inspection.

## Validation Status
- Canonical resolver and isolation unit tests passed.
- Phase 1 foundation compile, focused tests, and complete existing regression suite passed.
- Phase 2 routed-source compile, focused tests, complete existing regression suite, cleanup, commit, and push passed.
- Phase 3 self-reporting validation is running from the clean post-install trigger.
- Final whole-task validation is pending.

## Cleanup Status
- Completed Phase 1 and Phase 2 temporary patch scripts/workflows were removed.
- No database migration, economy copy, profile merge, or destructive conversion exists.
- The Phase 3 patch script and workflow are temporary and must remove themselves or be deleted after a successful validated push.

## Blockers
- None currently.

## Backlog Locked Behind This Task
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
