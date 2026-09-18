# ============================================================
# COMPANY_ENGINE.PY - v7.0 Fase 2 (Empresas)
# ============================================================
# Responsável por:
#   • Criar/gerenciar empresas
#   • Produção por tick
#   • Compra/venda de produtos
#   • Dividendos e ações
#   • Integração com recursos, empregos e preço endógeno
# ============================================================

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id
from resource_engine import ResourceEngine
from job_engine import JobEngine


# ============================================================
# SETORES (tudo customizável)
# ============================================================

DEFAULT_SECTORS = {
    "mining": {
        "name": "Mineração",
        "emoji": "⛏️",
        "extracts": ["iron", "copper", "coal", "gold_ore"],
        "produces": None,
        "cost_per_tick": 50,
        "base_production": 20,
    },
    "lumber": {
        "name": "Madeireira",
        "emoji": "🪵",
        "extracts": ["wood", "rubber"],
        "produces": None,
        "cost_per_tick": 30,
        "base_production": 25,
    },
    "oil": {
        "name": "Petrolífera",
        "emoji": "🛢️",
        "extracts": ["oil"],
        "produces": None,
        "cost_per_tick": 100,
        "base_production": 10,
    },
    "agriculture": {
        "name": "Agricultura",
        "emoji": "🌾",
        "extracts": ["cotton", "rubber"],
        "produces": None,
        "cost_per_tick": 25,
        "base_production": 30,
    },
    "manufacturing": {
        "name": "Manufatura",
        "emoji": "🏭",
        "extracts": [],
        "produces": "goods",
        "cost_per_tick": 80,
        "base_production": 15,
        "requires": {"iron": 5, "wood": 3},
    },
    "technology": {
        "name": "Tecnologia",
        "emoji": "💻",
        "extracts": [],
        "produces": "tech",
        "cost_per_tick": 150,
        "base_production": 8,
        "requires": {"copper": 10, "gold_ore": 1},
    },
    "retail": {
        "name": "Varejo",
        "emoji": "🏪",
        "extracts": [],
        "produces": "retail",
        "cost_per_tick": 40,
        "base_production": 20,
        "requires": {"goods": 5},
    },
}


DEFAULT_COMPANY_CONFIG = {
    "enabled": True,
    "max_companies_per_user": 3,
    "max_companies_per_guild": 100,
    "creation_cost": 10000,
    "min_capital": 5000,
    "base_operating_cost": 50,
    "auto_produce_on_tick": True,
    "auto_pay_operating_cost": True,
    "allow_shares": True,
    "allow_dividends": True,
    "dividend_interval_hours": 24,
    "bankruptcy_threshold": -10000,   # se caixa < isso, empresa fale
    "max_cash": 100_000_000,
}


_company_cache = TTLCache(max_size=300, ttl=45)


