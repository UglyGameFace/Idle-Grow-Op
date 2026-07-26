# Active Task: Restore the Public Slash-Command Surface

## Scope
Fix the live bot showing only stale `/sesh_setup` by publishing the complete canonical application-command tree automatically during the native Discord.py startup lifecycle.

## Root Cause and Confirmed Findings
- All current extensions load before `bot.start()` and register their hybrid/slash commands in the local command tree.
- `main.py` never calls `bot.tree.sync()` during startup.
- The only existing sync path is the hidden owner-only prefix command `!sync` in `admin.py`.
- Discord therefore keeps the previously published global command set even when newer commands exist in Python.
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

## Validation Requirements
- Runtime test for successful startup synchronization.
- Runtime test for bounded retry after a Discord HTTP failure.
- Runtime test proving final synchronization failure blocks startup.
- Full extension-load test proving required public commands exist locally and stale `/sesh_setup` does not.
- Static ordering test proving extensions load before `bot.start()`.
- Python compilation, complete pytest, command uniqueness, cleanup checks, and every extension loading together.

## Cleanup Requirements
- No temporary sync workflow, startup guard module, environment variable, or hardcoded guild ID.
- No repeated sync in `on_ready`.
- No duplicate command-registration path.

## Blockers
- None.

## Deployment Note
- After merge, Discloud must fetch the new `main` commit and restart the process. Startup will then publish the canonical global command set; Discord global command visibility may still take a short propagation window.
