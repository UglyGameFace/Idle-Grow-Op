import discord
import random
import time
import math
import asyncio
from discord.ext import commands
from utils import (
    db_manager, 
    jail_guard, 
    heat_value, 
    add_heat, 
    set_heat,
    inv_take, 
    inv_get, 
    has_item, 
    check_achievements
)

# ==========================================================
# ⚙️ HEIST CONFIGURATION (Extracted from main.py)
# ==========================================================
HEIST_SOLO_COOLDOWN = 30 * 60        # 30 min
HEIST_CREW_COOLDOWN = 60 * 60        # 60 min (per crew)
HEIST_RAID_COOLDOWN = 2 * 60 * 60    # 2 hours (per crew)
HEIST_JOIN_WINDOW = 45               # seconds

HEIST_JAIL_MIN = 3
HEIST_JAIL_MAX = 12

HEAT_MAX = 100
HEAT_GAIN_WIN = 6
HEAT_GAIN_FAIL = 12
HEAT_DECAY_PER_HOUR = 6

# Raid caps
RAID_MAX_STEAL_PCT = 0.18
RAID_MAX_STEAL_FLAT = 25000
RAID_MIN_TARGET_BANK = 5000

# In-memory lock for active heists
_ACTIVE_HEISTS = {}

class Crime(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==========================================================
    # 🛠️ HELPER FUNCTIONS
    # ==========================================================
    
    def _heist_now(self):
        return time.time()

    def _heist_fmt_time(self, seconds):
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h: return f"{h}h {m}m"
        if m: return f"{m}m {s}s"
        return f"{s}s"

    def _heist_in_jail(self, user):
        jail_until = int(user.get("jail_until", 0) or 0)
        rem = jail_until - int(self._heist_now())
        return rem if rem > 0 else 0

    def _heist_get_user_cd(self, user, key):
        cd = user.setdefault("cooldowns", {})
        return float(cd.get(key, 0) or 0)

    def _heist_set_user_cd(self, user, key, ts):
        cd = user.setdefault("cooldowns", {})
        cd[key] = float(ts)

    def _heist_crew_has_cooldown(self, crew, key):
        cds = crew.setdefault("cooldowns", {})
        last = float(cds.get(key, 0) or 0)
        dur = {"heist": HEIST_CREW_COOLDOWN, "raid": HEIST_RAID_COOLDOWN}.get(key, 0)
        rem = int((last + dur) - self._heist_now())
        return rem if rem > 0 else 0

    def _heist_set_crew_cooldown(self, crew, key):
        cds = crew.setdefault("cooldowns", {})
        cds[key] = float(self._heist_now())

    def _heist_calc_power(self, levels):
        if not levels: return 0.0
        s = sum((max(1, int(l)) ** 2) for l in levels)
        return (math.sqrt(s) / 10.0)

    def _heist_tier(self, level):
        if level <= 5: return "street"
        if level <= 12: return "crew"
        if level <= 25: return "pro"
        return "legend"

    def _heist_roll(self, chance):
        return random.random() < max(0.02, min(0.98, chance))

    def _get_crews(self):
        """Helper to safely fetch crews dict."""
        world = self.bot.db.world_state
        crews = world.get("crews")
        if not isinstance(crews, dict):
            crews = {}
            world["crews"] = crews
        return crews

    def _heat_apply_decay(self, user: dict) -> int:
        heat = int(user.get("heat", 0) or 0)
        last_ts = float(user.get("heat_ts", 0) or 0)
        now = float(self._heist_now())

        if last_ts > 0:
            hours = max(0.0, (now - last_ts) / 3600.0)
            if hours > 0:
                heat = max(0, heat - int(hours * HEAT_DECAY_PER_HOUR))

        user["heat_ts"] = now
        user["heat"] = int(max(0, min(HEAT_MAX, heat)))
        return int(user["heat"])

    def _heist_plan_mod(self, plan):
        plan = (plan or "stealth").lower().strip()
        if plan in ("stealth", "silent"): return ("STEALTH", +0.06, -0.10, -3)
        if plan in ("loud", "guns", "brute"): return ("LOUD", -0.08, +0.22, +10)
        if plan in ("con", "social", "scam"): return ("CON", +0.02, +0.08, +3)
        return ("STEALTH", +0.06, -0.10, -3)

    def _heist_solo_profile(self, level, prestige, heat, plan):
        tier = self._heist_tier(level)
        base = {
            "street": {"buyin": 250,  "reward": (600, 1400),   "xp": (40, 90),   "chance": 0.72},
            "crew":   {"buyin": 900,  "reward": (1800, 4800),  "xp": (90, 170),  "chance": 0.64},
            "pro":    {"buyin": 2600, "reward": (4800, 11800), "xp": (170, 320), "chance": 0.58},
            "legend": {"buyin": 7000, "reward": (12000, 28000),"xp": (320, 600), "chance": 0.52},
        }[tier]

        plan_name, ch_mod, pay_mod, heat_mod = self._heist_plan_mod(plan)

        lvl_mult = 1.0 + (min(level, 60) * 0.012)
        pres_mult = 1.0 + (prestige * 0.04)

        buyin = int(base["buyin"] * (0.92 + (lvl_mult * 0.10)))
        r_min = int(base["reward"][0] * lvl_mult * pres_mult * (1.0 + pay_mod))
        r_max = int(base["reward"][1] * lvl_mult * pres_mult * (1.0 + pay_mod))
        xp_min = int(base["xp"][0] * (1.0 + prestige * 0.05))
        xp_max = int(base["xp"][1] * (1.0 + prestige * 0.05))

        chance = base["chance"] + (min(level, 60) * 0.0025) + ch_mod
        # Heat Penalty (up to -25%)
        chance -= min(0.25, (heat / 100.0) * 0.25)

        return {
            "tier": tier,
            "plan": plan_name,
            "plan_heat_mod": heat_mod,
            "buyin": buyin,
            "reward_range": (max(1, r_min), max(2, r_max)),
            "xp_range": (max(1, xp_min), max(2, xp_max)),
            "chance": chance,
        }

    # ==========================================================
    # 🏦 MAIN HEIST COMMAND
    # ==========================================================
    @commands.command(name="heist", aliases=["heists"])
    async def heist(self, ctx, mode: str = "solo", arg: str = None):
        """
        Main Heist Command.
        !heist solo [loud/stealth] | !heist crew | !heist join | !heist raid <id>
        """
        user = self.bot.db.get_user(ctx.author.id)
        if await jail_guard(ctx, user, "heist"): return

        mode = (mode or "solo").lower().strip()

        # --- SOLO MODE ---
        if mode in ("solo", "", None):
            plan = (arg or "stealth")
            k = f"user:{ctx.author.id}"
            
            if k in _ACTIVE_HEISTS and _ACTIVE_HEISTS[k].get("ends", 0) > self._heist_now():
                return await ctx.send("⏳ You’re already mid-heist.")

            last = self._heist_get_user_cd(user, "heist_solo")
            rem = int((last + HEIST_SOLO_COOLDOWN) - self._heist_now())
            if rem > 0:
                return await ctx.send(f"⏳ Solo heist cooldown: **{self._heist_fmt_time(rem)}**")

            heat = self._heat_apply_decay(user)
            lvl = int(user.get("level", 1) or 1)
            prestige = int(user.get("prestige", 0) or 0)
            cfg = self._heist_solo_profile(lvl, prestige, heat, plan)

            if int(user.get("grams", 0) or 0) < cfg["buyin"]:
                return await ctx.send(f"💸 You need **${cfg['buyin']:,}** for this job.")

            _ACTIVE_HEISTS[k] = {"ends": self._heist_now() + 8}
            user["grams"] = int(user.get("grams", 0)) - int(cfg["buyin"])
            success = self._heist_roll(cfg["chance"])

            stats = user.setdefault("stats", {})
            stats["heists_run"] = int(stats.get("heists_run", 0)) + 1

            if success:
                payout = random.randint(*cfg["reward_range"])
                xp = random.randint(*cfg["xp_range"])
                
                user["grams"] = int(user.get("grams", 0)) + int(payout)
                
                # Apply Heat
                add_heat(user, HEAT_GAIN_WIN + int(cfg["plan_heat_mod"]))

                self._heist_set_user_cd(user, "heist_solo", self._heist_now())
                stats["heists_won"] = int(stats.get("heists_won", 0)) + 1
                stats["heist_profit"] = int(stats.get("heist_profit", 0)) + int(payout)
                
                user["xp"] = int(user.get("xp", 0)) + xp

                await self.bot.db.save()

                e = discord.Embed(
                    title="🏦 Heist Success",
                    description=(
                        f"**Plan:** {cfg['plan']}\n"
                        f"🎯 Odds: **{int(cfg['chance']*100)}%**\n"
                        f"💰 Profit: **+${payout:,}**\n"
                        f"⭐ XP: **+{xp:,}**\n"
                        f"🚓 Heat: **{int(user.get('heat',0))}%**"
                    ),
                    color=0x2ecc71
                )
                return await ctx.send(embed=e)

            else:
                # Fail
                loss = int(max(150, cfg["buyin"] * random.uniform(0.30, 0.70)))
                loss = min(loss, int(user.get("grams", 0)))
                user["grams"] = int(user.get("grams", 0)) - int(loss)

                jail_mins = random.randint(HEIST_JAIL_MIN, HEIST_JAIL_MAX)
                user["jail_until"] = int(self._heist_now() + jail_mins * 60)

                add_heat(user, HEAT_GAIN_FAIL + int(cfg["plan_heat_mod"]))

                self._heist_set_user_cd(user, "heist_solo", self._heist_now())
                stats["heists_lost"] = int(stats.get("heists_lost", 0)) + 1
                await self.bot.db.save()

                e = discord.Embed(
                    title="🚨 Heist Failed",
                    description=(
                        f"**Plan:** {cfg['plan']}\n"
                        f"🎯 Odds: **{int(cfg['chance']*100)}%**\n"
                        f"💸 Lost: **${loss:,}**\n"
                        f"🚔 Jail: **{jail_mins}m**\n"
                        f"🚓 Heat: **{int(user.get('heat',0))}%**"
                    ),
                    color=0xe74c3c
                )
                return await ctx.send(embed=e)

        # --- CREW MODE ---
        if mode in ("crew", "coop"):
            crew_id = user.get("crew_id")
            if not crew_id: return await ctx.send("❌ You need a crew.")
            
            crews = self._get_crews()
            crew = crews.get(str(crew_id))
            if not crew: return await ctx.send("❌ Crew data missing.")

            rem = self._heist_crew_has_cooldown(crew, "heist")
            if rem > 0: return await ctx.send(f"⏳ Crew Cooldown: **{self._heist_fmt_time(rem)}**")

            k = f"crew:{crew_id}"
            if k in _ACTIVE_HEISTS and _ACTIVE_HEISTS[k].get("join_until", 0) > self._heist_now():
                return await ctx.send("⏳ Crew heist already forming. Use `!heist join`.")

            _ACTIVE_HEISTS[k] = {
                "join_until": self._heist_now() + HEIST_JOIN_WINDOW,
                "members": set([int(ctx.author.id)]),
                "host_id": int(ctx.author.id),
            }

            e = discord.Embed(
                title="🧪 Crew Heist Forming",
                description=f"**{crew.get('name','Crew')}** is starting a job!\nType `!heist join` within **{HEIST_JOIN_WINDOW}s**.\nNeed 2+ members.",
                color=0x9b59b6
            )
            await ctx.send(embed=e)
            
            await asyncio.sleep(HEIST_JOIN_WINDOW + 1)
            sess = _ACTIVE_HEISTS.pop(k, None)
            if not sess: return

            joined = list(sess.get("members", set()))
            valid_members = []
            
            # Verify members (not jailed)
            for uid in joined:
                u = self.bot.db.get_user(int(uid))
                if self._heist_in_jail(u) <= 0:
                    valid_members.append((uid, u))

            if len(valid_members) < 2:
                return await ctx.send("❌ Heist Cancelled: Not enough members joined.")

            lvls = [int(u.get("level",1)) for _, u in valid_members]
            power = self._heist_calc_power(lvls)
            chance = max(0.18, min(0.88, 0.46 + (power * 0.06) + (len(valid_members) * 0.03)))
            
            success = self._heist_roll(chance)
            base = int(2600 + power * 1200)
            total = random.randint(int(base*0.7), int(base*1.3))

            if success:
                to_bank = int(total * 0.30)
                to_split = total - to_bank
                per = max(1, int(to_split / len(valid_members)))
                
                crew["bank"] = int(crew.get("bank",0)) + to_bank
                
                for _, u in valid_members:
                    u["grams"] = int(u.get("grams",0)) + per
                    add_heat(u, 2)
                    
                self._heist_set_crew_cooldown(crew, "heist")
                await self.bot.db.save()
                
                return await ctx.send(embed=discord.Embed(
                    title="🏦 Crew Heist Success",
                    description=f"💰 Total: **${total:,}**\n🏦 Crew Bank: **+${to_bank:,}**\n👤 Each: **+${per:,}**",
                    color=0x2ecc71
                ))
            else:
                jail_mins = random.randint(2, 7)
                for _, u in valid_members:
                    loss = int((u.get("grams",0) or 0) * 0.04)
                    u["grams"] = int(u.get("grams",0)) - loss
                    u["jail_until"] = int(self._heist_now() + jail_mins * 60)
                    add_heat(u, 6)
                
                self._heist_set_crew_cooldown(crew, "heist")
                await self.bot.db.save()
                return await ctx.send(f"🚨 **Crew Heist Failed.** Members jailed for {jail_mins}m.")

        # --- JOIN MODE ---
        if mode == "join":
            if self._heist_in_jail(user) > 0: return await ctx.send("🚔 You are jailed.")
            
            crew_id = user.get("crew_id")
            if not crew_id: return await ctx.send("❌ You need a crew.")
            
            k = f"crew:{crew_id}"
            sess = _ACTIVE_HEISTS.get(k)
            if not sess or sess.get("join_until", 0) <= self._heist_now():
                return await ctx.send("❌ No heist forming.")
            
            sess["members"].add(int(ctx.author.id))
            return await ctx.send(f"✅ {ctx.author.mention} joined!")

        # --- RAID MODE (PvP) ---
        if mode in ("raid", "pvp"):
            crew_id = user.get("crew_id")
            if not crew_id: return await ctx.send("❌ You need a crew.")
            if not arg: return await ctx.send("Usage: `!heist raid <target_crew_id>`")
            
            crews = self._get_crews()
            atk = crews.get(str(crew_id))
            dfd = crews.get(str(arg).strip())
            
            if not atk or not dfd: return await ctx.send("❌ Invalid crew IDs.")
            if atk == dfd: return await ctx.send("❌ Cannot raid yourself.")
            
            rem = self._heist_crew_has_cooldown(atk, "raid")
            if rem > 0: return await ctx.send(f"⏳ Raid Cooldown: **{self._heist_fmt_time(rem)}**")

            if int(dfd.get("bank",0)) < RAID_MIN_TARGET_BANK:
                return await ctx.send("❌ Target is too poor to raid.")

            # Get members for power calc
            def get_members(c):
                m_list = []
                for mid in c.get("members", []):
                    try: m_list.append(int(mid))
                    except: pass
                return m_list

            atk_lvls = [int(self.bot.db.get_user(uid).get("level",1)) for uid in get_members(atk)]
            dfd_lvls = [int(self.bot.db.get_user(uid).get("level",1)) for uid in get_members(dfd)]
            
            chance = max(0.12, min(0.85, 0.50 + (self._heist_calc_power(atk_lvls) - self._heist_calc_power(dfd_lvls)) * 0.06))
            success = self._heist_roll(chance)

            if success:
                target_bank = int(dfd.get("bank",0))
                steal = int(min(RAID_MAX_STEAL_FLAT, target_bank * RAID_MAX_STEAL_PCT))
                atk_gain = int(steal * 0.85)
                
                dfd["bank"] = target_bank - steal
                atk["bank"] = int(atk.get("bank",0)) + atk_gain
                
                self._heist_set_crew_cooldown(atk, "raid")
                await self.bot.db.save()
                
                return await ctx.send(embed=discord.Embed(
                    title="⚔️ Raid Success",
                    description=f"Stole **${steal:,}** from **{dfd.get('name')}**!\n(Net Gain: ${atk_gain:,})",
                    color=0xf1c40f
                ))
            else:
                penalty = int(min(12000, int(atk.get("bank",0)) * 0.06))
                atk["bank"] = int(atk.get("bank",0)) - penalty
                self._heist_set_crew_cooldown(atk, "raid")
                await self.bot.db.save()
                
                return await ctx.send(embed=discord.Embed(
                    title="🚫 Raid Failed",
                    description=f"Attack failed. Lost **${penalty:,}** in resources.",
                    color=0xe74c3c
                ))

    # ==========================================================
    # 🕵️ STEAL COMMAND (PVP)
    # ==========================================================
    @commands.hybrid_command(name="steal", aliases=["rob"])
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def steal(self, ctx, target: discord.Member):
        """Attempt to rob another player."""
        if target.id == ctx.author.id: return await ctx.send("❌ Robbing yourself?")
            
        user = self.bot.db.get_user(ctx.author.id)
        victim = self.bot.db.get_user(target.id)
        
        if await jail_guard(ctx, user, "steal"): return
        if not victim: return await ctx.send("❌ They don't play.")
        
        chance = 0.50
        if has_item(victim, "dog") or has_item(victim, "guard dog"): chance -= 0.25
        if has_item(victim, "cam") or has_item(victim, "security camera"): chance -= 0.15
        if has_item(user, "lockpick"): chance += 0.10
        if has_item(user, "ski mask"): chance += 0.10
        
        chance = max(0.05, min(0.90, chance))
        
        if random.random() < chance:
            wallet = int(victim.get("grams", 0))
            if wallet < 100: return await ctx.send("Too poor to rob.")
                
            amt = int(wallet * random.uniform(0.05, 0.20))
            victim["grams"] -= amt
            user["dirty_cash"] = int(user.get("dirty_cash", 0) + amt)
            
            add_heat(user, 15)
            user.setdefault("stats", {})["steals"] = user["stats"].get("steals", 0) + 1
            
            await ctx.send(f"🔫 **SUCCESS!** Stole **${amt:,}** (Dirty Cash).")
        else:
            fine = 1000
            user["grams"] = max(0, int(user.get("grams", 0)) - fine)
            user["jail_until"] = int(time.time() + 300)
            
            add_heat(user, 25)
            await ctx.send(f"🚓 **BUSTED!** Fined ${fine} & Jailed 5m.")
            
        await self.bot.db.save()

    # ==========================================================
    # 🧼 LAUNDER COMMAND
    # ==========================================================
    @commands.command(name="launder")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def launder(self, ctx, amount: str = "all"):
        """
        Clean your dirty cash.
        - Fee: 20%
        - Heat: +5
        - Restriction: cannot launder if Heat >= 90
        """
        user = self.bot.db.get_user(ctx.author.id)
        if not user:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("❌ You need to start the game first. Use `!start`.")

        dirty = int(user.get("dirty_cash", 0) or 0)
        heat_val = int(user.get("heat", 0) or 0)

        if dirty <= 0:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("❌ You have no **Dirty Cash** to launder.")

        if heat_val >= 90:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(f"🚓 **Too Hot!** Heat is **{heat_val}%**. Let it cool down first.")

        amt_raw = (amount or "all").strip().lower()
        if amt_raw in ("all", "max", "*"):
            to_clean = dirty
        else:
            try:
                to_clean = int(amt_raw.replace(",", ""))
            except Exception:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("❌ Invalid amount.")

        to_clean = max(0, min(to_clean, dirty))
        if to_clean <= 0:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("❌ Amount must be positive.")

        fee_pct = 0.20
        fee = int(to_clean * fee_pct)
        clean_gain = max(0, to_clean - fee)

        user["dirty_cash"] = max(0, dirty - to_clean)
        user["grams"] = int(user.get("grams", 0) or 0) + clean_gain
        user["heat"] = min(100, heat_val + 5)

        await self.bot.db.save()

        embed = discord.Embed(
            title="🧼 Money Laundered",
            description=f"You cleaned **${to_clean:,}** dirty cash.",
            color=0x95A5A6
        )
        embed.add_field(name="💸 Fee (20%)", value=f"-${fee:,}", inline=True)
        embed.add_field(name="💰 Received", value=f"+${clean_gain:,} (clean)", inline=True)
        embed.add_field(name="🔥 Heat", value=f"+5 (Total: {int(user.get('heat', 0) or 0)}%)", inline=True)

        await ctx.send(embed=embed)

    # ==========================================================
    # 🔥 HEAT CHECK
    # ==========================================================
    @commands.command(name="heat")
    async def heat(self, ctx):
        """Check your heat level and dirty cash status."""
        user = self.bot.db.get_user(ctx.author.id) or {}
        heat_level = int(user.get("heat", 0) or 0)
        dirty_cash = int(user.get("dirty_cash", 0) or 0)

        # Visual Heat Bar (0-100)
        bar_len = 10
        filled = max(0, min(bar_len, int(heat_level // 10)))
        bar = "🟥" * filled + "⬜" * (bar_len - filled)

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
        embed.set_footer(text="Use !launder to clean dirty cash. High heat = Raid Risk!")

        await ctx.send(embed=embed)

    # ==========================================================
    # 🏆 STATS COMMANDS
    # ==========================================================
    @commands.command(name="heiststats", aliases=["hst"])
    async def heiststats(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        u = self.bot.db.get_user(target.id)
        if not u: return await ctx.send("❌ User not found.")
        
        st = u.get("stats", {})
        e = discord.Embed(title=f"🏆 Heist Stats: {target.display_name}", color=0x3498db)
        e.add_field(name="Solo", value=f"Won: {st.get('heists_won',0)}\nRun: {st.get('heists_run',0)}", inline=True)
        e.add_field(name="Raids", value=f"Won: {st.get('raids_won',0)}\nRun: {st.get('raids_run',0)}", inline=True)
        e.add_field(name="Profit", value=f"${st.get('heist_profit',0):,}", inline=False)
        await ctx.send(embed=e)

    @commands.command(name="topheists", aliases=["lbheists"])
    async def topheists(self, ctx):
        users = []
        for uid, data in self.bot.db.data.items():
            if uid == "__world__": continue
            hw = data.get("stats", {}).get("heists_won", 0)
            if hw > 0: users.append((uid, hw))
        
        users.sort(key=lambda x: x[1], reverse=True)
        lines = []
        for i, (uid, score) in enumerate(users[:10], 1):
            name = f"User {uid}"
            if ctx.guild:
                m = ctx.guild.get_member(int(uid))
                if m: name = m.display_name
            lines.append(f"**{i}.** {name} — {score} wins")
            
        e = discord.Embed(title="🏆 Top Heisters", description="\n".join(lines) or "None", color=0xf1c40f)
        await ctx.send(embed=e)

    # ==========================================================
    # ⚙️ ADMIN: SET HEIST CHANNELS
    # ==========================================================
    @commands.command(name="heistset", aliases=["heistsetchannel"])
    @commands.has_permissions(manage_guild=True)
    async def heistset(self, ctx, mode: str = "add"):
        """Manage allowed heist channels."""
        # This implementation uses the world state directly
        try:
            ws = self.bot.db.world_state
            chans = set(ws.get("heist_channels", []))
        except:
            chans = set()

        cid = int(ctx.channel.id)
        mode = mode.lower().strip()

        if mode in ("add", "allow", "+"):
            chans.add(cid)
            ws["heist_channels"] = list(chans)
            await self.bot.db.save()
            return await ctx.send(f"✅ Heists ALLOWED in {ctx.channel.mention}")

        if mode in ("remove", "deny", "-", "del"):
            if cid in chans: chans.remove(cid)
            ws["heist_channels"] = list(chans)
            await self.bot.db.save()
            return await ctx.send(f"✅ Heists BLOCKED in {ctx.channel.mention}")
        
        # List logic
        names = []
        for c in chans:
            ch = ctx.guild.get_channel(c)
            names.append(ch.mention if ch else str(c))
        
        if not names: await ctx.send("✅ Heists allowed everywhere (Default).")
        else: await ctx.send("🏦 **Heist Channels:** " + ", ".join(names))

async def setup(bot):
    await bot.add_cog(Crime(bot))