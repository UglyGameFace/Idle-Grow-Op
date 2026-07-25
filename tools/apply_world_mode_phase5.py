from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def append_world_mode_policy_helpers() -> None:
    path = ROOT / "world_modes.py"
    source = path.read_text(encoding="utf-8")
    if "def policy_uses_local_world" in source:
        return
    source = source.rstrip() + '''


def _policy_value(policy_or_config) -> str:
    if isinstance(policy_or_config, dict):
        return normalize_world_mode_config(policy_or_config).get(POLICY_KEY, POLICY_SERVER)
    return str(policy_or_config or POLICY_SERVER)


def policy_uses_local_world(policy_or_config) -> bool:
    """Return whether this server still has an active guild-local game world."""
    return _policy_value(policy_or_config) in {
        POLICY_SOLO,
        POLICY_CHOICE,
        POLICY_SERVER,
    }


def policy_allows_open_world(policy_or_config) -> bool:
    """Return whether this server participates in the shared Open World."""
    return _policy_value(policy_or_config) in {
        POLICY_OPEN,
        POLICY_CHOICE,
    }
'''
    path.write_text(source + "\n", encoding="utf-8")


def method_source(source: str, node: ast.AsyncFunctionDef) -> tuple[str, str]:
    lines = source.splitlines(keepends=True)
    decorator_start = min(
        [decorator.lineno for decorator in node.decorator_list] or [node.lineno]
    )
    whole = "".join(lines[decorator_start - 1 : node.end_lineno])
    function = "".join(lines[node.lineno - 1 : node.end_lineno])
    decorators = "".join(lines[decorator_start - 1 : node.lineno - 1])
    return whole, decorators + function


def rewrite_loop_method(
    source: str,
    *,
    method_name: str,
    helper_name: str,
    wrapper_body: str,
    inject_candidate_filter: bool = False,
) -> str:
    tree = ast.parse(source)
    tasks_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Tasks"
    )
    method = next(
        node
        for node in tasks_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name
    )
    lines = source.splitlines(keepends=True)
    decorator_start = min(
        [decorator.lineno for decorator in method.decorator_list] or [method.lineno]
    )
    whole = "".join(lines[decorator_start - 1 : method.end_lineno])
    decorators = "".join(lines[decorator_start - 1 : method.lineno - 1])
    function = "".join(lines[method.lineno - 1 : method.end_lineno])
    function = re.sub(
        rf"async def {method_name}\(self\)\s*->?[^:]*:",
        f"async def {helper_name}(self, guilds):",
        function,
        count=1,
    )
    if f"async def {helper_name}(self, guilds):" not in function:
        function = function.replace(
            f"async def {method_name}(self):",
            f"async def {helper_name}(self, guilds):",
            1,
        )
    replaced = 0
    for pattern in (
        r"for guild in list\(self\.bot\.guilds\):",
        r"for guild in self\.bot\.guilds:",
    ):
        function, count = re.subn(pattern, "for guild in guilds:", function, count=1)
        if count:
            replaced = count
            break
    if replaced != 1:
        raise RuntimeError(f"Could not locate the guild loop in {method_name}")

    if inject_candidate_filter:
        candidate_patterns = (
            r"(?P<indent>\s*)for user_id, profile in candidates:\n",
            r"(?P<indent>\s*)for user_id, data in candidates:\n",
        )
        for pattern in candidate_patterns:
            match = re.search(pattern, function)
            if match:
                indent = match.group("indent")
                child = indent + "    "
                filter_code = (
                    match.group(0)
                    + child
                    + "guild_id = getattr(guild, \"source_guild_id\", guild.id)\n"
                    + child
                    + "if hasattr(guild, \"resolve_player_scope\"):\n"
                    + child
                    + "    scope = await guild.resolve_player_scope(self.bot.db, user_id)\n"
                    + child
                    + "    if scope is None or scope.scope_id != guild.id:\n"
                    + child
                    + "        continue\n"
                    + child
                    + "else:\n"
                    + child
                    + "    scope = await resolve_game_scope(self.bot.db, guild_id, user_id)\n"
                    + child
                    + "    if scope.scope_id != guild_id:\n"
                    + child
                    + "        continue\n"
                )
                function = function[: match.start()] + filter_code + function[match.end() :]
                break
        else:
            raise RuntimeError("Could not locate notification candidate iteration")

    wrapper = decorators + f"    async def {method_name}(self):\n" + wrapper_body
    return source.replace(whole, function + "\n" + wrapper, 1)


