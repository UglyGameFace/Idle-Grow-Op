from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "profile_signatures.py").read_text(encoding="utf-8")
SETUP_SOURCE = (ROOT / "setup.py").read_text(encoding="utf-8")
SOCIAL_SOURCE = (ROOT / "social.py").read_text(encoding="utf-8")
DB_SOURCE = (ROOT / "scoped_database.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")


def test_live_signatures_have_one_persisted_bot_owned_card_per_channel():
    assert 'SIGNATURE_STATE_KEY = "profile_signature_state"' in SOURCE
    assert 'SIGNATURE_MARKER = "Idle Grow Live Signature"' in SOURCE
    assert 'state[str(channel_id)] = {' in SOURCE
    assert 'message.author.id != self.bot.user.id' in SOURCE
    assert 'footer == SIGNATURE_MARKER' in SOURCE
    assert 'await old_message.delete()' in SOURCE
    assert 'await channel.send(' in SOURCE
    assert "message.webhook_id is not None" in SOURCE
    assert "message.author.bot" in SOURCE


def test_repeated_messages_are_debounced_and_same_speaker_is_suppressed():
    assert "SIGNATURE_DEBOUNCE_SECONDS" in SOURCE
    assert "previous.cancel()" in SOURCE
    assert "if self._pending.get(key) is task:" in SOURCE
    assert "self._pending.pop(key, None)" in SOURCE
    assert "self._channel_generation.get(key) != generation" in SOURCE
    assert "self._debounced_refresh(message, generation)" in SOURCE
    assert "SIGNATURE_CHANNEL_COOLDOWN_SECONDS" in SOURCE
    assert "SIGNATURE_USER_COOLDOWN_SECONDS" in SOURCE
    assert "SIGNATURE_SAME_SPEAKER_REFRESH_SECONDS" in SOURCE
    assert "prior_user_id == member.id" in SOURCE
    assert "prior_fingerprint == fingerprint" in SOURCE
    assert "channel.last_message_id == old_message.id" in SOURCE


def test_restart_reconciliation_collapses_duplicate_signature_cards():
    assert "async def reconcile_guild" in SOURCE
    assert "channel.history(limit=SIGNATURE_HISTORY_SCAN_LIMIT)" in SOURCE
    assert "cards.sort(key=lambda message: message.id, reverse=True)" in SOURCE
    assert "keep = cards[0] if cards else None" in SOURCE
    assert "for duplicate in cards[1:]" in SOURCE
    assert "await duplicate.delete()" in SOURCE


def test_platforms_and_privacy_use_scoped_persistence():
    assert 'IDENTITY_KEY = "profile_identity"' in SOURCE
    assert 'GLOBAL_PRIVACY_KEY = "profile_privacy"' in SOURCE
    assert 'GUILD_PRIVACY_KEY = "profile_signature_privacy"' in SOURCE
    assert "await self.bot.db.get_account" in SOURCE
    assert "self.bot.db.mark_account_dirty" in SOURCE
    assert "await self.bot.db.get_profile" in SOURCE
    assert "self.bot.db.mark_profile_dirty" in SOURCE
    assert "server_allowed" in SOURCE
    assert "visible &= server_allowed" in SOURCE
    assert "visible = global_visible - server_hidden" in SOURCE


def test_platform_registry_covers_requested_services_without_arbitrary_links():
    for key in (
        '"steam"',
        '"epic"',
        '"xbox"',
        '"playstation"',
        '"nintendo"',
        '"riot"',
        '"battlenet"',
        '"roblox"',
        '"twitch"',
        '"youtube"',
        '"kick"',
        '"custom"',
    ):
        assert key in SOURCE
    assert 'parsed.scheme.lower() != "https"' in SOURCE
    assert "host not in spec.hosts" in SOURCE
    assert "parsed.query" in SOURCE
    assert "parsed.fragment" in SOURCE
    assert "Custom platforms are username-only for safety." in SOURCE
    assert "PROFILE_PLATFORM_EMOJI_" in SOURCE


def test_user_controls_are_private_without_breaking_existing_profile_command():
    assert 'name="profile-settings"' in SOURCE
    assert "ephemeral=True" in SOURCE
    assert 'name="profile", aliases=["me", "stats"]' in SOCIAL_SOURCE
    assert 'self.bot.get_cog("ProfileSignatures")' in SOCIAL_SOURCE
    assert "await signatures.build_full_profile" in SOCIAL_SOURCE


def test_setup_is_optional_disabled_by_default_and_channel_selected():
    assert "class SignatureSetupView" in SETUP_SOURCE
    assert "class SignatureChannelSelect" in SETUP_SOURCE
    assert 'label="Profile Signatures"' in SETUP_SOURCE
    assert 'label="Enable Signatures"' in SETUP_SOURCE
    assert 'label="Disable Signatures"' in SETUP_SOURCE
    assert "async def build_signature_panel" in SETUP_SOURCE
    assert "invalidate_guild_cards" in SETUP_SOURCE
    assert '"profile_signatures"' in MAIN_SOURCE
    assert '"profile_signature_config": {' in DB_SOURCE
    assert '"enabled": False' in DB_SOURCE
    assert '"profile_signature_state": {}' in DB_SOURCE


def test_runtime_never_uses_webhooks_or_reposts_user_content():
    lowered = SOURCE.lower()
    assert "webhook.send" not in lowered
    assert "create_webhook" not in lowered
    assert "message.content" not in SOURCE
    assert "allowed_mentions=discord.AllowedMentions.none()" in SOURCE
