# ============================================================
# COMMODITY_ENGINE.PY - v7.0 Fase 4 (Commodities)
# ============================================================
# Responsável por:
#   • Catálogo de commodities (ouro, petróleo, soja, etc)
#   • Preço spot formado por oferta/demanda
#   • Estoque físico por guild
#   • Integração com recursos da Fase 2
# ============================================================

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


DEFAULT_COMMODITIES = {
    "GOLD":  {"name": "Ouro",       "emoji": "🥇", "unit": "oz",    "base_price": 2000, "rarity": 3.0},
    "OIL":   {"name": "Petróleo",   "emoji": "🛢️", "unit": "bbl",   "base_price": 80,   "rarity": 2.0},
    "SOY":   {"name": "Soja",       "emoji": "🌱", "unit": "bushel","base_price": 15,   "rarity": 1.0},
    "COFFEE":{"name": "Café",       "emoji": "☕", "unit": "lb",    "base_price": 5,    "rarity": 0.8},
    "WHEAT": {"name": "Trigo",      "emoji": "🌾", "unit": "bushel","base_price": 8,    "rarity": 0.9},
    "SILVER":{"name": "Prata",      "emoji": "🥈", "unit": "oz",    "base_price": 25,   "rarity": 2.0},
    "COPPER":{"name": "Cobre",      "emoji": "🟠", "unit": "lb",    "base_price": 4,    "rarity": 1.5},
    "COTTON":{"name": "Algodão",    "emoji": "🧵", "unit": "lb",    "base_price": 0.8,  "rarity": 1.0},
    "SUGAR": {"name": "Açúcar",     "emoji": "🍬", "unit": "lb",    "base_price": 0.20, "rarity": 0.7},
    "COCOA": {"name": "Cacau",      "emoji": "🍫", "unit": "lb",    "base_price": 3,    "rarity": 0.9},
}


DEFAULT_COMMODITY_CONFIG = {
    "enabled": True,
    "volatility": 0.03,
    "regenerate_per_tick": 0.02,    # 2% do estoque
    "max_stock": 100_000,
    "min_stock_floor": 100,         # estoque nunca cai abaixo disso
    "auto_list_on_tick": True,
}


_commodity_cache = TTLCache(max_size=200, ttl=60)


class CommodityEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _commodity_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "commodities"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_COMMODITY_CONFIG, **(doc.get("config") or {})}
        _commodity_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "commodities"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _commodity_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # INICIALIZAÇÃO
    # ============================================================

    @classmethod
    def ensure_commodities(cls, guild_id: int) -> int:
        """Garante que todas as commodities padrão existem."""
        db = get_connection()
        existing = set(
            d["symbol"] for d in db["commodities"].find(
                {"guild_id": guild_id}, {"symbol": 1}
            )
        )

        from pymongo import UpdateOne
        ops = []
        for symbol, data in DEFAULT_COMMODITIES.items():
            if symbol in existing:
                continue
            ops.append(UpdateOne(
                {"guild_id": guild_id, "symbol": symbol},
                {"$setOnInsert": {
                    "guild_id": guild_id,
                    "symbol": symbol,
                    "name": data["name"],
                    "emoji": data["emoji"],
                    "unit": data["unit"],
                    "base_price": data["base_price"],
                    "price": data["base_price"],
                    "rarity": data["rarity"],
                    "stock": int(DEFAULT_COMMODITY_CONFIG["max_stock"] * 0.5),
                    "max_stock": DEFAULT_COMMODITY_CONFIG["max_stock"],
                    "created_at": datetime.utcnow(),
                }},
                upsert=True,
            ))

        if ops:
            try:
                db["commodities"].bulk_write(ops, ordered=False)
            except Exception:
                pass

        return len(ops)

    # ============================================================
    # PREÇOS
    # ============================================================

    @classmethod
    def update_prices(cls, guild_id: int) -> int:
        """Atualiza preços spot por oferta/demanda + volatilidade."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return 0

        db = get_connection()
        volatility = float(config.get("volatility", 0.03))
        floor = int(config.get("min_stock_floor", 100))
        max_stock = int(config.get("max_stock", 100_000))

        commodities = list(db["commodities"].find({"guild_id": guild_id}))

        from pymongo import UpdateOne
        ops = []

        for c in commodities:
            base = int(c.get("base_price", 1))
            current = int(c.get("price", base))
            stock = int(c.get("stock", 0))

            # Fator de escassez
            stock_ratio = max(0.0, min(1.0, stock / max_stock))
            scarcity_factor = (1 - stock_ratio) * 0.7 + 0.5  # 0.5 a 1.2

            # Volatilidade aleatória
            noise = random.uniform(-volatility, volatility)

            target = int(base * scarcity_factor * (1 + noise))
            target = max(int(base * 0.3), min(int(base * 4.0), target))

            # Ajuste suave
            delta = target - current
            max_delta = max(1, int(current * 0.10))
            if abs(delta) > max_delta:
                delta = max_delta if delta > 0 else -max_delta
            new_price = max(1, current + delta)

            if new_price != current:
                ops.append(UpdateOne(
                    {"_id": c["_id"]},
                    {"$set": {
                        "price": new_price,
                        "last_update": datetime.utcnow(),
                    }}
                ))
                try:
                    db["commodity_prices"].insert_one({
                        "guild_id": guild_id,
                        "symbol": c["symbol"],
                        "price": new_price,
                        "stock": stock,
                        "timestamp": datetime.utcnow(),
                    })
                except Exception:
                    pass

        if ops:
            try:
                db["commodities"].bulk_write(ops, ordered=False)
            except Exception:
                pass

        return len(ops)

    @classmethod
    def regenerate(cls, guild_id: int) -> int:
        """Regenera estoque de commodities."""
        config = cls.get_config(guild_id)
        pct = float(config.get("regenerate_per_tick", 0.02))
        max_stock = int(config.get("max_stock", 100_000))

        db = get_connection()
        commodities = list(db["commodities"].find({"guild_id": guild_id}))

        from pymongo import UpdateOne
        ops = []
        for c in commodities:
            stock = int(c.get("stock", 0))
            if stock >= max_stock:
                continue
            gain = max(1, int(max_stock * pct * float(c.get("rarity", 1.0))))
            new_stock = min(max_stock, stock + gain)
            if new_stock > stock:
                ops.append(UpdateOne(
                    {"_id": c["_id"]},
                    {"$set": {"stock": new_stock}}
                ))

        if ops:
            try:
                db["commodities"].bulk_write(ops, ordered=False)
            except Exception:
                pass

        return len(ops)

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def list_commodities(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["commodities"].find({"guild_id": guild_id}).sort("symbol", 1))

    @classmethod
    def get_commodity(cls, guild_id: int, symbol: str) -> Optional[dict]:
        db = get_connection()
        return db["commodities"].find_one({
            "guild_id": guild_id,
            "symbol": symbol.upper(),
        })

    @classmethod
    def get_price(cls, guild_id: int, symbol: str) -> int:
        c = cls.get_commodity(guild_id, symbol)
        return int(c.get("price", 0)) if c else 0

    @classmethod
    def adjust_stock(cls, guild_id: int, symbol: str, delta: int) -> None:
        db = get_connection()
        db["commodities"].update_one(
            {"guild_id": guild_id, "symbol": symbol.upper()},
            {"$inc": {"stock": delta}}
        )

    @classmethod
    def clear_cache(cls) -> None:
        _commodity_cache.clear()


async def setup(bot):
    pass