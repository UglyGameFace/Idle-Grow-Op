import asyncio
from types import SimpleNamespace

from social import Social
from world_mode_contracts import POLICY_SERVER, new_world_mode_config


class MemoryDatabase:
    def __init__(self):
        self.lock = asyncio.Lock()
        config = new_world_mode_config()
        config.update({"policy": POLICY_SERVER, "configured": True})
        self.world = {
            "world_mode_config": config,
            "crews": {},
            "district": {
                "owner_crew_id": None,
                "owner_name": None,
                "multiplier": 1.0,
                "expires_at": 0,
            },
        }
        self.profiles = {}
        self.dirty_profiles = set()
        self.dirty_worlds = set()

    async def get_world(self, scope_id):
        return self.world

    async def get_profile(self, scope_id, user_id):
        return self.profiles.setdefault((int(scope_id), int(user_id)), {})

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))

    def mark_world_dirty(self, scope_id):
        self.dirty_worlds.add(int(scope_id))


class ContextStub:
    def __init__(self, user_id=42):
        self.author = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
        self.guild = SimpleNamespace(id=123)
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def test_crew_member_can_leave_without_destroying_bank():
    async def scenario():
        db = MemoryDatabase()
        db.profiles[(123, 42)] = {"crew_id": "12345", "grams": 1_000}
        db.world["crews"] = {
            "12345": {
                "id": "12345",
                "name": "Test Crew",
                "owner_id": 77,
                "members": [77, 42],
                "bank": 5_000,
                "level": 1,
            }
        }
        ctx = ContextStub()
        cog = Social(SimpleNamespace(db=db))

        await Social.crew_leave.callback(cog, ctx)

        crew = db.world["crews"]["12345"]
        assert db.profiles[(123, 42)]["crew_id"] is None
        assert crew["members"] == [77]
        assert crew["owner_id"] == 77
        assert crew["bank"] == 5_000
        assert db.dirty_profiles == {(123, 42)}
        assert db.dirty_worlds == {123}

    asyncio.run(scenario())


def test_crew_owner_leave_transfers_ownership_to_remaining_member():
    async def scenario():
        db = MemoryDatabase()
        db.profiles[(123, 42)] = {"crew_id": "12345", "grams": 1_000}
        db.world["crews"] = {
            "12345": {
                "id": "12345",
                "name": "Test Crew",
                "owner_id": 42,
                "members": [42, 77],
                "bank": 5_000,
                "level": 1,
            }
        }
        ctx = ContextStub()
        cog = Social(SimpleNamespace(db=db))

        await Social.crew_leave.callback(cog, ctx)

        crew = db.world["crews"]["12345"]
        assert db.profiles[(123, 42)]["crew_id"] is None
        assert crew["owner_id"] == 77
        assert crew["members"] == [77]
        assert crew["bank"] == 5_000
        assert "Ownership transferred" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_last_crew_member_disbands_refunds_bank_and_clears_district():
    async def scenario():
        db = MemoryDatabase()
        db.profiles[(123, 42)] = {"crew_id": "12345", "grams": 1_000}
        db.world["crews"] = {
            "12345": {
                "id": "12345",
                "name": "Test Crew",
                "owner_id": 42,
                "members": [42],
                "bank": 5_000,
                "level": 1,
            }
        }
        db.world["district"] = {
            "owner_crew_id": "12345",
            "owner_name": "Test Crew",
            "multiplier": 1.10,
            "expires_at": 9999999999,
        }
        ctx = ContextStub()
        cog = Social(SimpleNamespace(db=db))

        await Social.crew_leave.callback(cog, ctx)

        profile = db.profiles[(123, 42)]
        assert profile["crew_id"] is None
        assert profile["grams"] == 6_000
        assert "12345" not in db.world["crews"]
        assert db.world["district"] == {
            "owner_crew_id": None,
            "owner_name": None,
            "multiplier": 1.0,
            "expires_at": 0,
        }
        assert "Returned **$5,000**" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_stale_crew_membership_self_repairs_without_touching_world():
    async def scenario():
        db = MemoryDatabase()
        db.profiles[(123, 42)] = {"crew_id": "missing", "grams": 1_000}
        ctx = ContextStub()
        cog = Social(SimpleNamespace(db=db))

        await Social.crew_leave.callback(cog, ctx)

        assert db.profiles[(123, 42)]["crew_id"] is None
        assert db.dirty_profiles == {(123, 42)}
        assert db.dirty_worlds == set()
        assert "Cleared stale crew membership" in ctx.sent[-1][0][0]

    asyncio.run(scenario())
