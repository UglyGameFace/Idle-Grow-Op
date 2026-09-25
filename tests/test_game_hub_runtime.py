import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord.ext import commands

from game_hub import (
    GameHub,
    HubInteractionContext,
    CASINO_GAMES,
    GameHubView,
    HubCasinoGameSelect,
    HubConcentrateSelect,
    HubStealTargetSelect,
    SAFE_HUB_COMMANDS,
    _keno_bet_token,
)
from utils import CONCENTRATE_TYPES
from world_modes import GameScope, MODE_SERVER, POLICY_SERVER


def scope():
    return GameScope(
        guild_id=123,
        user_id=42,
        policy=POLICY_SERVER,
        mode=MODE_SERVER,
        scope_id=123,
        selection_explicit=True,
    )


def test_hub_allowlist_excludes_privileged_or_destructive_admin_surfaces():
    assert "setup" not in SAFE_HUB_COMMANDS
    assert "sync" not in SAFE_HUB_COMMANDS
    assert "wipeuser" not in SAFE_HUB_COMMANDS
    assert "setmoney" not in SAFE_HUB_COMMANDS


def test_refresh_original_prefers_owned_interaction_message_for_ephemeral_hub():
    class OwnedInteractionMessage:
        def __init__(self):
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)
            return self

    class ComponentMessage:
        async def edit(self, **_kwargs):
            raise AssertionError(
                "component interaction.message must not be used to edit the ephemeral Hub"
            )

    async def scenario():
        profile = {
            "grams": 500,
            "level": 1,
            "xp": 0,
            "plants": [],
            "items": {},
            "flower_stash": {},
            "concentrates": {},
        }
        cog = SimpleNamespace(
            state=AsyncMock(return_value=(scope(), profile, {})),
            build_embed=lambda *_args, **_kwargs: "embed",
        )
        view = GameHubView(cog, 42, 123)
        owned = OwnedInteractionMessage()
        view.message = owned
        interaction = SimpleNamespace(message=ComponentMessage())

        await view.refresh_original(interaction)

        cog.state.assert_awaited_once_with(123, 42)
        assert owned.edits == [{"embed": "embed", "view": view}]
        assert view.message is owned

    asyncio.run(scenario())


def test_component_hub_action_uses_context_checks_not_hybrid_baton():
    class ProbeCog(commands.Cog):
        def __init__(self):
            self.seen_check_context = None
            self.callback_context = None

        async def cog_check(self, ctx):
            self.seen_check_context = ctx
            return getattr(getattr(ctx, "guild", None), "id", None) == 123

        @commands.hybrid_command(name="help")
        async def help_command(self, ctx):
            self.callback_context = ctx
            await ctx.send("ok")

    class Response:
        def __init__(self):
            self.done = False

        def is_done(self):
            return self.done

        async def defer(self, **_kwargs):
            self.done = True

        async def send_message(self, **_kwargs):
            self.done = True

    class Followup:
        def __init__(self):
            self.messages = []

        async def send(self, content=None, **kwargs):
            self.messages.append((content, kwargs))
            return SimpleNamespace()

    async def scenario():
        bot = commands.Bot(
            command_prefix="!",
            intents=discord.Intents.none(),
            help_command=None,
        )
        probe = ProbeCog()
        await bot.add_cog(probe)
        command = bot.get_command("help")
        assert command is not None

        response = Response()
        followup = Followup()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42),
            guild=SimpleNamespace(id=123),
            guild_id=123,
            channel=SimpleNamespace(id=456),
            message=None,
            created_at=datetime.datetime.now(datetime.timezone.utc),
            response=response,
            followup=followup,
            client=bot,
            # Component interactions never receive the Context baton that
            # HybridAppCommand._check_can_run expects.
            _baton=discord.utils.MISSING,
        )

        game_hub = GameHub(bot)
        view = GameHubView(game_hub, 42, 123)
        view.refresh_original = AsyncMock()

        await view.run_command(interaction, "help")

        assert isinstance(probe.seen_check_context, HubInteractionContext)
        assert probe.callback_context is probe.seen_check_context
        assert followup.messages[0][0] == "ok"
        view.refresh_original.assert_awaited_once_with(interaction)

    asyncio.run(scenario())


