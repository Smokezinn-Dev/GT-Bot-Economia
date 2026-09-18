# ============================================================
# INFLATION_ENGINE.PY - v7.0 (IPC Sintético)
# ============================================================
# Responsável por:
#   • Medir inflação via índice de preços (IPC)
#   • Comparar moeda em circulação vs produção
#   • Registrar histórico de inflação
#   • Fornecer índice de poder de compra
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


DEFAULT_INFLATION_CONFIG = {
    "enabled": True,

    # Base da cesta de preços (quantos itens rastrear)
    "basket_size": 20,

    # Peso do dinheiro em circulação no cálculo da inflação (0.0 - 1.0)
    "money_supply_weight": 0.6,

    # Peso da produção no cálculo (se produção cresce, inflação cai)
    "production_weight": 0.4,

    # Meta de inflação (% por dia)
    "target_inflation": 0.5,

    # Faixa aceitável
    "acceptable_range": [0.0, 2.0],

    # Alerta se passar disso
    "alert_threshold": 5.0,

    # Deflação (queda de preços) — permitir?
    "allow_deflation": True,
}


_ipc_cache = TTLCache(max_size=200, ttl=60)


class InflationEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _ipc_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["price_config"].find_one({"guild_id": guild_id}, {"_id": 0}) or {}
        # Usa a mesma collection de config de preços (prefixo inflation_)
        inflation_cfg = {}
        for k, v in doc.items():
            if k.startswith("inflation_"):
                inflation_cfg[k[10:]] = v
        config = {**DEFAULT_INFLATION_CONFIG, **inflation_cfg}
        _ipc_cache.set(f"cfg:{guild_id}", config)
        return config

    # ============================================================
    # CÁLCULO DO IPC
    # ============================================================

    @classmethod
    def calculate_ipc(cls, guild_id: int) -> dict:
        """
        Calcula inflação atual.

        Lógica:
            IPC = (Σ preços atuais / Σ preços base) - 1
            Ajusta com peso de moeda e produção.
        """
        db = get_connection()

        # Pega amostra de preços (loja + histórico)
        shop_docs = list(db["economy_shop"].find(
            {"guild_id": guild_id, "active": {"$ne": False}},
            {"_id": 1, "price": 1, "base_price": 1, "category": 1}
        ).limit(100))

        if not shop_docs:
            return {
                "guild_id": guild_id,
                "ipc": 0.0,
                "index": 100.0,
                "status": "no_data",
                "timestamp": datetime.utcnow(),
            }

        total_current = 0
        total_base = 0
        tracked = 0

        for doc in shop_docs:
            base = doc.get("base_price") or doc.get("price", 0)
            current = doc.get("price", 0)
            if base > 0 and current > 0:
                total_current += current
                total_base += base
                tracked += 1

        if total_base == 0 or tracked == 0:
            return {
                "guild_id": guild_id,
                "ipc": 0.0,
                "index": 100.0,
                "status": "no_prices",
                "timestamp": datetime.utcnow(),
            }

        # IPC bruto
        raw_index = (total_current / total_base) * 100.0
        raw_ipc = (total_current / total_base) - 1.0

        # Fatores externos
        config = cls.get_config(guild_id)
        m_weight = float(config.get("money_supply_weight", 0.6))
        p_weight = float(config.get("production_weight", 0.4))

        # Money supply atual
        from commands_economy_core import EconomyManager
        total_money = EconomyManager.get_total_balance(guild_id)

        # Produção estimada (se existir, senão 1.0)
        production = cls._get_production_estimate(guild_id)

        # Fator monetário
        money_factor = 1.0
        state = db["economy_state"].find_one(
            {"guild_id": guild_id}, {"baseline_money": 1, "baseline_production": 1}
        )
        if state:
            base_money = max(1, int(state.get("baseline_money", 1)))
            base_prod = max(1.0, float(state.get("baseline_production", 1.0)))
            money_factor = (total_money / base_money) / (production / base_prod)

        # IPC ajustado
        adjusted_ipc = raw_ipc * (1 - m_weight) + (money_factor - 1.0) * m_weight

        # Classificação
        pct = adjusted_ipc * 100
        if pct < 0 and config.get("allow_deflation", True):
            status = "deflation"
        elif pct < float(config.get("target_inflation", 0.5)):
            status = "low"
        elif pct <= float(config.get("acceptable_range", [0, 2])[1]):
            status = "healthy"
        elif pct < float(config.get("alert_threshold", 5.0)):
            status = "high"
        else:
            status = "critical"

        result = {
            "guild_id": guild_id,
            "ipc": round(adjusted_ipc, 4),
            "index": round(raw_index, 2),
            "status": status,
            "tracked_items": tracked,
            "money_supply": total_money,
            "production": production,
            "timestamp": datetime.utcnow(),
        }

        # Registra histórico
        try:
            db["inflation_index"].insert_one(result.copy())
        except Exception:
            pass

        return result

    @classmethod
    def _get_production_estimate(cls, guild_id: int) -> float:
        """Produção estimada. Se company_engine existir, usa. Senão 1.0."""
        try:
            db = get_connection()
            state = db["economy_state"].find_one(
                {"guild_id": guild_id}, {"production_rate": 1}
            )
            return float(state.get("production_rate", 1.0)) if state else 1.0
        except Exception:
            return 1.0

    # ============================================================
    # POWER DE COMPRA
    # ============================================================

    @classmethod
    def get_purchasing_power(cls, guild_id: int, nominal_amount: int) -> int:
        """Ajusta um valor nominal pelo IPC atual."""
        db = get_connection()
        latest = db["inflation_index"].find_one(
            {"guild_id": guild_id}, sort=[("timestamp", -1)]
        )
        if not latest:
            return nominal_amount
        index = float(latest.get("index", 100.0))
        if index <= 0:
            return nominal_amount
        # Poder de compra = valor nominal × (100 / índice)
        return int(nominal_amount * (100.0 / index))

    @classmethod
    def get_history(cls, guild_id: int, limit: int = 30) -> List[dict]:
        db = get_connection()
        return list(
            db["inflation_index"]
            .find({"guild_id": guild_id})
            .sort("timestamp", -1)
            .limit(limit)
        )

    # ============================================================
    # ESTADO DA ECONOMIA
    # ============================================================

    @classmethod
    def update_economy_state(cls, guild_id: int) -> dict:
        """Atualiza o documento de estado da economia."""
        from commands_economy_core import EconomyManager
        db = get_connection()

        total_money = EconomyManager.get_total_balance(guild_id)
        ipc_data = cls.calculate_ipc(guild_id)

        state_doc = {
            "guild_id": guild_id,
            "total_money": total_money,
            "ipc": ipc_data.get("ipc", 0.0),
            "ipc_status": ipc_data.get("status", "unknown"),
            "last_updated": datetime.utcnow(),
        }

        db["economy_state"].update_one(
            {"guild_id": guild_id},
            {
                "$set": state_doc,
                "$setOnInsert": {
                    "baseline_money": total_money,
                    "baseline_production": 1.0,
                    "created_at": datetime.utcnow(),
                },
            },
            upsert=True,
        )

        return state_doc

    @classmethod
    def clear_cache(cls) -> None:
        _ipc_cache.clear()