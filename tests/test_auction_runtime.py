import asyncio
from types import SimpleNamespace

import pytest

from economy import Economy
from world_modes import GameScope, MODE_SERVER, POLICY_SERVER


class AuctionDatabase:
    def __init__(self, *, fail_user_id=None):
        self.lock = asyncio.Lock()
        self.world = {
            "auctions": {
                "1001": {
                    "seller_id": 77,
                    "seller_name": "Seller",
                    "item_name": "pager",
                    "start_price": 100,
                    "current_bid": 100,
                    "highest_bidder": None,
                    "buyout": 500,
                    "end_time": 9_999_999_999,
                }
            }
        }
        self.profiles = {
            42: {"grams": 1_000, "items": {}},
            77: {"grams": 100, "items": {}},
        }
        self.fail_user_id = fail_user_id
        self.dirty_profiles = set()
        self.dirty_worlds = set()

    async def get_world(self, scope_id):
        return self.world

    async def get_profile(self, scope_id, user_id):
        user_id = int(user_id)
        if user_id == self.fail_user_id:
            raise RuntimeError("simulated profile load failure")
        return self.profiles[user_id]

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty_profiles.add((int(scope_id), int(user_id)))

    def mark_world_dirty(self, scope_id):
        self.dirty_worlds.add(int(scope_id))


class ContextStub:
    def __init__(self):
        self.author = SimpleNamespace(id=42, name="Bidder")
        self.guild = SimpleNamespace(id=123)
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def scope():
    return GameScope(
        guild_id=123,
        user_id=42,
        policy=POLICY_SERVER,
        mode=MODE_SERVER,
        scope_id=123,
    )


def test_buyout_load_failure_does_not_partially_mutate_bidder_or_auction():
    async def scenario():
        db = AuctionDatabase(fail_user_id=77)
        bot = SimpleNamespace(db=db)
        cog = Economy(bot)
        ctx = ContextStub()

        async def resolved_profile(_ctx, user_id=None):
            return scope(), db.profiles[42]

        cog._profile = resolved_profile

        before_bidder = dict(db.profiles[42])
        before_auction = dict(db.world["auctions"]["1001"])

        with pytest.raises(RuntimeError, match="simulated profile load failure"):
            await Economy.bid.callback(cog, ctx, auction_id="1001", amount=500)

        assert db.profiles[42] == before_bidder
        assert db.world["auctions"]["1001"] == before_auction
        assert db.dirty_profiles == set()
        assert db.dirty_worlds == set()

    asyncio.run(scenario())


def test_buyout_transfers_escrowed_value_and_item_exactly_once():
    async def scenario():
        db = AuctionDatabase()
        bot = SimpleNamespace(db=db)
        cog = Economy(bot)
        ctx = ContextStub()

        async def resolved_profile(_ctx, user_id=None):
            return scope(), db.profiles[42]

        cog._profile = resolved_profile

        await Economy.bid.callback(cog, ctx, auction_id="1001", amount=500)

        assert db.profiles[42]["grams"] == 500
        assert db.profiles[42]["items"]["pager"] == 1
        assert db.profiles[77]["grams"] == 600
        assert "1001" not in db.world["auctions"]
        assert db.dirty_profiles == {(123, 42), (123, 77)}
        assert db.dirty_worlds == {123}
        assert "bought out" in ctx.sent[-1][0][0].lower()

    asyncio.run(scenario())


def test_first_bid_can_match_starting_price_but_repeat_bid_must_increase():
    async def scenario():
        db = AuctionDatabase()
        bot = SimpleNamespace(db=db)
        cog = Economy(bot)
        ctx = ContextStub()

        async def resolved_profile(_ctx, user_id=None):
            return scope(), db.profiles[42]

        cog._profile = resolved_profile

        await Economy.bid.callback(cog, ctx, auction_id="1001", amount=100)

        auction = db.world["auctions"]["1001"]
        assert db.profiles[42]["grams"] == 900
        assert auction["highest_bidder"] == 42
        assert auction["current_bid"] == 100

        before_balance = db.profiles[42]["grams"]
        await Economy.bid.callback(cog, ctx, auction_id="1001", amount=100)

        assert db.profiles[42]["grams"] == before_balance
        assert "higher than the current bid" in ctx.sent[-1][0][0]

    asyncio.run(scenario())
