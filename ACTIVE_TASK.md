# Active Task: Live Profile Signatures

## Scope
Add an optional per-server Live Profile Signature system that keeps one compact bot-owned Idle Grow profile card for the latest eligible speaker in explicitly configured channels. Add user-managed gaming/social identities and privacy controls without breaking the existing `/profile` command or leaking private profile data.

## Root Cause and Confirmed Findings
- No profile-signature runtime existed; the only prior message listener in `social.py` handled support-service rewards in one fixed channel.
- The existing `/profile` command directly built a public embed from guild profile/world data and exposed fields without user-level visibility controls.
- Discord cannot attach content to another user's message. A forum-signature effect therefore requires a separate bot-owned message that is safely moved, replaced, and deduplicated.
- Reposting after every message would be noisy and rate-limit prone. The runtime requires channel debouncing, same-speaker suppression, per-channel/per-user cooldowns, and persistent active-card state.
- Global accounts are the correct home for cross-server platform identities and default privacy choices.
- Guild profiles are the correct home for stricter per-server privacy overrides.
- Guild worlds are the correct home for server configuration and active bot-card references.
- The existing top-level `/profile` slash command cannot also become an application-command group without breaking its current invocation. Private editing/privacy controls therefore use `/profile-settings` plus an owner-only button on the existing profile view.
- Several requested platforms do not have a reliable canonical public profile URL. Those identities remain username-only rather than using guessed or third-party links.
- Discord link buttons require Unicode or uploaded application emoji. The runtime supports safe portable fallbacks plus host-configured application emoji for exact branded logos.

## Architecture Decision
- Use one canonical `profile_signatures.py` extension; no second profile system and no webhook impersonation path.
- Keep the existing `/profile` command and aliases intact.
- Store cross-server identities and default privacy under the global account.
- Store stricter server-only hidden fields and opt-out under the guild profile.
- Store server feature configuration and persisted active-card references in the guild world.
- Keep the feature disabled by default and require explicit channel selection through `/setup` before enabling.
- Use one card per configured channel, identified by a private footer marker and persisted message ID.
- Ignore bots, webhooks, system messages, commands, opted-out users, and users with no visible permitted fields.
- Coalesce message bursts, suppress repeated same-speaker reposts, and enforce per-channel/per-user cooldowns.
- Validate recognized URLs against platform-specific HTTPS host/path allowlists. Never allow arbitrary custom links behind trusted platform labels.
- Server managers may reduce the fields available in signatures, but user privacy always wins.

## Implementation Status
Completed in the feature branch:
- Added the live profile-signature extension and startup registration.
- Added compact signature rendering using existing guild-scoped game data.
- Added one-card-per-channel persistence, ownership checks, debouncing, cooldowns, same-speaker suppression, and restart duplicate reconciliation.
- Added setup channel selection, field restrictions, enable/disable controls, health presentation, and cleanup behavior.
- Added private `/profile-settings` controls and owner-only profile editing access.
- Added Steam, Epic Games, Xbox, PlayStation, Nintendo, Riot, Battle.net, Roblox, Twitch, YouTube, Kick, and limited custom-platform identities.
- Added allowlisted HTTPS validation and username-only fallback for platforms without dependable canonical profile links.
- Added optional host-configured application emoji for exact platform logos with safe Unicode fallbacks.
- Added global privacy, stricter per-server privacy, full signature opt-out, immediate stale-card cleanup after privacy changes, and immediate card invalidation after server field restrictions change.
- Preserved the existing `/profile` command and aliases through the canonical privacy-aware renderer.
- Added focused URL safety, privacy, setup, persistence, anti-repetition, cancellation, and cleanup tests.
- Staged final newest-speaker generation guards, platform-specific signature icons, and explicit-share visibility behavior for validation.

Still required:
- Complete the final runtime validation workflow.
- Run a fresh human-triggered complete repository CI gate after the generated hardening commit.
- Inspect automated review findings, final diff, mergeability, and cleanup before declaring the pull request ready to merge.

## Validation Status
- Integration compilation passed.
- Focused profile-signature tests passed.
- Complete pytest passed inside both integration workflows.
- Canonical command uniqueness passed.
- Repository CI run 358 passed compilation, the complete test suite, all 14 canonical extensions loading, and legacy-artifact guards before the final hardening commits.
- Repository CI run 371 passed after the URL, setup, and emoji hardening commits.
- A fresh final repository CI run is pending after newest-speaker generation hardening.

## Cleanup Status
- Earlier temporary integration scripts and workflows removed themselves.
- The final runtime patch workflow is required to remove itself before committing.
- Generated `__pycache__`, `.pyc`, and `.pyo` artifacts were removed.
- Permanent ignore rules now prevent compiled/test cache artifacts from being staged again.
- No webhook impersonation, user-message deletion/reposting, guessed third-party platform links, or duplicate setup/profile command path exists.

## Blockers
- None currently.

## Backlog Locked Behind This Task
- Multiplayer/open-world versus solo-world controls.
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
