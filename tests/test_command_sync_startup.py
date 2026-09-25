import asyncio
from pathlib import Path
from types import SimpleNamespace
import discord
import pytest

import main
from scoped_database import ScopedDatabaseManager


ROOT = Path(__file__).resolve().parents[1]

CONSOLIDATED_GAMEPLAY_COMMANDS = {
    "heist",
    "launder",
    "heat",
    "heiststats",
    "topheists",
    "heistset",
    "sellconc",
    "auction",
    "bid",
    "conc",
    "crew",
    "district",
}


ADVERTISED_PUBLIC_COMMAND_PATHS = {
    "help",
    "game",
    "menu",
    "play",
    "start",
    "setup",
    "chat",
    "profile",
    "profile-settings",
    "notifications",
    "world-mode",
    "balance",
    "give",
    "leaderboard",
    "inventory",
    "shop",
    "buy",
    "sell",
    "sellconc",
    "auction",
    "auction list",
    "bid",
    "plant",
    "harvest",
    "status",
    "strains",
    "process",
    "collect",
    "conc",
    "lab",
    "growdaily",
    "growclaim",
    "growcheckin",
    "growquests",
    "growachievements",
    "growlevel",
    "qhelp",
    "quick",
    "cooldowns",
    "ready",
    "calc",
    "qplant",
    "heist",
    "steal",
    "launder",
    "heat",
    "heiststats",
    "topheists",
    "heistset",
    "crew",
    "crew create",
    "crew join",
    "crew leave",
    "crew info",
    "crew deposit",
    "crew war",
    "district",
    "casino",
    "casinolb",
    "coinflip",
    "slots",
    "dice",
    "hilo",
    "rps",
    "cups",
    "keno",
    "crash",
    "wheel",
    "blackjack",
    "roulette",
    "sesh",
    "movie",
    "karaoke",
    "seshmove",
    "seshconfig",
    "seshconfig disable",
}

REMOVED_OR_NEVER_IMPLEMENTED_PUBLIC_PATHS = {
    "water",
    "tasks",
    "appeal",
    "bail",
    "sesh_setup",
}


class FakeTree:
    def __init__(self, commands, *, sync_effects=None):
        self._commands = list(commands)
        self._sync_effects = list(sync_effects or [self._commands])
        self.sync_calls = 0

    def get_commands(self):
        return list(self._commands)

    async def sync(self):
        self.sync_calls += 1
        effect = self._sync_effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return list(effect)


def command_set(*extra_names: str):
    names = set(main.REQUIRED_PUBLIC_COMMANDS)
    names.update(extra_names)
    return [SimpleNamespace(name=name) for name in sorted(names)]


def test_global_sync_publishes_required_commands_once():
    tree = FakeTree(command_set("shop", "plant", "sesh"))

    synced = asyncio.run(main.sync_global_commands(tree))

    assert tree.sync_calls == 1
    assert main.REQUIRED_PUBLIC_COMMANDS <= {command.name for command in synced}
    assert "sesh_setup" not in {command.name for command in synced}


def test_global_sync_retries_temporary_discord_http_failure(monkeypatch):
    class FakeHTTPException(Exception):
        pass

    monkeypatch.setattr(main.discord, "HTTPException", FakeHTTPException)
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    commands = command_set("shop")
    tree = FakeTree(
        commands,
        sync_effects=[FakeHTTPException("temporary"), commands],
    )

    synced = asyncio.run(main.sync_global_commands(tree))

    assert tree.sync_calls == 2
    assert sleep_calls == [main.COMMAND_SYNC_RETRY_SECONDS]
    assert {command.name for command in synced} >= main.REQUIRED_PUBLIC_COMMANDS


def test_global_sync_rejects_partial_or_unexpected_publication():
    local_commands = command_set("shop", "plant")
    incomplete_remote = command_set("shop")
    extra_remote = command_set("shop", "plant", "ghost")

    with pytest.raises(RuntimeError, match="complete local command tree"):
        asyncio.run(
            main.sync_global_commands(
                FakeTree(local_commands, sync_effects=[incomplete_remote])
            )
        )

    with pytest.raises(RuntimeError, match="complete local command tree"):
        asyncio.run(
            main.sync_global_commands(
                FakeTree(local_commands, sync_effects=[extra_remote])
            )
        )


def test_global_sync_blocks_startup_after_bounded_failures(monkeypatch):
    class FakeHTTPException(Exception):
        pass

    monkeypatch.setattr(main.discord, "HTTPException", FakeHTTPException)

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    commands = command_set()
    tree = FakeTree(
        commands,
        sync_effects=[
            FakeHTTPException("one"),
            FakeHTTPException("two"),
            FakeHTTPException("three"),
        ],
    )

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        asyncio.run(main.sync_global_commands(tree))

    assert tree.sync_calls == main.COMMAND_SYNC_ATTEMPTS


