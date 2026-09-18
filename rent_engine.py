# ============================================================
# RENT_ENGINE.PY - v7.0 Fase 7 (Aluguel)
# ============================================================
# Responsável por:
#   • Contratos de aluguel
#   • Cobrança automática por tick
#   • Inadimplência
#   • Despejo automático
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id


DEFAULT_RENT_CONFIG = {
    "enabled": True,
    "interval_hours": 24,             # cobrança diária
    "grace_period_hours": 48,         # carência
    "max_missed_payments": 3,         # após 3 faltas, despejo
    "deposit_months": 1,              # caução
    "rent_adjustment_yearly": 0.05,   # +5% ao ano
    "eviction_enabled": True,
}


_rent_cache = TTLCache(max_size=300, ttl=60)


class RentEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _rent_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "rent"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_RENT_CONFIG, **(doc.get("config") or {})}
        _rent_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "rent"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _rent_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # CRIAR CONTRATO
    # ============================================================

    @classmethod
    def create_rental(
        cls,
        guild_id: int,
        property_id: str,
        landlord_id: int,
        tenant_id: int,
        rent: int,
    ) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        if landlord_id == tenant_id:
            return {"error": "same_user"}

        db = get_connection()
        oid = safe_object_id(property_id)
        if not oid:
            return {"error": "invalid_id"}

        prop = db["realestate_properties"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "active": True,
        })
        if not prop:
            return {"error": "property_not_found"}

        if prop.get("owner_id") != landlord_id:
            return {"error": "not_owner"}

        if prop.get("rented_to"):
            return {"error": "already_rented"}

        # Caução
        deposit = rent * int(config.get("deposit_months", 1))

        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(guild_id, tenant_id)
        if balance < deposit:
            return {"error": "insufficient_deposit",
                    "needed": deposit, "have": balance}

        if not EconomyManager.remove_balance(
            guild_id, tenant_id, deposit,
            f"Caução aluguel {prop.get('name', '?')}",
            "rent_deposit"
        ):
            return {"error": "payment_failed"}

        # Cria contrato
        now = datetime.utcnow()
        interval_hours = int(config.get("interval_hours", 24))

        result = db["realestate_rentals"].insert_one({
            "guild_id": guild_id,
            "property_id": str(prop["_id"]),
            "landlord_id": landlord_id,
            "tenant_id": tenant_id,
            "rent": int(rent),
            "deposit": int(deposit),
            "status": "active",
            "missed_payments": 0,
            "total_paid": 0,
            "created_at": now,
            "next_due_at": now + timedelta(hours=interval_hours),
            "interval_hours": interval_hours,
        })

        # Marca imóvel como alugado
        db["realestate_properties"].update_one(
            {"_id": prop["_id"]},
            {"$set": {
                "rented_to": tenant_id,
                "current_rent": rent,
                "rental_id": str(result.inserted_id),
            }}
        )

        return {
            "ok": True,
            "rental_id": str(result.inserted_id),
            "deposit": deposit,
            "rent": rent,
        }

    # ============================================================
    # CANCELAR CONTRATO
    # ============================================================

    @classmethod
    def end_rental(
        cls, guild_id: int, rental_id: str, by_user: int
    ) -> dict:
        db = get_connection()
        oid = safe_object_id(rental_id)
        if not oid:
            return {"error": "invalid_id"}

        rental = db["realestate_rentals"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "status": "active",
        })
        if not rental:
            return {"error": "not_found"}

        if by_user not in (rental["landlord_id"], rental["tenant_id"]):
            return {"error": "not_party"}

        # Devolve caução ao inquilino
        deposit = int(rental.get("deposit", 0))
        if deposit > 0:
            from commands_economy_core import EconomyManager
            EconomyManager.add_balance(
                guild_id, rental["tenant_id"], deposit,
                f"Devolução caução aluguel",
                "rent_deposit_refund"
            )

        db["realestate_rentals"].update_one(
            {"_id": rental["_id"]},
            {"$set": {
                "status": "ended",
                "ended_at": datetime.utcnow(),
                "ended_by": by_user,
            }}
        )

        # Libera imóvel
        prop_oid = safe_object_id(rental.get("property_id", ""))
        if prop_oid:
            db["realestate_properties"].update_one(
                {"_id": prop_oid},
                {"$set": {"rented_to": None, "rental_id": None}}
            )

        return {"ok": True, "refunded": deposit}

    # ============================================================
    # PROCESSAMENTO (tick)
    # ============================================================

    @classmethod
    def process_rentals(cls, guild_id: int) -> dict:
        """Cobra aluguéis vencidos."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"collected": 0, "missed": 0, "evicted": 0}

        db = get_connection()
        now = datetime.utcnow()

        due = list(db["realestate_rentals"].find({
            "guild_id": guild_id,
            "status": "active",
            "next_due_at": {"$lte": now},
        }))

        from commands_economy_core import EconomyManager
        collected = 0
        missed = 0
        evicted = 0

        for rental in due:
            tenant = rental["tenant_id"]
            landlord = rental["landlord_id"]
            rent = int(rental.get("rent", 0))

            if rent <= 0:
                continue

            balance = EconomyManager.get_balance(guild_id, tenant)
            if balance >= rent:
                # Paga
                if EconomyManager.remove_balance(
                    guild_id, tenant, rent,
                    f"Aluguel {rental['property_id'][:8]}",
                    "rent_payment"
                ):
                    EconomyManager.add_balance(
                        guild_id, landlord, rent,
                        f"Aluguel recebido",
                        "rent_income"
                    )
                    db["realestate_rentals"].update_one(
                        {"_id": rental["_id"]},
                        {
                            "$inc": {"total_paid": rent},
                            "$set": {
                                "missed_payments": 0,
                                "next_due_at": now + timedelta(
                                    hours=int(rental.get("interval_hours", 24))
                                ),
                                "last_paid_at": now,
                            }
                        }
                    )
                    collected += 1
            else:
                # Inadimplente
                db["realestate_rentals"].update_one(
                    {"_id": rental["_id"]},
                    {"$inc": {"missed_payments": 1}}
                )
                missed += 1

                # Verifica despejo
                updated = db["realestate_rentals"].find_one({"_id": rental["_id"]})
                max_missed = int(config.get("max_missed_payments", 3))
                if (config.get("eviction_enabled", True) and
                    updated.get("missed_payments", 0) >= max_missed):

                    # Despejo
                    db["realestate_rentals"].update_one(
                        {"_id": rental["_id"]},
                        {"$set": {
                            "status": "evicted",
                            "evicted_at": now,
                            "deposit_kept": rental.get("deposit", 0),
                        }}
                    )
                    # Libera imóvel
                    prop_oid = safe_object_id(rental.get("property_id", ""))
                    if prop_oid:
                        db["realestate_properties"].update_one(
                            {"_id": prop_oid},
                            {"$set": {"rented_to": None, "rental_id": None}}
                        )
                    evicted += 1

                    # Caução vai pro proprietário como compensação
                    deposit = int(rental.get("deposit", 0))
                    if deposit > 0:
                        EconomyManager.add_balance(
                            guild_id, landlord, deposit,
                            "Caução retida (despejo)",
                            "rent_deposit_kept"
                        )

        return {
            "collected": collected,
            "missed": missed,
            "evicted": evicted,
        }

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_active_rental(cls, guild_id: int, property_id: str) -> Optional[dict]:
        db = get_connection()
        return db["realestate_rentals"].find_one({
            "guild_id": guild_id,
            "property_id": property_id,
            "status": "active",
        })

    @classmethod
    def list_user_rentals(cls, guild_id: int, user_id: int) -> List[dict]:
        db = get_connection()
        return list(db["realestate_rentals"].find({
            "guild_id": guild_id,
            "status": "active",
            "$or": [
                {"landlord_id": user_id},
                {"tenant_id": user_id},
            ],
        }))

    @classmethod
    def clear_cache(cls) -> None:
        _rent_cache.clear()


async def setup(bot):
    pass