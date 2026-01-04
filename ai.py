import discord
import aiohttp
import os
import json
import asyncio
from discord.ext import commands
from utils import db_manager, jail_guard, _env_str

# ==========================================================
# 🧠 AI CONFIGURATION
# ==========================================================
AI_BASE_URL = "https://openrouter.ai/api/v1"
AI_MODEL_CHAT = "openai/gpt-4o-mini"
AI_MODEL_IMAGE = "stabilityai/stable-diffusion-xl-base-1.0"

# The Persona
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
        # Support both env var names
        self.api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")

    # ==========================================================
    # 💬 CHAT COMMAND
    # ==========================================================
    @commands.hybrid_command(name="chat", aliases=["ask", "plug", "yo"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def chat(self, ctx, *, message: str):
        """Talk to The Plug (AI)."""
        if not self.api_key:
            return await ctx.send("❌ **AI Error:** API Key is missing.")

        async with ctx.typing():
            try:
                # payload setup
                payload = {
                    "model": AI_MODEL_CHAT,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": message}
                    ],
                    "temperature": 0.8,
                    "max_tokens": 600
                }

                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://discord.com",
                    "X-Title": "Stoney Baloney"
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(f"{AI_BASE_URL}/chat/completions", json=payload, headers=headers) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            print(f"⚠️ AI Error: {text}")
                            return await ctx.send("🔌 **The Plug is sleeping.** (API Error)")
                        
                        data = await resp.json()
                        reply = data["choices"][0]["message"]["content"]
                        
                        if len(reply) > 2000:
                            reply = reply[:1990] + "..."
                            
                        await ctx.send(reply)

            except Exception as e:
                print(f"AI Exception: {e}")
                await ctx.send("❌ **Connection Failed.** The Plug is offline.")

    # ==========================================================
    # 🎨 IMAGE GENERATION
    # ==========================================================
    @commands.hybrid_command(name="imagine", aliases=["draw", "img"])
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def imagine(self, ctx, *, prompt: str):
        """Generate an image (Costs $500)."""
        if not self.api_key:
            return await ctx.send("❌ API Key missing.")

        user = self.bot.db.get_user(ctx.author.id)
        
        # 1. Cost Check
        cost = 500
        if user.get("grams", 0) < cost:
            return await ctx.send(f"💸 **Art costs money.** You need ${cost}.")
        
        # 2. Deduct
        user["grams"] -= cost
        await self.bot.db.save()

        msg = await ctx.send(f"🎨 **Painting:** `{prompt}`... (Cost: ${cost})")

        try:
            # Note: For OpenRouter, image gen support varies.
            # If using direct OpenAI, URL is https://api.openai.com/v1/images/generations
            # If using OpenRouter, it passes through to providers like Stability AI
            
            # This payload targets OpenRouter's standard interface (or OpenAI's)
            url = f"{AI_BASE_URL}/images/generations" if "openrouter" not in AI_BASE_URL else "https://api.openai.com/v1/images/generations"
            
            # Adjust payload for model support
            payload = {
                "model": "dall-e-3", # or "stabilityai/stable-diffusion-xl-base-1.0"
                "prompt": f"Cool digital art, {prompt}",
                "n": 1,
                "size": "1024x1024"
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        # Refund
                        user["grams"] += cost
                        await self.bot.db.save()
                        return await msg.edit(content="❌ **Generation Failed.** Refunded.")
                    
                    data = await resp.json()
                    image_url = data["data"][0]["url"]
                    
                    embed = discord.Embed(title="🎨 Generated Art", description=prompt, color=discord.Color.purple())
                    embed.set_image(url=image_url)
                    embed.set_footer(text=f"Generated by {ctx.author.name}")
                    
                    await msg.edit(content=None, embed=embed)

        except Exception as e:
            user["grams"] += cost
            await self.bot.db.save()
            await msg.edit(content=f"❌ **Error:** {e}")

async def setup(bot):
    await bot.add_cog(AI(bot))