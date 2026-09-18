# ============================================================
# CREDIT_ENGINE.PY - v7.0 Fase 3 (Crédito)
# ============================================================
# Responsável por:
#   • Calcular score de crédito (0-1000)
#   • Criar e gerenciar empréstimos
#   • Processar parcelas (juros compostos)
#   • Detectar e processar inadimplência
#   • Bloquear devedores de operações
# ============================================================

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id


# ============================================================
# CONFIGURAÇÃO PADRÃO
# ============================================================

DEFAULT_CREDIT_CONFIG = {
    "enabled": True,

    # Score
    "min_score_to_borrow": 300,
    "score_max": 1000,
    "score_initial": 500,
    "score_recovery_per_day": 5,     # score recupera +5/dia se sem dívida

    # Empréstimos
    "min_loan_amount": 100,
    "max_loan_amount": 500_000,
    "max_active_loans": 3,
    "max_debt_to_balance_ratio": 2.0, # dívida máxima = 2x saldo

    # Taxa base por faixa de score
    "rate_excellent": 0.02,   # 850+
    "rate_great": 0.04,       # 700-849
    "rate_good": 0.08,        # 500-699
    "rate_fair": 0.15,        # 300-499
    "rate_poor": 0.30,        # <300

    # Parcelas
    "default_installments": 3,
    "max_installments": 12,
    "installment_interval_hours": 24,  # cobra parcela a cada 24h

    # Inadimplência
    "grace_period_hours": 24,        # tolerância após vencimento
    "late_fee_percent": 10.0,        # +10% por atraso
    "max_late_fee_percent": 100.0,   # teto
    "score_penalty_late": 50,        # -50 score por atraso
    "score_penalty_default": 150,    # -150 score por calote
    "writedown_after_hours": 168,    # 7 dias → marca como calote
}


_credit_cache = TTLCache(max_size=300, ttl=90)


