import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from economy import ShopView
from game_hub import GameHubView
from notification_preferences import (
    NotificationPreferences,
    NotificationPreferencesCog,
    NotificationPreferencesView,
)
from onboarding import Onboarding, OnboardingView
from profile_signatures import (
    ProfileSettingsView,
    ProfileSignatures,
    _OpenProfileSettingsButton,
)
from world_modes import PlayerWorldModeView, WorldModes


class ResponseStub:
    def __init__(self):
        self.done = False
        self.defer_calls = []
        self.sent = []

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        self.defer_calls.append(kwargs)
        self.done = True

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        self.done = True


def test_shop_close_deletes_owned_private_panel():
    async def scenario():
        response = ResponseStub()
        owned = SimpleNamespace(delete=AsyncMock())
        interaction = SimpleNamespace(
            response=response,
            delete_original_response=AsyncMock(),
        )
        view = ShopView(SimpleNamespace(), 42, 123)
        view.message = owned

        await view.close_button(interaction)

        assert response.defer_calls == [{}]
        owned.delete.assert_awaited_once_with()
        interaction.delete_original_response.assert_not_awaited()
        assert view.is_finished()

    asyncio.run(scenario())


def test_game_hub_close_deletes_owned_private_panel():
    async def scenario():
        response = ResponseStub()
        owned = SimpleNamespace(delete=AsyncMock())
        interaction = SimpleNamespace(
            response=response,
            delete_original_response=AsyncMock(),
        )
        view = GameHubView(SimpleNamespace(), 42, 123)
        view.message = owned

        await view.handle_action(interaction, "close")

        assert response.defer_calls == [{}]
        owned.delete.assert_awaited_once_with()
        interaction.delete_original_response.assert_not_awaited()
        assert view.is_finished()

    asyncio.run(scenario())


