# Active Task: Live Profile Signatures

## Scope
Add an optional per-server Live Profile Signature system that keeps one compact bot-owned Idle Grow profile card for the latest eligible speaker in explicitly configured channels. Add user-managed gaming/social identities and privacy controls without breaking the existing `/profile` command or leaking private profile data.

## Root Cause and Confirmed Findings
- No profile-signature runtime exists; the only message listener in `social.py` handles support-service rewards in one hardcoded channel.
- The existing `/profile` command directly builds a public embed from guild profile/world data and currently exposes wealth and career statistics.
- Discord cannot attach content to another user's message. A forum-signature effect therefore requires a separate bot-owned message that is safely edited, moved, replaced, and deduplicated.
- Reposting after every message would be noisy and rate-limit prone. The runtime needs per-channel debouncing, same-speaker suppression, cooldowns, and persistent active-card state.
- Global accounts already exist and are the correct home for cross-server platform identities and default privacy choices.
- Guild profiles are the correct home for stricter per-server privacy overrides.
- Guild worlds already store server configuration and are the correct home for enabled channels, allowed fields, and active bot-card references.
- The existing top-level `/profile` slash command cannot simultaneously become an application-command group without breaking its current invocation. Private editing/privacy controls must therefore use a separate `/profile-settings` surface plus buttons from the user's own profile view.
- Several requested platforms do not have a reliable canonical public profile URL. Those identities must remain username-only rather than linking to guessed or third-party pages.
- Safe link buttons can use platform-specific emoji/labels. Exact branded button logos require application emoji assets and must have a clean portable fallback.

## Architecture Decision
- Add one canonical `profile_signatures.py` extension; do not add a second profile system or webhook impersonation path.
- Keep the existing `/profile` command and aliases intact.
- Store cross-server identities and default privacy under the global account.
- Store stricter server-only hidden fields and opt-out under the guild profile.
- Store server feature configuration and persisted active-card references in the guild world.
- Keep the feature disabled by default and require explicit channel selection through `/setup` before enabling.
- Use one card per configured channel, identified by a private footer marker and persisted message ID.
- Ignore bots, webhooks, system messages, commands, opted-out users, and users with no visible permitted fields.
- Coalesce message bursts, suppress repeated same-speaker reposts, and enforce per-channel/per-user cooldowns.
- Validate recognized URLs against platform-specific HTTPS host/path allowlists. Never allow custom arbitrary URLs behind trusted platform labels.
- Server managers may reduce the fields available in signatures, but user privacy always wins.

## Implementation Status
In progress:
- Verified PR #8 is merged into `main`.
- Created `feature/live-profile-signatures` from current `main`.
- Inspected the real message listener, profile command, scoped account/profile/world storage, setup UI, startup extension list, and command uniqueness guard.

Still required:
- Implement platform registry, safe URL normalization, identity persistence, and privacy resolution.
- Implement private `/profile-settings` editing/privacy UI.
- Implement compact signature rendering and link buttons.
- Implement debounced one-card-per-channel runtime with restart-safe persisted state.
- Add `/setup` channel, enable/disable, allowed-field, and health controls.
- Integrate user-owned edit/privacy buttons without breaking `/profile` for normal viewing.
- Add focused runtime, privacy, URL safety, setup, persistence, deduplication, and restart-cleanup tests.
- Run compilation, complete pytest, command uniqueness, all-extension loading, cleanup, and conflict inspection.

## Validation Status
- Not run for this task yet.

## Cleanup Status
- No production code has been changed yet.
- No webhook impersonation, user-message deletion, guessed third-party platform links, or duplicate setup/profile command path is planned.

## Blockers
- None currently.

## Backlog Locked Behind This Task
- Multiplayer/open-world versus solo-world controls.
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
