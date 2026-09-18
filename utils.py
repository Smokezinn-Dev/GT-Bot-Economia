# ============================================================
# UTILS.PY - v7.0 (prefixo . + SlashCtxAdapter + v7 Fase 1)
# ============================================================

from __future__ import annotations

import gc
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Optional

try:
    from bson import ObjectId
    from bson.errors import InvalidId
    _HAS_BSON = True
except Exception:
    _HAS_BSON = False
    ObjectId = None
    InvalidId = Exception

try:
    import psutil
    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False

try:
    import discord
    _HAS_DISCORD = True
except Exception:
    _HAS_DISCORD = False


def safe_object_id(value: Any) -> Optional[Any]:
    if not _HAS_BSON or value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and len(value) == 24:
        try:
            return ObjectId(value)
        except (InvalidId, ValueError, TypeError):
            return None
    return None


class TTLCache:
    __slots__ = ("max_size", "ttl", "_data", "_lock", "_hits", "_misses")

    def __init__(self, max_size: int = 500, ttl: int = 30):
        self.max_size = max_size
        self.ttl = ttl
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key):
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return None
            value, expires = item
            if now > expires:
                del self._data[key]
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key, value):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, time.monotonic() + self.ttl)
            if len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def invalidate(self, key):
        with self._lock:
            self._data.pop(key, None)

    def invalidate_prefix(self, prefix: str):
        p = str(prefix)
        with self._lock:
            for k in [k for k in self._data if str(k).startswith(p)]:
                del self._data[k]

    def clear(self):
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data), "max": self.max_size,
                "hits": self._hits, "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
            }


