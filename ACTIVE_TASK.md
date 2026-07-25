# Active Task: Public Server Setup — Game and Announcement Channels

## Scope
Expand the existing Discord-native `/setup` wizard so every server owner can configure a main game channel and announcement channel without copying IDs or editing deployment variables.

## Root Cause and Confirmed Findings
- Error logging was already moved to per-guild setup, but game and announcement destinations were still absent.
- A saved setting without a real consumer would be misleading, so announcement routing must be connected to the live world-cycle execution path.
- Hard-locking gameplay commands to one channel would make the bot fragile and could lock users out after permission or channel changes.
- The 15-minute world cycle changes weather frequently; announcing every routine roll would create spam.
- Discord component rows become cluttered quickly on mobile, so focused sub-panels are preferable to three simultaneous channel pickers.

## Architecture Decision
- Keep one canonical `setup.py` system.
- Store `game_channel_id` and `announcement_channel_id` in each guild world's `settings` map.
- Treat the game channel as the recommended play hub, not a command restriction.
- Route special-event and major-market announcements to the explicit announcement channel.
- Use the configured game channel only when no announcement channel was selected.
- Never fall back to a random writable channel.
- If an explicitly configured announcement channel is deleted or unhealthy, show it as unhealthy and do not silently reroute.

## Implementation Status
Completed:
- Created `feature/setup-game-announcement-channels` from current `main`.
- Added Game Channel and Announcements buttons to the existing `/setup` panel.
- Added focused private channel-selection sub-panels.
- Added existing-channel selection, current-channel selection, automatic channel creation, test delivery, and disable actions.
- Added permission-health checks and deleted-channel detection.
- Added guild-world persistence with exact dirty tracking.
- Added game-channel fallback presentation in the main setup panel.
- Connected the Tasks world cycle to configured announcement routing.
- Added event-start, event-end, and major-market-change announcement generation.
- Kept routine weather rolls silent to prevent channel spam.

Still required:
- Add direct runtime tests for event and market announcement generation.
- Run full pytest, compilation, command uniqueness, and all-extension load checks.
- Inspect the final diff for duplicate configuration paths or temporary code.
- Merge only after CI is green.

## Validation Status
- Static setup contracts updated for all three guild channel settings.
- Full CI has not yet run on this branch.

## Cleanup Status
- No hardcoded channel IDs.
- No new environment variables.
- No second setup command or compatibility layer.
- No command-channel lock.
- No random-channel fallback.
- No routine weather announcement spam.

## Blockers
- None currently.

## Backlog Locked Behind This Task
- Sesh voice-room selection and private-category setup.
- AI enable/disable and model controls.
- Multiplayer/open-world versus solo-world controls.
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
