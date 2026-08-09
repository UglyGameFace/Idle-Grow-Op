# The Plug Minecraft Companion

## Architecture

The Minecraft companion is intentionally isolated from the Idle Grow database.

```text
Paper 26.2
  └─ ThePlugBridge.jar
       ├─ Paper server/player/stat APIs
       ├─ Floodgate API for Bedrock + XUID
       ├─ AuraSkills API while players are online
       ├─ transitional DiscordSRV link import
       └─ Turso SQL-over-HTTP writes (restricted bridge token)

Dedicated Turso database
  ├─ minecraft_servers      # Discord-side config
  ├─ minecraft_runtime      # latest Paper/Geyser health heartbeat
  ├─ minecraft_players      # latest player/stat/AuraSkills snapshots
  ├─ minecraft_activity     # joins/quits/deaths/advancements
  └─ minecraft_links        # native The Plug links later

The Plug on Discloud
  └─ Turso SQL-over-HTTP reads/writes (bot token)
       └─ Discord /minecraft commands
```

Turso is durable storage, **not** the future low-latency chat/proximity transport. Live chat and proximity voice will move to an authenticated realtime connection when The Plug has a public endpoint or a dedicated relay.

## Turso credentials

Use one dedicated database, recommended name: `the-plug-minecraft`.

### The Plug / Discloud

Set these environment variables on The Plug:

- `MINECRAFT_TURSO_DATABASE_URL`
- `MINECRAFT_TURSO_AUTH_TOKEN`

The bot token needs enough permission to create the Minecraft schema and read/write the Minecraft tables. The Plug automatically creates its tables on startup; no manual SQL migration is required.

### Paper bridge / Shockbyte

Create a **different fine-grained database token** for `ThePlugBridge.jar`. It should not receive schema permissions or broad read access. The bridge only needs:

- `minecraft_runtime:data_add,data_update`
- `minecraft_players:data_add,data_update`
- `minecraft_activity:data_add`

The bridge config accepts the Turso database URL or HTTP URL and normalizes it to `/v2/pipeline`.

Never put the Discord token, another bot's database credential, or Floodgate `key.pem` in ThePlugBridge.

## Discord commands

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

- `/minecraft setup`
- `/minecraft health`
- `/minecraft panel`

Prefix compatibility shortcuts are namespaced as `!mcstatus`, `!mcplayers`, `!mcprofile`, etc. Generic `!help`, `!players`, `!profile`, and `!stats` are deliberately not claimed.

## DiscordSRV migration

DiscordSRV stays installed until The Plug owns each replacement feature. Only one system may own a feature at a time.

Migration order:

1. Minecraft telemetry / profiles / health
2. Native account linking
3. LuckPerms ↔ Discord role sync
4. Minecraft ↔ Discord chat and events
5. Proximity voice
6. Disable the matching DiscordSRV modules
7. Remove DiscordSRV only after live parity is proven

The first bridge version may read existing DiscordSRV account links locally to preserve identity during migration. That lookup is transitional and is removed after native The Plug linking is live.

## ThePlugBridge install

1. Start The Plug once with its Turso environment variables. This creates the schema.
2. Build/download `ThePlugBridge.jar` from the Minecraft Bridge CI artifact.
3. Stop Paper.
4. Put the JAR in `/plugins/`.
5. Start once to generate `/plugins/ThePlugBridge/config.yml`, then stop again.
6. Fill `turso-http-url`, `turso-bridge-token`, and `guild-id`.
7. Start Paper normally. Do not use `/reload`.
8. Confirm the log says `ThePlugBridge 1.1.0 enabled` and `/minecraft health` begins showing bridge telemetry.

## Data safety

The bridge does not collect player IP addresses. Player snapshots contain Minecraft identity, edition/XUID where available, current gameplay state, selected vanilla statistics, and online AuraSkills snapshots. Network/database work is sent off the Paper server thread.
