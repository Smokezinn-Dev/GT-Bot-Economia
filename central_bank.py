# ============================================================
# CENTRAL_BANK.PY - v7.0 Fase 3 (Banco Central)
# ============================================================
# Responsável por:
#   • Definir Selic (taxa básica de juros)
#   • Emitir moeda (gera inflação)
#   • Operações de mercado aberto (QE / Tightening)
#   • Reservas obrigatórias
#   • Combate à inflação
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


DEFAULT_CENTRAL_BANK_CONFIG = {
    "enabled": True,
    "selic_rate": 0.02,              # 2% ao tick (taxa base)
    "max_selic": 0.20,               # teto 20%
    "min_selic": 0.0,                # piso 0%
    "emission_cap_per_tick": 100_000, # máx emissão por tick
    "emission_used_this_tick": 0,
    "reserve_requirement": 0.10,     # % que bancos devem guardar
    "inflation_target": 1.0,         # meta de inflação (%)
    "inflation_tolerance": 0.5,      # ±0.5%
    "auto_adjust_selic": True,       # ajusta Selic automaticamente
    "selic_adjustment_factor": 0.5,  # quanto ajusta por tick
    "max_emission_per_day": 1_000_000,
    "created_at": None,
}


_cb_cache = TTLCache(max_size=200, ttl=60)


