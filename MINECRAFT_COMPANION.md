# The Plug — Minecraft Companion

The Plug runs on Discloud. `ThePlugBridge.jar` runs on Paper/Shockbyte and sends a
small, structured telemetry snapshot to the same Supabase project already used by
Idle Grow Op.

The bridge exists because the Discloud process cannot read Shockbyte's local
plugin files. It does **not** expose RCON, does **not** enable Minecraft Query, and
does **not** collect player IP addresses.

## Command surface

Slash commands:

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
- `/minecraft health` — Manage Server
- `/minecraft setup` — Manage Server
- `/minecraft bridgekey` — Manage Server, slash-only secret delivery
- `/minecraft panel` — Manage Server; posts/pins the public command guide

Prefix compatibility shortcuts are deliberately namespaced so they do not steal
DiscordSRV or Idle Grow commands:

`!mcstatus`, `!mcplayers`, `!mcprofile`, `!mcstats`, `!mcseen`,
`!mcplaytime`, `!mctop`, `!mcrecords`, `!mcactivity`, `!mcwhois`,
`!mchealth`, `!mccommands`.

DiscordSRV can continue owning its existing `!players`, `!help`, `!mc`, `!link`,
and `!discord` canned responses.

## One-time database setup

Run `migrations/003_minecraft_companion.sql` in the Supabase SQL editor for the
project used by The Plug.

The migration creates:

- `minecraft_servers`
- `minecraft_bridge_auth`
- `minecraft_players`
- `minecraft_activity`
- `the_plug_bridge_ingest(...)`

The Paper plugin never needs the Supabase service-role key. It calls only the
restricted ingest RPC using the project's public anon/publishable key plus a
rotatable bridge secret. Direct anon/authenticated table access is revoked.

## Discord / Discloud setup

After the migration and after The Plug is deployed:

1. Run:
   `/minecraft setup host:<public-host> java_port:27002 bedrock_port:27002 display_name:The 420 Server`
2. Run `/minecraft bridgekey`.
3. Copy the private secret from the ephemeral response.
4. Keep the existing Discloud-only `IDLE_SUPABASE_URL`,
   `IDLE_SUPABASE_SERVICE_ROLE_KEY`, and `DISCORD_TOKEN` environment values.
   Do not put those secrets in GitHub.

## Shockbyte / Paper setup

Build or download the `ThePlugBridge` GitHub Actions artifact.

1. Stop the Minecraft server.
2. Upload `ThePlugBridge.jar` to `/plugins/`.
3. Start once so `/plugins/ThePlugBridge/config.yml` is generated, then stop.
4. Fill:
   - `supabase-url`
   - `supabase-anon-key` — public anon/publishable key only
   - `bridge-secret` — from `/minecraft bridgekey`
   - `guild-id`
5. Start normally. Do not use `/reload`.

Expected startup line:

`ThePlugBridge 1.0.0 enabled; heartbeat every 15s. No player IP addresses are collected.`

Within roughly 15 seconds, `/minecraft health` should show a recent bridge
heartbeat and `/minecraft players` should show online Java and Bedrock users.

## Data collected

For online players the bridge sends:

- Minecraft UUID and username
- Java/Bedrock platform classification
- Discord user ID when DiscordSRV already has that UUID linked
- first/last seen and current join time
- playtime
- world, game mode, health, food, XP level
- vanilla deaths/kills/jumps/movement statistics
- loaded AuraSkills levels/XP
- join, quit, death, and advancement activity

No IP address is collected or stored.

## Failure behavior

- If Supabase migration 003 is missing, Minecraft commands explain that the
  companion schema is unavailable; the existing Idle Grow bot remains intact.
- If the bridge secret is wrong, the Paper plugin logs an HTTP ingest failure and
  restores unsent activity events to its bounded queue.
- If the bridge is offline, `/minecraft status` still attempts a direct Java
  Server List Ping using the configured public host.
- Bridge requests are asynchronous; Bukkit/AuraSkills state is captured on the
  server thread before network I/O starts.
