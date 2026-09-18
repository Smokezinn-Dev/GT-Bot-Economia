# ============================================================
# MAIN.PY - v7.0 (CORRIGIDO)
# ============================================================

import asyncio
import logging
import sys
import time

import discord
from discord.ext import commands

from config import (
    DISCORD_TOKEN, PREFIX, GUILD_IDS, ENABLE_DEBUG,
    MEMORY_GUARD_MB, LOG_LEVEL,
)
from database import init_db, warmup
from utils import GuildGate, memory_mb, memory_guard


# ============================================================
# LOGGING
# ============================================================

log_level = getattr(logging, (LOG_LEVEL or "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("gtbot")

if ENABLE_DEBUG:
    logging.getLogger("discord").setLevel(logging.DEBUG)
else:
    logging.getLogger("discord").setLevel(logging.WARNING)


# ============================================================
# PREFIX DINÂMICO
# ============================================================

def get_prefix(bot, message):
    default_prefix = PREFIX or "."
    if not message.guild:
        return [default_prefix, "$", ">"]
    try:
        custom = GuildGate.get_prefix(message.guild.id, default_prefix)
    except Exception:
        custom = default_prefix
    prefixes = [custom, default_prefix, "$", ">"]
    return list(dict.fromkeys(prefixes))


# ============================================================
# BOT
# ============================================================

class GTBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.reactions = True

        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            case_insensitive=True,
            help_command=None,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="🌍 economia global | .help7"
            ),
            status=discord.Status.online,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False,
            ),
        )

        # ============================================================
        # COGS (só arquivos COM setup() — nunca engines)
        # ============================================================

        # v6.2
        self.cogs_v6 = [
            "commands_control",
            "commands_branding",
            "commands_backup",
            "commands_economy_core",
            "commands_economy_admin",
            "commands_economy_earn",
            "commands_economy_shop",
            "commands_economy_achievements",
            "commands_economy_events",
            "commands_economy_games",
            "commands_economy_games_extra",
            "commands_economy_gambling",
            "commands_economy_sinks",
            "commands_economy_social",
            "commands_economy_market",
            "commands_economy_missions",
        ]

        # v7.0 — Fase 1 (só o que é Cog)
        self.cogs_v7_fase1 = [
            "economy_tick",           # Cog
            "commands_president",      # Cog
            # ❌ price_engine     → ENGINE (não tem setup)
            # ❌ inflation_engine → ENGINE (não tem setup)
        ]

        # v7.0 — Fase 2
        self.cogs_v7_fase2 = [
            "commands_companies",      # Cog
            # ❌ resource_engine  → ENGINE
            # ❌ job_engine       → ENGINE
            # ❌ company_engine   → ENGINE
        ]

        # v7.0 — Fase 3
        self.cogs_v7_fase3 = [
            "commands_credit",         # Cog
            # ❌ credit_engine    → ENGINE
            # ❌ bank_engine      → ENGINE
            # ❌ central_bank     → ENGINE
        ]

        # v7.0 — Fase 4
        self.cogs_v7_fase4 = [
            "commands_market_v7",      # Cog
            # ❌ market_engine    → ENGINE
            # ❌ commodity_engine → ENGINE
            # ❌ futures_engine   → ENGINE
        ]

        # v7.0 — Fase 5
        self.cogs_v7_fase5 = [
            "commands_government",     # Cog
            # ❌ political_engine → ENGINE
            # ❌ policy_engine    → ENGINE
            # ❌ treasury_engine  → ENGINE
            # ❌ tax_engine       → ENGINE
        ]

        # v7.0 — Fase 6
        self.cogs_v7_fase6 = [
            "commands_global",         # Cog
            # ❌ currency_engine  → ENGINE
            # ❌ trade_engine     → ENGINE
            # ❌ diplomacy_engine → ENGINE
        ]

        # v7.0 — Fase 7
        self.cogs_v7_fase7 = [
            "commands_realestate",     # Cog
            # ❌ realestate_engine → ENGINE
            # ❌ rent_engine       → ENGINE
            # ❌ mortgage_engine   → ENGINE
        ]

        # v7.0 — Fase 8
        self.cogs_v7_fase8 = [
            "commands_admin_v7",       # Cog
            # ❌ dashboard_engine → ENGINE
            # ❌ balance_engine   → ENGINE
        ]

        self._startup_time = time.time()

    async def setup_hook(self):
        log.info("🔧 Carregando cogs...")
        await self._load_all_cogs()

        log.info("🔗 Sincronizando slash commands...")
        await self._sync_commands()

    async def _load_all_cogs(self):
        all_cogs = (
            self.cogs_v6 +
            self.cogs_v7_fase1 +
            self.cogs_v7_fase2 +
            self.cogs_v7_fase3 +
            self.cogs_v7_fase4 +
            self.cogs_v7_fase5 +
            self.cogs_v7_fase6 +
            self.cogs_v7_fase7 +
            self.cogs_v7_fase8
        )

        loaded = 0
        failed = 0
        skipped = 0

        for ext in all_cogs:
            try:
                await self.load_extension(ext)
                loaded += 1
                if ENABLE_DEBUG:
                    log.debug(f"  ✅ {ext}")
            except commands.ExtensionAlreadyLoaded:
                skipped += 1
                log.debug(f"  ⏭️ {ext}")
            except Exception as e:
                failed += 1
                log.error(f"  ❌ {ext} — {type(e).__name__}: {e}")

        log.info(f"📦 Cogs: {loaded} carregados, {skipped} já existiam, {failed} falharam")

    async def _sync_commands(self):
        try:
            if GUILD_IDS:
                for gid in GUILD_IDS:
                    guild = discord.Object(id=int(gid))
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    log.info(f"  ✅ {len(synced)} slash em guild {gid}")
            else:
                synced = await self.tree.sync()
                log.info(f"  ✅ {len(synced)} slash globais")
        except Exception as e:
            log.warning(f"⚠️ Sync slash: {e}")

    async def on_ready(self):
        uptime = time.time() - self._startup_time
        mem = memory_mb()

        log.info("=" * 60)
        log.info(f"✅ BOT ONLINE: {self.user}")
        log.info(f"📡 Guilds: {len(self.guilds)}")
        log.info(f"👥 Users: {sum(g.member_count or 0 for g in self.guilds)}")
        log.info(f"⚡ Cogs: {len(self.cogs)}")
        log.info(f"📝 Comandos: {len(self.commands)}")
        log.info(f"💾 RAM: {mem:.1f} MB")
        log.info(f"⏱️ Startup: {uptime:.1f}s")
        log.info("=" * 60)

        await self._init_guilds_v7()

    async def _init_guilds_v7(self):
        try:
            from resource_engine import ResourceEngine
            from commodity_engine import CommodityEngine
            from currency_engine import CurrencyEngine

            for guild in self.guilds:
                try:
                    ResourceEngine.ensure_resources(guild.id)
                    CommodityEngine.ensure_commodities(guild.id)
                    CurrencyEngine.get_currency(guild.id)
                except Exception as e:
                    log.warning(f"⚠️ Init v7 {guild.id}: {e}")
        except Exception:
            pass

    async def on_message(self, message):
        if message.author.bot:
            return

        if not message.guild:
            try:
                await self.process_commands(message)
            except Exception:
                pass
            return

        ctx = await self.get_context(message)
        if not ctx.valid:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        try:
            if GuildGate.is_maintenance(guild_id):
                role_ids = [r.id for r in message.author.roles]
                if not GuildGate.is_bypassed(guild_id, user_id, role_ids):
                    return

            cmd_name = ctx.command.name if ctx.command else ""
            if cmd_name and GuildGate.is_command_off(guild_id, cmd_name):
                role_ids = [r.id for r in message.author.roles]
                if not GuildGate.is_bypassed(guild_id, user_id, role_ids):
                    return

            if cmd_name and GuildGate.is_command_off_channel(
                guild_id, cmd_name, message.channel.id
            ):
                role_ids = [r.id for r in message.author.roles]
                if not GuildGate.is_bypassed(guild_id, user_id, role_ids):
                    return
        except Exception:
            pass

        try:
            await self.process_commands(message)
        except Exception as e:
            log.error(f"Erro process_commands: {e}")

    async def on_command_error(self, ctx, error):
        from embeds import embed_error, embed_warning

        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingPermissions):
            try:
                await ctx.send(embed=embed_error(
                    f"❌ Sem permissão: `{', '.join(error.missing_permissions)}`"
                ), delete_after=10)
            except Exception:
                pass
            return

        if isinstance(error, commands.MissingRequiredArgument):
            try:
                await ctx.send(embed=embed_warning(
                    f"⚠️ Falta argumento: `{error.param.name}`"
                ), delete_after=10)
            except Exception:
                pass
            return

        if isinstance(error, commands.BadArgument):
            try:
                await ctx.send(embed=embed_error(
                    f"❌ Argumento inválido: {error}"
                ), delete_after=10)
            except Exception:
                pass
            return

        if isinstance(error, commands.CommandOnCooldown):
            try:
                await ctx.send(embed=embed_warning(
                    f"⏳ Aguarde {error.retry_after:.1f}s"
                ), delete_after=5)
            except Exception:
                pass
            return

        if isinstance(error, commands.CheckFailure):
            return

        log.error(f"Erro em {ctx.command}: {type(error).__name__}: {error}")
        if ENABLE_DEBUG:
            import traceback
            traceback.print_exception(type(error), error, error.__traceback__)

        try:
            await ctx.send(embed=embed_error("❌ Erro interno."), delete_after=10)
        except Exception:
            pass

    async def on_guild_join(self, guild):
        log.info(f"➕ Entrou em: {guild.name} ({guild.id})")
        try:
            from resource_engine import ResourceEngine
            from commodity_engine import CommodityEngine
            from currency_engine import CurrencyEngine
            ResourceEngine.ensure_resources(guild.id)
            CommodityEngine.ensure_commodities(guild.id)
            CurrencyEngine.get_currency(guild.id)
        except Exception:
            pass

    async def on_guild_remove(self, guild):
        log.info(f"➖ Saiu de: {guild.name} ({guild.id})")


# ============================================================
# INICIALIZAÇÃO
# ============================================================

async def main():
    log.info("🔌 Conectando MongoDB...")
    try:
        init_db()
        if warmup():
            log.info("✅ MongoDB OK")
        else:
            log.warning("⚠️ MongoDB warmup falhou")
    except Exception as e:
        log.error(f"❌ Falha MongoDB: {e}")
        sys.exit(1)

    bot = GTBot()

    async def memory_watchdog():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                if memory_guard(MEMORY_GUARD_MB):
                    log.warning(f"⚠️ RAM alta ({memory_mb():.1f}MB) — GC")
            except Exception:
                pass
            await asyncio.sleep(300)

    try:
        async with bot:
            bot.loop.create_task(memory_watchdog())
            await bot.start(DISCORD_TOKEN)
    except KeyboardInterrupt:
        log.info("🛑 Encerrando...")
    except Exception as e:
        log.error(f"❌ Erro fatal: {e}")
        if ENABLE_DEBUG:
            import traceback
            traceback.print_exception(type(e), e, e.__traceback__)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot encerrado.")
    except Exception as e:
        print(f"❌ Erro: {e}")
        sys.exit(1)
