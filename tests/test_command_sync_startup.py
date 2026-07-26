import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

import main
from scoped_database import ScopedDatabaseManager


ROOT = Path(__file__).resolve().parents[1]


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


def test_native_setup_hook_uses_the_canonical_sync_path(monkeypatch):
    sync = AsyncMock(return_value=command_set())
    monkeypatch.setattr(main, "sync_global_commands", sync)
    bot = main.IdleGrowBot(
        command_prefix="!",
        intents=discord.Intents.none(),
        help_command=None,
    )

    asyncio.run(bot.setup_hook())

    sync.assert_awaited_once_with(bot.tree)


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

    async def list_guild_notification_candidates(self, guild_id, *, limit=500):
        return []


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


def test_complete_extension_tree_contains_public_entry_points_and_no_stale_sesh_setup():
    names = asyncio.run(_loaded_command_names())

    assert main.REQUIRED_PUBLIC_COMMANDS <= names
    assert "sesh_setup" not in names
    assert len(names) > len(main.REQUIRED_PUBLIC_COMMANDS)


def test_extensions_load_before_start_and_sync_is_not_repeated_in_on_ready():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert source.index("await load_extensions()") < source.index("await bot.start(TOKEN)")

    on_ready = source.split("async def on_ready", 1)[1].split(
        "async def load_extensions", 1
    )[0]
    assert "tree.sync" not in on_ready
    assert "async def setup_hook" in source