def test_slash_game_launch_defers_before_loading_state():
    class Context:
        def __init__(self):
            self.guild = SimpleNamespace(id=123)
            self.author = SimpleNamespace(id=42)
            self.deferred = False
            self.sent = []
            self.interaction = SimpleNamespace(
                edit_original_response=AsyncMock(
                    return_value=SimpleNamespace(edit=AsyncMock())
                )
            )

        async def defer(self, *, ephemeral=False):
            assert ephemeral is True
            self.deferred = True

        async def send(self, **kwargs):
            self.sent.append(kwargs)
            return SimpleNamespace()

    async def scenario():
        bot = SimpleNamespace()
        cog = GameHub(bot)
        ctx = Context()

        async def state(guild_id, user_id):
            assert ctx.deferred is True
            assert (guild_id, user_id) == (123, 42)
            return scope(), {
                "grams": 500,
                "level": 1,
                "xp": 0,
                "plants": [],
                "items": {},
                "flower_stash": {},
                "concentrates": {},
            }, {}

        cog.state = state
        await cog._send_hub_context(ctx)

        assert ctx.sent == []
        ctx.interaction.edit_original_response.assert_awaited_once()
        kwargs = ctx.interaction.edit_original_response.await_args.kwargs
        assert isinstance(kwargs["view"], GameHubView)

    asyncio.run(scenario())


def test_onboarding_game_launch_defers_component_before_loading_state():
    class Response:
        def __init__(self):
            self.deferred = False

        async def defer(self, *, ephemeral=False, thinking=False):
            assert ephemeral is True
            assert thinking is True
            self.deferred = True

        async def send_message(self, *args, **kwargs):
            raise AssertionError("guild Hub launch should defer, not send before state load")

    async def scenario():
        bot = SimpleNamespace()
        cog = GameHub(bot)
        response = Response()
        interaction = SimpleNamespace(
            guild_id=123,
            user=SimpleNamespace(id=42),
            response=response,
            edit_original_response=AsyncMock(
                return_value=SimpleNamespace(edit=AsyncMock())
            ),
        )

        async def state(guild_id, user_id):
            assert response.deferred is True
            assert (guild_id, user_id) == (123, 42)
            return scope(), {
                "grams": 500,
                "level": 1,
                "xp": 0,
                "plants": [],
                "items": {},
                "flower_stash": {},
                "concentrates": {},
            }, {}

        cog.state = state
        await cog.send_hub_interaction(interaction)

        interaction.edit_original_response.assert_awaited_once()
        kwargs = interaction.edit_original_response.await_args.kwargs
        assert isinstance(kwargs["view"], GameHubView)

    asyncio.run(scenario())


def test_game_menu_and_play_launchers_delegate_to_one_hub_path():
    async def scenario():
        cog = GameHub(SimpleNamespace())
        ctx = SimpleNamespace()
        shared = AsyncMock()
        cog._send_hub_context = shared

        await GameHub.game.callback(cog, ctx)
        await GameHub.menu.callback(cog, ctx)
        await GameHub.play.callback(cog, ctx)

        assert shared.await_count == 3
        assert all(call.args == (ctx,) for call in shared.await_args_list)

    asyncio.run(scenario())