def patch_tasks() -> None:
    path = ROOT / "tasks.py"
    source = path.read_text(encoding="utf-8")
    if "class _WorldGuildProxy" in source:
        return

    import_anchor = "from discord.ext import commands, tasks\n"
    if import_anchor not in source:
        import_anchor = "from discord.ext import tasks\n"
    if import_anchor not in source:
        raise RuntimeError("Could not locate tasks imports")
    mode_import = '''from world_modes import (
    OPEN_WORLD_SCOPE_ID,
    normalize_world_mode_config,
    policy_allows_open_world,
    policy_uses_local_world,
    resolve_game_scope,
)
'''
    source = source.replace(import_anchor, import_anchor + mode_import, 1)

    class_anchor = "class Tasks(commands.Cog):"
    if class_anchor not in source:
        raise RuntimeError("Could not locate Tasks class")
    proxy = '''class _WorldGuildProxy:
    """Delegate Discord operations to one guild while overriding the game scope ID."""

    def __init__(self, primary_guild, scope_id: int, member_guilds) -> None:
        self._primary_guild = primary_guild
        self.id = int(scope_id)
        self.source_guild_id = int(primary_guild.id)
        self.member_guilds = tuple(member_guilds)

    def __getattr__(self, name):
        return getattr(self._primary_guild, name)

    def get_member(self, user_id: int):
        for guild in self.member_guilds:
            member = guild.get_member(int(user_id))
            if member is not None:
                return member
        return None

    async def resolve_player_scope(self, database, user_id: int):
        for guild in self.member_guilds:
            if guild.get_member(int(user_id)) is None:
                continue
            scope = await resolve_game_scope(database, guild.id, int(user_id))
            if scope.scope_id == self.id:
                return scope
        return None


'''
    source = source.replace(class_anchor, proxy + class_anchor, 1)

    helper_anchor = "class Tasks(commands.Cog):\n"
    class_helpers = '''class Tasks(commands.Cog):
    async def _open_world_notification_guild(self, guilds):
        for guild in guilds:
            world = await self.bot.db.get_world(guild.id)
            settings = world.get("settings", {}) if isinstance(world, dict) else {}
            for key in ("announcement_channel_id", "game_channel_id"):
                channel_id = settings.get(key)
                if channel_id and guild.get_channel(int(channel_id)) is not None:
                    return guild
        return guilds[0] if guilds else None

    async def _sync_open_world_routing(self, guild) -> None:
        if guild is None:
            return
        local_world = await self.bot.db.get_world(guild.id)
        global_world = await self.bot.db.get_world(OPEN_WORLD_SCOPE_ID)
        local_settings = local_world.get("settings", {}) if isinstance(local_world, dict) else {}
        global_settings = global_world.setdefault("settings", {})
        changed = False
        for key in ("announcement_channel_id", "game_channel_id"):
            value = local_settings.get(key)
            if value and global_settings.get(key) != value:
                global_settings[key] = value
                changed = True
        if changed:
            self.bot.db.mark_world_dirty(OPEN_WORLD_SCOPE_ID)

    async def _active_cycle_guilds(self):
        local_guilds = []
        open_world_guilds = []
        for guild in list(self.bot.guilds):
            world = await self.bot.db.get_world(guild.id)
            config = normalize_world_mode_config(world.get("world_mode_config"))
            if policy_uses_local_world(config):
                local_guilds.append(guild)
            if policy_allows_open_world(config):
                open_world_guilds.append(guild)
        return local_guilds, open_world_guilds

'''
    source = source.replace(helper_anchor, class_helpers, 1)

    game_wrapper = '''        local_guilds, open_world_guilds = await self._active_cycle_guilds()
        cycle_guilds = list(local_guilds)
        open_world_processed = False
        if open_world_guilds and not open_world_processed:
            routing_guild = await self._open_world_notification_guild(open_world_guilds)
            await self._sync_open_world_routing(routing_guild)
            cycle_guilds.append(
                _WorldGuildProxy(
                    routing_guild,
                    OPEN_WORLD_SCOPE_ID,
                    open_world_guilds,
                )
            )
            open_world_processed = True
        await self._run_game_cycle_for(cycle_guilds)
'''
    source = rewrite_loop_method(
        source,
        method_name="game_cycle",
        helper_name="_run_game_cycle_for",
        wrapper_body=game_wrapper,
    )

    notification_wrapper = '''        local_guilds, open_world_guilds = await self._active_cycle_guilds()
        notification_guilds = list(local_guilds)
        open_world_processed = False
        if open_world_guilds and not open_world_processed:
            routing_guild = await self._open_world_notification_guild(open_world_guilds)
            await self._sync_open_world_routing(routing_guild)
            notification_guilds.append(
                _WorldGuildProxy(
                    routing_guild,
                    OPEN_WORLD_SCOPE_ID,
                    open_world_guilds,
                )
            )
            open_world_processed = True
        await self._run_notification_check_for(notification_guilds)
'''
    source = rewrite_loop_method(
        source,
        method_name="notification_check",
        helper_name="_run_notification_check_for",
        wrapper_body=notification_wrapper,
        inject_candidate_filter=True,
    )
    path.write_text(source, encoding="utf-8")


append_world_mode_policy_helpers()
patch_tasks()
