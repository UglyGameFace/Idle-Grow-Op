# Active Task: First-Run Onboarding and Help

## Scope
Give brand-new players a simple, truthful path into Idle Grow and give returning players a useful command guide without unsolicited DMs, automatic channel posts, destructive profile changes, or another setup system.

## Root Cause and Confirmed Findings
- The built-in help command was disabled and no replacement `/help` command existed.
- Startup presence and several error messages still directed players to `!help`, which did nothing.
- New profiles start with **$500**, three empty pots, no seeds, no plants, and Level 1 access to Schwag and Mexican Brick.
- The cheapest safe first action is buying a **Schwag Seed for $15**.
- Schwag's base grow time is five minutes before weather and other modifiers.
- The real starter loop is `/buy` → `/plant` → `/status` or `/water` → `/harvest` → `/sell`.
- `/growdaily` and `/growquests` are useful early progression actions after the first grow begins.
- Lab processing, crews, auctions, raids, and other multiplayer systems are later-stage or mode-dependent and should not clutter the first screen.
- Player Choice servers may require `/world-mode` selection before the player knows which save they are using.
- Existing high-traffic farming, lab, quick-command, and error messages still taught old prefix syntax.

## Architecture Decision
- Use one canonical `onboarding.py` extension.
- Use `/start` as a private, guild-only, active-save-aware guide that calculates the player's next useful action from real profile and world state.
- Use a real hybrid `/help` command because `help_command=None` intentionally disables discord.py's built-in help.
- Keep `/help` available to both slash and legacy prefix entry points while displaying slash syntax first.
- Use one owner-locked interactive view with focused pages: Next Step, Grow Loop, Progression, World Modes, and Server Setup.
- Do not create rewards, starter items, channels, roles, or onboarding flags merely by opening the guide.
- Do not send automatic DMs or post automatically when the bot joins a server.
- Keep manager launch guidance inside the existing `/setup` panel.
- Update only the highest-traffic stale starter messages so they point to real slash commands.

## Implementation Status
Completed:
- Added state-aware `/start` and compact `/help` interactive surfaces.
- Added next-step routing for Player Choice selection, ready flower, ready plants, completed lab work, growing/waterable plants, owned seeds, starter-seed purchase, and broke recovery.
- Added exact starter examples based on the real $500 profile and $15 Schwag Seed.
- Added active-save, wallet, plant, and flower context without mutating any record.
- Added Grow Loop, Progression, World Modes, and Server Setup guide pages.
- Registered the canonical onboarding extension through startup.
- Replaced high-traffic obsolete prefix guidance in farming, lab, quick commands, startup errors, setup, and rotating presence.
- Preserved zero timestamps and kept ready harvests ahead of watering.
- Kept all slash starter commands truthful by verifying their hybrid-command decorators.

## Validation Status
Completed:
- Focused onboarding gate: 15 tests passed.
- Runtime coverage for empty, seed-owned, growing, waterable, ready, harvested, lab-ready, broke, and Player Choice states.
- Read-only active Open World guide coverage with no dirty-profile or dirty-world writes.
- Static privacy, owner-lock, startup, command-map, setup, and stale-guidance contracts.
- Full read-only CI run 639 passed, including Python compilation, complete pytest, command uniqueness, startup contracts, cleanup checks, and every Enterprise extension loading together.
- Final exact-head CI on this status commit remains the merge gate.

## Cleanup Status
- Temporary onboarding patch script removed from the PR branch.
- Temporary write-enabled integrator removed from `main`.
- No focused-test or commit logs remain in the PR diff.
- Permanent CI remains read-only and includes `onboarding.py` in legacy-persistence inspection.
- Final diff contains only the canonical extension, focused tests, task record, and intended message/startup integrations.
- No duplicate help system, automatic join listener, migration, reward grant, or onboarding-only persistence field.

## Blockers
- None.

## Backlog Locked Behind This Task
- None. This completes the currently defined public setup and onboarding sequence.
