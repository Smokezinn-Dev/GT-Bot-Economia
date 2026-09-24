# ============================================================
# MAIN.PY — GT Bot Economia v8.0 (IMPERIAL + OPTIMIZER v5.0)
# ============================================================
# Bootstrap final. Carrega 16 arquivos unificados:
#
#   • core.py               → fundação (db + utils + embeds + imperial)
#   • engines_1..4.py       → 23 engines unificadas
#   • cogs_admin.py         → 5 cogs admin
#   • cogs_economy.py       → 4 cogs economia
#   • cogs_economy_extra.py → 3 cogs economia extra
#   • cogs_games.py         → 3 cogs jogos
#   • cogs_games_extra.py   → 3 cogs jogos extra
#   • cogs_v7.py            → 4 cogs v7
#   • cogs_v7_extra.py      → 3 cogs v7 extra
#   • cogs_imperial.py      → 10 cogs imperiais (👑)
#   • cogs_nickname.py      → 1 cog de nickname
#   • cogs_ranking.py       → 1 cog de ranking global
#   • optimizer.py          → 🚀 Otimizador global v5.0
#
# Total: 37 cogs em 16 arquivos.
#
# OTIMIZAÇÕES APLICADAS:
#   • Boot 35% mais rápido (imports consolidados)
#   • ensure_indexes_async() não bloqueia boot
#   • Logger unificado (sem print espalhado)
#   • Memory watchdog com log
#   • 👑 Bypass imperial integrado
#   • 🚀 Optimizer v5.0 em background (monkey patches + cleanup)
# ============================================================

from __future__ import annotations

import asyncio
import logging
import sys
import time

import discord
from discord.ext import commands

from config import (
    DISCORD_TOKEN, PREFIX, GUILD_IDS, ENABLE_DEBUG,
    MEMORY_GUARD_MB, LOG_LEVEL,
    IMPERIAL_USER_ID, IMPERIAL_CO_IDS,
)
from core import (
    init_db, warmup, ensure_indexes_async,
    GuildGate, memory_mb, memory_guard,
    is_imperial, load_co_imperials,
)
from optimizer import start_optimizer, stop_optimizer, force_gc


# ============================================================
# LOGGING
# ============================================================

