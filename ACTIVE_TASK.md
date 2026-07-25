# Active Task: First-Run Onboarding and Help

## Scope
Give brand-new players a simple, truthful path into Idle Grow and give returning players a useful command guide without unsolicited DMs, automatic channel posts, destructive profile changes, or another setup system.

## Root Cause and Confirmed Findings
- The built-in help command is disabled and no replacement `/help` command exists.
- Startup presence and several error messages still direct players to `!help`, which currently does nothing.
- New profiles start with **$500**, three empty pots, no seeds, no plants, and Level 1 access to Schwag and Mexican Brick.
- The cheapest safe first action is buying a **Schwag Seed for $15**.
- Schwag's base grow time is five minutes before weather and other modifiers.
- The real starter loop is `/buy` → `/plant` → `/status` or `/water` → `/harvest` → `/sell`.
- `/growdaily` and `/growquests` are useful early progression actions after the first grow begins.
- Lab processing, crews, auctions, raids, and other multiplayer systems are later-stage or mode-dependent and should not clutter the first screen.
- Player Choice servers may require `/world-mode` selection before the player knows which save they are using.
- Existing high-traffic farming, lab, quick-command, and error messages still teach old prefix syntax.

## Architecture Decision
- Add one canonical `onboarding.py` extension.
- Add `/start` as a private, guild-only, active-save-aware guide that calculates the player's next useful action from their real profile and world state.
- Add a real hybrid `/help` command because `help_command=None` intentionally disables discord.py's built-in help.
- Keep `/help` useful as both slash and legacy prefix entry points, but display slash syntax first.
- Use one owner-locked interactive view with focused pages: Next Step, Grow Loop, Progression, World Modes, and Server Setup.
- Do not create rewards, starter items, channels, roles, or onboarding flags merely by opening the guide.
- Do not send automatic DMs or post automatically when the bot joins a server.
- Managers may use the existing `/setup` panel to see how players launch `/start` and `/help`; do not add another setup command.
- Update only the highest-traffic stale starter messages so they point to real slash commands.

## Required Behavior
- `/start` must:
  - remain private for slash-command use;
  - show the active save and current wallet;
  - identify the next action from actual seeds, plants, readiness, flower stash, and world-mode policy;
  - use exact valid examples such as `/buy item_name:schwag seed` and `/plant strain_name:schwag`;
  - explain that weather can change grow time and sale value;
  - never mutate profile or world data.
- `/help` must:
  - provide a compact command map rather than dumping every alias;
  - separate core grow, economy, progression, multiplayer, utility, and manager commands;
  - clearly label mode-dependent systems;
  - link players back to `/start` for a tailored next step.
- Starter-message cleanup must replace nonexistent or misleading `!help`, `!shop`, `!plant`, `!status`, `!harvest`, `!process`, and `!collect` guidance where new players are most likely to encounter it.

## Validation Requirements
- Runtime tests for next-step selection across empty, seed-owned, growing, ready, harvested, and Player Choice states.
- Tests proving `/start` reads without marking records dirty.
- Owner-lock and private-response contracts.
- Command-surface uniqueness for `/help` and `/start`.
- Static contracts preventing stale starter guidance from returning.
- Python compilation, complete pytest, every extension loading together, cleanup checks, and final conflict inspection.

## Cleanup Requirements
- No temporary patch scripts or write-enabled workflows in the final diff.
- No duplicate help/onboarding extension or automatic join-message listener.
- No database migration or onboarding-only persistence field unless a real runtime requirement is proven.

## Blockers
- None.

## Backlog Locked Behind This Task
- None. This is the final currently defined public setup/onboarding slice.
