# ============================================================
# TAX_ENGINE.PY - v7.0 Fase 5 (Impostos com Destinação)
# ============================================================
# Responsável por:
#   • Gerenciar alíquotas de impostos
#   • Cobrar imposto e destinar ao tesouro
#   • Tipos: income (salário), transfer (pay), wealth (patrimônio)
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


DEFAULT_TAX_CONFIG = {
    "enabled": True,

    # Alíquotas padrão (% em decimal)
    "income_tax": 0.05,       # sobre salários
    "transfer_tax": 0.02,     # sobre .pay
    "wealth_tax": 0.00,       # sobre patrimônio (desligado)
    "wealth_threshold": 1_000_000,
    "market_tax": 0.01,       # sobre vendas no mercado
    "dividend_tax": 0.10,     # sobre dividendos

    # Configuração avançada
    "progressive": False,     # imposto progressivo?
    "min_balance_to_tax": 1000,
    "exempt_users": [],       # IDs isentos
    "auto_transfer_to_treasury": True,
}


_tax_cache = TTLCache(max_size=100, ttl=60)


class TaxEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _tax_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "taxes"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_TAX_CONFIG, **(doc.get("config") or {})}
        _tax_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "taxes"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _tax_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # TAXAS
    # ============================================================

    @classmethod
    def get_rate(cls, guild_id: int, tax_type: str) -> float:
        config = cls.get_config(guild_id)
        key_map = {
            "income": "income_tax",
            "transfer": "transfer_tax",
            "wealth": "wealth_tax",
            "market": "market_tax",
            "dividend": "dividend_tax",
        }
        key = key_map.get(tax_type, f"{tax_type}_tax")
        return float(config.get(key, 0.0))

    @classmethod
    def set_rate(cls, guild_id: int, tax_type: str, rate: float) -> None:
        rate = max(0.0, min(0.5, float(rate)))
        key_map = {
            "income": "income_tax",
            "transfer": "transfer_tax",
            "wealth": "wealth_tax",
            "market": "market_tax",
            "dividend": "dividend_tax",
        }
        key = key_map.get(tax_type, f"{tax_type}_tax")
        cls.update_config(guild_id, key, rate)

    # ============================================================
    # COBRANÇA
    # ============================================================

    @classmethod
    def collect_tax(
        cls,
        guild_id: int,
        user_id: int,
        base_amount: int,
        tax_type: str,
        description: str = "",
    ) -> dict:
        """
        Cobra imposto e destina ao tesouro.
        Retorna {collected, tax_rate}.
        """
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"collected": 0, "tax_rate": 0.0}

        # Isento?
        if user_id in (config.get("exempt_users") or []):
            return {"collected": 0, "tax_rate": 0.0}

        # Abaixo do mínimo?
        if base_amount < int(config.get("min_balance_to_tax", 0)):
            return {"collected": 0, "tax_rate": 0.0}

        rate = cls.get_rate(guild_id, tax_type)
        if rate <= 0:
            return {"collected": 0, "tax_rate": 0.0}

        tax_amount = int(base_amount * rate)
        if tax_amount <= 0:
            return {"collected": 0, "tax_rate": rate}

        # Registra
        db = get_connection()
        db["tax_records"].insert_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "tax_type": tax_type,
            "base_amount": int(base_amount),
            "tax_amount": int(tax_amount),
            "rate": float(rate),
            "description": description[:200],
            "timestamp": datetime.utcnow(),
        })

        # Destina ao tesouro
        if config.get("auto_transfer_to_treasury", True):
            try:
                from treasury_engine import TreasuryEngine
                TreasuryEngine.collect(
                    guild_id, tax_amount,
                    f"Imposto {tax_type} de {user_id}"
                )
            except Exception:
                pass

        return {"collected": tax_amount, "tax_rate": rate}

    # ============================================================
    # IMPOSTO DE RIQUEZA (chamado pelo tick)
    # ============================================================

    @classmethod
    def collect_wealth_tax(cls, guild_id: int) -> dict:
        """Cobra imposto de riqueza de usuários acima do threshold."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"collected": 0, "taxed_users": 0}

        rate = cls.get_rate(guild_id, "wealth")
        if rate <= 0:
            return {"collected": 0, "taxed_users": 0}

        threshold = int(config.get("wealth_threshold", 1_000_000))
        db = get_connection()
        from commands_economy_core import EconomyManager

        rich = list(db["economy_balances"].find({
            "guild_id": guild_id,
            "balance": {"$gt": threshold},
        }))

        total = 0
        count = 0

        for u in rich:
            excess = int(u["balance"]) - threshold
            tax = int(excess * rate)
            if tax <= 0:
                continue
            if EconomyManager.remove_balance(
                guild_id, u["user_id"], tax,
                "Imposto de riqueza", "wealth_tax"
            ):
                total += tax
                count += 1
                cls.collect_tax(
                    guild_id, u["user_id"], excess, "wealth",
                    "Imposto de riqueza automático"
                )

        return {"collected": total, "taxed_users": count}

    # ============================================================
    # HISTÓRICO
    # ============================================================

    @classmethod
    def get_stats(cls, guild_id: int, hours: int = 24) -> dict:
        db = get_connection()
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        pipeline = [
            {"$match": {
                "guild_id": guild_id,
                "timestamp": {"$gte": cutoff},
            }},
            {"$group": {
                "_id": "$tax_type",
                "total": {"$sum": "$tax_amount"},
                "count": {"$sum": 1},
            }},
        ]
        results = list(db["tax_records"].aggregate(pipeline))
        return {r["_id"]: {"total": r["total"], "count": r["count"]} for r in results}

    @classmethod
    def clear_cache(cls) -> None:
        _tax_cache.clear()


async def setup(bot):
    pass