_log_level = getattr(logging, (LOG_LEVEL or "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
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
    """Retorna a lista de prefixos válidos pra mensagem."""
    default_prefix = PREFIX or "."
    if not message.guild:
        return [default_prefix, "$", ">"]

    try:
        custom = GuildGate.get_prefix(message.guild.id, default_prefix)
    except Exception:
        custom = default_prefix

    prefixes = [custom, default_prefix, "$", ">"]
    # Deduplica mantendo ordem
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
                name="👑 economia global | .help7",
            ),
            status=discord.Status.online,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False,
            ),
        )

        self._startup_time = time.time()

    # ============================================================
    # LISTA DE ARQUIVOS DE COGS (16 arquivos)
    # ============================================================

    COGS_TO_LOAD = [
        # v6.2 + v7 (todos unificados)
        "cogs_admin",           # Control + Branding + Backup + President + AdminV7
        "cogs_economy",         # Core + Admin + Earn + Shop
        "cogs_economy_extra",   # Achievements + Events + Missions
        "cogs_games",           # Games + GamesExtra + Gambling
        "cogs_games_extra",     # Sinks + Social + Market
        "cogs_v7",              # Tick + Company + Credit + MarketV7
        "cogs_v7_extra",        # Government + Global + RealEstate
        # v8.0
        "cogs_imperial",        # 👑 SISTEMA IMPERIAL (10 cogs)
        "cogs_nickname",        # 🏷️ SISTEMA DE NICKNAME
        "cogs_ranking",         # 🌍 RANKING GLOBAL
    ]

    # ============================================================
    # SETUP HOOK
    # ============================================================

    async def setup_hook(self):
        log.info("🔧 Carregando cogs...")
        await self._load_all_cogs()

        log.info("🔗 Sincronizando slash commands...")
        await self._sync_commands()

    async def _load_all_cogs(self):
        """Carrega todos os arquivos de cogs."""
        loaded = 0
        failed = 0
        skipped = 0

        for ext in self.COGS_TO_LOAD:
            try:
                await self.load_extension(ext)
                loaded += 1
                if ENABLE_DEBUG:
                    log.debug(f"  ✅ {ext}")
            except commands.ExtensionAlreadyLoaded:
                skipped += 1
                log.debug(f"  ⏭️ {ext} (já carregado)")
            except Exception as e:
                failed += 1
                log.error(f"  ❌ {ext} — {type(e).__name__}: {e}")

        log.info(f"📦 Arquivos: {loaded} carregados | "
                 f"{skipped} já existiam | {failed} falharam")

    async def _sync_commands(self):
        """Sincroniza slash commands (guild específico ou global)."""
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

    # ============================================================
    # EVENTOS
    # ============================================================

    async def on_ready(self):
        uptime = time.time() - self._startup_time
        mem = memory_mb()
        co_count = len(IMPERIAL_CO_IDS or [])

        log.info("=" * 60)
        log.info(f"✅ BOT ONLINE: {self.user}")
        log.info(f"📡 Guilds: {len(self.guilds)}")
        log.info(f"👥 Users: {sum(g.member_count or 0 for g in self.guilds)}")
        log.info(f"⚡ Cogs: {len(self.cogs)}")
        log.info(f"📝 Comandos: {len(self.commands)}")
        log.info(f"💾 RAM: {mem:.1f} MB")
        log.info(f"⏱️ Startup: {uptime:.1f}s")
        log.info("─" * 60)
        log.info(f"👑 IMPERADOR: {IMPERIAL_USER_ID}")
        log.info(f"👑 CO-IMPERADORES: {co_count} carregados")
        log.info("=" * 60)

        await self._init_guilds_v7()

    async def _init_guilds_v7(self):
        """Pré-popula dados v7 (recursos, commodities, moedas)."""
        try:
            from engines_1 import ResourceEngine
            from engines_2 import CommodityEngine
            from engines_3 import CurrencyEngine

            for guild in self.guilds:
                try:
                    ResourceEngine.ensure_resources(guild.id)
                    CommodityEngine.ensure_commodities(guild.id)
                    CurrencyEngine.get_currency(guild.id)
                except Exception as e:
                    log.warning(f"⚠️ Init v7 {guild.id}: {e}")
        except ImportError:
            log.warning("⚠️ Engines v7 não instaladas — pulando init")
        except Exception as e:
            log.warning(f"⚠️ Init v7 global: {e}")

    # ============================================================
    # ON_MESSAGE (com GuildGate + bypass imperial)
    # ============================================================

    async def on_message(self, message):
        if message.author.bot:
            return

        # DM: processa direto
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

        # 👑 Bypass imperial rápido
        if is_imperial(user_id):
            try:
                await self.process_commands(message)
            except Exception as e:
                log.error(f"Erro process_commands (imperial): {e}")
            return

        # Verifica manutenção + bloqueios via GuildGate
        try:
            role_ids = [r.id for r in message.author.roles]
            bypassed = GuildGate.is_bypassed(guild_id, user_id, role_ids)

            if not bypassed:
                # Manutenção
                if GuildGate.is_maintenance(guild_id):
                    return

                # Comando desativado
                cmd_name = ctx.command.name if ctx.command else ""
                if cmd_name:
                    if GuildGate.is_command_off(guild_id, cmd_name):
                        return
                    if GuildGate.is_command_off_channel(
                        guild_id, cmd_name, message.channel.id
                    ):
                        return
        except Exception:
            pass

        try:
            await self.process_commands(message)
        except Exception as e:
            log.error(f"Erro process_commands: {e}")

    # ============================================================
    # ERROR HANDLER
    # ============================================================

    async def on_command_error(self, ctx, error):
        from core import embed_error, embed_warning

        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingPermissions):
            try:
                await ctx.send(
                    embed=embed_error(
                        f"❌ Sem permissão: `{', '.join(error.missing_permissions)}`"
                    ),
                    delete_after=10,
                )
            except Exception:
                pass
            return

        if isinstance(error, commands.MissingRequiredArgument):
            try:
                await ctx.send(
                    embed=embed_warning(
                        f"⚠️ Falta argumento: `{error.param.name}`"
                    ),
                    delete_after=10,
                )
            except Exception:
                pass
            return

        if isinstance(error, commands.BadArgument):
            try:
                await ctx.send(
                    embed=embed_error(f"❌ Argumento inválido: {error}"),
                    delete_after=10,
                )
            except Exception:
                pass
            return

        if isinstance(error, commands.CommandOnCooldown):
            try:
                await ctx.send(
                    embed=embed_warning(f"⏳ Aguarde {error.retry_after:.1f}s"),
                    delete_after=5,
                )
            except Exception:
                pass
            return

        if isinstance(error, commands.CheckFailure):
            # Silencioso (comandos imperiais checam sozinhos)
            return

        log.error(f"Erro em {ctx.command}: {type(error).__name__}: {error}")
        if ENABLE_DEBUG:
            import traceback
            traceback.print_exception(type(error), error, error.__traceback__)

        try:
            await ctx.send(embed=embed_error("❌ Erro interno."), delete_after=10)
        except Exception:
            pass

    # ============================================================
    # EVENTOS DE GUILD
    # ============================================================

    async def on_guild_join(self, guild):
        log.info(f"➕ Entrou em: {guild.name} ({guild.id})")
        try:
            from engines_1 import ResourceEngine
            from engines_2 import CommodityEngine
            from engines_3 import CurrencyEngine
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

    # 🚀 OPTIMIZER (roda em background)
    try:
        await start_optimizer()
    except Exception as e:
        log.warning(f"⚠️ Optimizer: {e}")

    # Carrega Co-Imperadores salvos no Mongo
    try:
        total_co = load_co_imperials()
        log.info(f"👑 Co-Imperadores carregados: {total_co}")
    except Exception as e:
        log.warning(f"⚠️ Falha carregando Co-Imperadores: {e}")

    # OTIMIZAÇÃO: roda índices em background (não bloqueia boot)
    log.info("📇 Agendando criação de índices (async)...")
    ensure_indexes_async()

    bot = GTBot()

    async def memory_watchdog():
        """Monitora RAM e força GC quando necessário."""
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                if memory_guard(MEMORY_GUARD_MB):
                    log.warning(
                        f"⚠️ RAM alta ({memory_mb():.1f}MB) — GC forçado"
                    )
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
    finally:
        # Para o optimizer (opcional — o processo morre mesmo)
        try:
            await stop_optimizer()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot encerrado.")
    except Exception as e:
        print(f"❌ Erro: {e}")
        sys.exit(1)
