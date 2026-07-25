from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI_SOURCE = (ROOT / "ai.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")
SETUP_SOURCE = (ROOT / "setup.py").read_text(encoding="utf-8")


def test_ai_is_guild_scoped_and_disabled_by_default():
    assert 'AI_CONFIG_KEY = "ai_config"' in AI_SOURCE
    assert 'AI_ENABLED_KEY = "enabled"' in AI_SOURCE
    assert 'config.get(AI_ENABLED_KEY, False)' in AI_SOURCE
    assert 'await self.bot.db.get_world(int(guild_id))' in AI_SOURCE
    assert 'Idle Grow AI is optional and disabled for this server' in AI_SOURCE


def test_ai_config_reads_do_not_mutate_world_state():
    assert 'config = world.get(AI_CONFIG_KEY)' in AI_SOURCE
    assert 'world.setdefault(AI_CONFIG_KEY' not in AI_SOURCE


def test_ai_uses_host_configuration_without_exposing_secrets():
    assert 'OPENROUTER_API_KEY' in AI_SOURCE
    assert 'OPENROUTER_CHAT_MODEL' in AI_SOURCE
    assert 'OPENROUTER_CHAT_MODELS' in AI_SOURCE
    assert 'OPENROUTER_MAX_TOKENS' in AI_SOURCE
    assert 'AI_COOLDOWN_SECONDS' in AI_SOURCE
    assert 'def _int_env(' in AI_SOURCE
    assert 'except (TypeError, ValueError)' in AI_SOURCE
    assert 'replace(self.api_key, "[redacted]")' in AI_SOURCE
    assert 'No user prompt, response, or API key was included.' in AI_SOURCE
    assert 'await response.text()' not in AI_SOURCE
    assert 'provider_text' not in AI_SOURCE


def test_ai_provider_failures_use_real_guild_error_reporter():
    assert 'async def _report_command_error(' in MAIN_SOURCE
    assert 'bot.report_command_error = _report_command_error' in MAIN_SOURCE
    assert 'reporter = getattr(self.bot, "report_command_error", None)' in AI_SOURCE
    assert 'await reporter(' in AI_SOURCE


def test_ai_identity_and_game_guidance_are_current():
    assert 'Idle Grow Op' in AI_SOURCE
    assert 'Stoney Baloney' not in AI_SOURCE
    assert '!plant' not in AI_SOURCE
    assert '`/plant`' in AI_SOURCE
    assert '`/harvest`' in AI_SOURCE
    assert '`/shop`' in AI_SOURCE
    compact = " ".join(AI_SOURCE.split())
    assert 'or create images' in compact


def test_ai_request_path_supports_model_fallback_and_health_tests():
    assert 'async def request_reply' in AI_SOURCE
    assert 'for model in self.models:' in AI_SOURCE
    assert 'health_test: bool = False' in AI_SOURCE
    assert '80 if health_test else AI_MAX_TOKENS' in AI_SOURCE
    assert 'service_health' in AI_SOURCE
    assert '_public_api_error' in AI_SOURCE


def test_setup_integration_remains_required_for_completion():
    assert 'class AISetupView' in SETUP_SOURCE
    assert 'label="Optional AI"' in SETUP_SOURCE
    assert 'async def update_ai_config' in SETUP_SOURCE
    assert 'async def build_ai_panel' in SETUP_SOURCE
    assert 'name="🤖 Optional AI"' in SETUP_SOURCE
