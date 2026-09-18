# ============================================================
# COMMANDS_CONTROL.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional

from config import PREFIX
from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from utils import GuildGate, SlashCtxAdapter

MODULE_DESCRIPTIONS = {
    "economy": "💰 Economia base (balance, daily, pay, ranking)",
    "earn": "📈 Ganhos (prestige, invest, streak)",
    "shop": "🏪 Loja e inventário",
    "games": "🎮 Jogos customizados",
    "gambling": "🎰 Apostas (flip, slots, roleta)",
    "events": "🎉 Eventos com multiplicadores",
    "achievements": "🏆 Conquistas automáticas",
    "social": "🏢 Guildas, casamento, PvP",
    "market": "📈 Bolsa e portfólio",
    "missions": "📅 Missões diárias",
    "sinks": "💸 Leilão e loteria",
    "backup": "💾 Backup/restore",
    "branding": "🎨 Personalização do bot",
}


class ControlModuleSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        state = GuildGate.get_module_state(guild_id)
        options = []
        for mod, desc in MODULE_DESCRIPTIONS.items():
            is_on = state.get(mod, True)
            options.append(discord.SelectOption(
                label=f"{'✅' if is_on else '❌'} {mod}",
                value=mod,
                description=desc[:100]
            ))
        super().__init__(placeholder="Selecione um módulo para alternar...", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        module = self.values[0]
        state = GuildGate.get_module_state(self.guild_id)
        current = state.get(module, True)
        GuildGate.set_module(self.guild_id, module, not current)
        new_state = "ativado" if not current else "desativado"
        await interaction.response.send_message(
            embed=embed_success(f"✅ Módulo **{module}** {new_state}!"),
            ephemeral=True
        )


class ControlViewFull(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.add_item(ControlModuleSelect(guild_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=embed_error("❌ Apenas administradores."), ephemeral=True)
            return False
        return True


class ControlCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="control", aliases=["painel", "panel"])
    @commands.has_permissions(administrator=True)
    async def control(self, ctx):
        embed = discord.Embed(
            title="🎛️ CONTROLE TOTAL",
            description=(
                "Este painel controla **tudo** do bot de economia neste servidor.\n\n"
                "**Comandos disponíveis:**\n"
                f"• `.control` — Este painel\n"
                f"• `.controlmodules` — Ativar/desativar módulos\n"
                f"• `.controlcommands` — Desativar comandos\n"
                f"• `.controlprefix <novo>` — Mudar prefixo\n"
                f"• `.controlmaintenance on/off` — Modo manutenção\n"
                f"• `.controlbypass @cargo` — Cargo que ignora tudo\n"
                f"• `.controlstate` — Estado atual"
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    @commands.command(name="controlmodules", aliases=["modules"])
    @commands.has_permissions(administrator=True)
    async def control_modules(self, ctx):
        state = GuildGate.get_module_state(ctx.guild.id)
        embed = discord.Embed(
            title="🎛️ MÓDULOS",
            description="Selecione abaixo para alternar:",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        on = [k for k, v in state.items() if v and k in MODULE_DESCRIPTIONS]
        off = [k for k, v in state.items() if not v and k in MODULE_DESCRIPTIONS]
        if on:
            embed.add_field(name="✅ Ativos", value=", ".join(f"`{m}`" for m in on), inline=False)
        if off:
            embed.add_field(name="❌ Desativados", value=", ".join(f"`{m}`" for m in off), inline=False)
        await ctx.send(embed=embed, view=ControlViewFull(ctx.guild.id))

    @app_commands.command(name="control", description="🎛️ Painel de controle total")
    @app_commands.default_permissions(administrator=True)
    async def control_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎛️ CONTROLE TOTAL",
            description="Use `.controlmodules` para gerenciar módulos.",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        await interaction.response.send_message(
            embed=embed, view=ControlViewFull(interaction.guild.id), ephemeral=True)

    @commands.command(name="controltoggle")
    @commands.has_permissions(administrator=True)
    async def control_toggle(self, ctx, module: str, state: str = "on"):
        module = module.lower()
        if module not in MODULE_DESCRIPTIONS:
            return await ctx.send(embed=embed_error(
                f"❌ Módulo inválido. Use um de:\n`{', '.join(MODULE_DESCRIPTIONS.keys())}`"))
        enabled = state.lower() in ("on", "true", "1", "sim", "ativar")
        GuildGate.set_module(ctx.guild.id, module, enabled)
        await ctx.send(embed=embed_success(
            f"✅ Módulo **{module}** {'ativado' if enabled else 'desativado'}!"))

    @commands.command(name="controlcommands", aliases=["disabledcmds"])
    @commands.has_permissions(administrator=True)
    async def control_commands(self, ctx):
        disabled = GuildGate.get_disabled_commands(ctx.guild.id)
        embed = discord.Embed(
            title="📋 Comandos Desativados",
            description=(
                "**Como usar:**\n"
                f"• `.controlcmd <nome> off` — desativa\n"
                f"• `.controlcmd <nome> on` — reativa\n"
                f"• `.controlcmd <nome> channel #canal` — desativa em canal\n"
            ),
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        if disabled:
            embed.add_field(name="Desativados",
                            value=", ".join(f"`{c}`" for c in sorted(disabled)), inline=False)
        else:
            embed.add_field(name="Desativados", value="*Nenhum*", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="controlcmd")
    @commands.has_permissions(administrator=True)
    async def control_cmd(self, ctx, command: str, action: str = "off",
                          channel: discord.TextChannel = None):
        command = command.lower()
        action = action.lower()

        if action == "channel" and channel:
            GuildGate.set_channel_lock(ctx.guild.id, command, channel.id, True)
            return await ctx.send(embed=embed_success(
                f"✅ Comando `{command}` desativado em {channel.mention}"))
        if action == "unchannel" and channel:
            GuildGate.set_channel_lock(ctx.guild.id, command, channel.id, False)
            return await ctx.send(embed=embed_success(
                f"✅ Comando `{command}` liberado em {channel.mention}"))

        disabled = action in ("off", "disable", "desativar")
        GuildGate.set_command(ctx.guild.id, command, disabled)
        await ctx.send(embed=embed_success(
            f"✅ Comando `{command}` {'desativado' if disabled else 'reativado'}!"))

    @commands.command(name="controlprefix")
    @commands.has_permissions(administrator=True)
    async def control_prefix(self, ctx, prefix: str = None):
        if not prefix:
            current = GuildGate.get_prefix(ctx.guild.id, ".")
            return await ctx.send(embed=embed_info(f"🔧 Prefixo atual: `{current}`"))
        if len(prefix) > 3:
            return await ctx.send(embed=embed_error("❌ Prefixo muito longo (máx 3)."))
        GuildGate.set_prefix(ctx.guild.id, prefix)
        await ctx.send(embed=embed_success(f"✅ Prefixo alterado para `{prefix}`"))

    @commands.command(name="controlmaintenance", aliases=["maintenance", "manut"])
    @commands.has_permissions(administrator=True)
    async def control_maintenance(self, ctx, state: str = "on"):
        enabled = state.lower() in ("on", "true", "1", "sim", "ativar")
        GuildGate.set_maintenance(ctx.guild.id, enabled)
        await ctx.send(embed=embed_warning(
            f"🛠️ Modo manutenção **{'ativado' if enabled else 'desativado'}**!"))

    @commands.command(name="controlbypass")
    @commands.has_permissions(administrator=True)
    async def control_bypass(self, ctx, target: str = None, action: str = "add"):
        if target is None:
            return await ctx.send(embed=embed_info(
                f"Uso: `.controlbypass @cargo/user add/remove`"))

        if target.startswith("<@&") and target.endswith(">"):
            role_id = int(target[3:-1])
            if action.lower() in ("add", "adicionar"):
                GuildGate.add_bypass(ctx.guild.id, "role", role_id)
                return await ctx.send(embed=embed_success(
                    f"✅ Cargo <@&{role_id}> agora ignora manutenção/bloqueios."))
            GuildGate.remove_bypass(ctx.guild.id, "role", role_id)
            return await ctx.send(embed=embed_success(
                f"✅ Cargo <@&{role_id}> removido."))

        if target.startswith("<@") and target.endswith(">"):
            user_id = int(target[2:-1].split("!")[-1])
            if action.lower() in ("add", "adicionar"):
                GuildGate.add_bypass(ctx.guild.id, "user", user_id)
                return await ctx.send(embed=embed_success(
                    f"✅ Usuário <@{user_id}> agora ignora tudo."))
            GuildGate.remove_bypass(ctx.guild.id, "user", user_id)
            return await ctx.send(embed=embed_success(
                f"✅ Usuário <@{user_id}> removido."))

    @commands.command(name="controlstate", aliases=["cstate"])
    @commands.has_permissions(administrator=True)
    async def control_state(self, ctx):
        state = GuildGate.get_module_state(ctx.guild.id)
        disabled = GuildGate.get_disabled_commands(ctx.guild.id)
        prefix = GuildGate.get_prefix(ctx.guild.id, ".")
        maint = GuildGate.is_maintenance(ctx.guild.id)
        bypass_roles = GuildGate.get_bypass_roles(ctx.guild.id)
        bypass_users = GuildGate.get_bypass_users(ctx.guild.id)

        embed = discord.Embed(title="📊 ESTADO ATUAL", color=discord.Color.blue(),
                              timestamp=datetime.utcnow())
        embed.add_field(name="🔧 Prefixo", value=f"`{prefix}`", inline=True)
        embed.add_field(name="🛠️ Manutenção", value="✅ ON" if maint else "❌ OFF", inline=True)
        embed.add_field(name="📋 Comandos desativados", value=str(len(disabled)), inline=True)
        embed.add_field(
            name="Módulos ON",
            value=", ".join(f"`{m}`" for m, v in state.items()
                            if v and m in MODULE_DESCRIPTIONS) or "*Nenhum*",
            inline=False
        )
        embed.add_field(
            name="Módulos OFF",
            value=", ".join(f"`{m}`" for m, v in state.items()
                            if not v and m in MODULE_DESCRIPTIONS) or "*Nenhum*",
            inline=False
        )
        if bypass_roles:
            embed.add_field(name="Cargos bypass",
                            value=", ".join(f"<@&{r}>" for r in bypass_roles), inline=False)
        if bypass_users:
            embed.add_field(name="Users bypass",
                            value=", ".join(f"<@{u}>" for u in bypass_users), inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("ControlCommands") is None:
        await bot.add_cog(ControlCommands(bot))