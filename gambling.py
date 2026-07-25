from __future__ import annotations

import asyncio
import random
import re
import secrets
from typing import Any

import discord
from discord.ext import commands

from persistence_context import GuildContextRequired, require_guild_id
from progression_core import add_progress, check_achievements
from utils import GAMBLE_CONFIG, SLOTS_PAYOUTS, SLOTS_SYMBOLS, jail_guard
from world_modes import (
    WorldModeDenied,
    require_multiplayer,
    resolve_game_scope,
)

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
GAME_METRICS = {
    "all": "casino_total_profit",
    "coinflip": "coinflip_profit", "cf": "coinflip_profit",
    "slots": "slots_profit", "blackjack": "blackjack_profit", "bj": "blackjack_profit",
    "dice": "dice_profit", "roulette": "roulette_profit", "hilo": "hilo_profit",
    "rps": "rps_profit", "crash": "crash_profit", "wheel": "wheel_profit",
    "cups": "cups_profit", "keno": "keno_profit", "numbers": "keno_profit",
}


def _cfg(key: str, default: Any) -> Any:
    return GAMBLE_CONFIG.get(key, default) if isinstance(GAMBLE_CONFIG, dict) else default


def _fmt_cash(value: int) -> str:
    value = int(value or 0)
    return f"{'-' if value < 0 else ''}${abs(value):,}"


def _parse_bet(raw: str | int | None, balance: int, *, min_bet: int = 1, max_bet: int | None = None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        amount = raw
    else:
        token = str(raw).strip().lower().replace(",", "")
        if token.startswith("$"):
            token = token[1:]
        token = token.rstrip(".!?,;:")
        if token in {"all", "max"}:
            amount = balance
        elif token in {"half", "1/2"}:
            amount = balance // 2
        elif token.endswith("%"):
            try:
                amount = int(balance * float(token[:-1]) / 100)
            except ValueError:
                return None
        else:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)([kmb])?", token)
            if not match:
                return None
            amount = int(float(match.group(1)) * _SUFFIX.get(match.group(2), 1))
    amount = int(amount)
    if max_bet is not None:
        amount = min(amount, int(max_bet))
    if amount < int(min_bet) or amount > int(balance):
        return None
    return amount


def _norm(value: str | None) -> str:
    return str(value or "").strip().lower()


def _pick_bet_and_choice(*, arg1, arg2, balance, min_bet, default_bet, default_choice, aliases, valid):
    def choice(value):
        normalized = aliases.get(_norm(value), _norm(value))
        return normalized if normalized in valid else None

    c1, c2 = choice(arg1), choice(arg2)
    b1 = _parse_bet(arg1, balance, min_bet=min_bet)
    b2 = _parse_bet(arg2, balance, min_bet=min_bet)
    if not arg1 and not arg2:
        return default_bet, default_choice
    if c1 and b2 is not None and b1 is None:
        return str(arg2), c1
    if b1 is not None and c2:
        return str(arg1), c2
    if c1 and not arg2:
        return default_bet, c1
    if b1 is not None and not arg2:
        return str(arg1), default_choice
    return None, None


def update_gamble_stats(profile: dict, game: str, net_change: int, wagered: int) -> None:
    stats = profile.setdefault("stats", {})
    wagered = max(0, int(wagered))
    net_change = int(net_change)
    for key in ("casino_total_bets", f"{game}_bets"):
        stats[key] = int(stats.get(key, 0) or 0) + 1
    for key in ("casino_total_wagered", f"{game}_wagered"):
        stats[key] = int(stats.get(key, 0) or 0) + wagered
    for key in ("casino_total_profit", f"{game}_profit"):
        stats[key] = int(stats.get(key, 0) or 0) + net_change
    if net_change > 0:
        stats["gambler_wins"] = int(stats.get("gambler_wins", 0) or 0) + 1
        stats[f"{game}_wins"] = int(stats.get(f"{game}_wins", 0) or 0) + 1
        streak = int(stats.get("casino_win_streak", 0) or 0) + 1
        stats["casino_win_streak"] = streak
        stats["casino_loss_streak"] = 0
        stats["casino_best_win_streak"] = max(int(stats.get("casino_best_win_streak", 0) or 0), streak)
        stats["casino_biggest_win"] = max(int(stats.get("casino_biggest_win", 0) or 0), net_change)
    elif net_change < 0:
        stats["gambler_losses"] = int(stats.get("gambler_losses", 0) or 0) + 1
        stats[f"{game}_losses"] = int(stats.get(f"{game}_losses", 0) or 0) + 1
        streak = int(stats.get("casino_loss_streak", 0) or 0) + 1
        stats["casino_loss_streak"] = streak
        stats["casino_win_streak"] = 0
        stats["casino_best_loss_streak"] = max(int(stats.get("casino_best_loss_streak", 0) or 0), streak)
        stats["casino_biggest_loss"] = max(int(stats.get("casino_biggest_loss", 0) or 0), abs(net_change))


