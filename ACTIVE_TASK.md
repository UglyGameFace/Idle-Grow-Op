# Active Task: Optional Guild-Scoped AI Setup

## Scope
Integrate optional Idle Grow AI controls into the existing Discord-native `/setup` wizard and make the real `/chat` execution path reliable, current, secret-safe, and disabled by default per server.

## Root Cause and Confirmed Findings
- The old AI path was branded for Stoney Baloney and documented outdated prefix commands.
- The model, timeout, token limit, and cooldown were hardcoded instead of using host configuration.
- Every server could use AI automatically with no guild opt-in.
- Provider errors were printed to stdout without guild-scoped error routing.
- The AI cog referenced a guild error-reporter hook that did not exist on the bot.
- Malformed numeric environment values could crash the AI extension during import and abort startup.
- The AI read path mutated cached guild-world configuration without locking or dirty tracking.
- Raw provider error bodies were not safe to retain because they could contain request-related details.
- Server owners must never enter or see the host OpenRouter key.
- AI image generation must remain absent.

## Architecture Decision
- Keep one canonical `setup.py` wizard.
- Store AI enablement in each guild world's `ai_config` map.
- Keep OpenRouter secrets and model configuration at the bot-host level.
- Use one `request_reply()` path for `/chat` and private setup health tests.
- Expose one awaited bot-level guild error-reporter contract for cogs.
- Route only secret-safe provider metadata to the configured guild error log.
- Never log prompts, replies, raw provider bodies, API keys, or provider secrets.
- Keep config reads non-mutating; reserve locked writes and dirty tracking for setup changes.

## Implementation Status
Completed:
- Rebuilt `ai.py` around a guild-aware canonical request service.
- Added current Idle Grow Op prompt and slash-command guidance.
- Added host-configured model fallback, timeout, cooldown, and token limits.
- Added bounded safe integer parsing with default fallback for malformed host configuration.
- Added clear provider error classes and secret-safe error routing.
- Added the real awaited `bot.report_command_error` hook backed by the existing per-guild reporter.
- Removed raw provider response bodies from logs.
- Changed guild AI configuration reads to return a non-mutating copy.
- Added disabled-by-default guild checks for `/chat`.
- Added the Optional AI panel to the existing `/setup` wizard.
- Added private provider health testing plus enable and disable controls.
- Added guild-world persistence for AI enablement.
- Added focused runtime, reporter, privacy, and setup regression contracts.
- Updated the existing guild error-routing contract for safe persisted ID parsing.

Still required:
- User approval to merge PR #8 into `main`.

## Validation Status
- Focused AI runtime and setup tests passed.
- Qodo's three review findings are resolved.
- PR #8 is mergeable with no file conflicts.
- GitHub Actions CI run **347** passed on commit `3102746`.
- Compilation passed.
- Complete pytest passed.
- All 13 canonical Enterprise extensions loaded successfully.
- Legacy persistence and backup-artifact guard passed.

## Cleanup Status
- No second setup command or compatibility layer.
- No AI image generation command or endpoint.
- No server-owned API key storage.
- No prompt, response, raw provider-body, or secret logging.
- No duplicate AI configuration path.
- No temporary patch script or branch workflow remains.
- The temporary trusted integrator was removed from `main` after use.
- Final changed-file surface is limited to AI runtime, shared error routing, canonical setup, task record, and targeted regression tests.

## Blockers
- None. PR #8 is ready to merge.

## Backlog Locked Behind This Task
- Live Profile Signature cards are tracked separately in issue #13 and must avoid repetitive reposting or channel spam.
- Multiplayer/open-world versus solo-world controls.
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
