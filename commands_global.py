# ============================================================
# COMMANDS_GLOBAL.PY - v7.0 Fase 6
# ============================================================
# Comandos globais:
#   • .fx — câmbio entre guilds
#   • .currency — moeda da guild
#   • .trade — importar/exportar
#   • .treaty — tratados
#   • .global — ranking global
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from currency_engine import CurrencyEngine
from trade_engine import TradeEngine
from diplomacy_engine import DiplomacyEngine, TREATY_TYPES
from utils import SlashCtxAdapter


class GlobalCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # HELP
    # ============================================================

    @commands.command(name="global", aliases=["mundial"])
    async def global_help(self, ctx):
        embed = discord.Embed(
            title="🌍 SISTEMA GLOBAL",
            description=(
                "**Câmbio:**\n"
                "• `.fx` — taxa de câmbio entre guilds\n"
                "• `.fx <guild_id>` — taxa específica\n\n"
                "**Moeda:**\n"
                "• `.currency` — info da moeda local\n"
                "• `.currency set <nome> <símbolo>` — admin\n\n"
                "**Comércio:**\n"
                "• `.trade export <guild_id> <symbol> <qtd>`\n"
                "• `.trade import <guild_id> <symbol> <qtd>`\n"
                "• `.trade balance` — balança comercial\n\n"
                "**Tratados:**\n"
                "• `.treaty` — lista tratados ativos\n"
                "• `.treaty propose <guild_id> <tipo>`\n"
                "• `.treaty accept <id>` / `.treaty reject <id>`\n"
                "• `.treaty cancel <id>`\n\n"
                "**Ranking:**\n"
                "• `.globalrank` — PIB global"
            ),
            color=discord.Color.purple(),
            timestamp=datetime.utcnow(),
        )
        await ctx.send(embed=embed)

    # ============================================================
    # CÂMBIO
    # ============================================================

    @commands.command(name="fx", aliases=["cambio"])
    async def fx(self, ctx, target_guild: str = None):
        gid = ctx.guild.id
        my_curr = CurrencyEngine.get_currency(gid)

        if target_guild is None:
            # Lista as principais
            db = get_connection()
            others = list(db["currencies"].find({
                "guild_id": {"$ne": gid},
            }).limit(10))

            embed = discord.Embed(
                title="💱 CÂMBIO",
                description=(
                    f"Sua moeda: **{my_curr['name']} ({my_curr['symbol']})**\n"
                    f"Taxa base: `{my_curr.get('rate', 1.0):.4f}`\n"
                    f"Confiança: `{my_curr.get('confidence', 1.0):.2f}`"
                ),
                color=discord.Color.purple(),
                timestamp=datetime.utcnow(),
            )

            for other in others:
                try:
                    ogid = int(other["guild_id"])
                    rate = CurrencyEngine.compute_rate(gid, ogid)
                    og = self.bot.get_guild(ogid)
                    name = og.name if og else f"Guild {ogid}"
                    embed.add_field(
                        name=f"→ {name}",
                        value=(
                            f"1 {my_curr['symbol']} = "
                            f"**{rate:.4f}** {other.get('symbol', '?')}"
                        ),
                        inline=False,
                    )
                except Exception:
                    continue
            return await ctx.send(embed=embed)

        try:
            target_id = int(target_guild)
        except ValueError:
            return await ctx.send(embed=embed_error("❌ ID inválido."))

        if target_id == gid:
            return await ctx.send(embed=embed_error("❌ É a sua própria guild."))

        target_curr = CurrencyEngine.get_currency(target_id)
        rate = CurrencyEngine.compute_rate(gid, target_id)
        reverse = CurrencyEngine.compute_rate(target_id, gid)

        embed = discord.Embed(
            title=f"💱 CÂMBIO — {ctx.guild.name} ↔ {target_id}",
            color=discord.Color.purple(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(
            name="Ida",
            value=f"1 {my_curr['symbol']} = **{rate:.4f}** {target_curr.get('symbol', '?')}",
            inline=False,
        )
        embed.add_field(
            name="Volta",
            value=f"1 {target_curr.get('symbol', '?')} = **{reverse:.4f}** {my_curr['symbol']}",
            inline=False,
        )
        await ctx.send(embed=embed)

    # ============================================================
    # MOEDA
    # ============================================================

    @commands.command(name="currency", aliases=["moeda"])
    async def currency(self, ctx, action: str = None, name: str = None, symbol: str = None):
        gid = ctx.guild.id
        curr = CurrencyEngine.get_currency(gid)

        if action is None:
            embed = discord.Embed(
                title="🪙 MOEDA DA GUILD",
                color=discord.Color.gold(),
                timestamp=datetime.utcnow(),
            )
            embed.add_field(name="Nome", value=curr.get("name", "?"), inline=True)
            embed.add_field(name="Símbolo", value=curr.get("symbol", "?"), inline=True)
            embed.add_field(name="Taxa base",
                            value=f"`{curr.get('rate', 1.0):.4f}`", inline=True)
            embed.add_field(name="Confiança",
                            value=f"`{curr.get('confidence', 1.0):.2f}`", inline=True)
            embed.add_field(name="PIB estimado",
                            value=self._fmt(gid, CurrencyEngine.estimate_gdp(gid)),
                            inline=True)
            return await ctx.send(embed=embed)

        if action == "set":
            if not ctx.author.guild_permissions.administrator:
                return await ctx.send(embed=embed_error("❌ Só admin."))
            if not name or not symbol:
                return await ctx.send(embed=embed_error(
                    "❌ Uso: `.currency set <nome> <símbolo>`"
                ))
            updated = CurrencyEngine.set_currency_info(gid, name, symbol)
            return await ctx.send(embed=embed_success(
                f"✅ Moeda: **{updated['name']} ({updated['symbol']})**"
            ))

        await ctx.send(embed=embed_error("❌ Ação inválida. Use `.currency set <nome> <símbolo>`"))

    # ============================================================
    # COMÉRCIO
    # ============================================================

    @commands.command(name="trade", aliases=["comercio"])
    async def trade(self, ctx, action: str = None, target: str = None,
                    symbol: str = None, quantity: int = 0):
        gid = ctx.guild.id
        uid = ctx.author.id

        if action is None:
            return await ctx.send(embed=embed_info(
                "Uso:\n"
                "`.trade export <guild_id> <symbol> <qtd>`\n"
                "`.trade import <guild_id> <symbol> <qtd>`\n"
                "`.trade balance`"
            ))

        if action == "balance":
            bal = TradeEngine.get_trade_balance(gid)
            embed = discord.Embed(
                title="⚖️ BALANÇA COMERCIAL",
                color=discord.Color.purple(),
                timestamp=datetime.utcnow(),
            )
            embed.add_field(name="📤 Exportações",
                            value=self._fmt(gid, bal["exports"]), inline=True)
            embed.add_field(name="📥 Importações",
                            value=self._fmt(gid, bal["imports"]), inline=True)
            balance_emoji = "🟢" if bal["balance"] >= 0 else "🔴"
            embed.add_field(name=f"{balance_emoji} Saldo",
                            value=self._fmt(gid, bal["balance"]), inline=True)
            embed.set_footer(text=f"{bal['export_count']} exports · {bal['import_count']} imports (7d)")
            return await ctx.send(embed=embed)

        if action in ("export", "import"):
            if not target or not symbol or quantity <= 0:
                return await ctx.send(embed=embed_error(
                    f"❌ Uso: `.trade {action} <guild_id> <symbol> <qtd>`"
                ))
            try:
                target_id = int(target)
            except ValueError:
                return await ctx.send(embed=embed_error("❌ ID inválido."))

            if EconomyManager.is_frozen(gid, uid):
                return await ctx.send(embed=embed_error("❌ Economia congelada."))

            if action == "export":
                result = TradeEngine.export_goods(gid, target_id, uid, symbol.upper(), quantity)
            else:
                result = TradeEngine.import_goods(gid, target_id, uid, symbol.upper(), quantity)

            if "error" in result:
                errors = {
                    "same_guild": "Guild igual.",
                    "embargo": "🚫 Embargo ativo entre as guilds.",
                    "insufficient_holding": f"Você não tem {result.get('needed', 0)}x {symbol}.",
                    "insufficient_funds": f"Saldo insuficiente ({self._fmt(gid, result.get('needed', 0))}).",
                    "no_price": "Sem preço disponível.",
                    "payment_failed": "Falha no pagamento.",
                    "invalid_quantity": "Quantidade inválida.",
                }
                return await ctx.send(embed=embed_error(
                    f"❌ {errors.get(result['error'], result['error'])}"
                ))

            embed = discord.Embed(
                title=f"{'📤 EXPORTAÇÃO' if action == 'export' else '📥 IMPORTAÇÃO'}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow(),
            )
            embed.add_field(name="📦 Item", value=f"{quantity}x {symbol.upper()}", inline=True)
            embed.add_field(name="💱 Taxa", value=f"`{result['rate']:.4f}`", inline=True)
            embed.add_field(name="💰 Valor",
                            value=self._fmt(gid, result.get("value_origin", 0)), inline=True)
            embed.add_field(name="🎯 Convertido",
                            value=f"`{result.get('converted', 0)}`", inline=True)
            embed.add_field(name="📊 Tarifa",
                            value=self._fmt(gid, result.get("tariff", 0)), inline=True)
            if action == "import":
                embed.add_field(name="💸 Total pago",
                                value=self._fmt(gid, result.get("total_paid", 0)),
                                inline=True)
            return await ctx.send(embed=embed)

        await ctx.send(embed=embed_error("❌ Ação inválida."))

    # ============================================================
    # TRATADOS
    # ============================================================

    @commands.command(name="treaty", aliases=["tratado"])
    async def treaty(self, ctx, action: str = None, target: str = None,
                     treaty_type: str = None, treaty_id: str = None):
        gid = ctx.guild.id

        if action is None:
            active = DiplomacyEngine.list_active(gid)
            proposed = DiplomacyEngine.list_proposed(gid)

            embed = discord.Embed(
                title="🤝 TRATADOS",
                color=discord.Color.purple(),
                timestamp=datetime.utcnow(),
            )

            if active:
                lines = []
                for t in active[:5]:
                    meta = TREATY_TYPES.get(t["type"], {})
                    other = t["guild_b"] if t["guild_a"] == gid else t["guild_a"]
                    lines.append(
                        f"{meta.get('emoji', '🤝')} **{meta.get('name', t['type'])}** "
                        f"com {other} `{str(t['_id'])[:8]}`"
                    )
                embed.add_field(name="✅ Ativos", value="\n".join(lines), inline=False)

            if proposed:
                lines = []
                for t in proposed[:5]:
                    meta = TREATY_TYPES.get(t["type"], {})
                    other = t["guild_b"] if t["guild_a"] == gid else t["guild_a"]
                    lines.append(
                        f"{meta.get('emoji', '🤝')} **{meta.get('name', t['type'])}** "
                        f"com {other} `{str(t['_id'])[:8]}`"
                    )
                embed.add_field(name="⏳ Propostas", value="\n".join(lines), inline=False)

            if not active and not proposed:
                embed.description = "Nenhum tratado ativo ou proposto."

            embed.add_field(
                name="Tipos disponíveis",
                value="\n".join(
                    f"{m['emoji']} `{k}` — {m['name']}"
                    for k, m in TREATY_TYPES.items()
                ),
                inline=False,
            )
            return await ctx.send(embed=embed)

        if action == "propose":
            if not target or not treaty_type:
                return await ctx.send(embed=embed_error(
                    "❌ Uso: `.treaty propose <guild_id> <tipo>`"
                ))
            try:
                target_id = int(target)
            except ValueError:
                return await ctx.send(embed=embed_error("❌ ID inválido."))

            result = DiplomacyEngine.propose_treaty(gid, target_id, treaty_type.lower())
            if "error" in result:
                errors = {
                    "same_guild": "Não pode consigo mesmo.",
                    "invalid_type": f"Tipo inválido. Use: `{', '.join(TREATY_TYPES.keys())}`",
                    "treaty_exists": f"Já existe tratado (ID: {result.get('id', '?')}).",
                    "max_treaties": "Máximo de tratados atingido.",
                }
                return await ctx.send(embed=embed_error(
                    f"❌ {errors.get(result['error'], result['error'])}"
                ))
            return await ctx.send(embed=embed_success(
                f"📜 Tratado proposto!\n🆔 `{result['treaty_id'][:8]}`"
            ))

        if action == "accept":
            if not target:
                return await ctx.send(embed=embed_error("❌ Uso: `.treaty accept <id>`"))
            result = DiplomacyEngine.accept_treaty(gid, target)
            if "error" in result:
                return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
            return await ctx.send(embed=embed_success("✅ Tratado ativado!"))

        if action == "reject":
            if not target:
                return await ctx.send(embed=embed_error("❌ Uso: `.treaty reject <id>`"))
            result = DiplomacyEngine.reject_treaty(gid, target)
            if "error" in result:
                return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
            return await ctx.send(embed=embed_warning("❌ Tratado rejeitado."))

        if action == "cancel":
            if not target:
                return await ctx.send(embed=embed_error("❌ Uso: `.treaty cancel <id>`"))
            result = DiplomacyEngine.cancel_treaty(gid, target)
            if "error" in result:
                return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
            return await ctx.send(embed=embed_warning("🚫 Tratado cancelado."))

        await ctx.send(embed=embed_error("❌ Ação inválida."))

    # ============================================================
    # RANKING GLOBAL
    # ============================================================

    @commands.command(name="globalrank", aliases=["rankglobal", "pib"])
    async def global_rank(self, ctx):
        db = get_connection()
        currencies = list(db["currencies"].find({}))

        rankings = []
        for c in currencies:
            gid = c["guild_id"]
            gdp = CurrencyEngine.estimate_gdp(gid)
            rankings.append({
                "guild_id": gid,
                "gdp": gdp,
                "name": c.get("name", "?"),
                "symbol": c.get("symbol", "?"),
                "confidence": c.get("confidence", 1.0),
            })

        rankings.sort(key=lambda x: x["gdp"], reverse=True)
        rankings = rankings[:15]

        embed = discord.Embed(
            title="🌍 RANKING GLOBAL — PIB",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(rankings):
            g = self.bot.get_guild(r["guild_id"])
            name = g.name if g else f"Guild {r['guild_id']}"
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            embed.add_field(
                name=f"{medal} {name}",
                value=(
                    f"💰 {r['gdp']:,} ({r['symbol']})\n"
                    f"🎯 Confiança: {r['confidence']:.2f}"
                ).replace(",", "."),
                inline=False,
            )

        if not rankings:
            embed.description = "Nenhuma guild com moeda registrada."
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("GlobalCommands") is None:
        await bot.add_cog(GlobalCommands(bot))