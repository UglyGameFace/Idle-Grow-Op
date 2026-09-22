# Active Task: Idle Grow Master Audit and Legacy Consolidation

## Outcome
Establish one trustworthy, production-ready Idle Grow architecture by tracing every live subsystem, identifying authoritative ownership, removing proven obsolete/conflicting implementations, repairing runtime defects, strengthening behavioral coverage, and validating the exact final build against real deployment behavior.

## Scope
This audit covers the complete Idle Grow repository and deployed behavior:
- startup, shutdown, reconnects, extension loading, slash/prefix command publication, and Discord intents
- command execution and user-facing help/onboarding
- Supabase persistence, cache/dirty tracking, migrations, concurrency, flush/failure behavior, and data ownership
- Solo Grow, Current Server World, Player Choice, and Open World scope routing
- farming, economy, progression, lab, crime, gambling, crews/social, sesh, AI, notifications, profile signatures, setup, admin, weather, market/events, auctions, and scheduled tasks
- CI/tests, Discloud deployment assumptions, stale compatibility logic, temporary artifacts, duplicated ownership, and dead code

## Status
IN PROGRESS

## Confirmed Findings
- Current main head at audit start: af81d32378afdc46a6da9915b06985d8777d0f79.
- No open pull requests existed at audit start.
- Discord startup loads all configured extensions before bot.start() and uses IdleGrowBot.setup_hook() to globally sync application commands.
- Background weather/market processing is owned by tasks.py and can remain healthy independently of user command execution, explaining the observed half-working bot behavior.
- The previous slash-command incident was real: PR #28 repaired startup publication after Discord had retained a stale remote command set.
- The command architecture is still mixed. Core gameplay contains hybrid/slash commands alongside prefix-only commands and prefix-only groups.
- Confirmed prefix-only gameplay surfaces currently include heist, launder, conc, sellconc, bid, district, crew, and auction entry points/subcommands. These require intent/UX review rather than blind conversion.
- Existing command uniqueness tests only prove duplicate names/aliases are absent; they do not prove every advertised or intended command is slash-accessible or executable.
- Existing CI compiles sources, runs pytest, loads extensions, and grep-rejects selected legacy persistence tokens, but extension loading does not execute the full runtime command surface.
- A concrete runtime defect already exists in quick.py: /calc discards the GameScope value and then references scope when computing the effective market multiplier.
- The repository still contains explicit legacy migration infrastructure and world-mode compatibility behavior. These may be legitimate compatibility paths and must be traced before removal.
- Large modules such as setup.py, profile_signatures.py, and sesh.py contain substantial behavior and asynchronous task ownership, making them high-priority conflict/race audit areas.

## Architecture / Execution Path
1. discloud.config launches main.py under Python 3.11.
2. main.py builds and verifies the scoped Supabase backend before connecting Discord.
3. GAME_EXTENSIONS load into a single commands.Bot instance.
4. IdleGrowBot.setup_hook() publishes the local application-command tree globally.
5. on_ready sets presence only; it does not own command registration.
6. tasks.py starts game_cycle, notification_check, and status_cycle through cog_load().
7. ScopedDatabaseManager owns lazy record caching, dirty tracking, periodic flush, and shutdown flush.
8. Feature cogs resolve game scope through world_modes.py and then read/write scoped profiles/worlds.

## Audit Rules
- One authoritative implementation per behavior.
- Do not delete code merely because it appears old; verify callers, persistence impact, config/dynamic usage, tests, and compatibility first.
- Prefer repairing/consolidating existing behavior over adding guards, fallbacks, duplicate handlers, or replacement systems.
- Runtime behavior outranks static source-contract tests.
- No unrelated redesign while a defect/ownership question is unresolved.
- Preserve unrelated user work and existing production data semantics unless an intentional migration is proven necessary.

## Validation Required Before Completion
- Every production module compiles.
- Full pytest passes on the exact final head.
- All extensions load together.
- Complete command inventory is generated from the real bot tree and compared with intended help/setup surfaces.
- Representative command callbacks from every subsystem execute against controlled runtime fixtures.
- Known failure paths and permission/context handling are exercised.
- Persistence read/write/flush/retry and scope isolation behavior are tested.
- Background task lifecycle and reconnect behavior are tested.
- Async tasks/views/listeners in profile signatures, sesh, setup, and tasks receive focused lifecycle/race review.
- Legacy/duplicate code removals have reference checks and regression coverage.
- Final diff contains no unrelated changes, secrets, temporary scripts, generated junk, conflict artifacts, or abandoned compatibility layers.
- Exact final head receives CI and deployment/runtime validation.

## Cleanup / Conflict Review
Pending. Every affected subsystem will be checked after its behavioral audit for obsolete, duplicate, conflicting, partial, temporary, and superseded logic.

## Blockers / Risks
- GitHub source and CI are available, but live Discloud runtime logs/deployed file fingerprint are not yet attached to this conversation. Production deployment state must be validated before claiming the live incident resolved.
- Existing tests contain many source-text contracts, so a green suite alone is not sufficient evidence of runtime correctness.

## Backlog Within This Master Audit
- Resolve slash/hybrid versus prefix-only command ownership and advertised UX.
- Fix /calc undefined scope through the authoritative quick-command path with runtime regression coverage.
- Audit all commands for equivalent runtime-only failures.
- Audit setup/profile-signature/sesh async lifecycle and duplicated ownership.
- Determine whether legacy migration workflow/tooling is still required or is completed residue.
- Determine whether legacy world-mode compatibility remains necessary for production data.
- Expand CI from mostly structural contracts toward behavioral command/runtime coverage.
- Validate the deployed Discloud revision and startup command-sync output.

## Git State
- Base: main @ af81d32378afdc46a6da9915b06985d8777d0f79
- Audit branch: fix/idle-grow-master-audit
- No open PR at audit start.

## Next Step
Build a complete command/feature ownership map, then audit command execution paths against help/setup advertising before making the first behavioral fix.
