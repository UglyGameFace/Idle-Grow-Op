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
- Existing gameplay profiles and worlds are keyed by `guild_id`; every current command assumes one guild-local scope.
- The normalized Supabase schema already permits a reserved internal positive scope ID, so cross-server Open World can reuse the proven profile/world persistence path without adding an unreviewed parallel database system.
- Existing guilds may already contain local multiplayer profiles, crews, auctions, district ownership, and leaderboards. Those records cannot be silently reclassified, merged, or deleted.
- Shared interactions currently exist in `economy.py` (`give`, auctions, leaderboard), `social.py` (crews, crew bank, district war), and `crime.py` (crew heists, raids, stealing).
- Farming, lab, progression, gambling, profile rendering, notifications, market/weather cycles, and background settlement directly read guild-scoped profiles/worlds and must be routed through one canonical game-scope resolver rather than patched independently.
- The background world loop currently advances every connected guild world and would advance a global Open World more than once unless it is explicitly deduplicated.
- Existing notification queries are indexed by scope ID and can support Open World cleanly if the global scope is processed once and local scopes are filtered by each player’s active mode.

## Architecture Decision
- Add one canonical `world_modes.py` module that owns policy normalization, player selection, scope resolution, feature gates, dirty-record routing, and safe mode labels.
- Reserve one internal persistence scope for the shared Open World; do not create duplicate economy/profile implementations.
- Preserve current guild-local behavior as a compatibility policy for already-running servers until a manager deliberately chooses a new policy.
- New server configuration choices:
  - **Solo Grow:** server-local save; no transfers, theft, auctions, crews, crew banks, crew heists, raids, or district wars.
  - **Open World:** shared cross-server save and world; full multiplayer systems enabled.
  - **Player Choice:** each player chooses Solo Grow or Open World; saves remain separate and switching is cooldown-protected.
  - **Current Server World:** compatibility mode preserving today’s guild-local multiplayer behavior for existing progress.
- Server configuration remains in the real guild world. Player choice metadata remains in the real guild profile. Gameplay data is resolved to the guild scope for Solo/Current Server World or the reserved Open World scope for Open World.
- Mode transitions never copy or merge gameplay records. Returning to a prior mode restores that mode’s existing save.
- Solo restrictions are enforced in one shared feature-gate layer and at every interaction boundary, including checking that both participants occupy the same eligible multiplayer scope.
- Existing local auctions and crews are preserved when a server leaves Current Server World; they become dormant rather than being destroyed.

## Implementation Status
In progress:
- Verified PR #14 is merged into `main`.
- Created `feature/world-mode-controls` from current `main`.
- Inspected scoped persistence keys, Supabase tables/query indexes, default profile/world records, setup UI, world cycles, notifications, economy, crews/districts, heists/raids, stealing, farming, lab valuation, progression, AI configuration, and profile rendering dependencies.

Still required:
- Implement and unit-test canonical policy/scope resolution.
- Route all gameplay profile/world reads and dirty writes through the canonical scope without changing server configuration storage.
- Add multiplayer feature gates and same-scope participant validation.
- Add player selection controls and cooldown-safe mode switching.
- Add a simple server setup panel with compatibility-safe migration behavior and plain-language consequences.
- Deduplicate Open World background cycles, auction settlement, announcements, leaderboards, and notifications.
- Update profile/signature presentation so the displayed data and crew/world always match the target player’s active mode.
- Add focused persistence, isolation, gating, switching, background-loop, setup, command-surface, and regression tests.
- Run compilation, complete pytest, all-extension loading, command uniqueness, cleanup, review, and conflict inspection.

## Validation Status
- Not run for this task yet.

## Cleanup Status
- No production implementation has been changed yet.
- No database migration, economy copy, profile merge, or destructive conversion is planned.

## Blockers
- None currently.

## Backlog Locked Behind This Task
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
