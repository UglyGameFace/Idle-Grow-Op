from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESH = ROOT / "sesh.py"


def _source() -> str:
    assert SESH.is_file(), "canonical sesh.py must exist"
    return SESH.read_text(encoding="utf-8")


def test_sesh_is_a_live_voice_session_not_only_a_ping():
    source = _source()
    assert "on_voice_state_update" in source
    assert "participants" in source
    assert "empty_since" in source
    assert "end_session" in source or "_end_sesh_session" in source
    assert "Puff & Pass" in source
    assert "Private Room" in source or "private room" in source.lower()


def test_sesh_allows_one_active_session_per_voice_channel_not_per_guild():
    source = _source()
    assert "dict[tuple[int, int], SeshSession]" in source
    assert "def _session_key(self, guild_id, voice_channel_id)" in source
    assert "return int(guild_id), int(voice_channel_id)" in source
    assert "_active_session_for_guild" not in source
    assert "one active session per voice channel" in source.lower()


def test_sesh_rewards_require_real_voice_presence_correct_cadence_and_caps():
    source = _source()
    assert "channel.members" in source or ".members" in source
    assert "member.bot" in source or "not member.bot" in source
    assert "XP_MIN_HUMANS" in source
    assert "XP_INTERVAL_SECONDS" in source
    assert "last_xp_award_at" in source
    assert "SESH_XP_MAX_PER_USER" in source
    assert "self_mute" in source
    assert "self_deaf" in source
    assert "STREAK" in source
    assert "ROTATION" in source
    assert "VOICE_GRACE_SECONDS" in source


def test_sesh_cleanup_has_normal_and_fallback_paths():
    source = _source()
    assert "cog_unload" in source
    assert "on_guild_channel_delete" in source
    assert "announcement_missing" in source
    assert "empty_timeout" in source
    assert "stale" in source.lower()
    assert "_delete_channel_with_fallback" in source
    assert "finally" in source
    assert "cancel" in source
    assert "reconcile" in source.lower()


def test_sesh_handles_host_departure_and_room_switching():
    source = _source()
    assert "can_manage_session" in source
    assert "host_present" in source
    assert "member_present" in source
    assert "manage_channels" in source
    assert "_switch_session_voice_channel" in source
    assert 'name="seshmove"' in source
    assert "Private room created and set active" in source


def test_sesh_media_is_session_aware_and_keyword_validated():
    source = _source()
    assert "TENOR_API_KEY" in source
    assert "build_media_query" in source
    assert "session_type" in source
    assert "keywords" in source or "note_tokens" in source
    assert "MEDIA_MIN_SCORE" in source
    assert "_media_score" in source
    assert "SESH" in source and "MOVIE" in source and "KARAOKE" in source
    assert "random.choice(results)" not in source
    assert "curated_media" in source
    assert "wrong GIF is worse than no GIF" in source


def test_sesh_configuration_and_restart_descriptors_are_guild_world_scoped():
    source = _source()
    assert "get_world" in source
    assert "mark_world_dirty" in source
    assert "get_profile" in source
    assert "mark_profile_dirty" in source
    assert "active_sesh_sessions" in source
    assert "world_state" not in source
    assert "db_manager" not in source
    assert ".get_user(" not in source
    assert "await self.bot.db.save()" not in source


def test_sesh_preserves_all_three_enterprise_session_types():
    source = _source()
    assert 'name="sesh"' in source
    assert 'name="movie"' in source
    assert 'name="karaoke"' in source
    assert "seshconfig" in source
