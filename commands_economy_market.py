# ============================================================
# COMMANDS_ECONOMY_MARKET.PY - BOLSA E PORTFÓLIO
# ============================================================

import discord
from discord.ext import commands
import random
from datetime import datetime
from typing import Optional

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager


class EconomyMarket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    @commands.command(name="market", aliases=["bolsa"])
    async def market(self, ctx, action: str = None, symbol: str = None, quantity: int = 1):
        db = get_connection()
        gid = ctx.guild.id

        if action is None:
            stocks = list(db["market_stocks"].find({"guild_id": gid}).sort("symbol", 1))
            if not stocks:
                return await ctx.send(embed=embed_info(
                    "📈 Nenhuma ação registrada.\n"
                    "Admin: `>market create <SYM> <nome> <preço>`"))
            embed = discord.Embed(title="📈 MERCADO DE AÇÕES",
                                  color=discord.Color.green(),
                                  timestamp=datetime.utcnow())
            for s in stocks:
                change = random.uniform(-3, 3)
                arrow = "🟢" if change > 0 else "🔴"
                embed.add_field(
                    name=f"{arrow} {s['symbol']} — {s['name']}",
                    value=f"💵 {self._fmt(gid, int(s['price']))} ({change:+.1f}%)",
                    inline=True
                )
            embed.set_footer(text="Use >market buy <SYM> <qtd> ou >portfolio")
            return await ctx.send(embed=embed)

        if action == "create" and symbol and quantity:
            if not ctx.author.guild_permissions.administrator:
                return await ctx.send(embed=embed_error("❌ Só admin."))
            if db["market_stocks"].find_one({"guild_id": gid, "symbol": symbol.upper()}):
                return await ctx.send(embed=embed_error("❌ Símbolo já existe."))
            name = f"Empresa {symbol}"
            db["market_stocks"].insert_one({
                "guild_id": gid,
                "symbol": symbol.upper(),
                "name": name,
                "price": int(quantity),
                "history": [int(quantity)],
                "created_at": datetime.utcnow()
            })
            return await ctx.send(embed=embed_success(f"✅ Ação **{symbol.upper()}** criada!"))

        if action == "buy" and symbol:
            if quantity <= 0:
                return await ctx.send(embed=embed_error("❌ Quantidade inválida."))
            stock = db["market_stocks"].find_one({"guild_id": gid, "symbol": symbol.upper()})
            if not stock:
                return await ctx.send(embed=embed_error("❌ Ação não existe."))
            cost = int(stock["price"]) * quantity
            if not EconomyManager.remove_balance(gid, ctx.author.id, cost,
                                                  f"Compra {quantity}x {symbol.upper()}", "market"):
                return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))
            db["market_portfolio"].update_one(
                {"guild_id": gid, "user_id": ctx.author.id, "symbol": symbol.upper()},
                {"$inc": {"quantity": quantity},
                 "$set": {"avg_price": int(stock["price"])}},
                upsert=True
            )
            return await ctx.send(embed=embed_success(
                f"✅ Comprou **{quantity}x {symbol.upper()}** por {self._fmt(gid, cost)}!"))

        if action == "sell" and symbol:
            stock = db["market_stocks"].find_one({"guild_id": gid, "symbol": symbol.upper()})
            if not stock:
                return await ctx.send(embed=embed_error("❌ Ação não existe."))
            port = db["market_portfolio"].find_one({
                "guild_id": gid, "user_id": ctx.author.id, "symbol": symbol.upper()})
            if not port or port.get("quantity", 0) < quantity:
                return await ctx.send(embed=embed_error("❌ Você não tem essa quantidade."))
            revenue = int(stock["price"]) * quantity
            db["market_portfolio"].update_one(
                {"_id": port["_id"]}, {"$inc": {"quantity": -quantity}})
            EconomyManager.add_balance(gid, ctx.author.id, revenue,
                                        f"Venda {quantity}x {symbol.upper()}", "market_sell")
            return await ctx.send(embed=embed_success(
                f"✅ Vendeu **{quantity}x {symbol.upper()}** por {self._fmt(gid, revenue)}!"))

        await ctx.send(embed=embed_error(
            "❌ Uso: `>market` | `>market buy <SYM> <qtd>` | `>market sell <SYM> <qtd>`"))

    @commands.command(name="portfolio", aliases=["carteira"])
    async def portfolio(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        db = get_connection()
        gid = ctx.guild.id
        docs = list(db["market_portfolio"].find({
            "guild_id": gid, "user_id": member.id, "quantity": {"$gt": 0}}))
        if not docs:
            return await ctx.send(embed=embed_info(f"📊 {member.mention} não tem ações."))

        embed = discord.Embed(title=f"📊 Portfólio de {member.display_name}",
                              color=discord.Color.green(),
                              timestamp=datetime.utcnow())
        total = 0
        for p in docs:
            stock = db["market_stocks"].find_one({"guild_id": gid, "symbol": p["symbol"]})
            if not stock:
                continue
            val = int(stock["price"]) * p["quantity"]
            total += val
            embed.add_field(
                name=f"{p['symbol']} ({p['quantity']}x)",
                value=f"💵 {self._fmt(gid, val)}",
                inline=True
            )
        embed.add_field(name="💰 Total", value=self._fmt(gid, total), inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("EconomyMarket") is None:
        await bot.add_cog(EconomyMarket(bot))