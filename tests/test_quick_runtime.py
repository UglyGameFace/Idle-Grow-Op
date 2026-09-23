import asyncio
from types import SimpleNamespace

from quick import Quick
from world_modes import POLICY_SOLO, new_world_mode_config


class MemoryDatabase:
    def __init__(self):
        self.worlds = {}
        self.profiles = {}

    async def get_world(self, scope_id):
        return self.worlds.setdefault(int(scope_id), {})

    async def get_profile(self, scope_id, user_id):
        return self.profiles.setdefault((int(scope_id), int(user_id)), {})


class ContextStub:
    def __init__(self, guild_id: int, user_id: int):
        self.guild = SimpleNamespace(id=guild_id)
        self.author = SimpleNamespace(id=user_id)
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def test_calc_uses_resolved_game_scope_for_effective_market_multiplier():
    async def scenario():
        guild_id = 123456789012345678
        user_id = 42
        database = MemoryDatabase()
        database.worlds[guild_id] = {
            "world_mode_config": {
                **new_world_mode_config(),
                "policy": POLICY_SOLO,
                "configured": True,
            },
            "market_multiplier": 2.5,
        }
        database.profiles[(guild_id, user_id)] = {"level": 1}

        bot = SimpleNamespace(db=database)
        ctx = ContextStub(guild_id, user_id)
        cog = Quick(bot)

        await Quick.calc.callback(cog, ctx, strain="schwag")

        assert len(ctx.sent) == 1
        embed = ctx.sent[0][1]["embed"]
        assert embed.title == "📊 Analysis: Schwag"
        assert embed.footer.text == "Current Market: 125%"

    asyncio.run(scenario())
