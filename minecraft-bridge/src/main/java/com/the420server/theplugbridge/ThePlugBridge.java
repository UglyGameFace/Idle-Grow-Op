package com.the420server.theplugbridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import dev.aurelium.auraskills.api.AuraSkillsApi;
import dev.aurelium.auraskills.api.skill.Skill;
import dev.aurelium.auraskills.api.user.SkillsUser;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.Statistic;
import org.bukkit.advancement.Advancement;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.player.PlayerAdvancementDoneEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;
import org.geysermc.floodgate.api.FloodgateApi;
import org.geysermc.floodgate.api.player.FloodgatePlayer;

import java.lang.reflect.Method;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.logging.Level;


public final class ThePlugBridge extends JavaPlugin implements Listener {
    private static final String BRIDGE_VERSION = "1.1.0";
    private static final long MIN_HEARTBEAT_SECONDS = 5L;
    private static final long MAX_HEARTBEAT_SECONDS = 300L;
    private static final int MAX_PENDING_EVENTS = 250;

    private final Gson gson = new GsonBuilder().disableHtmlEscaping().create();
    private final ConcurrentLinkedQueue<Map<String, Object>> pendingEvents = new ConcurrentLinkedQueue<>();
    private final Map<UUID, Instant> joinedAt = new LinkedHashMap<>();
    private final AtomicBoolean requestInFlight = new AtomicBoolean(false);