class CompanyEngine:

    # ============================================================
    # CONFIG
    # ============================================================

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _company_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "companies"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_COMPANY_CONFIG, **(doc.get("config") or {})}
        _company_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "companies"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _company_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # CRIAÇÃO
    # ============================================================

    @classmethod
    def create_company(
        cls,
        guild_id: int,
        owner_id: int,
        name: str,
        sector: str,
        initial_capital: int,
    ) -> Optional[dict]:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return None

        sector = sector.lower()
        if sector not in DEFAULT_SECTORS:
            return None

        name = name.strip()[:50]
        if not name:
            return None

        cost = int(config.get("creation_cost", 10000))
        min_cap = int(config.get("min_capital", 5000))

        if initial_capital < min_cap:
            return None

        db = get_connection()

        # Limites
        user_companies = db["companies"].count_documents({
            "guild_id": guild_id,
            "owner_id": owner_id,
            "active": True,
        })
        if user_companies >= int(config.get("max_companies_per_user", 3)):
            return None

        guild_companies = db["companies"].count_documents({
            "guild_id": guild_id,
            "active": True,
        })
        if guild_companies >= int(config.get("max_companies_per_guild", 100)):
            return None

        # Cobra do owner (custo + capital)
        from commands_economy_core import EconomyManager
        total_cost = cost + initial_capital
        balance = EconomyManager.get_balance(guild_id, owner_id)
        if balance < total_cost:
            return None

        if not EconomyManager.remove_balance(
            guild_id, owner_id, total_cost,
            f"Criação de empresa: {name}", "company_create"
        ):
            return None

        doc = {
            "guild_id": guild_id,
            "owner_id": owner_id,
            "name": name,
            "sector": sector,
            "cash": int(initial_capital),
            "inventory": {},          # {"symbol": qty}
            "employees_count": 0,
            "active": True,
            "shares_total": 100,       # 100 ações iniciais
            "shares_issued": 100,
            "share_price": max(1, int(initial_capital / 100)),
            "created_at": datetime.utcnow(),
            "total_produced": 0,
            "total_revenue": 0,
            "total_costs": total_cost,
            "last_production": None,
            "last_dividend": None,
        }
        result = db["companies"].insert_one(doc)
        company_id = result.inserted_id

        # Owner possui todas as ações
        db["company_shares"].insert_one({
            "guild_id": guild_id,
            "company_id": str(company_id),
            "holder_id": owner_id,
            "quantity": 100,
            "acquired_at": datetime.utcnow(),
        })

        return db["companies"].find_one({"_id": company_id})

    # ============================================================
    # PRODUÇÃO
    # ============================================================

    @classmethod
    def produce(cls, guild_id: int, company_id: str) -> dict:
        """
        Executa 1 ciclo de produção da empresa.
        Retorna stats.
        """
        db = get_connection()
        oid = safe_object_id(company_id)
        if not oid:
            return {"error": "invalid_id"}

        company = db["companies"].find_one({"_id": oid, "guild_id": guild_id})
        if not company or not company.get("active", True):
            return {"error": "not_found"}

        sector_key = company.get("sector", "")
        sector = DEFAULT_SECTORS.get(sector_key)
        if not sector:
            return {"error": "invalid_sector"}

        config = cls.get_config(guild_id)

        # Funcionários ativos
        employees = db["job_contracts"].count_documents({
            "guild_id": guild_id,
            "company_id": str(company["_id"]),
            "active": True,
        })

        # Produção base = base × (1 + employees × 0.2)
        # Sem funcionários, produz em capacidade reduzida
        labor_mult = 0.5 + (employees * 0.2)
        base_prod = int(sector.get("base_production", 10) * labor_mult)

        # Verifica requisitos (para setores de transformação)
        requires = sector.get("requires") or {}
        inventory = dict(company.get("inventory") or {})
        missing = []
        for symbol, qty in requires.items():
            have = int(inventory.get(symbol, 0))
            if have < qty:
                missing.append(symbol)

        if missing:
            return {"error": "missing_resources", "missing": missing}

        # Consome recursos necessários
        for symbol, qty in requires.items():
            inventory[symbol] = int(inventory.get(symbol, 0)) - qty

        # Custo operacional
        op_cost = int(sector.get("cost_per_tick", config.get("base_operating_cost", 50)))
        cash = int(company.get("cash", 0))

        if config.get("auto_pay_operating_cost", True) and cash < op_cost:
            return {"error": "insufficient_cash", "needed": op_cost, "have": cash}

        # Produção
        produced = base_prod
        produces = sector.get("produces")

        if produces:
            # Setores de transformação: produzem "goods", "tech", "retail"
            inventory[produces] = int(inventory.get(produces, 0)) + produced
        else:
            # Setores extrativistas: extraem recursos do pool global
            extracts = sector.get("extracts", [])
            if not extracts:
                return {"error": "no_extract_defined"}

            per_resource = max(1, produced // max(1, len(extracts)))
            extracted_total = 0
            for symbol in extracts:
                amount = ResourceEngine.extract(guild_id, symbol, per_resource)
                if amount > 0:
                    inventory[symbol] = int(inventory.get(symbol, 0)) + amount
                    extracted_total += amount
            produced = extracted_total

        # Debita custo
        new_cash = cash - op_cost

        # Atualiza empresa
        db["companies"].update_one(
            {"_id": company["_id"]},
            {
                "$set": {
                    "inventory": inventory,
                    "cash": new_cash,
                    "last_production": datetime.utcnow(),
                },
                "$inc": {
                    "total_produced": produced,
                    "total_costs": op_cost,
                }
            }
        )

        # Registra
        db["company_production"].insert_one({
            "guild_id": guild_id,
            "company_id": str(company["_id"]),
            "produced": produced,
            "produces": produces or ",".join(sector.get("extracts", [])),
            "operating_cost": op_cost,
            "employees": employees,
            "timestamp": datetime.utcnow(),
        })

        return {
            "produced": produced,
            "operating_cost": op_cost,
            "produces": produces or sector.get("extracts", []),
            "employees": employees,
            "cash_after": new_cash,
        }

    # ============================================================
    # VENDA DE PRODUTOS
    # ============================================================

    @classmethod
    def sell_inventory(
        cls, guild_id: int, company_id: str, symbol: str, quantity: int
    ) -> dict:
        """Vende produto do inventário da empresa pelo preço de mercado."""
        db = get_connection()
        oid = safe_object_id(company_id)
        if not oid:
            return {"error": "invalid_id"}

        company = db["companies"].find_one({"_id": oid, "guild_id": guild_id})
        if not company:
            return {"error": "not_found"}

        inventory = dict(company.get("inventory") or {})
        available = int(inventory.get(symbol, 0))
        if available < quantity or quantity <= 0:
            return {"error": "insufficient_stock", "have": available}

        # Preço: se for recurso, usa preço de recurso; senão, preço base do produto
        price_per_unit = cls._get_sell_price(guild_id, symbol)
        if price_per_unit <= 0:
            return {"error": "no_price"}

        revenue = price_per_unit * quantity

        # Atualiza empresa
        inventory[symbol] = available - quantity
        db["companies"].update_one(
            {"_id": company["_id"]},
            {
                "$set": {"inventory": inventory},
                "$inc": {
                    "cash": revenue,
                    "total_revenue": revenue,
                }
            }
        )

        return {
            "sold": quantity,
            "symbol": symbol,
            "price_per_unit": price_per_unit,
            "revenue": revenue,
            "cash_after": int(company.get("cash", 0)) + revenue,
        }

    @classmethod
    def _get_sell_price(cls, guild_id: int, symbol: str) -> int:
        """Preço de venda de um produto/recurso."""
        # Tenta recurso primeiro
        res = ResourceEngine.get_resource(guild_id, symbol)
        if res:
            return int(res.get("current_price", 0))
        # Fallback: preço base de produto manufaturado
        product_prices = {
            "goods": 100,
            "tech": 500,
            "retail": 50,
        }
        return product_prices.get(symbol, 0)

    # ============================================================
    # DIVIDENDOS
    # ============================================================

    @classmethod
    def pay_dividends(cls, guild_id: int, company_id: str) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("allow_dividends", True):
            return {"error": "disabled"}

        db = get_connection()
        oid = safe_object_id(company_id)
        if not oid:
            return {"error": "invalid_id"}

        company = db["companies"].find_one({"_id": oid, "guild_id": guild_id})
        if not company:
            return {"error": "not_found"}

        cash = int(company.get("cash", 0))
        # Reserva de segurança: 30% do caixa
        reserve = int(cash * 0.3)
        distributable = cash - reserve
        if distributable <= 0:
            return {"error": "no_profit", "cash": cash}

        shares = list(db["company_shares"].find({
            "guild_id": guild_id,
            "company_id": str(company["_id"]),
        }))
        total_shares = sum(int(s.get("quantity", 0)) for s in shares)
        if total_shares <= 0:
            return {"error": "no_shares"}

        # Distribui proporcional
        from commands_economy_core import EconomyManager
        paid_out = 0
        distributions = []

        for share in shares:
            holder = share["holder_id"]
            qty = int(share.get("quantity", 0))
            if qty <= 0:
                continue
            amount = int(distributable * (qty / total_shares))
            if amount <= 0:
                continue
            EconomyManager.add_balance(
                guild_id, holder, amount,
                f"Dividendo: {company.get('name', '?')}",
                "dividend"
            )
            paid_out += amount
            distributions.append({"holder": holder, "amount": amount})

        # Debita do caixa
        db["companies"].update_one(
            {"_id": company["_id"]},
            {
                "$inc": {"cash": -paid_out},
                "$set": {"last_dividend": datetime.utcnow()},
            }
        )

        db["company_financials"].insert_one({
            "guild_id": guild_id,
            "company_id": str(company["_id"]),
            "type": "dividends_paid",
            "amount": paid_out,
            "distributions": distributions,
            "timestamp": datetime.utcnow(),
        })

        return {
            "total_paid": paid_out,
            "holders": len(distributions),
            "distributions": distributions,
        }

    # ============================================================
    # TICK
    # ============================================================

    @classmethod
    def process_all_companies(cls, guild_id: int) -> dict:
        """
        Roda produção para todas as empresas ativas.
        Chamado pelo tick.
        """
        config = cls.get_config(guild_id)
        if not config.get("enabled", True) or not config.get("auto_produce_on_tick", True):
            return {"processed": 0, "errors": 0}

        db = get_connection()
        companies = list(db["companies"].find({
            "guild_id": guild_id,
            "active": True,
        }))

        processed = 0
        errors = 0
        total_produced = 0

        for company in companies:
            try:
                result = cls.produce(guild_id, str(company["_id"]))
                if "error" not in result:
                    processed += 1
                    total_produced += int(result.get("produced", 0))
                else:
                    errors += 1
            except Exception:
                errors += 1

        return {
            "processed": processed,
            "errors": errors,
            "total_produced": total_produced,
        }

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_company(cls, guild_id: int, company_id: str) -> Optional[dict]:
        db = get_connection()
        oid = safe_object_id(company_id)
        if not oid:
            return None
        return db["companies"].find_one({"_id": oid, "guild_id": guild_id})

    @classmethod
    def list_user_companies(cls, guild_id: int, owner_id: int) -> List[dict]:
        db = get_connection()
        return list(db["companies"].find({
            "guild_id": guild_id,
            "owner_id": owner_id,
            "active": True,
        }).sort("created_at", -1))

    @classmethod
    def list_guild_companies(cls, guild_id: int, limit: int = 20) -> List[dict]:
        db = get_connection()
        return list(db["companies"].find({
            "guild_id": guild_id,
            "active": True,
        }).sort("total_revenue", -1).limit(limit))

    @classmethod
    def clear_cache(cls) -> None:
        _company_cache.clear()