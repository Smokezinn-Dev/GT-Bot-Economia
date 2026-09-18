# ============================================================
# JOB_ENGINE.PY - v7.0 Fase 2 + Fase 5 (Empregos + Tesouro)
# ============================================================
# Responsável por:
#   • Gerenciar empregos criados por empresas
#   • Contratar/demitir funcionários
#   • Calcular salários por tick
#   • Pagar salários (chamado pelo tick)
#   • Fase 5: Destinar imposto de salário ao tesouro público
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


DEFAULT_JOB_CONFIG = {
    "enabled": True,
    "max_jobs_per_company": 10,
    "max_employees_per_company": 20,
    "min_salary": 10,             # salário mínimo por tick
    "max_salary": 10000,          # salário máximo por tick
    "salary_tax_percent": 5.0,    # imposto sobre salário (destinado ao governo)
    "auto_pay_salaries": True,    # paga automaticamente no tick
    "allow_player_jobs": True,    # jogadores podem criar empregos
    "require_application": False, # precisa se candidatar?
}


class JobEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "jobs"},
            {"_id": 0, "config": 1}
        ) or {}
        return {**DEFAULT_JOB_CONFIG, **(doc.get("config") or {})}

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "jobs"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )

    # ============================================================
    # CRIAR / REMOVER EMPREGO
    # ============================================================

    @classmethod
    def create_job(
        cls,
        guild_id: int,
        company_id: str,
        title: str,
        salary: int,
        description: str = "",
    ) -> Optional[str]:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return None

        salary = max(int(config.get("min_salary", 10)),
                     min(int(config.get("max_salary", 10000)), int(salary)))

        db = get_connection()
        existing = db["jobs"].count_documents({
            "guild_id": guild_id,
            "company_id": company_id,
            "active": True,
        })
        if existing >= int(config.get("max_jobs_per_company", 10)):
            return None

        result = db["jobs"].insert_one({
            "guild_id": guild_id,
            "company_id": company_id,
            "title": title[:100],
            "salary": salary,
            "description": description[:500],
            "active": True,
            "employees": [],
            "created_at": datetime.utcnow(),
        })
        return str(result.inserted_id)

    @classmethod
    def close_job(cls, guild_id: int, job_id: str) -> bool:
        db = get_connection()
        from utils import safe_object_id
        oid = safe_object_id(job_id)
        if not oid:
            return False
        result = db["jobs"].update_one(
            {"_id": oid, "guild_id": guild_id},
            {"$set": {"active": False, "closed_at": datetime.utcnow()}}
        )
        return result.modified_count > 0

    # ============================================================
    # CONTRATAR / DEMITIR
    # ============================================================

    @classmethod
    def hire(cls, guild_id: int, job_id: str, user_id: int) -> bool:
        db = get_connection()
        from utils import safe_object_id

        oid = safe_object_id(job_id)
        if not oid:
            return False

        job = db["jobs"].find_one({"_id": oid, "guild_id": guild_id, "active": True})
        if not job:
            return False

        if user_id in (job.get("employees") or []):
            return False

        existing_contract = db["job_contracts"].find_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "active": True,
        })
        if existing_contract:
            return False

        config = cls.get_config(guild_id)
        company_id = job["company_id"]
        total_emp = db["job_contracts"].count_documents({
            "guild_id": guild_id,
            "company_id": company_id,
            "active": True,
        })
        if total_emp >= int(config.get("max_employees_per_company", 20)):
            return False

        db["job_contracts"].insert_one({
            "guild_id": guild_id,
            "job_id": str(job["_id"]),
            "company_id": company_id,
            "user_id": user_id,
            "salary": int(job.get("salary", 0)),
            "hired_at": datetime.utcnow(),
            "active": True,
            "total_earned": 0,
            "ticks_worked": 0,
        })

        db["jobs"].update_one(
            {"_id": job["_id"]},
            {"$addToSet": {"employees": user_id}}
        )
        return True

    @classmethod
    def fire(cls, guild_id: int, user_id: int) -> bool:
        db = get_connection()
        contract = db["job_contracts"].find_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "active": True,
        })
        if not contract:
            return False

        db["job_contracts"].update_one(
            {"_id": contract["_id"]},
            {"$set": {"active": False, "fired_at": datetime.utcnow()}}
        )
        try:
            from utils import safe_object_id
            jid = safe_object_id(contract.get("job_id", ""))
            if jid:
                db["jobs"].update_one(
                    {"_id": jid},
                    {"$pull": {"employees": user_id}}
                )
        except Exception:
            pass
        return True

    # ============================================================
    # PAGAR SALÁRIOS (com destinação de imposto)
    # ============================================================

    @classmethod
    def pay_salaries(cls, guild_id: int) -> Dict[str, int]:
        """
        Paga salários de todos os contratos ativos.
        Imposto retido é destinado ao tesouro público (Fase 5),
        se o TreasuryEngine estiver disponível.
        """
        config = cls.get_config(guild_id)
        if not config.get("enabled", True) or not config.get("auto_pay_salaries", True):
            return {"paid": 0, "total": 0, "tax": 0, "failed": 0}

        from commands_economy_core import EconomyManager
        db = get_connection()

        contracts = list(db["job_contracts"].find({
            "guild_id": guild_id,
            "active": True,
        }))

        paid = 0
        total = 0
        tax_total = 0
        failed = 0
        tax_pct = float(config.get("salary_tax_percent", 5.0)) / 100.0

        # Importa TreasuryEngine de forma segura (Fase 5 pode não estar instalada)
        treasury = None
        try:
            from treasury_engine import TreasuryEngine
            treasury = TreasuryEngine
        except ImportError:
            treasury = None
        except Exception:
            treasury = None

        for contract in contracts:
            salary = int(contract.get("salary", 0))
            if salary <= 0:
                continue

            company_id = contract.get("company_id")
            user_id = contract.get("user_id")

            company = None
            if company_id:
                from utils import safe_object_id
                oid = safe_object_id(company_id)
                if oid:
                    company = db["companies"].find_one(
                        {"_id": oid, "guild_id": guild_id}
                    )

            if not company:
                failed += 1
                continue

            cash = int(company.get("cash", 0))
            if cash < salary:
                db["company_financials"].insert_one({
                    "guild_id": guild_id,
                    "company_id": str(company["_id"]),
                    "type": "salary_failed",
                    "amount": salary,
                    "user_id": user_id,
                    "timestamp": datetime.utcnow(),
                })
                failed += 1
                continue

            # Debita da empresa
            db["companies"].update_one(
                {"_id": company["_id"]},
                {"$inc": {"cash": -salary}}
            )

            # Calcula imposto retido
            tax = int(salary * tax_pct)
            net = salary - tax

            # Paga funcionário (líquido)
            EconomyManager.add_balance(
                guild_id, user_id, net,
                f"Salário ({company.get('name', '?')})",
                "salary"
            )

            # -------- Fase 5: destina imposto ao tesouro --------
            if tax > 0 and treasury is not None:
                try:
                    treasury.collect(
                        guild_id, tax,
                        f"Imposto de salário (empresa {company.get('name', '?')})"
                    )
                except Exception:
                    # Se tesouro falhar, o imposto some do sistema (sink real)
                    # mas não trava o fluxo.
                    pass

            # Registra
            db["job_contracts"].update_one(
                {"_id": contract["_id"]},
                {
                    "$inc": {
                        "total_earned": net,
                        "ticks_worked": 1,
                    },
                    "$set": {"last_paid_at": datetime.utcnow()},
                }
            )
            db["company_financials"].insert_one({
                "guild_id": guild_id,
                "company_id": str(company["_id"]),
                "type": "salary_paid",
                "amount": salary,
                "tax": tax,
                "net": net,
                "user_id": user_id,
                "timestamp": datetime.utcnow(),
            })

            paid += 1
            total += salary
            tax_total += tax

        return {
            "paid": paid,
            "total": total,
            "tax": tax_total,
            "failed": failed,
        }

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def list_jobs(cls, guild_id: int) -> List[dict]:
        db = get_connection()
        return list(db["jobs"].find({
            "guild_id": guild_id,
            "active": True,
        }).sort("salary", -1))

    @classmethod
    def get_user_contract(cls, guild_id: int, user_id: int) -> Optional[dict]:
        db = get_connection()
        return db["job_contracts"].find_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "active": True,
        })

    @classmethod
    def get_job(cls, guild_id: int, job_id: str) -> Optional[dict]:
        from utils import safe_object_id
        oid = safe_object_id(job_id)
        if not oid:
            return None
        db = get_connection()
        return db["jobs"].find_one({"_id": oid, "guild_id": guild_id})


async def setup(bot):
    pass