# ============================================================
# POLITICAL_ENGINE.PY - v7.0 Fase 5 (Governo e Eleições)
# ============================================================
# Responsável por:
#   • Eleições periódicas por reaction
#   • Presidente em exercício
#   • Nomeação de ministros
#   • Mandatos com prazo
#   • Registro histórico de governos
# ============================================================

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id


DEFAULT_POLITICAL_CONFIG = {
    "enabled": True,

    # Eleições
    "election_interval_days": 7,      # a cada 7 dias há nova eleição
    "campaign_hours": 24,             # tempo de candidatura
    "voting_hours": 24,               # tempo de votação
    "min_votes_to_win": 3,
    "allow_reelection": True,
    "max_consecutive_terms": 2,
    "candidate_min_balance": 1000,    # saldo mínimo pra se candidatar
    "campaign_cost": 500,             # custo de campanha

    # Mandato
    "term_days": 7,
    "daily_salary": 500,              # salário do presidente por dia
    "minister_salary": 200,           # salário de ministro por dia

    # Poderes
    "can_override_selic": True,       # presidente pode mexer na Selic
    "can_change_taxes": True,         # pode mexer em impostos
    "can_issue_stimulus": True,       # pode fazer estímulo fiscal
    "can_appoint_ministers": True,
    "max_stimulus_per_term": 500_000, # teto de estímulo

    # Punição
    "impeachment_votes": 5,           # votos mínimos pra impeachment
    "impeachment_enabled": True,
}


_political_cache = TTLCache(max_size=200, ttl=90)


class PoliticalEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _political_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "government"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_POLITICAL_CONFIG, **(doc.get("config") or {})}
        _political_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "government"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _political_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # PRESIDENTE ATUAL
    # ============================================================

    @classmethod
    def get_current_president(cls, guild_id: int) -> Optional[dict]:
        db = get_connection()
        return db["government_officials"].find_one({
            "guild_id": guild_id,
            "role": "president",
            "active": True,
        })

    @classmethod
    def get_ministers(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["government_officials"].find({
            "guild_id": guild_id,
            "role": {"$ne": "president"},
            "active": True,
        }))

    @classmethod
    def is_president(cls, guild_id: int, user_id: int) -> bool:
        p = cls.get_current_president(guild_id)
        return bool(p and p["user_id"] == user_id)

    @classmethod
    def is_minister(cls, guild_id: int, user_id: int) -> bool:
        db = get_connection()
        return db["government_officials"].find_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "role": {"$ne": "president"},
            "active": True,
        }) is not None

    # ============================================================
    # ELEIÇÕES
    # ============================================================

    @classmethod
    def start_election(cls, guild_id: int, channel_id: int) -> Optional[dict]:
        """Inicia nova eleição."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return None

        db = get_connection()

        # Já tem eleição ativa?
        active = db["elections"].find_one({
            "guild_id": guild_id,
            "status": {"$in": ["campaign", "voting"]},
        })
        if active:
            return active

        now = datetime.utcnow()
        campaign_end = now + timedelta(hours=int(config.get("campaign_hours", 24)))
        voting_end = campaign_end + timedelta(hours=int(config.get("voting_hours", 24)))

        doc = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "candidates": [],
            "votes": {},               # {user_id: candidate_id}
            "status": "campaign",      # campaign | voting | finished
            "started_at": now,
            "campaign_end": campaign_end,
            "voting_end": voting_end,
            "winner_id": None,
        }
        result = db["elections"].insert_one(doc)
        return db["elections"].find_one({"_id": result.inserted_id})

    @classmethod
    def apply_candidacy(cls, guild_id: int, user_id: int) -> dict:
        config = cls.get_config(guild_id)
        db = get_connection()
        now = datetime.utcnow()

        election = db["elections"].find_one({
            "guild_id": guild_id,
            "status": "campaign",
        })
        if not election:
            return {"error": "no_active_election"}

        if now > election["campaign_end"]:
            return {"error": "campaign_ended"}

        # Já é candidato?
        if any(c["user_id"] == user_id for c in election.get("candidates", [])):
            return {"error": "already_candidate"}

        # Reeleição?
        if not config.get("allow_reelection", True):
            current = cls.get_current_president(guild_id)
            if current and current["user_id"] == user_id:
                return {"error": "reelection_disabled"}

        # Verifica saldo mínimo
        from commands_economy_core import EconomyManager
        cost = int(config.get("campaign_cost", 500))
        min_bal = int(config.get("candidate_min_balance", 1000))
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < min_bal + cost:
            return {"error": "insufficient_funds",
                    "needed": min_bal + cost, "have": balance}

        # Cobra campanha
        EconomyManager.remove_balance(
            guild_id, user_id, cost,
            "Custo de campanha eleitoral",
            "campaign"
        )

        db["elections"].update_one(
            {"_id": election["_id"]},
            {"$push": {"candidates": {
                "user_id": user_id,
                "registered_at": now,
            }}}
        )

        return {
            "ok": True,
            "cost": cost,
            "campaign_ends": election["campaign_end"],
        }

    @classmethod
    def cast_vote(cls, guild_id: int, voter_id: int, candidate_id: int) -> dict:
        db = get_connection()
        now = datetime.utcnow()

        election = db["elections"].find_one({
            "guild_id": guild_id,
            "status": {"$in": ["campaign", "voting"]},
        })
        if not election:
            return {"error": "no_active_election"}

        # Se ainda está em campanha, passa automaticamente pra votação
        if election["status"] == "campaign" and now >= election["campaign_end"]:
            db["elections"].update_one(
                {"_id": election["_id"]},
                {"$set": {"status": "voting"}}
            )
            election["status"] = "voting"

        if election["status"] == "campaign":
            return {"error": "campaign_not_ended"}

        if now > election["voting_end"]:
            return {"error": "voting_ended"}

        # Candidato existe?
        candidates_ids = [c["user_id"] for c in election.get("candidates", [])]
        if candidate_id not in candidates_ids:
            return {"error": "candidate_not_found"}

        # Já votou?
        votes = dict(election.get("votes", {}))
        if str(voter_id) in votes:
            return {"error": "already_voted"}

        votes[str(voter_id)] = candidate_id
        db["elections"].update_one(
            {"_id": election["_id"]},
            {"$set": {"votes": votes}}
        )

        return {"ok": True, "voted_for": candidate_id}

    @classmethod
    def finalize_election(cls, guild_id: int) -> dict:
        """Finaliza eleição, apura votos, empossa presidente."""
        db = get_connection()
        now = datetime.utcnow()

        election = db["elections"].find_one({
            "guild_id": guild_id,
            "status": {"$in": ["campaign", "voting"]},
        })
        if not election:
            return {"error": "no_active_election"}

        if now < election["voting_end"] and election["status"] != "voting":
            return {"error": "election_not_finished"}

        config = cls.get_config(guild_id)
        votes = election.get("votes", {})
        candidates = election.get("candidates", [])

        # Contagem
        tally = {}
        for voter_id, candidate_id in votes.items():
            tally[candidate_id] = tally.get(candidate_id, 0) + 1

        # Vencedor
        winner_id = None
        max_votes = 0
        for c_id, count in tally.items():
            if count > max_votes:
                max_votes = count
                winner_id = c_id

        min_votes = int(config.get("min_votes_to_win", 3))
        if max_votes < min_votes:
            # Sem vencedor válido
            db["elections"].update_one(
                {"_id": election["_id"]},
                {"$set": {
                    "status": "finished",
                    "finished_at": now,
                    "winner_id": None,
                    "reason": "insufficient_votes",
                }}
            )
            return {"error": "insufficient_votes", "max_votes": max_votes}

        # Remove presidente anterior
        db["government_officials"].update_many(
            {"guild_id": guild_id, "role": "president", "active": True},
            {"$set": {"active": False, "ended_at": now}}
        )

        # Empossa novo presidente
        term_days = int(config.get("term_days", 7))
        term_end = now + timedelta(days=term_days)

        db["government_officials"].insert_one({
            "guild_id": guild_id,
            "user_id": winner_id,
            "role": "president",
            "active": True,
            "started_at": now,
            "term_end": term_end,
            "votes_received": max_votes,
        })

        # Finaliza eleição
        db["elections"].update_one(
            {"_id": election["_id"]},
            {"$set": {
                "status": "finished",
                "finished_at": now,
                "winner_id": winner_id,
                "tally": {str(k): v for k, v in tally.items()},
            }}
        )

        return {
            "ok": True,
            "winner_id": winner_id,
            "votes": max_votes,
            "term_end": term_end,
        }

    # ============================================================
    # MINISTROS
    # ============================================================

    @classmethod
    def appoint_minister(
        cls, guild_id: int, president_id: int, minister_id: int, role: str
    ) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("can_appoint_ministers", True):
            return {"error": "appointment_disabled"}

        if not cls.is_president(guild_id, president_id):
            return {"error": "not_president"}

        valid_roles = ["fazenda", "economia", "trabalho", "defesa"]
        if role not in valid_roles:
            return {"error": "invalid_role", "valid": valid_roles}

        db = get_connection()

        # Remove ministro anterior do mesmo cargo
        db["government_officials"].update_many(
            {"guild_id": guild_id, "role": role, "active": True},
            {"$set": {"active": False, "ended_at": datetime.utcnow()}}
        )

        db["government_officials"].insert_one({
            "guild_id": guild_id,
            "user_id": minister_id,
            "role": role,
            "active": True,
            "appointed_by": president_id,
            "started_at": datetime.utcnow(),
        })

        return {"ok": True, "role": role}

    @classmethod
    def dismiss_minister(cls, guild_id: int, president_id: int, role: str) -> bool:
        if not cls.is_president(guild_id, president_id):
            return False
        db = get_connection()
        result = db["government_officials"].update_many(
            {"guild_id": guild_id, "role": role, "active": True},
            {"$set": {"active": False, "ended_at": datetime.utcnow()}}
        )
        return result.modified_count > 0

    # ============================================================
    # MANDATO (salário + expiração)
    # ============================================================

    @classmethod
    def pay_daily_salaries(cls, guild_id: int) -> dict:
        """Paga salários diários de presidente e ministros."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"paid": 0}

        db = get_connection()
        from commands_economy_core import EconomyManager

        officials = list(db["government_officials"].find({
            "guild_id": guild_id,
            "active": True,
        }))

        pres_salary = int(config.get("daily_salary", 500))
        min_salary = int(config.get("minister_salary", 200))

        paid = 0
        total = 0

        for o in officials:
            salary = pres_salary if o["role"] == "president" else min_salary
            EconomyManager.add_balance(
                guild_id, o["user_id"], salary,
                f"Salário político ({o['role']})",
                "gov_salary"
            )
            paid += 1
            total += salary

        return {"paid": paid, "total": total}

    @classmethod
    def check_term_expiry(cls, guild_id: int) -> dict:
        """Verifica se presidente teve mandato expirado."""
        config = cls.get_config(guild_id)
        db = get_connection()
        now = datetime.utcnow()

        presidents = list(db["government_officials"].find({
            "guild_id": guild_id,
            "role": "president",
            "active": True,
        }))

        expired = 0
        for p in presidents:
            if p.get("term_end") and p["term_end"] <= now:
                db["government_officials"].update_one(
                    {"_id": p["_id"]},
                    {"$set": {"active": False, "ended_at": now, "reason": "term_expired"}}
                )
                # Remove ministros
                db["government_officials"].update_many(
                    {"guild_id": guild_id, "role": {"$ne": "president"}, "active": True},
                    {"$set": {"active": False, "ended_at": now, "reason": "term_expired"}}
                )
                expired += 1

        return {"expired": expired}

    @classmethod
    def should_start_election(cls, guild_id: int) -> bool:
        """Verifica se precisa iniciar nova eleição."""
        config = cls.get_config(guild_id)
        db = get_connection()

        # Já tem presidente?
        president = cls.get_current_president(guild_id)
        if not president:
            return True

        # Já tem eleição ativa?
        active = db["elections"].find_one({
            "guild_id": guild_id,
            "status": {"$in": ["campaign", "voting"]},
        })
        if active:
            return False

        # Verifica intervalo
        last = db["elections"].find_one(
            {"guild_id": guild_id, "status": "finished"},
            sort=[("finished_at", -1)]
        )
        interval_days = int(config.get("election_interval_days", 7))
        if last and last.get("finished_at"):
            elapsed = (datetime.utcnow() - last["finished_at"]).days
            if elapsed < interval_days:
                return False

        return True

    # ============================================================
    # IMPEACHMENT
    # ============================================================

    @classmethod
    def vote_impeachment(cls, guild_id: int, voter_id: int) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("impeachment_enabled", True):
            return {"error": "impeachment_disabled"}

        president = cls.get_current_president(guild_id)
        if not president:
            return {"error": "no_president"}

        db = get_connection()
        db["government_officials"].update_one(
            {"_id": president["_id"]},
            {"$addToSet": {"impeachment_votes": voter_id}}
        )

        updated = db["government_officials"].find_one({"_id": president["_id"]})
        votes_count = len(updated.get("impeachment_votes", []))
        needed = int(config.get("impeachment_votes", 5))

        if votes_count >= needed:
            # Impeachment!
            db["government_officials"].update_one(
                {"_id": president["_id"]},
                {"$set": {"active": False, "ended_at": datetime.utcnow(),
                          "reason": "impeachment"}}
            )
            db["government_officials"].update_many(
                {"guild_id": guild_id, "role": {"$ne": "president"}, "active": True},
                {"$set": {"active": False, "ended_at": datetime.utcnow(),
                          "reason": "impeachment"}}
            )
            return {"ok": True, "impeached": True, "votes": votes_count}

        return {"ok": True, "impeached": False, "votes": votes_count, "needed": needed}

    # ============================================================
    # HISTÓRICO
    # ============================================================

    @classmethod
    def get_government_history(cls, guild_id: int, limit: int = 10) -> List[dict]:
        db = get_connection()
        return list(db["government_officials"].find({
            "guild_id": guild_id,
            "role": "president",
            "active": False,
        }).sort("ended_at", -1).limit(limit))

    @classmethod
    def clear_cache(cls) -> None:
        _political_cache.clear()


async def setup(bot):
    pass