def test_hub_refresh_defers_before_state_load_and_edits_owned_panel():
    class Response:
        def __init__(self):
            self.done = False
            self.defer_calls = []

        def is_done(self):
            return self.done

        async def defer(self, **kwargs):
            self.defer_calls.append(kwargs)
            self.done = True

    async def scenario():
        profile = {
            "grams": 500,
            "level": 1,
            "xp": 0,
            "plants": [],
            "items": {},
            "flower_stash": {},
            "concentrates": {},
        }
        response = Response()
        interaction = SimpleNamespace(
            response=response,
            message=SimpleNamespace(edit=AsyncMock()),
        )
        cog = SimpleNamespace(
            state=AsyncMock(return_value=(scope(), profile, {})),
            build_embed=lambda *_args, **_kwargs: "embed",
        )
        view = GameHubView(cog, 42, 123)
        owned = SimpleNamespace(edit=AsyncMock(return_value=None))
        view.message = owned

        await view.refresh(interaction)

        assert response.defer_calls == [{}]
        cog.state.assert_awaited_once_with(123, 42)
        owned.edit.assert_awaited_once()

    asyncio.run(scenario())


def test_hub_shop_defers_before_profile_load_when_it_owns_response():
    class Response:
        def __init__(self):
            self.done = False
            self.defer_calls = []

        def is_done(self):
            return self.done

        async def defer(self, **kwargs):
            self.defer_calls.append(kwargs)
            self.done = True

    async def scenario():
        response = Response()
        interaction = SimpleNamespace(
            response=response,
            edit_original_response=AsyncMock(
                return_value=SimpleNamespace(edit=AsyncMock())
            ),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        profile = {"grams": 500, "level": 1, "items": {}}
        economy = SimpleNamespace(
            _profile_for=AsyncMock(),
            build_shop_embed=lambda *_args, **_kwargs: "shop-embed",
        )

        async def profile_for(guild_id, user_id):
            assert response.done is True
            assert (guild_id, user_id) == (123, 42)
            return scope(), profile

        economy._profile_for = profile_for
        bot = SimpleNamespace(get_cog=lambda name: economy if name == "Economy" else None)
        view = GameHubView(SimpleNamespace(bot=bot), 42, 123)

        await view.open_shop(interaction, category="seeds")

        assert response.defer_calls == [{"ephemeral": True, "thinking": True}]
        interaction.edit_original_response.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()

    asyncio.run(scenario())


def test_hub_shop_uses_followup_when_next_move_already_acknowledged():
    class Response:
        def is_done(self):
            return True

    async def scenario():
        sent_message = SimpleNamespace(edit=AsyncMock())
        interaction = SimpleNamespace(
            response=Response(),
            followup=SimpleNamespace(
                send=AsyncMock(return_value=sent_message)
            ),
        )
        profile = {"grams": 500, "level": 1, "items": {}}
        economy = SimpleNamespace(
            _profile_for=AsyncMock(return_value=(scope(), profile)),
            build_shop_embed=lambda *_args, **_kwargs: "shop-embed",
        )
        bot = SimpleNamespace(get_cog=lambda name: economy if name == "Economy" else None)
        view = GameHubView(SimpleNamespace(bot=bot), 42, 123)

        await view.open_shop(interaction, category="seeds")

        interaction.followup.send.assert_awaited_once()
        kwargs = interaction.followup.send.await_args.kwargs
        assert kwargs["ephemeral"] is True
        assert kwargs["wait"] is True

    asyncio.run(scenario())


def test_next_move_acknowledges_before_state_access():
    class StopAfterOrderingCheck(RuntimeError):
        pass

    class Response:
        def __init__(self):
            self.done = False
            self.defer_count = 0

        def is_done(self):
            return self.done

        async def defer(self, **_kwargs):
            self.defer_count += 1
            self.done = True

    async def scenario():
        response = Response()
        interaction = SimpleNamespace(response=response)
        view = GameHubView(SimpleNamespace(), 42, 123)

        async def state():
            assert response.done is True
            raise StopAfterOrderingCheck

        view.state = state
        try:
            await view.perform_next_move(interaction)
        except StopAfterOrderingCheck:
            pass
        else:
            raise AssertionError("state ordering sentinel was not reached")

        assert response.defer_count == 1

    asyncio.run(scenario())


def test_run_command_skips_second_defer_for_preacknowledged_component():
    class Response:
        def is_done(self):
            return True

        async def defer(self, **_kwargs):
            raise AssertionError("run_command must not acknowledge twice")

    class ProbeCog(commands.Cog):
        @commands.hybrid_command(name="help")
        async def help_command(self, ctx):
            await ctx.send("ok")

    async def scenario():
        bot = commands.Bot(
            command_prefix="!",
            intents=discord.Intents.none(),
            help_command=None,
        )
        probe = ProbeCog()
        await bot.add_cog(probe)
        interaction = SimpleNamespace(
            response=Response(),
            user=SimpleNamespace(id=42),
            guild=SimpleNamespace(id=123),
            guild_id=123,
            channel=SimpleNamespace(id=456),
            message=None,
            created_at=datetime.datetime.now(datetime.timezone.utc),
            followup=SimpleNamespace(
                send=AsyncMock(return_value=SimpleNamespace())
            ),
            client=bot,
        )
        hub = GameHub(bot)
        view = GameHubView(hub, 42, 123)
        view.refresh_original = AsyncMock()

        await view.run_command(interaction, "help")

        interaction.followup.send.assert_awaited_once()
        view.refresh_original.assert_awaited_once_with(interaction)

    asyncio.run(scenario())


def test_grow_page_uses_stable_ready_at_after_weather_changes(monkeypatch):
    monkeypatch.setattr("game_hub.time.time", lambda: 1200.0)
    cog = GameHub(SimpleNamespace())
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [
            {
                "strain": "schwag",
                "planted_at": 1000.0,
                "ready_at": 1150.0,
            }
        ],
        "items": {},
        "flower_stash": {},
        "concentrates": {},
    }

    sunny = cog.build_embed(
        scope(),
        profile,
        {"weather": "420 Day 🍁"},
        page="grow",
    )
    misty = cog.build_embed(
        scope(),
        profile,
        {"weather": "Misty 🌫️"},
        page="grow",
    )

    assert "1 plants (1 ready)" in sunny.description
    assert "1 plants (1 ready)" in misty.description
    assert "✅ READY" in sunny.fields[0].value
    assert "✅ READY" in misty.fields[0].value


