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
    assert "Switch Room" in source or "switch_session" in source


def test_sesh_allows_one_active_session_per_voice_channel_not_per_guild():
    source = _source()

    assert "(guild_id, voice_channel_id)" in source or "(guild_id, vc_id)" in source
    assert "_session_key" in source
    assert "voice_channel_id" in source or "vc_id" in source
    assert "_active_session_for_guild" not in source
    assert "one active session per voice channel" in source.lower()


def test_sesh_rewards_require_real_voice_presence_and_are_capped():
    source = _source()

    assert "channel.members" in source or ".members" in source
    assert "member.bot" in source or "not member.bot" in source
    assert "XP_MAX_PER_USER" in source or "SESH_XP_MAX_PER_USER" in source
    assert "self_mute" in source
    assert "self_deaf" in source
    assert "STREAK" in source
    assert "ROTATION" in source


def test_sesh_cleanup_has_normal_and_fallback_paths():
    source = _source()

    assert "cog_unload" in source
    assert "on_guild_channel_delete" in source
    assert "empty_since" in source
    assert "stale" in source.lower()
    assert "private" in source.lower() and "delete" in source.lower()
    assert "finally" in source
    assert "cancel" in source
    assert "prune" in source.lower() or "reconcile" in source.lower()


def test_sesh_media_is_session_aware_and_keyword_validated():
    source = _source()

    assert "TENOR_API_KEY" in source
    assert "media_query" in source or "build_media_query" in source
    assert "session_type" in source
    assert "keywords" in source or "note_tokens" in source
    assert "score" in source.lower()
    assert "SESH" in source and "MOVIE" in source and "KARAOKE" in source
    assert "random.choice(results)" not in source


def test_sesh_configuration_is_guild_world_scoped():
    source = _source()

    assert "get_world" in source
    assert "mark_world_dirty" in source
    assert "get_profile" in source
    assert "mark_profile_dirty" in source
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
