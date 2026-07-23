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

# Temporary coordination state only. Player value remains in the database cache.
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

    def _get_crews(self) -> dict:
        world = self.bot.db.world_state
        crews = world.get("crews")
        if not isinstance(crews, dict):
            crews = {}
            world["crews"] = crews
        return crews

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
        buyin = int(base["buyin"] * (0.92 + level_mult * 0.10))
        reward_min = int(base["reward"][0] * level_mult * prestige_mult * (1.0 + payout_mod))
        reward_max = int(base["reward"][1] * level_mult * prestige_mult * (1.0 + payout_mod))
        xp_min = int(base["xp"][0] * (1.0 + prestige * 0.05))
        xp_max = int(base["xp"][1] * (1.0 + prestige * 0.05))
        chance = base["chance"] + min(level, 60) * 0.0025 + chance_mod
        chance -= min(0.25, heat / 100.0 * 0.25)
        return {
            "plan": plan_name,
            "heat_mod": heat_mod,
            "buyin": max(1, buyin),
            "reward": (max(1, reward_min), max(2, reward_max)),
            "xp": (max(1, xp_min), max(2, xp_max)),
            "chance": max(0.02, min(0.98, chance)),
        }

    @commands.command(name="heist", aliases=["heists"])
    async def heist(self, ctx, mode: str = "solo", arg: str = None):
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "heist"):
            return

        mode = (mode or "solo").lower().strip()
        if mode in ("solo", ""):
            await self._solo_heist(ctx, user, arg or "stealth")
            return
        if mode in ("crew", "coop"):
            await self._start_crew_heist(ctx, user)
            return
        if mode == "join":
            await self._join_crew_heist(ctx, user)
            return
        if mode in ("raid", "pvp"):
            await self._raid(ctx, user, arg)
            return
        await ctx.send("Usage: `!heist solo [plan]`, `!heist crew`, `!heist join`, or `!heist raid <crew_id>`")

    async def _solo_heist(self, ctx, user: dict, plan: str) -> None:
        key = f"user:{ctx.author.id}"
        if _ACTIVE_HEISTS.get(key, {}).get("ends", 0) > self._now():
            await ctx.send("⏳ You’re already mid-heist.")
            return

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

            _ACTIVE_HEISTS[key] = {"ends": self._now() + 8}
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
            await self.bot.db.save()

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

    async def _start_crew_heist(self, ctx, user: dict) -> None:
        crew_id = user.get("crew_id")
        if not crew_id:
            await ctx.send("❌ You need a crew.")
            return
        crews = self._get_crews()
        crew = crews.get(str(crew_id))
        if not crew:
            await ctx.send("❌ Crew data missing.")
            return

        key = f"crew:{crew_id}"
        async with self.bot.db.lock:
            remaining = self._crew_cooldown_left(crew, "heist")
            if remaining > 0:
                await ctx.send(f"⏳ Crew cooldown: **{self._fmt_time(remaining)}**")
                return
            if _ACTIVE_HEISTS.get(key, {}).get("join_until", 0) > self._now():
                await ctx.send("⏳ Crew heist already forming. Use `!heist join`.")
                return
            _ACTIVE_HEISTS[key] = {
                "join_until": self._now() + HEIST_JOIN_WINDOW,
                "members": {int(ctx.author.id)},
                "host_id": int(ctx.author.id),
            }

        await ctx.send(embed=discord.Embed(
            title="🧪 Crew Heist Forming",
            description=f"**{crew.get('name', 'Crew')}** is starting a job!\nType `!heist join` within **{HEIST_JOIN_WINDOW}s**.\nNeed 2+ members.",
            color=0x9B59B6,
        ))
        await asyncio.sleep(HEIST_JOIN_WINDOW + 1)

        async with self.bot.db.lock:
            session = _ACTIVE_HEISTS.pop(key, None)
            if not session:
                return
            valid_members = []
            for member_id in session.get("members", set()):
                member = self.bot.db.get_user(member_id)
                if self._in_jail(member) <= 0 and str(member.get("crew_id")) == str(crew_id):
                    valid_members.append(member)
            if len(valid_members) < 2:
                await ctx.send("❌ Heist cancelled: not enough eligible crew members joined.")
                return

            levels = [max(1, int(member.get("level", 1))) for member in valid_members]
            power = self._calc_power(levels)
            chance = max(0.18, min(0.88, 0.46 + power * 0.06 + len(valid_members) * 0.03))
            success = self._roll(chance)
            base = int(2_600 + power * 1_200)
            total = random.randint(int(base * 0.7), int(base * 1.3))

            if success:
                split = calculate_crew_payout(total, len(valid_members), bank_rate=0.30)
                crew["bank"] = max(0, int(crew.get("bank", 0))) + split.crew_bank_gain + split.remainder
                for member in valid_members:
                    member["grams"] = max(0, int(member.get("grams", 0))) + split.member_gain
                    add_heat(member, 2)
                bank_gain = split.crew_bank_gain + split.remainder
                member_gain = split.member_gain
                jail_minutes = 0
            else:
                jail_minutes = random.randint(2, 7)
                for member in valid_members:
                    balance = max(0, int(member.get("grams", 0)))
                    loss = calculate_capped_loss(balance, int(balance * 0.04))
                    member["grams"] = balance - loss
                    member["jail_until"] = int(self._now() + jail_minutes * 60)
                    add_heat(member, 6)
                bank_gain = 0
                member_gain = 0

            self._set_crew_cooldown(crew, "heist")
            await self.bot.db.save()

        if success:
            await ctx.send(embed=discord.Embed(
                title="🏦 Crew Heist Success",
                description=f"💰 Total: **${total:,}**\n🏦 Crew bank: **+${bank_gain:,}**\n👤 Each member: **+${member_gain:,}**",
                color=0x2ECC71,
            ))
        else:
            await ctx.send(f"🚨 **Crew heist failed.** Eligible members were jailed for {jail_minutes}m.")

    async def _join_crew_heist(self, ctx, user: dict) -> None:
        if self._in_jail(user) > 0:
            await ctx.send("🚔 You are jailed.")
            return
        crew_id = user.get("crew_id")
        if not crew_id:
            await ctx.send("❌ You need a crew.")
            return
        key = f"crew:{crew_id}"
        async with self.bot.db.lock:
            session = _ACTIVE_HEISTS.get(key)
            if not session or session.get("join_until", 0) <= self._now():
                await ctx.send("❌ No heist is forming.")
                return
            session.setdefault("members", set()).add(int(ctx.author.id))
        await ctx.send(f"✅ {ctx.author.mention} joined!")

    async def _raid(self, ctx, user: dict, target_id: str | None) -> None:
        crew_id = user.get("crew_id")
        if not crew_id:
            await ctx.send("❌ You need a crew.")
            return
        if not target_id:
            await ctx.send("Usage: `!heist raid <target_crew_id>`")
            return

        async with self.bot.db.lock:
            crews = self._get_crews()
            attacker = crews.get(str(crew_id))
            defender = crews.get(str(target_id).strip())
            if not attacker or not defender:
                await ctx.send("❌ Invalid crew IDs.")
                return
            if str(crew_id) == str(target_id).strip():
                await ctx.send("❌ Cannot raid your own crew.")
                return
            remaining = self._crew_cooldown_left(attacker, "raid")
            if remaining > 0:
                await ctx.send(f"⏳ Raid cooldown: **{self._fmt_time(remaining)}**")
                return
            defender_bank = max(0, int(defender.get("bank", 0)))
            if defender_bank < RAID_MIN_TARGET_BANK:
                await ctx.send("❌ Target is too poor to raid.")
                return

            def levels(crew: dict) -> list[int]:
                result = []
                for member_id in crew.get("members", []):
                    try:
                        result.append(max(1, int(self.bot.db.get_user(int(member_id)).get("level", 1))))
                    except (TypeError, ValueError):
                        continue
                return result

            chance = max(0.12, min(0.85, 0.50 + (self._calc_power(levels(attacker)) - self._calc_power(levels(defender))) * 0.06))
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
            await self.bot.db.save()

        if success:
            await ctx.send(embed=discord.Embed(
                title="⚔️ Raid Success",
                description=f"Stole **${stolen:,}** from **{defender.get('name', 'crew')}**!\nNet crew-bank gain: **${attacker_gain:,}**",
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
            await ctx.send("❌ Robbing yourself?")
            return
        robber = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, robber, "steal"):
            return

        async with self.bot.db.lock:
            victim = self.bot.db.get_user(target.id)
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
                    await ctx.send("That player is too poor to rob.")
                    return
                victim["grams"] = wallet - amount
                robber["dirty_cash"] = max(0, int(robber.get("dirty_cash", 0))) + amount
                add_heat(robber, 15)
                stats = robber.setdefault("stats", {})
                stats["steals"] = max(0, int(stats.get("steals", 0))) + 1
                success = True
                fine = 0
            else:
                balance = max(0, int(robber.get("grams", 0)))
                fine = calculate_capped_loss(balance, 1_000)
                robber["grams"] = balance - fine
                robber["jail_until"] = int(self._now() + 300)
                add_heat(robber, 25)
                amount = 0
                success = False
            await self.bot.db.save()

        if success:
            await ctx.send(f"🔫 **SUCCESS!** Stole **${amount:,}** in dirty cash.")
        else:
            await ctx.send(f"🚓 **BUSTED!** Fined ${fine:,} and jailed for 5m.")

    @commands.command(name="launder")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def launder(self, ctx, amount: str = "all"):
        user = self.bot.db.get_user(ctx.author.id)
        async with self.bot.db.lock:
            dirty = max(0, int(user.get("dirty_cash", 0) or 0))
            heat = max(0, int(user.get("heat", 0) or 0))
            if dirty <= 0:
                ctx.command.reset_cooldown(ctx)
                await ctx.send("❌ You have no **Dirty Cash** to launder.")
                return
            if heat >= 90:
                ctx.command.reset_cooldown(ctx)
                await ctx.send(f"🚓 **Too Hot!** Heat is **{heat}%**. Let it cool down first.")
                return

            raw = (amount or "all").strip().lower()
            try:
                requested = dirty if raw in ("all", "max", "*") else require_positive_amount(raw.replace(",", ""))
                outcome = calculate_launder_outcome(requested, dirty_balance=dirty, fee_rate=0.20)
            except ValueError as error:
                ctx.command.reset_cooldown(ctx)
                await ctx.send(f"❌ {error}.")
                return

            user["dirty_cash"] = dirty - outcome.dirty_spent
            user["grams"] = max(0, int(user.get("grams", 0))) + outcome.clean_received
            add_heat(user, 5)
            await self.bot.db.save()

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
        user = self.bot.db.get_user(ctx.author.id)
        heat_level = max(0, min(100, int(user.get("heat", 0) or 0)))
        dirty_cash = max(0, int(user.get("dirty_cash", 0) or 0))
        filled = heat_level // 10
        bar = "🟥" * filled + "⬜" * (10 - filled)
        if heat_level > 80:
            status = "WANTED 🚓"
        elif heat_level > 50:
            status = "Hot 🔥"
        elif heat_level > 20:
            status = "Suspicious"
        else:
            status = "Chill"
        embed = discord.Embed(title="🚓 Police Heat Level", color=0xE74C3C)
        embed.add_field(name="Heat", value=f"{bar} ({heat_level}%)", inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="💼 Dirty Cash", value=f"${dirty_cash:,}", inline=True)
        embed.set_footer(text="Use !launder to clean dirty cash. High heat increases crime risk.")
        await ctx.send(embed=embed)

    @commands.command(name="heiststats", aliases=["hst"])
    async def heiststats(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        stats = self.bot.db.get_user(target.id).get("stats", {})
        embed = discord.Embed(title=f"🏆 Heist Stats: {target.display_name}", color=0x3498DB)
        embed.add_field(name="Solo", value=f"Won: {stats.get('heists_won', 0)}\nRun: {stats.get('heists_run', 0)}", inline=True)
        embed.add_field(name="Raids", value=f"Won: {stats.get('raids_won', 0)}\nRun: {stats.get('raids_run', 0)}", inline=True)
        embed.add_field(name="Payouts", value=f"${stats.get('heist_profit', 0):,}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="topheists", aliases=["lbheists"])
    async def topheists(self, ctx):
        users = []
        for user_id, data in self.bot.db.data.items():
            if user_id == "__world__":
                continue
            wins = max(0, int(data.get("stats", {}).get("heists_won", 0)))
            if wins:
                users.append((user_id, wins))
        users.sort(key=lambda entry: entry[1], reverse=True)
        lines = []
        for index, (user_id, score) in enumerate(users[:10], 1):
            name = f"User {user_id}"
            if ctx.guild:
                member = ctx.guild.get_member(int(user_id))
                if member:
                    name = member.display_name
            lines.append(f"**{index}.** {name} — {score} wins")
        await ctx.send(embed=discord.Embed(
            title="🏆 Top Heisters",
            description="\n".join(lines) or "None",
            color=0xF1C40F,
        ))

    @commands.command(name="heistset", aliases=["heistsetchannel"])
    @commands.has_permissions(manage_guild=True)
    async def heistset(self, ctx, mode: str = "add"):
        clean_mode = (mode or "list").lower().strip()
        async with self.bot.db.lock:
            world = self.bot.db.world_state
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
                await self.bot.db.save()

        if clean_mode in ("add", "allow", "+"):
            await ctx.send(f"✅ Heists allowed in {ctx.channel.mention}")
        elif clean_mode in ("remove", "deny", "-", "del"):
            await ctx.send(f"✅ Heists blocked in {ctx.channel.mention}")
        else:
            names = []
            for channel_id in sorted(channels):
                channel = ctx.guild.get_channel(channel_id)
                names.append(channel.mention if channel else str(channel_id))
            await ctx.send("🏦 **Heist Channels:** " + ", ".join(names) if names else "✅ Heists allowed everywhere (default).")


async def setup(bot):
    await bot.add_cog(Crime(bot))
