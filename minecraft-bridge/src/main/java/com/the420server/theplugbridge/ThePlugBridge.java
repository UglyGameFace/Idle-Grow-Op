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
    private static final String BRIDGE_VERSION = "1.0.0";
    private static final long MIN_HEARTBEAT_SECONDS = 5L;
    private static final long MAX_HEARTBEAT_SECONDS = 300L;

    private final Gson gson = new GsonBuilder().disableHtmlEscaping().create();
    private final ConcurrentLinkedQueue<Map<String, Object>> pendingEvents = new ConcurrentLinkedQueue<>();
    private final Map<UUID, Instant> joinedAt = new LinkedHashMap<>();
    private final AtomicBoolean requestInFlight = new AtomicBoolean(false);

    private HttpClient httpClient;
    private String supabaseUrl;
    private String supabaseAnonKey;
    private String bridgeSecret;
    private long guildId;
    private long heartbeatSeconds;
    private String instanceId;
    private BukkitTask heartbeatTask;

    @Override
    public void onEnable() {
        saveDefaultConfig();

        this.supabaseUrl = cleanUrl(getConfig().getString("supabase-url", ""));
        this.supabaseAnonKey = getConfig().getString("supabase-anon-key", "").trim();
        this.bridgeSecret = getConfig().getString("bridge-secret", "").trim();
        this.guildId = getConfig().getLong("guild-id", 0L);
        this.heartbeatSeconds = Math.max(
            MIN_HEARTBEAT_SECONDS,
            Math.min(MAX_HEARTBEAT_SECONDS, getConfig().getLong("heartbeat-seconds", 15L))
        );
        this.instanceId = UUID.randomUUID().toString();
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(8))
            .build();

        if (!configurationReady()) {
            getLogger().severe(
                "ThePlugBridge is not configured. Fill supabase-url, supabase-anon-key, "
                    + "bridge-secret, and guild-id in plugins/ThePlugBridge/config.yml."
            );
            getServer().getPluginManager().disablePlugin(this);
            return;
        }

        for (Player player : Bukkit.getOnlinePlayers()) {
            joinedAt.put(player.getUniqueId(), Instant.now());
        }

        Bukkit.getPluginManager().registerEvents(this, this);

        long periodTicks = heartbeatSeconds * 20L;
        this.heartbeatTask = Bukkit.getScheduler().runTaskTimer(
            this,
            this::captureAndDispatch,
            40L,
            periodTicks
        );

        getLogger().info(
            "ThePlugBridge " + BRIDGE_VERSION + " enabled; heartbeat every "
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
        String detail = ChatColor.stripColor(event.getDeathMessage() == null ? "" : event.getDeathMessage());
        enqueueEvent(player, "death", detail);
        scheduleFastSync();
    }

    @EventHandler
    public void onAdvancement(PlayerAdvancementDoneEvent event) {
        Player player = event.getPlayer();
        Advancement advancement = event.getAdvancement();
        String detail = advancement.getKey().toString();
        enqueueEvent(player, "advancement", detail);
        scheduleFastSync();
    }

    private void scheduleFastSync() {
        Bukkit.getScheduler().runTaskLater(this, this::captureAndDispatch, 20L);
    }

    private void enqueueEvent(Player player, String eventType, String detail) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("player_uuid", player.getUniqueId().toString());
        row.put("username", resolveUsername(player));
        row.put("event_type", eventType);
        row.put("detail", detail);
        row.put("occurred_at", Instant.now().toString());
        pendingEvents.add(row);

        while (pendingEvents.size() > 250) {
            pendingEvents.poll();
        }
    }

    /**
     * Runs on the server thread. Bukkit/AuraSkills state is captured here before the
     * network request is handed to an async worker.
     */
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

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("p_guild_id", guildId);
        body.put("p_secret", bridgeSecret);
        body.put("p_server", server);
        body.put("p_players", players);
        body.put("p_events", events);
        String jsonBody = gson.toJson(body);

        Bukkit.getScheduler().runTaskAsynchronously(this, () -> sendSnapshot(jsonBody, events));
    }

    private void sendSnapshot(String jsonBody, List<Map<String, Object>> events) {
        try {
            URI endpoint = URI.create(supabaseUrl + "/rest/v1/rpc/the_plug_bridge_ingest");
            HttpRequest request = HttpRequest.newBuilder(endpoint)
                .timeout(Duration.ofSeconds(12))
                .header("apikey", supabaseAnonKey)
                .header("Authorization", "Bearer " + supabaseAnonKey)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                .build();

            HttpResponse<String> response = httpClient.send(
                request,
                HttpResponse.BodyHandlers.ofString()
            );

            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                restoreEvents(events);
                getLogger().warning(
                    "Bridge ingest failed with HTTP " + response.statusCode()
                        + ". Check the Supabase migration, guild ID, and bridge secret."
                );
            }
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            restoreEvents(events);
            getLogger().log(Level.WARNING, "Bridge ingest interrupted", exc);
        } catch (Exception exc) {
            restoreEvents(events);
            getLogger().log(Level.WARNING, "Bridge ingest request failed", exc);
        } finally {
            requestInFlight.set(false);
        }
    }

    private void restoreEvents(List<Map<String, Object>> events) {
        for (Map<String, Object> event : events) {
            pendingEvents.add(event);
        }
        while (pendingEvents.size() > 250) {
            pendingEvents.poll();
        }
    }

    private Map<String, Object> captureServer() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("bridge_instance_id", instanceId);
        row.put("bridge_version", BRIDGE_VERSION);
        row.put("minecraft_version", Bukkit.getMinecraftVersion());
        row.put("paper_version", Bukkit.getVersion());
        row.put("tps", readServerMetric("getTPS", 20.0D, true));
        row.put("mspt", readServerMetric("getAverageTickTime", 0.0D, false));

        Runtime runtime = Runtime.getRuntime();
        long used = runtime.totalMemory() - runtime.freeMemory();
        row.put("memory_used_mb", used / (1024L * 1024L));
        row.put("memory_max_mb", runtime.maxMemory() / (1024L * 1024L));
        row.put("online_players", Bukkit.getOnlinePlayers().size());
        row.put("max_players", Bukkit.getMaxPlayers());

        List<String> plugins = new ArrayList<>();
        for (Plugin plugin : Bukkit.getPluginManager().getPlugins()) {
            plugins.add(plugin.getName() + " " + plugin.getPluginMeta().getVersion());
        }
        row.put("plugins", plugins);
        return row;
    }

    private double readServerMetric(String methodName, double fallback, boolean arrayResult) {
        try {
            Method method = Bukkit.getServer().getClass().getMethod(methodName);
            Object result = method.invoke(Bukkit.getServer());
            if (arrayResult && result instanceof double[] values && values.length > 0) {
                return values[0];
            }
            if (result instanceof Number number) {
                return number.doubleValue();
            }
        } catch (Exception ignored) {
            // Version-safe fallback. The bridge continues even if Paper renames a metric.
        }
        return fallback;
    }

    private Map<String, Object> capturePlayer(Player player) {
        Map<String, Object> row = new LinkedHashMap<>();
        UUID uuid = player.getUniqueId();

        row.put("player_uuid", uuid.toString());
        row.put("username", resolveUsername(player));
        row.put("platform", isBedrock(uuid) ? "bedrock" : "java");
        row.put("discord_user_id", linkedDiscordId(uuid));

        long firstPlayed = player.getFirstPlayed();
        row.put(
            "first_seen",
            firstPlayed > 0L ? Instant.ofEpochMilli(firstPlayed).toString() : Instant.now().toString()
        );
        row.put(
            "joined_at",
            joinedAt.getOrDefault(uuid, Instant.now()).toString()
        );
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
        stats.put("player_kills", statistic(player, "PLAYER_KILLS"));
        stats.put("mob_kills", statistic(player, "MOB_KILLS"));
        stats.put("deaths", statistic(player, "DEATHS"));
        stats.put("jumps", statistic(player, "JUMP"));
        stats.put("walk_cm", statistic(player, "WALK_ONE_CM"));
        stats.put("sprint_cm", statistic(player, "SPRINT_ONE_CM"));
        stats.put("swim_cm", statistic(player, "SWIM_ONE_CM"));
        stats.put("damage_dealt", statistic(player, "DAMAGE_DEALT"));
        stats.put("damage_taken", statistic(player, "DAMAGE_TAKEN"));
        return stats;
    }

    private long playtimeTicks(Player player) {
        long value = statistic(player, "PLAY_ONE_MINUTE");
        if (value <= 0L) {
            value = statistic(player, "PLAY_TIME");
        }
        return Math.max(0L, value);
    }

    private long statistic(Player player, String statisticName) {
        try {
            Statistic statistic = Statistic.valueOf(statisticName);
            return Math.max(0, player.getStatistic(statistic));
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
            getLogger().log(Level.FINE, "AuraSkills data unavailable for " + player.getName(), exc);
        }
        return output;
    }

    private boolean isBedrock(UUID uuid) {
        try {
            Class<?> apiClass = Class.forName("org.geysermc.floodgate.api.FloodgateApi");
            Object api = apiClass.getMethod("getInstance").invoke(null);
            Object result = apiClass.getMethod("isFloodgatePlayer", UUID.class).invoke(api, uuid);
            return result instanceof Boolean value && value;
        } catch (Throwable ignored) {
            return false;
        }
    }

    private String resolveUsername(Player player) {
        if (!isBedrock(player.getUniqueId())) {
            return player.getName();
        }

        try {
            Class<?> apiClass = Class.forName("org.geysermc.floodgate.api.FloodgateApi");
            Object api = apiClass.getMethod("getInstance").invoke(null);
            Object floodgatePlayer = apiClass.getMethod("getPlayer", UUID.class)
                .invoke(api, player.getUniqueId());
            if (floodgatePlayer != null) {
                Method usernameMethod = floodgatePlayer.getClass().getMethod("getUsername");
                Object username = usernameMethod.invoke(floodgatePlayer);
                if (username != null && !username.toString().isBlank()) {
                    return username.toString();
                }
            }
        } catch (Throwable ignored) {
            // Fall through to the server-side Floodgate name.
        }

        String name = player.getName();
        if (name.startsWith(".")) {
            return name.substring(1);
        }
        return name;
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
            if (raw.isEmpty()) {
                return null;
            }
            return Long.parseLong(raw);
        } catch (Throwable ignored) {
            return null;
        }
    }

    private boolean configurationReady() {
        return guildId > 0L
            && !supabaseUrl.isBlank()
            && !supabaseAnonKey.isBlank()
            && bridgeSecret.length() >= 24;
    }

    private String cleanUrl(String value) {
        String url = value == null ? "" : value.trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }
}
