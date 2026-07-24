import asyncio
import math
import random
import time

import discord
from discord.ext import commands

from crime_integrity import (
    calculate_capped_loss,
    calculate_crew_payout,
    calculate_launder_outcome,
    calculate_raid_outcome,
    calculate_robbery_transfer,
)
from economy_integrity import require_positive_amount
from persistence_context import require_guild_id
from utils import add_heat, has_item, jail_guard


HEIST_SOLO_COOLDOWN = 30 * 60
HEIST_CREW_COOLDOWN = 60 * 60
HEIST_RAID_COOLDOWN = 2 * 60 * 60
HEIST_JOIN_WINDOW = 45
HEIST_JAIL_MIN = 3
HEIST_JAIL_MAX = 12
HEAT_MAX = 100
HEAT_GAIN_WIN = 6
HEAT_GAIN_FAIL = 12
HEAT_DECAY_PER_HOUR = 6
RAID_MAX_STEAL_PCT = 0.18
RAID_MAX_STEAL_FLAT = 25_000
RAID_MIN_TARGET_BANK = 5_000

# Ephemeral coordination only. Persisted player and crew value stays in scoped storage.
_ACTIVE_HEISTS: dict[str, dict] = {}


class Crime(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _now(self) -> float:
        return time.time()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def _in_jail(self, user: dict) -> int:
        return max(0, int(user.get("jail_until", 0) or 0) - int(self._now()))

    @staticmethod
    def _get_user_cooldown(user: dict, key: str) -> float:
        return float(user.setdefault("cooldowns", {}).get(key, 0) or 0)

    @staticmethod
    def _set_user_cooldown(user: dict, key: str, timestamp: float) -> None:
        user.setdefault("cooldowns", {})[key] = float(timestamp)

    def _crew_cooldown_left(self, crew: dict, key: str) -> int:
        duration = {
            "heist": HEIST_CREW_COOLDOWN,
            "raid": HEIST_RAID_COOLDOWN,
        }.get(key, 0)
        last = float(crew.setdefault("cooldowns", {}).get(key, 0) or 0)
        return max(0, int(last + duration - self._now()))

    def _set_crew_cooldown(self, crew: dict, key: str) -> None:
        crew.setdefault("cooldowns", {})[key] = self._now()

    @staticmethod
    def _calc_power(levels: list[int]) -> float:
        if not levels:
            return 0.0
        return math.sqrt(sum(max(1, int(level)) ** 2 for level in levels)) / 10.0

    @staticmethod
    def _tier(level: int) -> str:
        if level <= 5:
            return "street"
        if level <= 12:
            return "crew"
        if level <= 25:
            return "pro"
        return "legend"

    @staticmethod
    def _roll(chance: float) -> bool:
        return random.random() < max(0.02, min(0.98, chance))

    @staticmethod
    def _get_crews(world: dict) -> dict:
        crews = world.get("crews")
        if not isinstance(crews, dict):
            crews = {}
            world["crews"] = crews
        return crews

    @staticmethod
    def _session_key(guild_id: int, kind: str, identifier: object) -> str:
        return f"guild:{guild_id}:{kind}:{identifier}"

    def _apply_heat_decay(self, user: dict) -> int:
        heat = max(0, int(user.get("heat", 0) or 0))
        last = float(user.get("heat_ts", 0) or 0)
        now = self._now()
        if last > 0:
            elapsed_hours = max(0.0, (now - last) / 3600.0)
            heat = max(0, heat - int(elapsed_hours * HEAT_DECAY_PER_HOUR))
        user["heat_ts"] = now
        user["heat"] = min(HEAT_MAX, heat)
        return user["heat"]

    @staticmethod
    def _plan_mod(plan: str) -> tuple[str, float, float, int]:
        clean = (plan or "stealth").lower().strip()
        if clean in ("stealth", "silent"):
            return "STEALTH", 0.06, -0.10, -3
        if clean in ("loud", "guns", "brute"):
            return "LOUD", -0.08, 0.22, 10
        if clean in ("con", "social", "scam"):
            return "CON", 0.02, 0.08, 3
        return "STEALTH", 0.06, -0.10, -3

    def _solo_profile(self, level: int, prestige: int, heat: int, plan: str) -> dict:
        base = {
            "street": {"buyin": 250, "reward": (600, 1_400), "xp": (40, 90), "chance": 0.72},
            "crew": {"buyin": 900, "reward": (1_800, 4_800), "xp": (90, 170), "chance": 0.64},
            "pro": {"buyin": 2_600, "reward": (4_800, 11_800), "xp": (170, 320), "chance": 0.58},
            "legend": {"buyin": 7_000, "reward": (12_000, 28_000), "xp": (320, 600), "chance": 0.52},
        }[self._tier(level)]
        plan_name, chance_mod, payout_mod, heat_mod = self._plan_mod(plan)
        level_mult = 1.0 + min(level, 60) * 0.012
        prestige_mult = 1.0 + prestige * 0.04
        return {
            "plan": plan_name,
            "heat_mod": heat_mod,
            "buyin": max(1, int(base["buyin"] * (0.92 + level_mult * 0.10))),
            "reward": (
                max(1, int(base["reward"][0] * level_mult * prestige_mult * (1.0 + payout_mod))),
                max(2, int(base["reward"][1] * level_mult * prestige_mult * (1.0 + payout_mod))),
            ),
            "xp": (
                max(1, int(base["xp"][0] * (1.0 + prestige * 0.05))),
                max(2, int(base["xp"][1] * (1.0 + prestige * 0.05))),
            ),
            "chance": max(
                0.02,
                min(
                    0.98,
                    base["chance"] + min(level, 60) * 0.0025 + chance_mod - min(0.25, heat / 100.0 * 0.25),
                ),
            ),
        }

    @commands.command(name="heist", aliases=["heists"])
    async def heist(self, ctx, mode: str = "solo", arg: str = None):
        guild_id = require_guild_id(ctx)
        user = await self.bot.db.get_profile(guild_id, ctx.author.id)
        if await jail_guard(ctx, user, "heist"):
            return

        mode = (mode or "solo").lower().strip()
        if mode in ("solo", ""):
            await self._solo_heist(ctx, guild_id, user, arg or "stealth")
        elif mode in ("crew", "coop"):
            await self._start_crew_heist(ctx, guild_id, user)
        elif mode == "join":
            await self._join_crew_heist(ctx, guild_id, user)
        elif mode in ("raid", "pvp"):
            await self._raid(ctx, guild_id, user, arg)
        else:
            await ctx.send("Usage: `!heist solo [plan]`, `!heist crew`, `!heist join`, or `!heist raid <crew_id>`")

    async def _solo_heist(self, ctx, guild_id: int, user: dict, plan: str) -> None:
        key = self._session_key(guild_id, "user", ctx.author.id)
        if _ACTIVE_HEISTS.get(key, {}).get("ends", 0) > self._now():
            await ctx.send("⏳ You’re already mid-heist.")
            return

        _ACTIVE_HEISTS[key] = {"ends": self._now() + 8}
        try:
            async with self.bot.db.lock:
                last = self._get_user_cooldown(user, "heist_solo")
                remaining = int(last + HEIST_SOLO_COOLDOWN - self._now())
                if remaining > 0:
                    await ctx.send(f"⏳ Solo heist cooldown: **{self._fmt_time(remaining)}**")
                    return

                heat = self._apply_heat_decay(user)
                level = max(1, int(user.get("level", 1) or 1))
                prestige = max(0, int(user.get("prestige", 0) or 0))
                config = self._solo_profile(level, prestige, heat, plan)
                balance = max(0, int(user.get("grams", 0) or 0))
                if balance < config["buyin"]:
                    await ctx.send(f"💸 You need **${config['buyin']:,}** for this job.")
                    return

                user["grams"] = balance - config["buyin"]
                stats = user.setdefault("stats", {})
                stats["heists_run"] = max(0, int(stats.get("heists_run", 0))) + 1
                success = self._roll(config["chance"])

                if success:
                    payout = random.randint(*config["reward"])
                    xp = random.randint(*config["xp"])
                    user["grams"] += payout
                    user["xp"] = max(0, int(user.get("xp", 0))) + xp
                    add_heat(user, HEAT_GAIN_WIN + config["heat_mod"])
                    stats["heists_won"] = max(0, int(stats.get("heists_won", 0))) + 1
                    stats["heist_profit"] = max(0, int(stats.get("heist_profit", 0))) + payout
                    jail_minutes = 0
                    loss = 0
                else:
                    requested_loss = max(150, int(config["buyin"] * random.uniform(0.30, 0.70)))
                    loss = calculate_capped_loss(user["grams"], requested_loss)
                    user["grams"] -= loss
                    jail_minutes = random.randint(HEIST_JAIL_MIN, HEIST_JAIL_MAX)
                    user["jail_until"] = int(self._now() + jail_minutes * 60)
                    add_heat(user, HEAT_GAIN_FAIL + config["heat_mod"])
                    stats["heists_lost"] = max(0, int(stats.get("heists_lost", 0))) + 1
                    payout = 0
                    xp = 0

                self._set_user_cooldown(user, "heist_solo", self._now())
                self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)
        finally:
            _ACTIVE_HEISTS.pop(key, None)

        if success:
            embed = discord.Embed(
                title="🏦 Heist Success",
                description=(
                    f"**Plan:** {config['plan']}\n"
                    f"🎯 Odds: **{int(config['chance'] * 100)}%**\n"
                    f"💰 Payout: **+${payout:,}**\n"
                    f"⭐ XP: **+{xp:,}**\n"
                    f"🚓 Heat: **{int(user.get('heat', 0))}%**"
                ),
                color=0x2ECC71,
            )
        else:
            embed = discord.Embed(
                title="🚨 Heist Failed",
                description=(
                    f"**Plan:** {config['plan']}\n"
                    f"🎯 Odds: **{int(config['chance'] * 100)}%**\n"
                    f"💸 Additional loss: **${loss:,}**\n"
                    f"🚔 Jail: **{jail_minutes}m**\n"
                    f"🚓 Heat: **{int(user.get('heat', 0))}%**"
                ),
                color=0xE74C3C,
            )
        await ctx.send(embed=embed)

    async def _start_crew_heist(self, ctx, guild_id: int, user: dict) -> None:
        crew_id = user.get("crew_id")
        if not crew_id:
            return await ctx.send("❌ You need a crew.")

        world = await self.bot.db.get_world(guild_id)
        crew = self._get_crews(world).get(str(crew_id))
        if not crew:
            return await ctx.send("❌ Crew data missing.")

        key = self._session_key(guild_id, "crew", crew_id)
        async with self.bot.db.lock:
            remaining = self._crew_cooldown_left(crew, "heist")
            if remaining > 0:
                return await ctx.send(f"⏳ Crew cooldown: **{self._fmt_time(remaining)}**")
            if _ACTIVE_HEISTS.get(key, {}).get("join_until", 0) > self._now():
                return await ctx.send("⏳ Crew heist already forming. Use `!heist join`.")
            _ACTIVE_HEISTS[key] = {
                "join_until": self._now() + HEIST_JOIN_WINDOW,
                "members": {int(ctx.author.id)},
                "host_id": int(ctx.author.id),
            }

        await ctx.send(embed=discord.Embed(
            title="🧪 Crew Heist Forming",
            description=(
                f"**{crew.get('name', 'Crew')}** is starting a job!\n"
                f"Type `!heist join` within **{HEIST_JOIN_WINDOW}s**.\nNeed 2+ members."
            ),
            color=0x9B59B6,
        ))
        await asyncio.sleep(HEIST_JOIN_WINDOW + 1)

        async with self.bot.db.lock:
            session = _ACTIVE_HEISTS.pop(key, None)
            if not session:
                return
            world = await self.bot.db.get_world(guild_id)
            crew = self._get_crews(world).get(str(crew_id))
            if not crew:
                return await ctx.send("❌ Crew data missing.")

            valid_members: list[tuple[int, dict]] = []
            for member_id in session.get("members", set()):
                member = await self.bot.db.get_profile(guild_id, member_id)
                if self._in_jail(member) <= 0 and str(member.get("crew_id")) == str(crew_id):
                    valid_members.append((int(member_id), member))
            if len(valid_members) < 2:
                return await ctx.send("❌ Heist cancelled: not enough eligible crew members joined.")

            levels = [max(1, int(member.get("level", 1))) for _, member in valid_members]
            power = self._calc_power(levels)
            chance = max(0.18, min(0.88, 0.46 + power * 0.06 + len(valid_members) * 0.03))
            success = self._roll(chance)
            base = int(2_600 + power * 1_200)
            total = random.randint(int(base * 0.7), int(base * 1.3))

            if success:
                split = calculate_crew_payout(total, len(valid_members), bank_rate=0.30)
                crew["bank"] = max(0, int(crew.get("bank", 0))) + split.crew_bank_gain + split.remainder
                for member_id, member in valid_members:
                    member["grams"] = max(0, int(member.get("grams", 0))) + split.member_gain
                    add_heat(member, 2)
                    self.bot.db.mark_profile_dirty(guild_id, member_id)
                bank_gain = split.crew_bank_gain + split.remainder
                member_gain = split.member_gain
                jail_minutes = 0
            else:
                jail_minutes = random.randint(2, 7)
                for member_id, member in valid_members:
                    balance = max(0, int(member.get("grams", 0)))
                    loss = calculate_capped_loss(balance, int(balance * 0.04))
                    member["grams"] = balance - loss
                    member["jail_until"] = int(self._now() + jail_minutes * 60)
                    add_heat(member, 6)
                    self.bot.db.mark_profile_dirty(guild_id, member_id)
                bank_gain = 0
                member_gain = 0

            self._set_crew_cooldown(crew, "heist")
            self.bot.db.mark_world_dirty(guild_id)

        if success:
            await ctx.send(embed=discord.Embed(
                title="🏦 Crew Heist Success",
                description=(
                    f"💰 Total: **${total:,}**\n"
                    f"🏦 Crew bank: **+${bank_gain:,}**\n"
                    f"👤 Each member: **+${member_gain:,}**"
                ),
                color=0x2ECC71,
            ))
        else:
            await ctx.send(f"🚨 **Crew heist failed.** Eligible members were jailed for {jail_minutes}m.")

    async def _join_crew_heist(self, ctx, guild_id: int, user: dict) -> None:
        if self._in_jail(user) > 0:
            return await ctx.send("🚔 You are jailed.")
        crew_id = user.get("crew_id")
        if not crew_id:
            return await ctx.send("❌ You need a crew.")
        key = self._session_key(guild_id, "crew", crew_id)
        async with self.bot.db.lock:
            session = _ACTIVE_HEISTS.get(key)
            if not session or session.get("join_until", 0) <= self._now():
                return await ctx.send("❌ No heist is forming.")
            session.setdefault("members", set()).add(int(ctx.author.id))
        await ctx.send(f"✅ {ctx.author.mention} joined!")

    async def _raid(self, ctx, guild_id: int, user: dict, target_id: str | None) -> None:
        crew_id = user.get("crew_id")
        if not crew_id:
            return await ctx.send("❌ You need a crew.")
        if not target_id:
            return await ctx.send("Usage: `!heist raid <target_crew_id>`")

        async with self.bot.db.lock:
            world = await self.bot.db.get_world(guild_id)
            crews = self._get_crews(world)
            attacker = crews.get(str(crew_id))
            defender = crews.get(str(target_id).strip())
            if not attacker or not defender:
                return await ctx.send("❌ Invalid crew IDs.")
            if str(crew_id) == str(target_id).strip():
                return await ctx.send("❌ Cannot raid your own crew.")
            remaining = self._crew_cooldown_left(attacker, "raid")
            if remaining > 0:
                return await ctx.send(f"⏳ Raid cooldown: **{self._fmt_time(remaining)}**")
            defender_bank = max(0, int(defender.get("bank", 0)))
            if defender_bank < RAID_MIN_TARGET_BANK:
                return await ctx.send("❌ Target is too poor to raid.")

            async def levels(crew: dict) -> list[int]:
                result = []
                for member_id in crew.get("members", []):
                    try:
                        profile = await self.bot.db.get_profile(guild_id, int(member_id))
                    except (TypeError, ValueError):
                        continue
                    result.append(max(1, int(profile.get("level", 1))))
                return result

            attacker_power = self._calc_power(await levels(attacker))
            defender_power = self._calc_power(await levels(defender))
            chance = max(0.12, min(0.85, 0.50 + (attacker_power - defender_power) * 0.06))
            success = self._roll(chance)
            attacker_bank = max(0, int(attacker.get("bank", 0)))
            if success:
                outcome = calculate_raid_outcome(
                    defender_bank,
                    attacker_bank,
                    steal_rate=RAID_MAX_STEAL_PCT,
                    steal_cap=RAID_MAX_STEAL_FLAT,
                    attacker_keep_rate=0.85,
                )
                defender["bank"] = outcome.defender_balance
                attacker["bank"] = outcome.attacker_balance
                stolen = outcome.stolen
                attacker_gain = outcome.attacker_gain
                penalty = 0
            else:
                penalty = calculate_capped_loss(attacker_bank, min(12_000, int(attacker_bank * 0.06)))
                attacker["bank"] = attacker_bank - penalty
                stolen = 0
                attacker_gain = 0

            self._set_crew_cooldown(attacker, "raid")
            stats = user.setdefault("stats", {})
            stats["raids_run"] = max(0, int(stats.get("raids_run", 0))) + 1
            if success:
                stats["raids_won"] = max(0, int(stats.get("raids_won", 0))) + 1
            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)
            self.bot.db.mark_world_dirty(guild_id)

        if success:
            await ctx.send(embed=discord.Embed(
                title="⚔️ Raid Success",
                description=(
                    f"Stole **${stolen:,}** from **{defender.get('name', 'crew')}**!\n"
                    f"Net crew-bank gain: **${attacker_gain:,}**"
                ),
                color=0xF1C40F,
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="🚫 Raid Failed",
                description=f"Attack failed. Lost **${penalty:,}** in crew resources.",
                color=0xE74C3C,
            ))

    @commands.hybrid_command(name="steal", aliases=["rob"])
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def steal(self, ctx, target: discord.Member):
        if target.id == ctx.author.id:
            return await ctx.send("❌ Robbing yourself?")
        guild_id = require_guild_id(ctx)
        robber = await self.bot.db.get_profile(guild_id, ctx.author.id)
        if await jail_guard(ctx, robber, "steal"):
            return

        async with self.bot.db.lock:
            victim = await self.bot.db.get_profile(guild_id, target.id)
            chance = 0.50
            if has_item(victim, "dog") or has_item(victim, "guard dog"):
                chance -= 0.25
            if has_item(victim, "cam") or has_item(victim, "security camera"):
                chance -= 0.15
            if has_item(robber, "lockpick"):
                chance += 0.10
            if has_item(robber, "ski mask"):
                chance += 0.10
            chance = max(0.05, min(0.90, chance))

            if random.random() < chance:
                wallet = max(0, int(victim.get("grams", 0)))
                try:
                    amount = calculate_robbery_transfer(wallet, random.uniform(0.05, 0.20))
                except ValueError:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send("That player is too poor to rob.")
                victim["grams"] = wallet - amount
                robber["dirty_cash"] = max(0, int(robber.get("dirty_cash", 0))) + amount
                add_heat(robber, 15)
                stats = robber.setdefault("stats", {})
                stats["steals"] = max(0, int(stats.get("steals", 0))) + 1
                success = True
                fine = 0
                self.bot.db.mark_profile_dirty(guild_id, target.id)
            else:
                balance = max(0, int(robber.get("grams", 0)))
                fine = calculate_capped_loss(balance, 1_000)
                robber["grams"] = balance - fine
                robber["jail_until"] = int(self._now() + 300)
                add_heat(robber, 25)
                amount = 0
                success = False
            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)

        if success:
            await ctx.send(f"🔫 **SUCCESS!** Stole **${amount:,}** in dirty cash.")
        else:
            await ctx.send(f"🚓 **BUSTED!** Fined ${fine:,} and jailed for 5m.")

    @commands.command(name="launder")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def launder(self, ctx, amount: str = "all"):
        guild_id = require_guild_id(ctx)
        user = await self.bot.db.get_profile(guild_id, ctx.author.id)
        async with self.bot.db.lock:
            dirty = max(0, int(user.get("dirty_cash", 0) or 0))
            heat = max(0, int(user.get("heat", 0) or 0))
            if dirty <= 0:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("❌ You have no **Dirty Cash** to launder.")
            if heat >= 90:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(f"🚓 **Too Hot!** Heat is **{heat}%**. Let it cool down first.")

            raw = (amount or "all").strip().lower()
            try:
                requested = dirty if raw in ("all", "max", "*") else require_positive_amount(raw.replace(",", ""))
                outcome = calculate_launder_outcome(requested, dirty_balance=dirty, fee_rate=0.20)
            except ValueError as error:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(f"❌ {error}.")

            user["dirty_cash"] = dirty - outcome.dirty_spent
            user["grams"] = max(0, int(user.get("grams", 0))) + outcome.clean_received
            add_heat(user, 5)
            self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)

        embed = discord.Embed(
            title="🧼 Money Laundered",
            description=f"You cleaned **${outcome.dirty_spent:,}** dirty cash.",
            color=0x95A5A6,
        )
        embed.add_field(name="💸 Fee (20%)", value=f"-${outcome.fee:,}", inline=True)
        embed.add_field(name="💰 Received", value=f"+${outcome.clean_received:,} clean", inline=True)
        embed.add_field(name="🔥 Heat", value=f"+5 (Total: {int(user.get('heat', 0))}%)", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="heat")
    async def heat(self, ctx):
        guild_id = require_guild_id(ctx)
        user = await self.bot.db.get_profile(guild_id, ctx.author.id)
        heat_level = max(0, min(100, int(user.get("heat", 0) or 0)))
        dirty_cash = max(0, int(user.get("dirty_cash", 0) or 0))
        filled = heat_level // 10
        bar = "🟥" * filled + "⬜" * (10 - filled)
        status = "WANTED 🚓" if heat_level > 80 else "Hot 🔥" if heat_level > 50 else "Suspicious" if heat_level > 20 else "Chill"
        embed = discord.Embed(title="🚓 Police Heat Level", color=0xE74C3C)
        embed.add_field(name="Heat", value=f"{bar} ({heat_level}%)", inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="💼 Dirty Cash", value=f"${dirty_cash:,}", inline=True)
        embed.set_footer(text="Use !launder to clean dirty cash. High heat increases crime risk.")
        await ctx.send(embed=embed)

    @commands.command(name="heiststats", aliases=["hst"])
    async def heiststats(self, ctx, member: discord.Member = None):
        guild_id = require_guild_id(ctx)
        target = member or ctx.author
        profile = await self.bot.db.get_profile(guild_id, target.id)
        stats = profile.get("stats", {})
        embed = discord.Embed(title=f"🏆 Heist Stats: {target.display_name}", color=0x3498DB)
        embed.add_field(name="Solo", value=f"Won: {stats.get('heists_won', 0)}\nRun: {stats.get('heists_run', 0)}", inline=True)
        embed.add_field(name="Raids", value=f"Won: {stats.get('raids_won', 0)}\nRun: {stats.get('raids_run', 0)}", inline=True)
        embed.add_field(name="Payouts", value=f"${stats.get('heist_profit', 0):,}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="topheists", aliases=["lbheists"])
    async def topheists(self, ctx):
        guild_id = require_guild_id(ctx)
        rows = await self.bot.db.list_guild_heist_leaderboard(guild_id, limit=10)
        lines = []
        for index, (user_id, score) in enumerate(rows, 1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            lines.append(f"**{index}.** {name} — {score} wins")
        await ctx.send(embed=discord.Embed(
            title="🏆 Top Heisters",
            description="\n".join(lines) or "None",
            color=0xF1C40F,
        ))

    @commands.command(name="heistset", aliases=["heistsetchannel"])
    @commands.has_permissions(manage_guild=True)
    async def heistset(self, ctx, mode: str = "add"):
        guild_id = require_guild_id(ctx)
        clean_mode = (mode or "list").lower().strip()
        async with self.bot.db.lock:
            world = await self.bot.db.get_world(guild_id)
            channels = set(world.get("heist_channels", []))
            channel_id = int(ctx.channel.id)
            changed = False
            if clean_mode in ("add", "allow", "+"):
                channels.add(channel_id)
                changed = True
            elif clean_mode in ("remove", "deny", "-", "del"):
                channels.discard(channel_id)
                changed = True
            if changed:
                world["heist_channels"] = sorted(channels)
                self.bot.db.mark_world_dirty(guild_id)

        if clean_mode in ("add", "allow", "+"):
            await ctx.send(f"✅ Heists allowed in {ctx.channel.mention}")
        elif clean_mode in ("remove", "deny", "-", "del"):
            await ctx.send(f"✅ Heists blocked in {ctx.channel.mention}")
        else:
            names = []
            for channel_id in sorted(channels):
                channel = ctx.guild.get_channel(channel_id)
                names.append(channel.mention if channel else str(channel_id))
            message = "🏦 **Heist Channels:** " + ", ".join(names) if names else "✅ Heists allowed everywhere (default)."
            await ctx.send(message)


async def setup(bot):
    await bot.add_cog(Crime(bot))
