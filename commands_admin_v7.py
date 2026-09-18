# ============================================================
# COMMANDS_ADMIN_V7.PY - v7.0 Fase 8
# ============================================================
# Painel unificado de admin v7:
#   • .dash — dashboard econômico
#   • .diag — diagnóstico
#   • .presets — presets de dificuldade
#   • .stresstest — teste de carga
#   • .admin7 — painel central
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from dashboard_engine import DashboardEngine
from balance_engine import BalanceEngine, DIFFICULTY_PRESETS
from utils import SlashCtxAdapter


class AdminV7Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # PAINEL CENTRAL
    # ============================================================

    @commands.command(name="admin7", aliases=["a7", "painel7"])
    @commands.has_permissions(administrator=True)
    async def admin7(self, ctx):
        embed = discord.Embed(
            title="⚙️ PAINEL ADMIN v7.0",
            description=(
                "**Diagnóstico:**\n"
                "• `.dash` — dashboard econômico\n"
                "• `.diag` — diagnóstico automático\n"
                "• `.compare` — comparativo de períodos\n"
                "• `.dashreport` — relatório completo\n\n"
                "**Balanceamento:**\n"
                "• `.presets` — presets de dificuldade\n"
                "• `.setpreset <nome>` — aplicar preset\n"
                "• `.stresstest` — teste de performance\n\n"
                "**Config completa (todas as 23 seções):**\n"
                "• `.president` — painel do presidente\n"
                "• `.presidentconfig <seção> <chave> <valor>`\n"
                "• `.presidentshow <seção>`"
            ),
            color=discord.Color.dark_gold(),
            timestamp=datetime.utcnow(),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    # ============================================================
    # DASHBOARD
    # ============================================================

    @commands.command(name="dash", aliases=["dashboard", "painel_eco"])
    @commands.has_permissions(administrator=True)
    async def dash(self, ctx):
        snap = DashboardEngine.snapshot(ctx.guild.id)
        sparks = DashboardEngine.sparklines(ctx.guild.id)

        embed = discord.Embed(
            title="📊 DASHBOARD ECONÔMICO",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        # Linha 1: Moeda + PIB
        embed.add_field(
            name="💰 Moeda em circulação",
            value=f"**{self._fmt(ctx.guild.id, snap['total_money'])}**",
            inline=True,
        )
        embed.add_field(
            name="📈 PIB estimado",
            value=f"**{self._fmt(ctx.guild.id, snap['gdp'])}**",
            inline=True,
        )
        embed.add_field(
            name="👥 População ativa",
            value=f"**{snap['population']}**",
            inline=True,
        )

        # Linha 2: Inflação + Moeda
        embed.add_field(
            name=f"{sparks['inflation_trend']} IPC",
            value=f"`{sparks['inflation']}`\n**{snap['ipc']*100:+.2f}%** "
                  f"({snap['ipc_status'].upper()})",
            inline=False,
        )

        # Linha 3: Setor real
        embed.add_field(
            name="🏢 Empresas",
            value=f"**{snap['companies']}**",
            inline=True,
        )
        embed.add_field(
            name="💼 Empregos",
            value=f"**{snap['jobs']}**",
            inline=True,
        )
        embed.add_field(
            name="🏠 Imóveis",
            value=f"**{snap['properties']}**",
            inline=True,
        )

        # Linha 4: Financeiro
        embed.add_field(
            name="💳 Empréstimos ativos",
            value=f"**{snap['loans']}**",
            inline=True,
        )
        embed.add_field(
            name="📊 Dívida total",
            value=self._fmt(ctx.guild.id, snap["total_debt"]),
            inline=True,
        )
        embed.add_field(
            name="💰 Tesouro",
            value=self._fmt(ctx.guild.id, snap["treasury"]),
            inline=True,
        )

        # Moeda
        curr = snap["currency"]
        embed.add_field(
            name="🪙 Moeda",
            value=f"**{curr.get('name', '?')}** ({curr.get('symbol', '?')})",
            inline=False,
        )

        embed.set_footer(text="Use .dashreport pra relatório completo")
        await ctx.send(embed=embed)

    @commands.command(name="dashreport", aliases=["relatorio"])
    @commands.has_permissions(administrator=True)
    async def dash_report(self, ctx):
        report = DashboardEngine.report(ctx.guild.id)
        # Discord tem limite de 2000 chars — envia em chunks
        chunks = [report[i:i+1900] for i in range(0, len(report), 1900)]
        for chunk in chunks:
            await ctx.send(f"```\n{chunk}\n```")

    @commands.command(name="compare", aliases=["comparar"])
    @commands.has_permissions(administrator=True)
    async def compare(self, ctx, hours: int = 24):
        hours = max(1, min(hours, 720))
        data = DashboardEngine.compare_periods(ctx.guild.id, hours)

        embed = discord.Embed(
            title=f"📊 COMPARATIVO — Últimas {hours}h",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="⚙️ Ticks", value=f"**{data['ticks']}**", inline=True)
        embed.add_field(name="💸 Transações", value=f"**{data['transactions']}**", inline=True)
        embed.add_field(name="💳 Novos empréstimos", value=f"**{data['new_loans']}**", inline=True)
        embed.add_field(name="🏠 Imóveis vendidos", value=f"**{data['sold_properties']}**", inline=True)
        await ctx.send(embed=embed)

    # ============================================================
    # DIAGNÓSTICO
    # ============================================================

    @commands.command(name="diag", aliases=["diagnostico"])
    @commands.has_permissions(administrator=True)
    async def diag(self, ctx):
        d = DashboardEngine.diagnose(ctx.guild.id)
        analysis = BalanceEngine.analyze(ctx.guild.id)

        color_map = {
            "green": discord.Color.green(),
            "blue": discord.Color.blue(),
            "yellow": discord.Color.gold(),
            "red": discord.Color.red(),
        }

        embed = discord.Embed(
            title="🔍 DIAGNÓSTICO ECONÔMICO",
            description=f"**Saúde:** {d['status']} ({d['health']}/100)",
            color=color_map.get(d["color"], discord.Color.blue()),
            timestamp=datetime.utcnow(),
        )

        # Barra de saúde
        bar_filled = int(d["health"] / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        embed.add_field(name="📊 Saúde", value=f"`{bar}`", inline=False)

        # Alertas
        if d["alerts"]:
            embed.add_field(
                name="⚠️ Alertas",
                value="\n".join(f"• {a}" for a in d["alerts"][:6]),
                inline=False,
            )

        # Issues estruturais
        if analysis["issues"]:
            lines = []
            for iss in analysis["issues"][:5]:
                sev = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(
                    iss["severity"], "•"
                )
                lines.append(f"{sev} {iss['message']}")
            embed.add_field(name="🔎 Problemas Detectados",
                            value="\n".join(lines), inline=False)

        # Sugestões
        if d["suggestions"]:
            embed.add_field(
                name="💡 Sugestões",
                value="\n".join(f"• {s}" for s in d["suggestions"][:5]),
                inline=False,
            )

        if not d["alerts"] and not analysis["issues"]:
            embed.add_field(name="✨ Tudo OK",
                            value="Nenhum problema detectado.",
                            inline=False)

        await ctx.send(embed=embed)

    # ============================================================
    # PRESETS
    # ============================================================

    @commands.command(name="presets", aliases=["dificuldades"])
    @commands.has_permissions(administrator=True)
    async def presets(self, ctx):
        current = BalanceEngine.get_config(ctx.guild.id).get("difficulty", "normal")

        embed = discord.Embed(
            title="🎚️ PRESETS DE DIFICULDADE",
            description=f"Atual: **{DIFFICULTY_PRESETS.get(current, {}).get('name', '?')}**",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        for key, preset in DIFFICULTY_PRESETS.items():
            marker = " ✅" if key == current else ""
            embed.add_field(
                name=f"{preset['emoji']} `{key}` — {preset['name']}{marker}",
                value=preset["description"],
                inline=False,
            )
        embed.set_footer(text="Use .setpreset <nome> para aplicar")
        await ctx.send(embed=embed)

    @commands.command(name="setpreset", aliases=["aplicarpreset"])
    @commands.has_permissions(administrator=True)
    async def set_preset(self, ctx, preset_name: str):
        result = BalanceEngine.apply_preset(ctx.guild.id, preset_name.lower())
        if "error" in result:
            return await ctx.send(embed=embed_error(
                f"❌ Preset inválido. Use: `{', '.join(DIFFICULTY_PRESETS.keys())}`"
            ))

        embed = discord.Embed(
            title=f"{result['emoji']} PRESET APLICADO",
            description=f"**{result['name']}**",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="📊 Configs alteradas", value=str(result["applied"]))
        embed.set_footer(text="Caches invalidados — efeitos imediatos")
        await ctx.send(embed=embed)

    # ============================================================
    # STRESS TEST
    # ============================================================

    @commands.command(name="stresstest", aliases=["st"])
    @commands.has_permissions(administrator=True)
    async def stress_test(self, ctx, iterations: int = 100):
        iterations = max(10, min(iterations, 1000))

        msg = await ctx.send(embed=embed_info(
            f"⚙️ Rodando stress test ({iterations} iterações)..."
        ))

        import asyncio
        await asyncio.sleep(0.5)

        result = BalanceEngine.stress_test(ctx.guild.id, iterations)

        embed = discord.Embed(
            title="⚡ STRESS TEST",
            description=result["verdict"],
            color=discord.Color.green() if "Excelente" in result["verdict"]
                  or "Bom" in result["verdict"] else discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="📊 Iterações", value=str(result["iterations"]), inline=True)
        embed.add_field(name="⚠️ Erros", value=str(result["errors"]), inline=True)
        embed.add_field(name="⏱️ Total", value=f"{result['total']:.1f}ms", inline=True)
        embed.add_field(name="💵 Price calc", value=f"{result['price_calc']:.1f}ms", inline=True)
        embed.add_field(name="📈 Inflation calc", value=f"{result['inflation_calc']:.1f}ms", inline=True)
        await msg.edit(embed=embed)

    # ============================================================
    # HELP GERAL v7
    # ============================================================

    @commands.command(name="help7", aliases=["ajuda7", "v7"])
    async def help_v7(self, ctx):
        embed = discord.Embed(
            title="📖 GT BOT ECONOMIA v7.0 — AJUDA",
            description=(
                "**Camadas do sistema:**\n\n"
                "**💵 Preços e Inflação**\n"
                "`.president show price` / `.president show inflation`\n\n"
                "**🏢 Produção**\n"
                "`.company` — empresas\n"
                "`.jobs` — empregos\n"
                "`.resources` — matérias-primas\n\n"
                "**💳 Crédito**\n"
                "`.score` — score\n"
                "`.loan` — empréstimo\n"
                "`.banks` — bancos\n"
                "`.selic` — taxa básica\n\n"
                "**📊 Mercado**\n"
                "`.book <symbol>` — order book\n"
                "`.commodities` — commodities\n"
                "`.future open ...` — futuros\n\n"
                "**🏛️ Governo**\n"
                "`.eleicao` — eleições\n"
                "`.gov` — governo\n"
                "`.policies` — políticas\n"
                "`.treasury` — tesouro\n\n"
                "**🌍 Global**\n"
                "`.fx` — câmbio\n"
                "`.trade` — comércio\n"
                "`.treaty` — tratados\n"
                "`.globalrank` — ranking\n\n"
                "**🏠 Imóveis**\n"
                "`.regions` — regiões\n"
                "`.buyland` — comprar terreno\n"
                "`.build` — construir\n"
                "`.rent` — alugar\n"
                "`.mortgage` — financiar\n\n"
                "**⚙️ Admin**\n"
                "`.admin7` — painel admin\n"
                "`.dash` — dashboard\n"
                "`.diag` — diagnóstico\n"
                "`.presets` — dificuldades"
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("AdminV7Commands") is None:
        await bot.add_cog(AdminV7Commands(bot))