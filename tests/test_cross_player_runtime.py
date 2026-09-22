import asyncio
from types import SimpleNamespace

import pytest

import crime as crime_module
from crime import Crime
from economy import Economy
from world_mode_contracts import POLICY_SERVER, new_world_mode_config


class MemoryDatabase:
    def __init__(self, *, fail_user_id=None):
        self.lock = asyncio.Lock()
        config = new_world_mode_config()
        config.update({"policy": POLICY_SERVER, "configured": True})
        self.worlds = {123: {"world_mode_config": config}}
        self.profiles = {
            (123, 42): {
                "grams": 1_000,
                "dirty_cash": 0,
                "heat": 0,
                "jail_until": 0,
                "items": {},
                "stats": {},
                "achievements": [],
                "level": 1,
                "xp": 0,
            },
            (123, 77): {
                "grams": 500,
                "dirty_cash": 0,
                "heat": 0,
                "jail_until": 0,
                "items": {},
                "stats": {},
                "achievements": [],
                "level": 1,
                "xp": 0,
            },
        }
        self.fail_user_id = fail_user_id
        self.dirty_profiles = set()

    async def get_world(self, scope_id):
        return self.worlds[int(scope_id)]

    async def get_profile(self, scope_id, user_id):
        user_id = int(user_id)
        if user_id == self.fail_user_id:
            raise RuntimeError("simulated profile load failure")
        return self.profiles[(int(scope_id), user_id)]

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))


class CommandStub:
    def __init__(self):
        self.reset_count = 0

    def reset_cooldown(self, _ctx):
        self.reset_count += 1


class ContextStub:
    def __init__(self):
        self.author = SimpleNamespace(id=42, name="Actor", mention="<@42>")
        self.guild = SimpleNamespace(id=123)
        self.command = CommandStub()
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def target():
    return SimpleNamespace(id=77, name="Target", mention="<@77>")


def test_give_conserves_value_across_sender_and_receiver():
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        cog = Economy(SimpleNamespace(db=db))

        before_total = db.profiles[(123, 42)]["grams"] + db.profiles[(123, 77)]["grams"]

        await Economy.give.callback(cog, ctx, target(), 300)

        assert db.profiles[(123, 42)]["grams"] == 700
        assert db.profiles[(123, 77)]["grams"] == 800
        assert db.profiles[(123, 42)]["grams"] + db.profiles[(123, 77)]["grams"] == before_total
        assert db.dirty_profiles == {(123, 42), (123, 77)}
        assert "Transferred" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_give_receiver_load_failure_does_not_debit_sender():
    async def scenario():
        db = MemoryDatabase(fail_user_id=77)
        ctx = ContextStub()
        cog = Economy(SimpleNamespace(db=db))
        sender_before = dict(db.profiles[(123, 42)])

        with pytest.raises(RuntimeError, match="simulated profile load failure"):
            await Economy.give.callback(cog, ctx, target(), 300)

        assert db.profiles[(123, 42)] == sender_before
        assert db.dirty_profiles == set()

    asyncio.run(scenario())


def test_give_insufficient_funds_leaves_both_profiles_unchanged():
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        cog = Economy(SimpleNamespace(db=db))
        sender_before = dict(db.profiles[(123, 42)])
        receiver_before = dict(db.profiles[(123, 77)])

        await Economy.give.callback(cog, ctx, target(), 2_000)

        assert db.profiles[(123, 42)] == sender_before
        assert db.profiles[(123, 77)] == receiver_before
        assert db.dirty_profiles == set()
        assert "Insufficient funds" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_successful_steal_conserves_victim_wallet_into_dirty_cash(monkeypatch):
    async def scenario():
        db = MemoryDatabase()
        ctx = ContextStub()
        cog = Crime(SimpleNamespace(db=db))

        monkeypatch.setattr(crime_module.random, "random", lambda: 0.0)
        monkeypatch.setattr(crime_module.random, "uniform", lambda _a, _b: 0.20)
        monkeypatch.setattr(crime_module, "add_progress", lambda *args, **kwargs: None)
        monkeypatch.setattr(crime_module, "check_achievements", lambda *args, **kwargs: [])

        before_value = (
            db.profiles[(123, 77)]["grams"]
            + db.profiles[(123, 42)]["dirty_cash"]
        )

        await Crime.steal.callback(cog, ctx, target())

        robber = db.profiles[(123, 42)]
        victim = db.profiles[(123, 77)]
        assert victim["grams"] == 400
        assert robber["dirty_cash"] == 100
        assert victim["grams"] + robber["dirty_cash"] == before_value
        assert robber["stats"]["steals"] == 1
        assert db.dirty_profiles == {(123, 42), (123, 77)}
        assert "SUCCESS" in ctx.sent[-1][0][0]

    asyncio.run(scenario())


def test_too_poor_robbery_target_causes_zero_partial_mutation(monkeypatch):
    async def scenario():
        db = MemoryDatabase()
        db.profiles[(123, 77)]["grams"] = 50
        ctx = ContextStub()
        cog = Crime(SimpleNamespace(db=db))

        monkeypatch.setattr(crime_module.random, "random", lambda: 0.0)
        monkeypatch.setattr(crime_module.random, "uniform", lambda _a, _b: 0.20)
        monkeypatch.setattr(crime_module, "add_progress", lambda *args, **kwargs: None)
        monkeypatch.setattr(crime_module, "check_achievements", lambda *args, **kwargs: [])

        robber_before = dict(db.profiles[(123, 42)])
        victim_before = dict(db.profiles[(123, 77)])

        await Crime.steal.callback(cog, ctx, target())

        assert db.profiles[(123, 42)] == robber_before
        assert db.profiles[(123, 77)] == victim_before
        assert db.dirty_profiles == set()
        assert ctx.command.reset_count == 1
        assert "too poor to rob" in ctx.sent[-1][0][0]

    asyncio.run(scenario())