def test_notification_toggle_acknowledges_before_persistence_work():
    async def scenario():
        response = ResponseStub()
        scope = SimpleNamespace(emoji="🏙️", label="Current Server World")
        prefs = NotificationPreferences(True, True, True)

        class Cog:
            async def toggle_preference(self, guild_id, user_id, target):
                assert response.done is True
                assert (guild_id, user_id, target) == (123, 42, "plant_ready")
                return scope, prefs

            async def get_state(self, guild_id, user_id):
                assert response.done is True
                assert (guild_id, user_id) == (123, 42)
                return scope, prefs

            build_panel = staticmethod(
                lambda resolved_scope, resolved_prefs: "notification-panel"
            )

        interaction = SimpleNamespace(
            response=response,
            edit_original_response=AsyncMock(return_value=SimpleNamespace()),
        )
        view = NotificationPreferencesView(Cog(), 42, 123)

        await view.toggle(interaction, "plant_ready")

        assert response.defer_calls == [{}]
        interaction.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_notifications_slash_launch_acknowledges_before_state_load():
    async def scenario():
        response = ResponseStub()
        interaction = SimpleNamespace(
            guild_id=123,
            user=SimpleNamespace(id=42),
            response=response,
            edit_original_response=AsyncMock(return_value=SimpleNamespace()),
        )
        cog = NotificationPreferencesCog(SimpleNamespace())
        scope = SimpleNamespace(emoji="🏙️", label="Current Server World")
        prefs = NotificationPreferences(True, True, True)

        async def get_state(guild_id, user_id):
            assert response.done is True
            assert (guild_id, user_id) == (123, 42)
            return scope, prefs

        cog.get_state = get_state

        await NotificationPreferencesCog.notifications.callback(cog, interaction)

        assert response.defer_calls == [{"ephemeral": True, "thinking": True}]
        interaction.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_player_world_selection_acknowledges_before_mode_mutation(monkeypatch):
    async def scenario():
        response = ResponseStub()
        choose_calls = []

        async def choose_player_mode(_db, guild_id, user_id, mode):
            assert response.done is True
            choose_calls.append((guild_id, user_id, mode))

        async def build_embed(_db, _guild, user_id):
            assert response.done is True
            assert user_id == 42
            return "world-panel"

        monkeypatch.setattr("world_modes.choose_player_mode", choose_player_mode)
        monkeypatch.setattr("world_modes.build_player_mode_embed", build_embed)

        bot = SimpleNamespace(
            db=object(),
            get_cog=lambda _name: None,
        )
        cog = SimpleNamespace(bot=bot)
        view = PlayerWorldModeView(cog, 42, 123)
        interaction = SimpleNamespace(
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
            edit_original_response=AsyncMock(),
            guild=SimpleNamespace(id=123),
        )

        await view._select(interaction, "solo")

        assert response.defer_calls == [{}]
        assert choose_calls == [(123, 42, "solo")]
        interaction.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_world_mode_slash_launch_acknowledges_before_database_load(monkeypatch):
    async def scenario():
        response = ResponseStub()

        class Database:
            async def get_world(self, guild_id):
                assert response.done is True
                assert guild_id == 123
                return {}

        async def build_embed(_db, _guild, user_id):
            assert response.done is True
            assert user_id == 42
            return "world-panel"

        monkeypatch.setattr(
            "world_modes.normalize_world_mode_config",
            lambda _world: {"policy": "server"},
        )
        monkeypatch.setattr("world_modes.build_player_mode_embed", build_embed)

        interaction_obj = SimpleNamespace(
            response=response,
            edit_original_response=AsyncMock(),
        )

        class Context:
            guild = SimpleNamespace(id=123)
            author = SimpleNamespace(id=42)
            interaction = interaction_obj

            async def defer(self, **kwargs):
                await response.defer(**kwargs)

            async def send(self, *_args, **_kwargs):
                raise AssertionError("slash launch must edit its deferred response")

        cog = WorldModes(SimpleNamespace(db=Database()))

        await WorldModes.world_mode.callback(cog, Context())

        assert response.defer_calls == [{"ephemeral": True}]
        interaction_obj.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_onboarding_start_acknowledges_before_state_build():
    async def scenario():
        response = ResponseStub()
        interaction_obj = SimpleNamespace(
            response=response,
            edit_original_response=AsyncMock(return_value=SimpleNamespace()),
        )

        class Context:
            guild = SimpleNamespace(id=123)
            author = SimpleNamespace(id=42)
            interaction = interaction_obj

            async def defer(self, **kwargs):
                await response.defer(**kwargs)

            async def send(self, *_args, **_kwargs):
                raise AssertionError("slash guide must edit its deferred response")

        cog = Onboarding(SimpleNamespace())

        async def build_start_embed(guild_id, user_id):
            assert response.done is True
            assert (guild_id, user_id) == (123, 42)
            return "start-panel"

        cog.build_start_embed = build_start_embed

        await Onboarding.start.callback(cog, Context())

        assert response.defer_calls == [{"ephemeral": True}]
        interaction_obj.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_onboarding_next_step_acknowledges_before_state_build():
    async def scenario():
        response = ResponseStub()
        interaction = SimpleNamespace(
            response=response,
            edit_original_response=AsyncMock(return_value=SimpleNamespace()),
        )

        class Cog:
            async def build_start_embed(self, guild_id, user_id):
                assert response.done is True
                assert (guild_id, user_id) == (123, 42)
                return "next-panel"

        view = OnboardingView(Cog(), 42, 123)
        await view.next_step(interaction, SimpleNamespace())

        assert response.defer_calls == [{}]
        interaction.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_profile_settings_open_button_acknowledges_before_panel_build():
    async def scenario():
        response = ResponseStub()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42),
            guild_id=123,
            response=response,
            edit_original_response=AsyncMock(),
        )

        class Cog:
            async def build_settings_panel(self, guild_id, user_id):
                assert response.done is True
                assert (guild_id, user_id) == (123, 42)
                return "profile-panel", SimpleNamespace()

        button = _OpenProfileSettingsButton(Cog(), 42, 123, row=0)

        await button.callback(interaction)

        assert response.defer_calls == [{"ephemeral": True, "thinking": True}]
        interaction.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_profile_settings_slash_launch_acknowledges_before_panel_build():
    async def scenario():
        response = ResponseStub()
        interaction_obj = SimpleNamespace(
            response=response,
            edit_original_response=AsyncMock(),
        )

        class Context:
            guild = SimpleNamespace(id=123)
            author = SimpleNamespace(id=42)
            interaction = interaction_obj

            async def defer(self, **kwargs):
                await response.defer(**kwargs)

            async def send(self, *_args, **_kwargs):
                raise AssertionError("slash settings must edit its deferred response")

        cog = ProfileSignatures(SimpleNamespace())

        async def build_settings_panel(guild_id, user_id):
            assert response.done is True
            assert (guild_id, user_id) == (123, 42)
            return "profile-panel", SimpleNamespace()

        cog.build_settings_panel = build_settings_panel

        await ProfileSignatures.profile_settings.callback(cog, Context())

        assert response.defer_calls == [{"ephemeral": True}]
        interaction_obj.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_profile_settings_toggle_acknowledges_before_privacy_mutation():
    async def scenario():
        response = ResponseStub()
        interaction = SimpleNamespace(
            response=response,
            edit_original_response=AsyncMock(),
        )

        class Cog:
            async def update_global_privacy(self, user_id, **kwargs):
                assert response.done is True
                assert user_id == 42
                assert kwargs == {"signature_enabled": False}

            async def build_settings_panel(self, guild_id, user_id):
                assert response.done is True
                assert (guild_id, user_id) == (123, 42)
                return "profile-panel", SimpleNamespace()

        view = ProfileSettingsView(Cog(), 42, 123, {}, {})

        await ProfileSettingsView.toggle_global(view, interaction, SimpleNamespace())

        assert response.defer_calls == [{}]
        interaction.edit_original_response.assert_awaited_once()

    asyncio.run(scenario())


def test_profile_settings_hub_adapter_keeps_followup_path_without_ctx_defer():
    async def scenario():
        response = ResponseStub()
        response.done = True
        interaction = SimpleNamespace(response=response)
        sent = []

        class HubLikeContext:
            guild = SimpleNamespace(id=123)
            author = SimpleNamespace(id=42)
            interaction = interaction

            async def send(self, *args, **kwargs):
                sent.append((args, kwargs))
                return SimpleNamespace()

        cog = ProfileSignatures(SimpleNamespace())

        async def build_settings_panel(guild_id, user_id):
            assert response.done is True
            assert (guild_id, user_id) == (123, 42)
            return "profile-panel", SimpleNamespace()

        cog.build_settings_panel = build_settings_panel

        await ProfileSignatures.profile_settings.callback(cog, HubLikeContext())

        assert len(sent) == 1
        assert sent[0][1]["ephemeral"] is True

    asyncio.run(scenario())
