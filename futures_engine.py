# ============================================================
# FUTURES_ENGINE.PY - v7.0 Fase 4 (Contratos Futuros)
# ============================================================
# Responsável por:
#   • Abertura de contratos long/short
#   • Margem + alavancagem
#   • Liquidação no vencimento
#   • Liquidação forçada (margin call)
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id


DEFAULT_FUTURES_CONFIG = {
    "enabled": True,
    "max_leverage": 20,
    "min_leverage": 1,
    "default_leverage": 5,
    "maintenance_margin": 0.5,       # 50% da margem inicial
    "maker_fee_percent": 0.10,
    "taker_fee_percent": 0.20,
    "liquidation_fee_percent": 0.5,
    "max_contracts_per_user": 5,
    "durations_hours": [24, 72, 168, 720],   # 1d, 3d, 7d, 30d
    "settlement_grace_hours": 1,
}


_futures_cache = TTLCache(max_size=300, ttl=30)


class FuturesEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _futures_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "futures"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_FUTURES_CONFIG, **(doc.get("config") or {})}
        _futures_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "futures"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _futures_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # ABRIR CONTRATO
    # ============================================================

    @classmethod
    def open_contract(
        cls,
        guild_id: int,
        user_id: int,
        symbol: str,
        direction: str,     # "long" | "short"
        quantity: int,
        leverage: int,
        duration_hours: int,
    ) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        direction = direction.lower()
        if direction not in ("long", "short"):
            return {"error": "invalid_direction"}

        max_lev = int(config.get("max_leverage", 20))
        min_lev = int(config.get("min_leverage", 1))
        if leverage < min_lev or leverage > max_lev:
            return {"error": "invalid_leverage",
                    "min": min_lev, "max": max_lev}

        durations = config.get("durations_hours", [24, 72, 168, 720])
        if duration_hours not in durations:
            return {"error": "invalid_duration", "allowed": durations}

        # Spot atual
        from market_engine import MarketEngine
        from commodity_engine import CommodityEngine
        spot = MarketEngine.get_spot_price(guild_id, symbol.upper())
        if spot <= 0:
            spot = CommodityEngine.get_price(guild_id, symbol.upper())
        if spot <= 0:
            return {"error": "no_price"}

        db = get_connection()

        # Limite de contratos
        open_count = db["futures_contracts"].count_documents({
            "guild_id": guild_id,
            "user_id": user_id,
            "status": "open",
        })
        if open_count >= int(config.get("max_contracts_per_user", 5)):
            return {"error": "too_many_contracts"}

        # Margem inicial = notional / leverage
        notional = spot * quantity
        margin = int(notional / leverage)

        # Verifica saldo
        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < margin:
            return {"error": "insufficient_margin",
                    "needed": margin, "have": balance}

        # Cobra margem
        EconomyManager.remove_balance(
            guild_id, user_id, margin,
            f"Margem futuros {direction} {symbol}",
            "futures_margin"
        )

        now = datetime.utcnow()
        expires = now + timedelta(hours=duration_hours)

        doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "symbol": symbol.upper(),
            "direction": direction,
            "quantity": int(quantity),
            "leverage": int(leverage),
            "entry_price": spot,
            "notional": notional,
            "margin": margin,
            "duration_hours": int(duration_hours),
            "status": "open",
            "created_at": now,
            "expires_at": expires,
            "liquidation_price": cls._compute_liquidation_price(
                spot, direction, leverage,
                float(config.get("maintenance_margin", 0.5))
            ),
        }
        result = db["futures_contracts"].insert_one(doc)

        return {
            "ok": True,
            "contract_id": str(result.inserted_id),
            "symbol": doc["symbol"],
            "direction": direction,
            "quantity": quantity,
            "leverage": leverage,
            "entry": spot,
            "margin": margin,
            "expires_at": expires,
            "liquidation_price": doc["liquidation_price"],
        }

    @classmethod
    def _compute_liquidation_price(
        cls, entry: int, direction: str, leverage: int, maintenance: float
    ) -> int:
        """Preço em que o contrato é liquidado."""
        move_pct = (1.0 / leverage) * (1 - maintenance)
        if direction == "long":
            return max(1, int(entry * (1 - move_pct)))
        else:
            return int(entry * (1 + move_pct))

    # ============================================================
    # FECHAR
    # ============================================================

    @classmethod
    def close_contract(
        cls, guild_id: int, user_id: int, contract_id: str, reason: str = "manual"
    ) -> dict:
        db = get_connection()
        oid = safe_object_id(contract_id)
        if not oid:
            return {"error": "invalid_id"}

        contract = db["futures_contracts"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "user_id": user_id,
            "status": "open",
        })
        if not contract:
            return {"error": "not_found"}

        # Preço atual
        from market_engine import MarketEngine
        from commodity_engine import CommodityEngine
        spot = MarketEngine.get_spot_price(guild_id, contract["symbol"])
        if spot <= 0:
            spot = CommodityEngine.get_price(guild_id, contract["symbol"])
        if spot <= 0:
            return {"error": "no_price"}

        # Calcula PnL
        entry = int(contract["entry_price"])
        quantity = int(contract["quantity"])
        direction = contract["direction"]

        if direction == "long":
            pnl = (spot - entry) * quantity
        else:
            pnl = (entry - spot) * quantity

        config = cls.get_config(guild_id)
        fee_pct = float(config.get("taker_fee_percent", 0.20)) / 100.0
        fee = int(abs(pnl) * fee_pct)

        payout = int(contract["margin"]) + pnl - fee

        from commands_economy_core import EconomyManager
        if payout > 0:
            EconomyManager.add_balance(
                guild_id, user_id, payout,
                f"Futuros fechado ({reason})",
                "futures_close"
            )

        db["futures_contracts"].update_one(
            {"_id": contract["_id"]},
            {
                "$set": {
                    "status": "closed",
                    "closed_at": datetime.utcnow(),
                    "exit_price": spot,
                    "pnl": pnl,
                    "fee": fee,
                    "payout": max(0, payout),
                    "close_reason": reason,
                }
            }
        )

        return {
            "ok": True,
            "exit_price": spot,
            "pnl": pnl,
            "fee": fee,
            "payout": max(0, payout),
        }

    # ============================================================
    # PROCESSAMENTO POR TICK
    # ============================================================

    @classmethod
    def process_tick(cls, guild_id: int) -> dict:
        """Verifica liquidações e vencimentos."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"liquidated": 0, "expired": 0}

        db = get_connection()
        now = datetime.utcnow()

        contracts = list(db["futures_contracts"].find({
            "guild_id": guild_id,
            "status": "open",
        }))

        from market_engine import MarketEngine
        from commodity_engine import CommodityEngine

        liquidated = 0
        expired = 0

        for c in contracts:
            spot = MarketEngine.get_spot_price(guild_id, c["symbol"])
            if spot <= 0:
                spot = CommodityEngine.get_price(guild_id, c["symbol"])
            if spot <= 0:
                continue

            liq = int(c.get("liquidation_price", 0))
            direction = c["direction"]
            should_liq = (
                (direction == "long" and spot <= liq) or
                (direction == "short" and spot >= liq)
            )

            if should_liq:
                cls.close_contract(guild_id, c["user_id"], str(c["_id"]), "liquidation")
                liquidated += 1
                continue

            if c.get("expires_at") and c["expires_at"] <= now:
                cls.close_contract(guild_id, c["user_id"], str(c["_id"]), "expired")
                expired += 1

        return {"liquidated": liquidated, "expired": expired}

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_user_contracts(cls, guild_id: int, user_id: int) -> List[dict]:
        db = get_connection()
        return list(db["futures_contracts"].find({
            "guild_id": guild_id,
            "user_id": user_id,
            "status": "open",
        }).sort("created_at", -1))

    @classmethod
    def clear_cache(cls) -> None:
        _futures_cache.clear()


async def setup(bot):
    pass