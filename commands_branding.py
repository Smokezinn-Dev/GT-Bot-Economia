# ============================================================
# COMMANDS_BRANDING.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands
from datetime import datetime

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info, invalidate_brand


class BrandingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get(self, guild_id: int) -> dict:
        doc = get_connection()["branding_config"].find_one({"guild_id": guild_id}) or {}
        return doc

    @commands.command(name="branding", aliases=["brand", "personalizar"])
    @commands.has_permissions(administrator=True)
    async def branding(self, ctx):
        doc = self._get(ctx.guild.id)
        embed = discord.Embed(
            title="🎨 PERSONALIZAÇÃO DO BOT",
            description=(
                "Deixe o bot único neste servidor!\n\n"
                "**Comandos:**\n"
                "• `.branding nickname <nome>` — apelido do bot\n"
                "• `.branding color <hex>` — cor dos embeds (ex: `#ff0000`)\n"
                "• `.branding footer <texto>` — rodapé dos embeds\n"
                "• `.branding reset` — reseta tudo"
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        nick = doc.get("nickname") or "*padrão*"
        color = doc.get("color")
        color_str = f"#{color:06x}" if color else "*padrão*"
        footer = doc.get("footer") or "*padrão*"

        embed.add_field(name="📛 Apelido", value=nick, inline=True)
        embed.add_field(name="🎨 Cor", value=color_str, inline=True)
        embed.add_field(name="📝 Footer", value=footer, inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="brandingnickname", aliases=["botnick"])
    @commands.has_permissions(administrator=True)
    async def branding_nickname(self, ctx, *, nickname: str = None):
        if not nickname:
            return await ctx.send(embed=embed_error(
                "❌ Use: `.brandingnickname <nome>` ou `reset` para remover."))

        if nickname.lower() == "reset":
            get_connection()["branding_config"].update_one(
                {"guild_id": ctx.guild.id},
                {"$unset": {"nickname": ""}}, upsert=True
            )
            try:
                await ctx.guild.me.edit(nick=None)
            except Exception:
                pass
            return await ctx.send(embed=embed_success("✅ Apelido resetado."))

        if len(nickname) > 32:
            return await ctx.send(embed=embed_error("❌ Máximo 32 caracteres."))

        get_connection()["branding_config"].update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"nickname": nickname}}, upsert=True
        )
        try:
            await ctx.guild.me.edit(nick=nickname)
        except Exception as e:
            return await ctx.send(embed=embed_error(f"❌ Erro ao mudar apelido: {e}"))

        await ctx.send(embed=embed_success(f"✅ Apelido do bot definido para **{nickname}**!"))

    @commands.command(name="brandingcolor", aliases=["botcolor"])
    @commands.has_permissions(administrator=True)
    async def branding_color(self, ctx, color: str = None):
        if not color:
            return await ctx.send(embed=embed_error(
                "❌ Use: `.brandingcolor #ff0000` ou `reset`"))

        if color.lower() == "reset":
            get_connection()["branding_config"].update_one(
                {"guild_id": ctx.guild.id},
                {"$unset": {"color": ""}}, upsert=True
            )
            invalidate_brand(ctx.guild.id)
            return await ctx.send(embed=embed_success("✅ Cor resetada."))

        color = color.lstrip("#")
        try:
            color_int = int(color, 16)
        except ValueError:
            return await ctx.send(embed=embed_error(
                "❌ Cor hex inválida. Use formato `#RRGGBB`."))

        get_connection()["branding_config"].update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"color": color_int}}, upsert=True
        )
        invalidate_brand(ctx.guild.id)
        await ctx.send(embed=embed_success(
            f"✅ Cor dos embeds definida para `#{color_int:06x}`!"))

    @commands.command(name="brandingfooter", aliases=["botfooter"])
    @commands.has_permissions(administrator=True)
    async def branding_footer(self, ctx, *, footer: str = None):
        if not footer:
            return await ctx.send(embed=embed_error(
                "❌ Use: `.brandingfooter <texto>` ou `reset`"))

        if footer.lower() == "reset":
            get_connection()["branding_config"].update_one(
                {"guild_id": ctx.guild.id},
                {"$unset": {"footer": ""}}, upsert=True
            )
            invalidate_brand(ctx.guild.id)
            return await ctx.send(embed=embed_success("✅ Footer resetado."))

        if len(footer) > 200:
            return await ctx.send(embed=embed_error("❌ Máximo 200 caracteres."))

        get_connection()["branding_config"].update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"footer": footer}}, upsert=True
        )
        invalidate_brand(ctx.guild.id)
        await ctx.send(embed=embed_success(f"✅ Rodapé definido: **{footer}**"))

    @commands.command(name="brandingreset")
    @commands.has_permissions(administrator=True)
    async def branding_reset(self, ctx):
        get_connection()["branding_config"].delete_one({"guild_id": ctx.guild.id})
        invalidate_brand(ctx.guild.id)
        try:
            await ctx.guild.me.edit(nick=None)
        except Exception:
            pass
        await ctx.send(embed=embed_warning("⚠️ Personalização resetada!"))


async def setup(bot):
    if bot.get_cog("BrandingCommands") is None:
        await bot.add_cog(BrandingCommands(bot))