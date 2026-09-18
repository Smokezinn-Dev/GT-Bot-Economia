# ============================================================
# CONFIG.PY - GT BOT ECONOMIA GLOBAL v6.2
# Validação estrita + multi-guild + suporte a env
# ============================================================

import os
import sys
from typing import List


# ============================================================
# HELPERS
# ============================================================

def _env_str(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    return val.strip() if val else default


def _env_int(key: str, default: int = 0) -> int:
    val = os.getenv(key)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "sim", "on", "yes", "ativar")


def _env_list_int(key: str) -> List[int]:
    val = os.getenv(key, "")
    if not val:
        return []
    result = []
    for part in val.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


# ============================================================
# VALIDAÇÃO OBRIGATÓRIA
# ============================================================

def _require(key: str, value: str) -> str:
    if not value:
        print(f"❌ Variável obrigatória ausente: {key}", file=sys.stderr)
        print(f"   Configure no arquivo .env ou variáveis de ambiente.", file=sys.stderr)
        sys.exit(1)
    return value


# ============================================================
# DISCORD
# ============================================================

DISCORD_TOKEN: str = _require(
    "DISCORD_TOKEN",
    _env_str("DISCORD_TOKEN", "")
)

# Lista de IDs de guild para sync rápido de slash commands (opcional)
# Se vazio, o bot registra slash globalmente (leva ~1h pra propagar)
GUILD_IDS: List[int] = _env_list_int("GUILD_IDS")


# ============================================================
# MONGODB
# ============================================================

MONGODB_URL: str = _require(
    "MONGODB_URL",
    _env_str("MONGODB_URL", "")
)

DB_NAME: str = _env_str("DB_NAME", "gt_bot_economia")


# ============================================================
# PREFIXO
# ============================================================
# Padrão: "." (ponto)
# O bot aceita 3 prefixos simultâneos: ".", "$", ">"
# Prefixo customizado por guild via `.controlprefix <novo>`
# ============================================================

PREFIX: str = _env_str("PREFIX", ".")

# Prefixos extras que o bot também aceita (fallback)
EXTRA_PREFIXES: List[str] = ["$", ">"]


# ============================================================
# PERMISSÕES GLOBAIS
# ============================================================

# Cargo de admin global (bypass em todos os servidores)
# 0 = desativado
ADMIN_ROLE_ID: int = _env_int("ADMIN_ROLE_ID", 0)

# ID do dono do bot (bypass absoluto, acesso imperial)
# 0 = desativado
IMPERIAL_USER_ID: int = _env_int("IMPERIAL_USER_ID", 0)


# ============================================================
# DEBUG
# ============================================================

ENABLE_DEBUG: bool = _env_bool("ENABLE_DEBUG", False)


# ============================================================
# BACKUP AUTOMÁTICO
# ============================================================

BACKUP_ENABLED: bool = _env_bool("BACKUP_ENABLED", False)
BACKUP_AUTO_HOUR: int = _env_int("BACKUP_AUTO_HOUR", 4)      # UTC
BACKUP_MAX_PER_GUILD: int = _env_int("BACKUP_MAX_PER_GUILD", 10)


# ============================================================
# ECONOMIA — DEFAULTS
# ============================================================
# Estes valores são usados como fallback quando a guild não
# tem config própria em economy_config
# ============================================================

ECONOMY_DEFAULT_CURRENCY_NAME: str = _env_str("ECONOMY_DEFAULT_CURRENCY_NAME", "Moeda")
ECONOMY_DEFAULT_CURRENCY_EMOJI: str = _env_str("ECONOMY_DEFAULT_CURRENCY_EMOJI", "💰")
ECONOMY_DEFAULT_DAILY_BONUS: int = _env_int("ECONOMY_DEFAULT_DAILY_BONUS", 100)
ECONOMY_DEFAULT_TAX_RATE: float = float(_env_str("ECONOMY_DEFAULT_TAX_RATE", "0") or 0)
ECONOMY_DEFAULT_MIN_TRANSFER: int = _env_int("ECONOMY_DEFAULT_MIN_TRANSFER", 1)
ECONOMY_DEFAULT_MAX_TRANSFER: int = _env_int("ECONOMY_DEFAULT_MAX_TRANSFER", 1_000_000)
ECONOMY_DEFAULT_BONUS_MULTIPLIER: float = float(_env_str("ECONOMY_DEFAULT_BONUS_MULTIPLIER", "1.0") or 1.0)


# ============================================================
# EARN — DEFAULTS
# ============================================================

