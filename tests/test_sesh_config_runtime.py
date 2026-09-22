import asyncio
from types import SimpleNamespace

from sesh import SESH_CONFIG_KEY, Sesh


class MemoryDatabase:
    def __init__(self):
        self.worlds = {123: {"unrelated": True}}
        self.lock = asyncio.Lock()
        self.dirty_worlds = set()

    async def get_world(self, guild_id):
        return self.worlds.setdefault(int(guild_id), {})

    def mark_world_dirty(self, guild_id):
        self.dirty_worlds.add(int(guild_id))


def test_sesh_config_read_does_not_mutate_or_dirty_world():
    async def scenario():
        db = MemoryDatabase()
        cog = Sesh(SimpleNamespace(db=db))

        world, config = await cog._guild_config(123)

        assert config == {}
        assert world == {"unrelated": True}
        assert SESH_CONFIG_KEY not in db.worlds[123]
        assert not db.dirty_worlds

    asyncio.run(scenario())
