# ============================================================
# PRICE_ENGINE.PY - v7.0 (Preços Endógenos)
# ============================================================
# Responsável por:
#   • Calcular preços baseados em oferta/demanda/moeda
#   • Ajustar preços de loja dinamicamente
#   • Registrar histórico de preços
#   • Detectar escassez e abundância
# ============================================================

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database import get_connection
from utils import TTLCache, retry_mongo


# ============================================================
# CONFIGURAÇÃO PADRÃO (tudo customizável pelo presidente)
# ============================================================

DEFAULT_PRICE_CONFIG = {
    "enabled": True,

    # Elasticidade-preço da demanda (quanto maior, mais sensível)
    "demand_elasticity": 0.8,

    # Elasticidade-preço da oferta
    "supply_elasticity": 0.6,

    # Peso da moeda em circulação no preço (0.0 a 1.0)
    # 0.0 = ignora inflação monetária
    # 1.0 = preço 100% atrelado à moeda
    "money_supply_weight": 0.5,

    # Limites de variação de preço por tick (evita choques bruscos)
    "max_change_per_tick": 0.15,   # ±15% por tick
    "min_multiplier": 0.5,          # preço mínimo = 50% do base
    "max_multiplier": 3.0,          # preço máximo = 300% do base

    # Sensibilidade a estoque da loja
    "stock_sensitivity": 0.03,

    # Frequência de recálculo (em ticks)
    "recalc_every_ticks": 1,

    # Preços de referência (opcional) — admin pode fixar
    "anchor_prices": {},            # {"item_id": price_float}
}


# ============================================================
# CACHE
# ============================================================

_price_cache = TTLCache(max_size=300, ttl=30)
_velocity_cache = TTLCache(max_size=200, ttl=120)


# ============================================================
# ENGINE
# ============================================================

class PriceEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _price_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["price_config"].find_one({"guild_id": guild_id}, {"_id": 0}) or {}
        config = {**DEFAULT_PRICE_CONFIG, **doc}
        _price_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["price_config"].update_one(
            {"guild_id": guild_id}, {"$set": {key: value}}, upsert=True
        )
        _price_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # CÁLCULO DE PREÇO
    # ============================================================

    @classmethod
    def calculate_price(
        cls,
        guild_id: int,
        base_price: float,
        demand: float = 1.0,
        supply: float = 1.0,
        stock: int = -1,
        money_supply: Optional[int] = None,
    ) -> int:
        """
        Calcula preço endógeno.

        Fórmula:
            P = P_base × D_elasticity × S_elasticity × M_weight × stock_factor

        Onde:
            D_elasticity = (demand / baseline_demand) ^ (-demand_elasticity)
            S_elasticity = (supply / baseline_supply) ^ (supply_elasticity)
            M_weight     = 1 + money_supply_weight × (moeda / baseline_moeda - 1)
            stock_factor = 1 + stock_sensitivity × (stock_inicial - stock_atual)
        """
        if base_price <= 0:
            return 0

        config = cls.get_config(guild_id)

        if not config.get("enabled", True):
            return int(base_price)

        # 1. Demanda (se demanda sobe, preço sobe → elasticidade negativa no expoente)
        d_elast = float(config.get("demand_elasticity", 0.8))
        demand_factor = max(0.2, min(5.0, (demand) ** (-d_elast)))

        # 2. Oferta (se oferta sobe, preço cai → elasticidade negativa)
        s_elast = float(config.get("supply_elasticity", 0.6))
        supply_factor = max(0.2, min(5.0, (supply) ** (-s_elast)))

        # 3. Moeda em circulação
        m_weight = float(config.get("money_supply_weight", 0.5))
        money_factor = 1.0
        if money_supply is not None and m_weight > 0:
            baseline = cls._get_baseline_money(guild_id)
            if baseline > 0:
                ratio = money_supply / baseline
                money_factor = 1 + m_weight * (ratio - 1)
                money_factor = max(0.5, min(3.0, money_factor))

        # 4. Estoque (se estoque cai, preço sobe)
        stock_factor = 1.0
        if stock >= 0:
            stock_sens = float(config.get("stock_sensitivity", 0.03))
            # Estoque inicial de referência = 100
            stock_factor = 1 + stock_sens * (100 - stock) / 100
            stock_factor = max(0.5, min(2.0, stock_factor))

        # Fórmula final
        raw = base_price * demand_factor * supply_factor * money_factor * stock_factor

        # Aplicar limites
        min_mult = float(config.get("min_multiplier", 0.5))
        max_mult = float(config.get("max_multiplier", 3.0))
        raw = max(base_price * min_mult, min(base_price * max_mult, raw))

        return max(1, int(round(raw)))

    @classmethod
    def adjust_existing_price(
        cls,
        guild_id: int,
        item_id: str,
        current_price: int,
        base_price: int,
        target_price: int,
    ) -> int:
        """
        Ajusta preço suavemente (evita choques bruscos).
        Respeita max_change_per_tick.
        """
        config = cls.get_config(guild_id)
        max_change = float(config.get("max_change_per_tick", 0.15))

        if current_price <= 0:
            return target_price

        delta = target_price - current_price
        max_delta = int(current_price * max_change)

        if abs(delta) > max_delta:
            delta = max_delta if delta > 0 else -max_delta

        new_price = current_price + delta
        return max(1, new_price)

    # ============================================================
    # ANCHOR PRICES
    # ============================================================

    @classmethod
    def get_anchor_price(cls, guild_id: int, item_id: str) -> Optional[int]:
        config = cls.get_config(guild_id)
        anchors = config.get("anchor_prices") or {}
        val = anchors.get(str(item_id))
        return int(val) if val is not None else None

    @classmethod
    def set_anchor_price(cls, guild_id: int, item_id: str, price: int) -> None:
        config = cls.get_config(guild_id)
        anchors = dict(config.get("anchor_prices") or {})
        if price <= 0:
            anchors.pop(str(item_id), None)
        else:
            anchors[str(item_id)] = price
        cls.update_config(guild_id, "anchor_prices", anchors)

    # ============================================================
    # HISTÓRICO
    # ============================================================

    @classmethod
    def record_price_history(
        cls, guild_id: int, item_id: str, price: int, base_price: int
    ) -> None:
        db = get_connection()
        try:
            db["price_history"].insert_one({
                "guild_id": guild_id,
                "item_id": str(item_id),
                "price": price,
                "base_price": base_price,
                "timestamp": datetime.utcnow(),
            })
        except Exception:
            pass

    @classmethod
    def get_price_history(
        cls, guild_id: int, item_id: str, limit: int = 20
    ) -> List[dict]:
        db = get_connection()
        return list(
            db["price_history"]
            .find({"guild_id": guild_id, "item_id": str(item_id)})
            .sort("timestamp", -1)
            .limit(limit)
        )

    # ============================================================
    # MONEY SUPPLY (base pra inflação)
    # ============================================================

    @classmethod
    def _get_baseline_money(cls, guild_id: int) -> int:
        cached = _velocity_cache.get(f"baseline_money:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        state = db["economy_state"].find_one(
            {"guild_id": guild_id}, {"baseline_money": 1}
        )
        baseline = int(state.get("baseline_money", 0)) if state else 0
        if baseline <= 0:
            # Fallback: usar total atual como baseline
            from commands_economy_core import EconomyManager
            baseline = max(1, EconomyManager.get_total_balance(guild_id))
        _velocity_cache.set(f"baseline_money:{guild_id}", baseline)
        return baseline

    @classmethod
    def set_baseline_money(cls, guild_id: int, value: int) -> None:
        db = get_connection()
        db["economy_state"].update_one(
            {"guild_id": guild_id},
            {"$set": {"baseline_money": int(value)}},
            upsert=True,
        )
        _velocity_cache.invalidate(f"baseline_money:{guild_id}")

    # ============================================================
    # CACHE
    # ============================================================

    @classmethod
    def clear_cache(cls) -> None:
        _price_cache.clear()
        _velocity_cache.clear()