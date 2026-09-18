# ============================================================
# COMMANDS_ECONOMY_SOCIAL.PY - GUILDAS + CASAMENTO + PVP
# ============================================================

import discord
from discord.ext import commands
import random
from datetime import datetime
from typing import Optional

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager


class EconomySocial(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # GUILDAS
    # ============================================================

    @commands.command(name="guild", aliases=["guilda"])
    async def guild(self, ctx, action: str = None, *, args: str = None):
        db = get_connection()
        gid = ctx.guild.id

        # Sem ação → info da guild do usuário
        if action is None:
            my = db["guilds_members"].find_one({"guild_id": gid, "user_id": ctx.author.id})
            if not my:
                return await ctx.send(embed=embed_info(
                    "🏢 Você não está em uma guilda.\n"
                    "Use: `>guild create <nome>` ou `>guild join <nome>`"))

            guild = db["guilds_social"].find_one({"_id": my["guild_ref"], "guild_id": gid})
            if not guild:
                return await ctx.send(embed=embed_error("❌ Guilda não encontrada."))

            members = list(db["guilds_members"].find(
                {"guild_id": gid, "guild_ref": guild["_id"]}))
            embed = discord.Embed(title=f"🏢 {guild['name']}",
                                  color=discord.Color.gold(),
                                  timestamp=datetime.utcnow())
            embed.add_field(name="👑 Líder", value=f"<@{guild['leader_id']}>", inline=True)
            embed.add_field(name="👥 Membros", value=str(len(members)), inline=True)
            embed.add_field(name="💰 Cofre",
                            value=self._fmt(gid, int(guild.get("vault", 0))), inline=True)
            return await ctx.send(embed=embed)

        if action == "create" and args:
            if db["guilds_members"].find_one({"guild_id": gid, "user_id": ctx.author.id}):
                return await ctx.send(embed=embed_error("❌ Você já está em uma guilda."))
            if db["guilds_social"].find_one({"guild_id": gid, "name": args}):
                return await ctx.send(embed=embed_error("❌ Nome já usado."))

            cost = 5000
            bal = EconomyManager.get_balance(gid, ctx.author.id)
            if bal < cost:
                return await ctx.send(embed=embed_error(
                    f"❌ Precisa de {self._fmt(gid, cost)} para criar uma guilda."))

            EconomyManager.remove_balance(gid, ctx.author.id, cost,
                                           "Criação de guilda", "guild_create")
            r = db["guilds_social"].insert_one({
                "guild_id": gid,
                "name": args,
                "leader_id": ctx.author.id,
                "vault": 0,
                "created_at": datetime.utcnow()
            })
            db["guilds_members"].insert_one({
                "guild_id": gid,
                "user_id": ctx.author.id,
                "guild_ref": r.inserted_id,
                "joined_at": datetime.utcnow()
            })
            return await ctx.send(embed=embed_success(f"✅ Guilda **{args}** criada!"))

        if action == "join" and args:
            if db["guilds_members"].find_one({"guild_id": gid, "user_id": ctx.author.id}):
                return await ctx.send(embed=embed_error("❌ Você já está em uma guilda."))
            guild = db["guilds_social"].find_one({"guild_id": gid, "name": args})
            if not guild:
                return await ctx.send(embed=embed_error("❌ Guilda não existe."))
            members = db["guilds_members"].count_documents(
                {"guild_id": gid, "guild_ref": guild["_id"]})
            if members >= 10:
                return await ctx.send(embed=embed_error("❌ Guilda cheia (máx 10)."))

            db["guilds_members"].insert_one({
                "guild_id": gid,
                "user_id": ctx.author.id,
                "guild_ref": guild["_id"],
                "joined_at": datetime.utcnow()
            })
            return await ctx.send(embed=embed_success(f"✅ Você entrou na guilda **{args}**!"))

        if action == "leave":
            my = db["guilds_members"].find_one({"guild_id": gid, "user_id": ctx.author.id})
            if not my:
                return await ctx.send(embed=embed_error("❌ Você não está em uma guilda."))
            guild = db["guilds_social"].find_one({"_id": my["guild_ref"]})
            if guild and guild["leader_id"] == ctx.author.id:
                # Transfere liderança
                other = db["guilds_members"].find_one({
                    "guild_id": gid, "guild_ref": guild["_id"],
                    "user_id": {"$ne": ctx.author.id}
                })
                if other:
                    db["guilds_social"].update_one(
                        {"_id": guild["_id"]},
                        {"$set": {"leader_id": other["user_id"]}})
                else:
                    # Guilda extinta
                    db["guilds_social"].delete_one({"_id": guild["_id"]})
            db["guilds_members"].delete_one({"guild_id": gid, "user_id": ctx.author.id})
            return await ctx.send(embed=embed_success("✅ Você saiu da guilda."))

        if action == "deposit" and args:
            my = db["guilds_members"].find_one({"guild_id": gid, "user_id": ctx.author.id})
            if not my:
                return await ctx.send(embed=embed_error("❌ Você não está em uma guilda."))
            try:
                amount = int(args)
            except Exception:
                return await ctx.send(embed=embed_error("❌ Valor inválido."))
            if not EconomyManager.remove_balance(gid, ctx.author.id, amount,
                                                  "Depósito guilda", "guild_dep"):
                return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))
            db["guilds_social"].update_one(
                {"_id": my["guild_ref"]}, {"$inc": {"vault": amount}})
            return await ctx.send(embed=embed_success(
                f"✅ Depositado {self._fmt(gid, amount)} na guilda."))

        if action == "list":
            guilds = list(db["guilds_social"].find({"guild_id": gid}).limit(15))
            if not guilds:
                return await ctx.send(embed=embed_info("📋 Nenhuma guilda ainda."))
            embed = discord.Embed(title="🏢 GUILDAS DO SERVIDOR",
                                  color=discord.Color.gold(),
                                  timestamp=datetime.utcnow())
            for gu in guilds:
                members = db["guilds_members"].count_documents(
                    {"guild_id": gid, "guild_ref": gu["_id"]})
                embed.add_field(
                    name=f"**{gu['name']}**",
                    value=f"👑 <@{gu['leader_id']}> | 👥 {members} | 💰 {self._fmt(gid, gu.get('vault', 0))}",
                    inline=False
                )
            return await ctx.send(embed=embed)

        await ctx.send(embed=embed_error(
            "❌ Uso: `>guild` | `>guild create <nome>` | `>guild join <nome>` | "
            "`>guild leave` | `>guild deposit <valor>` | `>guild list`"))

    # ============================================================
    # CASAMENTO
    # ============================================================

    @commands.command(name="marry", aliases=["casar"])
    async def marry(self, ctx, member: discord.Member):
        if member.id == ctx.author.id or member.bot:
            return await ctx.send(embed=embed_error("❌ Inválido."))
        db = get_connection()
        gid = ctx.guild.id

        existing = db["marriages"].find_one({
            "guild_id": gid,
            "$or": [{"user_a": ctx.author.id}, {"user_b": ctx.author.id}]
        })
        if existing:
            return await ctx.send(embed=embed_error("❌ Você já é casado(a)!"))

        existing_b = db["marriages"].find_one({
            "guild_id": gid,
            "$or": [{"user_a": member.id}, {"user_b": member.id}]
        })
        if existing_b:
            return await ctx.send(embed=embed_error(f"❌ {member.mention} já é casado(a)!"))

        db["marriages"].insert_one({
            "guild_id": gid,
            "user_a": ctx.author.id,
            "user_b": member.id,
            "married_at": datetime.utcnow()
        })
        embed = discord.Embed(
            title="💍 CASAMENTO!",
            description=f"{ctx.author.mention} 💖 {member.mention}",
            color=discord.Color.pink(),
            timestamp=datetime.utcnow()
        )
        await ctx.send(embed=embed)

    @commands.command(name="divorce", aliases=["divorciar"])
    async def divorce(self, ctx):
        db = get_connection()
        result = db["marriages"].delete_one({
            "guild_id": ctx.guild.id,
            "$or": [{"user_a": ctx.author.id}, {"user_b": ctx.author.id}]
        })
        if result.deleted_count > 0:
            await ctx.send(embed=embed_warning("💔 Divórcio efetuado."))
        else:
            await ctx.send(embed=embed_error("❌ Você não é casado(a)."))

    # ============================================================
    # PVP
    # ============================================================

    @commands.command(name="pvp", aliases=["duelo"])
    async def pvp(self, ctx, member: discord.Member, amount: int):
        if member.id == ctx.author.id or member.bot:
            return await ctx.send(embed=embed_error("❌ Inválido."))
        if amount <= 0:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo."))

        gid = ctx.guild.id
        bal_a = EconomyManager.get_balance(gid, ctx.author.id)
        bal_b = EconomyManager.get_balance(gid, member.id)
        if bal_a < amount:
            return await ctx.send(embed=embed_error("❌ Você não tem saldo suficiente."))
        if bal_b < amount:
            return await ctx.send(embed=embed_error(f"❌ {member.mention} não tem saldo."))

        embed = discord.Embed(
            title="⚔️ DESAFIO PVP",
            description=f"{ctx.author.mention} desafiou {member.mention}!\n"
                        f"💰 Valor: **{self._fmt(gid, amount)}**\n\n"
                        f"{member.mention}, reaja com ✅ para aceitar (30s).",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")

        def check(reaction, user):
            return user.id == member.id and str(reaction.emoji) == "✅" and reaction.message.id == msg.id

        try:
            await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
        except Exception:
            return await ctx.send(embed=embed_info("❌ Desafio expirado."))

        # Cobra ambos
        if not EconomyManager.remove_balance(gid, ctx.author.id, amount, "PvP", "pvp"):
            return await ctx.send(embed=embed_error("❌ Falha."))
        if not EconomyManager.remove_balance(gid, member.id, amount, "PvP", "pvp"):
            EconomyManager.add_balance(gid, ctx.author.id, amount, "Reembolso PvP", "pvp_refund")
            return await ctx.send(embed=embed_error("❌ Falha."))

        winner = random.choice([ctx.author, member])
        prize = amount * 2
        EconomyManager.add_balance(gid, winner.id, prize, "PvP Vitória", "pvp_win")

        db = get_connection()
        db["pvp_bets"].insert_one({
            "guild_id": gid,
            "challenger": ctx.author.id,
            "opponent": member.id,
            "amount": amount,
            "winner": winner.id,
            "created_at": datetime.utcnow()
        })

        embed = discord.Embed(
            title="⚔️ RESULTADO PVP",
            description=f"🏆 Vencedor: {winner.mention}\n💰 Prêmio: **{self._fmt(gid, prize)}**",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("EconomySocial") is None:
        await bot.add_cog(EconomySocial(bot))