def _record_win(profile: dict, user_id: int) -> None:
    add_progress(profile, "gamble_win", 1, user_id=user_id)
    check_achievements(profile)


class BlackjackView(discord.ui.View):
    def __init__(self, cog: "Gambling", ctx, scope_id: int, user_id: int, bet: int, deck, player, dealer):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.scope_id = scope_id
        self.user_id = user_id
        self.bet = bet
        self.deck = deck
        self.player = player
        self.dealer = dealer
        self.message: discord.Message | None = None
        self.ended = False
        self._settle_lock = asyncio.Lock()

    @staticmethod
    def value(hand) -> int:
        total = 0
        aces = 0
        for card in hand:
            if card in {"J", "Q", "K"}:
                total += 10
            elif card == "A":
                total += 11
                aces += 1
            else:
                total += int(card)
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    @staticmethod
    def cards(hand) -> str:
        return " ".join(f"[{card}]" for card in hand)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your game.", ephemeral=True)
            return False
        return True

    async def _settle(self, result: str, payout: int = 0, *, timeout_refund: bool = False) -> None:
        async with self._settle_lock:
            if self.ended:
                return
            self.ended = True
            async with self.cog.bot.db.lock:
                profile = await self.cog.bot.db.get_profile(self.scope_id, self.user_id)
                if timeout_refund:
                    profile["grams"] = int(profile.get("grams", 0) or 0) + self.bet
                    title, color = "🃏 Blackjack expired — wager refunded", discord.Color.gold()
                elif result == "win":
                    profile["grams"] = int(profile.get("grams", 0) or 0) + payout
                    update_gamble_stats(profile, "blackjack", payout - self.bet, self.bet)
                    _record_win(profile, self.user_id)
                    title, color = f"🃏 Won {_fmt_cash(payout)}", discord.Color.green()
                elif result == "tie":
                    profile["grams"] = int(profile.get("grams", 0) or 0) + self.bet
                    update_gamble_stats(profile, "blackjack", 0, self.bet)
                    title, color = "🃏 Push — wager returned", discord.Color.gold()
                else:
                    update_gamble_stats(profile, "blackjack", -self.bet, self.bet)
                    title, color = f"🃏 Lost {_fmt_cash(self.bet)}", discord.Color.red()
                self.cog.bot.db.mark_profile_dirty(self.scope_id, self.user_id)
            self.clear_items()
            embed = discord.Embed(title=title, color=color)
            embed.add_field(name="Your Hand", value=f"{self.cards(self.player)}\nValue: **{self.value(self.player)}**")
            embed.add_field(name="Dealer Hand", value=f"{self.cards(self.dealer)}\nValue: **{self.value(self.dealer)}**")
            if self.message:
                try:
                    await self.message.edit(embed=embed, view=self)
                except discord.HTTPException:
                    pass
            self.stop()

    async def on_timeout(self) -> None:
        await self._settle("tie", timeout_refund=True)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, _button):
        await interaction.response.defer()
        self.player.append(self.deck.pop())
        if self.value(self.player) > 21:
            await self._settle("lose")
        elif self.message:
            embed = self.message.embeds[0]
            embed.set_field_at(0, name="Your Hand", value=f"{self.cards(self.player)}\nValue: **{self.value(self.player)}**")
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, _button):
        await interaction.response.defer()
        while self.value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        p, d = self.value(self.player), self.value(self.dealer)
        await self._settle("win" if d > 21 or p > d else "tie" if p == d else "lose", self.bet * 2)


