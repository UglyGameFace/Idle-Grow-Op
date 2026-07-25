# Active Task: Optional Guild-Scoped AI Setup

## Scope
Integrate optional Idle Grow AI controls into the existing Discord-native `/setup` wizard and make the real `/chat` execution path reliable, current, secret-safe, and disabled by default per server.

## Root Cause and Confirmed Findings
- The old AI path was branded for Stoney Baloney and documented outdated prefix commands.
- The model, timeout, token limit, and cooldown were hardcoded instead of using host configuration.
- Every server could use AI automatically with no guild opt-in.
- Provider errors were printed to stdout without guild-scoped error routing.
- Server owners must never enter or see the host OpenRouter key.
- AI image generation must remain absent.

## Architecture Decision
- Keep one canonical `setup.py` wizard.
- Store AI enablement in each guild world's `ai_config` map.
- Keep OpenRouter secrets and model configuration at the bot-host level.
- Use one `request_reply()` path for `/chat` and private setup health tests.
- Route only secret-safe provider metadata to the configured guild error log.
- Never log prompts, replies, API keys, or provider secrets.

## Implementation Status
Completed:
- Rebuilt `ai.py` around a guild-aware canonical request service.
- Added current Idle Grow Op prompt and slash-command guidance.
- Added host-configured model fallback, timeout, cooldown, and token limits.
- Added clear provider error classes and secret-safe error routing.
- Added disabled-by-default guild checks for `/chat`.
- Added the Optional AI panel to the existing `/setup` wizard.
- Added private provider health testing plus enable and disable controls.
- Added guild-world persistence for AI enablement.
- Added focused runtime and setup regression contracts.

Still required:
- Run fresh full pytest, compilation, command uniqueness, and all-extension loading.
- Inspect the final PR diff and merge only after every gate passes.

## Validation Status
- Focused AI runtime and setup tests passed in the trusted integration gate.
- A fresh human-authored commit is triggering the complete repository CI gate.

## Cleanup Status
- No second setup command or compatibility layer.
- No AI image generation.
- No server-owned API key storage.
- No prompt or response logging.
- No temporary patch script or branch workflow remains.
- The temporary trusted integrator was removed from `main` after use.

## Blockers
- None beyond the final full CI and conflict inspection.

## Backlog Locked Behind This Task
- Multiplayer/open-world versus solo-world controls.
- Notification preferences and announcement-role controls.
- Broader onboarding and first-run guidance.