class CreditEngine:

    # ============================================================
    # CONFIG
    # ============================================================

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _credit_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "credit"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_CREDIT_CONFIG, **(doc.get("config") or {})}
        _credit_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "credit"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _credit_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # SCORE DE CRÉDITO
    # ============================================================

    @classmethod
    def get_score_doc(cls, guild_id: int, user_id: int) -> dict:
        db = get_connection()
        doc = db["credit_scores"].find_one({
            "guild_id": guild_id,
            "user_id": user_id,
        })
        if doc:
            return doc

        config = cls.get_config(guild_id)
        initial = int(config.get("score_initial", 500))
        new_doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "score": initial,
            "total_borrowed": 0,
            "total_repaid": 0,
            "loans_taken": 0,
            "loans_repaid": 0,
            "loans_defaulted": 0,
            "late_payments": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        db["credit_scores"].insert_one(new_doc.copy())
        return new_doc

    @classmethod
    def get_score(cls, guild_id: int, user_id: int) -> int:
        doc = cls.get_score_doc(guild_id, user_id)
        return int(doc.get("score", 500))

    @classmethod
    def set_score(cls, guild_id: int, user_id: int, new_score: int) -> None:
        config = cls.get_config(guild_id)
        max_s = int(config.get("score_max", 1000))
        new_score = max(0, min(max_s, int(new_score)))
        db = get_connection()
        db["credit_scores"].update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$set": {"score": new_score, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    @classmethod
    def adjust_score(cls, guild_id: int, user_id: int, delta: int) -> int:
        doc = cls.get_score_doc(guild_id, user_id)
        current = int(doc.get("score", 500))
        new_score = current + delta
        cls.set_score(guild_id, user_id, new_score)
        return max(0, min(int(cls.get_config(guild_id).get("score_max", 1000)), new_score))

    @classmethod
    def recalculate_score(cls, guild_id: int, user_id: int) -> int:
        """
        Recalcula score com base no histórico.
        Fórmula:
            score = 500 + pesos históricos
        """
        db = get_connection()
        doc = db["credit_scores"].find_one({
            "guild_id": guild_id, "user_id": user_id,
        }) or {}

        base = 500

        # Fator 1: Taxa de pagamento (peso 40%)
        taken = int(doc.get("loans_taken", 0))
        repaid = int(doc.get("loans_repaid", 0))
        defaulted = int(doc.get("loans_defaulted", 0))
        if taken > 0:
            pay_ratio = repaid / taken
            base += int((pay_ratio - 0.5) * 400)  # -200 a +200

        # Fator 2: Atrasos (peso 30%)
        late = int(doc.get("late_payments", 0))
        base -= min(300, late * 25)

        # Fator 3: Volume emprestado (peso 15%)
        volume = int(doc.get("total_borrowed", 0))
        if volume > 0:
            # log10 do volume × 10 (máx +150)
            base += min(150, int(math.log10(max(1, volume)) * 10))

        # Fator 4: Calotes (peso 15%)
        base -= min(400, defaulted * 150)

        # Clamp
        base = max(0, min(1000, base))
        cls.set_score(guild_id, user_id, base)
        return base

    @classmethod
    def get_score_tier(cls, guild_id: int, score: int) -> str:
        if score >= 850:
            return "excellent"
        if score >= 700:
            return "great"
        if score >= 500:
            return "good"
        if score >= 300:
            return "fair"
        return "poor"

    @classmethod
    def get_base_rate(cls, guild_id: int, score: int) -> float:
        config = cls.get_config(guild_id)
        tier = cls.get_score_tier(guild_id, score)
        return float(config.get(f"rate_{tier}", 0.15))

    # ============================================================
    # EMPRÉSTIMOS
    # ============================================================

    @classmethod
    def can_borrow(
        cls, guild_id: int, user_id: int, amount: int
    ) -> dict:
        """Verifica se pode pegar empréstimo. Retorna {ok, reason}."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"ok": False, "reason": "credit_disabled"}

        # Valor
        if amount < int(config.get("min_loan_amount", 100)):
            return {"ok": False, "reason": "amount_too_low"}
        if amount > int(config.get("max_loan_amount", 500000)):
            return {"ok": False, "reason": "amount_too_high"}

        db = get_connection()

        # Empréstimos ativos
        active = db["loans"].count_documents({
            "guild_id": guild_id,
            "user_id": user_id,
            "status": {"$in": ["active", "late"]},
        })
        if active >= int(config.get("max_active_loans", 3)):
            return {"ok": False, "reason": "too_many_active_loans"}

        # Score
        score = cls.get_score(guild_id, user_id)
        if score < int(config.get("min_score_to_borrow", 300)):
            return {"ok": False, "reason": "score_too_low", "score": score}

        # Dívida atual vs saldo
        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(guild_id, user_id)
        total_debt = cls.get_total_debt(guild_id, user_id)
        max_ratio = float(config.get("max_debt_to_balance_ratio", 2.0))
        max_debt = max(int(config.get("min_loan_amount", 100)), int(balance * max_ratio))
        if total_debt + amount > max_debt:
            return {
                "ok": False,
                "reason": "debt_ratio_exceeded",
                "current_debt": total_debt,
                "max_debt": max_debt,
            }

        return {"ok": True, "score": score}

    @classmethod
    def create_loan(
        cls,
        guild_id: int,
        user_id: int,
        principal: int,
        installments: Optional[int] = None,
    ) -> Optional[dict]:
        """Cria empréstimo. Retorna o doc ou None."""
        config = cls.get_config(guild_id)
        check = cls.can_borrow(guild_id, user_id, principal)
        if not check.get("ok"):
            return None

        installments = installments or int(config.get("default_installments", 3))
        installments = max(1, min(int(config.get("max_installments", 12)), installments))

        score = check["score"]
        base_rate = cls.get_base_rate(guild_id, score)

        # Adiciona Selic do Banco Central
        try:
            from central_bank import CentralBank
            selic = CentralBank.get_selic(guild_id)
            base_rate = base_rate + selic
        except Exception:
            pass

        # Taxa por parcela (juros compostos)
        # Se taxa mensal é 8% e 3 parcelas, cada parcela tem juros compostos
        total_due = int(principal * ((1 + base_rate) ** installments))
        per_installment = int(total_due / installments)

        now = datetime.utcnow()
        interval_hours = int(config.get("installment_interval_hours", 24))
        next_due = now + timedelta(hours=interval_hours)

        db = get_connection()
        doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "principal": int(principal),
            "rate": float(base_rate),
            "installments": int(installments),
            "total_due": int(total_due),
            "per_installment": int(per_installment),
            "paid_amount": 0,
            "paid_installments": 0,
            "status": "active",     # active | late | paid | defaulted
            "created_at": now,
            "next_due_at": next_due,
            "score_at_creation": score,
            "interval_hours": interval_hours,
        }
        result = db["loans"].insert_one(doc)
        loan_id = str(result.inserted_id)

        # Credita valor
        from commands_economy_core import EconomyManager
        EconomyManager.add_balance(
            guild_id, user_id, principal,
            f"Empréstimo #{loan_id[:8]}",
            "loan"
        )

        # Atualiza score doc
        db["credit_scores"].update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {
                "$inc": {
                    "total_borrowed": principal,
                    "loans_taken": 1,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

        return db["loans"].find_one({"_id": result.inserted_id})

    @classmethod
    def pay_installment(
        cls, guild_id: int, user_id: int, loan_id: str, amount: Optional[int] = None
    ) -> dict:
        """Paga parcela de um empréstimo."""
        from commands_economy_core import EconomyManager

        db = get_connection()
        oid = safe_object_id(loan_id)
        if not oid:
            return {"error": "invalid_id"}

        loan = db["loans"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "user_id": user_id,
            "status": {"$in": ["active", "late"]},
        })
        if not loan:
            return {"error": "not_found"}

        per_inst = int(loan.get("per_installment", 0))
        pay_amount = amount if amount and amount > 0 else per_inst

        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < pay_amount:
            return {"error": "insufficient_balance",
                    "needed": pay_amount, "have": balance}

        # Cobra
        if not EconomyManager.remove_balance(
            guild_id, user_id, pay_amount,
            f"Parcela empréstimo #{str(loan['_id'])[:8]}",
            "loan_payment"
        ):
            return {"error": "payment_failed"}

        new_paid = int(loan.get("paid_amount", 0)) + pay_amount
        new_paid_inst = int(loan.get("paid_installments", 0)) + 1
        total_due = int(loan.get("total_due", 0))
        was_late = loan.get("status") == "late"

        new_status = "active"
        if new_paid >= total_due:
            new_status = "paid"

        next_due = loan.get("next_due_at")
        if new_status == "active":
            interval = int(loan.get("interval_hours", 24))
            next_due = datetime.utcnow() + timedelta(hours=interval)

        db["loans"].update_one(
            {"_id": loan["_id"]},
            {
                "$set": {
                    "paid_amount": new_paid,
                    "paid_installments": new_paid_inst,
                    "status": new_status,
                    "next_due_at": next_due,
                    "last_payment_at": datetime.utcnow(),
                }
            }
        )

        db["loan_payments"].insert_one({
            "guild_id": guild_id,
            "loan_id": str(loan["_id"]),
            "user_id": user_id,
            "amount": pay_amount,
            "was_late": was_late,
            "paid_at": datetime.utcnow(),
        })

        # Atualiza score
        if new_status == "paid":
            db["credit_scores"].update_one(
                {"guild_id": guild_id, "user_id": user_id},
                {
                    "$inc": {
                        "total_repaid": new_paid,
                        "loans_repaid": 1,
                    },
                    "$set": {"updated_at": datetime.utcnow()},
                },
                upsert=True,
            )
            cls.adjust_score(guild_id, user_id, 30)  # Bônus por quitar

        return {
            "ok": True,
            "paid": pay_amount,
            "remaining": max(0, total_due - new_paid),
            "status": new_status,
        }

    # ============================================================
    # PROCESSAMENTO (por tick)
    # ============================================================

    @classmethod
    def process_loans(cls, guild_id: int) -> dict:
        """
        Roda no tick. Verifica vencimentos, marca atrasos,
        aplica multas, processa calotes.
        """
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"processed": 0}

        db = get_connection()
        now = datetime.utcnow()

        # Empréstimos vencidos e ainda ativos
        overdue = list(db["loans"].find({
            "guild_id": guild_id,
            "status": "active",
            "next_due_at": {"$lte": now},
        }))

        late_count = 0
        default_count = 0

        for loan in overdue:
            grace = int(config.get("grace_period_hours", 24))
            grace_end = loan["next_due_at"] + timedelta(hours=grace)

            if now <= grace_end:
                continue  # ainda na carência

            # Está atrasado
            late_fee_pct = float(config.get("late_fee_percent", 10.0))
            max_fee_pct = float(config.get("max_late_fee_percent", 100.0))

            current_penalty = float(loan.get("late_fee_applied", 0.0))
            new_penalty = min(max_fee_pct, current_penalty + late_fee_pct)

            if loan.get("status") == "active":
                # Marca como late
                db["loans"].update_one(
                    {"_id": loan["_id"]},
                    {
                        "$set": {
                            "status": "late",
                            "late_since": now,
                            "late_fee_applied": new_penalty,
                        }
                    }
                )
                late_count += 1
                cls.adjust_score(
                    guild_id, loan["user_id"],
                    -int(config.get("score_penalty_late", 50))
                )
                db["credit_scores"].update_one(
                    {"guild_id": guild_id, "user_id": loan["user_id"]},
                    {"$inc": {"late_payments": 1}},
                    upsert=True,
                )

            # Verifica calote (tempo excessivo)
            writeoff_hours = int(config.get("writedown_after_hours", 168))
            if loan.get("late_since") and (now - loan["late_since"]).total_seconds() > writeoff_hours * 3600:
                db["loans"].update_one(
                    {"_id": loan["_id"]},
                    {"$set": {"status": "defaulted", "defaulted_at": now}}
                )
                default_count += 1
                cls.adjust_score(
                    guild_id, loan["user_id"],
                    -int(config.get("score_penalty_default", 150))
                )
                db["credit_scores"].update_one(
                    {"guild_id": guild_id, "user_id": loan["user_id"]},
                    {"$inc": {"loans_defaulted": 1}},
                    upsert=True,
                )

        return {
            "processed": len(overdue),
            "late": late_count,
            "defaulted": default_count,
        }

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_total_debt(cls, guild_id: int, user_id: int) -> int:
        db = get_connection()
        pipeline = [
            {"$match": {
                "guild_id": guild_id,
                "user_id": user_id,
                "status": {"$in": ["active", "late"]},
            }},
            {"$group": {
                "_id": None,
                "total": {"$sum": {"$subtract": ["$total_due", "$paid_amount"]}}
            }}
        ]
        result = list(db["loans"].aggregate(pipeline))
        return int(result[0]["total"]) if result else 0

    @classmethod
    def get_active_loans(cls, guild_id: int, user_id: int) -> List[dict]:
        db = get_connection()
        return list(db["loans"].find({
            "guild_id": guild_id,
            "user_id": user_id,
            "status": {"$in": ["active", "late"]},
        }).sort("created_at", -1))

    @classmethod
    def clear_cache(cls) -> None:
        _credit_cache.clear()


async def setup(bot):
    pass