def test_home_page_recommends_real_next_move_without_requiring_command_memory(monkeypatch):
    monkeypatch.setattr("game_hub.time.time", lambda: 1000.0)
    cog = GameHub(SimpleNamespace())
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
        "flower_stash": {},
        "concentrates": {},
        "unlocked_strains": ["schwag"],
    }

    embed = cog.build_embed(scope(), profile, {}, page="home")

    assert "Recommended Next Move" in embed.fields[0].name
    assert "Play from this panel" in embed.fields[-1].name
    assert "memorize" in embed.fields[-1].value



def _button(view, label):
    return next(
        item
        for item in view.children
        if getattr(item, "label", None) == label
    )


def test_hub_allowlist_includes_only_needed_direct_nested_player_actions():
    assert "steal" in SAFE_HUB_COMMANDS
    assert {
        "crew create",
        "crew join",
        "crew leave",
        "crew info",
        "crew deposit",
        "crew war",
    } <= SAFE_HUB_COMMANDS


def test_grow_inventory_and_lab_buttons_disable_when_action_has_no_work(monkeypatch):
    monkeypatch.setattr("game_hub.time.time", lambda: 1_000.0)
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
        "flower_stash": {},
        "processing_queue": [],
    }

    grow = GameHubView(SimpleNamespace(), 42, 123, page="grow")
    grow.rebuild(scope(), profile, {})
    assert _button(grow, "Harvest Ready").disabled is True

    inventory = GameHubView(SimpleNamespace(), 42, 123, page="inventory")
    inventory.rebuild(scope(), profile, {})
    assert _button(inventory, "Sell All Flower").disabled is True
    assert _button(inventory, "Collect Lab").disabled is True

    lab = GameHubView(SimpleNamespace(), 42, 123, page="lab")
    lab.rebuild(scope(), profile, {})
    assert any(isinstance(item, HubConcentrateSelect) for item in lab.children)
    assert _button(lab, "Start Batch").disabled is True

    profile["plants"] = [
        {"strain": "schwag", "planted_at": 0.0, "ready_at": 500.0}
    ]
    profile["flower_stash"] = {"schwag": 10}
    profile["processing_queue"] = [{"finish_time": 900.0, "amount": 1, "type": "hash"}]
    grow.rebuild(scope(), profile, {})
    inventory.rebuild(scope(), profile, {})
    assert _button(grow, "Harvest Ready").disabled is False
    assert _button(inventory, "Sell All Flower").disabled is False
    assert _button(inventory, "Collect Lab").disabled is False

    lab.selected_concentrate = next(iter(CONCENTRATE_TYPES))
    lab.rebuild(scope(), profile, {})
    assert _button(lab, "Start Batch").disabled is False
    assert _button(lab, "Collect Ready").disabled is False


