import asyncio
import os
from pathlib import Path

import pytest

from ai import AI, _extract_reply, _int_env, _public_api_error


ROOT = Path(__file__).resolve().parents[1]


class BotStub:
    pass


class DatabaseStub:
    def __init__(self, world):
        self.world = world

    async def get_world(self, guild_id):
        assert guild_id == 123
        return self.world


class ConfigBotStub:
    def __init__(self, world):
        self.db = DatabaseStub(world)


def test_chat_uses_only_openrouter_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-valid-for-openrouter")
    assert AI(BotStub()).api_key == ""

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    assert AI(BotStub()).api_key == "sk-or-v1-test"


def test_int_env_falls_back_and_clamps_without_crashing(monkeypatch):
    monkeypatch.setenv("AI_TEST_INTEGER", "thirty")
    assert _int_env("AI_TEST_INTEGER", 30, minimum=5, maximum=60) == 30

    monkeypatch.setenv("AI_TEST_INTEGER", "1")
    assert _int_env("AI_TEST_INTEGER", 30, minimum=5, maximum=60) == 5

    monkeypatch.setenv("AI_TEST_INTEGER", "500")
    assert _int_env("AI_TEST_INTEGER", 30, minimum=5, maximum=60) == 60


def test_guild_config_read_does_not_mutate_world():
    world = {}
    config = asyncio.run(AI(ConfigBotStub(world))._guild_config(123))

    assert config == {}
    assert world == {}


def test_extract_reply_accepts_standard_openrouter_response():
    payload = {"choices": [{"message": {"content": "  Say less, fam.  "}}]}
    assert _extract_reply(payload) == "Say less, fam."


def test_extract_reply_accepts_text_parts():
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "First "},
                        {"type": "text", "text": "second"},
                    ]
                }
            }
        ]
    }
    assert _extract_reply(payload) == "First second"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": None}}]},
    ],
)
def test_extract_reply_rejects_missing_or_empty_content(payload):
    with pytest.raises(ValueError):
        _extract_reply(payload)


def test_public_errors_distinguish_configuration_credits_and_rate_limits():
    assert "invalid" in _public_api_error(401).lower()
    assert "credits" in _public_api_error(402).lower()
    assert "try again" in _public_api_error(429).lower()


def test_chat_source_matches_openrouter_contract_and_has_timeout():
    source = (ROOT / "ai.py").read_text(encoding="utf-8")

    assert 'AI_BASE_URL = "https://openrouter.ai/api/v1"' in source
    assert 'DEFAULT_AI_MODEL = "openrouter/free"' in source
    assert 'os.getenv("OPENROUTER_CHAT_MODEL", DEFAULT_AI_MODEL)' in source
    assert 'os.getenv("OPENROUTER_CHAT_MODELS", "")' in source
    assert 'os.getenv("OPENROUTER_API_KEY", "")' in source
    assert "OPENAI_API_KEY" not in source
    assert "aiohttp.ClientTimeout" in source
    assert '/chat/completions"' in source
    assert '"Authorization": f"Bearer {self.api_key}"' in source
    assert "response.json(content_type=None)" in source


def test_image_generation_remains_absent():
    source = (ROOT / "ai.py").read_text(encoding="utf-8")

    assert 'name="imagine"' not in source
    assert 'aliases=["draw", "img"]' not in source
    assert "/images/generations" not in source
    assert "dall-e" not in source.lower()
