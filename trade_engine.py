# ============================================================
# TRADE_ENGINE.PY - v7.0 Fase 6 (Comércio Internacional)
# ============================================================
# Responsável por:
#   • Exportação / importação entre guilds
#   • Tarifas configuráveis
#   • Balança comercial
#   • Registro de transações internacionais
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id
from currency_engine import CurrencyEngine


DEFAULT_TRADE_CONFIG = {
    "enabled": True,
    "default_tariff_percent": 5.0,   # tarifa padrão de importação
    "max_tariff_percent": 50.0,
    "min_tariff_percent": 0.0,
    "allow_player_trades": True,     # jogadores podem importar/exportar?
    "admin_only": False,             # só admin pode?
    "require_treaty": False,         # precisa de tratado pra comerciar?
    "max_trade_per_user_per_day": 10,
    "cooldown_seconds": 30,
}


_trade_cache = TTLCache(max_size=300, ttl=45)


class TradeEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _trade_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "trade"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_TRADE_CONFIG, **(doc.get("config") or {})}
        _trade_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "trade"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _trade_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # TARIFAS
    # ============================================================

    @classmethod
    def get_tariff(cls, guild_id: int) -> float:
        config = cls.get_config(guild_id)
        return float(config.get("default_tariff_percent", 5.0)) / 100.0

    @classmethod
    def get_effective_tariff(cls, from_guild: int, to_guild: int) -> float:
        """
        Tarifa efetiva = tarifa da guild importadora,
        reduzida se houver tratado comercial.
        """
        base_tariff = cls.get_tariff(to_guild)

        # Verifica tratado
        try:
            from diplomacy_engine import DiplomacyEngine
            treaty = DiplomacyEngine.get_active_treaty(to_guild, from_guild)
            if treaty:
                ttype = treaty.get("type", "")
                if ttype == "commercial":
                    base_tariff *= 0.5   # -50% com acordo comercial
                elif ttype == "alliance":
                    base_tariff *= 0.25  # -75% com aliança
                elif ttype == "free_trade":
                    base_tariff = 0.0    # livre comércio
                elif ttype == "embargo":
                    base_tariff = 1.0    # 100% bloqueio (não faz trade)
        except Exception:
            pass

        return max(0.0, min(0.5, base_tariff))

    # ============================================================
    # COMÉRCIO
    # ============================================================

    @classmethod
    def export_goods(
        cls,
        from_guild: int,
        to_guild: int,
        user_id: int,
        symbol: str,
        quantity: int,
    ) -> dict:
        """
        Exporta bens da guild origem pra guild destino.
        User precisa ter o item no inventário de market.
        """
        config = cls.get_config(from_guild)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        if from_guild == to_guild:
            return {"error": "same_guild"}

        if quantity <= 0:
            return {"error": "invalid_quantity"}

        # Verifica embargo
        try:
            from diplomacy_engine import DiplomacyEngine
            if DiplomacyEngine.has_embargo(from_guild, to_guild):
                return {"error": "embargo"}
        except Exception:
            pass

        db = get_connection()

        # Verifica holding do jogador
        from market_engine import MarketEngine
        holding = MarketEngine.get_holding(from_guild, user_id, symbol)
        if holding < quantity:
            return {"error": "insufficient_holding",
                    "have": holding, "needed": quantity}

        # Preço spot na guild origem
        from commodity_engine import CommodityEngine
        spot = MarketEngine.get_spot_price(from_guild, symbol)
        if spot <= 0:
            spot = CommodityEngine.get_price(from_guild, symbol)
        if spot <= 0:
            return {"error": "no_price"}

        # Valor total
        total_value = spot * quantity

        # Converte pra moeda da guild destino
        converted, rate = CurrencyEngine.convert(total_value, from_guild, to_guild)

        # Aplica tarifa
        tariff = cls.get_effective_tariff(from_guild, to_guild)
        tariff_amount = int(converted * tariff)
        net_to_seller = converted - tariff_amount

        # Remove do vendedor (holding)
        MarketEngine._adjust_holding(from_guild, user_id, symbol, -quantity)

        # Credita vendedor na guild origem (com valor convertido de volta)
        # Na prática, vendedor recebe em moeda local o valor bruto
        from commands_economy_core import EconomyManager
        EconomyManager.add_balance(
            from_guild, user_id, total_value,
            f"Exportação {quantity}x {symbol} → guild {to_guild}",
            "export"
        )

        # Tarifa vai pro tesouro da guild importadora
        if tariff_amount > 0:
            try:
                from treasury_engine import TreasuryEngine
                # Converte tarifa pra moeda da importadora
                treasury_amount, _ = CurrencyEngine.convert(
                    tariff_amount, to_guild, to_guild
                )
                TreasuryEngine.collect(
                    to_guild, tariff_amount,
                    f"Tarifa de importação de guild {from_guild}"
                )
            except Exception:
                pass

        # Registra transação internacional
        db["international_transfers"].insert_one({
            "from_guild": from_guild,
            "to_guild": to_guild,
            "user_id": user_id,
            "type": "export",
            "symbol": symbol,
            "quantity": quantity,
            "value_origin": total_value,
            "value_converted": converted,
            "tariff": tariff_amount,
            "net": net_to_seller,
            "rate": rate,
            "timestamp": datetime.utcnow(),
        })

        return {
            "ok": True,
            "type": "export",
            "quantity": quantity,
            "symbol": symbol,
            "value_origin": total_value,
            "converted": converted,
            "tariff": tariff_amount,
            "net_received": net_to_seller,
            "rate": rate,
        }

    @classmethod
    def import_goods(
        cls,
        to_guild: int,
        from_guild: int,
        user_id: int,
        symbol: str,
        quantity: int,
    ) -> dict:
        """
        Importa bens de outra guild.
        User paga em moeda local e recebe o item.
        """
        config = cls.get_config(to_guild)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        if from_guild == to_guild:
            return {"error": "same_guild"}

        if quantity <= 0:
            return {"error": "invalid_quantity"}

        # Verifica embargo
        try:
            from diplomacy_engine import DiplomacyEngine
            if DiplomacyEngine.has_embargo(to_guild, from_guild):
                return {"error": "embargo"}
        except Exception:
            pass

        # Preço spot na guild origem
        from market_engine import MarketEngine
        from commodity_engine import CommodityEngine

        spot = MarketEngine.get_spot_price(from_guild, symbol)
        if spot <= 0:
            spot = CommodityEngine.get_price(from_guild, symbol)
        if spot <= 0:
            return {"error": "no_price"}

        total_value_origin = spot * quantity

        # Converte pra moeda da guild importadora
        converted, rate = CurrencyEngine.convert(total_value_origin, from_guild, to_guild)

        # Aplica tarifa
        tariff = cls.get_effective_tariff(from_guild, to_guild)
        tariff_amount = int(converted * tariff)
        total_cost = converted + tariff_amount

        # Verifica saldo
        from commands_economy_core import EconomyManager
        balance = EconomyManager.get_balance(to_guild, user_id)
        if balance < total_cost:
            return {"error": "insufficient_funds",
                    "needed": total_cost, "have": balance}

        # Cobra do importador
        if not EconomyManager.remove_balance(
            to_guild, user_id, total_cost,
            f"Importação {quantity}x {symbol} ← guild {from_guild}",
            "import"
        ):
            return {"error": "payment_failed"}

        # Adiciona holding
        MarketEngine._adjust_holding(to_guild, user_id, symbol, quantity)

        # Tarifa vai pro tesouro da guild importadora
        if tariff_amount > 0:
            try:
                from treasury_engine import TreasuryEngine
                TreasuryEngine.collect(
                    to_guild, tariff_amount,
                    f"Tarifa de importação de {symbol}"
                )
            except Exception:
                pass

        # Registra
        db = get_connection()
        db["international_transfers"].insert_one({
            "from_guild": from_guild,
            "to_guild": to_guild,
            "user_id": user_id,
            "type": "import",
            "symbol": symbol,
            "quantity": quantity,
            "value_origin": total_value_origin,
            "value_converted": converted,
            "tariff": tariff_amount,
            "total_paid": total_cost,
            "rate": rate,
            "timestamp": datetime.utcnow(),
        })

        return {
            "ok": True,
            "type": "import",
            "quantity": quantity,
            "symbol": symbol,
            "value_origin": total_value_origin,
            "converted": converted,
            "tariff": tariff_amount,
            "total_paid": total_cost,
            "rate": rate,
        }

    # ============================================================
    # BALANÇA COMERCIAL
    # ============================================================

    @classmethod
    def get_trade_balance(cls, guild_id: int, hours: int = 24 * 7) -> dict:
        """Calcula balança comercial da guild."""
        db = get_connection()
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Exportações (guild origem = guild_id)
        exports = list(db["international_transfers"].aggregate([
            {"$match": {
                "from_guild": guild_id,
                "timestamp": {"$gte": cutoff},
            }},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$value_origin"},
                "count": {"$sum": 1},
            }},
        ]))

        # Importações (guild destino = guild_id)
        imports = list(db["international_transfers"].aggregate([
            {"$match": {
                "to_guild": guild_id,
                "timestamp": {"$gte": cutoff},
            }},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$value_converted"},
                "count": {"$sum": 1},
            }},
        ]))

        export_total = int(exports[0]["total"]) if exports else 0
        import_total = int(imports[0]["total"]) if imports else 0
        export_count = exports[0]["count"] if exports else 0
        import_count = imports[0]["count"] if imports else 0

        return {
            "exports": export_total,
            "imports": import_total,
            "balance": export_total - import_total,
            "export_count": export_count,
            "import_count": import_count,
        }

    @classmethod
    def get_recent_trades(cls, guild_id: int, limit: int = 15) -> List[dict]:
        db = get_connection()
        return list(db["international_transfers"].find({
            "$or": [
                {"from_guild": guild_id},
                {"to_guild": guild_id},
            ],
        }).sort("timestamp", -1).limit(limit))

    @classmethod
    def clear_cache(cls) -> None:
        _trade_cache.clear()


async def setup(bot):
    pass