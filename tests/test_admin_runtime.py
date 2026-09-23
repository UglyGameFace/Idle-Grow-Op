import asyncio
from types import SimpleNamespace

from admin import Admin
from profile_signature_contracts import GUILD_PRIVACY_KEY
from world_mode_contracts import (
    MODE_SOLO,
    PLAYER_MODE_SELECTION_KEY,
    POLICY_CHOICE,
    new_world_mode_config,
)


class MemoryDatabase:
    def __init__(self):
        self.lock = asyncio.Lock()
        config = new_world_mode_config()
        config.update(
            {
                "policy": POLICY_CHOICE,
                "default_player_mode": MODE_SOLO,
                "configured": True,
            }
        )
        self.worlds = {123: {"world_mode_config": config}}
        self.profiles = {
            (123, 42): {
                "grams": 99_999,
                "dirty_cash": 8_000,
                "level": 15,
                "xp": 321,
                "items": {"pager": 1},
                "plants": [{"strain": "schwag", "planted_at": 1}],
                "settings": {
                    "notifications": False,
                    "notification_categories": {
                        "plant_ready": False,
                        "lab_ready": True,
                    },
                },
                GUILD_PRIVACY_KEY: {
                    "signature_disabled": True,
                    "hidden_fields": ["wealth"],
                },
                PLAYER_MODE_SELECTION_KEY: {
                    "mode": MODE_SOLO,
                    "selected_at": 100.0,
                    "switch_available_at": 200.0,
                    "explicit": True,
                },
            }
        }
        self.dirty_profiles = set()

    async def get_world(self, guild_id):
        return self.worlds[int(guild_id)]

    async def get_profile(self, scope_id, user_id):
        return self.profiles.setdefault((int(scope_id), int(user_id)), {})

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))


class ContextStub:
    def __init__(self):
        self.author = SimpleNamespace(id=999, name="Owner")
        self.guild = SimpleNamespace(id=123)
        self.channel = SimpleNamespace(id=555)
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def test_wipeuser_resets_gameplay_but_preserves_control_preferences():
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        target = SimpleNamespace(id=42, name="Target")

        async def wait_for(event, *, timeout, check):
            message = SimpleNamespace(
                author=ctx.author,
                channel=ctx.channel,
                content="yes",
            )
            assert event == "message"
            assert timeout == 15.0
            assert check(message) is True
            return message

        bot = SimpleNamespace(db=db, wait_for=wait_for)
        cog = Admin(bot)

        await Admin.wipeuser.callback(cog, ctx, target)

        profile = db.profiles[(123, 42)]
        assert profile["grams"] == 500
        assert profile["dirty_cash"] == 0
        assert profile["level"] == 1
        assert profile["xp"] == 0
        assert profile["items"] == {}
        assert profile["plants"] == []

        assert profile["settings"] == {
            "notifications": False,
            "notification_categories": {
                "plant_ready": False,
                "lab_ready": True,
            },
        }
        assert profile[GUILD_PRIVACY_KEY] == {
            "signature_disabled": True,
            "hidden_fields": ["wealth"],
        }
        assert profile[PLAYER_MODE_SELECTION_KEY] == {
            "mode": MODE_SOLO,
            "selected_at": 100.0,
            "switch_available_at": 200.0,
            "explicit": True,
        }
        assert db.dirty_profiles == {(123, 42)}
        assert "Wiped Target" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_setmoney_mutates_only_target_active_profile():
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        target = SimpleNamespace(id=42, name="Target")
        cog = Admin(SimpleNamespace(db=db))

        await Admin.setmoney.callback(cog, ctx, target, 1_234)

        profile = db.profiles[(123, 42)]
        assert profile["grams"] == 1_234
        assert db.dirty_profiles == {(123, 42)}
        assert "$1,234" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_setmoney_rejects_negative_balance_without_mutation():
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        target = SimpleNamespace(id=42, name="Target")
        cog = Admin(SimpleNamespace(db=db))
        before = dict(db.profiles[(123, 42)])

        await Admin.setmoney.callback(cog, ctx, target, -1)

        assert db.profiles[(123, 42)] == before
        assert db.dirty_profiles == set()
        assert "cannot be negative" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_giveitem_and_setlevel_apply_validated_owner_mutations():
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        target = SimpleNamespace(id=42, name="Target")
        cog = Admin(SimpleNamespace(db=db))

        await Admin.giveitem.callback(cog, ctx, target, "Pager", 3)
        await Admin.setlevel.callback(cog, ctx, target, 7)

        profile = db.profiles[(123, 42)]
        assert profile["items"]["pager"] == 4
        assert profile["level"] == 7
        assert profile["xp"] == 0
        assert db.dirty_profiles == {(123, 42)}

    asyncio.run(scenario())


def test_giveitem_and_setlevel_reject_non_positive_amounts():
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        target = SimpleNamespace(id=42, name="Target")
        cog = Admin(SimpleNamespace(db=db))
        before = {
            "items": dict(db.profiles[(123, 42)]["items"]),
            "level": db.profiles[(123, 42)]["level"],
            "xp": db.profiles[(123, 42)]["xp"],
        }

        await Admin.giveitem.callback(cog, ctx, target, "pager", 0)
        await Admin.setlevel.callback(cog, ctx, target, 0)

        profile = db.profiles[(123, 42)]
        assert profile["items"] == before["items"]
        assert profile["level"] == before["level"]
        assert profile["xp"] == before["xp"]
        assert db.dirty_profiles == set()

    asyncio.run(scenario())
