# ============================================================
# COMMANDS_REALESTATE.PY - v7.0 Fase 7
# ============================================================
# Comandos do jogador:
#   • .re — painel
#   • .regions — regiões disponíveis
#   • .buyland — comprar terreno
#   • .build — construir imóvel
#   • .mylands / .myprops — inventário
#   • .rent / .unrent — aluguel
#   • .mortgage — financiamento
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from realestate_engine import RealEstateEngine, PROPERTY_TYPES
from rent_engine import RentEngine
from mortgage_engine import MortgageEngine
from utils import SlashCtxAdapter


class RealEstateCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _fmt(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # HELP
    # ============================================================

    @commands.command(name="realestate", aliases=["re", "imoveis", "imobiliaria"])
    async def realestate(self, ctx):
        embed = discord.Embed(
            title="🏠 SISTEMA IMOBILIÁRIO",
            description=(
                "**Terrenos:**\n"
                "• `.regions` — ver regiões disponíveis\n"
                "• `.buyland <region_id>` — comprar terreno\n"
                "• `.mylands` — seus terrenos\n\n"
                "**Imóveis:**\n"
                "• `.build <land_id> <tipo>` — construir\n"
                "• `.myprops` — seus imóveis\n"
                "• `.sellprop <id>` — vender\n\n"
                "**Aluguel:**\n"
                "• `.rent <property_id> @inquilino <valor>` — alugar\n"
                "• `.myrentals` — contratos\n"
                "• `.unrent <rental_id>` — encerrar\n\n"
                "**Financiamento:**\n"
                "• `.mortgage <property_id> <meses> <entrada>`\n"
                "• `.mymortgages` — seus financiamentos\n"
                "• `.paymortgage <id>` — pagar parcela\n"
                "• `.auctions` — leilões de execução"
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await ctx.send(embed=embed)

    # ============================================================
    # REGIÕES
    # ============================================================

    @commands.command(name="regions", aliases=["regioes"])
    async def regions(self, ctx):
        RealEstateEngine.ensure_regions(ctx.guild, self.bot)
        regions = RealEstateEngine.list_regions(ctx.guild.id)
        if not regions:
            return await ctx.send(embed=embed_info(
                "📋 Nenhuma região. Crie categorias no servidor."
            ))

        embed = discord.Embed(
            title="🗺️ REGIÕES DISPONÍVEIS",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        for r in regions[:15]:
            available = int(r.get("available_lands", 0))
            total = int(r.get("total_lands", 0))
            base = int(r.get("base_land_price", 0))
            embed.add_field(
                name=f"🏙️ {r.get('name', '?')} (`{str(r['_id'])[:8]}`)",
                value=(
                    f"💰 {self._fmt(ctx.guild.id, base)}/terreno\n"
                    f"📊 {available}/{total} disponíveis\n"
                    f"📈 Multiplicador: {r.get('multiplier', 1.0):.2f}x"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="buyland", aliases=["comprarterreno"])
    async def buyland(self, ctx, region_id: str):
        gid = ctx.guild.id
        uid = ctx.author.id

        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))

        # Encontra região
        db = get_connection()
        from utils import safe_object_id
        oid = safe_object_id(region_id)
        region = None
        if oid:
            region = db["realestate_regions"].find_one({"_id": oid, "guild_id": gid})
        if not region:
            regions = list(db["realestate_regions"].find({"guild_id": gid}))
            region = next(
                (r for r in regions if str(r["_id"]).startswith(region_id)),
                None
            )
        if not region:
            return await ctx.send(embed=embed_error("❌ Região não encontrada."))

        result = RealEstateEngine.buy_land(gid, uid, region["category_id"])
        if "error" in result:
            errors = {
                "region_not_found": "Região não encontrada.",
                "no_lands_available": "Sem terrenos disponíveis.",
                "max_lands_reached": "Limite de terrenos atingido.",
                "insufficient_funds": f"Precisa de {self._fmt(gid, result.get('needed', 0))}.",
                "payment_failed": "Falha no pagamento.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))

        await ctx.send(embed=embed_success(
            f"🏞️ Terreno comprado!\n"
            f"📍 Região: **{result['region']}**\n"
            f"💰 Preço: {self._fmt(gid, result['price'])}\n"
            f"🆔 ID: `{result['land_id'][:8]}`\n"
            f"Use `.build {result['land_id'][:8]} <tipo>` pra construir."
        ))

    # ============================================================
    # CONSTRUÇÃO
    # ============================================================

    @commands.command(name="build", aliases=["construir"])
    async def build(self, ctx, land_id: str, property_type: str = None):
        gid = ctx.guild.id
        uid = ctx.author.id

        if not property_type:
            types_txt = "\n".join(
                f"{t['emoji']} `{k}` — {t['name']} (custo base {self._fmt(gid, t['base_cost'])})"
                for k, t in PROPERTY_TYPES.items()
            )
            return await ctx.send(embed=embed_info(
                f"**Tipos disponíveis:**\n{types_txt}\n\n"
                f"Use: `.build <land_id> <tipo>`"
            ))

        if EconomyManager.is_frozen(gid, uid):
            return await ctx.send(embed=embed_error("❌ Economia congelada."))

        result = RealEstateEngine.build_property(gid, uid, land_id, property_type)
        if "error" in result:
            errors = {
                "invalid_id": "ID inválido.",
                "land_not_found": "Terreno não encontrado.",
                "land_already_has_property": "Terreno já tem imóvel.",
                "invalid_type": f"Tipo inválido. Use: `{', '.join(PROPERTY_TYPES.keys())}`",
                "max_properties_reached": "Limite de imóveis atingido.",
                "missing_materials": f"Faltam recursos: {result.get('symbol')} (tem {result.get('have')}, precisa {result.get('needed')}).",
                "insufficient_funds": f"Precisa de {self._fmt(gid, result.get('needed', 0))}.",
                "payment_failed": "Falha no pagamento.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))

        meta = PROPERTY_TYPES.get(result["type"], {})
        await ctx.send(embed=embed_success(
            f"{meta.get('emoji', '🏠')} **{meta.get('name', 'Imóvel')} construído!**\n"
            f"🆔 ID: `{result['property_id'][:8]}`\n"
            f"💰 Custo: {self._fmt(gid, result['cost'])}\n"
            f"💵 Aluguel base: {self._fmt(gid, result['base_rent'])}/dia"
        ))

    # ============================================================
    # INVENTÁRIO
    # ============================================================

    @commands.command(name="mylands", aliases=["meusterrenos"])
    async def my_lands(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lands = RealEstateEngine.list_user_lands(ctx.guild.id, member.id)
        if not lands:
            return await ctx.send(embed=embed_info(
                f"📋 {member.mention} não tem terrenos."
            ))

        embed = discord.Embed(
            title=f"🏞️ Terrenos de {member.display_name}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        for land in lands[:20]:
            db = get_connection()
            from utils import safe_object_id
            region = db["realestate_regions"].find_one({"_id": safe_object_id(land.get("region_id", ""))})
            rname = region.get("name", "?") if region else "?"
            status = "🏠 Com imóvel" if land.get("has_property") else "⬜ Vazio"
            embed.add_field(
                name=f"`{str(land['_id'])[:8]}` — {rname}",
                value=f"{status}\n💰 Pago: {self._fmt(ctx.guild.id, int(land.get('price_paid', 0)))}",
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="myprops", aliases=["meusimoveis"])
    async def my_props(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        props = RealEstateEngine.list_user_properties(ctx.guild.id, member.id)
        if not props:
            return await ctx.send(embed=embed_info(
                f"📋 {member.mention} não tem imóveis."
            ))

        embed = discord.Embed(
            title=f"🏠 Imóveis de {member.display_name}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        for p in props[:15]:
            meta = PROPERTY_TYPES.get(p["type"], {})
            rented = "🔒 Alugado" if p.get("rented_to") else "🏠 Disponível"
            mortgaged = "💳 Hipotecado" if p.get("mortgaged") else ""
            embed.add_field(
                name=f"{meta.get('emoji', '🏠')} {p.get('name', '?')} `{str(p['_id'])[:8]}`",
                value=(
                    f"{rented} {mortgaged}\n"
                    f"💰 Valor: {self._fmt(ctx.guild.id, int(p.get('cost', 0)))}\n"
                    f"💵 Aluguel: {self._fmt(ctx.guild.id, int(p.get('current_rent', 0)))}/dia"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="sellprop", aliases=["venderimovel"])
    async def sell_prop(self, ctx, property_id: str):
        result = RealEstateEngine.sell_property(ctx.guild.id, ctx.author.id, property_id)
        if "error" in result:
            errors = {
                "invalid_id": "ID inválido.",
                "not_found": "Imóvel não encontrado.",
                "property_rented": "Imóvel está alugado.",
                "active_mortgage": "Imóvel tem financiamento ativo.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))
        await ctx.send(embed=embed_success(
            f"💰 Imóvel vendido!\n"
            f"💵 Valor: {self._fmt(ctx.guild.id, result['sale_value'])}\n"
            f"📊 Imposto: {self._fmt(ctx.guild.id, result['tax'])}\n"
            f"✅ Recebido: {self._fmt(ctx.guild.id, result['net'])}"
        ))

    # ============================================================
    # ALUGUEL
    # ============================================================

    @commands.command(name="rent", aliases=["alugar"])
    async def rent(self, ctx, property_id: str, tenant: discord.Member = None, rent_value: int = None):
        gid = ctx.guild.id

        if not tenant or not rent_value:
            return await ctx.send(embed=embed_error(
                "❌ Uso: `.rent <property_id> @inquilino <valor>`"
            ))

        if rent_value <= 0:
            return await ctx.send(embed=embed_error("❌ Valor inválido."))

        result = RentEngine.create_rental(gid, property_id, ctx.author.id, tenant.id, rent_value)
        if "error" in result:
            errors = {
                "same_user": "Você não pode alugar pra si mesmo.",
                "property_not_found": "Imóvel não encontrado.",
                "not_owner": "Você não é o dono.",
                "already_rented": "Imóvel já alugado.",
                "insufficient_deposit": f"Inquilino não tem caução ({self._fmt(gid, result.get('needed', 0))}).",
                "payment_failed": "Falha no pagamento.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))

        await ctx.send(embed=embed_success(
            f"🏠 **Aluguel criado!**\n"
            f"👤 Inquilino: {tenant.mention}\n"
            f"💵 Aluguel: {self._fmt(gid, result['rent'])}/dia\n"
            f"🔐 Caução: {self._fmt(gid, result['deposit'])}\n"
            f"🆔 ID: `{result['rental_id'][:8]}`"
        ))

    @commands.command(name="myrentals", aliases=["meusalugueis"])
    async def my_rentals(self, ctx):
        rentals = RentEngine.list_user_rentals(ctx.guild.id, ctx.author.id)
        if not rentals:
            return await ctx.send(embed=embed_info("📋 Sem aluguéis ativos."))

        embed = discord.Embed(
            title="📋 Seus aluguéis",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        for r in rentals[:10]:
            role = "🏠 Senhorio" if r["landlord_id"] == ctx.author.id else "👤 Inquilino"
            other = r["tenant_id"] if r["landlord_id"] == ctx.author.id else r["landlord_id"]
            missed = int(r.get("missed_payments", 0))
            missed_str = f"\n⚠️ {missed} falta(s)" if missed > 0 else ""
            embed.add_field(
                name=f"{role} `{str(r['_id'])[:8]}`",
                value=(
                    f"👤 Outro: <@{other}>\n"
                    f"💵 {self._fmt(ctx.guild.id, int(r.get('rent', 0)))}/dia\n"
                    f"⏰ <t:{int(r['next_due_at'].timestamp())}:R>{missed_str}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="unrent", aliases=["desalugar"])
    async def unrent(self, ctx, rental_id: str):
        result = RentEngine.end_rental(ctx.guild.id, rental_id, ctx.author.id)
        if "error" in result:
            return await ctx.send(embed=embed_error(f"❌ {result['error']}"))
        await ctx.send(embed=embed_success(
            f"✅ Aluguel encerrado.\n"
            f"💰 Caução devolvida: {self._fmt(ctx.guild.id, result['refunded'])}"
        ))

    # ============================================================
    # FINANCIAMENTO
    # ============================================================

    @commands.command(name="mortgage", aliases=["financiar"])
    async def mortgage(self, ctx, property_id: str, term: int, down_payment: int):
        gid = ctx.guild.id

        result = MortgageEngine.create_mortgage(
            gid, ctx.author.id, property_id, term, down_payment
        )
        if "error" in result:
            errors = {
                "invalid_id": "ID inválido.",
                "property_not_found": "Imóvel não encontrado.",
                "not_owner": "Você não é o dono.",
                "already_mortgaged": "Imóvel já financiado.",
                "down_payment_too_low": f"Entrada mínima: {self._fmt(gid, result.get('needed', 0))}.",
                "loan_too_high": f"Valor máximo: {self._fmt(gid, result.get('max', 0))}.",
                "score_too_low": f"Score muito baixo ({result.get('score')}).",
                "insufficient_down_payment": f"Saldo insuficiente ({self._fmt(gid, result.get('needed', 0))}).",
                "payment_failed": "Falha no pagamento.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))

        embed = discord.Embed(
            title="💳 FINANCIAMENTO APROVADO",
            description=f"ID: `{result['mortgage_id'][:8]}`",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💰 Emprestado",
                        value=self._fmt(gid, result['loan_amount']), inline=True)
        embed.add_field(name="📊 Taxa",
                        value=f"{result['rate']*100:.2f}%/parcela", inline=True)
        embed.add_field(name="📅 Parcelas", value=str(result['term']), inline=True)
        embed.add_field(name="💵 Por parcela",
                        value=self._fmt(gid, result['per_installment']), inline=True)
        embed.add_field(name="💰 Total",
                        value=self._fmt(gid, result['total_due']), inline=True)
        embed.set_footer(text="Pague com .paymortgage <id>")
        await ctx.send(embed=embed)

    @commands.command(name="mymortgages", aliases=["meusfinanciamentos"])
    async def my_mortgages(self, ctx):
        mortgages = MortgageEngine.get_user_mortgages(ctx.guild.id, ctx.author.id)
        if not mortgages:
            return await ctx.send(embed=embed_info("📋 Sem financiamentos ativos."))

        embed = discord.Embed(
            title="💳 Seus financiamentos",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        for m in mortgages:
            remaining = int(m.get("total_due", 0)) - int(m.get("paid_amount", 0))
            missed = int(m.get("missed_payments", 0))
            missed_str = f"\n⚠️ {missed} falta(s)" if missed > 0 else ""
            embed.add_field(
                name=f"`{str(m['_id'])[:8]}`",
                value=(
                    f"💰 Falta: {self._fmt(ctx.guild.id, remaining)}\n"
                    f"📅 {m.get('paid_installments', 0)}/{m.get('term_months', 0)}\n"
                    f"💵 Parcela: {self._fmt(ctx.guild.id, int(m.get('per_installment', 0)))}\n"
                    f"⏰ <t:{int(m['next_due_at'].timestamp())}:R>{missed_str}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(name="paymortgage", aliases=["pagarmortgage"])
    async def pay_mortgage(self, ctx, mortgage_id: str):
        result = MortgageEngine.pay_installment(ctx.guild.id, ctx.author.id, mortgage_id)
        if "error" in result:
            errors = {
                "invalid_id": "ID inválido.",
                "not_found": "Financiamento não encontrado.",
                "insufficient_funds": f"Saldo insuficiente ({self._fmt(ctx.guild.id, result.get('needed', 0))}).",
                "payment_failed": "Falha no pagamento.",
            }
            return await ctx.send(embed=embed_error(
                f"❌ {errors.get(result['error'], result['error'])}"
            ))

        if result["status"] == "paid":
            await ctx.send(embed=embed_success(
                f"🎉 **Financiamento quitado!**\n"
                f"💰 Pago: {self._fmt(ctx.guild.id, result['paid'])}"
            ))
        else:
            await ctx.send(embed=embed_success(
                f"✅ Parcela paga!\n"
                f"💵 Valor: {self._fmt(ctx.guild.id, result['paid'])}\n"
                f"📅 Restantes: {result['installments_left']}\n"
                f"💰 Falta: {self._fmt(ctx.guild.id, result['remaining'])}"
            ))

    @commands.command(name="auctions", aliases=["leiloes_imoveis"])
    async def auctions(self, ctx):
        auctions = MortgageEngine.list_active_auctions(ctx.guild.id)
        if not auctions:
            return await ctx.send(embed=embed_info("📋 Sem leilões ativos."))

        embed = discord.Embed(
            title="⚖️ LEILÕES DE IMÓVEIS",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        for a in auctions[:10]:
            embed.add_field(
                name=f"`{str(a['_id'])[:8]}` — Imóvel {a['property_id'][:8]}",
                value=(
                    f"💵 Inicial: {self._fmt(ctx.guild.id, int(a.get('start_price', 0)))}\n"
                    f"📊 Atual: {self._fmt(ctx.guild.id, int(a.get('current_bid', 0)))}\n"
                    f"⏰ <t:{int(a['ends_at'].timestamp())}:R>"
                ),
                inline=True,
            )
        embed.set_footer(text="Use .bidland <id> <valor> para dar lance")
        await ctx.send(embed=embed)

    @commands.command(name="bidland", aliases=["lanceland"])
    async def bid_land(self, ctx, auction_id: str, amount: int):
        gid = ctx.guild.id
        uid = ctx.author.id
        if amount <= 0:
            return await ctx.send(embed=embed_error("❌ Valor inválido."))

        db = get_connection()
        from utils import safe_object_id
        oid = safe_object_id(auction_id)
        auc = None
        if oid:
            auc = db["realestate_auctions"].find_one({"_id": oid, "guild_id": gid, "active": True})
        if not auc:
            auctions = list(db["realestate_auctions"].find({"guild_id": gid, "active": True}))
            auc = next((a for a in auctions if str(a["_id"]).startswith(auction_id)), None)
        if not auc:
            return await ctx.send(embed=embed_error("❌ Leilão não encontrado."))

        if datetime.utcnow() >= auc["ends_at"]:
            return await ctx.send(embed=embed_error("❌ Leilão encerrado."))

        min_bid = max(int(auc.get("start_price", 0)), int(auc.get("current_bid", 0)) + 1)
        if amount < min_bid:
            return await ctx.send(embed=embed_error(
                f"❌ Lance mínimo: {self._fmt(gid, min_bid)}"
            ))

        balance = EconomyManager.get_balance(gid, uid)
        if balance < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))

        # Devolve pro anterior
        prev = auc.get("current_bidder")
        prev_bid = int(auc.get("current_bid", 0))
        if prev and prev_bid > 0:
            EconomyManager.add_balance(
                gid, prev, prev_bid,
                "Reembolso leilão imóvel", "auction_refund"
            )

        # Cobra novo
        if not EconomyManager.remove_balance(gid, uid, amount, "Lance leilão imóvel", "auction_bid"):
            return await ctx.send(embed=embed_error("❌ Falha no pagamento."))

        db["realestate_auctions"].update_one(
            {"_id": auc["_id"]},
            {"$set": {"current_bid": amount, "current_bidder": uid}}
        )

        await ctx.send(embed=embed_success(
            f"✅ Lance de {self._fmt(gid, amount)} registrado!"
        ))

    # ============================================================
    # PROCESSAMENTO DE LEILÕES (tick — chamado pelo tick global)
    # ============================================================

    @classmethod
    def finalize_auctions(cls, guild_id: int) -> int:
        """Finaliza leilões vencidos. Retorna quantos foram finalizados."""
        db = get_connection()
        now = datetime.utcnow()
        finished = list(db["realestate_auctions"].find({
            "guild_id": guild_id,
            "active": True,
            "ends_at": {"$lte": now},
        }))

        from commands_economy_core import EconomyManager

        count = 0
        for a in finished:
            winner = a.get("current_bidder")
            bid = int(a.get("current_bid", 0))
            debt = int(a.get("debt", 0))

            db["realestate_auctions"].update_one(
                {"_id": a["_id"]},
                {"$set": {"active": False, "finished_at": now, "winner": winner}}
            )

            prop_oid = safe_object_id(a.get("property_id", ""))

            if winner and bid > 0 and prop_oid:
                # Winner recebe o imóvel
                db["realestate_properties"].update_one(
                    {"_id": prop_oid},
                    {
                        "$set": {
                            "owner_id": winner,
                            "active": True,
                            "auctioned": False,
                        }
                    }
                )
                # Sobra vai pro antigo dono (se houver)
                surplus = bid - debt
                if surplus > 0:
                    EconomyManager.add_balance(
                        guild_id, a["original_owner"], surplus,
                        "Sobra leilão imóvel", "auction_surplus"
                    )
            else:
                # Sem lance: imóvel volta pro banco/estado
                if prop_oid:
                    db["realestate_properties"].update_one(
                        {"_id": prop_oid},
                        {"$set": {"active": False, "seized_by_state": True}}
                    )

            count += 1

        return count


async def setup(bot):
    if bot.get_cog("RealEstateCommands") is None:
        await bot.add_cog(RealEstateCommands(bot))