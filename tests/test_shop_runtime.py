import asyncio
from types import SimpleNamespace

import economy as economy_module
from economy import (
    Economy,
    ShopCategorySelect,
    ShopItemSelect,
    ShopQuantitySelect,
    ShopView,
)


class MemoryDatabase:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.dirty = set()

    def mark_profile_dirty(self, scope_id, user_id):
        self.dirty.add((int(scope_id), int(user_id)))


def test_purchase_item_success_uses_shared_mutation_path(monkeypatch):
    async def scenario():
        db = MemoryDatabase()
        cog = Economy(SimpleNamespace(db=db))
        scope = SimpleNamespace(scope_id=123)
        profile = {
            "grams": 500,
            "level": 1,
            "items": {},
            "daily_quests": [],
            "achievements": [],
            "stats": {},
        }
        monkeypatch.setattr(economy_module, "add_progress", lambda *args, **kwargs: None)
        monkeypatch.setattr(economy_module, "check_achievements", lambda *args, **kwargs: [])

        ok, message = await cog._purchase_item(
            scope,
            profile,
            42,
            "schwag seed",
        )

        assert ok is True
        assert profile["grams"] == 485
        assert profile["items"]["schwag seed"] == 1
        assert db.dirty == {(123, 42)}
        assert "Bought" in message

    asyncio.run(scenario())


def test_bulk_seed_purchase_is_atomic_and_counts_each_item(monkeypatch):
    async def scenario():
        db = MemoryDatabase()
        cog = Economy(SimpleNamespace(db=db))
        scope = SimpleNamespace(scope_id=123)
        progress = []
        profile = {
            "grams": 1_000,
            "level": 1,
            "items": {},
            "daily_quests": [],
            "achievements": [],
            "stats": {},
        }
        monkeypatch.setattr(
            economy_module,
            "add_progress",
            lambda user, key, amount, **kwargs: progress.append((key, amount)),
        )
        monkeypatch.setattr(economy_module, "check_achievements", lambda *args, **kwargs: [])

        ok, message = await cog._purchase_item(
            scope,
            profile,
            42,
            "schwag seed",
            quantity=25,
        )

        assert ok is True
        assert profile["grams"] == 625
        assert profile["items"]["schwag seed"] == 25
        assert progress == [("buy", 25)]
        assert db.dirty == {(123, 42)}
        assert "25x Schwag Seed" in message
        assert "$375" in message

    asyncio.run(scenario())


def test_max_affordable_seed_quantity_uses_live_wallet():
    cog = Economy(SimpleNamespace(db=MemoryDatabase()))
    profile = {"grams": 4_753_663}

    assert cog.resolve_shop_quantity(profile, "white widow seed", "max") == 950
    assert cog.resolve_shop_quantity(profile, "white widow seed", "25") == 25
    assert cog.resolve_shop_quantity(profile, "pager", "max") == 1


def test_purchase_item_rejects_locked_duplicate_and_unaffordable_without_mutation(monkeypatch):
    async def scenario():
        db = MemoryDatabase()
        cog = Economy(SimpleNamespace(db=db))
        scope = SimpleNamespace(scope_id=123)
        monkeypatch.setattr(economy_module, "add_progress", lambda *args, **kwargs: None)
        monkeypatch.setattr(economy_module, "check_achievements", lambda *args, **kwargs: [])

        locked = {"grams": 999_999, "level": 1, "items": {}}
        before_locked = dict(locked)
        ok, message = await cog._purchase_item(scope, locked, 42, "led lights")
        assert ok is False
        assert "level locked" in message.lower()
        assert locked == before_locked

        duplicate = {"grams": 999_999, "level": 50, "items": {"pager": 1}}
        before_duplicate = {
            "grams": duplicate["grams"],
            "level": duplicate["level"],
            "items": dict(duplicate["items"]),
        }
        ok, message = await cog._purchase_item(scope, duplicate, 42, "pager")
        assert ok is False
        assert "already own" in message.lower()
        assert duplicate == before_duplicate

        poor = {"grams": 0, "level": 1, "items": {}}
        before_poor = dict(poor)
        ok, message = await cog._purchase_item(scope, poor, 42, "schwag seed")
        assert ok is False
        assert "need" in message.lower()
        assert poor == before_poor

        assert db.dirty == set()

    asyncio.run(scenario())


