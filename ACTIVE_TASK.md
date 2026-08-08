# Active Task: Build The Plug Minecraft Companion

## Scope
Add one production Minecraft companion surface to the existing The Plug / Idle Grow Op
Discloud bot, backed by a small Paper bridge on the Shockbyte server. Provide live server
status, player identity/linking, profiles, stats, last-seen, playtime, leaderboards,
records, activity, and manager health/setup controls without colliding with the existing
Idle Grow or DiscordSRV command surfaces.

## Root Cause and Confirmed Findings
- The current production-capable The Plug codebase is `UglyGameFace/Idle-Grow-Op`;
  it already has `discloud.config`, Supabase persistence, CI, and automatic slash sync.
- `social.py` already owns the generic `profile`/`stats` game command surface, so
  Minecraft commands must be namespaced rather than registering duplicate `/profile`,
  `!profile`, `/stats`, or `!stats`.
- DiscordSRV already owns simple `!players`, `!help`, `!mc`, `!link`, and `!discord`
  behavior in the live Minecraft chat channel.
- A Discloud process cannot safely read Shockbyte-local Bukkit/DiscordSRV/AuraSkills
  files, so full player data needs a server-side bridge.
- Minecraft Query is not suitable because Geyser already uses UDP port 27002; exposing
  RCON just for stats would add unnecessary remote-control risk.
- DiscordSRV exposes its UUID -> Discord account-link manager, Floodgate exposes Bedrock
  identity, and AuraSkills exposes loaded player skill data.
- Paper 26.2 plugins target Java 25 and the current Paper API version format.
- The bridge must not store player IP addresses or receive the Supabase service-role key.

## Architecture
- One canonical Discord extension: `minecraft.py`.
- One dependency-free Java Server List Ping implementation: `minecraft_service.py`.
- One `/minecraft` slash/hybrid group plus collision-safe `!mc...` prefix shortcuts.
- One Paper plugin: `ThePlugBridge`, installed on Shockbyte.
- One Supabase migration with four Minecraft tables and one SECURITY DEFINER ingest RPC.
- The Discloud bot keeps the trusted service-role key it already has.
- The Paper plugin uses only the Supabase public anon/publishable key plus a rotatable
  per-guild bridge secret.
- Bukkit/AuraSkills state is captured on the main server thread; HTTP ingest runs async.
- The bridge sends UUID, username, Java/Bedrock platform, DiscordSRV linked account ID,
  playtime, vanilla stats, AuraSkills, and bounded recent activity. It never sends IPs.

## Planned Command Surface
Public:
- `/minecraft status`
- `/minecraft players`
- `/minecraft profile [player]`
- `/minecraft stats [player]`
- `/minecraft seen [player]`
- `/minecraft playtime [player]`
- `/minecraft top [metric]`
- `/minecraft records`
- `/minecraft activity`
- `/minecraft whois <player or @member>`
- `/minecraft commands`

Manager:
- `/minecraft health`
- `/minecraft setup`
- `/minecraft bridgekey`
- `/minecraft panel`

Prefix compatibility:
- `!mcstatus`, `!mcplayers`, `!mcprofile`, `!mcstats`, `!mcseen`, `!mcplaytime`,
  `!mctop`, `!mcrecords`, `!mcactivity`, `!mcwhois`, `!mchealth`, `!mccommands`.

## Implementation Status
In progress on `feature/minecraft-companion`.

Implemented in the working change set:
- Namespaced Discord command module and public guide/panel.
- Direct Java server ping fallback with no extra Python dependency.
- Supabase-backed server/player/activity repository helpers.
- Secure bridge-key rotation command with ephemeral secret delivery.
- Migration 003 with RLS, private bridge-auth storage, and restricted ingest RPC.
- Paper 26.2 / Java 25 ThePlugBridge with async HTTP transport.
- DiscordSRV linked-account lookup, Floodgate Bedrock detection, and AuraSkills capture.
- Join/quit/death/advancement activity feed.
- No player IP collection.
- Focused Python tests and dedicated Java bridge CI artifact build.
- Deployment documentation.

Still required before task closure:
- Commit/push implementation and open PR.
- Run Python CI, command-tree load checks, and Java 25 Maven build.
- Fix any CI/compiler failures.
- Merge only after exact-head CI is green.
- Apply migration 003 in the user's Supabase project.
- Deploy/restart The Plug on Discloud.
- Upload/configure ThePlugBridge on Shockbyte and restart normally.
- Verify a fresh bridge heartbeat and real Java + Bedrock player rows.
- Verify DiscordSRV account link resolution and AuraSkills values on live users.
- Post/pin the public `/minecraft panel` after runtime validation.

## Cleanup / Conflict Checks
- No generic `!profile`, `!stats`, `!help`, `!players`, or `!mc` aliases added.
- No RCON or Minecraft Query.
- No service-role key in the Paper plugin.
- No player IP collection.
- No second Discord linking database; DiscordSRV remains authoritative for account links.
- No Boar dependency. Boar 2.0.1 was isolated as the Bedrock movement rubber-banding
  source and was removed from the Minecraft server before this force switch.

## Blockers
- Supabase migration and live Shockbyte/Discloud deployment require the user's connected
  infrastructure/manual host steps after code validation.
- Exact public Minecraft hostname is intentionally not hardcoded; `/minecraft setup`
  stores it per Discord guild at deployment time.

## Backlog Locked Behind This Task
- Java-client compatibility/direct-connection troubleshooting.
- Paper build update.
- Any remaining DiscordSRV role-sync/presence polish not required by this companion.
