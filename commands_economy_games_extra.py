# ============================================================
# COMMANDS_ECONOMY_GAMES_EXTRA.PY - BLACKJACK + CRASH + CORRIDA
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import time
from datetime import datetime
from typing import Dict, List

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager


def _card() -> str:
    suits = ["♠️", "♥️", "♦️", "♣️"]
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    return f"{random.choice(ranks)}{random.choice(suits)}"


def _card_value(card: str) -> int:
    rank = card[:-2]
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def _hand_value(hand: List[str]) -> int:
    total = sum(_card_value(c) for c in hand)
    aces = sum(1 for c in hand if c.startswith("A"))
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


class EconomyGamesExtra(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cd: Dict[str, float] = {}

    def _fmt(self, gid: int, amount: int) -> str:
        return EconomyManager.format_currency(gid, amount)

    def _check_cd(self, gid: int, uid: int, cmd: str, secs: float = 2.0) -> bool:
        key = f"{gid}:{uid}:{cmd}"
        now = time.time()
        if now - self._cd.get(key, 0) < secs:
            return True
        self._cd[key] = now
        if len(self._cd) > 2000:
            cutoff = now - 60
            for k in [k for k, v in self._cd.items() if v < cutoff]:
                del self._cd[k]
        return False

    # ============================================================
    # BLACKJACK
    # ============================================================

    @commands.command(name="blackjack", aliases=["bj"])
    async def blackjack(self, ctx, amount: int):
        if amount <= 0 or amount > 100_000:
            return await ctx.send(embed=embed_error("❌ Aposta: 1 a 100.000"))
        gid = ctx.guild.id
        uid = ctx.author.id
        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))
        if self._check_cd(gid, uid, "bj", 3):
            return await ctx.send(embed=embed_warning("⏳ Aguarde..."), delete_after=3)
        bal = EconomyManager.get_balance(gid, uid)
        if bal < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))

        if not EconomyManager.remove_balance(gid, uid, amount, "Blackjack", "bj"):
            return await ctx.send(embed=embed_error("❌ Falha."))

        player = [_card(), _card()]
        dealer = [_card(), _card()]
        pv = _hand_value(player)
        dv = _hand_value(dealer)

        if pv == 21:
            winnings = int(amount * 2.5)
            EconomyManager.add_balance(gid, uid, winnings, "Blackjack natural", "bj_win")
            return await ctx.send(embed=embed_success(
                f"🃏 **BLACKJACK NATURAL!**\n"
                f"Você: {' '.join(player)} ({pv})\n"
                f"💰 Prêmio: **{self._fmt(gid, winnings)}**"))

        embed = discord.Embed(
            title="🃏 BLACKJACK",
            description=f"**Sua mão:** {' '.join(player)} (**{pv}**)\n"
                        f"**Dealer mostra:** {dealer[0]}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Reaja: 🇭 = Hit | 🇸 = Stand")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("🇭")
        await msg.add_reaction("🇸")

        def check(reaction, user):
            return user.id == uid and str(reaction.emoji) in ("🇭", "🇸") and reaction.message.id == msg.id

        while pv < 21:
            try:
                reaction, _ = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
            except Exception:
                break
            if str(reaction.emoji) == "🇸":
                break
            player.append(_card())
            pv = _hand_value(player)
            embed.description = (f"**Sua mão:** {' '.join(player)} (**{pv}**)\n"
                                 f"**Dealer mostra:** {dealer[0]}")
            await msg.edit(embed=embed)
            if pv >= 21:
                break

        if pv > 21:
            return await msg.edit(embed=embed_error(
                f"💥 **BUST!** Você: {pv}\nPerdeu **{self._fmt(gid, amount)}**"))

        while dv < 17:
            dealer.append(_card())
            dv = _hand_value(dealer)

        if dv > 21 or pv > dv:
            winnings = amount * 2
            EconomyManager.add_balance(gid, uid, winnings, "Blackjack ganhou", "bj_win")
            await msg.edit(embed=embed_success(
                f"🏆 **VOCÊ GANHOU!**\n"
                f"Sua mão: {' '.join(player)} (**{pv}**)\n"
                f"Dealer: {' '.join(dealer)} (**{dv}**)\n"
                f"💰 Prêmio: **{self._fmt(gid, winnings)}**"))
        elif pv == dv:
            EconomyManager.add_balance(gid, uid, amount, "Empate blackjack", "bj_push")
            await msg.edit(embed=embed_info(
                f"🤝 **EMPATE!**\nVocê: {pv} | Dealer: {dv}\nValor devolvido."))
        else:
            await msg.edit(embed=embed_error(
                f"❌ **PERDEU!**\nVocê: {pv} | Dealer: {dv}\nPerdeu **{self._fmt(gid, amount)}**"))

    # ============================================================
    # CRASH
    # ============================================================

    @commands.command(name="crash")
    async def crash(self, ctx, amount: int, auto_cashout: float = 0):
        if amount <= 0 or amount > 100_000:
            return await ctx.send(embed=embed_error("❌ Aposta: 1 a 100.000"))
        gid = ctx.guild.id
        uid = ctx.author.id
        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))
        if self._check_cd(gid, uid, "crash", 3):
            return await ctx.send(embed=embed_warning("⏳ Aguarde..."), delete_after=3)
        bal = EconomyManager.get_balance(gid, uid)
        if bal < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))

        if not EconomyManager.remove_balance(gid, uid, amount, "Crash", "crash"):
            return await ctx.send(embed=embed_error("❌ Falha."))

        # Crash point
        r = random.random()
        crash_at = max(1.0, 1 / (1 - r * 0.97))

        current = 1.0
        embed = discord.Embed(
            title="📈 CRASH",
            description=f"Multiplicador: **x{current:.2f}**\n\nReaja 💰 para sacar!",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("💰")

        cashed = False
        def check(reaction, user):
            return user.id == uid and str(reaction.emoji) == "💰" and reaction.message.id == msg.id

        while current < crash_at and current < 100:
            await asyncio.sleep(0.8)
            current *= random.uniform(1.08, 1.35)

            if auto_cashout > 0 and current >= auto_cashout:
                cashed = True
                break

            try:
                await self.bot.wait_for("reaction_add", timeout=0.1, check=check)
                cashed = True
                break
            except Exception:
                pass

            embed.description = f"Multiplicador: **x{current:.2f}**\n\nReaja 💰 para sacar!"
            try:
                await msg.edit(embed=embed)
            except Exception:
                pass

        if cashed and current < crash_at:
            winnings = int(amount * current)
            EconomyManager.add_balance(gid, uid, winnings, f"Crash x{current:.2f}", "crash_win")
            await msg.edit(embed=embed_success(
                f"💰 **SACOU!** x{current:.2f}\nPrêmio: **{self._fmt(gid, winnings)}**"))
        else:
            await msg.edit(embed=embed_error(
                f"💥 **CRASHOU em x{crash_at:.2f}!**\nPerdeu **{self._fmt(gid, amount)}**"))

    # ============================================================
    # CORRIDA
    # ============================================================

    @commands.command(name="race", aliases=["corrida"])
    async def race(self, ctx, horse: int, amount: int):
        if horse < 1 or horse > 6:
            return await ctx.send(embed=embed_error("❌ Escolha 1 a 6."))
        if amount <= 0 or amount > 50_000:
            return await ctx.send(embed=embed_error("❌ Aposta: 1 a 50.000"))

        gid = ctx.guild.id
        uid = ctx.author.id
        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))
        if self._check_cd(gid, uid, "race", 3):
            return await ctx.send(embed=embed_warning("⏳ Aguarde..."), delete_after=3)
        bal = EconomyManager.get_balance(gid, uid)
        if bal < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))

        if not EconomyManager.remove_balance(gid, uid, amount, "Corrida", "race"):
            return await ctx.send(embed=embed_error("❌ Falha."))

        positions = [0] * 6
        winner = None
        goal = 30

        for _ in range(60):
            for i in range(6):
                positions[i] += random.randint(0, 4)
            if any(p >= goal for p in positions):
                winner = positions.index(max(positions)) + 1
                break

        if winner is None:
            winner = positions.index(max(positions)) + 1

        if winner == horse:
            winnings = amount * 4
            EconomyManager.add_balance(gid, uid, winnings, "Corrida ganha", "race_win")
            await ctx.send(embed=embed_success(
                f"🐎 **CAVALO {horse} VENCEU!**\n"
                f"💰 Prêmio: **{self._fmt(gid, winnings)}**"))
        else:
            await ctx.send(embed=embed_error(
                f"🐎 **Cavalo {winner} venceu.** Você apostou em {horse}.\n"
                f"Perdeu **{self._fmt(gid, amount)}**"))

    # ============================================================
    # RASPADINHA
    # ============================================================

    @commands.command(name="scratch", aliases=["raspadinha"])
    async def scratch(self, ctx):
        gid = ctx.guild.id
        uid = ctx.author.id
        cost = 50
        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))
        if not EconomyManager.remove_balance(gid, uid, cost, "Raspadinha", "scratch"):
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente (custa 50)."))

        grid = [random.choice(["💎", "⭐", "🔔", "🍒", "🍋", "💀"]) for _ in range(9)]

        # Regras
        if grid.count("💎") >= 3:
            win = 5000
        elif grid.count("⭐") >= 3:
            win = 1000
        elif grid.count("🔔") >= 4:
            win = 500
        elif grid.count("🍒") >= 4:
            win = 250
        elif grid.count("🍋") >= 4:
            win = 100
        else:
            win = 0

        if win > 0:
            EconomyManager.add_balance(gid, uid, win, "Raspadinha", "scratch_win")

        lines = " ".join(grid[0:3]) + "\n" + " ".join(grid[3:6]) + "\n" + " ".join(grid[6:9])
        embed = discord.Embed(
            title="🎟️ RASPADINHA",
            description=f"```\n{lines}\n```",
            color=discord.Color.gold() if win > 0 else discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        if win > 0:
            embed.add_field(name="🎉 PRÊMIO",
                            value=f"**{self._fmt(gid, win)}**")
        else:
            embed.add_field(name="😢 Sem prêmio", value="Tente novamente!")
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("EconomyGamesExtra") is None:
        await bot.add_cog(EconomyGamesExtra(bot))