def test_setup_hook_schedules_sync_without_blocking_gateway(monkeypatch):
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def sync(tree):
            assert tree is bot.tree
            started.set()
            await release.wait()
            return command_set()

        monkeypatch.setattr(main, "sync_global_commands", sync)
        bot = main.IdleGrowBot(
            command_prefix="!",
            intents=discord.Intents.none(),
            help_command=None,
        )

        await bot.setup_hook()
        await asyncio.wait_for(started.wait(), timeout=1)

        assert bot.command_sync_task is not None
        assert not bot.command_sync_task.done()
        assert bot.command_sync_succeeded is None

        release.set()
        await bot.command_sync_task

        assert bot.command_sync_succeeded is True

    asyncio.run(scenario())


def test_background_sync_failure_does_not_abort_bot_startup(monkeypatch):
    async def scenario():
        async def fail_sync(_tree):
            raise RuntimeError("simulated Discord sync failure")

        monkeypatch.setattr(main, "sync_global_commands", fail_sync)
        bot = main.IdleGrowBot(
            command_prefix="!",
            intents=discord.Intents.none(),
            help_command=None,
        )

        await bot.setup_hook()
        assert bot.command_sync_task is not None
        await bot.command_sync_task

        assert bot.command_sync_succeeded is False

    asyncio.run(scenario())


class SmokeBackend:
    async def load(self, key):
        return None

    async def save_many(self, records):
        return None

    async def list_guild_leaderboard(self, guild_id, *, limit=10):
        return []

    async def list_guild_heist_leaderboard(self, guild_id, *, limit=10):
        return []

    async def list_guild_casino_leaderboard(
        self,
        guild_id,
        *,
        metric="casino_total_profit",
        limit=10,
    ):
        return []

    async def list_notification_candidates(self, guild_ids):
        return []


def _flatten_command_paths(commands, prefix: str = ""):
    paths = set()
    for command in commands:
        path = f"{prefix} {command.name}".strip()
        paths.add(path)
        children = getattr(command, "commands", None)
        if children:
            paths.update(_flatten_command_paths(children, path))
    return paths


async def _loaded_command_paths():
    database = ScopedDatabaseManager(SmokeBackend(), flush_interval=3600)
    await database.start()
    bot = main.IdleGrowBot(
        command_prefix="!",
        intents=discord.Intents.none(),
        help_command=None,
    )
    bot.db = database
    try:
        async with bot:
            for extension_name in main.GAME_EXTENSIONS:
                await bot.load_extension(extension_name)
            return _flatten_command_paths(bot.tree.get_commands())
    finally:
        await database.close()


async def _loaded_command_names():
    database = ScopedDatabaseManager(SmokeBackend(), flush_interval=3600)
    await database.start()
    bot = main.IdleGrowBot(
        command_prefix="!",
        intents=discord.Intents.none(),
        help_command=None,
    )
    bot.db = database
    try:
        async with bot:
            for extension_name in main.GAME_EXTENSIONS:
                await bot.load_extension(extension_name)
            return {command.name for command in bot.tree.get_commands()}
    finally:
        await database.close()


def test_loaded_tree_contains_every_advertised_public_command_path():
    paths = asyncio.run(_loaded_command_paths())

    assert ADVERTISED_PUBLIC_COMMAND_PATHS <= paths
    assert REMOVED_OR_NEVER_IMPLEMENTED_PUBLIC_PATHS.isdisjoint(paths)


def test_complete_extension_tree_contains_public_entry_points_and_no_stale_sesh_setup():
    names = asyncio.run(_loaded_command_names())

    assert main.REQUIRED_PUBLIC_COMMANDS <= names
    assert CONSOLIDATED_GAMEPLAY_COMMANDS <= names
    assert "sesh_setup" not in names
    assert "water" not in names
    assert len(names) > len(main.REQUIRED_PUBLIC_COMMANDS)


def test_extensions_load_before_start_and_sync_is_not_repeated_in_on_ready():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert source.index("await load_extensions()") < source.index("await bot.start(TOKEN)")

    setup_hook = source.split("async def setup_hook", 1)[1].split(
        "intents = discord.Intents.default()", 1
    )[0]
    on_ready = source.split("async def on_ready", 1)[1].split(
        "async def load_extensions", 1
    )[0]

    assert "asyncio.create_task" in setup_hook
    assert "await sync_global_commands" not in setup_hook
    assert "tree.sync" not in on_ready
