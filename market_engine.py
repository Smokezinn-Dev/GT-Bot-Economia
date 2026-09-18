# ============================================================
# MARKET_ENGINE.PY - v7.0 Fase 4 (Order Book Real)
# ============================================================
# Responsável por:
#   • Gerenciar order book (bid/ask) por símbolo
#   • Processar limit orders e market orders
#   • Executar matching de ordens
#   • Market maker automático (evita book vazio)
#   • Fornecer preço spot (último trade)
# ============================================================

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache, safe_object_id


DEFAULT_MARKET_CONFIG = {
    "enabled": True,
    "max_orders_per_user": 20,
    "min_order_size": 1,
    "max_order_size": 100_000,
    "tick_size": 1,                    # preço mínimo de incremento
    "maker_fee_percent": 0.10,         # taxa para quem coloca ordem
    "taker_fee_percent": 0.20,         # taxa para quem executa
    "enable_market_maker": True,       # bot cria liquidez
    "market_maker_spread_percent": 2.0, # spread do MM
    "market_maker_depth": 5,           # níveis que MM cobre
    "market_maker_size": 100,          # tamanho base do MM
    "auto_expire_orders_days": 7,      # ordens expiram após N dias
    "max_spread_percent": 10.0,        # sanidade
}


_market_cache = TTLCache(max_size=400, ttl=20)


class MarketEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _market_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "market_v7"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_MARKET_CONFIG, **(doc.get("config") or {})}
        _market_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "market_v7"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _market_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # ORDERS
    # ============================================================

    @classmethod
    def place_limit_order(
        cls,
        guild_id: int,
        user_id: int,
        symbol: str,
        side: str,          # "buy" | "sell"
        price: int,
        quantity: int,
    ) -> dict:
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        side = side.lower()
        if side not in ("buy", "sell"):
            return {"error": "invalid_side"}

        if quantity < int(config.get("min_order_size", 1)):
            return {"error": "quantity_too_low"}
        if quantity > int(config.get("max_order_size", 100000)):
            return {"error": "quantity_too_high"}
        if price <= 0:
            return {"error": "invalid_price"}

        db = get_connection()

        # Verifica limite de ordens abertas
        open_orders = db["market_orders"].count_documents({
            "guild_id": guild_id,
            "user_id": user_id,
            "status": "open",
        })
        if open_orders >= int(config.get("max_orders_per_user", 20)):
            return {"error": "too_many_orders"}

        # Bloqueia fundos/bens
        if side == "buy":
            total_cost = price * quantity
            from commands_economy_core import EconomyManager
            balance = EconomyManager.get_balance(guild_id, user_id)
            if balance < total_cost:
                return {"error": "insufficient_balance",
                        "needed": total_cost, "have": balance}
            # Escrow: remove do saldo
            EconomyManager.remove_balance(
                guild_id, user_id, total_cost,
                f"Ordem de compra {symbol}@{price}",
                "market_escrow"
            )
        else:
            # Sell: verifica que tem o ativo
            holding = cls.get_holding(guild_id, user_id, symbol)
            if holding < quantity:
                return {"error": "insufficient_holdings",
                        "have": holding, "needed": quantity}
            # Escrow de ativos
            cls._adjust_holding(guild_id, user_id, symbol, -quantity, locked=True)

        doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "symbol": symbol.upper(),
            "side": side,
            "type": "limit",
            "price": int(price),
            "quantity": int(quantity),
            "filled": 0,
            "status": "open",
            "created_at": datetime.utcnow(),
        }
        result = db["market_orders"].insert_one(doc)

        # Tenta match imediatamente
        cls._try_match(guild_id, symbol.upper())

        return {
            "ok": True,
            "order_id": str(result.inserted_id),
            "side": side,
            "price": price,
            "quantity": quantity,
        }

    @classmethod
    def place_market_order(
        cls,
        guild_id: int,
        user_id: int,
        symbol: str,
        side: str,
        quantity: int,
    ) -> dict:
        """Market order: executa imediatamente contra o melhor preço disponível."""
        config = cls.get_config(guild_id)
        if not config.get("enabled", True):
            return {"error": "disabled"}

        db = get_connection()
        symbol = symbol.upper()

        # Pega o melhor preço do lado oposto
        opposite = "ask" if side.lower() == "buy" else "bid"
        query = {
            "guild_id": guild_id,
            "symbol": symbol,
            "status": "open",
        }
        if opposite == "ask":
            query["side"] = "sell"
            sort_dir = 1  # menor preço primeiro
        else:
            query["side"] = "buy"
            sort_dir = -1  # maior preço primeiro

        best = db["market_orders"].find_one(query, sort=[("price", sort_dir)])
        if not best:
            return {"error": "no_liquidity"}

        # Cria limit order ao preço do best (vai matchear direto)
        return cls.place_limit_order(
            guild_id, user_id, symbol, side,
            int(best["price"]), quantity
        )

    @classmethod
    def cancel_order(cls, guild_id: int, user_id: int, order_id: str) -> dict:
        db = get_connection()
        oid = safe_object_id(order_id)
        if not oid:
            return {"error": "invalid_id"}

        order = db["market_orders"].find_one({
            "_id": oid,
            "guild_id": guild_id,
            "user_id": user_id,
            "status": "open",
        })
        if not order:
            return {"error": "not_found"}

        remaining = int(order["quantity"]) - int(order.get("filled", 0))

        # Devolve escrow
        if order["side"] == "buy":
            refund = int(order["price"]) * remaining
            from commands_economy_core import EconomyManager
            EconomyManager.add_balance(
                guild_id, user_id, refund,
                f"Cancelamento ordem {order['symbol']}",
                "market_refund"
            )
        else:
            cls._adjust_holding(
                guild_id, user_id, order["symbol"], remaining, locked=True, release=True
            )

        db["market_orders"].update_one(
            {"_id": order["_id"]},
            {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow()}}
        )

        return {"ok": True, "cancelled": remaining}

    # ============================================================
    # MATCHING
    # ============================================================

    @classmethod
    def _try_match(cls, guild_id: int, symbol: str) -> int:
        """Tenta casar ordens de compra e venda. Retorna trades executados."""
        config = cls.get_config(guild_id)
        db = get_connection()

        trades = 0
        max_iterations = 50  # evita loop infinito

        for _ in range(max_iterations):
            # Melhor bid (compra mais alta)
            best_bid = db["market_orders"].find_one({
                "guild_id": guild_id,
                "symbol": symbol,
                "side": "buy",
                "status": "open",
            }, sort=[("price", -1), ("created_at", 1)])

            # Melhor ask (venda mais baixa)
            best_ask = db["market_orders"].find_one({
                "guild_id": guild_id,
                "symbol": symbol,
                "side": "sell",
                "status": "open",
            }, sort=[("price", 1), ("created_at", 1)])

            if not best_bid or not best_ask:
                break

            bid_price = int(best_bid["price"])
            ask_price = int(best_ask["price"])

            # Sem cruzamento, para
            if bid_price < ask_price:
                break

            # Executa trade
            bid_remaining = int(best_bid["quantity"]) - int(best_bid.get("filled", 0))
            ask_remaining = int(best_ask["quantity"]) - int(best_ask.get("filled", 0))
            trade_qty = min(bid_remaining, ask_remaining)

            if trade_qty <= 0:
                break

            # Preço de execução: preço da ordem que chegou primeiro
            exec_price = ask_price if best_ask["created_at"] < best_bid["created_at"] else bid_price

            cls._execute_trade(
                guild_id, best_bid, best_ask, exec_price, trade_qty, config
            )
            trades += 1

        return trades

    @classmethod
    def _execute_trade(
        cls,
        guild_id: int,
        bid: dict,
        ask: dict,
        exec_price: int,
        quantity: int,
        config: dict,
    ) -> None:
        """Executa um trade entre duas ordens."""
        db = get_connection()
        buyer_id = bid["user_id"]
        seller_id = ask["user_id"]
        symbol = bid["symbol"]

        # Custos
        maker_fee_pct = float(config.get("maker_fee_percent", 0.10)) / 100.0
        taker_fee_pct = float(config.get("taker_fee_percent", 0.20)) / 100.0

        # Preço do comprador (bid.price) menos exec_price = "troco" que volta pro buyer
        buyer_refund = (int(bid["price"]) - exec_price) * quantity
        if buyer_refund > 0:
            from commands_economy_core import EconomyManager
            EconomyManager.add_balance(
                guild_id, buyer_id, buyer_refund,
                f"Troco ordem {symbol}", "market_change"
            )

        # Valor líquido que o vendedor recebe
        gross = exec_price * quantity
        fee_seller = int(gross * taker_fee_pct)
        net_seller = gross - fee_seller

        from commands_economy_core import EconomyManager
        EconomyManager.add_balance(
            guild_id, seller_id, net_seller,
            f"Venda {quantity}x {symbol} @ {exec_price}",
            "market_sell"
        )

        # Comprador recebe ativos
        cls._adjust_holding(guild_id, buyer_id, symbol, quantity)

        # Comprador paga fee do maker
        fee_buyer = int(exec_price * quantity * maker_fee_pct)
        if fee_buyer > 0:
            EconomyManager.remove_balance(
                guild_id, buyer_id, fee_buyer,
                f"Taxa maker {symbol}", "market_fee"
            )

        # Atualiza ordens
        db["market_orders"].update_one(
            {"_id": bid["_id"]},
            {"$inc": {"filled": quantity}}
        )
        db["market_orders"].update_one(
            {"_id": ask["_id"]},
            {"$inc": {"filled": quantity}}
        )

        # Fecha ordens totalmente preenchidas
        db["market_orders"].update_many(
            {
                "_id": {"$in": [bid["_id"], ask["_id"]]},
                "$expr": {"$gte": ["$filled", "$quantity"]},
            },
            {"$set": {"status": "filled", "filled_at": datetime.utcnow()}}
        )

        # Registra trade
        db["market_trades"].insert_one({
            "guild_id": guild_id,
            "symbol": symbol,
            "buyer_id": buyer_id,
            "seller_id": seller_id,
            "price": exec_price,
            "quantity": quantity,
            "buy_order_id": str(bid["_id"]),
            "sell_order_id": str(ask["_id"]),
            "timestamp": datetime.utcnow(),
        })

    # ============================================================
    # HOLDINGS (ações / commodities que o user tem)
    # ============================================================

    @classmethod
    def get_holding(cls, guild_id: int, user_id: int, symbol: str) -> int:
        db = get_connection()
        doc = db["market_portfolio"].find_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "symbol": symbol.upper(),
        })
        return int(doc.get("quantity", 0)) if doc else 0

    @classmethod
    def _adjust_holding(
        cls, guild_id: int, user_id: int, symbol: str, delta: int,
        locked: bool = False, release: bool = False
    ) -> None:
        db = get_connection()
        symbol = symbol.upper()
        query = {"guild_id": guild_id, "user_id": user_id, "symbol": symbol}

        if locked and not release:
            db["market_portfolio"].update_one(
                query,
                {"$inc": {"locked": delta}},
                upsert=True,
            )
        elif release:
            db["market_portfolio"].update_one(
                query,
                {"$inc": {"locked": -delta}},
            )
        else:
            db["market_portfolio"].update_one(
                query,
                {"$inc": {"quantity": delta}, "$set": {"updated_at": datetime.utcnow()}},
                upsert=True,
            )

    # ============================================================
    # MARKET MAKER
    # ============================================================

    @classmethod
    def market_maker_tick(cls, guild_id: int) -> int:
        """
        Cria liquidez sintética ao redor do preço spot.
        Chamado pelo tick.
        """
        config = cls.get_config(guild_id)
        if not config.get("enable_market_maker", True):
            return 0

        # Símbolos conhecidos (stocks + commodities)
        db = get_connection()
        symbols = set()
        for s in db["market_stocks"].find({"guild_id": guild_id}, {"symbol": 1}):
            symbols.add(s["symbol"])
        for c in db["commodities"].find({"guild_id": guild_id}, {"symbol": 1}):
            symbols.add(c["symbol"])

        created = 0
        for symbol in symbols:
            spot = cls.get_spot_price(guild_id, symbol)
            if spot <= 0:
                continue

            spread_pct = float(config.get("market_maker_spread_percent", 2.0)) / 100.0
            depth = int(config.get("market_maker_depth", 5))
            size = int(config.get("market_maker_size", 100))

            # Verifica se já tem liquidez suficiente
            open_count = db["market_orders"].count_documents({
                "guild_id": guild_id,
                "symbol": symbol,
                "status": "open",
                "is_mm": True,
            })
            if open_count >= depth * 2:
                continue

            now = datetime.utcnow()
            docs = []

            for level in range(1, depth + 1):
                offset = int(spot * spread_pct * level)
                bid_price = max(1, spot - offset)
                ask_price = spot + offset

                docs.append({
                    "guild_id": guild_id,
                    "user_id": 0,           # 0 = MM
                    "symbol": symbol,
                    "side": "buy",
                    "type": "limit",
                    "price": bid_price,
                    "quantity": size,
                    "filled": 0,
                    "status": "open",
                    "is_mm": True,
                    "created_at": now,
                })
                docs.append({
                    "guild_id": guild_id,
                    "user_id": 0,
                    "symbol": symbol,
                    "side": "sell",
                    "type": "limit",
                    "price": ask_price,
                    "quantity": size,
                    "filled": 0,
                    "status": "open",
                    "is_mm": True,
                    "created_at": now,
                })

            if docs:
                db["market_orders"].insert_many(docs)
                created += len(docs)

        return created

    # ============================================================
    # PREÇO SPOT
    # ============================================================

    @classmethod
    def get_spot_price(cls, guild_id: int, symbol: str) -> int:
        """Último preço de trade OU mid do book OU preço base."""
        cached = _market_cache.get(f"spot:{guild_id}:{symbol}")
        if cached is not None:
            return cached

        db = get_connection()
        symbol = symbol.upper()

        # 1. Último trade
        last_trade = db["market_trades"].find_one(
            {"guild_id": guild_id, "symbol": symbol},
            sort=[("timestamp", -1)]
        )
        if last_trade:
            price = int(last_trade["price"])
            _market_cache.set(f"spot:{guild_id}:{symbol}", price)
            return price

        # 2. Mid do book
        best_bid = db["market_orders"].find_one(
            {"guild_id": guild_id, "symbol": symbol, "side": "buy", "status": "open"},
            sort=[("price", -1)]
        )
        best_ask = db["market_orders"].find_one(
            {"guild_id": guild_id, "symbol": symbol, "side": "sell", "status": "open"},
            sort=[("price", 1)]
        )
        if best_bid and best_ask:
            price = (int(best_bid["price"]) + int(best_ask["price"])) // 2
            _market_cache.set(f"spot:{guild_id}:{symbol}", price)
            return price

        # 3. Preço base
        stock = db["market_stocks"].find_one({"guild_id": guild_id, "symbol": symbol})
        if stock:
            price = int(stock.get("price", 100))
            _market_cache.set(f"spot:{guild_id}:{symbol}", price)
            return price

        commodity = db["commodities"].find_one({"guild_id": guild_id, "symbol": symbol})
        if commodity:
            price = int(commodity.get("price", 100))
            _market_cache.set(f"spot:{guild_id}:{symbol}", price)
            return price

        return 0

    # ============================================================
    # CONSULTAS
    # ============================================================

    @classmethod
    def get_order_book(cls, guild_id: int, symbol: str, depth: int = 5) -> dict:
        db = get_connection()
        symbol = symbol.upper()

        bids = list(db["market_orders"].find({
            "guild_id": guild_id,
            "symbol": symbol,
            "side": "buy",
            "status": "open",
        }).sort("price", -1).limit(depth))

        asks = list(db["market_orders"].find({
            "guild_id": guild_id,
            "symbol": symbol,
            "side": "sell",
            "status": "open",
        }).sort("price", 1).limit(depth))

        return {
            "symbol": symbol,
            "bids": [{"price": b["price"], "quantity": b["quantity"] - b.get("filled", 0)}
                     for b in bids],
            "asks": [{"price": a["price"], "quantity": a["quantity"] - a.get("filled", 0)}
                     for a in asks],
            "best_bid": bids[0]["price"] if bids else 0,
            "best_ask": asks[0]["price"] if asks else 0,
        }

    @classmethod
    def get_user_orders(cls, guild_id: int, user_id: int) -> List[dict]:
        db = get_connection()
        return list(db["market_orders"].find({
            "guild_id": guild_id,
            "user_id": user_id,
            "status": "open",
        }).sort("created_at", -1))

    @classmethod
    def clear_cache(cls) -> None:
        _market_cache.clear()


async def setup(bot):
    pass