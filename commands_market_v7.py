# ============================================================
# COMMANDS_MARKET_V7.PY - v7.0 Fase 4
# ============================================================
# Comandos do jogador:
#   • Order book (.book, .order, .cancelorder)
#   • Commodities (.commodities, .commodity)
#   • Futuros (.future, .futures, .closefuture)
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from market_engine import MarketEngine
from commodity_engine import CommodityEngine
from futures_engine import FuturesEngine
from utils import SlashCtxAdapter


class MarketV7Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # HELP
    # ============================================================

    @commands.command(name="trading", aliases=["trader", "bolsa_v7"])
    async def trading_help(self, ctx):
        embed = discord.Embed(
            title="📊 SISTEMA DE TRADING",
            description=(
                "**Order Book:**\n"
                "• `.book <symbol>` — ver o livro de ofertas\n"
                "• `.order buy/sell <symbol> <price> <qty>` — ordem limit\n"
                "• `.market buy/sell <symbol> <qty>` — ordem a mercado\n"
                "• `.myorders` — suas ordens abertas\n"
                "• `.cancelorder <id>` — cancelar\n\n"
                "**Commodities:**\n"
                "• `.commodities` — listar\n"
                "• `.commodity <symbol>` — detalhes + histórico\n\n"
                "**Futuros:**\n"
                "• `.future open <symbol> <dir> <qty> <lev> <horas>`\n"
                "• `.futures` — seus contratos\n"
                "• `.closefuture <id>` — fechar"
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await ctx.send(embed=embed)

    # ============================================================
    # ORDER BOOK
    # ============================================================

    @commands.command(name="book", aliases=["livro", "orderbook"])
    async def book(self, ctx, symbol: str):
        book = MarketEngine.get_order_book(ctx.guild.id, symbol, 8)
        if not book["bids"] and not book["asks"]:
            return await ctx.send(embed=embed_info(
                f"📖 Sem liquidez para **{symbol.upper()}**.\n"
                f"Seja o primeiro! `.order buy {symbol} 100 10`"
            ))

        embed = discord.Embed(
            title=f"📖 ORDER BOOK — {symbol.upper()}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )

        # Asks (vendedores) — do maior pro menor
        asks_lines = []
        for a in reversed(book["asks"]):
            asks_lines.append(f"🔴 `{a['price']:>10}` × `{a['quantity']:>6}`")
        embed.add_field(
            name="📤 ASK (vendedores)",
            value="\n".join(asks_lines) or "*vazio*",
            inline=True,
        )

        # Bids (compradores) — do maior pro menor
        bids_lines = []
        for b in book["bids"]:
            bids_lines.append(f"🟢 `{b['price']:>10}` × `{b['quantity']:>6}`")
        embed.add_field(
            name="📥 BID (compradores)",
            value="\n".join(bids_lines) or "*vazio*",
            inline=True,
        )

        # Spread
        if book["best_bid"] and book["best_ask"]:
            spread = book["best_ask"] - book["best_bid"]
            spread_pct = (spread / book["best_bid"]) * 100
            embed.add_field(
                name="📊 Spread",
                value=f"**{spread}** ({spread_pct:.2f}%)",
                inline=False,
            )

        embed.add_field(
            name="💡 Último preço",
            value=self._fmt(ctx.guild.id, MarketEngine.get_spot_price(ctx.guild.id, symbol)),
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="order", aliases=["ordem"])
    async def order(self, ctx, side: str, symbol: str, price: int, quantity: int):
        gid = ctx.guild.id
        uid = ctx.author.id

        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))

        result = MarketEngine.place_limit_order(gid, uid, symbol, side, price, quantity)

        if "error" in result:
            errors = {
                "disabled": "Mercado desativado.",
                "invalid_side": "Lado inválido (use buy/sell).",
                "quantity_too_low": "Quantidade muito baixa.",
                "quantity_too_high": "Quantidade muito alta.",
                "invalid_price": "Preço inválido.",
                "too_many_orders": "Muitas ordens abertas.",
                "insufficient_balance": f"Saldo insuficiente. Precisa de {self._fmt(gid, result.get('needed', 0))}.",
                "insufficient_holdings": f"Você não tem o ativo suficiente. Possui {result.get('have', 0)}.",
            }
            return await ctx.send(embed=embed_error(f"❌ {errors.get(result['error'], result['error'])}"))

        await ctx.send(embed=embed_success(
            f"✅ Ordem **{result['side'].upper()}** criada!\n"
            f"🆔 `{result['order_id'][:8]}`\n"
            f"📊 {result['quantity']}x {symbol.upper()} @ {self._fmt(gid, result['price'])}"
        ))

    @commands.command(name="marketorder", aliases=["ordemmercado"])
    async def market_order(self, ctx, side: str, symbol: str, quantity: int):
        gid = ctx.guild.id
        uid = ctx.author.id

        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))

        result = MarketEngine.place_market_order(gid, uid, symbol, side, quantity)

        if "error" in result:
            if result["error"] == "no_liquidity":
                return await ctx.send(embed=embed_error(
                    "❌ Sem liquidez no livro. Tente uma ordem limit."
                ))
            return await ctx.send(embed=embed_error(f"❌ {result['error']}"))

        await ctx.send(embed=embed_success(
            f"⚡ Ordem a mercado executada!\n"
            f"📊 {result['quantity']}x {symbol.upper()} @ {self._fmt(gid, result['price'])}"
        ))

    @commands.command(name="myorders", aliases=["minhasordens"])
    async def my_orders(self, ctx):
        orders = MarketEngine.get_user_orders(ctx.guild.id, ctx.author.id)
        if not orders:
            return await ctx.send(embed=embed_info("📋 Você não tem ordens abertas."))

        embed = discord.Embed(
            title="📋 Suas ordens",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        for o in orders[:15]:
            side_emoji = "🟢" if o["side"] == "buy" else "🔴"
            remaining = int(o["quantity"]) - int(o.get("filled", 0))
            embed.add_field(
                name=f"{side_emoji} `{str(o['_id'])[:8]}` — {o['symbol']}",
                value=(
                    f"{o['side'].upper()} {remaining}x @ "
                    f"{self._fmt(ctx.guild.id, int(o['price']))}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="cancelorder", aliases=["cancelarordem"])
    async def cancel_order(self, ctx, order_id: str):
        result = MarketEngine.cancel_order(ctx.guild.id, ctx.author.id, order_id)
        if "error" in result:
            return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
        await ctx.send(embed=embed_success(
            f"✅ Ordem cancelada. **{result['cancelled']}** unidades liberadas."
        ))

    # ============================================================
    # COMMODITIES
    # ============================================================

    @commands.command(name="commodities", aliases=["commodity_list"])
    async def commodities(self, ctx):
        CommodityEngine.ensure_commodities(ctx.guild.id)
        commodities = CommodityEngine.list_commodities(ctx.guild.id)
        if not commodities:
            return await ctx.send(embed=embed_info("📋 Nenhuma commodity registrada."))

        embed = discord.Embed(
            title="🏭 COMMODITIES",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        for c in commodities:
            embed.add_field(
                name=f"{c.get('emoji', '📦')} {c.get('name', '?')} ({c['symbol']})",
                value=(
                    f"💵 {self._fmt(ctx.guild.id, int(c.get('price', 0)))}\n"
                    f"📦 Estoque: {int(c.get('stock', 0)):,} {c.get('unit', '')}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="commodity", aliases=["comm"])
    async def commodity_info(self, ctx, symbol: str):
        c = CommodityEngine.get_commodity(ctx.guild.id, symbol)
        if not c:
            return await ctx.send(embed=embed_error(f"❌ Commodity `{symbol}` não encontrada."))

        embed = discord.Embed(
            title=f"{c.get('emoji', '📦')} {c.get('name')} ({c['symbol']})",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💵 Preço", value=self._fmt(ctx.guild.id, int(c.get('price', 0))), inline=True)
        embed.add_field(name="📊 Base", value=self._fmt(ctx.guild.id, int(c.get('base_price', 0))), inline=True)
        embed.add_field(name="📦 Estoque", value=f"{int(c.get('stock', 0)):,} {c.get('unit', '')}", inline=True)
        await ctx.send(embed=embed)

    # ============================================================
    # FUTUROS
    # ============================================================

    @commands.command(name="future", aliases=["futuro"])
    async def future(self, ctx, action: str = None, symbol: str = None,
                     direction: str = None, quantity: int = 0,
                     leverage: int = 5, hours: int = 24):
        gid = ctx.guild.id
        uid = ctx.author.id

        if action is None:
            return await ctx.send(embed=embed_info(
                "Uso: `.future open <symbol> <long/short> <qty> <lev> <horas>`\n"
                "Durações: 24, 72, 168, 720"
            ))

        if action.lower() == "open":
            if not symbol or not direction or quantity <= 0:
                return await ctx.send(embed=embed_error(
                    "❌ Uso: `.future open <symbol> <long/short> <qty> <lev> <horas>`"
                ))

            if EconomyManager.is_frozen(gid, uid):
                return await ctx.send(embed=embed_error("❌ Economia congelada."))

            result = FuturesEngine.open_contract(
                gid, uid, symbol, direction, quantity, leverage, hours
            )

            if "error" in result:
                errors = {
                    "disabled": "Futuros desativados.",
                    "invalid_direction": "Direção inválida (long/short).",
                    "invalid_leverage": f"Alavancagem inválida ({result.get('min')}-{result.get('max')}).",
                    "invalid_duration": f"Duração inválida. Use: {result.get('allowed')}",
                    "no_price": "Sem preço disponível.",
                    "too_many_contracts": "Muitos contratos abertos.",
                    "insufficient_margin": f"Margem insuficiente. Precisa de {self._fmt(gid, result.get('needed', 0))}.",
                }
                return await ctx.send(embed=embed_error(f"❌ {errors.get(result['error'], result['error'])}"))

            embed = discord.Embed(
                title="📈 CONTRATO FUTURO ABERTO",
                color=discord.Color.green() if result['direction'] == 'long' else discord.Color.red(),
                timestamp=datetime.utcnow(),
            )
            embed.add_field(name="🆔 ID", value=f"`{result['contract_id'][:8]}`", inline=True)
            embed.add_field(name="📊", value=f"{result['symbol']} {result['direction'].upper()}", inline=True)
            embed.add_field(name="⚖️ Alavancagem", value=f"{result['leverage']}x", inline=True)
            embed.add_field(name="💰 Entrada", value=self._fmt(gid, result['entry']), inline=True)
            embed.add_field(name="💵 Margem", value=self._fmt(gid, result['margin']), inline=True)
            embed.add_field(name="🔴 Liquidação", value=self._fmt(gid, result['liquidation_price']), inline=True)
            embed.add_field(name="⏰ Expira", value=f"<t:{int(result['expires_at'].timestamp())}:R>", inline=False)
            return await ctx.send(embed=embed)

        await ctx.send(embed=embed_error("❌ Ação inválida. Use `open`."))

    @commands.command(name="futures", aliases=["meusfuturos"])
    async def futures(self, ctx):
        contracts = FuturesEngine.get_user_contracts(ctx.guild.id, ctx.author.id)
        if not contracts:
            return await ctx.send(embed=embed_info("📋 Você não tem contratos abertos."))

        embed = discord.Embed(
            title="📊 Seus contratos futuros",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )

        from market_engine import MarketEngine
        from commodity_engine import CommodityEngine

        for c in contracts:
            spot = MarketEngine.get_spot_price(ctx.guild.id, c["symbol"])
            if spot <= 0:
                spot = CommodityEngine.get_price(ctx.guild.id, c["symbol"])

            entry = int(c["entry_price"])
            qty = int(c["quantity"])
            direction = c["direction"]

            if direction == "long":
                pnl = (spot - entry) * qty
            else:
                pnl = (entry - spot) * qty

            pnl_emoji = "🟢" if pnl >= 0 else "🔴"

            embed.add_field(
                name=f"{pnl_emoji} `{str(c['_id'])[:8]}` — {c['symbol']} {direction.upper()}",
                value=(
                    f"📈 Entrada: {self._fmt(ctx.guild.id, entry)}\n"
                    f"💵 Atual: {self._fmt(ctx.guild.id, spot)}\n"
                    f"📊 PnL: **{self._fmt(ctx.guild.id, pnl)}**\n"
                    f"⚖️ {c['leverage']}x | ⏰ <t:{int(c['expires_at'].timestamp())}:R>"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="closefuture", aliases=["fecharfuturo"])
    async def close_future(self, ctx, contract_id: str):
        result = FuturesEngine.close_contract(ctx.guild.id, ctx.author.id, contract_id, "manual")
        if "error" in result:
            return await ctx.send(embed=embed_error(f"❌ {result['error']}"))

        pnl = result["pnl"]
        emoji = "🟢" if pnl >= 0 else "🔴"
        await ctx.send(embed=embed_success(
            f"{emoji} Contrato fechado!\n"
            f"📊 Saída: {self._fmt(ctx.guild.id, result['exit_price'])}\n"
            f"💰 PnL: **{self._fmt(ctx.guild.id, pnl)}**\n"
            f"💵 Payout: {self._fmt(ctx.guild.id, result['payout'])}"
        ))


async def setup(bot):
    if bot.get_cog("MarketV7Commands") is None:
        await bot.add_cog(MarketV7Commands(bot))