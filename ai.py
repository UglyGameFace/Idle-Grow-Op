import asyncio
import os
from typing import Any

import aiohttp
from discord.ext import commands


AI_BASE_URL = "https://openrouter.ai/api/v1"
AI_MODEL_CHAT = "openai/gpt-4o-mini"
AI_REQUEST_TIMEOUT_SECONDS = 30

SYSTEM_PROMPT = """
You are 'The Plug', a street-smart, helpful, and chill Discord bot assistant for a Weed Tycoon game called 'Stoney Baloney'.
- You speak in mild slang (bruh, fam, bet, say less), but you are intelligent and clear.
- You help users with game strategy (growing, selling, heists).
- You are loyal to the crew.
- Keep responses concise (under 2000 chars).
- GAME INFO:
  - !plant <strain> to grow weed.
  - !heist to steal money (risk jail).
  - !shop to buy seeds and gear.
  - !process to make hash/wax.
"""


def _extract_reply(payload: Any) -> str:
    """Return the first assistant text response or raise a clear parse error."""
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
        401: "❌ **AI configuration error:** the OpenRouter API key is invalid.",
        402: "💳 **The Plug is out of AI credits.** Add OpenRouter credits and try again.",
        403: "⛔ **The AI request was blocked by the provider.**",
        429: "⏳ **The Plug is getting hit too fast.** Try again shortly.",
        502: "🔌 **The selected AI provider is temporarily unavailable.**",
        503: "🔌 **No AI provider is currently available.** Try again shortly.",
    }
    return messages.get(status, "🔌 **The Plug is sleeping.** The AI service returned an error.")


class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # This cog calls OpenRouter directly. An OpenAI key is not valid here.
        self.api_key = str(os.getenv("OPENROUTER_API_KEY", "")).strip()

    @commands.hybrid_command(name="chat", aliases=["ask", "plug", "yo"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def chat(self, ctx, *, message: str):
        """Talk to The Plug (AI)."""
        if not self.api_key:
            return await ctx.send(
                "❌ **AI configuration error:** `OPENROUTER_API_KEY` is missing."
            )

        prompt = str(message).strip()
        if not prompt:
            return await ctx.send("❌ Give The Plug something to answer.")

        payload = {
            "model": AI_MODEL_CHAT,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": 600,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://discord.com",
            "X-Title": "Stoney Baloney",
        }
        timeout = aiohttp.ClientTimeout(total=AI_REQUEST_TIMEOUT_SECONDS)

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"{AI_BASE_URL}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status != 200:
                            error_text = (await response.text())[:500]
                            print(
                                f"⚠️ OpenRouter chat error status={response.status}: {error_text}"
                            )
                            return await ctx.send(_public_api_error(response.status))
                        data = await response.json(content_type=None)
                reply = _extract_reply(data)
            except asyncio.TimeoutError:
                return await ctx.send("⌛ **The AI request timed out.** Try again shortly.")
            except aiohttp.ClientError as exc:
                print(f"OpenRouter connection error: {exc}")
                return await ctx.send("❌ **Connection failed.** The AI service is unreachable.")
            except (ValueError, TypeError) as exc:
                print(f"OpenRouter response error: {exc}")
                return await ctx.send("❌ **The AI returned an invalid response.** Try again.")

        if len(reply) > 2000:
            reply = reply[:1990] + "..."
        await ctx.send(reply)


async def setup(bot):
    await bot.add_cog(AI(bot))
