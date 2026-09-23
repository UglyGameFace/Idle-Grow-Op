import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

import gambling as gambling_module
import scoped_database as scoped_database_module
from casino_contracts import (
    CASINO_ESCROW_KEY,
    blackjack_escrow_amount,
    make_blackjack_escrow,
)
from gambling import BlackjackView, Gambling
from persistence_scope import RecordKey
from scoped_database import ScopedDatabaseManager
from world_mode_contracts import POLICY_SERVER, new_world_mode_config


class Backend:
    def __init__(self, profile=None):
        self.records = {}
        if profile is not None:
            self.records["profile:123:42"] = deepcopy(profile)

    async def load(self, key: RecordKey):
        value = self.records.get(key.cache_key)
        return deepcopy(value) if value is not None else None

    async def save_many(self, records):
        for key, value in records.items():
            self.records[key.cache_key] = deepcopy(dict(value))


class MemoryDatabase:
    def __init__(self, profile):
        self.lock = asyncio.Lock()
        config = new_world_mode_config()
        config.update({"policy": POLICY_SERVER, "configured": True})
        self.world = {"world_mode_config": config}
        self.profile = profile
        self.dirty_profiles = set()

    async def get_world(self, scope_id):
        return self.world

    async def get_profile(self, scope_id, user_id):
        return self.profile

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))


class FailingMessageContext:
    def __init__(self):
        self.author = SimpleNamespace(id=42, name="Tester")
        self.guild = SimpleNamespace(id=123)
        self.sent = []

    async def send(self, *args, **kwargs):
        if "view" in kwargs:
            raise RuntimeError("simulated Discord send failure")
        self.sent.append((args, kwargs))


def test_profile_load_refunds_expired_blackjack_escrow(monkeypatch):
    async def scenario():
        profile = {
            "grams": 800,
            CASINO_ESCROW_KEY: {
                "game": "blackjack",
                "amount": 200,
                "expires_at": 100.0,
            },
        }
        database = ScopedDatabaseManager(Backend(profile))
        monkeypatch.setattr(scoped_database_module.time, "time", lambda: 200.0)

        loaded = await database.get_profile(123, 42)

        assert loaded["grams"] == 1_000
        assert CASINO_ESCROW_KEY not in loaded
        assert database.store.dirty_keys == frozenset({"profile:123:42"})

    asyncio.run(scenario())


def test_profile_load_keeps_active_blackjack_escrow_reserved(monkeypatch):
    async def scenario():
        profile = {
            "grams": 800,
            CASINO_ESCROW_KEY: {
                "game": "blackjack",
                "amount": 200,
                "expires_at": 300.0,
            },
        }
        database = ScopedDatabaseManager(Backend(profile))
        monkeypatch.setattr(scoped_database_module.time, "time", lambda: 200.0)

        loaded = await database.get_profile(123, 42)

        assert loaded["grams"] == 800
        assert blackjack_escrow_amount(loaded) == 200
        assert database.store.dirty_keys == frozenset()

    asyncio.run(scenario())


def test_blackjack_message_send_failure_refunds_reserved_wager(monkeypatch):
    async def scenario():
        profile = {
            "grams": 1_000,
            "jail_until": 0,
            "items": {},
            "stats": {},
            "achievements": [],
            "level": 1,
            "xp": 0,
        }
        db = MemoryDatabase(profile)
        ctx = FailingMessageContext()
        cog = Gambling(SimpleNamespace(db=db))

        def force_non_natural(deck):
            deck[-4:] = [2, 3, 4, 5]

        monkeypatch.setattr(gambling_module.random, "shuffle", force_non_natural)
        monkeypatch.setattr(gambling_module.time, "time", lambda: 100.0)

        with pytest.raises(RuntimeError, match="simulated Discord send failure"):
            await Gambling.blackjack.callback(cog, ctx, bet="200")

        assert profile["grams"] == 1_000
        assert CASINO_ESCROW_KEY not in profile
        assert db.dirty_profiles == {(123, 42)}

    asyncio.run(scenario())


def test_blackjack_timeout_refunds_and_clears_escrow(monkeypatch):
    async def scenario():
        profile = {
            "grams": 800,
            CASINO_ESCROW_KEY: make_blackjack_escrow(200, now=100.0),
            "stats": {},
            "achievements": [],
            "level": 1,
            "xp": 0,
        }
        db = MemoryDatabase(profile)
        cog = Gambling(SimpleNamespace(db=db))
        view = BlackjackView(
            cog,
            SimpleNamespace(),
            123,
            42,
            200,
            [2, 3, 4],
            [10, 7],
            [9, 8],
        )
        monkeypatch.setattr(gambling_module.time, "time", lambda: 150.0)

        await view._settle("tie", timeout_refund=True)

        assert profile["grams"] == 1_000
        assert CASINO_ESCROW_KEY not in profile
        assert profile.get("stats", {}) == {}
        assert view.ended is True
        assert db.dirty_profiles == {(123, 42)}

    asyncio.run(scenario())


def test_late_blackjack_settlement_cannot_double_pay_after_stale_refund(monkeypatch):
    async def scenario():
        profile = {
            "grams": 800,
            CASINO_ESCROW_KEY: make_blackjack_escrow(200, now=0.0),
            "stats": {},
            "achievements": [],
            "level": 1,
            "xp": 0,
        }
        db = MemoryDatabase(profile)
        cog = Gambling(SimpleNamespace(db=db))
        view = BlackjackView(
            cog,
            SimpleNamespace(),
            123,
            42,
            200,
            [2, 3, 4],
            [10, 7],
            [9, 8],
        )
        monkeypatch.setattr(gambling_module.time, "time", lambda: 200.0)

        await view._settle("win", payout=400)

        assert profile["grams"] == 1_000
        assert CASINO_ESCROW_KEY not in profile
        assert profile.get("stats", {}) == {}
        assert view.ended is True

    asyncio.run(scenario())