def retry_mongo(attempts: int = 3, base_delay: float = 0.08):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for i in range(attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if i < attempts - 1:
                        time.sleep(base_delay * (2 ** i))
            raise last_exc
        return wrapper
    return decorator


class RateLimiter:
    __slots__ = ("rate", "per", "_buckets", "_lock")

    def __init__(self, rate: int = 3, per: float = 5.0):
        self.rate = rate
        self.per = per
        self._buckets: dict = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            entry = self._buckets.get(key)
            if entry is None:
                self._buckets[key] = [now, self.rate - 1]
                if len(self._buckets) > 5000:
                    cutoff = now - self.per * 4
                    for k in [k for k, v in self._buckets.items() if v[0] < cutoff]:
                        del self._buckets[k]
                return True
            last, tokens = entry
            tokens = min(self.rate, tokens + (now - last) * (self.rate / self.per))
            if tokens < 1:
                entry[0] = now
                entry[1] = tokens
                return False
            entry[0] = now
            entry[1] = tokens - 1
            return True


_PROCESS = psutil.Process() if _HAS_PSUTIL else None


def memory_mb() -> float:
    if _PROCESS is None:
        return 0.0
    try:
        return _PROCESS.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def memory_guard(threshold_mb: float = 380.0) -> bool:
    if _PROCESS is None:
        return False
    if memory_mb() >= threshold_mb:
        gc.collect(2)
        return True
    return False


def has_psutil() -> bool:
    return _HAS_PSUTIL


# ============================================================
# GUILD GATE — prefixo padrão "."
# ============================================================

class GuildGate:
    _cache = TTLCache(max_size=200, ttl=60)
    _lock = threading.RLock()

    DEFAULT_MODULES = {
        # ============================================================
        # v6.2
        # ============================================================
        "economy": True, "earn": True, "shop": True, "games": True,
        "gambling": True, "events": True, "achievements": True,
        "staff": True, "automod": False, "antinuke": False,
        "cases": True, "social": True, "market": True,
        "missions": True, "sinks": True, "backup": True, "branding": True,
        # ============================================================
        # v7.0 — FASE 1 (ligados por padrão, admin desativa se quiser)
        # ============================================================
        "price_engine": True, "inflation": True, "economy_tick": True,
        "president": True,
        # ============================================================
        # v7.0 — FASES FUTURAS (ligados por padrão, admin desativa)
        # ============================================================
        "companies": True, "credit": True, "market_v7": True,
        "government": True, "interguild": True,
    }

    @classmethod
    def _fetch(cls, guild_id: int) -> dict:
        cached = cls._cache.get(guild_id)
        if cached is not None:
            return cached
        from database import get_connection
        db = get_connection()
        doc = db["control_config"].find_one({"guild_id": guild_id}) or {}
        state = {
            "modules": {**cls.DEFAULT_MODULES, **(doc.get("modules") or {})},
            "disabled_commands": set(doc.get("disabled_commands") or []),
            "disabled_channels": {k: set(v) for k, v in (doc.get("disabled_channels") or {}).items()},
            "prefix": doc.get("prefix") or None,
            "maintenance": bool(doc.get("maintenance", False)),
            "bypass_roles": set(doc.get("bypass_roles") or []),
            "bypass_users": set(doc.get("bypass_users") or []),
        }
        cls._cache.set(guild_id, state)
        return state

    @classmethod
    def invalidate(cls, guild_id: int):
        cls._cache.invalidate(guild_id)

    @classmethod
    def get_prefix(cls, guild_id: int, default: str = ".") -> str:
        return cls._fetch(guild_id)["prefix"] or default

    @classmethod
    def is_module_on(cls, guild_id: int, module: str) -> bool:
        return bool(cls._fetch(guild_id)["modules"].get(module, True))

    @classmethod
    def is_command_off(cls, guild_id: int, command: str) -> bool:
        return command in cls._fetch(guild_id)["disabled_commands"]

    @classmethod
    def is_command_off_channel(cls, guild_id: int, command: str, channel_id: int) -> bool:
        chans = cls._fetch(guild_id)["disabled_channels"].get(command)
        return bool(chans and channel_id in chans)

    @classmethod
    def is_maintenance(cls, guild_id: int) -> bool:
        return cls._fetch(guild_id)["maintenance"]

    @classmethod
    def is_bypassed(cls, guild_id: int, user_id: int, role_ids: list) -> bool:
        state = cls._fetch(guild_id)
        if user_id in state["bypass_users"]:
            return True
        return any(rid in state["bypass_roles"] for rid in role_ids)

    @classmethod
    def get_module_state(cls, guild_id: int) -> dict:
        return dict(cls._fetch(guild_id)["modules"])

    @classmethod
    def get_disabled_commands(cls, guild_id: int) -> set:
        return set(cls._fetch(guild_id)["disabled_commands"])

    @classmethod
    def get_bypass_roles(cls, guild_id: int) -> set:
        return set(cls._fetch(guild_id)["bypass_roles"])

    @classmethod
    def get_bypass_users(cls, guild_id: int) -> set:
        return set(cls._fetch(guild_id)["bypass_users"])

    @classmethod
    def set_module(cls, guild_id: int, module: str, enabled: bool):
        from database import get_connection
        get_connection()["control_config"].update_one(
            {"guild_id": guild_id},
            {"$set": {f"modules.{module}": enabled}}, upsert=True
        )
        cls.invalidate(guild_id)

    @classmethod
    def set_command(cls, guild_id: int, command: str, disabled: bool):
        from database import get_connection
        db = get_connection()
        if disabled:
            db["control_config"].update_one(
                {"guild_id": guild_id},
                {"$addToSet": {"disabled_commands": command}}, upsert=True
            )
        else:
            db["control_config"].update_one(
                {"guild_id": guild_id},
                {"$pull": {"disabled_commands": command}}, upsert=True
            )
        cls.invalidate(guild_id)

    @classmethod
    def set_channel_lock(cls, guild_id: int, command: str, channel_id: int, disabled: bool):
        from database import get_connection
        db = get_connection()
        key = f"disabled_channels.{command}"
        if disabled:
            db["control_config"].update_one(
                {"guild_id": guild_id},
                {"$addToSet": {key: channel_id}}, upsert=True
            )
        else:
            db["control_config"].update_one(
                {"guild_id": guild_id},
                {"$pull": {key: channel_id}}, upsert=True
            )
        cls.invalidate(guild_id)

    @classmethod
    def set_prefix(cls, guild_id: int, prefix: Optional[str]):
        from database import get_connection
        db = get_connection()
        if prefix:
            db["control_config"].update_one(
                {"guild_id": guild_id},
                {"$set": {"prefix": prefix}}, upsert=True
            )
        else:
            db["control_config"].update_one(
                {"guild_id": guild_id},
                {"$unset": {"prefix": ""}}, upsert=True
            )
        cls.invalidate(guild_id)

    @classmethod
    def set_maintenance(cls, guild_id: int, enabled: bool):
        from database import get_connection
        get_connection()["control_config"].update_one(
            {"guild_id": guild_id},
            {"$set": {"maintenance": enabled}}, upsert=True
        )
        cls.invalidate(guild_id)

    @classmethod
    def add_bypass(cls, guild_id: int, kind: str, target_id: int):
        from database import get_connection
        key = "bypass_roles" if kind == "role" else "bypass_users"
        get_connection()["control_config"].update_one(
            {"guild_id": guild_id},
            {"$addToSet": {key: target_id}}, upsert=True
        )
        cls.invalidate(guild_id)

    @classmethod
    def remove_bypass(cls, guild_id: int, kind: str, target_id: int):
        from database import get_connection
        key = "bypass_roles" if kind == "role" else "bypass_users"
        get_connection()["control_config"].update_one(
            {"guild_id": guild_id},
            {"$pull": {key: target_id}}, upsert=True
        )
        cls.invalidate(guild_id)


# ============================================================
# SLASH CTX ADAPTER
# ============================================================

class _NoopAsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class SlashCtxAdapter:
    """
    Wrapper que faz um discord.Interaction se comportar como commands.Context.
    """

    __slots__ = ("interaction", "guild", "author", "channel", "message", "_responded")

    def __init__(self, interaction):
        self.interaction = interaction
        self.guild = interaction.guild
        self.author = interaction.user
        self.channel = interaction.channel
        self.message = None
        self._responded = False

    async def send(self, content=None, *, embed=None, view=None,
                   ephemeral=False, delete_after=None, **kwargs):
        payload = {}
        if content is not None:
            payload["content"] = content
        if embed is not None:
            payload["embed"] = embed
        if view is not None:
            payload["view"] = view
        if delete_after is not None:
            payload["delete_after"] = delete_after
        payload.update(kwargs)

        if not self._responded:
            self._responded = True
            if ephemeral:
                payload["ephemeral"] = True
            return await self.interaction.response.send_message(**payload)
        else:
            payload.pop("ephemeral", None)
            return await self.interaction.followup.send(**payload)

    async def reply(self, content=None, **kwargs):
        return await self.send(content, **kwargs)

    def typing(self):
        return _NoopAsyncCtx()

    async def defer(self, ephemeral: bool = False):
        if not self._responded:
            self._responded = True
            await self.interaction.response.defer(ephemeral=ephemeral)

    @property
    def is_slash(self) -> bool:
        return True