# ============================================================
# COMMANDS_GLOBAL_IMPERIAL.PY - Painel do Imperador
# ============================================================
# ATENÇÃO: Todos os comandos exigem IMPERIAL_USER_ID no .env
# Ninguém mais pode executar. Nem admin. Nem ninguém.
# ============================================================

from __future__ import annotations

import os
import json
import discord
from discord.ext import commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from utils import safe_object_id


IMPERIAL_USER_ID = int(os.getenv("IMPERIAL_USER_ID", "0"))


class GlobalImperial(commands.Cog):
    """👑 Painel do Imperador - Controle absoluto sobre tudo."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if IMPERIAL_USER_ID == 0:
            raise commands.CheckFailure("IMPERIAL_USER_ID não configurado")
        if ctx.author.id != IMPERIAL_USER_ID:
            raise commands.CheckFailure("Só o Imperador pode usar isso.")
        return True

    @commands.command(name="imperial", aliases=["imperio", "king"])
    @commands.guild_only()
    async def imperial_panel(self, ctx):
        db = get_connection()

        total_nations = db["global_nations"].count_documents({})
        total_companies = db["global_companies"].count_documents(
            {"status": {"$in": ["active", "public"]}})
        total_loans = db["global_loans"].count_documents({"status": "active"})
        total_processes = db["global_legal_processes"].count_documents(
            {"status": {"$in": ["pending_notification", "awaiting_verdict"]}})

        guilds = list(db["global_nations"].find(
            {}, {"guild_id": 1, "guild_name": 1, "gdp": 1,
                  "confidence": 1, "idh": 1}
        ).sort("gdp", -1).limit(10))

        embed = discord.Embed(
            title="👑 PAINEL DO IMPERADOR",
            description=(
                "Você tem **poder absoluto** sobre o mundo econômico.\n"
                "Suas ações são registradas em log imutável.\n\n"
                "**Comandos disponíveis:**"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        embed.add_field(
            name="📊 Estatísticas Globais",
            value=(
                f"🌍 Nações ativas: **{total_nations}**\n"
                f"🏢 Empresas: **{total_companies}**\n"
                f"💳 Empréstimos ativos: **{total_loans}**\n"
                f"⚖️ Processos: **{total_processes}**"
            ),
            inline=False,
        )

        if guilds:
            top_lines = []
            for g in guilds[:5]:
                gdp_fmt = f"{int(g.get('gdp', 0)):,}".replace(",", ".")
                top_lines.append(
                    f"• **{g.get('guild_name', '?')}** — "
                    f"PIB: {gdp_fmt} | "
                    f"Conf: {g.get('confidence', 0)} | "
                    f"IDH: {g.get('idh', 0):.2f}"
                )
            embed.add_field(name="🏆 Top 5 Nações",
                            value="\n".join(top_lines), inline=False)

        embed.add_field(
            name="⚡ Comandos de Poder",
            value=(
                "`$imperial_forcafalir <empresa_id>` — Força falência\n"
                "`$imperial_congelartudo <guild_id>` — Congela contas\n"
                "`$imperial_crise <low/medium/high/catastrophic>` — Crise global\n"
                "`$imperial_resetpib <guild_id>` — Zera PIB\n"
                "`$imperial_editar <collection> <query_json> <update_json>`\n"
                "`$imperial_deletar <collection> <query_json>`\n"
                "`$imperial_logs` — Ver seus últimos decretos"
            ),
            inline=False,
        )

        await ctx.send(embed=embed)

    @commands.command(name="imperial_forcafalir")
    async def imperial_force_fail(self, ctx, company_id: str,
                                    *, reason: str = "imperial_decree"):
        oid = safe_object_id(company_id)
        if not oid:
            return await ctx.send(embed=embed_error("❌ ID inválido."))

        db = get_connection()
        company = db["global_companies"].find_one({"_id": oid})
        if not company:
            return await ctx.send(embed=embed_error("❌ Empresa não encontrada."))

        from political_engine import ImperialEngine
        success = ImperialEngine.force_fail_company(
            company["guild_id"], company_id, reason
        )

        if success:
            embed = discord.Embed(
                title="💀 DECRETO IMPERIAL EXECUTADO",
                description=(
                    f"A empresa **{company.get('name', '?')}** "
                    f"(`{company_id[:8]}`) foi **forçada à falência**.\n\n"
                    f"**Motivo:** {reason}"
                ),
                color=discord.Color.dark_red(),
                timestamp=datetime.utcnow(),
            )
            embed.add_field(name="🏢 Guild",
                            value=str(company.get("guild_id", "?")), inline=True)
            embed.add_field(name="📉 Ações",
                            value="Zeradas e delistadas", inline=True)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=embed_error("❌ Falha ao executar decreto."))

    @commands.command(name="imperial_congelartudo")
    async def imperial_freeze_all(self, ctx, guild_id: int,
                                    *, reason: str = "imperial_lockdown"):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.send(embed=embed_error("❌ Guild não encontrada."))

        await ctx.send(embed=embed_warning(
            f"⚠️ Você vai congelar **TODAS** as contas de **{guild.name}**.\n"
            f"Digite `CONFIRMAR` em 15 segundos."
        ))

        def check(m):
            return (m.author.id == ctx.author.id and
                    m.channel.id == ctx.channel.id and
                    m.content == "CONFIRMAR")

        try:
            await self.bot.wait_for("message", check=check, timeout=15)
        except Exception:
            return await ctx.send(embed=embed_info("Cancelado."))

        from political_engine import ImperialEngine
        count = ImperialEngine.freeze_all_accounts(guild_id, reason)

        await ctx.send(embed=embed_success(
            f"🧊 **{count}** contas congeladas em **{guild.name}**."
        ))

    @commands.command(name="imperial_crise")
    async def imperial_crisis(self, ctx, severity: str = "medium"):
        valid = ("low", "medium", "high", "catastrophic")
        if severity not in valid:
            return await ctx.send(embed=embed_error(
                f"❌ Severidade: {', '.join(valid)}"
            ))

        from political_engine import ImperialEngine
        affected = ImperialEngine.create_global_crisis(severity)

        embed = discord.Embed(
            title="🌍 CRISE GLOBAL DECRETADA",
            description=(
                f"O Imperador decretou uma **crise global**.\n"
                f"**Severidade:** `{severity}`\n\n"
                f"**{affected}** nações foram afetadas."
            ),
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow(),
        )
        await ctx.send(embed=embed)

    @commands.command(name="imperial_resetpib")
    async def imperial_reset_gdp(self, ctx, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.send(embed=embed_error("❌ Guild não encontrada."))

        from political_engine import ImperialEngine
        if ImperialEngine.reset_gdp(guild_id):
            await ctx.send(embed=embed_success(
                f"📉 PIB de **{guild.name}** zerado."
            ))

    @commands.command(name="imperial_editar")
    async def imperial_edit(self, ctx, collection: str,
                              filter_json: str, update_json: str):
        if not collection.startswith("global_"):
            return await ctx.send(embed=embed_error(
                "❌ Só posso editar collections `global_*`."
            ))

        try:
            filter_query = json.loads(filter_json)
            update = json.loads(update_json)
        except json.JSONDecodeError as e:
            return await ctx.send(embed=embed_error(f"❌ JSON inválido: {e}"))

        from political_engine import ImperialEngine
        success = ImperialEngine.edit_any_value(
            collection, 0, filter_query, update
        )

        if success:
            await ctx.send(embed=embed_success(
                f"✏️ Editado em `{collection}`."
            ))
        else:
            await ctx.send(embed=embed_error("❌ Nada editado."))

    @commands.command(name="imperial_deletar")
    async def imperial_delete(self, ctx, collection: str, query_json: str):
        if not collection.startswith("global_"):
            return await ctx.send(embed=embed_error("❌ Só collections global_*."))

        try:
            query = json.loads(query_json)
        except json.JSONDecodeError as e:
            return await ctx.send(embed=embed_error(f"❌ JSON inválido: {e}"))

        await ctx.send(embed=embed_warning(
            "⚠️ Digite `CONFIRMAR` em 15s para deletar."
        ))

        def check(m):
            return (m.author.id == ctx.author.id and
                    m.content == "CONFIRMAR")

        try:
            await self.bot.wait_for("message", check=check, timeout=15)
        except Exception:
            return await ctx.send(embed=embed_info("Cancelado."))

        from political_engine import ImperialEngine
        count = ImperialEngine.delete_any_data(collection, query)

        await ctx.send(embed=embed_success(
            f"🗑️ **{count}** documentos deletados de `{collection}`."
        ))

    @commands.command(name="imperial_logs")
    async def imperial_logs(self, ctx, limit: int = 10):
        limit = max(1, min(limit, 25))
        db = get_connection()
        logs = list(db["global_imperial_logs"].find(
            {}
        ).sort("timestamp", -1).limit(limit))

        if not logs:
            return await ctx.send(embed=embed_info("📜 Nenhum decreto registrado."))

        embed = discord.Embed(
            title="📜 DECRETOS IMPERIAIS RECENTES",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        for log in logs:
            action = log.get("action", "?")
            ts = log.get("timestamp", datetime.utcnow())
            ts_str = ts.strftime("%d/%m %H:%M") if hasattr(ts, "strftime") else "?"

            details = log.get("details", {})
            detail_str = ", ".join(
                f"{k}={v}" for k, v in list(details.items())[:3]
            )[:100]

            embed.add_field(
                name=f"⚡ {action}",
                value=f"`{ts_str}` — {detail_str or 'sem detalhes'}",
                inline=False,
            )

        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("GlobalImperial") is None:
        await bot.add_cog(GlobalImperial(bot))