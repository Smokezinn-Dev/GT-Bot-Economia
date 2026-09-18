# ============================================================
# POLICY_ENGINE.PY - v7.0 Fase 5 (Políticas Econômicas)
# ============================================================
# Responsável por:
#   • Propor políticas (ministros)
#   • Aprovar/rejeitar (presidente)
#   • Aplicar efeitos (via engines)
#   • Expirar políticas temporárias
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id


DEFAULT_POLICY_CONFIG = {
    "enabled": True,
    "max_active_policies": 5,
    "policy_duration_hours": 24,      # duração padrão
    "max_stimulus_per_policy": 100_000,
    "cooldown_hours": 6,              # entre políticas iguais
    "require_treasury_funds": True,   # precisa de fundos no tesouro
}


_policy_cache = TTLCache(max_size=200, ttl=45)


# Catálogo de políticas disponíveis
POLICY_TYPES = {
    "tax_cut": {
        "name": "Corte de Impostos",
        "description": "Reduz alíquota de imposto",
        "emoji": "📉",
        "requires_funds": False,
        "duration": 24,
    },
    "tax_hike": {
        "name": "Aumento de Impostos",
        "description": "Aumenta alíquota pra arrecadar mais",
        "emoji": "📈",
        "requires_funds": False,
        "duration": 24,
    },
    "stimulus": {
        "name": "Estímulo Fiscal",
        "description": "Injeta dinheiro do tesouro na economia",
        "emoji": "💸",
        "requires_funds": True,
        "duration": 1,
    },
    "austerity": {
        "name": "Austeridade",
        "description": "Corta gastos e recolhe moeda",
        "emoji": "✂️",
        "requires_funds": False,
        "duration": 24,
    },
    "subsidy": {
        "name": "Subsídio Setorial",
        "description": "Subsidia um setor econômico",
        "emoji": "🎁",
        "requires_funds": True,
        "duration": 24,
    },
    "public_works": {
        "name": "Obras Públicas",
        "description": "Gasta no tesouro pra gerar empregos",
        "emoji": "🏗️",
        "requires_funds": True,
        "duration": 1,
    },
}


class PolicyEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _policy_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "policies"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_POLICY_CONFIG, **(doc.get("config") or {})}
        _policy_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "policies"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _policy_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # PROPOR / APROVAR
    # ============================================================

    @classmethod
    def propose(
        cls,
        guild_id: int,
        proposer_id: int,
        policy_type: str,
        params: dict,
    ) -> dict:
        """Ministro propõe uma política."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        if policy_type not in POLICY_TYPES:
            return {"error": "invalid_type",
                    "valid": list(POLICY_TYPES.keys())}

        # Verifica que é ministro
        from political_engine import PoliticalEngine
        if not PoliticalEngine.is_minister(guild_id, proposer_id):
            return {"error": "not_minister"}

        db = get_connection()

        # Limite de políticas ativas
        active_count = db["policies"].count_documents({
            "guild_id": guild_id,
            "status": "active",
        })
        if active_count >= int(config.get("max_active_policies", 5)):
            return {"error": "max_policies"}

        # Cooldown
        cutoff = datetime.utcnow() - timedelta(hours=int(config.get("cooldown_hours", 6)))
        recent = db["policies"].find_one({
            "guild_id": guild_id,
            "type": policy_type,
            "created_at": {"$gte": cutoff},
            "status": {"$in": ["proposed", "approved", "active"]},
        })
        if recent:
            return {"error": "cooldown"}

        # Custo (se aplicável)
        cost = int(params.get("cost", 0))
        policy_meta = POLICY_TYPES[policy_type]
        if policy_meta["requires_funds"]:
            from treasury_engine import TreasuryEngine
            if not TreasuryEngine.can_spend(guild_id, cost):
                return {"error": "insufficient_treasury",
                        "cost": cost,
                        "have": TreasuryEngine.get_balance(guild_id)}

        duration = int(params.get("duration",
                                  policy_meta.get("duration",
                                                  config.get("policy_duration_hours", 24))))

        doc = {
            "guild_id": guild_id,
            "type": policy_type,
            "params": params,
            "proposer_id": proposer_id,
            "status": "proposed",
            "duration_hours": duration,
            "cost": cost,
            "created_at": datetime.utcnow(),
            "approved_by": None,
            "approved_at": None,
            "expires_at": None,
        }
        result = db["policies"].insert_one(doc)
        return {"ok": True, "policy_id": str(result.inserted_id)}

    @classmethod
    def approve(cls, guild_id: int, president_id: int, policy_id: str) -> dict:
        """Presidente aprova uma política proposta."""
        from political_engine import PoliticalEngine
        if not PoliticalEngine.is_president(guild_id, president_id):
            return {"error": "not_president"}

        db = get_connection()
        oid = safe_object_id(policy_id)
        if not oid:
            return {"error": "invalid_id"}

        policy = db["policies"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "status": "proposed",
        })
        if not policy:
            return {"error": "not_found"}

        # Aplica efeitos
        effects = cls._apply_effects(guild_id, policy)

        now = datetime.utcnow()
        expires_at = now + timedelta(hours=int(policy.get("duration_hours", 24)))

        db["policies"].update_one(
            {"_id": policy["_id"]},
            {"$set": {
                "status": "active",
                "approved_by": president_id,
                "approved_at": now,
                "expires_at": expires_at,
                "effects_applied": effects,
            }}
        )

        return {
            "ok": True,
            "policy_id": policy_id,
            "type": policy["type"],
            "expires_at": expires_at,
            "effects": effects,
        }

    @classmethod
    def reject(cls, guild_id: int, president_id: int, policy_id: str) -> dict:
        from political_engine import PoliticalEngine
        if not PoliticalEngine.is_president(guild_id, president_id):
            return {"error": "not_president"}

        db = get_connection()
        oid = safe_object_id(policy_id)
        if not oid:
            return {"error": "invalid_id"}

        result = db["policies"].update_one(
            {"_id": oid, "guild_id": guild_id, "status": "proposed"},
            {"$set": {
                "status": "rejected",
                "rejected_by": president_id,
                "rejected_at": datetime.utcnow(),
            }}
        )

        if result.modified_count == 0:
            return {"error": "not_found"}

        return {"ok": True}

    # ============================================================
    # EFEITOS
    # ============================================================

    @classmethod
    def _apply_effects(cls, guild_id: int, policy: dict) -> dict:
        """Aplica os efeitos da política aprovada."""
        ptype = policy["type"]
        params = policy.get("params") or {}
        effects = {}

        try:
            if ptype == "tax_cut":
                from tax_engine import TaxEngine
                current = TaxEngine.get_rate(guild_id, params.get("tax_type", "income"))
                new_rate = max(0.0, current - float(params.get("amount", 0.02)))
                TaxEngine.set_rate(guild_id, params.get("tax_type", "income"), new_rate)
                effects = {"tax_type": params.get("tax_type", "income"),
                           "from": current, "to": new_rate}

            elif ptype == "tax_hike":
                from tax_engine import TaxEngine
                current = TaxEngine.get_rate(guild_id, params.get("tax_type", "income"))
                new_rate = min(0.5, current + float(params.get("amount", 0.02)))
                TaxEngine.set_rate(guild_id, params.get("tax_type", "income"), new_rate)
                effects = {"tax_type": params.get("tax_type", "income"),
                           "from": current, "to": new_rate}

            elif ptype == "stimulus":
                from treasury_engine import TreasuryEngine
                from commands_economy_core import EconomyManager
                amount = int(params.get("amount", 0))
                # Distribui igualmente por todos os membros com saldo > 0
                db = get_connection()
                docs = list(db["economy_balances"].find({
                    "guild_id": guild_id, "balance": {"$gt": 0}
                }))
                if docs:
                    per_user = amount // len(docs)
                    for d in docs:
                        if per_user > 0:
                            EconomyManager.add_balance(
                                guild_id, d["user_id"], per_user,
                                "Estímulo fiscal", "stimulus"
                            )
                    TreasuryEngine.spend(guild_id, amount, "Estímulo fiscal")
                    effects = {"distributed": amount, "beneficiaries": len(docs)}

            elif ptype == "austerity":
                from treasury_engine import TreasuryEngine
                # Aumenta impostos temporariamente
                from tax_engine import TaxEngine
                current = TaxEngine.get_rate(guild_id, "income")
                new_rate = min(0.5, current + 0.05)
                TaxEngine.set_rate(guild_id, "income", new_rate)
                effects = {"income_from": current, "income_to": new_rate}

            elif ptype == "subsidy":
                from treasury_engine import TreasuryEngine
                from commands_economy_core import EconomyManager
                sector = params.get("sector", "mining")
                amount = int(params.get("amount", 0))
                # Distribui pra donos de empresas do setor
                db = get_connection()
                companies = list(db["companies"].find({
                    "guild_id": guild_id,
                    "sector": sector,
                    "active": True,
                }))
                if companies:
                    per_company = amount // len(companies)
                    for c in companies:
                        db["companies"].update_one(
                            {"_id": c["_id"]},
                            {"$inc": {"cash": per_company}}
                        )
                    TreasuryEngine.spend(guild_id, amount, f"Subsídio {sector}")
                    effects = {"sector": sector, "amount": amount, "companies": len(companies)}

            elif ptype == "public_works":
                from treasury_engine import TreasuryEngine
                from commands_economy_core import EconomyManager
                amount = int(params.get("amount", 0))
                # Cria empregos temporários / paga obras
                # Simplificação: distribui pra desempregados
                db = get_connection()
                # Pega membros sem contrato ativo
                contracts = set()
                for c in db["job_contracts"].find({
                    "guild_id": guild_id, "active": True
                }, {"user_id": 1}):
                    contracts.add(c["user_id"])
                docs = list(db["economy_balances"].find({
                    "guild_id": guild_id, "balance": {"$gt": 0}
                }))
                unemployed = [d for d in docs if d["user_id"] not in contracts]
                if unemployed:
                    per_user = amount // len(unemployed)
                    for d in unemployed:
                        if per_user > 0:
                            EconomyManager.add_balance(
                                guild_id, d["user_id"], per_user,
                                "Obras públicas", "public_works"
                            )
                    TreasuryEngine.spend(guild_id, amount, "Obras públicas")
                    effects = {"distributed": amount, "beneficiaries": len(unemployed)}

        except Exception as e:
            effects = {"error": str(e)}

        return effects

    @classmethod
    def expire_policies(cls, guild_id: int) -> int:
        """Expira políticas vencidas. Chamado pelo tick."""
        db = get_connection()
        now = datetime.utcnow()
        result = db["policies"].update_many(
            {
                "guild_id": guild_id,
                "status": "active",
                "expires_at": {"$lte": now},
            },
            {"$set": {"status": "expired", "expired_at": now}}
        )
        return result.modified_count

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def list_active(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["policies"].find({
            "guild_id": guild_id,
            "status": "active",
        }).sort("created_at", -1))

    @classmethod
    def list_proposed(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["policies"].find({
            "guild_id": guild_id,
            "status": "proposed",
        }).sort("created_at", -1))

    @classmethod
    def get_policy_types(cls) -> dict:
        return POLICY_TYPES

    @classmethod
    def clear_cache(cls) -> None:
        _policy_cache.clear()


async def setup(bot):
    pass