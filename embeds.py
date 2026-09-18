# ============================================================
# EMBEDS.PY - v6.0 (BRAND POR GUILD)
# ============================================================

import discord
from datetime import datetime
from typing import Optional

from utils import TTLCache

COLOR_SUCCESS = 0x00ff00
COLOR_ERROR = 0xff0000
COLOR_WARNING = 0xffa500
COLOR_INFO = 0x00bfff
COLOR_GOLD = 0xffd700
COLOR_BLUE = 0x3498db

_brand_cache = TTLCache(max_size=200, ttl=60)


def _get_brand(guild_id: Optional[int]) -> dict:
    if not guild_id:
        return {}
    cached = _brand_cache.get(guild_id)
    if cached is not None:
        return cached
    try:
        from database import get_connection
        doc = get_connection()["branding_config"].find_one(
            {"guild_id": guild_id}, {"color": 1, "footer": 1}) or {}
    except Exception:
        doc = {}
    _brand_cache.set(guild_id, doc)
    return doc


def invalidate_brand(guild_id: int):
    _brand_cache.invalidate(guild_id)


def _now() -> datetime:
    return datetime.utcnow()


def _apply_brand(embed: discord.Embed, guild_id: Optional[int]) -> discord.Embed:
    if not guild_id:
        return embed
    brand = _get_brand(guild_id)
    color = brand.get("color")
    footer = brand.get("footer")
    if color is not None:
        try:
            embed.color = discord.Color(int(color))
        except Exception:
            pass
    if footer:
        existing = embed.footer.text if embed.footer else None
        embed.set_footer(text=f"{footer} • {existing}" if existing else footer)
    return embed


def embed_success(desc: str) -> discord.Embed:
    return discord.Embed(title="✅ Sucesso", description=desc, color=COLOR_SUCCESS, timestamp=_now())


def embed_error(desc: str) -> discord.Embed:
    return discord.Embed(title="❌ Erro", description=desc, color=COLOR_ERROR, timestamp=_now())


def embed_warning(desc: str) -> discord.Embed:
    return discord.Embed(title="⚠️ Atenção", description=desc, color=COLOR_WARNING, timestamp=_now())


def embed_info(desc: str) -> discord.Embed:
    return discord.Embed(title="ℹ️ Informação", description=desc, color=COLOR_INFO, timestamp=_now())


def embed_guild(guild_id: int, title: str, desc: str, color: int = COLOR_INFO) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color, timestamp=_now())
    return _apply_brand(e, guild_id)