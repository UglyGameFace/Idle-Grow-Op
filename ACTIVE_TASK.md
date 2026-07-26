# Active Task: Restore the Public Slash-Command Surface

## Scope
Fix the live bot showing only stale `/sesh_setup` by publishing the complete canonical application-command tree automatically during the native Discord.py startup lifecycle.

## Root Cause and Confirmed Findings
- All current extensions load before `bot.start()` and register their hybrid/slash commands in the local command tree.
- `main.py` never called `bot.tree.sync()` during startup.
- The only existing sync path was the hidden owner-only prefix command `!sync` in `admin.py`.
- Discord therefore kept the previously published global command set even when newer commands existed in Python.
- `/sesh_setup` is not present in the current source command surface; it is an orphaned remote command from an older deployment.
- A successful global `CommandTree.sync()` bulk-replaces the remote global command set, publishing current commands and removing stale ones.

## Architecture Decision
- Use a real `commands.Bot` subclass and its native `setup_hook`; do not monkey patch the bot or sync from `on_ready`.
- Keep extension loading before `bot.start()` so the complete command tree exists before `setup_hook` runs.
- Sync global application commands once per process startup, not on every reconnect.
- Retry brief Discord HTTP failures a small bounded number of times.
- Refuse startup if synchronization ultimately fails, returns no commands, omits required public entry points, or somehow retains stale `/sesh_setup`.
- Keep owner-only `!sync` as a manual repair command, not the normal deployment path.
- Add no environment toggle, guild IDs, compatibility shim, or second registration system.

## Required Public Entry Points
- `/setup`
- `/start`
- `/help`
- `/notifications`
- `/world-mode`

## Implementation Status
Completed:
- Added `IdleGrowBot.setup_hook()` using Discord.py's native one-time startup lifecycle.
- Added one canonical global sync path after all extensions load and before the gateway connection starts.
- Added three bounded sync attempts with short backoff for Discord HTTP failures.
- Added local-tree validation before publication.
- Added remote-result validation after publication.
- Added a hard startup failure for empty, incomplete, failed, or stale command publication.
- Kept `!sync` as an owner-only manual repair path.
- Kept `on_ready` free of repeated command synchronization.

## Validation Status
Completed:
- Successful one-pass publication test.
- Temporary HTTP failure retry test.
- Final failure blocks startup test.
- Native `setup_hook` invocation test.
- Full extension-load test proving `/setup`, `/start`, `/help`, `/notifications`, and `/world-mode` are registered locally.
- Full extension-load test proving `/sesh_setup` is absent.
- Startup-order and no-`on_ready`-sync contracts.
- Full CI run 647 passed, including Python compilation, complete pytest, command uniqueness, cleanup checks, and every Enterprise extension loading together.
- Final exact-head CI on this status commit remains the merge gate.

## Cleanup Status
- No temporary workflow, startup guard module, environment variable, hardcoded guild ID, or compatibility shim.
- No second registration system.
- Final diff contains only `main.py`, focused tests, and this task record.

## Blockers
- None.

## Deployment Note
- After merge, Discloud must fetch the new `main` commit and restart the process.
- Startup will publish the canonical global command set and remove orphaned `/sesh_setup`.
- Discord's global command cache may still need a short propagation window after the successful startup sync.
