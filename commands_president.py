# ============================================================
# COMMANDS_PRESIDENT.PY - v7.0 Fases 1 a 6
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from price_engine import PriceEngine
from inflation_engine import InflationEngine
from economy_tick import TickConfig, EconomyTick


PRESIDENT_SECTIONS = {
    # Fase 1
    "price": "💵 Preços Endógenos",
    "inflation": "📈 Inflação / IPC",
    "tick": "⚙️ Motor Central (Tick)",
    # Fase 2
    "companies": "🏢 Empresas",
    "jobs": "💼 Empregos",
    "resources": "⛏️ Recursos",
    # Fase 3
    "credit": "💳 Crédito",
    "banks": "🏦 Bancos",
    "central_bank": "🏛️ Banco Central",
    # Fase 4
    "market_v7": "📊 Mercado Real",
    "commodities": "🏭 Commodities",
    "futures": "📈 Futuros",
    # Fase 5
    "government": "🏛️ Governo",
    "policies": "📋 Políticas",
    "taxes": "💸 Impostos",
    "treasury": "💰 Tesouro",
    # Fase 6
    "interguild": "🌍 Inter-Guild",
    "trade": "⚖️ Comércio Internacional",
    "diplomacy": "🤝 Diplomacia",
}


class PresidentCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="president", aliases=["presidente", "presid"])
    @commands.has_permissions(administrator=True)
    async def president(self, ctx):
        embed = discord.Embed(
            title="🏛️ PAINEL DO PRESIDENTE — v7.0",
            description=(
                "Controle total da macroeconomia do servidor.\n\n"
                "**Configurações:**\n"
                "• `.presidentconfig <seção> <chave> <valor>`\n"
                "• `.presidentshow <seção>`\n\n"
                "**Diagnóstico:**\n"
                "• `.presidentstatus` / `.presidentipc` / `.presidenttick`\n"
                "• `.presidentforce` — tick imediato\n\n"
                "**Seções:**\n" +
                "\n".join(f"• `{k}` — {v}" for k, v in PRESIDENT_SECTIONS.items())
            ),
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    @app_commands.command(name="president", description="🏛️ Painel do Presidente")
    @app_commands.default_permissions(administrator=True)
    async def president_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏛️ PAINEL DO PRESIDENTE — v7.0",
            description="Use `.president` no chat.",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="presidentconfig", aliases=["pcfg"])
    @commands.has_permissions(administrator=True)
    async def president_config(self, ctx, section: str = None, key: str = None, *, value: str = None):
        if not section:
            return await ctx.send(embed=embed_info(
                "Uso: `.presidentconfig <seção> <chave> <valor>`"
            ))
        section = section.lower()
        if section not in PRESIDENT_SECTIONS:
            return await ctx.send(embed=embed_error(
                f"❌ Seção inválida. Use: `{', '.join(PRESIDENT_SECTIONS.keys())}`"
            ))
        if key is None:
            return await self._show_section(ctx, section)
        if value is None:
            return await ctx.send(embed=embed_error("❌ Forneça um valor."))
        parsed = self._parse_value(value)

        try:
            if section == "price":
                if key not in PriceEngine.get_config(ctx.guild.id):
                    return await ctx.send(embed=embed_error(f"❌ Chave `{key}` inválida."))
                PriceEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "inflation":
                PriceEngine.update_config(ctx.guild.id, f"inflation_{key}", parsed)
                InflationEngine.clear_cache()
            elif section == "tick":
                if key not in TickConfig.get(ctx.guild.id):
                    return await ctx.send(embed=embed_error(f"❌ Chave `{key}` inválida."))
                TickConfig.update(ctx.guild.id, key, parsed)
            elif section == "companies":
                from company_engine import CompanyEngine
                CompanyEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "jobs":
                from job_engine import JobEngine
                JobEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "resources":
                from resource_engine import ResourceEngine
                ResourceEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "credit":
                from credit_engine import CreditEngine
                CreditEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "banks":
                from bank_engine import BankEngine
                BankEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "central_bank":
                from central_bank import CentralBank
                CentralBank.update_config(ctx.guild.id, key, parsed)
            elif section == "market_v7":
                from market_engine import MarketEngine
                MarketEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "commodities":
                from commodity_engine import CommodityEngine
                CommodityEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "futures":
                from futures_engine import FuturesEngine
                FuturesEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "government":
                from political_engine import PoliticalEngine
                PoliticalEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "policies":
                from policy_engine import PolicyEngine
                PolicyEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "taxes":
                from tax_engine import TaxEngine
                TaxEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "treasury":
                from treasury_engine import TreasuryEngine
                TreasuryEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "interguild":
                from currency_engine import CurrencyEngine
                CurrencyEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "trade":
                from trade_engine import TradeEngine
                TradeEngine.update_config(ctx.guild.id, key, parsed)
            elif section == "diplomacy":
                from diplomacy_engine import DiplomacyEngine
                DiplomacyEngine.update_config(ctx.guild.id, key, parsed)
            else:
                return await ctx.send(embed=embed_warning(
                    f"⚠️ Seção `{section}` ainda não implementada."
                ))
            await ctx.send(embed=embed_success(f"✅ `{section}.{key}` = `{parsed}`"))
        except Exception as e:
            await ctx.send(embed=embed_error(f"❌ Erro: {e}"))

    def _parse_value(self, value: str):
        v = value.strip()
        if v.lower() in ("true", "on", "sim", "yes", "1"):
            return True
        if v.lower() in ("false", "off", "nao", "não", "no", "0"):
            return False
        try:
            return int(v)
        except ValueError:
            pass
        try:
            return float(v)
        except ValueError:
            pass
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1]
            try:
                return [self._parse_value(x.strip()) for x in inner.split(",") if x.strip()]
            except Exception:
                pass
        return v

    @commands.command(name="presidentshow", aliases=["pshow"])
    @commands.has_permissions(administrator=True)
    async def president_show(self, ctx, section: str = None):
        if not section:
            return await ctx.send(embed=embed_error("Uso: `.presidentshow <seção>`"))
        await self._show_section(ctx, section.lower())

    async def _show_section(self, ctx, section: str):
        if section == "price":
            config = PriceEngine.get_config(ctx.guild.id)
            title = "💵 Configuração de Preços"
        elif section == "inflation":
            config = InflationEngine.get_config(ctx.guild.id)
            title = "📈 Configuração de Inflação"
        elif section == "tick":
            config = TickConfig.get(ctx.guild.id)
            title = "⚙️ Configuração do Tick"
        elif section == "companies":
            from company_engine import CompanyEngine
            config = CompanyEngine.get_config(ctx.guild.id)
            title = "🏢 Configuração de Empresas"
        elif section == "jobs":
            from job_engine import JobEngine
            config = JobEngine.get_config(ctx.guild.id)
            title = "💼 Configuração de Empregos"
        elif section == "resources":
            from resource_engine import ResourceEngine
            config = ResourceEngine.get_config(ctx.guild.id)
            title = "⛏️ Configuração de Recursos"
        elif section == "credit":
            from credit_engine import CreditEngine
            config = CreditEngine.get_config(ctx.guild.id)
            title = "💳 Configuração de Crédito"
        elif section == "banks":
            from bank_engine import BankEngine
            config = BankEngine.get_config(ctx.guild.id)
            title = "🏦 Configuração de Bancos"
        elif section == "central_bank":
            from central_bank import CentralBank
            config = CentralBank.get_config(ctx.guild.id)
            title = "🏛️ Configuração do Banco Central"
        elif section == "market_v7":
            from market_engine import MarketEngine
            config = MarketEngine.get_config(ctx.guild.id)
            title = "📊 Configuração do Mercado"
        elif section == "commodities":
            from commodity_engine import CommodityEngine
            config = CommodityEngine.get_config(ctx.guild.id)
            title = "🏭 Configuração de Commodities"
        elif section == "futures":
            from futures_engine import FuturesEngine
            config = FuturesEngine.get_config(ctx.guild.id)
            title = "📈 Configuração de Futuros"
        elif section == "government":
            from political_engine import PoliticalEngine
            config = PoliticalEngine.get_config(ctx.guild.id)
            title = "🏛️ Configuração do Governo"
        elif section == "policies":
            from policy_engine import PolicyEngine
            config = PolicyEngine.get_config(ctx.guild.id)
            title = "📋 Configuração de Políticas"
        elif section == "taxes":
            from tax_engine import TaxEngine
            config = TaxEngine.get_config(ctx.guild.id)
            title = "💸 Configuração de Impostos"
        elif section == "treasury":
            from treasury_engine import TreasuryEngine
            config = TreasuryEngine.get_config(ctx.guild.id)
            title = "💰 Configuração do Tesouro"
        elif section == "interguild":
            from currency_engine import CurrencyEngine
            config = CurrencyEngine.get_config(ctx.guild.id)
            title = "🌍 Configuração Inter-Guild"
        elif section == "trade":
            from trade_engine import TradeEngine
            config = TradeEngine.get_config(ctx.guild.id)
            title = "⚖️ Configuração de Comércio"
        elif section == "diplomacy":
            from diplomacy_engine import DiplomacyEngine
            config = DiplomacyEngine.get_config(ctx.guild.id)
            title = "🤝 Configuração de Diplomacia"
        else:
            return await ctx.send(embed=embed_warning(
                f"⚠️ Seção `{section}` ainda não implementada."
            ))

        embed = discord.Embed(
            title=title, color=discord.Color.blue(), timestamp=datetime.utcnow(),
        )
        lines = []
        for k, v in config.items():
            if isinstance(v, dict):
                lines.append(f"`{k}`: *({len(v)} entradas)*")
            elif isinstance(v, list):
                lines.append(f"`{k}`: `{v}`")
            else:
                lines.append(f"`{k}`: `{v}`")
        chunks = [lines[i:i+15] for i in range(0, len(lines), 15)]
        for i, ch in enumerate(chunks):
            embed.add_field(
                name=f"Configuração {'(cont.)' if i > 0 else ''}",
                value="\n".join(ch), inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="presidentstatus", aliases=["pstatus"])
    @commands.has_permissions(administrator=True)
    async def president_status(self, ctx):
        db = get_connection()
        state = db["economy_state"].find_one({"guild_id": ctx.guild.id}) or {}
        ipc = InflationEngine.calculate_ipc(ctx.guild.id)
        from commands_economy_core import EconomyManager
        total = EconomyManager.get_total_balance(ctx.guild.id)
        embed = discord.Embed(
            title="📊 ESTADO DA ECONOMIA",
            color=discord.Color.blue(), timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💰 Moeda",
                        value=EconomyManager.format_currency(ctx.guild.id, total),
                        inline=True)
        embed.add_field(name="📈 IPC",
                        value=f"{ipc.get('ipc', 0)*100:+.2f}%", inline=True)
        embed.add_field(name="🎯 Status",
                        value=ipc.get("status", "?").upper(), inline=True)
        embed.add_field(name="📊 Índice", value=f"{ipc.get('index', 100):.1f}", inline=True)
        embed.add_field(name="🏷️ Itens", value=str(ipc.get("tracked_items", 0)), inline=True)
        embed.add_field(name="⚙️ Último tick",
                        value=self._format_dt(state.get("last_updated")), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="presidentipc", aliases=["pipc"])
    @commands.has_permissions(administrator=True)
    async def president_ipc(self, ctx, history: int = 10):
        history = max(1, min(history, 30))
        docs = InflationEngine.get_history(ctx.guild.id, history)
        if not docs:
            return await ctx.send(embed=embed_info("📋 Sem histórico ainda."))
        embed = discord.Embed(
            title="📈 HISTÓRICO DE INFLAÇÃO",
            color=discord.Color.blue(), timestamp=datetime.utcnow(),
        )
        lines = []
        for d in docs:
            ts = d.get("timestamp")
            ts_str = ts.strftime("%d/%m %H:%M") if hasattr(ts, "strftime") else "?"
            lines.append(f"`{ts_str}` → **{d.get('ipc', 0)*100:+.2f}%** | idx={d.get('index', 100):.1f} | `{d.get('status', '?')}`")
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.command(name="presidenttick", aliases=["ptick"])
    @commands.has_permissions(administrator=True)
    async def president_tick(self, ctx):
        last = EconomyTick.get_last_tick(ctx.guild.id)
        if not last:
            return await ctx.send(embed=embed_info("📋 Nenhum tick registrado."))
        ts = last.get("timestamp")
        ts_str = ts.strftime("%d/%m %H:%M:%S") if hasattr(ts, "strftime") else "?"
        embed = discord.Embed(
            title="⚙️ ÚLTIMO TICK", color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="🕐 Quando", value=ts_str, inline=True)
        embed.add_field(name="⏱️ Duração", value=f"{last.get('duration_ms', 0)}ms", inline=True)
        embed.add_field(name="✅ Passos",
                        value=", ".join(last.get("steps", [])) or "—", inline=False)
        errs = last.get("errors") or []
        if errs:
            embed.add_field(name="⚠️ Erros",
                            value="\n".join(f"• `{e}`" for e in errs[:5]),
                            inline=False)
        count = EconomyTick.get_tick_count(ctx.guild.id)
        embed.set_footer(text=f"Total: {count}")
        await ctx.send(embed=embed)

    @commands.command(name="presidentforce", aliases=["pforce"])
    @commands.has_permissions(administrator=True)
    async def president_force(self, ctx):
        msg = await ctx.send(embed=embed_info("⚙️ Forçando tick..."))
        try:
            cog = self.bot.get_cog("EconomyTick")
            if not cog:
                return await msg.edit(embed=embed_error("❌ Motor não carregado."))
            cfg = TickConfig.get(ctx.guild.id)
            await cog._run_tick_for_guild(ctx.guild.id, cfg)
            await msg.edit(embed=embed_success("✅ Tick executado!"))
        except Exception as e:
            await msg.edit(embed=embed_error(f"❌ Erro: {e}"))

    def _format_dt(self, dt) -> str:
        if not dt:
            return "—"
        if hasattr(dt, "strftime"):
            return dt.strftime("%d/%m %H:%M")
        return str(dt)[:16]


async def setup(bot):
    if bot.get_cog("PresidentCommands") is None:
        await bot.add_cog(PresidentCommands(bot))