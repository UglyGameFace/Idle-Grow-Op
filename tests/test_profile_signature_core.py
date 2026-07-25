from pathlib import Path

import pytest

from profile_signatures import (
    _configured_platform_emoji,
    DEFAULT_VISIBLE_FIELDS,
    effective_visible_fields,
    normalize_platform_entry,
    normalize_platform_url,
    shared_platform_entries,
)


def test_safe_platform_urls_are_normalized_to_official_hosts():
    assert (
        normalize_platform_url(
            "steam",
            "https://www.steamcommunity.com/id/UglyGameFace/",
        )
        == "https://steamcommunity.com/id/UglyGameFace"
    )
    assert (
        normalize_platform_url(
            "twitch",
            "https://www.twitch.tv/UglyGameFace",
        )
        == "https://twitch.tv/UglyGameFace"
    )
    assert (
        normalize_platform_url(
            "roblox",
            "https://www.roblox.com/users/123456/profile",
        )
        == "https://roblox.com/users/123456/profile"
    )


@pytest.mark.parametrize(
    ("platform", "url"),
    [
        ("steam", "http://steamcommunity.com/id/UglyGameFace"),
        ("steam", "https://steamcommunity.com.evil.example/id/UglyGameFace"),
        ("steam", "https://steamcommunity.com/id/UglyGameFace?redirect=evil"),
        ("steam", "https://steamcommunity.com:bad/id/UglyGameFace"),
        ("twitch", "https://twitch.tv/UglyGameFace/extra"),
        ("youtube", "https://youtube.com/watch?v=abc"),
        ("roblox", "https://roblox.com/games/123"),
    ],
)
def test_platform_links_reject_insecure_disguised_or_non_profile_urls(platform, url):
    with pytest.raises(ValueError):
        normalize_platform_url(platform, url)


def test_username_only_platforms_never_accept_or_invent_links():
    entry = normalize_platform_entry("epic", "UglyGameFace", shared=True)
    assert entry["username"] == "UglyGameFace"
    assert entry["url"] == ""

    with pytest.raises(ValueError):
        normalize_platform_entry(
            "epic",
            "UglyGameFace",
            "https://example.com/not-epic",
            shared=True,
        )


def test_platform_identity_is_private_until_explicitly_shared():
    private = normalize_platform_entry("steam", "UglyGameFace")
    public = normalize_platform_entry("steam", "UglyGameFace", shared=True)
    account = {
        "profile_identity": {
            "platforms": {
                "private": private,
                "public": public,
            }
        }
    }

    entries = shared_platform_entries(account)
    assert [entry["key"] for entry in entries] == ["public"]


def test_user_privacy_is_stricter_than_server_allowed_fields():
    account = {
        "profile_privacy": {
            "signature_enabled": True,
            "visible_fields": ["level", "crew", "wealth", "platforms"],
        }
    }
    profile = {
        "profile_signature_privacy": {
            "signature_disabled": False,
            "hidden_fields": ["wealth"],
        }
    }

    assert effective_visible_fields(
        account,
        profile,
        server_allowed={"level", "wealth", "rank"},
    ) == {"level"}


def test_signature_opt_out_hides_every_field():
    account = {
        "profile_privacy": {
            "signature_enabled": False,
            "visible_fields": list(DEFAULT_VISIBLE_FIELDS),
        }
    }
    assert effective_visible_fields(account, {}) == set()

    profile = {
        "profile_signature_privacy": {
            "signature_disabled": True,
            "hidden_fields": [],
        }
    }
    assert effective_visible_fields({}, profile) == set()


def test_custom_application_emoji_override_requires_a_real_discord_emoji(monkeypatch):
    monkeypatch.setenv("PROFILE_PLATFORM_EMOJI_STEAM", "<:steam:123456789012345678>")
    assert (
        _configured_platform_emoji("steam", "🎮")
        == "<:steam:123456789012345678>"
    )

    monkeypatch.setenv("PROFILE_PLATFORM_EMOJI_STEAM", "https://evil.example/logo.png")
    assert _configured_platform_emoji("steam", "🎮") == "🎮"


def test_explicit_platform_sharing_enables_platform_visibility_in_source():
    source = (Path(__file__).resolve().parents[1] / "profile_signatures.py").read_text(
        encoding="utf-8"
    )
    assert 'if entry.get("shared", False):' in source
    assert 'visible.add("platforms")' in source
    assert "_safe_display(entry['username'], limit=80)" in source


def test_generation_bump_cancels_only_the_pending_debounce_task():
    import asyncio

    from profile_signatures import ProfileSignatures

    class BotStub:
        guilds = []

    async def scenario():
        cog = ProfileSignatures(BotStub())
        key = (1, 2)
        pending = asyncio.create_task(asyncio.sleep(60))
        cog._pending[key] = pending
        generation = cog._bump_channel_generation(key)
        await asyncio.sleep(0)
        assert generation == 1
        assert cog._channel_generation[key] == 1
        assert key not in cog._pending
        assert pending.cancelled()

    asyncio.run(scenario())
