# Active Task: Notification Preferences and Announcement Roles

## Scope
Add simple, active-save-aware player DM preferences and one optional server announcement ping role without creating another server setup path, pinging broad audiences, or breaking existing notification data.

## Root Cause and Confirmed Findings
- Ready-plant and completed-lab notifications are sent by `tasks.py` as one combined DM after active-save filtering.
- Existing profiles store `settings.notifications` as a boolean.
- Supabase's generated `has_notification_work` column casts `settings.notifications` directly to boolean, so replacing it with an object would break profile writes.
- The normalized notification-candidate query is already indexed by scope and does not require a database migration.
- Notification flags are committed only after a successful DM.
- World-event and major-market announcements already use `/setup` channel configuration with the game channel as a safe fallback.
- Open World copies one participating server's announcement route into the shared world so the shared tick runs and announces once.
- `/profile-settings` remains dedicated to public profile identity and privacy.

## Architecture Decision
- Use one canonical `notification_preferences.py` extension for preference normalization, private player UI, active-save persistence, and safe allowed-mention construction.
- Expose `/notifications` as a private, guild-only player panel for the currently active save.
- Preserve `settings.notifications` as the master boolean for database compatibility.
- Store category choices in sibling `settings.notification_categories` with `plant_ready` and `lab_ready` booleans.
- Legacy `true` means both categories enabled; legacy `false` means both disabled.
- Keep notification flags unchanged for disabled categories. Re-enabling may alert for work that is still ready and has never been delivered.
- Store the optional server role as `settings.announcement_role_id` in the real guild world.
- Keep role selection inside `/setup → Announcements`; do not add a second server setup command.
- A configured role must be a real non-`@everyone` role and mentionable by the bot.
- Real announcement sends use strict `AllowedMentions`: only the selected role may be mentioned; user, broad, and replied-user mentions remain disabled.
- Send Test never pings the announcement role.
- Open World routing synchronizes the selected server's announcement channel, game-channel fallback, and optional announcement role into the shared world once.

## Implementation Status
Completed:
- Added active-save-aware `/notifications` controls for all, plant-ready, and lab-ready DMs.
- Kept the legacy notification boolean intact and added sibling category preferences without a migration.
- Filtered disabled categories before DM composition and preserved their undelivered flags.
- Kept notification flags committing only after successful DM delivery.
- Added optional announcement-role selection and clearing inside the existing Announcements setup panel.
- Added deleted and unmentionable role health reporting.
- Added strict selected-role-only mention delivery with silent fallback.
- Prevented setup test messages from pinging any role.
- Synchronized the optional role through the one-per-tick Open World announcement route.
- Loaded the new extension through the canonical startup list.
- Kept the private preference view stable across button presses so an older timeout cannot replace newer controls.

## Validation Status
Completed:
- Legacy boolean normalization and category-toggle runtime coverage.
- Active Open World save persistence coverage.
- Category-specific snapshot and post-delivery flag coverage.
- Selected-role and silent-fallback `AllowedMentions` coverage.
- Static contracts for setup integration, database compatibility, Open World routing, and no broad pings.
- Focused integration gate: 13 tests passed.
- Full read-only CI runs 604 and 606 passed, including compilation, complete pytest, command uniqueness, cleanup checks, and every Enterprise extension loading together.
- The exact-head CI rerun on this status commit remains the final merge gate.

## Cleanup Status
- Temporary patch script removed from the PR branch.
- Temporary write-enabled integrator removed from `main`.
- Accidental focused-test log removed from the PR branch.
- Permanent CI is read-only and includes the new module in legacy-persistence checks.
- No duplicate setup path, migration, hardcoded role, `@here` fallback, or destructive profile rewrite.

## Blockers
- None.

## Backlog Locked Behind This Task
- Broader onboarding and first-run guidance.
