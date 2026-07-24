import os
from pathlib import Path

import pytest

from ai import AI, _extract_reply, _public_api_error


ROOT = Path(__file__).resolve().parents[1]


class BotStub:
    pass


def test_chat_uses_only_openrouter_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-valid-for-openrouter")
    assert AI(BotStub()).api_key == ""

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    assert AI(BotStub()).api_key == "sk-or-v1-test"


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
    assert 'AI_MODEL_CHAT = "openai/gpt-4o-mini"' in source
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
