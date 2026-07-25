# Active Task: Notification Preferences and Announcement Roles

## Scope
Add simple, active-save-aware player DM preferences and an optional server announcement ping role without creating another server setup path, pinging broad audiences, or breaking existing notification data.

## Confirmed Current Architecture
- Ready-plant and completed-lab notifications are sent by `tasks.py` as one combined DM after active-save filtering.
- Existing profiles store a legacy `settings.notifications` boolean and notification flags are committed only after a successful DM.
- The normalized notification-candidate query is already indexed by scope and does not require a database migration.
- World-event and major-market announcements already use `/setup` channel configuration with the game channel as a safe fallback.
- Open World copies one participating server's announcement route into the shared world so the shared tick runs and announces once.
- `/profile-settings` is dedicated to public profile identity/privacy and should not become a mixed general-settings panel.
- `/setup` already has reusable channel and role-selection patterns, including rejection of `@everyone`.

## Architecture Decision
- Add one canonical `notification_preferences.py` extension for preference normalization, private player UI, announcement-role validation, and safe allowed-mention construction.
- Add `/notifications` as a private, guild-only player panel for the currently active save.
- Store preferences under the active gameplay profile's `settings.notifications` record.
- Normalize the existing boolean form without mutating on reads:
  - `true` means all, plant, and lab alerts enabled.
  - `false` means all alerts disabled.
  - new records use explicit `enabled`, `plant_ready`, and `lab_ready` booleans.
- Keep notification flags unchanged when a preference is disabled. Re-enabling may alert for work that is still ready and has never been delivered.
- Store the optional server role as `settings.announcement_role_id` in the real guild world.
- Keep role selection inside `/setup → Announcements`; do not add a second server setup command.
- A configured role must be a real non-`@everyone` role and must be mentionable by the bot.
- Announcement sends use strict `AllowedMentions`: only the selected role may be mentioned; users, `@everyone`, and replied-user mentions remain disabled.
- Send Test never pings the announcement role.
- Open World routing synchronizes the selected server's announcement channel, game-channel fallback, and optional announcement role into the shared world once.

## Required Behavior
- Player controls:
  - Toggle all DM alerts.
  - Toggle plant-ready alerts.
  - Toggle lab-batch-ready alerts.
  - Clearly show the active save being configured.
  - All responses and controls remain private.
- Server controls:
  - Select or clear one optional announcement role in the existing Announcements panel.
  - Show missing/deleted/unmentionable role health plainly.
  - Default to silent announcements when no role is configured.
  - Never ping `@everyone` or `@here`.
- Runtime:
  - Filter each notification category before composing the DM.
  - Do not mark disabled categories as notified.
  - Commit only categories actually delivered.
  - Preserve active-save and one-shared-Open-World behavior.
  - Ping the configured role only for real event/major-market announcements.

## Validation Requirements
- Preference normalization and legacy-boolean compatibility tests.
- Active-save persistence and private `/notifications` UI contracts.
- Category-specific notification snapshot/commit runtime tests.
- Announcement role selection, clearing, health, and `@everyone` rejection tests.
- Strict allowed-mention tests proving no broad or user pings.
- Open World routing tests including the role ID.
- Python compilation, complete pytest, extension loading, command uniqueness, cleanup, and conflict inspection.

## Cleanup Requirements
- No temporary patch scripts or write-enabled workflows in the final diff.
- No duplicate notification preference or announcement-role config path.
- No database migration or destructive rewrite of existing profile settings.

## Blockers
- None.

## Backlog Locked Behind This Task
- Broader onboarding and first-run guidance.
