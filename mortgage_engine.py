# ============================================================
# MORTGAGE_ENGINE.PY - v7.0 Fase 7 (Financiamento Imobiliário)
# ============================================================
# Responsável por:
#   • Financiamento de imóveis
#   • Parcelas com juros
#   • Execução hipotecária
#   • Leilão público
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id
from credit_engine import CreditEngine


DEFAULT_MORTGAGE_CONFIG = {
    "enabled": True,
    "max_loan_to_value": 0.8,        # 80% do imóvel
    "min_down_payment": 0.20,         # 20% de entrada
    "default_term_months": 12,        # 12 parcelas
    "max_term_months": 60,
    "min_term_months": 3,
    "base_interest_rate": 0.02,       # 2% ao tick (juros base)
    "late_fee_percent": 5.0,
    "max_missed_payments": 5,
    "eviction_after_missed": 5,
    "auction_duration_hours": 48,
}


_mortgage_cache = TTLCache(max_size=300, ttl=60)


class MortgageEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _mortgage_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "mortgage"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_MORTGAGE_CONFIG, **(doc.get("config") or {})}
        _mortgage_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "mortgage"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _mortgage_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # CRIAR FINANCIAMENTO
    # ============================================================

    @classmethod
    def create_mortgage(
        cls,
        guild_id: int,
        user_id: int,
        property_id: str,
        term_months: int,
        down_payment: int,
    ) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

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

        if prop.get("owner_id") != user_id:
            return {"error": "not_owner"}

        # Já tem financiamento?
        existing = db["realestate_mortgages"].find_one({
            "property_id": str(prop["_id"]),
            "status": "active",
        })
        if existing:
            return {"error": "already_mortgaged"}

        # Cálculo
        cost = int(prop.get("cost", 0))
        min_down = int(cost * float(config.get("min_down_payment", 0.20)))

        if down_payment < min_down:
            return {"error": "down_payment_too_low",
                    "needed": min_down}

        max_lend = int(cost * float(config.get("max_loan_to_value", 0.8)))
        loan_amount = cost - down_payment

        if loan_amount > max_lend:
            return {"error": "loan_too_high", "max": max_lend}

        # Verifica score de crédito
        score = CreditEngine.get_score(guild_id, user_id)
        if score < 300:
            return {"error": "score_too_low", "score": score}

        # Verifica term
        term = max(int(config.get("min_term_months", 3)),
                   min(int(config.get("max_term_months", 60)), term_months))

        # Taxa: base + score
        base_rate = float(config.get("base_interest_rate", 0.02))
        if score >= 850:
            rate = base_rate * 0.5
        elif score >= 700:
            rate = base_rate * 0.7
        elif score >= 500:
            rate = base_rate
        elif score >= 300:
            rate = base_rate * 1.5
        else:
            rate = base_rate * 2.0

        # Parcela (tabela Price simplificada)
        # M = P * (r * (1+r)^n) / ((1+r)^n - 1)
        if rate > 0:
            factor = (rate * ((1 + rate) ** term)) / (((1 + rate) ** term) - 1)
        else:
            factor = 1.0 / term
        per_installment = int(loan_amount * factor)
        total_due = per_installment * term

        # Verifica entrada
        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < down_payment:
            return {"error": "insufficient_down_payment",
                    "needed": down_payment, "have": balance}

        # Cobra entrada
        if not EconomyManager.remove_balance(
            guild_id, user_id, down_payment,
            f"Entrada financiamento {prop.get('name', '?')}",
            "mortgage_down"
        ):
            return {"error": "payment_failed"}

        # Cria financiamento
        now = datetime.utcnow()
        interval_hours = 24  # cobrança diária

        result = db["realestate_mortgages"].insert_one({
            "guild_id": guild_id,
            "property_id": str(prop["_id"]),
            "user_id": user_id,
            "loan_amount": loan_amount,
            "down_payment": down_payment,
            "term_months": term,
            "paid_installments": 0,
            "total_due": total_due,
            "per_installment": per_installment,
            "rate": rate,
            "paid_amount": 0,
            "status": "active",
            "missed_payments": 0,
            "created_at": now,
            "next_due_at": now + timedelta(hours=interval_hours),
            "interval_hours": interval_hours,
        })

        # Marca imóvel como hipotecado
        db["realestate_properties"].update_one(
            {"_id": prop["_id"]},
            {"$set": {"mortgaged": True, "mortgage_id": str(result.inserted_id)}}
        )

        return {
            "ok": True,
            "mortgage_id": str(result.inserted_id),
            "loan_amount": loan_amount,
            "per_installment": per_installment,
            "total_due": total_due,
            "rate": rate,
            "term": term,
        }

    # ============================================================
    # PAGAR PARCELA
    # ============================================================

    @classmethod
    def pay_installment(
        cls, guild_id: int, user_id: int, mortgage_id: str
    ) -> dict:
        db = get_connection()
        oid = safe_object_id(mortgage_id)
        if not oid:
            return {"error": "invalid_id"}

        m = db["realestate_mortgages"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "user_id": user_id,
            "status": {"$in": ["active", "late"]},
        })
        if not m:
            return {"error": "not_found"}

        per = int(m.get("per_installment", 0))

        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < per:
            return {"error": "insufficient_funds",
                    "needed": per, "have": balance}

        if not EconomyManager.remove_balance(
            guild_id, user_id, per,
            f"Parcela imóvel",
            "mortgage_payment"
        ):
            return {"error": "payment_failed"}

        new_paid = int(m.get("paid_amount", 0)) + per
        new_inst = int(m.get("paid_installments", 0)) + 1
        total_due = int(m.get("total_due", 0))

        new_status = "active"
        if new_paid >= total_due:
            new_status = "paid"

        db["realestate_mortgages"].update_one(
            {"_id": m["_id"]},
            {
                "$set": {
                    "paid_amount": new_paid,
                    "paid_installments": new_inst,
                    "status": new_status,
                    "missed_payments": 0,
                    "next_due_at": datetime.utcnow() + timedelta(hours=24),
                    "last_paid_at": datetime.utcnow(),
                }
            }
        )

        # Se quitou, libera hipoteca
        if new_status == "paid":
            prop_oid = safe_object_id(m.get("property_id", ""))
            if prop_oid:
                db["realestate_properties"].update_one(
                    {"_id": prop_oid},
                    {"$set": {"mortgaged": False, "mortgage_id": None}}
                )
            # Bônus de score
            CreditEngine.adjust_score(guild_id, user_id, 50)

        return {
            "ok": True,
            "paid": per,
            "remaining": max(0, total_due - new_paid),
            "installments_left": max(0, int(m.get("term_months", 0)) - new_inst),
            "status": new_status,
        }

    # ============================================================
    # PROCESSAMENTO (tick)
    # ============================================================

    @classmethod
    def process_mortgages(cls, guild_id: int) -> dict:
        """Processa parcelas vencidas + execuções."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"collected": 0, "missed": 0, "evicted": 0}

        db = get_connection()
        now = datetime.utcnow()

        due = list(db["realestate_mortgages"].find({
            "guild_id": guild_id,
            "status": "active",
            "next_due_at": {"$lte": now},
        }))

        from commands_economy_core import EconomyManager
        collected = 0
        missed = 0
        evicted = 0

        for m in due:
            per = int(m.get("per_installment", 0))
            balance = EconomyManager.get_balance(guild_id, m["user_id"])

            if balance >= per:
                if EconomyManager.remove_balance(
                    guild_id, m["user_id"], per,
                    "Parcela imóvel (auto)", "mortgage_payment"
                ):
                    new_paid = int(m.get("paid_amount", 0)) + per
                    new_inst = int(m.get("paid_installments", 0)) + 1
                    total_due = int(m.get("total_due", 0))
                    new_status = "paid" if new_paid >= total_due else "active"

                    db["realestate_mortgages"].update_one(
                        {"_id": m["_id"]},
                        {"$set": {
                            "paid_amount": new_paid,
                            "paid_installments": new_inst,
                            "status": new_status,
                            "missed_payments": 0,
                            "next_due_at": now + timedelta(hours=24),
                            "last_paid_at": now,
                        }}
                    )
                    collected += 1

                    if new_status == "paid":
                        prop_oid = safe_object_id(m.get("property_id", ""))
                        if prop_oid:
                            db["realestate_properties"].update_one(
                                {"_id": prop_oid},
                                {"$set": {"mortgaged": False, "mortgage_id": None}}
                            )
            else:
                db["realestate_mortgages"].update_one(
                    {"_id": m["_id"]},
                    {"$inc": {"missed_payments": 1}}
                )
                missed += 1

                updated = db["realestate_mortgages"].find_one({"_id": m["_id"]})
                if updated.get("missed_payments", 0) >= int(config.get("eviction_after_missed", 5)):
                    cls._execute_mortgage(guild_id, updated, config)
                    evicted += 1

        return {
            "collected": collected,
            "missed": missed,
            "evicted": evicted,
        }

    @classmethod
    def _execute_mortgage(cls, guild_id: int, mortgage: dict, config: dict) -> None:
        """Execução hipotecária: imóvel vai a leilão."""
        db = get_connection()
        prop_oid = safe_object_id(mortgage.get("property_id", ""))
        if not prop_oid:
            return

        prop = db["realestate_properties"].find_one({"_id": prop_oid})
        if not prop:
            return

        # Valor do imóvel
        cost = int(prop.get("cost", 0))
        auction_start = int(cost * 0.7)   # começa em 70%

        # Cria leilão
        duration_hours = int(config.get("auction_duration_hours", 48))
        db["realestate_auctions"].insert_one({
            "guild_id": guild_id,
            "property_id": str(prop["_id"]),
            "original_owner": mortgage["user_id"],
            "debt": int(mortgage.get("total_due", 0)) - int(mortgage.get("paid_amount", 0)),
            "start_price": auction_start,
            "current_bid": auction_start,
            "current_bidder": None,
            "active": True,
            "created_at": datetime.utcnow(),
            "ends_at": datetime.utcnow() + timedelta(hours=duration_hours),
        })

        # Marca financiamento como executado
        db["realestate_mortgages"].update_one(
            {"_id": mortgage["_id"]},
            {"$set": {
                "status": "foreclosed",
                "foreclosed_at": datetime.utcnow(),
            }}
        )

        # Marca imóvel como em leilão
        db["realestate_properties"].update_one(
            {"_id": prop["_id"]},
            {"$set": {
                "active": False,
                "auctioned": True,
                "auctioned_at": datetime.utcnow(),
            }}
        )

        # Penaliza score
        CreditEngine.adjust_score(guild_id, mortgage["user_id"], -150)

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def list_active_auctions(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["realestate_auctions"].find({
            "guild_id": guild_id,
            "active": True,
        }).sort("ends_at", 1))

    @classmethod
    def get_user_mortgages(cls, guild_id: int, user_id: int) -> List[dict]:
        db = get_connection()
        return list(db["realestate_mortgages"].find({
            "guild_id": guild_id,
            "user_id": user_id,
            "status": {"$in": ["active", "late"]},
        }))

    @classmethod
    def clear_cache(cls) -> None:
        _mortgage_cache.clear()


async def setup(bot):
    pass