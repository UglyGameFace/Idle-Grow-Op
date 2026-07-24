import os

import aiohttp
from discord.ext import commands


AI_BASE_URL = "https://openrouter.ai/api/v1"
AI_MODEL_CHAT = "openai/gpt-4o-mini"

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


class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")

    @commands.hybrid_command(name="chat", aliases=["ask", "plug", "yo"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def chat(self, ctx, *, message: str):
        """Talk to The Plug (AI)."""
        if not self.api_key:
            return await ctx.send("❌ **AI Error:** API Key is missing.")

        payload = {
            "model": AI_MODEL_CHAT,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
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

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{AI_BASE_URL}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            print(f"⚠️ AI Error: {error_text}")
                            return await ctx.send("🔌 **The Plug is sleeping.** (API Error)")
                        data = await response.json()
            except (aiohttp.ClientError, KeyError, TypeError, ValueError) as exc:
                print(f"AI Exception: {exc}")
                return await ctx.send("❌ **Connection Failed.** The Plug is offline.")

        reply = str(data["choices"][0]["message"]["content"])
        if len(reply) > 2000:
            reply = reply[:1990] + "..."
        await ctx.send(reply)


async def setup(bot):
    await bot.add_cog(AI(bot))
