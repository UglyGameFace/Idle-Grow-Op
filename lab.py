import asyncio
import random
import time
from math import ceil

import discord
from discord.ext import commands

from economy_integrity import (
    flower_required_for_output,
    require_positive_amount,
    reserve_flower,
    restore_flower,
    split_reservation_penalty,
)
from utils import (
    CONCENTRATE_TYPES,
    SafeView,
    _xp_needed_for_level,
    add__progress,
    db_manager,
    has_item,
    jail_guard,
)


def _lab_format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m"
    return f"{int(seconds / 86400)}d {int((seconds % 86400) / 3600)}h"


def _lab_prestige_mult(user):
    prestige = int(user.get("prestige", 0))
    return 1.0 + (prestige * 0.05)


def _lab_market_value(user, base_value):
    world = db_manager.world_state
    market_mult = float(world.get("market_multiplier", 1.0))
    prestige_mult = _lab_prestige_mult(user)
    district_mult = 1.0
    district = world.get("district", {})
    if (
        district.get("owner_crew_id") == user.get("crew_id")
        and time.time() < district.get("expires_at", 0)
    ):
        district_mult = float(district.get("multiplier", 1.10))
    return int(base_value * market_mult * prestige_mult * district_mult)


def _credit_xp(user, amount):
    """Credit XP under the caller's mutation lock and report a level-up."""
    user["xp"] = int(user.get("xp", 0)) + int(amount)
    level = max(1, int(user.get("level", 1)))
    needed = _xp_needed_for_level(level)
    if user["xp"] >= needed:
        user["xp"] -= needed
        user["level"] = level + 1
        return user["level"]
    return None