def test_shop_view_has_category_item_and_transaction_controls():
    db = MemoryDatabase()
    cog = Economy(SimpleNamespace(db=db))
    profile = {"grams": 500, "level": 1, "items": {}}
    view = ShopView(cog, 42, 123)

    view.rebuild(profile)

    assert isinstance(view.children[0], ShopCategorySelect)
    assert isinstance(view.children[1], ShopItemSelect)
    assert isinstance(view.children[2], ShopQuantitySelect)
    labels = {
        child.label
        for child in view.children
        if getattr(child, "label", None)
    }
    assert {"Buy Selected", "Refresh", "Close"} <= labels


def test_shop_buy_defers_before_state_load_and_refreshes_owned_panel(monkeypatch):
    class Response:
        def __init__(self):
            self.done = False
            self.deferred = 0

        def is_done(self):
            return self.done

        async def defer(self):
            self.done = True
            self.deferred += 1

    class Message:
        def __init__(self):
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)
            return self

    async def scenario():
        db = MemoryDatabase()
        cog = Economy(SimpleNamespace(db=db))
        view = ShopView(cog, 42, 123)
        view.selected_item = "schwag seed"
        view.purchase_quantity = "10"
        profile = {
            "grams": 1_000,
            "level": 1,
            "items": {},
            "daily_quests": [],
            "achievements": [],
            "stats": {},
        }
        scope = SimpleNamespace(scope_id=123, emoji="🏙️", label="Current Server World")
        view.state = AsyncMock(return_value=(scope, profile))
        monkeypatch.setattr(economy_module, "add_progress", lambda *args, **kwargs: None)
        monkeypatch.setattr(economy_module, "check_achievements", lambda *args, **kwargs: [])

        owned = Message()
        view.message = owned
        response = Response()
        interaction = SimpleNamespace(
            response=response,
            message=SimpleNamespace(
                edit=AsyncMock(side_effect=AssertionError("wrong message object"))
            ),
        )

        await view.buy_selected(interaction)

        assert response.deferred == 1
        assert profile["items"]["schwag seed"] == 10
        assert profile["grams"] == 850
        assert len(owned.edits) == 1
        assert view.message is owned

    asyncio.run(scenario())


def test_shop_embed_exposes_live_wallet_level_and_selected_item():
    cog = Economy(SimpleNamespace(db=MemoryDatabase()))
    scope = SimpleNamespace(emoji="🏙️", label="Current Server World")
    profile = {
        "grams": 500,
        "level": 1,
        "items": {"schwag seed": 2},
    }

    embed = cog.build_shop_embed(
        scope,
        profile,
        category="seeds",
        selected_item="schwag seed",
        selected_quantity="25",
    )

    assert "$500" in embed.description
    assert "Level:** 1" in embed.description
    assert "Schwag Seed" in embed.fields[0].name
    assert "Owned:** 2" in embed.fields[0].value
    assert "Purchase Quantity:** x25" in embed.fields[0].value



def test_shop_timeout_disables_visible_controls_and_edits_message():
    class Message:
        def __init__(self):
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    async def scenario():
        cog = Economy(SimpleNamespace(db=MemoryDatabase()))
        view = ShopView(cog, 42, 123)
        view.rebuild({"grams": 500, "level": 1, "items": {}})
        message = Message()
        view.message = message

        await view.on_timeout()

        assert all(child.disabled for child in view.children)
        assert message.edits == [{"view": view}]

    asyncio.run(scenario())
