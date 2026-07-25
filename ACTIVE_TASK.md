# Active Task: World Mode Controls

## Scope
Add safe server-owner controls for Solo Grow, shared Open World, Player Choice, and compatibility-safe Current Server World without copying, merging, resetting, or deleting existing progress.

## Locked Requirements
- Solo Grow is a real private server-local operation, not multiplayer with a different label.
- Open World is one shared cross-server economy with trading, auctions, crews, raids, territory, and global competition.
- Solo and Open World saves never mix balances, inventory, plants, crews, cooldowns, achievements, auctions, or progression.
- Player Choice uses separate saves and a seven-day switch cooldown after the first free selection.
- Existing guild-local multiplayer progress remains available through Current Server World compatibility mode.
- Solo keeps lower active grow, lab, and positive-market ceilings so it does not become the easiest or richest route.
- Setup remains simple for ordinary server owners and requires no copied IDs or environment edits.

## Implemented Architecture
- `world_modes.py` is the canonical policy, scope, feature-gate, mode-label, and dirty-record routing layer.
- Reserved persistence scope `1` stores the shared Open World using the existing normalized profile and world tables.
- Server policy remains in the real guild world; Player Choice metadata remains in the real guild profile.
- Gameplay records resolve to either the real guild scope or the reserved Open World scope.
- Mode changes never migrate gameplay data. Returning to a mode restores that mode's existing save.
- Existing guild-local crews, auctions, and progress become dormant rather than being deleted when their policy changes.

## Implemented Behavior
- Safe Solo default for new worlds and compatibility interpretation for pre-feature worlds.
- `/world-mode` player controls and `/setup` server policy controls with confirmation and plain-language consequences.
- First selection is free; later switches use a seven-day cooldown.
- Progression, farming, quick actions, owner tools, lab, gambling, Sesh XP, profiles, signatures, active-save ranks, and stale-card invalidation use the active save.
- Transfers, auctions, shared leaderboards, crews, crew banking, district wars, crew heists, raids, and theft require an eligible matching multiplayer scope.
- Solo-safe personal systems remain available: shops, production, solo heists, laundering, personal stats, and private progression.
- Shared Open World auctions, weather, market events, and world advancement run once per tick regardless of participating server count.
- Local worlds continue once per active local scope.
- Notification candidates are filtered against the player's active save before profile reads, DMs, or notification-flag writes.
- Open World member lookup spans participating guilds while sending each shared notification only once.
- One participating guild supplies safe announcement routing for the shared world.

## Completed Validation
- Phase 1 through Phase 3 compilation, focused tests, applicable full regressions, cleanup, and source pushes passed.
- Phase 4 patching, compilation, focused multiplayer contracts, 203 applicable regressions, cleanup, whitespace inspection, and source push passed.
- Phase 5 static contracts now verify full-world policy normalization, deduplicated scope construction, active-save filtering order, and one shared tick.
- Phase 5 runtime tests cover local/open policy partitioning, active Player Choice resolution, and shared routing synchronization.

## Final Validation In Progress
- Complete pytest suite, including Phase 5 and all previous regressions.
- Every Enterprise extension loading into the bot.
- Python compilation.
- Legacy persistence and backup-artifact rejection.
- Command uniqueness and startup contracts through pytest.
- Final changed-file cleanup and conflict inspection against `main`.

## Cleanup Status
- Temporary Phase 1 through Phase 5 patch scripts, wrappers, helper copies, diagnostics, shadow modules, trigger markers, and one-shot workflows are removed.
- Permanent CI is restored to read-only contents permission.
- Temporary PR #17 is closed and was not merged.
- No database migration, economy copy, profile merge, or destructive conversion exists.

## Blockers
- None currently; final validation results are pending.

## Backlog Locked Behind This Task
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
