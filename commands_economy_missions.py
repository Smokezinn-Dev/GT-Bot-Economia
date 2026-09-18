# ============================================================
# COMMANDS_ECONOMY_MISSIONS.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands
import random
from datetime import datetime, timedelta
from typing import List, Dict

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager

MISSION_POOL = [
    {"key": "msg_20", "desc": "Envie 20 mensagens no chat", "type": "messages", "target": 20, "reward": 150},
    {"key": "msg_50", "desc": "Envie 50 mensagens no chat", "type": "messages", "target": 50, "reward": 400},
    {"key": "flip_3", "desc": "Jogue 3 vezes no flip", "type": "flip", "target": 3, "reward": 200},
    {"key": "gamble_5", "desc": "Faça 5 apostas (qualquer tipo)", "type": "gamble", "target": 5, "reward": 300},
    {"key": "pay_1", "desc": "Faça 1 transferência", "type": "pay", "target": 1, "reward": 100},
    {"key": "daily_1", "desc": "Colete seu daily", "type": "daily", "target": 1, "reward": 100},
    {"key": "invest_1", "desc": "Faça 1 investimento", "type": "invest", "target": 1, "reward": 250},
]


class EconomyMissions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _today(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _get_or_create(self, guild_id: int, user_id: int) -> dict:
        db = get_connection()
        today = self._today()
        doc = db["missions_daily"].find_one({
            "guild_id": guild_id, "user_id": user_id, "date": today})
        if doc:
            return doc

        picks = random.sample(MISSION_POOL, 3)
        missions = [{**m, "progress": 0, "claimed": False} for m in picks]
        expires = datetime.utcnow() + timedelta(days=2)
        db["missions_daily"].insert_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "date": today,
            "missions": missions,
            "expires_at": expires,
            "created_at": datetime.utcnow()
        })
        return db["missions_daily"].find_one({
            "guild_id": guild_id, "user_id": user_id, "date": today})

    def track(self, guild_id: int, user_id: int, kind: str, amount: int = 1):
        db = get_connection()
        today = self._today()
        doc = db["missions_daily"].find_one({
            "guild_id": guild_id, "user_id": user_id, "date": today})
        if not doc:
            return
        for i, m in enumerate(doc["missions"]):
            if m["type"] == kind and not m["claimed"]:
                new_prog = min(m["target"], m["progress"] + amount)
                db["missions_daily"].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {f"missions.{i}.progress": new_prog}}
                )

    @commands.command(name="missions", aliases=["missoes"])
    async def missions(self, ctx):
        doc = self._get_or_create(ctx.guild.id, ctx.author.id)
        embed = discord.Embed(
            title="📅 MISSÕES DIÁRIAS",
            description="Você tem **3 missões** hoje. Complete e resgate!",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        for i, m in enumerate(doc["missions"]):
            prog = m["progress"]
            target = m["target"]
            pct = int((prog / target) * 100) if target else 0
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            status = "✅" if m.get("claimed") else "🎯"
            embed.add_field(
                name=f"{status} {m['desc']}",
                value=f"`{bar}` {prog}/{target}\n💰 {EconomyManager.format_currency(ctx.guild.id, m['reward'])}",
                inline=False
            )
        embed.set_footer(text=f"Use .missionsclaim <número> para resgatar")
        await ctx.send(embed=embed)

    @commands.command(name="missionsclaim", aliases=["resgatar"])
    async def missions_claim(self, ctx, mission_num: int):
        if mission_num < 1 or mission_num > 3:
            return await ctx.send(embed=embed_error("❌ Use 1, 2 ou 3."))
        doc = self._get_or_create(ctx.guild.id, ctx.author.id)
        idx = mission_num - 1
        m = doc["missions"][idx]
        if m.get("claimed"):
            return await ctx.send(embed=embed_error("❌ Missão já resgatada."))
        if m["progress"] < m["target"]:
            return await ctx.send(embed=embed_error(
                f"❌ Progresso: {m['progress']}/{m['target']}"))
        EconomyManager.add_balance(ctx.guild.id, ctx.author.id, m["reward"],
                                    f"Missão: {m['desc']}", "mission")
        db = get_connection()
        db["missions_daily"].update_one(
            {"_id": doc["_id"]},
            {"$set": {f"missions.{idx}.claimed": True}}
        )
        await ctx.send(embed=embed_success(
            f"✅ Resgatou **{EconomyManager.format_currency(ctx.guild.id, m['reward'])}**!"))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        # ✅ Ignora comandos com prefixo . e slash
        if message.content.startswith((".", "/")):
            return
        self.track(message.guild.id, message.author.id, "messages")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if not ctx.guild:
            return
        name = ctx.command.name if ctx.command else ""
        if name == "daily":
            self.track(ctx.guild.id, ctx.author.id, "daily")
        elif name == "pay":
            self.track(ctx.guild.id, ctx.author.id, "pay")
        elif name == "invest":
            self.track(ctx.guild.id, ctx.author.id, "invest")
        elif name == "flip":
            self.track(ctx.guild.id, ctx.author.id, "flip")
        elif name in ("rollgamble", "roulette", "slots"):
            self.track(ctx.guild.id, ctx.author.id, "gamble")


async def setup(bot):
    if bot.get_cog("EconomyMissions") is None:
        await bot.add_cog(EconomyMissions(bot))