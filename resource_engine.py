# ============================================================
# RESOURCE_ENGINE.PY - v7.0 Fase 2 (Matérias-primas)
# ============================================================
# Responsável por:
#   • Definir recursos disponíveis (ferro, madeira, petróleo, etc)
#   • Simular extração por empresas extrativistas
#   • Controlar escassez (recursos finitos)
#   • Calcular preço de recursos (oferta/demanda)
# ============================================================

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


# ============================================================
# RECURSOS PADRÃO (admin pode adicionar/remover)
# ============================================================

DEFAULT_RESOURCES = {
    "iron": {
        "name": "Ferro",
        "emoji": "⛏️",
        "base_price": 50,
        "rarity": 1.0,          # multiplicador de dificuldade
        "extract_rate": 10,      # unidades por tick (base)
        "sector": "mining",
    },
    "wood": {
        "name": "Madeira",
        "emoji": "🪵",
        "base_price": 30,
        "rarity": 0.8,
        "extract_rate": 15,
        "sector": "lumber",
    },
    "oil": {
        "name": "Petróleo",
        "emoji": "🛢️",
        "base_price": 120,
        "rarity": 2.0,
        "extract_rate": 6,
        "sector": "oil",
    },
    "copper": {
        "name": "Cobre",
        "emoji": "🟠",
        "base_price": 70,
        "rarity": 1.3,
        "extract_rate": 9,
        "sector": "mining",
    },
    "cotton": {
        "name": "Algodão",
        "emoji": "🌾",
        "base_price": 25,
        "rarity": 0.7,
        "extract_rate": 20,
        "sector": "agriculture",
    },
    "coal": {
        "name": "Carvão",
        "emoji": "⚫",
        "base_price": 40,
        "rarity": 0.9,
        "extract_rate": 12,
        "sector": "mining",
    },
    "gold_ore": {
        "name": "Minério de Ouro",
        "emoji": "🟡",
        "base_price": 200,
        "rarity": 3.0,
        "extract_rate": 3,
        "sector": "mining",
    },
    "rubber": {
        "name": "Borracha",
        "emoji": "🟤",
        "base_price": 60,
        "rarity": 1.1,
        "extract_rate": 8,
        "sector": "agriculture",
    },
}


DEFAULT_RESOURCE_CONFIG = {
    "enabled": True,
    "global_scarcity": 1.0,        # 1.0 = normal, <1 = recursos mais raros
    "regenerate_interval_hours": 6, # a cada N horas, recursos regeneram
    "regenerate_percent": 10,       # % do estoque máximo regenerado
    "max_stock_per_resource": 10000,
    "price_volatility": 0.05,       # ±5% por tick
    "allow_player_extraction": True,
}


_resources_cache = TTLCache(max_size=100, ttl=120)


class ResourceEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _resources_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "resources"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_RESOURCE_CONFIG, **(doc.get("config") or {})}
        _resources_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "resources"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _resources_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # INICIALIZAÇÃO
    # ============================================================

    @classmethod
    def ensure_resources(cls, guild_id: int) -> None:
        """Garante que todos os recursos padrão existem na guild."""
        db = get_connection()
        existing = set(
            doc["symbol"] for doc in db["resources"].find(
                {"guild_id": guild_id}, {"symbol": 1}
            )
        )
        from pymongo import UpdateOne
        ops = []
        for symbol, data in DEFAULT_RESOURCES.items():
            if symbol in existing:
                continue
            ops.append(UpdateOne(
                {"guild_id": guild_id, "symbol": symbol},
                {"$setOnInsert": {
                    "guild_id": guild_id,
                    "symbol": symbol,
                    "name": data["name"],
                    "emoji": data["emoji"],
                    "base_price": data["base_price"],
                    "current_price": data["base_price"],
                    "rarity": data["rarity"],
                    "extract_rate": data["extract_rate"],
                    "sector": data["sector"],
                    "stock": int(DEFAULT_RESOURCE_CONFIG["max_stock_per_resource"] * 0.5),
                    "max_stock": DEFAULT_RESOURCE_CONFIG["max_stock_per_resource"],
                    "created_at": datetime.utcnow(),
                }},
                upsert=True,
            ))
        if ops:
            try:
                db["resources"].bulk_write(ops, ordered=False)
            except Exception:
                pass

    # ============================================================
    # EXTRAÇÃO
    # ============================================================

    @classmethod
    def extract(cls, guild_id: int, symbol: str, amount: int) -> int:
        """
        Extrai `amount` unidades de um recurso.
        Retorna quantidade efetivamente extraída (pode ser menor se estoque baixo).
        """
        db = get_connection()
        resource = db["resources"].find_one(
            {"guild_id": guild_id, "symbol": symbol}
        )
        if not resource:
            return 0

        available = int(resource.get("stock", 0))
        if available <= 0:
            return 0

        extracted = min(amount, available)

        db["resources"].update_one(
            {"_id": resource["_id"]},
            {
                "$inc": {"stock": -extracted},
                "$set": {"last_extracted_at": datetime.utcnow()},
            }
        )
        return extracted

    @classmethod
    def add_stock(cls, guild_id: int, symbol: str, amount: int) -> None:
        """Adiciona estoque (regeneração natural ou admin)."""
        db = get_connection()
        resource = db["resources"].find_one(
            {"guild_id": guild_id, "symbol": symbol}
        )
        if not resource:
            return
        max_stock = int(resource.get("max_stock", 10000))
        db["resources"].update_one(
            {"_id": resource["_id"]},
            [{"$set": {
                "stock": {"$min": [max_stock, {"$add": ["$stock", amount]}]}
            }}]
        )

    # ============================================================
    # PREÇO DE RECURSO
    # ============================================================

    @classmethod
    def update_resource_prices(cls, guild_id: int) -> int:
        """Atualiza preços de recursos baseado em escassez + volatilidade."""
        db = get_connection()
        config = cls.get_config(guild_id)
        volatility = float(config.get("price_volatility", 0.05))
        scarcity = float(config.get("global_scarcity", 1.0))

        resources = list(db["resources"].find({"guild_id": guild_id}))
        if not resources:
            return 0

        from pymongo import UpdateOne
        ops = []

        for res in resources:
            base = int(res.get("base_price", 1))
            current = int(res.get("current_price", base))
            stock = int(res.get("stock", 0))
            max_stock = max(1, int(res.get("max_stock", 10000)))

            # Fator de escassez: quanto menos estoque, mais caro
            stock_ratio = stock / max_stock
            scarcity_factor = (1 - stock_ratio) * 0.5 + 0.5  # 0.5 a 1.5

            # Aplica scarcity global
            scarcity_factor *= scarcity

            # Aplica volatilidade
            noise = random.uniform(-volatility, volatility)

            target = base * scarcity_factor * (1 + noise)
            target = max(int(base * 0.3), min(int(base * 5.0), int(target)))

            # Ajuste suave (não pula muito por tick)
            delta = target - current
            max_delta = max(1, int(current * 0.15))
            if abs(delta) > max_delta:
                delta = max_delta if delta > 0 else -max_delta
            new_price = current + delta
            new_price = max(1, new_price)

            if new_price != current:
                ops.append(UpdateOne(
                    {"_id": res["_id"]},
                    {"$set": {
                        "current_price": new_price,
                        "last_price_update": datetime.utcnow(),
                    }}
                ))
                # Histórico
                try:
                    db["resource_prices"].insert_one({
                        "guild_id": guild_id,
                        "symbol": res["symbol"],
                        "price": new_price,
                        "base_price": base,
                        "stock": stock,
                        "timestamp": datetime.utcnow(),
                    })
                except Exception:
                    pass

        if ops:
            try:
                db["resources"].bulk_write(ops, ordered=False)
            except Exception:
                pass

        return len(ops)

    # ============================================================
    # REGENERAÇÃO
    # ============================================================

    @classmethod
    def regenerate_all(cls, guild_id: int) -> int:
        """Regenera recursos naturalmente (chamado pelo tick)."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return 0

        pct = float(config.get("regenerate_percent", 10)) / 100.0
        db = get_connection()
        resources = list(db["resources"].find({"guild_id": guild_id}))
        count = 0

        from pymongo import UpdateOne
        ops = []
        for res in resources:
            max_stock = int(res.get("max_stock", 10000))
            stock = int(res.get("stock", 0))
            if stock >= max_stock:
                continue
            gain = max(1, int(max_stock * pct * float(res.get("rarity", 1.0))))
            new_stock = min(max_stock, stock + gain)
            if new_stock > stock:
                ops.append(UpdateOne(
                    {"_id": res["_id"]},
                    {"$set": {"stock": new_stock}}
                ))
                count += 1

        if ops:
            try:
                db["resources"].bulk_write(ops, ordered=False)
            except Exception:
                pass

        return count

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_resource(cls, guild_id: int, symbol: str) -> Optional[dict]:
        db = get_connection()
        return db["resources"].find_one(
            {"guild_id": guild_id, "symbol": symbol}
        )

    @classmethod
    def list_resources(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["resources"].find({"guild_id": guild_id}).sort("symbol", 1))

    @classmethod
    def get_price(cls, guild_id: int, symbol: str) -> int:
        res = cls.get_resource(guild_id, symbol)
        return int(res.get("current_price", 0)) if res else 0

    @classmethod
    def clear_cache(cls) -> None:
        _resources_cache.clear()


async def setup(bot):
    # Módulo utilitário — não é Cog
    pass