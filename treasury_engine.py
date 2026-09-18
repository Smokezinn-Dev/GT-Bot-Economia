# ============================================================
# TREASURY_ENGINE.PY - v7.0 Fase 5 (Tesouro Público)
# ============================================================
# Responsável por:
#   • Guardar o caixa do governo
#   • Receber arrecadação de impostos
#   • Gastar em políticas
#   • Saldo e histórico
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


DEFAULT_TREASURY_CONFIG = {
    "enabled": True,
    "initial_balance": 0,
    "max_balance": 100_000_000,
    "allow_negative": False,
    "auto_log": True,
}


_treasury_cache = TTLCache(max_size=100, ttl=30)


class TreasuryEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _treasury_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "treasury"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_TREASURY_CONFIG, **(doc.get("config") or {})}
        _treasury_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "treasury"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _treasury_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # ESTADO
    # ============================================================

    @classmethod
    def _get_state(cls, guild_id: int) -> dict:
        db = get_connection()
        doc = db["government_config"].find_one({"guild_id": guild_id})
        if doc:
            return doc
        config = cls.get_config(guild_id)
        new_doc = {
            "guild_id": guild_id,
            "treasury_balance": int(config.get("initial_balance", 0)),
            "total_collected": 0,
            "total_spent": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        db["government_config"].insert_one(new_doc.copy())
        return new_doc

    @classmethod
    def get_balance(cls, guild_id: int) -> int:
        state = cls._get_state(guild_id)
        return int(state.get("treasury_balance", 0))

    @classmethod
    def can_spend(cls, guild_id: int, amount: int) -> bool:
        config = cls.get_config(guild_id)
        if amount <= 0:
            return False
        if config.get("allow_negative", False):
            return True
        return cls.get_balance(guild_id) >= amount

    # ============================================================
    # COLETA / GASTO
    # ============================================================

    @classmethod
    def collect(cls, guild_id: int, amount: int, source: str) -> int:
        """Adiciona valor ao tesouro."""
        if amount <= 0:
            return cls.get_balance(guild_id)

        db = get_connection()
        state = cls._get_state(guild_id)

        current = int(state.get("treasury_balance", 0))
        new_balance = current + amount

        db["government_config"].update_one(
            {"guild_id": guild_id},
            {
                "$set": {
                    "treasury_balance": new_balance,
                    "updated_at": datetime.utcnow(),
                },
                "$inc": {"total_collected": amount},
            },
            upsert=True,
        )

        # Registro
        try:
            db["public_spending"].insert_one({
                "guild_id": guild_id,
                "type": "income",
                "amount": int(amount),
                "source": source[:100],
                "timestamp": datetime.utcnow(),
            })
        except Exception:
            pass

        _treasury_cache.invalidate(f"cfg:{guild_id}")
        return new_balance

    @classmethod
    def spend(cls, guild_id: int, amount: int, reason: str) -> bool:
        """Gasta do tesouro."""
        if amount <= 0:
            return False

        config = cls.get_config(guild_id)
        current = cls.get_balance(guild_id)
        if not config.get("allow_negative", False) and current < amount:
            return False

        db = get_connection()
        new_balance = current - amount

        db["government_config"].update_one(
            {"guild_id": guild_id},
            {
                "$set": {
                    "treasury_balance": new_balance,
                    "updated_at": datetime.utcnow(),
                },
                "$inc": {"total_spent": amount},
            },
            upsert=True,
        )

        try:
            db["public_spending"].insert_one({
                "guild_id": guild_id,
                "type": "expense",
                "amount": int(amount),
                "reason": reason[:100],
                "timestamp": datetime.utcnow(),
            })
        except Exception:
            pass

        _treasury_cache.invalidate(f"cfg:{guild_id}")
        return True

    # ============================================================
    # HISTÓRICO
    # ============================================================

    @classmethod
    def get_history(cls, guild_id: int, limit: int = 20) -> List[dict]:
        db = get_connection()
        return list(db["public_spending"].find({
            "guild_id": guild_id,
        }).sort("timestamp", -1).limit(limit))

    @classmethod
    def get_stats(cls, guild_id: int) -> dict:
        state = cls._get_state(guild_id)
        return {
            "balance": int(state.get("treasury_balance", 0)),
            "total_collected": int(state.get("total_collected", 0)),
            "total_spent": int(state.get("total_spent", 0)),
        }

    @classmethod
    def clear_cache(cls) -> None:
        _treasury_cache.clear()


async def setup(bot):
    pass