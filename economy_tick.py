# ============================================================
# ECONOMY_TICK.PY - v7.0 (Motor Central - Fases 1 a 7)
# ============================================================
# 17 passos:
#   1.  Snapshot de moeda
#   2.  Inflação (IPC)
#   3.  Preços da loja
#   4.  Estado geral
#   5.  Recursos (Fase 2)
#   6.  Empresas (Fase 2)
#   7.  Salários (Fase 2)
#   8.  Crédito / calotes (Fase 3)
#   9.  Bancos + Selic (Fase 3)
#  10.  Commodities (Fase 4)
#  11.  Market maker + futuros (Fase 4)
#  12.  Governo (Fase 5)
#  13.  Câmbio (Fase 6)
#  14.  Tratados (Fase 6)
#  15.  Regiões + aluguel (Fase 7)
#  16.  Financiamento + leilões (Fase 7)
#  17.  Log
# ============================================================

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict

from discord.ext import commands, tasks

from database import get_connection
from utils import memory_guard
from price_engine import PriceEngine
from inflation_engine import InflationEngine
from resource_engine import ResourceEngine
from company_engine import CompanyEngine
from job_engine import JobEngine
from credit_engine import CreditEngine
from bank_engine import BankEngine
from central_bank import CentralBank
from market_engine import MarketEngine
from commodity_engine import CommodityEngine
from futures_engine import FuturesEngine
from political_engine import PoliticalEngine
from policy_engine import PolicyEngine
from tax_engine import TaxEngine
from currency_engine import CurrencyEngine
from diplomacy_engine import DiplomacyEngine
from realestate_engine import RealEstateEngine
from rent_engine import RentEngine
from mortgage_engine import MortgageEngine


DEFAULT_TICK_CONFIG = {
    "interval_minutes": 5,
    "enabled": True,
    "adjust_shop_prices": True,
    "update_inflation": True,
    "update_resources": True,
    "process_companies": True,
    "pay_salaries": True,
    "process_credit": True,
    "process_banks": True,
    "update_commodities": True,
    "process_market": True,
    "process_government": True,
    "update_currencies": True,
    "process_treaties": True,
    "process_realestate": True,
    "process_mortgages": True,
    "reset_baseline_days": 30,
    "log_ticks": True,
    "log_retention_days": 7,
    "max_guilds_per_cycle": 50,
    "step_yield_seconds": 0.05,
}


