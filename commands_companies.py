# ============================================================
# COMMANDS_COMPANIES.PY - v7.0 Fase 2
# ============================================================
# Comandos do jogador para:
#   • Criar empresa
#   • Ver empresas
#   • Produzir, vender, pagar dividendos
#   • Contratar funcionários
#   • Comprar/vender ações
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from company_engine import CompanyEngine, DEFAULT_SECTORS
from job_engine import JobEngine
from resource_engine import ResourceEngine
from utils import SlashCtxAdapter, safe_object_id


class CompanyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # HELP
    # ============================================================

    @commands.command(name="company", aliases=["empresa", "comp"])
    async def company(self, ctx):
        """Painel principal de empresas."""
        embed = discord.Embed(
            title="🏢 SISTEMA DE EMPRESAS",
            description=(
                "**Como funciona:**\n"
                "1. Você cria uma empresa escolhendo um setor\n"
                "2. Cada tick (5min), a empresa produz automaticamente\n"
                "3. Você pode contratar funcionários pra aumentar produção\n"
                "4. Vende produtos no mercado pra ter lucro\n"
                "5. Sócios recebem dividendos\n\n"
                "**Comandos:**\n"
                "• `.company create <nome> <setor> <capital>` — criar\n"
                "• `.company my` — suas empresas\n"
                "• `.company info <id>` — detalhes\n"
                "• `.company produce <id>` — forçar produção\n"
                "• `.company sell <id> <recurso> <qtd>` — vender\n"
                "• `.company dividends <id>` — pagar dividendos\n"
                "• `.company close <id>` — fechar empresa\n\n"
                "**Setores disponíveis:**\n" +
                "\n".join(f"{s['emoji']} `{k}` — {s['name']}" for k, s in DEFAULT_SECTORS.items()) +
                "\n\n**Empregos:**\n"
                "• `.jobs` — listar vagas\n"
                "• `.jobs apply <id>` — se candidatar\n"
                "• `.jobs quit` — pedir demissão\n"
                "• `.jobs my` — seu contrato\n\n"
                "**Recursos:** `.resources`"
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await ctx.send(embed=embed)

    # ============================================================
    # CRIAR
    # ============================================================

    @commands.command(name="companycreate", aliases=["criarempresa", "ccreate"])
    async def company_create(self, ctx, name: str, sector: str, capital: int):
        gid = ctx.guild.id
        uid = ctx.author.id

        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))

        sector = sector.lower()
        if sector not in DEFAULT_SECTORS:
            return await ctx.send(embed=embed_error(
                f"❌ Setor inválido. Use: `{', '.join(DEFAULT_SECTORS.keys())}`"
            ))

        config = CompanyEngine.get_config(gid)
        cost = int(config.get("creation_cost", 10000))
        min_cap = int(config.get("min_capital", 5000))

        if capital < min_cap:
            return await ctx.send(embed=embed_error(
                f"❌ Capital mínimo: {self._fmt(gid, min_cap)}"
            ))

        total = cost + capital
        balance = EconomyManager.get_balance(gid, uid)
        if balance < total:
            return await ctx.send(embed=embed_error(
                f"❌ Você precisa de {self._fmt(gid, total)} "
                f"(taxa {self._fmt(gid, cost)} + capital {self._fmt(gid, capital)}).\n"
                f"Você tem {self._fmt(gid, balance)}."
            ))

        company = CompanyEngine.create_company(gid, uid, name, sector, capital)
        if not company:
            return await ctx.send(embed=embed_error(
                "❌ Falha ao criar empresa. Verifique limites e tente novamente."
            ))

        embed = discord.Embed(
            title="🏢 EMPRESA CRIADA!",
            description=f"**{name}** ({DEFAULT_SECTORS[sector]['emoji']} {DEFAULT_SECTORS[sector]['name']})",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="🆔 ID", value=f"`{str(company['_id'])[:8]}`", inline=True)
        embed.add_field(name="💰 Caixa", value=self._fmt(gid, capital), inline=True)
        embed.add_field(name="📈 Ações", value="100 (você possui todas)", inline=True)
        embed.set_footer(text="A empresa produz automaticamente a cada 5min")
        await ctx.send(embed=embed)

    @app_commands.command(name="companycreate", description="🏢 Cria uma empresa")
    @app_commands.describe(name="Nome", sector="Setor", capital="Capital inicial")
    async def company_create_slash(self, interaction: discord.Interaction,
                                    name: str, sector: str, capital: int):
        await self.company_create(SlashCtxAdapter(interaction), name, sector, capital)

    # ============================================================
    # LISTAR / INFO
    # ============================================================

    @commands.command(name="companymy", aliases=["minhasempresas"])
    async def company_my(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        companies = CompanyEngine.list_user_companies(ctx.guild.id, member.id)
        if not companies:
            return await ctx.send(embed=embed_info(
                f"📋 {member.mention} não possui empresas.\n"
                f"Use `.company create <nome> <setor> <capital>`"
            ))

        embed = discord.Embed(
            title=f"🏢 Empresas de {member.display_name}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        for c in companies:
            sid = DEFAULT_SECTORS.get(c.get("sector", ""), {})
            cash = int(c.get("cash", 0))
            embed.add_field(
                name=f"{sid.get('emoji', '🏢')} {c.get('name', '?')}",
                value=(
                    f"`{str(c['_id'])[:8]}`\n"
                    f"💰 Caixa: {self._fmt(ctx.guild.id, cash)}\n"
                    f"📦 Produzido: {int(c.get('total_produced', 0))}\n"
                    f"💵 Receita: {self._fmt(ctx.guild.id, int(c.get('total_revenue', 0)))}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="companyinfo", aliases=["cinfo"])
    async def company_info(self, ctx, company_id: str):
        company = CompanyEngine.get_company(ctx.guild.id, company_id)
        if not company:
            return await ctx.send(embed=embed_error("❌ Empresa não encontrada."))

        sector_key = company.get("sector", "")
        sector = DEFAULT_SECTORS.get(sector_key, {})

        embed = discord.Embed(
            title=f"{sector.get('emoji', '🏢')} {company.get('name', '?')}",
            description=f"Setor: **{sector.get('name', sector_key)}**",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="🆔 ID", value=f"`{str(company['_id'])[:8]}`", inline=True)
        embed.add_field(name="👤 Owner", value=f"<@{company['owner_id']}>", inline=True)
        embed.add_field(name="💰 Caixa",
                        value=self._fmt(ctx.guild.id, int(company.get("cash", 0))),
                        inline=True)
        embed.add_field(name="📦 Produzido",
                        value=str(int(company.get("total_produced", 0))),
                        inline=True)
        embed.add_field(name="💵 Receita",
                        value=self._fmt(ctx.guild.id, int(company.get("total_revenue", 0))),
                        inline=True)
        embed.add_field(name="💸 Custos",
                        value=self._fmt(ctx.guild.id, int(company.get("total_costs", 0))),
                        inline=True)

        # Inventário
        inv = company.get("inventory") or {}
        if inv:
            inv_lines = []
            for symbol, qty in list(inv.items())[:10]:
                if int(qty) > 0:
                    res = ResourceEngine.get_resource(ctx.guild.id, symbol)
                    name = res.get("name", symbol) if res else symbol
                    emoji = res.get("emoji", "📦") if res else "📦"
                    inv_lines.append(f"{emoji} **{name}**: {qty}")
            if inv_lines:
                embed.add_field(name="📦 Estoque",
                                value="\n".join(inv_lines),
                                inline=False)

        # Funcionários
        db = get_connection()
        emp_count = db["job_contracts"].count_documents({
            "guild_id": ctx.guild.id,
            "company_id": str(company["_id"]),
            "active": True,
        })
        embed.add_field(name="👥 Funcionários", value=str(emp_count), inline=True)

        await ctx.send(embed=embed)

    @app_commands.command(name="companyinfo", description="🏢 Info da empresa")
    @app_commands.describe(company_id="ID da empresa")
    async def company_info_slash(self, interaction: discord.Interaction, company_id: str):
        await self.company_info(SlashCtxAdapter(interaction), company_id)

    # ============================================================
    # PRODUZIR / VENDER / DIVIDENDOS
    # ============================================================

    @commands.command(name="companyproduce", aliases=["cproduce", "produzir"])
    async def company_produce(self, ctx, company_id: str):
        company = CompanyEngine.get_company(ctx.guild.id, company_id)
        if not company:
            return await ctx.send(embed=embed_error("❌ Empresa não encontrada."))

        result = CompanyEngine.produce(ctx.guild.id, company_id)

        if "error" in result:
            err = result["error"]
            if err == "missing_resources":
                return await ctx.send(embed=embed_error(
                    f"❌ Faltam recursos: {', '.join(result['missing'])}"
                ))
            if err == "insufficient_cash":
                return await ctx.send(embed=embed_error(
                    f"❌ Caixa insuficiente. Precisa de {self._fmt(ctx.guild.id, result['needed'])}."
                ))
            return await ctx.send(embed=embed_error(f"❌ Erro: {err}"))

        await ctx.send(embed=embed_success(
            f"🏭 Produzido: **{result['produced']}** unidades\n"
            f"💸 Custo: {self._fmt(ctx.guild.id, result['operating_cost'])}\n"
            f"💰 Caixa: {self._fmt(ctx.guild.id, result['cash_after'])}"
        ))

    @commands.command(name="companysell", aliases=["csell", "vender"])
    async def company_sell(self, ctx, company_id: str, symbol: str, quantity: int):
        if quantity <= 0:
            return await ctx.send(embed=embed_error("❌ Quantidade deve ser positiva."))

        result = CompanyEngine.sell_inventory(ctx.guild.id, company_id, symbol.lower(), quantity)
        if "error" in result:
            if result["error"] == "insufficient_stock":
                return await ctx.send(embed=embed_error(
                    f"❌ Estoque insuficiente. Você tem {result['have']}."
                ))
            return await ctx.send(embed=embed_error(f"❌ Erro: {result['error']}"))

        await ctx.send(embed=embed_success(
            f"💰 Vendido: **{result['sold']}x {result['symbol']}**\n"
            f"💵 Preço unitário: {self._fmt(ctx.guild.id, result['price_per_unit'])}\n"
            f"🪙 Receita total: **{self._fmt(ctx.guild.id, result['revenue'])}**\n"
            f"💰 Caixa: {self._fmt(ctx.guild.id, result['cash_after'])}"
        ))

    @commands.command(name="companydividends", aliases=["cdividends", "dividendos"])
    async def company_dividends(self, ctx, company_id: str):
        company = CompanyEngine.get_company(ctx.guild.id, company_id)
        if not company:
            return await ctx.send(embed=embed_error("❌ Empresa não encontrada."))

        if company["owner_id"] != ctx.author.id and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=embed_error("❌ Só o dono pode distribuir dividendos."))

        result = CompanyEngine.pay_dividends(ctx.guild.id, company_id)
        if "error" in result:
            if result["error"] == "no_profit":
                return await ctx.send(embed=embed_error(
                    f"❌ Sem lucro disponível. Caixa: {self._fmt(ctx.guild.id, result['cash'])}"
                ))
            return await ctx.send(embed=embed_error(f"❌ Erro: {result['error']}"))

        await ctx.send(embed=embed_success(
            f"💸 Dividendos pagos: **{self._fmt(ctx.guild.id, result['total_paid'])}**\n"
            f"👥 Para **{result['holders']}** acionista(s)."
        ))

    @commands.command(name="companyclose", aliases=["fecharempresa"])
    async def company_close(self, ctx, company_id: str):
        company = CompanyEngine.get_company(ctx.guild.id, company_id)
        if not company:
            return await ctx.send(embed=embed_error("❌ Empresa não encontrada."))

        if company["owner_id"] != ctx.author.id and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=embed_error("❌ Só o dono pode fechar."))

        db = get_connection()
        # Devolve caixa ao dono
        cash = int(company.get("cash", 0))
        if cash > 0:
            EconomyManager.add_balance(
                ctx.guild.id, company["owner_id"], cash,
                f"Fechamento: {company.get('name')}",
                "company_close"
            )

        # Demite todos
        db["job_contracts"].update_many(
            {"guild_id": ctx.guild.id, "company_id": str(company["_id"]), "active": True},
            {"$set": {"active": False, "fired_at": datetime.utcnow(), "reason": "company_closed"}}
        )
        db["companies"].update_one(
            {"_id": company["_id"]},
            {"$set": {"active": False, "closed_at": datetime.utcnow()}}
        )

        await ctx.send(embed=embed_warning(
            f"🏢 Empresa **{company.get('name')}** fechada.\n"
            f"💰 {self._fmt(ctx.guild.id, cash)} devolvidos ao dono."
        ))

    # ============================================================
    # EMPREGOS
    # ============================================================

    @commands.command(name="jobs", aliases=["empregos", "vagas"])
    async def jobs_list(self, ctx):
        jobs = JobEngine.list_jobs(ctx.guild.id)
        if not jobs:
            return await ctx.send(embed=embed_info(
                "📋 Nenhuma vaga aberta.\nDonos de empresa podem criar com `.jobcreate`."
            ))

        embed = discord.Embed(
            title="💼 VAGAS ABERTAS",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        for job in jobs[:15]:
            company = CompanyEngine.get_company(ctx.guild.id, job["company_id"])
            cname = company.get("name", "?") if company else "?"
            embed.add_field(
                name=f"`{str(job['_id'])[:8]}` — {job.get('title', '?')}",
                value=(
                    f"🏢 {cname}\n"
                    f"💰 Salário: {self._fmt(ctx.guild.id, int(job.get('salary', 0)))}/tick\n"
                    f"👥 Funcionários: {len(job.get('employees', []))}"
                ),
                inline=True,
            )
        embed.set_footer(text="Use .jobsapply <id> para se candidatar")
        await ctx.send(embed=embed)

    @commands.command(name="jobcreate", aliases=["criarvaga"])
    async def job_create(self, ctx, company_id: str, salary: int, *, title: str):
        company = CompanyEngine.get_company(ctx.guild.id, company_id)
        if not company:
            return await ctx.send(embed=embed_error("❌ Empresa não encontrada."))

        if company["owner_id"] != ctx.author.id:
            return await ctx.send(embed=embed_error("❌ Só o dono pode criar vagas."))

        job_id = JobEngine.create_job(ctx.guild.id, str(company["_id"]), title, salary)
        if not job_id:
            return await ctx.send(embed=embed_error("❌ Falha ao criar vaga."))

        await ctx.send(embed=embed_success(
            f"💼 Vaga **{title}** criada!\n"
            f"💰 Salário: {self._fmt(ctx.guild.id, salary)}/tick\n"
            f"🆔 ID: `{job_id[:8]}`"
        ))

    @commands.command(name="jobsapply", aliases=["candidatar", "aplicar"])
    async def jobs_apply(self, ctx, job_id: str):
        # Já tem contrato?
        existing = JobEngine.get_user_contract(ctx.guild.id, ctx.author.id)
        if existing:
            return await ctx.send(embed=embed_error("❌ Você já tem um emprego. Use `.jobsquit`."))

        if JobEngine.hire(ctx.guild.id, job_id, ctx.author.id):
            await ctx.send(embed=embed_success(
                f"✅ Você foi contratado! Vai receber salário a cada tick."
            ))
        else:
            await ctx.send(embed=embed_error("❌ Não foi possível se candidatar."))

    @commands.command(name="jobsquit", aliases=["demissao", "sair"])
    async def jobs_quit(self, ctx):
        if JobEngine.fire(ctx.guild.id, ctx.author.id):
            await ctx.send(embed=embed_warning("👋 Você pediu demissão."))
        else:
            await ctx.send(embed=embed_error("❌ Você não tem emprego ativo."))

    @commands.command(name="jobsmy", aliases=["meuemprego"])
    async def jobs_my(self, ctx):
        contract = JobEngine.get_user_contract(ctx.guild.id, ctx.author.id)
        if not contract:
            return await ctx.send(embed=embed_info("📋 Você não tem emprego ativo."))

        company = CompanyEngine.get_company(ctx.guild.id, contract.get("company_id", ""))
        embed = discord.Embed(
            title="💼 Seu contrato",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="🏢 Empresa",
                        value=company.get("name", "?") if company else "?",
                        inline=True)
        embed.add_field(name="💰 Salário",
                        value=self._fmt(ctx.guild.id, int(contract.get("salary", 0))) + "/tick",
                        inline=True)
        embed.add_field(name="💵 Total recebido",
                        value=self._fmt(ctx.guild.id, int(contract.get("total_earned", 0))),
                        inline=True)
        embed.add_field(name="⏱️ Ticks trabalhados",
                        value=str(int(contract.get("ticks_worked", 0))),
                        inline=True)
        await ctx.send(embed=embed)

    # ============================================================
    # RECURSOS
    # ============================================================

    @commands.command(name="resources", aliases=["recursos", "materias"])
    async def resources(self, ctx):
        ResourceEngine.ensure_resources(ctx.guild.id)
        resources = ResourceEngine.list_resources(ctx.guild.id)
        if not resources:
            return await ctx.send(embed=embed_info("📋 Nenhum recurso registrado."))

        embed = discord.Embed(
            title="⛏️ RECURSOS DISPONÍVEIS",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        for res in resources:
            embed.add_field(
                name=f"{res.get('emoji', '📦')} {res.get('name', '?')}",
                value=(
                    f"💵 {self._fmt(ctx.guild.id, int(res.get('current_price', 0)))}\n"
                    f"📦 Estoque: {int(res.get('stock', 0)):,}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    # ============================================================
    # RANKING
    # ============================================================

    @commands.command(name="companytop", aliases=["topempresas"])
    async def company_top(self, ctx):
        companies = CompanyEngine.list_guild_companies(ctx.guild.id, 10)
        if not companies:
            return await ctx.send(embed=embed_info("📋 Nenhuma empresa registrada ainda."))

        embed = discord.Embed(
            title="🏆 TOP EMPRESAS",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        for i, c in enumerate(companies):
            sid = DEFAULT_SECTORS.get(c.get("sector", ""), {})
            embed.add_field(
                name=f"{i+1}. {sid.get('emoji', '🏢')} {c.get('name', '?')}",
                value=(
                    f"💵 Receita: {self._fmt(ctx.guild.id, int(c.get('total_revenue', 0)))}\n"
                    f"👤 <@{c['owner_id']}>"
                ),
                inline=False,
            )
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("CompanyCommands") is None:
        await bot.add_cog(CompanyCommands(bot))