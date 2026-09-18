# ============================================================
# COMMANDS_CREDIT.PY - v7.0 Fase 3
# ============================================================
# Comandos do jogador para:
#   • Ver score / pegar empréstimo
#   • Pagar parcelas
#   • Abrir conta em banco
#   • Depositar / sacar
#   • Criar banco
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from credit_engine import CreditEngine
from bank_engine import BankEngine
from central_bank import CentralBank
from utils import SlashCtxAdapter


class CreditCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # HELP
    # ============================================================

    @commands.command(name="credit", aliases=["credito", "cred"])
    async def credit(self, ctx):
        embed = discord.Embed(
            title="💳 SISTEMA DE CRÉDITO",
            description=(
                "**Empréstimos:**\n"
                "• `.score` — seu score de crédito\n"
                "• `.loan <valor> [parcelas]` — pegar empréstimo\n"
                "• `.myloans` — seus empréstimos ativos\n"
                "• `.payloan <id>` — pagar parcela\n\n"
                "**Bancos:**\n"
                "• `.banks` — listar bancos\n"
                "• `.bank account <id>` — abrir conta\n"
                "• `.bank deposit <id> <valor>` — depositar\n"
                "• `.bank withdraw <id> <valor>` — sacar\n"
                "• `.bank create <nome> <capital>` — criar banco\n\n"
                "**Banco Central:**\n"
                "• `.selic` — taxa básica de juros\n"
                "• `.monetary` — política monetária"
            ),
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        await ctx.send(embed=embed)

    # ============================================================
    # SCORE
    # ============================================================

    @commands.command(name="score", aliases=["creditscore", "pontuacao"])
    async def score(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        gid = ctx.guild.id
        uid = member.id

        score = CreditEngine.get_score(gid, uid)
        tier = CreditEngine.get_score_tier(gid, score)
        rate = CreditEngine.get_base_rate(gid, score)
        total_debt = CreditEngine.get_total_debt(gid, uid)
        active = CreditEngine.get_active_loans(gid, uid)
        doc = CreditEngine.get_score_doc(gid, uid)

        tier_labels = {
            "excellent": "🌟 Excelente",
            "great": "✨ Ótimo",
            "good": "👍 Bom",
            "fair": "😐 Regular",
            "poor": "⚠️ Ruim",
        }

        embed = discord.Embed(
            title=f"💳 Score de {member.display_name}",
            description=f"**{score}** / 1000 — {tier_labels[tier]}",
            color=discord.Color.gold() if score >= 700 else
                  discord.Color.blue() if score >= 500 else
                  discord.Color.orange() if score >= 300 else
                  discord.Color.red(),
            timestamp=datetime.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="📊 Taxa de juros",
                        value=f"{rate*100:.1f}% por parcela",
                        inline=True)
        embed.add_field(name="💰 Dívida atual",
                        value=self._fmt(gid, total_debt),
                        inline=True)
        embed.add_field(name="📋 Empréstimos ativos",
                        value=str(len(active)),
                        inline=True)
        embed.add_field(name="📈 Total emprestado",
                        value=self._fmt(gid, int(doc.get("total_borrowed", 0))),
                        inline=True)
        embed.add_field(name="✅ Empréstimos quitados",
                        value=str(int(doc.get("loans_repaid", 0))),
                        inline=True)
        embed.add_field(name="❌ Calotes",
                        value=str(int(doc.get("loans_defaulted", 0))),
                        inline=True)
        await ctx.send(embed=embed)

    # ============================================================
    # EMPRÉSTIMO
    # ============================================================

    @commands.command(name="loan", aliases=["emprestimo", "pegar"])
    async def loan(self, ctx, amount: int, installments: int = None):
        gid = ctx.guild.id
        uid = ctx.author.id

        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))

        check = CreditEngine.can_borrow(gid, uid, amount)
        if not check.get("ok"):
            reasons = {
                "credit_disabled": "Sistema de crédito desativado.",
                "amount_too_low": "Valor muito baixo.",
                "amount_too_high": "Valor muito alto.",
                "too_many_active_loans": "Você já tem empréstimos ativos.",
                "score_too_low": f"Score muito baixo ({check.get('score')}).",
                "debt_ratio_exceeded": "Dívida máxima atingida.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {reasons.get(check['reason'], 'Não é possível emprestar.')}"
            ))

        loan_doc = CreditEngine.create_loan(gid, uid, amount, installments)
        if not loan_doc:
            return await ctx.send(embed=embed_error("❌ Falha ao criar empréstimo."))

        embed = discord.Embed(
            title="💳 EMPRÉSTIMO APROVADO!",
            description=f"Você recebeu **{self._fmt(gid, amount)}**",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="🆔 ID",
                        value=f"`{str(loan_doc['_id'])[:8]}`", inline=True)
        embed.add_field(name="📊 Taxa",
                        value=f"{loan_doc['rate']*100:.1f}% por parcela",
                        inline=True)
        embed.add_field(name="📅 Parcelas",
                        value=str(loan_doc['installments']), inline=True)
        embed.add_field(name="💰 Total a pagar",
                        value=self._fmt(gid, loan_doc['total_due']),
                        inline=True)
        embed.add_field(name="💵 Por parcela",
                        value=self._fmt(gid, loan_doc['per_installment']),
                        inline=True)
        embed.set_footer(text="Use .payloan <id> para pagar")
        await ctx.send(embed=embed)

    @commands.command(name="myloans", aliases=["meusemprestimos"])
    async def my_loans(self, ctx):
        loans = CreditEngine.get_active_loans(ctx.guild.id, ctx.author.id)
        if not loans:
            return await ctx.send(embed=embed_info("✅ Você não tem empréstimos ativos."))

        embed = discord.Embed(
            title="📋 Seus empréstimos",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        for loan in loans:
            status_emoji = "✅" if loan["status"] == "active" else "⚠️"
            remaining = int(loan["total_due"]) - int(loan["paid_amount"])
            embed.add_field(
                name=f"{status_emoji} `{str(loan['_id'])[:8]}`",
                value=(
                    f"💰 Falta: {self._fmt(ctx.guild.id, remaining)}\n"
                    f"📅 Parcelas: {loan['paid_installments']}/{loan['installments']}\n"
                    f"⏰ Próximo: <t:{int(loan['next_due_at'].timestamp())}:R>"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="payloan", aliases=["pagaremprestimo"])
    async def pay_loan(self, ctx, loan_id: str, amount: int = None):
        result = CreditEngine.pay_installment(ctx.guild.id, ctx.author.id, loan_id, amount)
        if "error" in result:
            errors = {
                "invalid_id": "ID inválido.",
                "not_found": "Empréstimo não encontrado.",
                "insufficient_balance": f"Saldo insuficiente. Precisa de {self._fmt(ctx.guild.id, result['needed'])}.",
                "payment_failed": "Falha no pagamento.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], 'Erro desconhecido.')}"
            ))

        if result["status"] == "paid":
            await ctx.send(embed=embed_success(
                f"🎉 **Empréstimo quitado!**\n"
                f"Pago: {self._fmt(ctx.guild.id, result['paid'])}"
            ))
        else:
            await ctx.send(embed=embed_success(
                f"✅ Parcela paga!\n"
                f"💵 Valor: {self._fmt(ctx.guild.id, result['paid'])}\n"
                f"📅 Restante: {self._fmt(ctx.guild.id, result['remaining'])}"
            ))

    # ============================================================
    # BANCOS
    # ============================================================

    @commands.command(name="banks", aliases=["bancos"])
    async def banks(self, ctx):
        banks = BankEngine.list_banks(ctx.guild.id)
        if not banks:
            return await ctx.send(embed=embed_info(
                "🏦 Nenhum banco registrado.\n"
                "Use `.bank create <nome> <capital>` para criar."
            ))

        embed = discord.Embed(
            title="🏦 BANCOS DISPONÍVEIS",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        for b in banks:
            embed.add_field(
                name=f"🏦 {b.get('name', '?')}",
                value=(
                    f"`{str(b['_id'])[:8]}`\n"
                    f"💰 Capital: {self._fmt(ctx.guild.id, int(b.get('capital', 0)))}\n"
                    f"💵 Depósitos: {self._fmt(ctx.guild.id, int(b.get('deposits', 0)))}\n"
                    f"📤 Emprestado: {self._fmt(ctx.guild.id, int(b.get('loans_out', 0)))}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="bankcreate", aliases=["criarbanco"])
    async def bank_create(self, ctx, name: str, capital: int):
        gid = ctx.guild.id
        uid = ctx.author.id

        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))

        bank = BankEngine.create_bank(gid, uid, name, capital)
        if not bank:
            config = BankEngine.get_config(gid)
            min_cap = int(config.get("min_bank_capital", 50000))
            cost = int(config.get("bank_creation_cost", 25000))
            return await ctx.send(embed=embed_error(
                f"❌ Falha ao criar banco.\n"
                f"Requisitos:\n"
                f"• Capital mínimo: {self._fmt(gid, min_cap)}\n"
                f"• Taxa de criação: {self._fmt(gid, cost)}\n"
                f"• Sem banco existente"
            ))

        await ctx.send(embed=embed_success(
            f"🏦 Banco **{name}** criado!\n"
            f"🆔 `{str(bank['_id'])[:8]}`\n"
            f"💰 Capital: {self._fmt(gid, capital)}"
        ))

    @commands.command(name="bankdeposit", aliases=["depositar"])
    async def bank_deposit(self, ctx, bank_id: str, amount: int):
        result = BankEngine.deposit(ctx.guild.id, ctx.author.id, bank_id, amount)
        if "error" in result:
            return await ctx.send(embed=embed_error(f"❌ Erro: {result['error']}"))
        await ctx.send(embed=embed_success(
            f"💵 Depositado: {self._fmt(ctx.guild.id, result['deposited'])}\n"
            f"💼 Saldo na conta: {self._fmt(ctx.guild.id, result['account_balance'])}"
        ))

    @commands.command(name="bankwithdraw", aliases=["sacar"])
    async def bank_withdraw(self, ctx, bank_id: str, amount: int):
        result = BankEngine.withdraw(ctx.guild.id, ctx.author.id, bank_id, amount)
        if "error" in result:
            return await ctx.send(embed=embed_error(f"❌ Erro: {result['error']}"))
        await ctx.send(embed=embed_success(
            f"💸 Sacado: {self._fmt(ctx.guild.id, result['withdrawn'])}"
        ))

    @commands.command(name="bankmy", aliases=["minhaconta"])
    async def bank_my(self, ctx):
        db = get_connection()
        accounts = list(db["bank_accounts"].find({
            "guild_id": ctx.guild.id,
            "type": "client",
            "owner_id": ctx.author.id,
            "active": True,
        }))
        if not accounts:
            return await ctx.send(embed=embed_info("📋 Você não tem contas bancárias."))

        embed = discord.Embed(
            title="💼 Suas contas bancárias",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        for acc in accounts:
            bank = BankEngine._get_bank(ctx.guild.id, acc.get("bank_id", ""))
            bname = bank.get("name", "?") if bank else "?"
            embed.add_field(
                name=f"🏦 {bname}",
                value=f"💵 Saldo: {self._fmt(ctx.guild.id, int(acc.get('balance', 0)))}",
                inline=True,
            )
        await ctx.send(embed=embed)

    # ============================================================
    # BANCO CENTRAL
    # ============================================================

    @commands.command(name="selic", aliases=["taxa"])
    async def selic(self, ctx):
        gid = ctx.guild.id
        selic = CentralBank.get_selic(gid)
        reserve = CentralBank.get_reserve_requirement(gid)
        mult = BankEngine.get_money_multiplier(gid)
        supply = CentralBank.get_money_supply_estimate(gid)

        embed = discord.Embed(
            title="🏛️ POLÍTICA MONETÁRIA",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="📊 Selic",
                        value=f"{selic*100:.2f}%",
                        inline=True)
        embed.add_field(name="🏦 Reserva obrigatória",
                        value=f"{reserve*100:.1f}%",
                        inline=True)
        embed.add_field(name="💹 Multiplicador bancário",
                        value=f"{mult}x",
                        inline=True)
        embed.add_field(name="💰 Moeda estimada em circulação",
                        value=self._fmt(gid, supply),
                        inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="centralbank", aliases=["bc"])
    @commands.has_permissions(administrator=True)
    async def central_bank(self, ctx, action: str = None, amount: int = 0):
        gid = ctx.guild.id
        if not action:
            ops = CentralBank.get_ops_history(gid, 10)
            embed = discord.Embed(
                title="🏛️ BANCO CENTRAL",
                description=(
                    "**Comandos:**\n"
                    "• `.centralbank selic <taxa>` — fixar Selic\n"
                    "• `.centralbank emit <valor> [@user]` — emitir moeda\n"
                    "• `.centralbank qe <valor>` — Quantitative Easing\n"
                    "• `.centralbank tighten <valor>` — Tightening\n"
                    "• `.centralbank reserve <ratio>` — reserva obrigatória\n"
                ),
                color=discord.Color.gold(),
                timestamp=datetime.utcnow(),
            )
            if ops:
                lines = []
                for op in ops[:5]:
                    ts = op.get("timestamp")
                    ts_str = ts.strftime("%d/%m %H:%M") if hasattr(ts, "strftime") else "?"
                    lines.append(f"`{op.get('type', '?')}` {op.get('amount', 0)} — {ts_str}")
                embed.add_field(name="📋 Últimas operações",
                                value="\n".join(lines), inline=False)
            return await ctx.send(embed=embed)

        if action == "selic":
            rate = amount / 100.0
            new_rate = CentralBank.set_selic(gid, rate)
            return await ctx.send(embed=embed_success(
                f"🏛️ Selic definida: **{new_rate*100:.2f}%**"
            ))

        if action == "emit":
            result = CentralBank.emit_money(gid, amount, ctx.author.id, "Emissão manual")
            if "error" in result:
                return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
            return await ctx.send(embed=embed_success(
                f"💰 Emitido: {self._fmt(gid, amount)}"
            ))

        if action == "qe":
            result = CentralBank.quantitative_easing(gid, amount)
            if "error" in result:
                return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
            return await ctx.send(embed=embed_success(
                f"📈 QE: {self._fmt(gid, amount)}\n"
                f"📉 Nova Selic: {result['new_selic']*100:.2f}%"
            ))

        if action == "tighten":
            result = CentralBank.tightening(gid, amount)
            return await ctx.send(embed=embed_success(
                f"📉 Tightening: {self._fmt(gid, amount)}\n"
                f"📈 Nova Selic: {result['new_selic']*100:.2f}%"
            ))

        if action == "reserve":
            ratio = amount / 100.0
            CentralBank.set_reserve_requirement(gid, ratio)
            return await ctx.send(embed=embed_success(
                f"🏦 Reserva obrigatória: **{ratio*100:.1f}%**"
            ))

        await ctx.send(embed=embed_error("❌ Ação inválida."))


async def setup(bot):
    if bot.get_cog("CreditCommands") is None:
        await bot.add_cog(CreditCommands(bot))