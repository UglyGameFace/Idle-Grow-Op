from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp
from discord.ext import commands

from persistence_context import GuildContextRequired, require_guild_id


logger = logging.getLogger(__name__)

AI_BASE_URL = "https://openrouter.ai/api/v1"
AI_CONFIG_KEY = "ai_config"
AI_ENABLED_KEY = "enabled"
DEFAULT_AI_MODEL = "openrouter/free"


def _int_env(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        value = default
    else:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid integer configuration %s=%r; using default %s",
                name,
                raw_value,
                default,
            )
            value = default
    return max(minimum, min(maximum, value))


AI_REQUEST_TIMEOUT_SECONDS = _int_env(
    "OPENROUTER_TIMEOUT_SECONDS",
    30,
    minimum=5,
    maximum=60,
)
AI_COOLDOWN_SECONDS = _int_env(
    "AI_COOLDOWN_SECONDS",
    5,
    minimum=3,
    maximum=60,
)
AI_MAX_TOKENS = _int_env(
    "OPENROUTER_MAX_TOKENS",
    350,
    minimum=100,
    maximum=1200,
)

SYSTEM_PROMPT = """
You are The Plug, the concise and helpful in-game assistant for Idle Grow Op.

Help players understand the current Discord game without inventing features, prices,
items, outcomes, commands, or server rules. Use the bot's slash-command wording and
recommend `/help`, `/profile`, `/shop`, `/inventory`, `/plant`, `/harvest`, `/process`,
`/sell`, `/tasks`, and `/crew` when relevant. Explain that server economies and progress
may be guild-scoped. Sesh is an optional server feature configured by server managers.
Never claim to perform a game action, grant currency/items/XP, expose secrets, or create
images. Keep replies clear, friendly, and under Discord's 2,000-character limit.
""".strip()


class AIServiceError(Exception):
    def __init__(
        self,
        public_message: str,
        log_message: str,
        status: int | None = None,
    ) -> None:
        super().__init__(public_message)
        self.public_message = public_message
        self.log_message = log_message
        self.status = status


def _extract_reply(payload: Any) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("OpenRouter returned no assistant message") from exc

    if isinstance(content, str):
        reply = content.strip()
    elif isinstance(content, list):
        reply = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    else:
        reply = ""

    if not reply:
        raise ValueError("OpenRouter returned an empty assistant message")
    return reply


def _public_api_error(status: int) -> str:
    messages = {
        400: "❌ **The AI request was rejected.** Try rewording it.",
        401: "❌ **The OpenRouter API key is invalid.**",
        402: "💳 **Idle Grow AI is temporarily out of provider credits.**",
        403: "⛔ **The AI provider blocked that request.**",
        408: "⌛ **The AI provider timed out.** Try again shortly.",
        429: "⏳ **Idle Grow AI is getting hit too fast.** Try again shortly.",
        502: "🔌 **The selected AI provider is temporarily unavailable.**",
        503: "🔌 **No AI provider is currently available.** Try again shortly.",
    }
    return messages.get(
        status,
        "🔌 **Idle Grow AI is temporarily unavailable.** Try again shortly.",
    )