class Gambling(commands.Cog):
    """Guild-scoped Enterprise casino. Every wager settles atomically."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        try:
            require_guild_id(ctx)
        except GuildContextRequired as exc:
            await ctx.send(f"❌ {exc}.")
            return False
        return True

    async def _profile(self, ctx, user_id: int | None = None):
        guild_id = require_guild_id(ctx)
        resolved = ctx.author.id if user_id is None else user_id
        scope = await resolve_game_scope(self.bot.db, guild_id, resolved)
        return scope, await self.bot.db.get_profile(scope.scope_id, resolved)

    async def _usage(self, ctx, title: str, *examples: str):
        await ctx.send(embed=discord.Embed(title=title, description="**Examples:**\n" + "\n".join(f"• `{x}`" for x in examples), color=0x9B59B6))

    async def _atomic_game(self, ctx, raw_bet, game: str, resolver, *, min_bet=10, max_bet=None):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        async with self.bot.db.lock:
            profile = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
            if await jail_guard(ctx, profile, "gamble"):
                return None
            balance = max(0, int(profile.get("grams", 0) or 0))
            bet = _parse_bet(raw_bet, balance, min_bet=int(min_bet), max_bet=max_bet)
            if bet is None:
                await ctx.send(f"❌ Invalid bet or insufficient funds. Minimum: {_fmt_cash(min_bet)}.")
                return None
            profile["grams"] = balance - bet
            result = resolver(bet)
            payout = max(0, int(result.get("payout", 0)))
            profile["grams"] += payout
            net = payout - bet
            update_gamble_stats(profile, game, net, bet)
            if net > 0:
                _record_win(profile, ctx.author.id)
            self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
        return bet, result

    @commands.hybrid_command(name="casino", aliases=["gambleprofile"])
    async def casino_profile(self, ctx, target: discord.User = None):
        target = target or ctx.author
        scope, profile = await self._profile(ctx, target.id)
        stats = profile.get("stats", {}) or {}
        wins = int(stats.get("gambler_wins", 0) or 0)
        losses = int(stats.get("gambler_losses", 0) or 0)
        profit = int(stats.get("casino_total_profit", 0) or 0)
        embed = discord.Embed(title=f"🎰 {target.name}'s Gambling Record", color=0x9B59B6)
        embed.description = f"**Active save:** {scope.emoji} {scope.label}"
        embed.add_field(name="Net Profit", value=f"{'+' if profit >= 0 else '-'}{_fmt_cash(abs(profit))}", inline=False)
        embed.add_field(name="Activity", value=f"Bets: **{int(stats.get('casino_total_bets', 0) or 0):,}**\nWagered: **{_fmt_cash(int(stats.get('casino_total_wagered', 0) or 0))}**")
        total = wins + losses
        embed.add_field(name="Win Rate", value=f"{(wins / total * 100 if total else 0):.1f}% ({wins}W/{losses}L)")
        lines = []
        for game in ("coinflip", "slots", "blackjack", "dice", "roulette", "hilo", "rps", "crash", "wheel", "cups", "keno"):
            value = int(stats.get(f"{game}_profit", 0) or 0)
            lines.append(f"**{game.title()}**: {'+' if value >= 0 else '-'}{_fmt_cash(abs(value))}")
        embed.add_field(name="Game Breakdown", value="\n".join(lines), inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="casinolb", aliases=["clb", "gamblinglb"])
    async def casinolb(self, ctx, game: str = "all"):
        guild_id = require_guild_id(ctx)
        scope = await resolve_game_scope(self.bot.db, guild_id, ctx.author.id)
        try:
            require_multiplayer(scope, "leaderboard")
        except WorldModeDenied as exc:
            return await ctx.send(str(exc))
        metric = GAME_METRICS.get(_norm(game), "casino_total_profit")
        rows = await self.bot.db.list_guild_casino_leaderboard(
            scope.scope_id, metric=metric, limit=10
        )
        lines = []
        for index, row in enumerate(rows):
            uid, amount = int(row[0]), int(row[1])
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            rank = "🥇" if index == 0 else "🥈" if index == 1 else "🥉" if index == 2 else f"#{index + 1}"
            lines.append(f"{rank} **{name}**: {'+' if amount >= 0 else '-'}{_fmt_cash(abs(amount))}")
        await ctx.send(embed=discord.Embed(title=f"🏛️ Casino Leaderboard: {game.upper()}", description="\n".join(lines) or "No data.", color=0x9B59B6))

    @commands.hybrid_command(name="coinflip", aliases=["cf", "flip"])
    async def coinflip(self, ctx, arg1: str | None = None, arg2: str | None = None):
        _, profile = await self._profile(ctx)
        balance = int(profile.get("grams", 0) or 0)
        token, choice = _pick_bet_and_choice(arg1=arg1, arg2=arg2, balance=balance, min_bet=int(_cfg("coinflip_min_bet", 10)), default_bet="100", default_choice="heads", aliases={"h":"heads","head":"heads","heads":"heads","t":"tails","tail":"tails","tails":"tails"}, valid={"heads","tails"})
        if not token:
            return await self._usage(ctx, "🪙 Coinflip", "!coinflip heads 500", "!coinflip 500 tails")
        result = await self._atomic_game(ctx, token, "coinflip", lambda bet: (lambda landed: {"payout": bet * 2 if landed == choice else 0, "landed": landed})(secrets.choice(["heads", "tails"])), min_bet=int(_cfg("coinflip_min_bet", 10)))
        if result:
            bet, data = result
            await ctx.send(f"🪙 **{data['landed'].upper()}!** " + (f"Won **{_fmt_cash(data['payout'])}**." if data['payout'] else f"Lost **{_fmt_cash(bet)}**."))

    @commands.hybrid_command(name="slots", aliases=["slot"])
    async def slots(self, ctx, amount: str = "100"):
        def resolve(bet):
            row = [random.choice(SLOTS_SYMBOLS) for _ in range(3)]
            payout = int(bet * SLOTS_PAYOUTS.get(row[0], 2) * 3) if len(set(row)) == 1 else int(bet * 1.5) if row[0] == row[1] or row[1] == row[2] else 0
            return {"payout": payout, "row": row}
        result = await self._atomic_game(ctx, amount, "slots", resolve, min_bet=int(_cfg("slots_min_bet", 10)))
        if result:
            bet, data = result
            await ctx.send(f"🎰 | {'  '.join(data['row'])} | " + (f"🍀 WIN ({_fmt_cash(data['payout'])})" if data['payout'] else f"💀 LOSE (-{_fmt_cash(bet)})"))

    @commands.hybrid_command(name="dice", aliases=["roll"])
    async def dice(self, ctx, bet: str = "100", guess: str = "over", target: int = 50):
        target = max(2, min(98, int(target)))
        mode = "over" if _norm(guess) in {"o","over","high","above",">"} else "under" if _norm(guess) in {"u","under","low","below","<"} else None
        if not mode:
            return await ctx.send("❌ Guess must be `over` or `under`.")
        def resolve(wager):
            roll = random.randint(1, 100)
            win = roll > target if mode == "over" else roll < target
            probability = (100-target)/100 if mode == "over" else (target-1)/100
            payout = int(wager * max(1.01, (1-float(_cfg("dice_house_edge", .04))) / max(.01, probability))) if win else 0
            return {"payout": payout, "roll": roll}
        result = await self._atomic_game(ctx, bet, "dice", resolve, min_bet=int(_cfg("dice_min_bet", 10)))
        if result:
            wager, data = result
            await ctx.send(f"🎲 Rolled **{data['roll']}** — needed **{mode} {target}**. " + (f"✅ Won **{_fmt_cash(data['payout'])}**." if data['payout'] else f"❌ Lost **{_fmt_cash(wager)}**."))

    @commands.hybrid_command(name="hilo", aliases=["highlow", "hl"])
    async def hilo(self, ctx, arg1: str | None = None, arg2: str | None = None):
        _, profile = await self._profile(ctx)
        token, choice = _pick_bet_and_choice(arg1=arg1,arg2=arg2,balance=int(profile.get("grams",0) or 0),min_bet=int(_cfg("hilo_min_bet",10)),default_bet="100",default_choice="high",aliases={"h":"high","hi":"high","high":"high","l":"low","lo":"low","low":"low","7":"7","seven":"7","mid":"7"},valid={"high","low","7"})
        if not token:
            return await self._usage(ctx, "🃏 HiLo", "!hilo high 1k", "!hilo 7 500")
        def resolve(bet):
            card=random.randint(1,13); won=(choice=="high" and card>=8) or (choice=="low" and card<=6) or (choice=="7" and card==7)
            return {"payout": int(bet * (12 if choice=="7" else 2)) if won else 0, "card": {1:"A",11:"J",12:"Q",13:"K"}.get(card,str(card))}
        result=await self._atomic_game(ctx,token,"hilo",resolve,min_bet=int(_cfg("hilo_min_bet",10)))
        if result:
            bet,data=result; await ctx.send(f"🃏 Drew **{data['card']}**. "+(f"✅ Won **{_fmt_cash(data['payout'])}**." if data['payout'] else f"❌ Lost **{_fmt_cash(bet)}**."))

    @commands.hybrid_command(name="rps", aliases=["rockpaperscissors"])
    async def rps(self, ctx, arg1: str | None = None, arg2: str | None = None):
        _, profile=await self._profile(ctx); token,choice=_pick_bet_and_choice(arg1=arg1,arg2=arg2,balance=int(profile.get("grams",0) or 0),min_bet=int(_cfg("rps_min_bet",10)),default_bet="100",default_choice="rock",aliases={"r":"rock","rock":"rock","p":"paper","paper":"paper","s":"scissors","scissor":"scissors","scissors":"scissors"},valid={"rock","paper","scissors"})
        if not token: return await self._usage(ctx,"✊ Rock Paper Scissors","!rps paper 500","!rps 500 scissors")
        def resolve(bet):
            dealer=secrets.choice(["rock","paper","scissors"]); win={"rock":"scissors","paper":"rock","scissors":"paper"}; payout=bet if dealer==choice else bet*2 if win[choice]==dealer else 0
            return {"payout":payout,"dealer":dealer}
        result=await self._atomic_game(ctx,token,"rps",resolve,min_bet=int(_cfg("rps_min_bet",10)))
        if result:
            bet,data=result; net=data['payout']-bet; await ctx.send(f"✊ You: **{choice.upper()}** | Dealer: **{data['dealer'].upper()}** — "+("PUSH." if net==0 else f"✅ Won **{_fmt_cash(data['payout'])}**." if net>0 else f"❌ Lost **{_fmt_cash(bet)}**."))

    @commands.hybrid_command(name="cups", aliases=["shell", "shellgame"])
    async def cups(self, ctx, arg1: str | None = None, arg2: str | None = None):
        _,profile=await self._profile(ctx); bal=int(profile.get("grams",0) or 0); a1,a2=_norm(arg1),_norm(arg2); cup=None; token=None
        if a1 in {"1","2","3"} and _parse_bet(arg2,bal,min_bet=int(_cfg("cups_min_bet",10))) is not None: cup,token=int(a1),str(arg2)
        elif _parse_bet(arg1,bal,min_bet=int(_cfg("cups_min_bet",10))) is not None and a2 in {"1","2","3"}: cup,token=int(a2),str(arg1)
        elif a1 in {"1","2","3"} and not a2: cup,token=int(a1),"100"
        if cup is None: return await self._usage(ctx,"🥤 Cups","!cups 1k 2","!cups 2 1k")
        result=await self._atomic_game(ctx,token,"cups",lambda bet:(lambda prize:{"payout":int(bet*2.85) if cup==prize else 0,"prize":prize})(secrets.choice([1,2,3])),min_bet=int(_cfg("cups_min_bet",10)))
        if result:
            bet,data=result; await ctx.send(f"🥤 Prize was under **{data['prize']}** — "+(f"✅ Won **{_fmt_cash(data['payout'])}**." if data['payout'] else f"❌ Lost **{_fmt_cash(bet)}**."))

    @commands.hybrid_command(name="keno", aliases=["numbers", "pick"])
    async def keno(self, ctx, arg1=None,arg2=None,arg3=None,arg4=None):
        _,profile=await self._profile(ctx); balance=int(profile.get("grams",0) or 0); tokens=[t for t in (arg1,arg2,arg3,arg4) if t]; picks=[]; bet_token=None
        for token in tokens:
            cleaned=_norm(token).rstrip(".!?,;:")
            if cleaned.isdigit() and 1<=int(cleaned)<=40: picks.append(int(cleaned))
            elif bet_token is None and _parse_bet(token,balance,min_bet=int(_cfg("keno_min_bet",100))) is not None: bet_token=str(token)
        picks=list(dict.fromkeys(picks))[:3]; bet_token=bet_token or "100"
        if not picks: return await self._usage(ctx,"🔢 Keno","!keno 1k 7","!keno 7 12 33 1k")
        def resolve(bet):
            drawn=random.sample(range(1,41),5); matches=len(set(picks)&set(drawn)); count=len(picks); mult=(6 if matches==1 else 0) if count==1 else (20 if matches==2 else 2 if matches==1 else 0) if count==2 else (80 if matches==3 else 5 if matches==2 else 1 if matches==1 else 0)
            return {"payout":int(bet*mult),"drawn":drawn,"matches":matches}
        result=await self._atomic_game(ctx,bet_token,"keno",resolve,min_bet=int(_cfg("keno_min_bet",100)))
        if result:
            bet,data=result; await ctx.send(f"🔢 Picks: **{', '.join(map(str,picks))}** | Draw: **{', '.join(map(str,sorted(data['drawn'])))}**\n"+(f"✅ Returned **{_fmt_cash(data['payout'])}**." if data['payout'] else f"❌ Lost **{_fmt_cash(bet)}**."))

    @commands.hybrid_command(name="crash", aliases=["rocket"])
    async def crash(self, ctx, bet: str="100", cashout: float=2.0):
        cashout=max(1.1,min(50.0,float(cashout)))
        def resolve(wager):
            point=round(max(1.0,(1-float(_cfg("crash_house_edge",.03)))/max(1e-9,1-random.random())),2)
            return {"payout":int(wager*cashout) if cashout<=point else 0,"point":point}
        result=await self._atomic_game(ctx,bet,"crash",resolve,min_bet=int(_cfg("crash_min_bet",10)))
        if result:
            wager,data=result; await ctx.send(f"🚀 Crashed at **{data['point']}x**. "+(f"✅ Cashed out **{_fmt_cash(data['payout'])}**." if data['payout'] else f"❌ Lost **{_fmt_cash(wager)}**."))

    _WHEEL=[(0.0,8),(.5,10),(1.0,14),(1.5,10),(2.0,7),(3.0,4),(5.0,2),(10.0,1)]
    @commands.hybrid_command(name="wheel", aliases=["spin"])
    async def wheel(self, ctx, bet: str="100"):
        def resolve(wager):
            mult=random.choice([m for m,w in self._WHEEL for _ in range(w)]); return {"payout":int(wager*mult),"mult":mult}
        result=await self._atomic_game(ctx,bet,"wheel",resolve,min_bet=int(_cfg("wheel_min_bet",10)))
        if result:
            wager,data=result; await ctx.send(f"🎡 Wheel hit **{data['mult']}x** — "+(f"returned **{_fmt_cash(data['payout'])}**." if data['payout'] else f"lost **{_fmt_cash(wager)}**."))

    @commands.hybrid_command(name="blackjack", aliases=["bj"])
    async def blackjack(self, ctx, bet: str="200"):
        guild_id=require_guild_id(ctx)
        scope=await resolve_game_scope(self.bot.db,guild_id,ctx.author.id)
        async with self.bot.db.lock:
            profile=await self.bot.db.get_profile(scope.scope_id,ctx.author.id)
            if await jail_guard(ctx,profile,"gamble"): return
            wager=_parse_bet(bet,int(profile.get("grams",0) or 0),min_bet=int(_cfg("blackjack_min_bet",200)))
            if wager is None: return await ctx.send("❌ Invalid bet or insufficient funds.")
            profile["grams"]-=wager; self.bot.db.mark_profile_dirty(scope.scope_id,ctx.author.id)
        deck=[2,3,4,5,6,7,8,9,10,"J","Q","K","A"]*4; random.shuffle(deck); player=[deck.pop(),deck.pop()]; dealer=[deck.pop(),deck.pop()]
        view=BlackjackView(self,ctx,scope.scope_id,ctx.author.id,wager,deck,player,dealer)
        if view.value(player) == 21:
            result = "tie" if view.value(dealer) == 21 else "win"
            payout = wager if result == "tie" else int(wager * 2.5)
            async with self.bot.db.lock:
                profile = await self.bot.db.get_profile(scope.scope_id, ctx.author.id)
                profile["grams"] = int(profile.get("grams", 0) or 0) + payout
                update_gamble_stats(profile, "blackjack", payout - wager, wager)
                if result == "win":
                    _record_win(profile, ctx.author.id)
                self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)
            if result == "tie":
                await ctx.send("🃏 **PUSH!** Both have 21. Wager returned.")
            else:
                await ctx.send(f"🃏 **BLACKJACK!** Natural 21 — won **{_fmt_cash(payout)}**.")
            return
        embed=discord.Embed(title=f"🃏 Blackjack (Bet: {_fmt_cash(wager)})",color=discord.Color.blue()); embed.add_field(name="Your Hand",value=f"{view.cards(player)}\nValue: **{view.value(player)}**"); embed.add_field(name="Dealer Hand",value=f"[{dealer[0]}] [?]")
        view.message=await ctx.send(embed=embed,view=view)

    @commands.hybrid_command(name="roulette", aliases=["roul"])
    async def roulette(self, ctx, arg1=None,arg2=None):
        _,profile=await self._profile(ctx); balance=int(profile.get("grams",0) or 0); aliases={"r":"red","b":"black","o":"odd","e":"even","l":"low","h":"high","green":"0","zero":"0"}
        def choice(v):
            t=aliases.get(_norm(v).replace(" ",""),_norm(v).replace(" ","")); return t if t in {"red","black","odd","even","low","high","1st12","2nd12","3rd12","0"} or (t.isdigit() and 0<=int(t)<=36) else None
        c1,c2=choice(arg1),choice(arg2); b1=_parse_bet(arg1,balance,min_bet=int(_cfg("roulette_min_bet",10))); b2=_parse_bet(arg2,balance,min_bet=int(_cfg("roulette_min_bet",10)))
        if c1 and (b2 is not None or not arg2): selected,token=c1,str(arg2) if arg2 else "100"
        elif b1 is not None and c2: selected,token=c2,str(arg1)
        else: return await self._usage(ctx,"🎡 Roulette","!roulette red 1k","!roulette 500 17")
        def resolve(bet):
            n=random.randint(0,36); color="green" if n==0 else "red" if n%2 else "black"; won=(selected==color) if selected in {"red","black"} else n==0 if selected=="0" else (n!=0 and (n%2==1)==(selected=="odd")) if selected in {"odd","even"} else 1<=n<=18 if selected=="low" else 19<=n<=36 if selected=="high" else 1<=n<=12 if selected=="1st12" else 13<=n<=24 if selected=="2nd12" else 25<=n<=36 if selected=="3rd12" else n==int(selected)
            mult=36 if selected=="0" or selected.isdigit() else 3 if selected.endswith("12") else 2
            return {"payout":bet*mult if won else 0,"number":n,"color":color}
        result=await self._atomic_game(ctx,token,"roulette",resolve,min_bet=int(_cfg("roulette_min_bet",10)))
        if result:
            wager,data=result; await ctx.send(f"🎡 Landed **{data['number']} ({data['color'].upper()})** — "+(f"✅ Won **{_fmt_cash(data['payout'])}**." if data['payout'] else f"❌ Lost **{_fmt_cash(wager)}**."))


async def setup(bot):
    await bot.add_cog(Gambling(bot))
