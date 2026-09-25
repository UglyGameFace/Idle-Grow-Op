import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from discord.ext import commands

import main
from persistence_context import GuildContextRequired


class PrefixContext:
    def __init__(self):
        self.sent = []
        self.guild = None
        self.channel = SimpleNamespace(id=999)
        self.author = SimpleNamespace(id=42)
        self.command = SimpleNamespace(qualified_name="harvest")

    async def send(self, message):
        self.sent.append(message)


def test_prefix_server_only_rejection_is_user_facing_not_reported(monkeypatch):
    async def scenario():
        ctx = PrefixContext()
        reporter = AsyncMock()
        monkeypatch.setattr(main, "_report_error", reporter)

        error = commands.CommandInvokeError(
            GuildContextRequired(
                "Idle Grow game commands can only be used inside a server"
            )
        )
        await main.on_command_error(ctx, error)

        assert ctx.sent == [
            "❌ Idle Grow game commands can only be used inside a server."
        ]
        reporter.assert_not_awaited()

    asyncio.run(scenario())


class Response:
    def __init__(self, *, done=False):
        self.done = done
        self.messages = []

    def is_done(self):
        return self.done

    async def send_message(self, message, *, ephemeral=False):
        self.messages.append((message, ephemeral))
        self.done = True


class Followup:
    def __init__(self):
        self.messages = []

    async def send(self, message, *, ephemeral=False):
        self.messages.append((message, ephemeral))


def test_slash_server_only_rejection_is_user_facing_not_reported(monkeypatch):
    async def scenario():
        response = Response()
        followup = Followup()
        interaction = SimpleNamespace(
            command=SimpleNamespace(qualified_name="harvest"),
            guild_id=None,
            channel_id=999,
            user=SimpleNamespace(id=42),
            response=response,
            followup=followup,
        )
        reporter = AsyncMock()
        monkeypatch.setattr(main, "_report_error", reporter)

        error = SimpleNamespace(
            original=GuildContextRequired(
                "Idle Grow game commands can only be used inside a server"
            )
        )
        await main._tree_error(interaction, error)

        assert response.messages == [
            ("❌ Idle Grow game commands can only be used inside a server.", True)
        ]
        assert followup.messages == []
        reporter.assert_not_awaited()

    asyncio.run(scenario())


def test_slash_server_only_rejection_uses_followup_after_ack(monkeypatch):
    async def scenario():
        response = Response(done=True)
        followup = Followup()
        interaction = SimpleNamespace(
            command=SimpleNamespace(qualified_name="harvest"),
            guild_id=None,
            channel_id=999,
            user=SimpleNamespace(id=42),
            response=response,
            followup=followup,
        )
        reporter = AsyncMock()
        monkeypatch.setattr(main, "_report_error", reporter)

        error = SimpleNamespace(
            original=GuildContextRequired(
                "Idle Grow game commands can only be used inside a server"
            )
        )
        await main._tree_error(interaction, error)

        assert response.messages == []
        assert followup.messages == [
            ("❌ Idle Grow game commands can only be used inside a server.", True)
        ]
        reporter.assert_not_awaited()

    asyncio.run(scenario())
