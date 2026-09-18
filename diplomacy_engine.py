# ============================================================
# DIPLOMACY_ENGINE.PY - v7.0 Fase 6 (Tratados e Diplomacia)
# ============================================================
# Responsável por:
#   • Tratados comerciais entre guilds
#   • Alianças e embargos
#   • Confiança diplomática
#   • Aprovação bilateral
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id
from currency_engine import CurrencyEngine


DEFAULT_DIPLOMACY_CONFIG = {
    "enabled": True,
    "treaty_duration_days": 7,
    "max_active_treaties": 5,
    "confidence_gain_per_treaty": 0.05,
    "confidence_loss_per_embargo": 0.10,
    "require_president": True,
}


TREATY_TYPES = {
    "commercial": {
        "name": "Acordo Comercial",
        "emoji": "🤝",
        "description": "Reduz tarifa em 50% entre as guilds",
    },
    "alliance": {
        "name": "Aliança",
        "emoji": "🛡️",
        "description": "Reduz tarifa em 75% + confiança mútua",
    },
    "free_trade": {
        "name": "Livre Comércio",
        "emoji": "🕊️",
        "description": "Elimina tarifas totalmente",
    },
    "embargo": {
        "name": "Embargo",
        "emoji": "🚫",
        "description": "Bloqueia comércio entre as guilds",
    },
    "monetary_union": {
        "name": "União Monetária",
        "emoji": "💱",
        "description": "Fixa câmbio em 1:1",
    },
}


_diplomacy_cache = TTLCache(max_size=300, ttl=60)


class DiplomacyEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _diplomacy_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "diplomacy"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_DIPLOMACY_CONFIG, **(doc.get("config") or {})}
        _diplomacy_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "diplomacy"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _diplomacy_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # TRATADOS
    # ============================================================

    @classmethod
    def propose_treaty(
        cls,
        from_guild: int,
        to_guild: int,
        treaty_type: str,
        duration_days: Optional[int] = None,
    ) -> dict:
        if from_guild == to_guild:
            return {"error": "same_guild"}

        if treaty_type not in TREATY_TYPES:
            return {"error": "invalid_type",
                    "valid": list(TREATY_TYPES.keys())}

        config = cls.get_config(from_guild)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        db = get_connection()

        existing = db["trade_agreements"].find_one({
            "guild_a": from_guild,
            "guild_b": to_guild,
            "active": True,
        })
        if existing:
            return {"error": "treaty_exists", "id": str(existing["_id"])}

        active_count = db["trade_agreements"].count_documents({
            "$or": [
                {"guild_a": from_guild, "active": True},
                {"guild_b": from_guild, "active": True},
            ],
        })
        if active_count >= int(config.get("max_active_treaties", 5)):
            return {"error": "max_treaties"}

        duration = duration_days or int(config.get("treaty_duration_days", 7))
        expires = datetime.utcnow() + timedelta(days=duration)

        doc = {
            "guild_a": from_guild,
            "guild_b": to_guild,
            "type": treaty_type,
            "status": "proposed",
            "duration_days": duration,
            "proposed_by": from_guild,
            "expires_at": None,
            "created_at": datetime.utcnow(),
            "activated_at": None,
        }
        result = db["trade_agreements"].insert_one(doc)
        return {"ok": True, "treaty_id": str(result.inserted_id)}

    @classmethod
    def accept_treaty(cls, guild_id: int, treaty_id: str) -> dict:
        db = get_connection()
        oid = safe_object_id(treaty_id)
        if not oid:
            return {"error": "invalid_id"}

        treaty = db["trade_agreements"].find_one({
            "_id": oid,
            "status": "proposed",
        })
        if not treaty:
            return {"error": "not_found"}

        if guild_id not in (treaty["guild_a"], treaty["guild_b"]):
            return {"error": "not_involved"}

        if treaty.get("proposed_by") == guild_id:
            return {"error": "proposer_cannot_accept"}

        config = cls.get_config(guild_id)
        duration = int(treaty.get("duration_days", 7))
        expires = datetime.utcnow() + timedelta(days=duration)

        db["trade_agreements"].update_one(
            {"_id": treaty["_id"]},
            {"$set": {
                "status": "active",
                "activated_at": datetime.utcnow(),
                "expires_at": expires,
            }}
        )

        gain = float(config.get("confidence_gain_per_treaty", 0.05))
        CurrencyEngine.adjust_confidence(treaty["guild_a"], gain)
        CurrencyEngine.adjust_confidence(treaty["guild_b"], gain)

        if treaty["type"] == "embargo":
            loss = float(config.get("confidence_loss_per_embargo", 0.10))
            CurrencyEngine.adjust_confidence(treaty["guild_a"], -loss)
            CurrencyEngine.adjust_confidence(treaty["guild_b"], -loss)

        return {"ok": True, "expires_at": expires}

    @classmethod
    def reject_treaty(cls, guild_id: int, treaty_id: str) -> dict:
        db = get_connection()
        oid = safe_object_id(treaty_id)
        if not oid:
            return {"error": "invalid_id"}

        result = db["trade_agreements"].update_one(
            {"_id": oid, "status": "proposed",
             "$or": [{"guild_a": guild_id}, {"guild_b": guild_id}]},
            {"$set": {"status": "rejected",
                      "rejected_at": datetime.utcnow()}}
        )
        if result.modified_count == 0:
            return {"error": "not_found"}
        return {"ok": True}

    @classmethod
    def cancel_treaty(cls, guild_id: int, treaty_id: str) -> dict:
        db = get_connection()
        oid = safe_object_id(treaty_id)
        if not oid:
            return {"error": "invalid_id"}

        result = db["trade_agreements"].update_one(
            {"_id": oid, "status": "active",
             "$or": [{"guild_a": guild_id}, {"guild_b": guild_id}]},
            {"$set": {"status": "cancelled",
                      "cancelled_at": datetime.utcnow()}}
        )
        if result.modified_count == 0:
            return {"error": "not_found"}
        return {"ok": True}

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_active_treaty(cls, guild_a: int, guild_b: int) -> Optional[dict]:
        db = get_connection()
        return db["trade_agreements"].find_one({
            "$or": [
                {"guild_a": guild_a, "guild_b": guild_b},
                {"guild_a": guild_b, "guild_b": guild_a},
            ],
            "status": "active",
        })

    @classmethod
    def has_embargo(cls, guild_a: int, guild_b: int) -> bool:
        treaty = cls.get_active_treaty(guild_a, guild_b)
        return bool(treaty and treaty.get("type") == "embargo")

    @classmethod
    def list_active(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["trade_agreements"].find({
            "$or": [
                {"guild_a": guild_id, "status": "active"},
                {"guild_b": guild_id, "status": "active"},
            ],
        }).sort("activated_at", -1))

    @classmethod
    def list_proposed(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["trade_agreements"].find({
            "$or": [
                {"guild_a": guild_id, "status": "proposed"},
                {"guild_b": guild_id, "status": "proposed"},
            ],
        }).sort("created_at", -1))

    @classmethod
    def expire_treaties(cls) -> int:
        db = get_connection()
        now = datetime.utcnow()
        result = db["trade_agreements"].update_many(
            {"status": "active", "expires_at": {"$lte": now}},
            {"$set": {"status": "expired", "expired_at": now}}
        )
        return result.modified_count

    @classmethod
    def get_treaty_types(cls) -> dict:
        return TREATY_TYPES

    @classmethod
    def clear_cache(cls) -> None:
        _diplomacy_cache.clear()


async def setup(bot):
    pass