class TickConfig:
    _cache: Dict[int, dict] = {}

    @classmethod
    def get(cls, guild_id: int) -> dict:
        if guild_id in cls._cache:
            return cls._cache[guild_id]
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "tick"}, {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_TICK_CONFIG, **(doc.get("config") or {})}
        cls._cache[guild_id] = config
        return config

    @classmethod
    def update(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "tick"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        cls._cache.pop(guild_id, None)

    @classmethod
    def invalidate(cls, guild_id: int) -> None:
        cls._cache.pop(guild_id, None)


class EconomyTick(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_tick: Dict[int, float] = {}
        self._tick_count: Dict[int, int] = {}
        self._last_daily_pay: Dict[int, float] = {}
        self._last_treaty_expire: float = 0.0
        self.tick_loop.start()

    def cog_unload(self):
        self.tick_loop.cancel()

    @tasks.loop(minutes=5)
    async def tick_loop(self):
        try:
            if memory_guard(380.0):
                return

            now = time.time()
            processed = 0

            if now - self._last_treaty_expire > 3600:
                try:
                    DiplomacyEngine.expire_treaties()
                    self._last_treaty_expire = now
                except Exception as e:
                    print(f"⚠️ Expire treaties: {e}")

            for guild in self.bot.guilds:
                try:
                    cfg = TickConfig.get(guild.id)
                    if not cfg.get("enabled", True):
                        continue

                    interval = int(cfg.get("interval_minutes", 5)) * 60
                    last = self._last_tick.get(guild.id, 0)
                    if now - last < interval:
                        continue

                    await self._run_tick_for_guild(guild.id, cfg)
                    self._last_tick[guild.id] = now
                    self._tick_count[guild.id] = self._tick_count.get(guild.id, 0) + 1
                    processed += 1

                    if processed >= int(cfg.get("max_guilds_per_cycle", 50)):
                        break

                    await asyncio.sleep(float(cfg.get("step_yield_seconds", 0.05)))

                except Exception as e:
                    print(f"⚠️ Tick guild {guild.id}: {e}")
                    continue

        except Exception as e:
            print(f"⚠️ Tick loop erro: {e}")

    @tick_loop.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(30)

    # ============================================================
    # EXECUÇÃO POR GUILD
    # ============================================================

    async def _run_tick_for_guild(self, guild_id: int, cfg: dict) -> None:
        start = time.perf_counter()
        db = get_connection()
        guild = self.bot.get_guild(guild_id)

        steps_done = []
        errors = []

        # --- 1. Snapshot ---
        try:
            await self._step_money_snapshot(guild_id)
            steps_done.append("money")
        except Exception as e:
            errors.append(f"money: {e}")

        # --- 2. Inflação ---
        if cfg.get("update_inflation", True):
            try:
                await self._step_inflation(guild_id)
                steps_done.append("inflation")
            except Exception as e:
                errors.append(f"inflation: {e}")

        # --- 3. Preços loja ---
        if cfg.get("adjust_shop_prices", True):
            try:
                await self._step_shop_prices(guild_id)
                steps_done.append("shop_prices")
            except Exception as e:
                errors.append(f"shop_prices: {e}")

        # --- 4. Estado ---
        try:
            await self._step_state(guild_id)
            steps_done.append("state")
        except Exception as e:
            errors.append(f"state: {e}")

        # --- 5. Recursos ---
        if cfg.get("update_resources", True):
            try:
                await self._step_resources(guild_id)
                steps_done.append("resources")
            except Exception as e:
                errors.append(f"resources: {e}")

        # --- 6. Empresas ---
        if cfg.get("process_companies", True):
            try:
                await self._step_companies(guild_id)
                steps_done.append("companies")
            except Exception as e:
                errors.append(f"companies: {e}")

        # --- 7. Salários ---
        if cfg.get("pay_salaries", True):
            try:
                await self._step_salaries(guild_id)
                steps_done.append("salaries")
            except Exception as e:
                errors.append(f"salaries: {e}")

        # --- 8. Crédito ---
        if cfg.get("process_credit", True):
            try:
                await self._step_credit(guild_id)
                steps_done.append("credit")
            except Exception as e:
                errors.append(f"credit: {e}")

        # --- 9. Bancos + BC ---
        if cfg.get("process_banks", True):
            try:
                await self._step_banks(guild_id)
                steps_done.append("banks")
            except Exception as e:
                errors.append(f"banks: {e}")

        # --- 10. Commodities ---
        if cfg.get("update_commodities", True):
            try:
                await self._step_commodities(guild_id)
                steps_done.append("commodities")
            except Exception as e:
                errors.append(f"commodities: {e}")

        # --- 11. Market ---
        if cfg.get("process_market", True):
            try:
                await self._step_market(guild_id)
                steps_done.append("market")
            except Exception as e:
                errors.append(f"market: {e}")

        # --- 12. Governo ---
        if cfg.get("process_government", True):
            try:
                await self._step_government(guild_id)
                steps_done.append("government")
            except Exception as e:
                errors.append(f"government: {e}")

        # --- 13. Câmbio ---
        if cfg.get("update_currencies", True):
            try:
                await self._step_currencies(guild_id)
                steps_done.append("currencies")
            except Exception as e:
                errors.append(f"currencies: {e}")

        # --- 14. Tratados ---
        if cfg.get("process_treaties", True):
            try:
                await self._step_treaties(guild_id)
                steps_done.append("treaties")
            except Exception as e:
                errors.append(f"treaties: {e}")

        # --- 15. Realestate (regiões + aluguel) ---
        if cfg.get("process_realestate", True):
            try:
                await self._step_realestate(guild_id, guild)
                steps_done.append("realestate")
            except Exception as e:
                errors.append(f"realestate: {e}")

        # --- 16. Financiamento + leilões ---
        if cfg.get("process_mortgages", True):
            try:
                await self._step_mortgages(guild_id)
                steps_done.append("mortgages")
            except Exception as e:
                errors.append(f"mortgages: {e}")

        # --- 17. Log ---
        if cfg.get("log_ticks", True):
            try:
                elapsed = (time.perf_counter() - start) * 1000
                db["economy_ticks"].insert_one({
                    "guild_id": guild_id,
                    "timestamp": datetime.utcnow(),
                    "steps": steps_done,
                    "errors": errors,
                    "duration_ms": round(elapsed, 1),
                })
            except Exception:
                pass

    # ============================================================
    # PASSOS — FASE 1
    # ============================================================

    async def _step_money_snapshot(self, guild_id: int) -> None:
        from commands_economy_core import EconomyManager
        total = EconomyManager.get_total_balance(guild_id)
        db = get_connection()
        db["economy_state"].update_one(
            {"guild_id": guild_id},
            {
                "$set": {
                    "last_money_snapshot": total,
                    "last_snapshot_at": datetime.utcnow(),
                },
                "$setOnInsert": {
                    "baseline_money": total,
                    "baseline_production": 1.0,
                    "created_at": datetime.utcnow(),
                },
            },
            upsert=True,
        )

    async def _step_inflation(self, guild_id: int) -> None:
        InflationEngine.calculate_ipc(guild_id)

    async def _step_shop_prices(self, guild_id: int) -> None:
        from commands_economy_core import EconomyManager
        from pymongo import UpdateOne
        db = get_connection()
        total_money = EconomyManager.get_total_balance(guild_id)
        items = list(db["economy_shop"].find(
            {"guild_id": guild_id, "active": {"$ne": False}},
            {"_id": 1, "price": 1, "base_price": 1, "stock": 1, "item_type": 1}
        ).limit(200))
        if not items:
            return
        ops = []
        for item in items:
            item_id = str(item["_id"])
            base = item.get("base_price") or item.get("price", 0)
            current = item.get("price", base)
            stock = item.get("stock", -1)
            if base <= 0:
                continue
            anchor = PriceEngine.get_anchor_price(guild_id, item_id)
            if anchor is not None:
                target = anchor
            else:
                target = PriceEngine.calculate_price(
                    guild_id, base_price=base, demand=1.0, supply=1.0,
                    stock=stock, money_supply=total_money,
                )
            new_price = PriceEngine.adjust_existing_price(
                guild_id, item_id, current, base, target
            )
            if new_price != current:
                ops.append(UpdateOne(
                    {"_id": item["_id"]},
                    {"$set": {
                        "price": new_price,
                        "base_price": base,
                        "last_price_change": datetime.utcnow(),
                    }}
                ))
                PriceEngine.record_price_history(guild_id, item_id, new_price, base)
        if ops:
            try:
                db["economy_shop"].bulk_write(ops, ordered=False)
            except Exception as e:
                print(f"⚠️ Bulk shop update: {e}")

    async def _step_state(self, guild_id: int) -> None:
        InflationEngine.update_economy_state(guild_id)

    # ============================================================
    # PASSOS — FASE 2
    # ============================================================

    async def _step_resources(self, guild_id: int) -> None:
        ResourceEngine.ensure_resources(guild_id)
        ResourceEngine.regenerate_all(guild_id)
        ResourceEngine.update_resource_prices(guild_id)

    async def _step_companies(self, guild_id: int) -> None:
        CompanyEngine.process_all_companies(guild_id)

    async def _step_salaries(self, guild_id: int) -> None:
        JobEngine.pay_salaries(guild_id)

    # ============================================================
    # PASSOS — FASE 3
    # ============================================================

    async def _step_credit(self, guild_id: int) -> None:
        CreditEngine.process_loans(guild_id)

    async def _step_banks(self, guild_id: int) -> None:
        BankEngine.process_bank_interest(guild_id)
        ipc = InflationEngine.calculate_ipc(guild_id)
        CentralBank.process_tick(guild_id, ipc.get("ipc", 0.0) * 100)

    # ============================================================
    # PASSOS — FASE 4
    # ============================================================

    async def _step_commodities(self, guild_id: int) -> None:
        CommodityEngine.ensure_commodities(guild_id)
        CommodityEngine.regenerate(guild_id)
        CommodityEngine.update_prices(guild_id)

    async def _step_market(self, guild_id: int) -> None:
        MarketEngine.market_maker_tick(guild_id)
        FuturesEngine.process_tick(guild_id)

    # ============================================================
    # PASSOS — FASE 5
    # ============================================================

    async def _step_government(self, guild_id: int) -> None:
        PolicyEngine.expire_policies(guild_id)
        PoliticalEngine.check_term_expiry(guild_id)

        now = time.time()
        last_pay = self._last_daily_pay.get(guild_id, 0)
        if now - last_pay >= 86400:
            PoliticalEngine.pay_daily_salaries(guild_id)
            self._last_daily_pay[guild_id] = now

        TaxEngine.collect_wealth_tax(guild_id)

    # ============================================================
    # PASSOS — FASE 6
    # ============================================================

    async def _step_currencies(self, guild_id: int) -> None:
        CurrencyEngine.get_currency(guild_id)
        CurrencyEngine.update_all_rates(guild_id)

    async def _step_treaties(self, guild_id: int) -> None:
        DiplomacyEngine.expire_treaties()

    # ============================================================
    # PASSOS — FASE 7
    # ============================================================

    async def _step_realestate(self, guild_id: int, guild) -> None:
        """Cria regiões + cobra aluguéis."""
        if guild:
            RealEstateEngine.ensure_regions(guild, self.bot)
        RentEngine.process_rentals(guild_id)

    async def _step_mortgages(self, guild_id: int) -> None:
        """Processa financiamentos + finaliza leilões."""
        MortgageEngine.process_mortgages(guild_id)

        # Finaliza leilões de execução hipotecária
        cog = self.bot.get_cog("RealEstateCommands")
        if cog and hasattr(cog, "finalize_auctions"):
            cog.finalize_auctions(guild_id)

    # ============================================================
    # UTILITÁRIOS
    # ============================================================

    @classmethod
    def get_tick_count(cls, guild_id: int) -> int:
        db = get_connection()
        return db["economy_ticks"].count_documents({"guild_id": guild_id})

    @classmethod
    def get_last_tick(cls, guild_id: int) -> dict:
        db = get_connection()
        return db["economy_ticks"].find_one(
            {"guild_id": guild_id}, sort=[("timestamp", -1)]
        ) or {}


async def setup(bot):
    if bot.get_cog("EconomyTick") is None:
        await bot.add_cog(EconomyTick(bot))