# ============================================================
# REALESTATE_ENGINE.PY - v7.0 Fase 7 (Terrenos e Imóveis)
# ============================================================
# Responsável por:
#   • Regiões (por categoria do Discord)
#   • Terrenos escassos
#   • Construção de imóveis
#   • Venda de imóveis
# ============================================================

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id


DEFAULT_REALESTATE_CONFIG = {
    "enabled": True,

    # Regiões
    "auto_create_regions": True,       # cria região por categoria
    "default_land_count": 100,          # terrenos por região
    "base_price_multiplier": 1.0,

    # Imóveis
    "max_properties_per_user": 10,
    "max_lands_per_user": 20,

    # Mercado
    "resale_tax_percent": 5.0,          # imposto sobre venda de imóvel
    "property_decay_percent_per_month": 0.5,  # depreciação

    # Customização por região
    "region_multipliers": {},           # {"Centro": 2.0, "Periferia": 0.5}

    # Recurso consumido na construção
    "construction_materials": {
        "house": {"wood": 50, "iron": 20},
        "apartment": {"iron": 80, "copper": 40},
        "shop": {"wood": 100, "iron": 100},
        "factory": {"iron": 300, "copper": 200, "coal": 100},
        "mansion": {"wood": 500, "iron": 400, "gold_ore": 10},
    },
}


PROPERTY_TYPES = {
    "house": {
        "name": "Casa",
        "emoji": "🏠",
        "base_cost": 100_000,
        "base_rent": 5_000,
        "rental_yield": 0.05,        # 5% ao mês (mas aqui por tick)
    },
    "apartment": {
        "name": "Apartamento",
        "emoji": "🏢",
        "base_cost": 50_000,
        "base_rent": 3_000,
        "rental_yield": 0.06,
    },
    "shop": {
        "name": "Loja",
        "emoji": "🏪",
        "base_cost": 200_000,
        "base_rent": 12_000,
        "rental_yield": 0.06,
    },
    "factory": {
        "name": "Fábrica",
        "emoji": "🏭",
        "base_cost": 800_000,
        "base_rent": 60_000,
        "rental_yield": 0.075,
    },
    "mansion": {
        "name": "Mansão",
        "emoji": "🏰",
        "base_cost": 2_000_000,
        "base_rent": 100_000,
        "rental_yield": 0.05,
    },
}


_realestate_cache = TTLCache(max_size=300, ttl=60)


class RealEstateEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _realestate_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "realestate"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_REALESTATE_CONFIG, **(doc.get("config") or {})}
        _realestate_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "realestate"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _realestate_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # REGIÕES
    # ============================================================

    @classmethod
    def ensure_regions(cls, guild, bot_guild) -> int:
        """
        Cria regiões a partir das categorias do Discord.
        Chamado no tick, idempotente.
        """
        db = get_connection()
        config = cls.get_config(guild.id)
        if not config.get("auto_create_regions", True):
            return 0

        existing = set(
            r["category_id"] for r in db["realestate_regions"].find(
                {"guild_id": guild.id}, {"category_id": 1}
            )
        )

        from pymongo import UpdateOne
        ops = []
        now = datetime.utcnow()
        default_count = int(config.get("default_land_count", 100))
        multipliers = config.get("region_multipliers") or {}

        for cat in guild.categories:
            if cat.id in existing:
                continue

            mult = float(multipliers.get(cat.name, 1.0))

            ops.append(UpdateOne(
                {"guild_id": guild.id, "category_id": cat.id},
                {"$setOnInsert": {
                    "guild_id": guild.id,
                    "category_id": cat.id,
                    "name": cat.name,
                    "multiplier": mult,
                    "total_lands": default_count,
                    "available_lands": default_count,
                    "base_land_price": int(50_000 * mult),
                    "created_at": now,
                }},
                upsert=True,
            ))

        if ops:
            try:
                db["realestate_regions"].bulk_write(ops, ordered=False)
            except Exception:
                pass

        return len(ops)

    @classmethod
    def get_region(cls, guild_id: int, category_id: int) -> Optional[dict]:
        db = get_connection()
        return db["realestate_regions"].find_one({
            "guild_id": guild_id,
            "category_id": category_id,
        })

    @classmethod
    def list_regions(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["realestate_regions"].find({
            "guild_id": guild_id,
        }).sort("multiplier", -1))

    # ============================================================
    # COMPRA DE TERRENO
    # ============================================================

    @classmethod
    def buy_land(
        cls, guild_id: int, user_id: int, category_id: int
    ) -> dict:
        db = get_connection()
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        region = cls.get_region(guild_id, category_id)
        if not region:
            return {"error": "region_not_found"}

        if int(region.get("available_lands", 0)) <= 0:
            return {"error": "no_lands_available"}

        # Limite por user
        user_lands = db["realestate_lands"].count_documents({
            "guild_id": guild_id,
            "owner_id": user_id,
        })
        if user_lands >= int(config.get("max_lands_per_user", 20)):
            return {"error": "max_lands_reached"}

        # Preço base
        base_price = int(region.get("base_land_price", 50_000))

        # Escassez: quanto menos terrenos, mais caro
        total = int(region.get("total_lands", 100))
        available = int(region.get("available_lands", 0))
        scarcity = 1 + (1 - available / max(1, total)) * 0.5  # 1.0 a 1.5

        price = int(base_price * scarcity)

        # Verifica saldo
        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < price:
            return {"error": "insufficient_funds",
                    "needed": price, "have": balance}

        # Cobra
        if not EconomyManager.remove_balance(
            guild_id, user_id, price,
            f"Compra de terreno em {region['name']}",
            "land"
        ):
            return {"error": "payment_failed"}

        # Registra terreno
        result = db["realestate_lands"].insert_one({
            "guild_id": guild_id,
            "region_id": str(region["_id"]),
            "category_id": category_id,
            "owner_id": user_id,
            "price_paid": price,
            "has_property": False,
            "property_id": None,
            "purchased_at": datetime.utcnow(),
        })

        # Reduz disponível
        db["realestate_regions"].update_one(
            {"_id": region["_id"]},
            {"$inc": {"available_lands": -1}}
        )

        return {
            "ok": True,
            "land_id": str(result.inserted_id),
            "region": region["name"],
            "price": price,
        }

    # ============================================================
    # CONSTRUÇÃO
    # ============================================================

    @classmethod
    def build_property(
        cls, guild_id: int, user_id: int, land_id: str, property_type: str
    ) -> dict:
        db = get_connection()
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        property_type = property_type.lower()
        if property_type not in PROPERTY_TYPES:
            return {"error": "invalid_type",
                    "valid": list(PROPERTY_TYPES.keys())}

        oid = safe_object_id(land_id)
        if not oid:
            return {"error": "invalid_id"}

        land = db["realestate_lands"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "owner_id": user_id,
        })
        if not land:
            return {"error": "land_not_found"}

        if land.get("has_property"):
            return {"error": "land_already_has_property"}

        # Limite de imóveis por user
        user_props = db["realestate_properties"].count_documents({
            "guild_id": guild_id,
            "owner_id": user_id,
            "active": True,
        })
        if user_props >= int(config.get("max_properties_per_user", 10)):
            return {"error": "max_properties_reached"}

        prop_meta = PROPERTY_TYPES[property_type]
        region = db["realestate_regions"].find_one({"_id": safe_object_id(land["region_id"])})
        region_mult = float(region.get("multiplier", 1.0)) if region else 1.0

        # Custo
        base_cost = int(prop_meta["base_cost"] * region_mult)
        base_rent = int(prop_meta["base_rent"] * region_mult)

        # Verifica recursos necessários
        materials = (config.get("construction_materials") or {}).get(property_type, {})
        from market_engine import MarketEngine
        for symbol, qty in materials.items():
            have = MarketEngine.get_holding(guild_id, user_id, symbol)
            if have < qty:
                return {"error": "missing_materials",
                        "symbol": symbol, "needed": qty, "have": have}

        # Verifica dinheiro
        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < base_cost:
            return {"error": "insufficient_funds",
                    "needed": base_cost, "have": balance}

        # Cobra dinheiro
        if not EconomyManager.remove_balance(
            guild_id, user_id, base_cost,
            f"Construção de {prop_meta['name']}",
            "property_build"
        ):
            return {"error": "payment_failed"}

        # Consome materiais
        for symbol, qty in materials.items():
            MarketEngine._adjust_holding(guild_id, user_id, symbol, -qty)

        # Cria imóvel
        result = db["realestate_properties"].insert_one({
            "guild_id": guild_id,
            "land_id": str(land["_id"]),
            "region_id": land["region_id"],
            "category_id": land["category_id"],
            "owner_id": user_id,
            "type": property_type,
            "name": prop_meta["name"],
            "cost": base_cost,
            "base_rent": base_rent,
            "rental_yield": float(prop_meta["rental_yield"]),
            "current_rent": base_rent,
            "rented_to": None,
            "active": True,
            "built_at": datetime.utcnow(),
        })

        # Marca terreno
        db["realestate_lands"].update_one(
            {"_id": land["_id"]},
            {"$set": {
                "has_property": True,
                "property_id": str(result.inserted_id),
            }}
        )

        return {
            "ok": True,
            "property_id": str(result.inserted_id),
            "type": property_type,
            "cost": base_cost,
            "base_rent": base_rent,
        }

    # ============================================================
    # VENDA DE IMÓVEL
    # ============================================================

    @classmethod
    def sell_property(
        cls, guild_id: int, user_id: int, property_id: str
    ) -> dict:
        db = get_connection()
        oid = safe_object_id(property_id)
        if not oid:
            return {"error": "invalid_id"}

        prop = db["realestate_properties"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "owner_id": user_id,
            "active": True,
        })
        if not prop:
            return {"error": "not_found"}

        if prop.get("rented_to"):
            return {"error": "property_rented"}

        # Verifica financiamento ativo
        mortgage = db["realestate_mortgages"].find_one({
            "property_id": str(prop["_id"]),
            "status": "active",
        })
        if mortgage:
            return {"error": "active_mortgage"}

        config = cls.get_config(guild_id)
        tax_pct = float(config.get("resale_tax_percent", 5.0)) / 100.0

        # Valor de venda = 80% do custo (depreciação)
        sale_value = int(int(prop.get("cost", 0)) * 0.8)
        tax = int(sale_value * tax_pct)
        net = sale_value - tax

        # Credita vendedor
        from commands_economy_core import EconomyManager
        EconomyManager.add_balance(
            guild_id, user_id, net,
            f"Venda de {prop.get('name', '?')}",
            "property_sell"
        )

        # Destrói imóvel
        db["realestate_properties"].update_one(
            {"_id": prop["_id"]},
            {"$set": {
                "active": False,
                "sold_at": datetime.utcnow(),
                "sold_for": sale_value,
            }}
        )

        # Libera terreno
        land_oid = safe_object_id(prop.get("land_id", ""))
        if land_oid:
            db["realestate_lands"].update_one(
                {"_id": land_oid},
                {"$set": {"has_property": False, "property_id": None}}
            )

        # Destina imposto ao tesouro
        if tax > 0:
            try:
                from treasury_engine import TreasuryEngine
                TreasuryEngine.collect(
                    guild_id, tax,
                    f"Imposto de venda de imóvel ({prop.get('name', '?')})"
                )
            except Exception:
                pass

        return {
            "ok": True,
            "sale_value": sale_value,
            "tax": tax,
            "net": net,
        }

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_property(cls, guild_id: int, property_id: str) -> Optional[dict]:
        db = get_connection()
        oid = safe_object_id(property_id)
        if not oid:
            return None
        return db["realestate_properties"].find_one({
            "_id": oid,
            "guild_id": guild_id,
        })

    @classmethod
    def list_user_properties(cls, guild_id: int, user_id: int) -> List[dict]:
        db = get_connection()
        return list(db["realestate_properties"].find({
            "guild_id": guild_id,
            "owner_id": user_id,
            "active": True,
        }).sort("built_at", -1))

    @classmethod
    def list_user_lands(cls, guild_id: int, user_id: int) -> List[dict]:
        db = get_connection()
        return list(db["realestate_lands"].find({
            "guild_id": guild_id,
            "owner_id": user_id,
        }).sort("purchased_at", -1))

    @classmethod
    def get_property_types(cls) -> dict:
        return PROPERTY_TYPES

    @classmethod
    def clear_cache(cls) -> None:
        _realestate_cache.clear()


async def setup(bot):
    pass