EARN_DEFAULT_PER_MESSAGE: int = _env_int("EARN_DEFAULT_PER_MESSAGE", 1)
EARN_DEFAULT_MESSAGE_DELAY: int = _env_int("EARN_DEFAULT_MESSAGE_DELAY", 8)
EARN_DEFAULT_MAX_PER_DAY: int = _env_int("EARN_DEFAULT_MAX_PER_DAY", 150)
EARN_DEFAULT_PRESTIGE_COST: int = _env_int("EARN_DEFAULT_PRESTIGE_COST", 10000)
EARN_DEFAULT_PRESTIGE_MULT: float = float(_env_str("EARN_DEFAULT_PRESTIGE_MULT", "1.12") or 1.12)


# ============================================================
# PERFORMANCE / LIMITES
# ============================================================

# Máximo de conexões no pool do MongoDB
MONGO_MAX_POOL: int = _env_int("MONGO_MAX_POOL", 5)

# Limite de RAM (MB) antes de acionar GC agressivo
MEMORY_GUARD_MB: float = float(_env_str("MEMORY_GUARD_MB", "380") or 380)

# Intervalo (segundos) do cleanup de memória nos loops
CLEANUP_INTERVAL: int = _env_int("CLEANUP_INTERVAL", 240)


# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL: str = "DEBUG" if ENABLE_DEBUG else _env_str("LOG_LEVEL", "INFO").upper()


# ============================================================
# VALIDAÇÕES FINAIS
# ============================================================

def _validate() -> None:
    """Validação de sanidade. Não bloqueia, apenas avisa."""

    warnings = []

    if not DISCORD_TOKEN:
        warnings.append("DISCORD_TOKEN vazio")

    if not MONGODB_URL:
        warnings.append("MONGODB_URL vazia")

    if not MONGODB_URL.startswith(("mongodb://", "mongodb+srv://")):
        warnings.append("MONGODB_URL não parece uma connection string válida")

    if not PREFIX:
        warnings.append("PREFIX vazio (usando '.' como padrão)")

    if len(PREFIX) > 3:
        warnings.append(f"PREFIX '{PREFIX}' é longo (máx recomendado: 3 chars)")

    if BACKUP_AUTO_HOUR < 0 or BACKUP_AUTO_HOUR > 23:
        warnings.append(f"BACKUP_AUTO_HOUR={BACKUP_AUTO_HOUR} inválido (0-23)")

    if BACKUP_MAX_PER_GUILD < 1:
        warnings.append(f"BACKUP_MAX_PER_GUILD={BACKUP_MAX_PER_GUILD} muito baixo")

    if MONGO_MAX_POOL < 1:
        warnings.append(f"MONGO_MAX_POOL={MONGO_MAX_POOL} inválido")

    if MEMORY_GUARD_MB < 100:
        warnings.append(f"MEMORY_GUARD_MB={MEMORY_GUARD_MB} muito baixo")

    if warnings:
        print("⚠️  Avisos de config:", file=sys.stderr)
        for w in warnings:
            print(f"   • {w}", file=sys.stderr)


# Roda validação no import
_validate()


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Discord
    "DISCORD_TOKEN",
    "GUILD_IDS",

    # MongoDB
    "MONGODB_URL",
    "DB_NAME",

    # Prefixo
    "PREFIX",
    "EXTRA_PREFIXES",

    # Permissões
    "ADMIN_ROLE_ID",
    "IMPERIAL_USER_ID",

    # Debug
    "ENABLE_DEBUG",
    "LOG_LEVEL",

    # Backup
    "BACKUP_ENABLED",
    "BACKUP_AUTO_HOUR",
    "BACKUP_MAX_PER_GUILD",

    # Economia
    "ECONOMY_DEFAULT_CURRENCY_NAME",
    "ECONOMY_DEFAULT_CURRENCY_EMOJI",
    "ECONOMY_DEFAULT_DAILY_BONUS",
    "ECONOMY_DEFAULT_TAX_RATE",
    "ECONOMY_DEFAULT_MIN_TRANSFER",
    "ECONOMY_DEFAULT_MAX_TRANSFER",
    "ECONOMY_DEFAULT_BONUS_MULTIPLIER",

    # Earn
    "EARN_DEFAULT_PER_MESSAGE",
    "EARN_DEFAULT_MESSAGE_DELAY",
    "EARN_DEFAULT_MAX_PER_DAY",
    "EARN_DEFAULT_PRESTIGE_COST",
    "EARN_DEFAULT_PRESTIGE_MULT",

    # Performance
    "MONGO_MAX_POOL",
    "MEMORY_GUARD_MB",
    "CLEANUP_INTERVAL",
]