class CentralBank:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _cb_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["central_bank_config"].find_one({"guild_id": guild_id}) or {}
        config = {**DEFAULT_CENTRAL_BANK_CONFIG, **{k: v for k, v in doc.items() if k != "_id"}}
        if not config.get("created_at"):
            config["created_at"] = datetime.utcnow()
        _cb_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["central_bank_config"].update_one(
            {"guild_id": guild_id},
            {"$set": {key: value}},
            upsert=True,
        )
        _cb_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # SELIC
    # ============================================================

    @classmethod
    def get_selic(cls, guild_id: int) -> float:
        config = cls.get_config(guild_id)
        return float(config.get("selic_rate", 0.02))

    @classmethod
    def set_selic(cls, guild_id: int, rate: float) -> float:
        config = cls.get_config(guild_id)
        rate = max(float(config.get("min_selic", 0.0)),
                   min(float(config.get("max_selic", 0.20)), rate))
        cls.update_config(guild_id, "selic_rate", rate)

        # Registra operação
        db = get_connection()
        db["central_bank_ops"].insert_one({
            "guild_id": guild_id,
            "type": "selic_change",
            "new_rate": rate,
            "timestamp": datetime.utcnow(),
        })
        return rate

    @classmethod
    def auto_adjust_selic(cls, guild_id: int, current_inflation: float) -> Optional[float]:
        """
        Ajusta Selic com base na inflação (regra de Taylor simplificada).
        Se inflação > meta → aumenta Selic.
        Se inflação < meta → diminui Selic.
        """
        config = cls.get_config(guild_id)
        if not config.get("auto_adjust_selic", True):
            return None

        target = float(config.get("inflation_target", 1.0))
        tolerance = float(config.get("inflation_tolerance", 0.5))
        current_selic = float(config.get("selic_rate", 0.02))
        factor = float(config.get("selic_adjustment_factor", 0.5))

        # Inflação acima da meta + tolerância → aumenta
        if current_inflation > target + tolerance:
            excess = current_inflation - (target + tolerance)
            new_selic = current_selic + (excess * 0.01 * factor)
        elif current_inflation < target - tolerance:
            deficit = (target - tolerance) - current_inflation
            new_selic = current_selic - (deficit * 0.01 * factor)
        else:
            return None  # dentro da meta

        return cls.set_selic(guild_id, new_selic)

    # ============================================================
    # EMISSÃO
    # ============================================================

    @classmethod
    def can_emit(cls, guild_id: int, amount: int) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"ok": False, "reason": "disabled"}

        cap = int(config.get("emission_cap_per_tick", 100_000))
        used = int(config.get("emission_used_this_tick", 0))
        if amount > cap - used:
            return {"ok": False, "reason": "tick_cap",
                    "available": cap - used}

        # Verifica limite diário
        db = get_connection()
        day_ago = datetime.utcnow() - timedelta(hours=24)
        emissions = list(db["central_bank_ops"].aggregate([
            {"$match": {
                "guild_id": guild_id,
                "type": "emission",
                "timestamp": {"$gte": day_ago},
            }},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]))
        daily_used = int(emissions[0]["total"]) if emissions else 0
        daily_cap = int(config.get("max_emission_per_day", 1_000_000))
        if daily_used + amount > daily_cap:
            return {"ok": False, "reason": "daily_cap",
                    "available": daily_cap - daily_used}

        return {"ok": True}

    @classmethod
    def emit_money(
        cls,
        guild_id: int,
        amount: int,
        recipient_id: Optional[int] = None,
        description: str = "Emissão monetária",
    ) -> dict:
        """
        Emite moeda nova.
        Se recipient_id → credita pra alguém.
        Se None → vai pro "tesouro" (não circula).
        """
        check = cls.can_emit(guild_id, amount)
        if not check.get("ok"):
            return {"error": check.get("reason")}

        db = get_connection()

        if recipient_id:
            from commands_economy_core import EconomyManager
            EconomyManager.add_balance(
                guild_id, recipient_id, amount,
                description, "emission"
            )

        db["central_bank_ops"].insert_one({
            "guild_id": guild_id,
            "type": "emission",
            "amount": int(amount),
            "recipient_id": recipient_id,
            "description": description[:200],
            "timestamp": datetime.utcnow(),
        })

        # Atualiza contador do tick
        config = cls.get_config(guild_id)
        used = int(config.get("emission_used_this_tick", 0)) + amount
        cls.update_config(guild_id, "emission_used_this_tick", used)

        return {"ok": True, "emitted": amount}

    @classmethod
    def reset_tick_emission(cls, guild_id: int) -> None:
        """Chamado pelo tick — reseta contador de emissão."""
        cls.update_config(guild_id, "emission_used_this_tick", 0)

    # ============================================================
    # OPERAÇÕES DE MERCADO ABERTO (QE / Tightening)
    # ============================================================

    @classmethod
    def quantitative_easing(cls, guild_id: int, amount: int) -> dict:
        """QE — injeta liquidez."""
        check = cls.can_emit(guild_id, amount)
        if not check.get("ok"):
            return {"error": check.get("reason")}

        db = get_connection()
        db["central_bank_ops"].insert_one({
            "guild_id": guild_id,
            "type": "qe",
            "amount": int(amount),
            "timestamp": datetime.utcnow(),
        })

        # Reduz Selic automaticamente
        current = cls.get_selic(guild_id)
        cls.set_selic(guild_id, current * 0.9)  # -10%

        return {"ok": True, "qe_amount": amount, "new_selic": cls.get_selic(guild_id)}

    @classmethod
    def tightening(cls, guild_id: int, amount: int) -> dict:
        """Tightening — retira liquidez."""
        db = get_connection()
        db["central_bank_ops"].insert_one({
            "guild_id": guild_id,
            "type": "tightening",
            "amount": int(amount),
            "timestamp": datetime.utcnow(),
        })

        # Aumenta Selic
        current = cls.get_selic(guild_id)
        cls.set_selic(guild_id, current * 1.1)  # +10%

        return {"ok": True, "tightened": amount, "new_selic": cls.get_selic(guild_id)}

    # ============================================================
    # RESERVAS OBRIGATÓRIAS
    # ============================================================

    @classmethod
    def set_reserve_requirement(cls, guild_id: int, ratio: float) -> None:
        ratio = max(0.0, min(1.0, ratio))
        cls.update_config(guild_id, "reserve_requirement", ratio)

    @classmethod
    def get_reserve_requirement(cls, guild_id: int) -> float:
        config = cls.get_config(guild_id)
        return float(config.get("reserve_requirement", 0.10))

    # ============================================================
    # PROCESSAMENTO POR TICK
    # ============================================================

    @classmethod
    def process_tick(cls, guild_id: int, current_inflation: float) -> dict:
        """Roda no tick — reset emissão + auto-ajuste Selic."""
        cls.reset_tick_emission(guild_id)
        new_selic = cls.auto_adjust_selic(guild_id, current_inflation)

        return {
            "selic": cls.get_selic(guild_id),
            "adjusted": new_selic is not None,
        }

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_ops_history(cls, guild_id: int, limit: int = 20) -> List[dict]:
        db = get_connection()
        return list(db["central_bank_ops"].find({
            "guild_id": guild_id,
        }).sort("timestamp", -1).limit(limit))

    @classmethod
    def get_money_supply_estimate(cls, guild_id: int) -> int:
        """Estima moeda em circulação × multiplicador."""
        from commands_economy_core import EconomyManager
        from bank_engine import BankEngine
        base = EconomyManager.get_total_balance(guild_id)
        mult = BankEngine.get_money_multiplier(guild_id)
        return int(base * mult)

    @classmethod
    def clear_cache(cls) -> None:
        _cb_cache.clear()


async def setup(bot):
    pass