def _configured_models() -> list[str]:
    configured = [
        value.strip()
        for value in os.getenv("OPENROUTER_CHAT_MODELS", "").split(",")
        if value.strip()
    ]
    primary = os.getenv("OPENROUTER_CHAT_MODEL", DEFAULT_AI_MODEL).strip()
    models = [primary or DEFAULT_AI_MODEL, *configured]
    return list(dict.fromkeys(models))


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api_key = str(os.getenv("OPENROUTER_API_KEY", "")).strip()
        self.models = _configured_models()

    async def _guild_config(self, guild_id: int) -> dict:
        world = await self.bot.db.get_world(int(guild_id))
        config = world.get(AI_CONFIG_KEY)
        return dict(config) if isinstance(config, dict) else {}

    async def is_enabled(self, guild_id: int) -> bool:
        config = await self._guild_config(guild_id)
        return bool(config.get(AI_ENABLED_KEY, False))

    def service_health(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "OpenRouter key is missing from the bot host"
        if not self.models:
            return False, "No OpenRouter chat model is configured"
        return True, f"Ready with {len(self.models)} configured model option(s)"

    async def _report_failure(
        self,
        guild_id: int,
        *,
        category: str,
        detail: str,
        status: int | None = None,
    ) -> None:
        safe_detail = detail.replace(self.api_key, "[redacted]") if self.api_key else detail
        logger.warning(
            "Idle Grow AI failure guild=%s category=%s status=%s detail=%s",
            guild_id,
            category,
            status,
            safe_detail[:500],
        )
        reporter = getattr(self.bot, "report_command_error", None)
        if not callable(reporter):
            logger.error("Guild error reporter is unavailable for guild %s", guild_id)
            return
        try:
            await reporter(
                guild_id=guild_id,
                title="Idle Grow AI provider error",
                description=(
                    f"Category: {category}\nStatus: {status or 'n/a'}\n"
                    "No user prompt, response, or API key was included."
                ),
            )
        except Exception:
            logger.exception("Could not route AI failure for guild %s", guild_id)

    async def request_reply(
        self,
        guild_id: int,
        prompt: str,
        *,
        health_test: bool = False,
    ) -> str:
        healthy, health_detail = self.service_health()
        if not healthy:
            raise AIServiceError(
                "❌ **Idle Grow AI is not configured on the bot host yet.**",
                health_detail,
            )

        user_prompt = str(prompt).strip()
        if not user_prompt:
            raise AIServiceError(
                "❌ Give Idle Grow AI something to answer.",
                "empty prompt rejected",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://discord.com",
            "X-Title": "Idle Grow Op",
        }
        timeout = aiohttp.ClientTimeout(total=AI_REQUEST_TIMEOUT_SECONDS)
        last_error: AIServiceError | None = None

        for model in self.models:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 80 if health_test else AI_MAX_TOKENS,
            }
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"{AI_BASE_URL}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status != 200:
                            last_error = AIServiceError(
                                _public_api_error(response.status),
                                f"model={model} provider_status={response.status}",
                                response.status,
                            )
                            if response.status in {401, 402, 403, 429}:
                                break
                            continue
                        data = await response.json(content_type=None)
                reply = _extract_reply(data)
                return reply[:1990] + "..." if len(reply) > 2000 else reply
            except asyncio.TimeoutError:
                last_error = AIServiceError(
                    "⌛ **The AI request timed out.** Try again shortly.",
                    f"model={model} request timed out",
                )
            except aiohttp.ClientError as exc:
                last_error = AIServiceError(
                    "❌ **Connection failed.** The AI service is unreachable.",
                    f"model={model} connection={type(exc).__name__}",
                )
            except (ValueError, TypeError) as exc:
                last_error = AIServiceError(
                    "❌ **The AI returned an invalid response.** Try again.",
                    f"model={model} parse={type(exc).__name__}: {exc}",
                )

        failure = last_error or AIServiceError(
            "🔌 **Idle Grow AI is temporarily unavailable.**",
            "all configured models failed without a response",
        )
        await self._report_failure(
            guild_id,
            category="health_test" if health_test else "chat",
            detail=failure.log_message,
            status=failure.status,
        )
        raise failure

    @commands.hybrid_command(name="chat", aliases=["ask", "plug", "yo"])
    @commands.dynamic_cooldown(
        lambda _ctx: commands.Cooldown(1, AI_COOLDOWN_SECONDS),
        commands.BucketType.user,
    )
    async def chat(self, ctx: commands.Context, *, message: str) -> None:
        """Ask the optional Idle Grow AI assistant for game help."""
        try:
            guild_id = require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return

        if not await self.is_enabled(guild_id):
            await ctx.send(
                "ℹ️ Idle Grow AI is optional and disabled for this server. "
                "A server manager can enable it in `/setup`."
            )
            return

        async with ctx.typing():
            try:
                reply = await self.request_reply(guild_id, message)
            except AIServiceError as exc:
                await ctx.send(exc.public_message)
                return
        await ctx.send(reply)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AI(bot))