class LabMinigameView(SafeView):
    def __init__(self, owner_id: int, conc_type: str, amount: int, target_zone: int):
        super().__init__(timeout=15)
        self.owner_id = int(owner_id)
        self.conc_type = str(conc_type)
        self.amount = int(amount)
        self.pressed = False
        self.success = False
        self.progress = 0
        self.target_zone = target_zone

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Not your lab session.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🧪 EXTRACT NOW!", style=discord.ButtonStyle.danger)
    async def extract(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pressed = True
        self.stop()
        if self.target_zone <= self.progress <= self.target_zone + 15:
            self.success = True
            content = f"✅ **PERFECT EXTRACTION!** Hit at {self.progress}%"
        else:
            reason = "Too Early!" if self.progress < self.target_zone else "Too Late!"
            content = f"💥 **BOOM!** {reason}"
        await interaction.response.edit_message(content=content, view=None)


class Lab(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="process", aliases=["cook"])
    async def process(self, ctx, concentrate_type: str = None, amount: str = "1"):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "process"):
            return

        if not concentrate_type:
            embed = discord.Embed(title="🧪 **Concentrate Lab (Queue)**", color=0x9B59B6)
            for conc_name, conc_data in CONCENTRATE_TYPES.items():
                required_tool = conc_data.get("req_item")
                available = not required_tool or has_item(user, required_tool)
                status = "✅" if available else f"🔒 Need {required_tool}"
                yield_pct = int(float(conc_data.get("yield_ratio", 0.15)) * 100)
                embed.add_field(
                    name=f"{status} {conc_name.title()}",
                    value=(
                        f"**Ratio:** {yield_pct}% Yield\n"
                        f"**Req:** Level {conc_data.get('level_req', 1)}"
                    ),
                    inline=True,
                )
            embed.set_footer(text="Use: !process [type] [amount] (e.g. !process wax 10)")
            return await ctx.send(embed=embed)

        c_type = concentrate_type.lower().strip()
        if c_type not in CONCENTRATE_TYPES:
            return await ctx.send(
                f"❌ **Invalid type.** Options: {', '.join(CONCENTRATE_TYPES.keys())}"
            )

        try:
            qty = require_positive_amount(amount)
            info = CONCENTRATE_TYPES[c_type]
            needed_flower = flower_required_for_output(qty, info.get("yield_ratio", 0.1))
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}.")

        required_level = int(info.get("level_req", 1))
        required_tool = info.get("req_item")
        now = time.time()
        duration = 300 * qty

        async with self.bot.db.lock:
            user = self.bot.db.get_user(ctx.author.id)
            if int(user.get("level", 1)) < required_level:
                return await ctx.send(f"🔒 **Level {required_level} Required.**")
            if required_tool and not has_item(user, required_tool):
                return await ctx.send(f"🛠️ You need a **{required_tool.title()}** to make this.")

            stash = user.setdefault("flower_stash", {})
            try:
                reservation = reserve_flower(stash, needed_flower)
            except ValueError:
                total_flower = sum(max(0, int(value)) for value in stash.values())
                return await ctx.send(
                    f"🌿 **Not enough flower.** Need {needed_flower}g total "
                    f"(You have {total_flower}g)."
                )

            user.setdefault("processing_queue", []).append(
                {
                    "type": c_type,
                    "amount": qty,
                    "start_time": now,
                    "finish_time": now + duration,
                    "flower_used": needed_flower,
                    "flower_sources": reservation,
                }
            )
            add__progress(user, "process_dabs", qty)
            await self.bot.db.save()

        embed = discord.Embed(
            title="⚗️ **Extraction Started**",
            description=f"Processing **{needed_flower}g flower** into **{qty}g {c_type.title()}**.",
            color=0xE67E22,
        )
        embed.add_field(name="⏳ Time", value=f"{int(duration / 60)} minutes", inline=True)
        embed.set_footer(text="Use !collect when the batch is ready.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="collect", aliases=["collectlab"])
    async def collect(self, ctx):
        """Collect all completed queued concentrate batches exactly once."""
        now = time.time()
        collected: dict[str, int] = {}

        async with self.bot.db.lock:
            user = self.bot.db.get_user(ctx.author.id)
            queue = user.setdefault("processing_queue", [])
            remaining = []
            for item in queue:
                if float(item.get("finish_time", now + 1)) > now:
                    remaining.append(item)
                    continue

                c_type = str(item.get("type", "")).strip().lower()
                try:
                    qty = require_positive_amount(item.get("amount", 0))
                except ValueError:
                    # Preserve malformed records for manual recovery instead of deleting them.
                    remaining.append(item)
                    continue
                if c_type not in CONCENTRATE_TYPES:
                    remaining.append(item)
                    continue
                collected[c_type] = collected.get(c_type, 0) + qty

            if not collected:
                return await ctx.send("⏳ No completed lab batches are ready to collect.")

            user["processing_queue"] = remaining
            concentrates = user.setdefault("concentrates", {})
            for c_type, qty in collected.items():
                concentrates[c_type] = int(concentrates.get(c_type, 0)) + qty
            stats = user.setdefault("stats", {})
            stats["concentrate_made"] = int(stats.get("concentrate_made", 0)) + sum(
                collected.values()
            )
            await self.bot.db.save()

        summary = "\n".join(f"• **{qty}g {name.title()}**" for name, qty in collected.items())
        await ctx.send(f"📦 **Lab collection complete:**\n{summary}")

    @commands.command(name="conc")
    async def conc(self, ctx, user_target: discord.Member = None):
        target = user_target or ctx.author
        player = self.bot.db.get_user(target.id)
        concentrates = player.get("concentrates", {})
        queue = player.get("processing_queue", [])

        if not concentrates and not queue:
            if target == ctx.author:
                return await ctx.send("🧪 **No concentrates yet!** Use `!process` to make some.")
            return await ctx.send(f"🧪 **{target.display_name}** has no concentrates.")

        embed = discord.Embed(title=f"🧪 {target.display_name}'s Concentrates", color=0x9B59B6)
        conc_lines = []
        total_value = 0
        for conc_type, raw_amount in concentrates.items():
            amount = int(raw_amount)
            if amount <= 0:
                continue
            conc_data = CONCENTRATE_TYPES.get(conc_type, {"value_mult": 3.0})
            base_total = 500 * float(conc_data.get("value_mult", 3.0)) * amount
            final_value = _lab_market_value(player, base_total)
            total_value += final_value
            conc_lines.append(f"**{conc_type.title()}:** {amount}g (≈${final_value:,})")
        if conc_lines:
            embed.add_field(name="📦 **In Stock**", value="\n".join(conc_lines), inline=False)
            embed.add_field(name="💰 **Total Value**", value=f"≈${total_value:,}", inline=True)

        queue_lines = []
        for item in queue[:5]:
            time_left = float(item.get("finish_time", time.time())) - time.time()
            if time_left > 0:
                queue_lines.append(
                    f"**{str(item.get('type', 'unknown')).title()}:** "
                    f"{item.get('amount', 0)}g - {_lab_format_time(time_left)} left"
                )
            else:
                queue_lines.append(
                    f"**{str(item.get('type', 'unknown')).title()}:** "
                    f"{item.get('amount', 0)}g - ✅ ready to collect"
                )
        if queue_lines:
            embed.add_field(name="⚗️ **Processing**", value="\n".join(queue_lines), inline=False)
        if len(queue) > 5:
            embed.set_footer(text=f"+{len(queue) - 5} more in queue")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="lab")
    async def lab(self, ctx, conc_type: str = "shatter", amount: int = 10):
        """Play the manual extraction minigame with flower reserved up front."""
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "lab"):
            return

        c_type = conc_type.lower().strip()
        if c_type not in CONCENTRATE_TYPES:
            return await ctx.send(f"❌ Unknown type. Options: {', '.join(CONCENTRATE_TYPES.keys())}")

        info = CONCENTRATE_TYPES[c_type]
        try:
            qty = require_positive_amount(amount)
            manual_ratio = float(info.get("yield_ratio", 0.1)) * 1.1
            needed_flower = flower_required_for_output(qty, manual_ratio)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}.")

        required_tool = info.get("req_item")
        required_level = int(info.get("level_req", 1))
        async with self.bot.db.lock:
            user = self.bot.db.get_user(ctx.author.id)
            if required_tool and not has_item(user, required_tool):
                return await ctx.send(f"❌ You need a **{required_tool.title()}**.")
            if int(user.get("level", 1)) < required_level:
                return await ctx.send(f"🔒 Level {required_level} required.")
            stash = user.setdefault("flower_stash", {})
            try:
                reservation = reserve_flower(stash, needed_flower)
            except ValueError:
                return await ctx.send(f"🌿 **Not enough flower.** Need {needed_flower}g.")
            await self.bot.db.save()

        target = random.randint(40, 75)
        view = LabMinigameView(ctx.author.id, c_type, qty, target)
        msg = await ctx.send(
            f"⚗️ **Extraction Started: {c_type.title()}**\n"
            f"Reserved: **{needed_flower}g flower**\n"
            f"Target: **{target}% - {target + 15}%**",
            view=view,
        )

        for progress in range(0, 105, 5):
            if view.pressed:
                break
            view.progress = progress
            slots = 20
            position = int((progress / 100) * slots)
            chars = []
            for index in range(slots):
                zone_value = index * 5
                if index == position:
                    chars.append("🔘")
                elif target <= zone_value <= target + 15:
                    chars.append("🟩")
                else:
                    chars.append("➖")
            try:
                await msg.edit(content=f"⚗️ Pressure: **{progress}%**\n`[{''.join(chars)}]`")
            except discord.HTTPException:
                break
            await asyncio.sleep(0.5 if progress < 50 else 0.3)

        level_up = None
        if not view.pressed:
            async with self.bot.db.lock:
                user = self.bot.db.get_user(ctx.author.id)
                restore_flower(user.setdefault("flower_stash", {}), reservation)
                await self.bot.db.save()
            await msg.edit(content="💥 **Timeout!** Reserved flower was returned.", view=None)
            return

        if view.success:
            async with self.bot.db.lock:
                user = self.bot.db.get_user(ctx.author.id)
                concentrates = user.setdefault("concentrates", {})
                concentrates[c_type] = int(concentrates.get(c_type, 0)) + qty
                level_up = _credit_xp(user, qty * 5)
                add__progress(user, "process_dabs", qty)
                stats = user.setdefault("stats", {})
                stats["concentrate_made"] = int(stats.get("concentrate_made", 0)) + qty
                await self.bot.db.save()
            await ctx.send(f"💎 **Success!** Created **{qty}g {c_type.title()}**.")
            if level_up:
                await ctx.send(f"🎉 **Level Up!** You are now level {level_up}!")
            return

        penalty = min(needed_flower, max(1, ceil(needed_flower * 0.2)))
        _, refundable = split_reservation_penalty(reservation, penalty)
        async with self.bot.db.lock:
            user = self.bot.db.get_user(ctx.author.id)
            restore_flower(user.setdefault("flower_stash", {}), refundable)
            await self.bot.db.save()
        await ctx.send(f"💥 **Failed!** Lost {penalty}g flower; the rest was returned.")


async def setup(bot):
    await bot.add_cog(Lab(bot))