def test_social_page_changes_from_join_flow_to_member_controls():
    profile = {
        "grams": 100_000,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="social")
    view.rebuild(scope(), profile, {})

    labels = {getattr(item, "label", None) for item in view.children}
    assert "Create Crew" in labels
    assert "Join Crew" in labels
    assert "Crew Info" not in labels

    profile["crew_id"] = "12345"
    view.rebuild(scope(), profile, {})
    labels = {getattr(item, "label", None) for item in view.children}
    assert {"Crew Info", "Deposit", "Leave Crew", "Turf War"} <= labels
    assert "Create Crew" not in labels


def test_crime_page_uses_user_picker_and_only_enables_robbery_after_selection():
    profile = {
        "grams": 500,
        "dirty_cash": 0,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="crime")
    view.rebuild(scope(), profile, {})

    assert any(isinstance(item, HubStealTargetSelect) for item in view.children)
    assert _button(view, "Rob Selected").disabled is True

    view.selected_steal_target = SimpleNamespace(id=77)
    view.rebuild(scope(), profile, {})
    assert _button(view, "Rob Selected").disabled is False


def test_home_page_exposes_one_tap_next_move():
    profile = {
        "grams": 500,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="home")
    view.rebuild(scope(), profile, {})

    assert _button(view, "Do Next Move").disabled is False



def test_casino_page_uses_game_picker_and_requires_explicit_selection():
    profile = {
        "grams": 5_000,
        "level": 1,
        "xp": 0,
        "plants": [],
        "items": {},
    }
    view = GameHubView(SimpleNamespace(), 42, 123, page="casino")
    view.rebuild(scope(), profile, {})

    assert any(isinstance(item, HubCasinoGameSelect) for item in view.children)
    assert _button(view, "Play Selected").disabled is True

    view.selected_casino_game = CASINO_GAMES[0][0]
    view.rebuild(scope(), profile, {})
    assert _button(view, "Play Selected").disabled is False


def test_casino_launcher_allowlist_covers_every_selectable_game():
    assert {key for key, _label, _emoji in CASINO_GAMES} <= SAFE_HUB_COMMANDS



def test_keno_launcher_disambiguates_small_numeric_bets_from_picks():
    assert _keno_bet_token("10") == "$10"
    assert _keno_bet_token("$25") == "$25"
    assert _keno_bet_token("1,000") == "$1000"
    assert _keno_bet_token("1k") == "1k"
    assert _keno_bet_token("half") == "half"
    assert _keno_bet_token("25%") == "25%"



def test_game_hub_timeout_disables_visible_controls_and_edits_message():
    class Message:
        def __init__(self):
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    async def scenario():
        profile = {
            "grams": 500,
            "level": 1,
            "xp": 0,
            "plants": [],
            "items": {},
        }
        view = GameHubView(SimpleNamespace(), 42, 123, page="home")
        view.rebuild(scope(), profile, {})
        message = Message()
        view.message = message

        await view.on_timeout()

        assert all(item.disabled for item in view.children)
        assert message.edits == [{"view": view}]

    asyncio.run(scenario())
