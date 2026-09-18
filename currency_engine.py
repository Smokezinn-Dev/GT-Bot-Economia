# ============================================================
# CURRENCY_ENGINE.PY - v7.0 Fase 6 (Moeda e Câmbio)
# ============================================================
# Responsável por:
#   • Moeda própria por guild (nome, símbolo, oferta)
#   • Taxa de câmbio entre guilds
#   • Reservas internacionais
#   • Paridade por PIB + confiança
# ============================================================

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database import get_connection
from utils import TTLCache


DEFAULT_CURRENCY_CONFIG = {
    "enabled": True,
    "default_name": "Credits",
    "default_symbol": "₡",
    "default_rate": 1.0,          # paridade base com "moeda global"
    "allow_devaluation": True,
    "max_inflation_devaluation": 0.10,  # 10% por dia
    "min_rate": 0.01,
    "max_rate": 100.0,
    "confidence_weight": 0.3,     # peso da confiança no câmbio
    "gdp_weight": 0.5,            # peso do PIB
    "supply_weight": 0.2,         # peso da oferta
}


_currency_cache = TTLCache(max_size=300, ttl=60)


class CurrencyEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _currency_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "interguild"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_CURRENCY_CONFIG, **(doc.get("config") or {})}
        _currency_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "interguild"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _currency_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # MOEDA
    # ============================================================

    @classmethod
    def get_currency(cls, guild_id: int) -> dict:
        db = get_connection()
        doc = db["currencies"].find_one({"guild_id": guild_id})
        if doc:
            return doc

        config = cls.get_config(guild_id)
        new_doc = {
            "guild_id": guild_id,
            "name": config.get("default_name", "Credits"),
            "symbol": config.get("default_symbol", "₡"),
            "rate": float(config.get("default_rate", 1.0)),
            "confidence": 1.0,
            "reserves": 0,
            "last_rate_update": datetime.utcnow(),
            "created_at": datetime.utcnow(),
        }
        db["currencies"].insert_one(new_doc.copy())
        return new_doc

    @classmethod
    def set_currency_info(
        cls, guild_id: int, name: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> dict:
        db = get_connection()
        update = {}
        if name:
            update["name"] = name[:30]
        if symbol:
            update["symbol"] = symbol[:5]
        if update:
            db["currencies"].update_one(
                {"guild_id": guild_id},
                {"$set": update, "$setOnInsert": {"guild_id": guild_id}},
                upsert=True,
            )
        return cls.get_currency(guild_id)

    @classmethod
    def get_rate(cls, guild_id: int) -> float:
        curr = cls.get_currency(guild_id)
        return float(curr.get("rate", 1.0))

    @classmethod
    def set_rate(cls, guild_id: int, rate: float) -> float:
        rate = max(0.01, min(100.0, float(rate)))
        db = get_connection()
        db["currencies"].update_one(
            {"guild_id": guild_id},
            {"$set": {"rate": rate, "last_rate_update": datetime.utcnow()}},
            upsert=True,
        )
        _currency_cache.invalidate(f"cfg:{guild_id}")
        return rate

    @classmethod
    def adjust_confidence(cls, guild_id: int, delta: float) -> float:
        curr = cls.get_currency(guild_id)
        new_conf = max(0.1, min(2.0, float(curr.get("confidence", 1.0)) + delta))
        db = get_connection()
        db["currencies"].update_one(
            {"guild_id": guild_id},
            {"$set": {"confidence": new_conf, "confidence_updated_at": datetime.utcnow()}},
        )
        return new_conf

    # ============================================================
    # PIB ESTIMADO
    # ============================================================

    @classmethod
    def estimate_gdp(cls, guild_id: int) -> int:
        """
        PIB estimado = saldo em circulação + valor de empresas + estoque de recursos.
        É uma proxy pra comparação entre guilds.
        """
        db = get_connection()

        # 1. Saldo total
        from commands_economy_core import EconomyManager
        total_money = EconomyManager.get_total_balance(guild_id)

        # 2. Valor das empresas (caixa + inventário estimado)
        companies = list(db["companies"].find({
            "guild_id": guild_id,
            "active": True,
        }))
        company_value = 0
        for c in companies:
            cash = int(c.get("cash", 0))
            inv = c.get("inventory") or {}
            inv_value = sum(int(v) * 10 for v in inv.values())  # estimativa simples
            company_value += cash + inv_value

        # 3. Valor do tesouro
        treasury = 0
        try:
            from treasury_engine import TreasuryEngine
            treasury = TreasuryEngine.get_balance(guild_id)
        except Exception:
            pass

        return int(total_money + company_value + treasury)

    # ============================================================
    # CÂMBIO
    # ============================================================

    @classmethod
    def compute_rate(cls, from_guild: int, to_guild: int) -> float:
        """
        Calcula taxa de câmbio entre duas guilds.
        rate = (PIB_destino / PIB_origem) × (oferta_origem / oferta_destino) × confiança
        """
        if from_guild == to_guild:
            return 1.0

        config = cls.get_config(from_guild)

        from_gdp = max(1, cls.estimate_gdp(from_guild))
        to_gdp = max(1, cls.estimate_gdp(to_guild))

        from_curr = cls.get_currency(from_guild)
        to_curr = cls.get_currency(to_guild)

        from_rate = float(from_curr.get("rate", 1.0))
        to_rate = float(to_curr.get("rate", 1.0))

        from_conf = float(from_curr.get("confidence", 1.0))
        to_conf = float(to_curr.get("confidence", 1.0))

        # Fatores
        gdp_factor = to_gdp / from_gdp
        supply_factor = from_rate / max(0.01, to_rate)
        confidence_factor = from_conf / max(0.01, to_conf)

        # Pesos
        w_gdp = float(config.get("gdp_weight", 0.5))
        w_supply = float(config.get("supply_weight", 0.2))
        w_conf = float(config.get("confidence_weight", 0.3))

        # Combina (log-space pra ficar estável)
        log_rate = (
            w_gdp * math.log(max(0.01, gdp_factor)) +
            w_supply * math.log(max(0.01, supply_factor)) +
            w_conf * math.log(max(0.01, confidence_factor))
        )
        rate = math.exp(log_rate)
        return max(0.01, min(100.0, rate))

    @classmethod
    def convert(
        cls, amount: int, from_guild: int, to_guild: int
    ) -> Tuple[int, float]:
        """Converte um valor entre duas guilds. Retorna (valor, taxa)."""
        if from_guild == to_guild:
            return int(amount), 1.0
        rate = cls.compute_rate(from_guild, to_guild)
        converted = int(amount * rate)
        return converted, rate

    @classmethod
    def record_rate(cls, from_guild: int, to_guild: int, rate: float) -> None:
        db = get_connection()
        try:
            db["exchange_rates"].insert_one({
                "from_guild": from_guild,
                "to_guild": to_guild,
                "rate": rate,
                "timestamp": datetime.utcnow(),
            })
        except Exception:
            pass

    @classmethod
    def update_all_rates(cls, guild_id: int) -> int:
        """
        Atualiza taxa de câmbio da guild com todas as outras.
        Chamado pelo tick.
        """
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return 0

        db = get_connection()
        other_currencies = list(db["currencies"].find({
            "guild_id": {"$ne": guild_id},
        }, {"guild_id": 1}))

        count = 0
        for other in other_currencies:
            other_id = other["guild_id"]
            rate = cls.compute_rate(guild_id, other_id)
            cls.record_rate(guild_id, other_id, rate)
            count += 1

        return count

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def list_currencies(cls) -> List[dict]:
        db = get_connection()
        return list(db["currencies"].find({}))

    @classmethod
    def get_rate_history(
        cls, from_guild: int, to_guild: int, limit: int = 20
    ) -> List[dict]:
        db = get_connection()
        return list(db["exchange_rates"].find({
            "from_guild": from_guild,
            "to_guild": to_guild,
        }).sort("timestamp", -1).limit(limit))

    @classmethod
    def clear_cache(cls) -> None:
        _currency_cache.clear()


async def setup(bot):
    pass