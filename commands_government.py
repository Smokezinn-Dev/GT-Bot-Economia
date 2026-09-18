# ============================================================
# COMMANDS_GOVERNMENT.PY - v7.0 Fase 5
# ============================================================
# Comandos do governo:
#   • Eleições (.eleicao)
#   • Governo atual (.gov)
#   • Políticas (.policy, .propose)
#   • Tesouro (.treasury)
#   • Impostos (.taxes)
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from political_engine import PoliticalEngine
from policy_engine import PolicyEngine, POLICY_TYPES
from treasury_engine import TreasuryEngine
from tax_engine import TaxEngine
from utils import SlashCtxAdapter


class GovernmentCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # HELP
    # ============================================================

    @commands.command(name="government", aliases=["governo", "gov"])
    async def government(self, ctx):
        embed = discord.Embed(
            title="🏛️ SISTEMA DE GOVERNO",
            description=(
                "**Eleições:**\n"
                "• `.eleicao` — status da eleição\n"
                "• `.eleicao candidatar` — se candidatar\n"
                "• `.eleicao votar @user` — votar\n"
                "• `.eleicao impeachment` — votar impeachment\n\n"
                "**Governo atual:**\n"
                "• `.govinfo` — presidente + ministros\n"
                "• `.govhistoria` — presidentes anteriores\n"
                "• `.govnomear @user <cargo>` — nomear ministro\n"
                "• `.govdemitir <cargo>` — demitir ministro\n\n"
                "**Políticas:**\n"
                "• `.policies` — políticas ativas\n"
                "• `.propose <tipo> <params>` — propor (ministro)\n"
                "• `.approve <id>` — aprovar (presidente)\n"
                "• `.reject <id>` — rejeitar (presidente)\n\n"
                "**Tesouro:**\n"
                "• `.treasury` — saldo e histórico\n"
                "• `.taxes` — alíquotas atuais"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        await ctx.send(embed=embed)

    # ============================================================
    # ELEIÇÕES
    # ============================================================

    @commands.command(name="eleicao", aliases=["election"])
    async def election(self, ctx, action: str = None, member: discord.Member = None):
        gid = ctx.guild.id

        if action is None:
            db = get_connection()
            election = db["elections"].find_one({
                "guild_id": gid,
                "status": {"$in": ["campaign", "voting"]},
            })
            if not election:
                president = PoliticalEngine.get_current_president(gid)
                if president:
                    embed = discord.Embed(
                        title="🏛️ GOVERNO ATUAL",
                        description=f"Presidente: <@{president['user_id']}>",
                        color=discord.Color.gold(),
                        timestamp=datetime.utcnow(),
                    )
                    if president.get("term_end"):
                        embed.add_field(
                            name="⏰ Mandato até",
                            value=f"<t:{int(president['term_end'].timestamp())}:R>"
                        )
                else:
                    embed = discord.Embed(
                        title="🗳️ SEM PRESIDENTE",
                        description="Use `.eleicao iniciar` para começar.",
                        color=discord.Color.orange(),
                        timestamp=datetime.utcnow(),
                    )
                return await ctx.send(embed=embed)

            embed = discord.Embed(
                title="🗳️ ELEIÇÃO EM ANDAMENTO",
                color=discord.Color.gold(),
                timestamp=datetime.utcnow(),
            )
            status = "📢 CAMPANHA" if election["status"] == "campaign" else "🗳️ VOTAÇÃO"
            embed.add_field(name="📊 Status", value=status, inline=True)

            candidates = election.get("candidates", [])
            embed.add_field(name="👥 Candidatos", value=str(len(candidates)), inline=True)

            votes = election.get("votes", {})
            embed.add_field(name="🗳️ Votos", value=str(len(votes)), inline=True)

            if election["status"] == "campaign":
                embed.add_field(
                    name="⏰ Campanha termina",
                    value=f"<t:{int(election['campaign_end'].timestamp())}:R>",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="⏰ Votação termina",
                    value=f"<t:{int(election['voting_end'].timestamp())}:R>",
                    inline=False,
                )

            if candidates:
                lines = [f"• <@{c['user_id']}>" for c in candidates[:10]]
                embed.add_field(name="Candidatos", value="\n".join(lines), inline=False)

            return await ctx.send(embed=embed)

        if action in ("iniciar", "start"):
            if not ctx.author.guild_permissions.administrator:
                return await ctx.send(embed=embed_error("❌ Só admins."))
            election = PoliticalEngine.start_election(gid, ctx.channel.id)
            if not election:
                return await ctx.send(embed=embed_error("❌ Falha ao iniciar."))
            return await ctx.send(embed=embed_success(
                "🗳️ Eleição iniciada! Use `.eleicao candidatar`."
            ))

        if action in ("candidatar", "candidatar-se", "run"):
            result = PoliticalEngine.apply_candidacy(gid, ctx.author.id)
            if "error" in result:
                errors = {
                    "no_active_election": "Nenhuma eleição ativa.",
                    "campaign_ended": "Campanha encerrada.",
                    "already_candidate": "Você já é candidato.",
                    "reelection_disabled": "Reeleição desativada.",
                    "insufficient_funds": f"Precisa de {self._fmt(gid, result.get('needed', 0))}.",
                }
                return await ctx.send(embed=embed_error(
                    f"❌ {errors.get(result['error'], result['error'])}"
                ))
            return await ctx.send(embed=embed_success(
                f"✅ Candidatura registrada!\n"
                f"💸 Custo: {self._fmt(gid, result['cost'])}\n"
                f"⏰ Campanha termina: <t:{int(result['campaign_ends'].timestamp())}:R>"
            ))

        if action in ("votar", "vote"):
            if not member:
                return await ctx.send(embed=embed_error("❌ Uso: `.eleicao votar @candidato`"))
            result = PoliticalEngine.cast_vote(gid, ctx.author.id, member.id)
            if "error" in result:
                errors = {
                    "no_active_election": "Nenhuma eleição ativa.",
                    "campaign_not_ended": "Campanha não terminou.",
                    "voting_ended": "Votação encerrada.",
                    "candidate_not_found": "Candidato não encontrado.",
                    "already_voted": "Você já votou.",
                }
                return await ctx.send(embed=embed_error(
                    f"❌ {errors.get(result['error'], result['error'])}"
                ))
            return await ctx.send(embed=embed_success(f"🗳️ Voto em {member.mention}!"))

        if action in ("finalizar", "finish"):
            if not ctx.author.guild_permissions.administrator:
                return await ctx.send(embed=embed_error("❌ Só admins."))
            result = PoliticalEngine.finalize_election(gid)
            if "error" in result:
                return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
            return await ctx.send(embed=embed_success(
                f"🏆 Eleição finalizada!\n"
                f"👑 Presidente: <@{result['winner_id']}>\n"
                f"🗳️ Votos: {result['votes']}"
            ))

        if action in ("impeachment", "impeach"):
            result = PoliticalEngine.vote_impeachment(gid, ctx.author.id)
            if "error" in result:
                return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
            if result.get("impeached"):
                return await ctx.send(embed=embed_warning(
                    f"⚖️ **PRESIDENTE IMPEACHADO!**\nVotos: {result['votes']}"
                ))
            return await ctx.send(embed=embed_success(
                f"⚖️ Voto registrado.\n📊 {result['votes']}/{result['needed']}"
            ))

        await ctx.send(embed=embed_error("❌ Ação inválida."))

    # ============================================================
    # GOV INFO
    # ============================================================

    @commands.command(name="govinfo", aliases=["governoinfo"])
    async def gov_info(self, ctx):
        gid = ctx.guild.id
        president = PoliticalEngine.get_current_president(gid)
        ministers = PoliticalEngine.get_ministers(gid)

        if not president:
            return await ctx.send(embed=embed_info(
                "🏛️ Nenhum presidente. Use `.eleicao iniciar`."
            ))

        embed = discord.Embed(
            title="🏛️ GOVERNO ATUAL",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="👑 Presidente",
                        value=f"<@{president['user_id']}>", inline=True)
        if president.get("term_end"):
            embed.add_field(name="⏰ Mandato até",
                            value=f"<t:{int(president['term_end'].timestamp())}:R>",
                            inline=True)
        embed.add_field(name="🗳️ Votos",
                        value=str(president.get("votes_received", 0)), inline=True)

        if ministers:
            lines = [f"• **{m['role'].title()}**: <@{m['user_id']}>" for m in ministers]
            embed.add_field(name="🎖️ Ministros", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="🎖️ Ministros", value="*Nenhum*", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="govnomear", aliases=["nomear"])
    async def gov_appoint(self, ctx, member: discord.Member, role: str):
        result = PoliticalEngine.appoint_minister(
            ctx.guild.id, ctx.author.id, member.id, role.lower()
        )
        if "error" in result:
            errors = {
                "not_president": "Só o presidente pode nomear.",
                "invalid_role": f"Cargos: {', '.join(result.get('valid', []))}",
                "appointment_disabled": "Nomeação desativada.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))
        await ctx.send(embed=embed_success(
            f"🎖️ {member.mention} nomeado **{role.title()}**!"
        ))

    @commands.command(name="govdemitir", aliases=["demitirministro"])
    async def gov_dismiss(self, ctx, role: str):
        if PoliticalEngine.dismiss_minister(ctx.guild.id, ctx.author.id, role.lower()):
            await ctx.send(embed=embed_success(f"🎖️ Ministro de **{role.title()}** demitido."))
        else:
            await ctx.send(embed=embed_error("❌ Falha ao demitir."))

    @commands.command(name="govhistoria", aliases=["govhist"])
    async def gov_history(self, ctx):
        history = PoliticalEngine.get_government_history(ctx.guild.id, 10)
        if not history:
            return await ctx.send(embed=embed_info("📋 Nenhum governo anterior."))

        embed = discord.Embed(
            title="📜 HISTÓRICO DE GOVERNOS",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        for h in history:
            start = h.get("started_at")
            end = h.get("ended_at")
            start_str = start.strftime("%d/%m/%Y") if hasattr(start, "strftime") else "?"
            end_str = end.strftime("%d/%m/%Y") if hasattr(end, "strftime") else "?"
            reason = h.get("reason", "fim de mandato")
            embed.add_field(
                name=f"<@{h['user_id']}>",
                value=f"{start_str} → {end_str}\n*{reason}*",
                inline=False,
            )
        await ctx.send(embed=embed)

    # ============================================================
    # POLÍTICAS
    # ============================================================

    @commands.command(name="policies", aliases=["politicas"])
    async def policies(self, ctx):
        gid = ctx.guild.id
        active = PolicyEngine.list_active(gid)
        proposed = PolicyEngine.list_proposed(gid)

        embed = discord.Embed(
            title="📋 POLÍTICAS ECONÔMICAS",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )

        if active:
            lines = []
            for p in active[:5]:
                ptype = POLICY_TYPES.get(p["type"], {})
                emoji = ptype.get("emoji", "📋")
                name = ptype.get("name", p["type"])
                exp = p.get("expires_at")
                exp_str = f"<t:{int(exp.timestamp())}:R>" if exp else "—"
                lines.append(f"{emoji} **{name}** `{str(p['_id'])[:8]}` — {exp_str}")
            embed.add_field(name="✅ Ativas", value="\n".join(lines), inline=False)

        if proposed:
            lines = []
            for p in proposed[:5]:
                ptype = POLICY_TYPES.get(p["type"], {})
                emoji = ptype.get("emoji", "📋")
                name = ptype.get("name", p["type"])
                lines.append(f"{emoji} **{name}** `{str(p['_id'])[:8]}`")
            embed.add_field(name="⏳ Propostas", value="\n".join(lines), inline=False)

        if not active and not proposed:
            embed.description = "Nenhuma política ativa ou proposta."

        embed.add_field(
            name="💡 Tipos disponíveis",
            value="\n".join(f"`{k}` — {v['name']}" for k, v in POLICY_TYPES.items()),
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="propose", aliases=["propor"])
    async def propose(self, ctx, policy_type: str, *, params: str = ""):
        gid = ctx.guild.id
        params_dict = {}

        if params:
            for pair in params.split(","):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.isdigit():
                        v = int(v)
                    else:
                        try:
                            v = float(v)
                        except ValueError:
                            pass
                    params_dict[k] = v

        result = PolicyEngine.propose(gid, ctx.author.id, policy_type, params_dict)
        if "error" in result:
            errors = {
                "disabled": "Políticas desativadas.",
                "invalid_type": f"Tipo inválido. Use: `{', '.join(result.get('valid', []))}`",
                "not_minister": "Só ministros podem propor.",
                "max_policies": "Máximo atingido.",
                "cooldown": "Aguarde antes de propor.",
                "insufficient_treasury": f"Tesouro insuficiente ({self._fmt(gid, result.get('cost', 0))}).",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))

        await ctx.send(embed=embed_success(
            f"📋 Política proposta!\n"
            f"🆔 `{result['policy_id'][:8]}`\n"
            f"⏳ Aguardando aprovação."
        ))

    @commands.command(name="approve", aliases=["aprovar"])
    async def approve(self, ctx, policy_id: str):
        result = PolicyEngine.approve(ctx.guild.id, ctx.author.id, policy_id)
        if "error" in result:
            errors = {
                "not_president": "Só o presidente pode aprovar.",
                "invalid_id": "ID inválido.",
                "not_found": "Política não encontrada.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))
        await ctx.send(embed=embed_success(
            f"✅ Política **{result['type']}** aprovada!\n"
            f"⏰ Expira: <t:{int(result['expires_at'].timestamp())}:R>"
        ))

    @commands.command(name="reject", aliases=["rejeitar"])
    async def reject(self, ctx, policy_id: str):
        result = PolicyEngine.reject(ctx.guild.id, ctx.author.id, policy_id)
        if "error" in result:
            return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
        await ctx.send(embed=embed_warning("❌ Política rejeitada."))

    # ============================================================
    # TESOURO
    # ============================================================

    @commands.command(name="treasury", aliases=["tesouro"])
    async def treasury(self, ctx):
        gid = ctx.guild.id
        stats = TreasuryEngine.get_stats(gid)
        history = TreasuryEngine.get_history(gid, 10)

        embed = discord.Embed(
            title="💰 TESOURO PÚBLICO",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💵 Saldo",
                        value=self._fmt(gid, stats["balance"]), inline=True)
        embed.add_field(name="📈 Arrecadado",
                        value=self._fmt(gid, stats["total_collected"]), inline=True)
        embed.add_field(name="📉 Gasto",
                        value=self._fmt(gid, stats["total_spent"]), inline=True)

        if history:
            lines = []
            for h in history[:8]:
                ts = h.get("timestamp")
                ts_str = ts.strftime("%d/%m %H:%M") if hasattr(ts, "strftime") else "?"
                emoji = "🟢" if h["type"] == "income" else "🔴"
                desc = h.get("source") or h.get("reason", "—")
                lines.append(f"{emoji} {self._fmt(gid, h['amount'])} — {desc[:40]} ({ts_str})")
            embed.add_field(name="📋 Histórico", value="\n".join(lines), inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="taxes", aliases=["impostos"])
    async def taxes(self, ctx):
        gid = ctx.guild.id
        config = TaxEngine.get_config(gid)
        stats = TaxEngine.get_stats(gid, 24)

        embed = discord.Embed(
            title="💸 IMPOSTOS",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💼 Renda",
                        value=f"{config.get('income_tax', 0)*100:.1f}%", inline=True)
        embed.add_field(name="🔁 Transferência",
                        value=f"{config.get('transfer_tax', 0)*100:.1f}%", inline=True)
        embed.add_field(name="💎 Riqueza",
                        value=f"{config.get('wealth_tax', 0)*100:.1f}%", inline=True)
        embed.add_field(name="📊 Mercado",
                        value=f"{config.get('market_tax', 0)*100:.1f}%", inline=True)
        embed.add_field(name="💰 Dividendos",
                        value=f"{config.get('dividend_tax', 0)*100:.1f}%", inline=True)
        embed.add_field(name="🎯 Isenção",
                        value=self._fmt(gid, config.get("min_balance_to_tax", 0)),
                        inline=True)

        if stats:
            lines = [f"**{t}**: {self._fmt(gid, d['total'])} ({d['count']}x)"
                     for t, d in stats.items()]
            embed.add_field(name="📊 Arrecadado (24h)", value="\n".join(lines), inline=False)

        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("GovernmentCommands") is None:
        await bot.add_cog(GovernmentCommands(bot))
