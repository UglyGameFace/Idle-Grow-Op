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


def test_sesh_rewards_require_real_voice_presence_and_are_capped():
    source = _source()

    assert "channel.members" in source or ".members" in source
    assert "member.bot" in source or "not member.bot" in source
    assert "XP_MAX_PER_USER" in source or "SESH_XP_MAX_PER_USER" in source
    assert "self_mute" in source
    assert "self_deaf" in source
    assert "STREAK" in source
    assert "ROTATION" in source


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
