# ============================================================
# BANK_ENGINE.PY - v7.0 Fase 3 (Bancos)
# ============================================================
# Responsável por:
#   • Bancos com reservas fracionárias
#   • Contas bancárias (depósito/saque)
#   • Criação de moeda via empréstimos
#   • Multiplicador bancário
# ============================================================

from datetime import datetime
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id
from credit_engine import CreditEngine


DEFAULT_BANK_CONFIG = {
    "enabled": True,
    "reserve_ratio": 0.10,           # 10% de reserva obrigatória
    "min_bank_capital": 50_000,      # capital mínimo pra abrir banco
    "bank_creation_cost": 25_000,    # custo pra criar banco
    "max_banks_per_guild": 10,
    "max_banks_per_user": 1,
    "deposit_interest": 0.002,       # 0.2% ao tick
    "loan_interest_margin": 0.03,    # +3% acima da taxa base
    "allow_player_banks": True,
    "auto_process_interest": True,
}


_bank_cache = TTLCache(max_size=200, ttl=60)


class BankEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _bank_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "banks"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_BANK_CONFIG, **(doc.get("config") or {})}
        _bank_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "banks"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _bank_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # CRIAÇÃO
    # ============================================================

    @classmethod
    def create_bank(
        cls, guild_id: int, owner_id: int, name: str, initial_capital: int
    ) -> Optional[dict]:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True) or not config.get("allow_player_banks", True):
            return None

        db = get_connection()

        # Limites
        total = db["bank_accounts"].count_documents({
            "guild_id": guild_id, "type": "bank", "active": True,
        })
        if total >= int(config.get("max_banks_per_guild", 10)):
            return None

        user_banks = db["bank_accounts"].count_documents({
            "guild_id": guild_id, "owner_id": owner_id,
            "type": "bank", "active": True,
        })
        if user_banks >= int(config.get("max_banks_per_user", 1)):
            return None

        min_cap = int(config.get("min_bank_capital", 50000))
        cost = int(config.get("bank_creation_cost", 25000))

        if initial_capital < min_cap:
            return None

        total_cost = min_cap + cost
        from commands_economy_core import EconomyManager
        if EconomyManager.get_balance(guild_id, owner_id) < total_cost:
            return None

        if not EconomyManager.remove_balance(
            guild_id, owner_id, total_cost,
            f"Criação de banco: {name}", "bank_create"
        ):
            return None

        doc = {
            "guild_id": guild_id,
            "type": "bank",
            "owner_id": owner_id,
            "name": name[:50],
            "capital": initial_capital,
            "reserves": initial_capital,      # reserva obrigatória
            "loans_out": 0,                   # total emprestado
            "deposits": 0,                    # total em depósitos
            "active": True,
            "created_at": datetime.utcnow(),
        }
        result = db["bank_accounts"].insert_one(doc)
        return db["bank_accounts"].find_one({"_id": result.inserted_id})

    # ============================================================
    # CONTAS
    # ============================================================

    @classmethod
    def create_account(
        cls, guild_id: int, user_id: int, bank_id: str
    ) -> Optional[dict]:
        db = get_connection()
        oid = safe_object_id(bank_id)
        if not oid:
            return None

        bank = db["bank_accounts"].find_one({
            "_id": oid, "guild_id": guild_id,
            "type": "bank", "active": True,
        })
        if not bank:
            return None

        existing = db["bank_accounts"].find_one({
            "guild_id": guild_id,
            "type": "client",
            "owner_id": user_id,
            "bank_id": str(bank["_id"]),
        })
        if existing:
            return existing

        doc = {
            "guild_id": guild_id,
            "type": "client",
            "owner_id": user_id,
            "bank_id": str(bank["_id"]),
            "balance": 0,
            "created_at": datetime.utcnow(),
            "active": True,
        }
        result = db["bank_accounts"].insert_one(doc)
        return db["bank_accounts"].find_one({"_id": result.inserted_id})

    @classmethod
    def deposit(
        cls, guild_id: int, user_id: int, bank_id: str, amount: int
    ) -> dict:
        if amount <= 0:
            return {"error": "invalid_amount"}

        db = get_connection()
        bank = cls._get_bank(guild_id, bank_id)
        if not bank:
            return {"error": "bank_not_found"}

        account = cls.create_account(guild_id, user_id, bank_id)
        if not account:
            return {"error": "account_failed"}

        from commands_economy_core import EconomyManager
        if not EconomyManager.remove_balance(
            guild_id, user_id, amount,
            f"Depósito em {bank.get('name')}", "bank_deposit"
        ):
            return {"error": "insufficient_balance"}

        # Credita na conta
        db["bank_accounts"].update_one(
            {"_id": account["_id"]},
            {"$inc": {"balance": amount}}
        )
        # Registra no banco
        db["bank_accounts"].update_one(
            {"_id": bank["_id"]},
            {"$inc": {"deposits": amount}}
        )

        return {
            "ok": True,
            "deposited": amount,
            "account_balance": int(account.get("balance", 0)) + amount,
        }

    @classmethod
    def withdraw(
        cls, guild_id: int, user_id: int, bank_id: str, amount: int
    ) -> dict:
        if amount <= 0:
            return {"error": "invalid_amount"}

        db = get_connection()
        bank = cls._get_bank(guild_id, bank_id)
        if not bank:
            return {"error": "bank_not_found"}

        account = db["bank_accounts"].find_one({
            "guild_id": guild_id,
            "type": "client",
            "owner_id": user_id,
            "bank_id": str(bank["_id"]),
        })
        if not account or int(account.get("balance", 0)) < amount:
            return {"error": "insufficient_funds"}

        # Debita
        db["bank_accounts"].update_one(
            {"_id": account["_id"]},
            {"$inc": {"balance": -amount}}
        )
        db["bank_accounts"].update_one(
            {"_id": bank["_id"]},
            {"$inc": {"deposits": -amount}}
        )

        from commands_economy_core import EconomyManager
        EconomyManager.add_balance(
            guild_id, user_id, amount,
            f"Saque de {bank.get('name')}", "bank_withdraw"
        )

        return {"ok": True, "withdrawn": amount}

    # ============================================================
    # EMPRÉSTIMO BANCÁRIO
    # ============================================================

    @classmethod
    def bank_loan(
        cls, guild_id: int, user_id: int, bank_id: str, amount: int
    ) -> dict:
        """
        Empréstimo direto do banco (não é o credit_engine padrão).
        Aqui o banco é o credor.
        """
        config = cls.get_config(guild_id)
        db = get_connection()
        bank = cls._get_bank(guild_id, bank_id)
        if not bank:
            return {"error": "bank_not_found"}

        # Verifica reservas (reservas fracionárias)
        reserve_ratio = float(config.get("reserve_ratio", 0.10))
        deposits = int(bank.get("deposits", 0))
        loans_out = int(bank.get("loans_out", 0))
        reserves = int(bank.get("reserves", 0))

        max_loans = int(deposits * (1 - reserve_ratio))
        available = max_loans - loans_out
        if available < amount:
            return {"error": "bank_insufficient_capacity",
                    "available": available}

        # Score + taxa
        score = CreditEngine.get_score(guild_id, user_id)
        base_rate = CreditEngine.get_base_rate(guild_id, score)
        margin = float(config.get("loan_interest_margin", 0.03))
        rate = base_rate + margin

        # Cria como loan normal, mas com bank_id
        loan_doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "bank_id": str(bank["_id"]),
            "principal": int(amount),
            "rate": float(rate),
            "installments": 3,
            "total_due": int(amount * ((1 + rate) ** 3)),
            "per_installment": int((amount * ((1 + rate) ** 3)) / 3),
            "paid_amount": 0,
            "paid_installments": 0,
            "status": "active",
            "created_at": datetime.utcnow(),
            "next_due_at": datetime.utcnow(),
            "score_at_creation": score,
            "interval_hours": 24,
        }

        from commands_economy_core import EconomyManager
        EconomyManager.add_balance(
            guild_id, user_id, amount,
            f"Empréstimo bancário ({bank.get('name')})",
            "bank_loan"
        )

        db["loans"].insert_one(loan_doc)
        db["bank_accounts"].update_one(
            {"_id": bank["_id"]},
            {"$inc": {"loans_out": amount}}
        )

        return {
            "ok": True,
            "borrowed": amount,
            "rate": rate,
            "total_due": loan_doc["total_due"],
        }

    # ============================================================
    # PROCESSAMENTO POR TICK
    # ============================================================

    @classmethod
    def process_bank_interest(cls, guild_id: int) -> dict:
        """Paga juros de depósito + processa receita de empréstimos."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"processed": 0}

        db = get_connection()
        rate = float(config.get("deposit_interest", 0.002))

        # Contas de cliente recebem juros
        accounts = list(db["bank_accounts"].find({
            "guild_id": guild_id,
            "type": "client",
            "balance": {"$gt": 0},
        }))

        from commands_economy_core import EconomyManager
        paid = 0
        for acc in accounts:
            balance = int(acc.get("balance", 0))
            interest = int(balance * rate)
            if interest <= 0:
                continue
            # O juro vem do banco (debita da reserva e credita no cliente)
            bank = db["bank_accounts"].find_one({
                "_id": safe_object_id(acc.get("bank_id", "")),
                "type": "bank",
            })
            if not bank or int(bank.get("reserves", 0)) < interest:
                continue
            db["bank_accounts"].update_one(
                {"_id": bank["_id"]},
                {"$inc": {"reserves": -interest}}
            )
            db["bank_accounts"].update_one(
                {"_id": acc["_id"]},
                {"$inc": {"balance": interest}}
            )
            paid += 1

        return {"processed": paid}

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def _get_bank(cls, guild_id: int, bank_id: str) -> Optional[dict]:
        oid = safe_object_id(bank_id)
        if not oid:
            return None
        db = get_connection()
        return db["bank_accounts"].find_one({
            "_id": oid, "guild_id": guild_id,
            "type": "bank", "active": True,
        })

    @classmethod
    def list_banks(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["bank_accounts"].find({
            "guild_id": guild_id, "type": "bank", "active": True,
        }).sort("capital", -1))

    @classmethod
    def get_account(
        cls, guild_id: int, user_id: int, bank_id: str
    ) -> Optional[dict]:
        db = get_connection()
        return db["bank_accounts"].find_one({
            "guild_id": guild_id,
            "type": "client",
            "owner_id": user_id,
            "bank_id": bank_id,
        })

    @classmethod
    def get_money_multiplier(cls, guild_id: int) -> float:
        """
        Multiplicador bancário = 1 / reserve_ratio.
        Ex: 10% de reserva → 10x multiplicador.
        """
        config = cls.get_config(guild_id)
        rr = float(config.get("reserve_ratio", 0.10))
        if rr <= 0:
            return 1.0
        return round(1.0 / rr, 2)

    @classmethod
    def clear_cache(cls) -> None:
        _bank_cache.clear()


async def setup(bot):
    pass