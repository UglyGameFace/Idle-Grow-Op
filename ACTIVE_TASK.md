# Active Task: Build The Plug Minecraft Companion

## Scope
Build one production Minecraft companion for The Plug, with a Paper 26.2 bridge on Shockbyte and a dedicated Turso database. Provide server status, named online players, Java/Bedrock identity, profiles, stats, AuraSkills snapshots, last-seen, playtime, leaderboards, records, activity and manager health/setup without colliding with Idle Grow or DiscordSRV.

## Confirmed Architecture
- Existing bot repo: `UglyGameFace/Idle-Grow-Op`.
- Feature branch: `feature/minecraft-companion`.
- Canonical Discord command namespace: `/minecraft` plus collision-safe `!mc...` shortcuts.
- Existing Idle Grow persistence remains separate and unchanged.
- Minecraft persistence uses its own Turso database.
- The Plug uses Turso SQL over HTTP with `MINECRAFT_TURSO_DATABASE_URL` and `MINECRAFT_TURSO_AUTH_TOKEN`.
- `ThePlugBridge.jar` uses a separate fine-grained Turso token with only add/update access to runtime/player/activity tables.
- No inbound HTTP port is required on the current Discloud `TYPE=bot` deployment for telemetry.
- Turso is durable storage, not the future realtime chat/proximity transport.
- Geyser + Floodgate remain installed. Floodgate API is authoritative for Bedrock/XUID detection.
- AuraSkills data is captured only while players are loaded online, avoiding false offline-default values.
- DiscordSRV link lookup is transitional only, to preserve existing UUID↔Discord links during migration.
- No RCON, no Minecraft Query, no player IP storage, no Discord token or unrelated database credential in the Paper plugin.

## Implementation Status
Completed on the feature branch:
- Registered the `minecraft` extension in startup.
- Added `/minecraft status`, `players`, `profile`, `stats`, `seen`, `playtime`, `top`, `records`, `activity`, `whois`, `commands`, `setup`, `health`, and `panel`.
- Added collision-safe prefix shortcuts: `!mcstatus`, `!mcplayers`, `!mcprofile`, `!mcstats`, `!mcseen`, `!mcplaytime`, `!mctop`, `!mcrecords`, `!mcactivity`, `!mcwhois`, `!mchealth`, `!mccommands`.
- Added native Java Server List Ping without a third-party status API.
- Replaced the first Minecraft persistence design with dedicated Turso SQL-over-HTTP storage.
- Added automatic Turso schema bootstrap for `minecraft_servers`, `minecraft_runtime`, `minecraft_players`, `minecraft_links`, and `minecraft_activity`.
- Removed the obsolete Minecraft database migration from the other persistence system.
- Reworked ThePlugBridge 1.1.0 to send Paper telemetry directly to Turso `/v2/pipeline` using a restricted token.
- Switched Bedrock detection to the official Floodgate API and kept online AuraSkills API snapshots.
- Paper network writes remain asynchronous; Bukkit state is captured on the server thread.
- Updated bridge CI to reject unrelated privileged credentials and require Turso transport.
- Updated focused Minecraft tests for URL normalization, typed 64-bit IDs, schema isolation, metrics, MOTD parsing, status protocol, and command collision guards.

## Current Validation
- Python compilation has passed on intermediate branch commits.
- Earlier focused CI exposed one stale source-contract assertion; the legacy reference was removed and a new exact-head CI run is pending.
- Java 25 bridge build must pass on the exact current head before merge.
- No production deployment has happened yet.

## Remaining Before Merge
1. Get exact-head Python CI green.
2. Get exact-head Minecraft Bridge CI green and fix any Paper/Floodgate/AuraSkills API compile issues.
3. Inspect the final branch diff for duplicate/obsolete Minecraft implementations and credentials.
4. Create the dedicated Turso database and configure the two credential scopes.
5. Start The Plug once to create the Turso schema.
6. Configure `/minecraft setup` with the live Minecraft endpoint.
7. Install ThePlugBridge.jar and validate live Turso heartbeat/player snapshots.
8. Confirm `/minecraft health`, profiles, stats, players and activity against live Paper data.
9. Only then merge/deploy the feature branch.

## DiscordSRV Replacement Backlog Inside This Task
After telemetry/profile parity is live:
1. Native The Plug account linking.
2. LuckPerms ↔ Discord role synchronization.
3. Minecraft ↔ Discord chat and event delivery.
4. Proximity voice coordination.
5. Disable matching DiscordSRV modules one at a time.
6. Remove DiscordSRV only after live parity and regression validation.
