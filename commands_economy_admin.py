# ============================================================
# COMMANDS_ECONOMY_ADMIN.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
import re
from datetime import datetime, timedelta
from typing import Optional

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from utils import SlashCtxAdapter


class EconomyAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _format(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    async def _check_admin(self, ctx_or_interaction) -> bool:
        if isinstance(ctx_or_interaction, commands.Context):
            return ctx_or_interaction.author.guild_permissions.administrator
        return ctx_or_interaction.user.guild_permissions.administrator

    # ============================================================
    # CONFIGURAÇÃO
    # ============================================================

    @commands.command(name="economyconfig", aliases=["ecoconfig"])
    @commands.has_permissions(administrator=True)
    async def economy_config(self, ctx: commands.Context, key: str = None, *, value: str = None):
        config = EconomyManager.get_config(ctx.guild.id)

        if not key:
            embed = discord.Embed(
                title="⚙️ Configuração Econômica",
                color=discord.Color.blue(), timestamp=datetime.utcnow())
            embed.add_field(name="💵 Nome",
                            value=config.get("currency_name", "Moeda"), inline=True)
            embed.add_field(name="🎨 Emoji",
                            value=config.get("currency_emoji", "💰"), inline=True)
            embed.add_field(name="🎁 Daily",
                            value=str(config.get("daily_bonus", 100)), inline=True)
            embed.add_field(name="📈 Multiplicador",
                            value=str(config.get("bonus_multiplier", 1.0)), inline=True)
            embed.add_field(name="📉 Taxa Transferência",
                            value=f"{config.get('tax_rate', 0)}%", inline=True)
            embed.add_field(name="↕️ Min / Max Transfer",
                            value=f"{config.get('min_transfer', 1)} / {config.get('max_transfer', 1000000)}",
                            inline=True)
            embed.add_field(name="🔒 Economia Congelada",
                            value="Sim" if config.get("economy_frozen") else "Não",
                            inline=True)
            embed.add_field(name="👤 Usuários Congelados",
                            value=str(len(config.get("frozen_users", []))), inline=True)
            total = EconomyManager.get_total_balance(ctx.guild.id)
            embed.add_field(name="💰 Total em Circulação",
                            value=self._format(ctx.guild.id, total), inline=False)
            embed.set_footer(text="Use .economyconfig <chave> <valor>")
            return await ctx.send(embed=embed)

        valid_keys = {
            "currency_name": str,
            "currency_emoji": str,
            "daily_bonus": int,
            "staff_role": int,
            "log_channel": int,
            "tax_rate": float,
            "min_transfer": int,
            "max_transfer": int,
            "bonus_multiplier": float,
            "economy_frozen": bool,
        }

        if key not in valid_keys:
            return await ctx.send(embed=embed_error(
                f"❌ Chaves válidas:\n`{', '.join(valid_keys.keys())}`"))

        if value is None:
            return await ctx.send(embed=embed_error("❌ Forneça um valor!"))

        try:
            expected = valid_keys[key]
            if expected is bool:
                parsed = value.lower() in ("true", "1", "sim", "on", "yes", "ativar")
            elif expected is int:
                match = re.search(r"<#?(\d+)>", value) or re.search(r"<@&?(\d+)>", value)
                parsed = int(match.group(1)) if match else int(value)
            elif expected is float:
                parsed = float(value)
            else:
                parsed = value.strip()
        except Exception:
            return await ctx.send(embed=embed_error("❌ Valor inválido para essa chave."))

        EconomyManager.update_config(ctx.guild.id, key, parsed)
        await ctx.send(embed=embed_success(f"✅ `{key}` definido como `{parsed}`"))

    @app_commands.command(name="economyconfig", description="⚙️ Configura a economia do servidor")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(key="Chave de configuração", value="Novo valor")
    async def economy_config_slash(self, interaction: discord.Interaction,
                                   key: str, value: str):
        await self.economy_config(SlashCtxAdapter(interaction), key, value=value)

    # ============================================================
    # DAR / REMOVER / DEFINIR
    # ============================================================

    @commands.command(name="ecogive", aliases=["give", "addmoney"])
    @commands.has_permissions(administrator=True)
    async def eco_give(self, ctx: commands.Context, member: discord.Member,
                       amount: int, *, reason: str = "Ajuste admin"):
        if amount <= 0:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))
        if amount > 10_000_000:
            return await ctx.send(embed=embed_error("❌ Valor máximo por comando: 10.000.000"))

        new_balance = EconomyManager.add_balance(
            ctx.guild.id, member.id, amount,
            description=reason, source="admin_give")
        await ctx.send(embed=embed_success(
            f"✅ {self._format(ctx.guild.id, amount)} dados a {member.mention}\n"
            f"💰 Novo saldo: **{self._format(ctx.guild.id, new_balance)}**"
        ))

    @app_commands.command(name="ecogive", description="💰 Dá dinheiro a um usuário")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Membro", amount="Valor", reason="Motivo")
    async def eco_give_slash(self, interaction: discord.Interaction,
                             member: discord.Member, amount: int,
                             reason: str = "Ajuste admin"):
        if amount <= 0:
            return await interaction.response.send_message(
                embed=embed_error("❌ Valor deve ser positivo!"), ephemeral=True)
        new_balance = EconomyManager.add_balance(
            interaction.guild.id, member.id, amount,
            description=reason, source="admin_give")
        await interaction.response.send_message(embed=embed_success(
            f"✅ {self._format(interaction.guild.id, amount)} dados a {member.mention}\n"
            f"💰 Novo saldo: **{self._format(interaction.guild.id, new_balance)}**"
        ))

    @commands.command(name="ecoremove", aliases=["removemoney"])
    @commands.has_permissions(administrator=True)
    async def eco_remove(self, ctx: commands.Context, member: discord.Member,
                         amount: int, *, reason: str = "Ajuste admin"):
        if amount <= 0:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))

        current = EconomyManager.get_balance(ctx.guild.id, member.id)
        if current < amount:
            return await ctx.send(embed=embed_error(
                f"❌ {member.mention} tem apenas {self._format(ctx.guild.id, current)}"))

        success = EconomyManager.remove_balance(
            ctx.guild.id, member.id, amount,
            description=reason, source="admin_remove")
        if success:
            new_balance = EconomyManager.get_balance(ctx.guild.id, member.id)
            await ctx.send(embed=embed_warning(
                f"✅ {self._format(ctx.guild.id, amount)} removidos de {member.mention}\n"
                f"💰 Novo saldo: **{self._format(ctx.guild.id, new_balance)}**"
            ))
        else:
            await ctx.send(embed=embed_error("❌ Falha ao remover saldo."))

    @app_commands.command(name="ecoremove", description="💰 Remove dinheiro de um usuário")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Membro", amount="Valor", reason="Motivo")
    async def eco_remove_slash(self, interaction: discord.Interaction,
                               member: discord.Member, amount: int,
                               reason: str = "Ajuste admin"):
        if amount <= 0:
            return await interaction.response.send_message(
                embed=embed_error("❌ Valor deve ser positivo!"), ephemeral=True)
        current = EconomyManager.get_balance(interaction.guild.id, member.id)
        if current < amount:
            return await interaction.response.send_message(
                embed=embed_error(
                    f"❌ {member.mention} tem apenas "
                    f"{self._format(interaction.guild.id, current)}"),
                ephemeral=True)
        EconomyManager.remove_balance(
            interaction.guild.id, member.id, amount, reason, "admin_remove")
        new_balance = EconomyManager.get_balance(interaction.guild.id, member.id)
        await interaction.response.send_message(embed=embed_warning(
            f"✅ {self._format(interaction.guild.id, amount)} removidos de {member.mention}\n"
            f"💰 Novo saldo: **{self._format(interaction.guild.id, new_balance)}**"
        ))

    @commands.command(name="ecoset", aliases=["setmoney"])
    @commands.has_permissions(administrator=True)
    async def eco_set(self, ctx: commands.Context, member: discord.Member,
                      amount: int, *, reason: str = "Ajuste admin"):
        if amount < 0:
            return await ctx.send(embed=embed_error("❌ Valor não pode ser negativo!"))

        current = EconomyManager.get_balance(ctx.guild.id, member.id)
        diff = amount - current

        if diff > 0:
            EconomyManager.add_balance(ctx.guild.id, member.id, diff, reason, "admin_set")
        elif diff < 0:
            EconomyManager.remove_balance(ctx.guild.id, member.id, -diff, reason, "admin_set")
        else:
            return await ctx.send(embed=embed_info(
                f"ℹ️ {member.mention} já possui {self._format(ctx.guild.id, amount)}"))

        await ctx.send(embed=embed_success(
            f"✅ Saldo de {member.mention} definido para "
            f"**{self._format(ctx.guild.id, amount)}**"
        ))

    @app_commands.command(name="ecoset", description="💰 Define o saldo de um usuário")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Membro", amount="Novo saldo", reason="Motivo")
    async def eco_set_slash(self, interaction: discord.Interaction,
                            member: discord.Member, amount: int,
                            reason: str = "Ajuste admin"):
        if amount < 0:
            return await interaction.response.send_message(
                embed=embed_error("❌ Valor não pode ser negativo!"), ephemeral=True)
        current = EconomyManager.get_balance(interaction.guild.id, member.id)
        diff = amount - current
        if diff > 0:
            EconomyManager.add_balance(interaction.guild.id, member.id, diff, reason, "admin_set")
        elif diff < 0:
            EconomyManager.remove_balance(interaction.guild.id, member.id, -diff, reason, "admin_set")
        await interaction.response.send_message(embed=embed_success(
            f"✅ Saldo de {member.mention} definido para "
            f"**{self._format(interaction.guild.id, amount)}**"
        ))

    @commands.command(name="ecoreset")
    @commands.has_permissions(administrator=True)
    async def eco_reset(self, ctx: commands.Context, member: discord.Member):
        EconomyManager.set_balance(ctx.guild.id, member.id, 0)
        await ctx.send(embed=embed_warning(f"✅ Saldo de {member.mention} resetado para 0!"))

    @app_commands.command(name="ecoreset", description="🔄 Reseta o saldo de um usuário")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Membro")
    async def eco_reset_slash(self, interaction: discord.Interaction, member: discord.Member):
        EconomyManager.set_balance(interaction.guild.id, member.id, 0)
        await interaction.response.send_message(
            embed=embed_warning(f"✅ Saldo de {member.mention} resetado!"))

    # ============================================================
    # FREEZE
    # ============================================================

    @commands.command(name="ecofreeze")
    @commands.has_permissions(administrator=True)
    async def eco_freeze(self, ctx: commands.Context, target: str = None):
        if target is None or target.lower() in ("all", "server", "guild"):
            EconomyManager.freeze_guild(ctx.guild.id, True)
            return await ctx.send(embed=embed_warning(
                "🔒 Economia do **servidor inteiro** foi congelada!"))

        member = None
        if ctx.message and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            try:
                member = await commands.MemberConverter().convert(ctx, target)
            except Exception:
                return await ctx.send(embed=embed_error(
                    "❌ Usuário não encontrado. Use @usuário ou `all`."))

        EconomyManager.freeze_user(ctx.guild.id, member.id)
        await ctx.send(embed=embed_warning(
            f"🔒 Economia de {member.mention} foi **congelada**!"))

    @commands.command(name="ecounfreeze")
    @commands.has_permissions(administrator=True)
    async def eco_unfreeze(self, ctx: commands.Context, target: str = None):
        if target is None or target.lower() in ("all", "server", "guild"):
            EconomyManager.freeze_guild(ctx.guild.id, False)
            return await ctx.send(embed=embed_success(
                "🔓 Economia do servidor foi **descongelada**!"))

        member = None
        if ctx.message and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            try:
                member = await commands.MemberConverter().convert(ctx, target)
            except Exception:
                return await ctx.send(embed=embed_error("❌ Usuário não encontrado."))

        EconomyManager.unfreeze_user(ctx.guild.id, member.id)
        await ctx.send(embed=embed_success(
            f"🔓 Economia de {member.mention} foi **descongelada**!"))

    # ============================================================
    # AUDITORIA
    # ============================================================

    @commands.command(name="ecoaudit", aliases=["ecologs", "transactions"])
    @commands.has_permissions(administrator=True)
    async def eco_audit(self, ctx: commands.Context, member: discord.Member = None,
                        limit: int = 10):
        limit = max(1, min(limit, 25))
        db = get_connection()

        query = {"guild_id": ctx.guild.id}
        if member:
            query["user_id"] = member.id

        docs = list(db["economy_transactions"].find(query)
                    .sort("timestamp", -1).limit(limit))

        if not docs:
            return await ctx.send(embed=embed_info("📋 Nenhuma transação encontrada."))

        title = f"📋 Transações de {member.display_name}" if member else "📋 Últimas Transações"
        embed = discord.Embed(title=title, color=discord.Color.blue(),
                              timestamp=datetime.utcnow())

        for doc in docs:
            t_type = doc.get("type", "?").upper()
            amount = doc.get("amount", 0)
            desc = doc.get("description", "—")[:60]
            source = doc.get("source", "—")
            ts = doc.get("timestamp", datetime.utcnow())
            if hasattr(ts, "strftime"):
                ts_str = ts.strftime("%d/%m %H:%M")
            else:
                ts_str = str(ts)[:16]

            emoji = "🟢" if t_type == "ADD" else "🔴" if t_type == "REMOVE" else "🔄"
            embed.add_field(
                name=f"{emoji} {t_type} | {self._format(ctx.guild.id, amount)}",
                value=f"{desc}\n`{source}` • {ts_str}",
                inline=False)

        embed.set_footer(text=f"Mostrando {len(docs)} transações")
        await ctx.send(embed=embed)

    @commands.command(name="ecostats")
    @commands.has_permissions(administrator=True)
    async def eco_stats(self, ctx: commands.Context):
        db = get_connection()
        guild_id = ctx.guild.id

        total = EconomyManager.get_total_balance(guild_id)
        ranking = EconomyManager.get_ranking(guild_id, 5)
        accounts = db["economy_balances"].count_documents(
            {"guild_id": guild_id, "balance": {"$gt": 0}})

        since = datetime.utcnow() - timedelta(hours=24)
        tx_24h = db["economy_transactions"].count_documents({
            "guild_id": guild_id,
            "timestamp": {"$gte": since}
        })

        config = EconomyManager.get_config(guild_id)

        embed = discord.Embed(
            title="📊 Estatísticas da Economia",
            color=discord.Color.gold(), timestamp=datetime.utcnow())
        embed.add_field(name="💰 Total em Circulação",
                        value=self._format(guild_id, total), inline=False)
        embed.add_field(name="👥 Contas Ativas", value=str(accounts), inline=True)
        embed.add_field(name="📝 Transações (24h)", value=str(tx_24h), inline=True)
        embed.add_field(name="🔒 Status",
                        value="Congelada" if config.get("economy_frozen") else "Ativa",
                        inline=True)

        if ranking:
            top_text = "\n".join(
                f"**{i+1}.** <@{uid}> — {self._format(guild_id, bal)}"
                for i, (uid, bal) in enumerate(ranking)
            )
            embed.add_field(name="🏆 Top 5", value=top_text, inline=False)

        await ctx.send(embed=embed)

    # ============================================================
    # MANUTENÇÃO
    # ============================================================

    @commands.command(name="ecoclearcache")
    @commands.has_permissions(administrator=True)
    async def eco_clear_cache(self, ctx: commands.Context):
        EconomyManager.clear_caches()
        await ctx.send(embed=embed_success("✅ Cache da economia limpo!"))

    @commands.command(name="ecosofreset")
    @commands.has_permissions(administrator=True)
    async def eco_soft_reset(self, ctx: commands.Context, confirm: str = None):
        if confirm != "CONFIRMAR":
            return await ctx.send(embed=embed_warning(
                "⚠️ Isso vai **zerar todos os saldos** do servidor.\n"
                "Para confirmar digite: `.ecosofreset CONFIRMAR`"
            ))

        db = get_connection()
        result = db["economy_balances"].update_many(
            {"guild_id": ctx.guild.id},
            {"$set": {"balance": 0, "updated_at": datetime.utcnow()}}
        )
        EconomyManager.clear_caches()
        await ctx.send(embed=embed_success(
            f"✅ Soft-reset concluído!\nContas afetadas: **{result.modified_count}**"
        ))


async def setup(bot):
    if bot.get_cog("EconomyAdmin") is None:
        await bot.add_cog(EconomyAdmin(bot))