    private HttpClient httpClient;
    private URI tursoPipelineUri;
    private String tursoAuthToken;
    private long guildId;
    private long heartbeatSeconds;
    private String instanceId;
    private BukkitTask heartbeatTask;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        String tursoUrl = getConfig().getString("turso-http-url", "");
        this.tursoAuthToken = getConfig().getString("turso-bridge-token", "").trim();
        this.guildId = getConfig().getLong("guild-id", 0L);
        this.heartbeatSeconds = Math.max(
            MIN_HEARTBEAT_SECONDS,
            Math.min(MAX_HEARTBEAT_SECONDS, getConfig().getLong("heartbeat-seconds", 15L))
        );
        this.instanceId = UUID.randomUUID().toString();
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(8)).build();

        try {
            this.tursoPipelineUri = normalizeTursoPipelineUri(tursoUrl);
        } catch (IllegalArgumentException exc) {
            getLogger().severe("Invalid turso-http-url: " + exc.getMessage());
            getServer().getPluginManager().disablePlugin(this);
            return;
        }

        if (!configurationReady()) {
            getLogger().severe(
                "ThePlugBridge is not configured. Fill turso-http-url, turso-bridge-token, "
                    + "and guild-id in plugins/ThePlugBridge/config.yml."
            );
            getServer().getPluginManager().disablePlugin(this);
            return;
        }

        for (Player player : Bukkit.getOnlinePlayers()) {
            joinedAt.put(player.getUniqueId(), Instant.now());
        }
        Bukkit.getPluginManager().registerEvents(this, this);
        this.heartbeatTask = Bukkit.getScheduler().runTaskTimer(
            this,
            this::captureAndDispatch,
            40L,
            heartbeatSeconds * 20L
        );
        getLogger().info(
            "ThePlugBridge " + BRIDGE_VERSION + " enabled; Turso heartbeat every "
                + heartbeatSeconds + "s. No player IP addresses are collected."
        );
    }

    @Override
    public void onDisable() {
        if (heartbeatTask != null) {
            heartbeatTask.cancel();
            heartbeatTask = null;
        }
        requestInFlight.set(false);
        pendingEvents.clear();
        joinedAt.clear();
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        Player player = event.getPlayer();
        joinedAt.put(player.getUniqueId(), Instant.now());
        enqueueEvent(player, "join", null);
        scheduleFastSync();
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        Player player = event.getPlayer();
        enqueueEvent(player, "quit", null);
        joinedAt.remove(player.getUniqueId());
        scheduleFastSync();
    }

    @EventHandler
    public void onDeath(PlayerDeathEvent event) {
        Player player = event.getEntity();
        String message = event.getDeathMessage();
        String detail = ChatColor.stripColor(message == null ? "" : message);
        enqueueEvent(player, "death", detail);
        scheduleFastSync();
    }

    @EventHandler
    public void onAdvancement(PlayerAdvancementDoneEvent event) {
        Player player = event.getPlayer();
        Advancement advancement = event.getAdvancement();
        enqueueEvent(player, "advancement", advancement.getKey().toString());
        scheduleFastSync();
    }

    private void scheduleFastSync() {
        Bukkit.getScheduler().runTaskLater(this, this::captureAndDispatch, 20L);
    }

    private void enqueueEvent(Player player, String eventType, String detail) {
        Map<String, Object> event = new LinkedHashMap<>();
        FloodgatePlayer floodgatePlayer = floodgatePlayer(player.getUniqueId());
        event.put("player_uuid", player.getUniqueId().toString());
        event.put("username", resolveUsername(player, floodgatePlayer));
        event.put("event_type", eventType);
        event.put("detail", detail);
        event.put("occurred_at", Instant.now().toString());
        pendingEvents.add(event);
        trimPendingEvents();
    }

    private void trimPendingEvents() {
        while (pendingEvents.size() > MAX_PENDING_EVENTS) {
            pendingEvents.poll();
        }
    }

    private void captureAndDispatch() {
        if (!isEnabled() || !requestInFlight.compareAndSet(false, true)) {
            return;
        }
        Map<String, Object> server = captureServer();
        List<Map<String, Object>> players = new ArrayList<>();
        for (Player player : Bukkit.getOnlinePlayers()) {
            players.add(capturePlayer(player));
        }
        List<Map<String, Object>> events = new ArrayList<>();
        Map<String, Object> event;
        while ((event = pendingEvents.poll()) != null) {
            events.add(event);
        }
        String requestBody = gson.toJson(buildPipeline(server, players, events));
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> sendPipeline(requestBody, events));
    }

    private Map<String, Object> buildPipeline(
        Map<String, Object> server,
        List<Map<String, Object>> players,
        List<Map<String, Object>> events
    ) {
        List<Map<String, Object>> requests = new ArrayList<>();
        requests.add(execute("BEGIN"));
        requests.add(execute(
            """
            INSERT INTO minecraft_runtime (
                guild_id, bridge_instance_id, bridge_version, heartbeat_at,
                minecraft_version, paper_version, geyser_version, floodgate_version,
                tps_1m, tps_5m, tps_15m, mspt,
                memory_used_mb, memory_max_mb, online_players, max_players,
                bedrock_online, plugins_json
            ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                bridge_instance_id = excluded.bridge_instance_id,
                bridge_version = excluded.bridge_version,
                heartbeat_at = CURRENT_TIMESTAMP,
                minecraft_version = excluded.minecraft_version,
                paper_version = excluded.paper_version,
                geyser_version = excluded.geyser_version,
                floodgate_version = excluded.floodgate_version,
                tps_1m = excluded.tps_1m,
                tps_5m = excluded.tps_5m,
                tps_15m = excluded.tps_15m,
                mspt = excluded.mspt,
                memory_used_mb = excluded.memory_used_mb,
                memory_max_mb = excluded.memory_max_mb,
                online_players = excluded.online_players,
                max_players = excluded.max_players,
                bedrock_online = excluded.bedrock_online,
                plugins_json = excluded.plugins_json
            """,
            guildId,
            server.get("bridge_instance_id"),
            server.get("bridge_version"),
            server.get("minecraft_version"),
            server.get("paper_version"),
            server.get("geyser_version"),
            server.get("floodgate_version"),
            server.get("tps_1m"),
            server.get("tps_5m"),
            server.get("tps_15m"),
            server.get("mspt"),
            server.get("memory_used_mb"),
            server.get("memory_max_mb"),
            server.get("online_players"),
            server.get("max_players"),
            server.get("bedrock_online"),
            gson.toJson(server.get("plugins"))
        ));
        requests.add(execute(
            "UPDATE minecraft_players SET online = 0 WHERE guild_id = ? AND online = 1",
            guildId
        ));

        for (Map<String, Object> player : players) {
            requests.add(execute(
                """
                INSERT INTO minecraft_players (
                    guild_id, player_uuid, username, platform, xuid, discord_user_id,
                    online, first_seen, last_seen, joined_at, playtime_ticks,
                    world, game_mode, health, food, experience_level,
                    stats_json, aura_skills_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id, player_uuid) DO UPDATE SET
                    username = excluded.username,
                    platform = excluded.platform,
                    xuid = COALESCE(excluded.xuid, minecraft_players.xuid),
                    discord_user_id = COALESCE(excluded.discord_user_id, minecraft_players.discord_user_id),
                    online = 1,
                    first_seen = COALESCE(minecraft_players.first_seen, excluded.first_seen),
                    last_seen = CURRENT_TIMESTAMP,
                    joined_at = excluded.joined_at,
                    playtime_ticks = excluded.playtime_ticks,
                    world = excluded.world,
                    game_mode = excluded.game_mode,
                    health = excluded.health,
                    food = excluded.food,
                    experience_level = excluded.experience_level,
                    stats_json = excluded.stats_json,
                    aura_skills_json = excluded.aura_skills_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                guildId,
                player.get("player_uuid"),
                player.get("username"),
                player.get("platform"),
                player.get("xuid"),
                player.get("discord_user_id"),
                player.get("first_seen"),
                player.get("joined_at"),
                player.get("playtime_ticks"),
                player.get("world"),
                player.get("game_mode"),
                player.get("health"),
                player.get("food"),
                player.get("experience_level"),
                gson.toJson(player.get("stats")),
                gson.toJson(player.get("aura_skills"))
            ));
        }

        for (Map<String, Object> event : events) {
            requests.add(execute(
                """
                INSERT INTO minecraft_activity (
                    guild_id, player_uuid, username, event_type, detail, occurred_at
                ) VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                guildId,
                event.get("player_uuid"),
                event.get("username"),
                event.get("event_type"),
                event.get("detail"),
                event.get("occurred_at")
            ));
        }
        requests.add(execute("COMMIT"));
        Map<String, Object> close = new LinkedHashMap<>();
        close.put("type", "close");
        requests.add(close);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("requests", requests);
        return body;
    }

    private Map<String, Object> execute(String sql, Object... arguments) {
        Map<String, Object> statement = new LinkedHashMap<>();
        statement.put("sql", sql);
        if (arguments.length > 0) {
            List<Map<String, Object>> args = new ArrayList<>();
            for (Object argument : arguments) {
                args.add(sqlArgument(argument));
            }
            statement.put("args", args);
        }
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("type", "execute");
        request.put("stmt", statement);
        return request;
    }

    private Map<String, Object> sqlArgument(Object value) {
        Map<String, Object> argument = new LinkedHashMap<>();
        if (value == null) {
            argument.put("type", "null");
        } else if (value instanceof Boolean booleanValue) {
            argument.put("type", "integer");
            argument.put("value", booleanValue ? "1" : "0");
        } else if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long) {
            argument.put("type", "integer");
            argument.put("value", value.toString());
        } else if (value instanceof Number) {
            argument.put("type", "float");
            argument.put("value", value.toString());
        } else {
            argument.put("type", "text");
            argument.put("value", value.toString());
        }
        return argument;
    }

    private void sendPipeline(String requestBody, List<Map<String, Object>> events) {
        try {
            HttpRequest request = HttpRequest.newBuilder(tursoPipelineUri)
                .timeout(Duration.ofSeconds(12))
                .header("Authorization", "Bearer " + tursoAuthToken)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(requestBody))
                .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                restoreEvents(events);
                getLogger().warning(
                    "Turso bridge write failed with HTTP " + response.statusCode()
                        + ". Check the database URL and bridge token."
                );
                return;
            }
            if (!pipelineSucceeded(response.body())) {
                restoreEvents(events);
                getLogger().warning(
                    "Turso accepted the HTTP request but rejected one or more SQL statements. "
                        + "Check that The Plug created the schema and the bridge token has add/update permissions."
                );
            }
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            restoreEvents(events);
            getLogger().log(Level.WARNING, "Turso bridge request interrupted", exc);
        } catch (Exception exc) {
            restoreEvents(events);
            getLogger().log(Level.WARNING, "Turso bridge request failed", exc);
        } finally {
            requestInFlight.set(false);
        }
    }

    private boolean pipelineSucceeded(String responseBody) {
        try {
            Object decoded = gson.fromJson(responseBody, Object.class);
            if (!(decoded instanceof Map<?, ?> root)) {
                return false;
            }
            Object rawResults = root.get("results");
            if (!(rawResults instanceof List<?> results)) {
                return false;
            }
            for (Object item : results) {
                if (!(item instanceof Map<?, ?> result)
                    || !"ok".equals(String.valueOf(result.get("type")))) {
                    return false;
                }
            }
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    private void restoreEvents(List<Map<String, Object>> events) {
        for (Map<String, Object> event : events) {
            pendingEvents.add(event);
        }
        trimPendingEvents();
    }

    private Map<String, Object> captureServer() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("bridge_instance_id", instanceId);
        row.put("bridge_version", BRIDGE_VERSION);
        row.put("minecraft_version", Bukkit.getMinecraftVersion());
        row.put("paper_version", Bukkit.getVersion());
        row.put("geyser_version", pluginVersion("Geyser-Spigot"));
        row.put("floodgate_version", pluginVersion("floodgate"));
        double[] tps = Bukkit.getServer().getTPS();
        row.put("tps_1m", tps.length > 0 ? tps[0] : 20.0D);
        row.put("tps_5m", tps.length > 1 ? tps[1] : 20.0D);
        row.put("tps_15m", tps.length > 2 ? tps[2] : 20.0D);
        row.put("mspt", Bukkit.getServer().getAverageTickTime());

        Runtime runtime = Runtime.getRuntime();
        long used = runtime.totalMemory() - runtime.freeMemory();
        row.put("memory_used_mb", used / (1024.0D * 1024.0D));
        row.put("memory_max_mb", runtime.maxMemory() / (1024.0D * 1024.0D));
        row.put("online_players", Bukkit.getOnlinePlayers().size());
        row.put("max_players", Bukkit.getMaxPlayers());
        int bedrockOnline = 0;
        for (Player player : Bukkit.getOnlinePlayers()) {
            if (isBedrock(player.getUniqueId())) {
                bedrockOnline++;
            }
        }
        row.put("bedrock_online", bedrockOnline);

        List<String> plugins = new ArrayList<>();
        for (Plugin plugin : Bukkit.getPluginManager().getPlugins()) {
            plugins.add(plugin.getName() + " " + plugin.getPluginMeta().getVersion());
        }
        row.put("plugins", plugins);
        return row;
    }

    private String pluginVersion(String pluginName) {
        Plugin plugin = Bukkit.getPluginManager().getPlugin(pluginName);
        if (plugin == null || !plugin.isEnabled()) {
            return null;
        }
        return plugin.getPluginMeta().getVersion();
    }

    private Map<String, Object> capturePlayer(Player player) {
        Map<String, Object> row = new LinkedHashMap<>();
        UUID uuid = player.getUniqueId();
        FloodgatePlayer floodgatePlayer = floodgatePlayer(uuid);
        row.put("player_uuid", uuid.toString());
        row.put("username", resolveUsername(player, floodgatePlayer));
        row.put("platform", floodgatePlayer == null ? "java" : "bedrock");
        row.put("xuid", floodgatePlayer == null ? null : String.valueOf(floodgatePlayer.getXuid()));
        row.put("discord_user_id", linkedDiscordId(uuid));
        long firstPlayed = player.getFirstPlayed();
        row.put(
            "first_seen",
            firstPlayed > 0L ? Instant.ofEpochMilli(firstPlayed).toString() : Instant.now().toString()
        );
        row.put("joined_at", joinedAt.getOrDefault(uuid, Instant.now()).toString());
        row.put("playtime_ticks", playtimeTicks(player));
        row.put("world", player.getWorld().getName());
        row.put("game_mode", player.getGameMode().name());
        row.put("health", player.getHealth());
        row.put("food", player.getFoodLevel());
        row.put("experience_level", player.getLevel());
        row.put("stats", vanillaStats(player));
        row.put("aura_skills", auraSkills(player));
        return row;
    }

    private Map<String, Object> vanillaStats(Player player) {
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("player_kills", statistic(player, Statistic.PLAYER_KILLS));
        stats.put("mob_kills", statistic(player, Statistic.MOB_KILLS));
        stats.put("deaths", statistic(player, Statistic.DEATHS));
        stats.put("jumps", statistic(player, Statistic.JUMP));
        stats.put("walk_cm", statisticByName(player, "WALK_ONE_CM"));
        stats.put("sprint_cm", statisticByName(player, "SPRINT_ONE_CM"));
        stats.put("swim_cm", statisticByName(player, "SWIM_ONE_CM"));
        stats.put("damage_dealt", statisticByName(player, "DAMAGE_DEALT"));
        stats.put("damage_taken", statisticByName(player, "DAMAGE_TAKEN"));
        return stats;
    }

    private long playtimeTicks(Player player) {
        long value = statisticByName(player, "PLAY_TIME");
        return Math.max(0L, value > 0L ? value : statisticByName(player, "PLAY_ONE_MINUTE"));
    }

    private long statistic(Player player, Statistic statistic) {
        try {
            return Math.max(0, player.getStatistic(statistic));
        } catch (IllegalArgumentException ignored) {
            return 0L;
        }
    }

    private long statisticByName(Player player, String statisticName) {
        try {
            return statistic(player, Statistic.valueOf(statisticName));
        } catch (IllegalArgumentException ignored) {
            return 0L;
        }
    }

    private Map<String, Object> auraSkills(Player player) {
        Map<String, Object> output = new LinkedHashMap<>();
        Plugin plugin = Bukkit.getPluginManager().getPlugin("AuraSkills");
        if (plugin == null || !plugin.isEnabled()) {
            return output;
        }
        try {
            AuraSkillsApi api = AuraSkillsApi.get();
            SkillsUser user = api.getUser(player.getUniqueId());
            Collection<Skill> skills = api.getGlobalRegistry().getSkills();
            for (Skill skill : skills) {
                String rawId = skill.getId().toString();
                String key = rawId.contains("/") ? rawId.substring(rawId.indexOf('/') + 1) : rawId;
                Map<String, Object> value = new LinkedHashMap<>();
                value.put("level", user.getSkillLevel(skill));
                value.put("xp", user.getSkillXp(skill));
                output.put(key.toLowerCase(Locale.ROOT), value);
            }
        } catch (Throwable exc) {
            getLogger().log(Level.FINE, "AuraSkills snapshot unavailable for " + player.getName(), exc);
        }
        return output;
    }

    private FloodgatePlayer floodgatePlayer(UUID uuid) {
        try {
            FloodgateApi api = FloodgateApi.getInstance();
            return api != null && api.isFloodgatePlayer(uuid) ? api.getPlayer(uuid) : null;
        } catch (Throwable ignored) {
            return null;
        }
    }

    private boolean isBedrock(UUID uuid) {
        return floodgatePlayer(uuid) != null;
    }

    private String resolveUsername(Player player, FloodgatePlayer floodgatePlayer) {
        if (floodgatePlayer != null) {
            String username = floodgatePlayer.getUsername();
            if (username != null && !username.isBlank()) {
                return username;
            }
        }
        String name = player.getName();
        return name.startsWith(".") ? name.substring(1) : name;
    }

    private Long linkedDiscordId(UUID uuid) {
        try {
            Plugin plugin = Bukkit.getPluginManager().getPlugin("DiscordSRV");
            if (plugin == null || !plugin.isEnabled()) {
                return null;
            }
            Method managerMethod = plugin.getClass().getMethod("getAccountLinkManager");
            Object manager = managerMethod.invoke(plugin);
            if (manager == null) {
                return null;
            }
            Method getDiscordId = manager.getClass().getMethod("getDiscordId", UUID.class);
            Object result = getDiscordId.invoke(manager, uuid);
            if (result == null) {
                return null;
            }
            String raw = result.toString().trim();
            return raw.isEmpty() ? null : Long.parseLong(raw);
        } catch (Throwable ignored) {
            return null;
        }
    }

    private boolean configurationReady() {
        return guildId > 0L && tursoPipelineUri != null && !tursoAuthToken.isBlank();
    }

    private URI normalizeTursoPipelineUri(String rawValue) {
        String value = rawValue == null ? "" : rawValue.trim();
        if (value.isBlank()) {
            throw new IllegalArgumentException("URL is empty");
        }
        value = value.replaceFirst("^libsql://", "https://");
        value = value.replaceFirst("^turso://", "https://");
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        if (!value.endsWith("/v2/pipeline")) {
            value += "/v2/pipeline";
        }
        URI uri = URI.create(value);
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null) {
            throw new IllegalArgumentException("use the Turso database/HTTP URL");
        }
        return uri;
    }
}
