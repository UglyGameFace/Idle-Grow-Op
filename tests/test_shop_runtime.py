import asyncio
from types import SimpleNamespace

import economy as economy_module
from economy import Economy, ShopCategorySelect, ShopItemSelect, ShopView


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
    labels = {
        child.label
        for child in view.children
        if getattr(child, "label", None)
    }
    assert {"Buy Selected", "Refresh", "Close"} <= labels


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
    )

    assert "$500" in embed.description
    assert "Level:** 1" in embed.description
    assert "Schwag Seed" in embed.fields[0].name
    assert "Owned:** 2" in embed.fields[0].value



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
