# Active Task: World Mode Controls

## Scope
Add safe server-owner controls for Solo Grow, shared Open World, Player Choice, and compatibility-safe Current Server World without copying, merging, resetting, or deleting existing progress.

## Locked Requirements
- Solo Grow is a real private server-local operation, not multiplayer with a different label.
- Open World is one shared cross-server economy with trading, auctions, crews, raids, territory, and global competition.
- Solo and Open World saves never mix balances, inventory, plants, crews, cooldowns, achievements, auctions, or progression.
- Player Choice uses separate saves and a seven-day switch cooldown after the first free selection.
- Existing guild-local multiplayer progress remains available through Current Server World compatibility mode.
- Solo keeps lower active grow/lab/market ceilings so it does not become the easiest or richest route.
- Setup must remain simple for ordinary server owners and require no copied IDs or environment edits.

## Architecture
- `world_modes.py` is the canonical policy, scope, feature-gate, mode-label, and dirty-record routing layer.
- Reserved persistence scope `1` stores the shared Open World using the existing normalized profile/world tables.
- Server policy stays in the real guild world; Player Choice metadata stays in the real guild profile.
- Gameplay records resolve to either the real guild scope or the reserved Open World scope.
- Mode changes never migrate gameplay data. Returning to a mode restores that mode's existing save.

## Completed
- Canonical policy and scope resolver.
- Safe Solo default for new worlds and compatibility interpretation for older worlds.
- `/world-mode` player controls and `/setup` server policy controls with confirmation and plain-language consequences.
- First selection free; later switches cooldown-protected.
- Progression, farming, quick actions, owner tools, lab, gambling, Sesh XP, profiles, signatures, active-save ranks, and stale-card invalidation routed through the correct save.
- Phase 1 through Phase 3 compilation, focused tests, applicable full regressions, cleanup, and source pushes passed.
- Removed temporary Python shadow modules and obsolete Phase 3 bridge code that could interfere with standard-library imports.

## In Progress: Phase 4
Route and gate all shared multiplayer value paths:
- Player transfers.
- Auctions and settlement.
- Shared leaderboards.
- Crews and crew banking.
- District ownership and wars.
- Crew heists and joining sessions.
- Crew raids.
- Player theft.

Solo-safe personal systems remain usable: shops, production, solo heists, laundering, personal stats, and private progression.

The Phase 4 implementation applies, compiles, and passes its focused contracts. The first broader regression was an overbroad legacy guard matching Discord cache calls; generated leaderboard and crew-owner fallbacks now use the current guild member or a stable `User <id>` label instead.

## Still Required
- Pass the complete pre-background regression suite and publish/clean Phase 4.
- Deduplicate Open World background cycles, auction settlement, announcements, and notifications.
- Filter notification candidates by each player's active save and resolve Open World members across participating guilds.
- Remove all remaining temporary workflows, scripts, triggers, diagnostics, and markers.
- Restore permanent read-only CI.
- Run complete pytest, extension loading, command uniqueness, static compilation, whitespace checks, cleanup inspection, conflict inspection, and final review.

## Validation Status
- Phase 4 patch application: passed.
- Phase 4 source compilation: passed.
- Focused Phase 4 contracts: passed.
- Legacy persistence cache-call regression: corrected.
- Complete pre-background regression suite: rerunning now.

## Blockers
- None.

## Backlog Locked Behind This Task
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
