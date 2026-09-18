# ============================================================
# BALANCE_ENGINE.PY - v7.0 Fase 8 (Diagnóstico e Balanceamento)
# ============================================================
# Responsável por:
#   • Analisar saúde econômica profunda
#   • Detectar desequilíbrios
#   • Sugerir ajustes automáticos
#   • Aplicar "presets" de dificuldade
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_connection
from utils import TTLCache


DEFAULT_BALANCE_CONFIG = {
    "difficulty": "normal",           # easy | normal | hard | brutal
    "auto_balance": False,            # se True, ajusta automaticamente
    "auto_balance_interval_hours": 24,
    "target_inflation": 1.0,
    "target_gdp_growth": 2.0,          # % por dia
    "target_wealth_gap": 10.0,         # razão rico/pobre aceitável
}


# Presets de dificuldade
DIFFICULTY_PRESETS = {
    "easy": {
        "name": "Fácil",
        "emoji": "🟢",
        "description": "Economia generosa, progressão rápida",
        "overrides": {
            "earn": {"per_message_amount": 2},
            "price": {"money_supply_weight": 0.3},
            "credit": {"rate_good": 0.05, "rate_fair": 0.10},
            "taxes": {"income_tax": 0.03, "transfer_tax": 0.01},
        },
    },
    "normal": {
        "name": "Normal",
        "emoji": "🔵",
        "description": "Balanceado (padrão)",
        "overrides": {},   # usa defaults
    },
    "hard": {
        "name": "Difícil",
        "emoji": "🟠",
        "description": "Economia apertada, progressão lenta",
        "overrides": {
            "earn": {"per_message_amount": 1, "message_delay": 12},
            "price": {"money_supply_weight": 0.7},
            "credit": {"rate_good": 0.10, "rate_fair": 0.20},
            "taxes": {"income_tax": 0.08, "transfer_tax": 0.03},
        },
    },
    "brutal": {
        "name": "Brutal",
        "emoji": "🔴",
        "description": "Sobrevivência — só os melhores prosperam",
        "overrides": {
            "earn": {"per_message_amount": 1, "message_delay": 20,
                     "max_messages_per_day": 80},
            "price": {"money_supply_weight": 0.9},
            "credit": {"rate_good": 0.15, "rate_fair": 0.30, "rate_poor": 0.50},
            "taxes": {"income_tax": 0.15, "transfer_tax": 0.05,
                      "wealth_tax": 0.02},
        },
    },
}


_balance_cache = TTLCache(max_size=100, ttl=60)


class BalanceEngine:

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = _balance_cache.get(f"cfg:{guild_id}")
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["president_config"].find_one(
            {"guild_id": guild_id, "section": "balance"},
            {"_id": 0, "config": 1}
        ) or {}
        config = {**DEFAULT_BALANCE_CONFIG, **(doc.get("config") or {})}
        _balance_cache.set(f"cfg:{guild_id}", config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["president_config"].update_one(
            {"guild_id": guild_id, "section": "balance"},
            {"$set": {f"config.{key}": value}},
            upsert=True,
        )
        _balance_cache.invalidate(f"cfg:{guild_id}")

    # ============================================================
    # ANÁLISE PROFUNDA
    # ============================================================

    @classmethod
    def analyze(cls, guild_id: int) -> dict:
        """
        Análise completa de desequilíbrios.
        """
        from dashboard_engine import DashboardEngine
        snap = DashboardEngine.snapshot(guild_id)

        db = get_connection()
        issues = []

        # 1. Inflação
        ipc_pct = snap["ipc"] * 100
        if ipc_pct > 10:
            issues.append({
                "type": "inflation_high",
                "severity": "critical",
                "value": ipc_pct,
                "message": f"Inflação em {ipc_pct:.1f}% (meta: 1%)",
                "fix": "Aumentar Selic",
            })
        elif ipc_pct < -5:
            issues.append({
                "type": "deflation",
                "severity": "warning",
                "value": ipc_pct,
                "message": f"Deflação em {ipc_pct:.1f}%",
                "fix": "Reduzir Selic ou injetar moeda",
            })

        # 2. Concentração de riqueza
        balances = list(db["economy_balances"].find({
            "guild_id": guild_id,
            "balance": {"$gt": 0},
        }).sort("balance", -1))

        if len(balances) >= 10:
            top_10_pct = max(1, len(balances) // 10)
            top_wealth = sum(int(b["balance"]) for b in balances[:top_10_pct])
            total_wealth = sum(int(b["balance"]) for b in balances)
            if total_wealth > 0:
                concentration = (top_wealth / total_wealth) * 100
                if concentration > 70:
                    issues.append({
                        "type": "wealth_concentration",
                        "severity": "warning",
                        "value": concentration,
                        "message": f"Top 10% controla {concentration:.0f}% da riqueza",
                        "fix": "Aumentar imposto de riqueza",
                    })

        # 3. Atividade econômica
        from dashboard_engine import DashboardEngine as DE
        compare = DE.compare_periods(guild_id, hours=24)
        if compare["ticks"] < 10:
            issues.append({
                "type": "low_activity",
                "severity": "info",
                "value": compare["ticks"],
                "message": f"Poucos ticks nas últimas 24h ({compare['ticks']})",
                "fix": "Verificar se o tick está rodando",
            })

        # 4. Desemprego
        total_pop = snap["population"]
        if total_pop > 0:
            unemployment = 1 - (snap["jobs"] / total_pop)
            if unemployment > 0.7:
                issues.append({
                    "type": "high_unemployment",
                    "severity": "warning",
                    "value": unemployment * 100,
                    "message": f"Desemprego em {unemployment*100:.0f}%",
                    "fix": "Incentivar criação de empresas/empregos",
                })

        # 5. Crédito
        if snap["total_debt"] > snap["total_money"]:
            issues.append({
                "type": "high_leverage",
                "severity": "warning",
                "value": snap["total_debt"],
                "message": "Dívida total maior que moeda em circulação",
                "fix": "Aumentar reserva dos bancos",
            })

        # Classificação geral
        critical = sum(1 for i in issues if i["severity"] == "critical")
        warnings = sum(1 for i in issues if i["severity"] == "warning")

        if critical > 0:
            overall = "critical"
        elif warnings > 2:
            overall = "warning"
        elif warnings > 0:
            overall = "attention"
        else:
            overall = "healthy"

        return {
            "overall": overall,
            "issues": issues,
            "count_critical": critical,
            "count_warning": warnings,
            "snapshot": snap,
        }

    # ============================================================
    # PRESETS
    # ============================================================

    @classmethod
    def list_presets(cls) -> dict:
        return DIFFICULTY_PRESETS

    @classmethod
    def apply_preset(cls, guild_id: int, preset_name: str) -> dict:
        """
        Aplica um preset de dificuldade na guild.
        Sobrescreve configs específicas.
        """
        preset = DIFFICULTY_PRESETS.get(preset_name)
        if not preset:
            return {"error": "invalid_preset",
                    "valid": list(DIFFICULTY_PRESETS.keys())}

        overrides = preset.get("overrides", {})
        applied = 0

        db = get_connection()
        for section, values in overrides.items():
            for key, value in values.items():
                try:
                    db["president_config"].update_one(
                        {"guild_id": guild_id, "section": section},
                        {"$set": {f"config.{key}": value}},
                        upsert=True,
                    )
                    applied += 1
                except Exception:
                    continue

        # Salva preset atual
        cls.update_config(guild_id, "difficulty", preset_name)

        # Invalida caches
        cls._invalidate_all_caches()

        return {
            "ok": True,
            "preset": preset_name,
            "applied": applied,
            "name": preset["name"],
            "emoji": preset["emoji"],
        }

    @classmethod
    def _invalidate_all_caches(cls) -> None:
        """Invalida caches de todas as engines pra forçar reload."""
        try:
            from price_engine import PriceEngine
            PriceEngine.clear_cache()
        except Exception:
            pass
        try:
            from inflation_engine import InflationEngine
            InflationEngine.clear_cache()
        except Exception:
            pass
        try:
            from company_engine import CompanyEngine
            CompanyEngine.clear_cache()
        except Exception:
            pass
        try:
            from credit_engine import CreditEngine
            CreditEngine.clear_cache()
        except Exception:
            pass
        try:
            from bank_engine import BankEngine
            BankEngine.clear_cache()
        except Exception:
            pass
        try:
            from central_bank import CentralBank
            CentralBank.clear_cache()
        except Exception:
            pass
        try:
            from market_engine import MarketEngine
            MarketEngine.clear_cache()
        except Exception:
            pass
        try:
            from commodity_engine import CommodityEngine
            CommodityEngine.clear_cache()
        except Exception:
            pass
        try:
            from futures_engine import FuturesEngine
            FuturesEngine.clear_cache()
        except Exception:
            pass
        try:
            from political_engine import PoliticalEngine
            PoliticalEngine.clear_cache()
        except Exception:
            pass
        try:
            from policy_engine import PolicyEngine
            PolicyEngine.clear_cache()
        except Exception:
            pass
        try:
            from tax_engine import TaxEngine
            TaxEngine.clear_cache()
        except Exception:
            pass
        try:
            from treasury_engine import TreasuryEngine
            TreasuryEngine.clear_cache()
        except Exception:
            pass
        try:
            from currency_engine import CurrencyEngine
            CurrencyEngine.clear_cache()
        except Exception:
            pass
        try:
            from diplomacy_engine import DiplomacyEngine
            DiplomacyEngine.clear_cache()
        except Exception:
            pass
        try:
            from trade_engine import TradeEngine
            TradeEngine.clear_cache()
        except Exception:
            pass
        try:
            from realestate_engine import RealEstateEngine
            RealEstateEngine.clear_cache()
        except Exception:
            pass
        try:
            from rent_engine import RentEngine
            RentEngine.clear_cache()
        except Exception:
            pass
        try:
            from mortgage_engine import MortgageEngine
            MortgageEngine.clear_cache()
        except Exception:
            pass
        _balance_cache.clear()

    # ============================================================
    # STRESS TEST
    # ============================================================

    @classmethod
    def stress_test(cls, guild_id: int, iterations: int = 100) -> dict:
        """
        Simula N operações e mede tempo. Não afeta dados reais.
        """
        import time
        from price_engine import PriceEngine
        from inflation_engine import InflationEngine

        results = {
            "iterations": iterations,
            "price_calc": 0.0,
            "inflation_calc": 0.0,
            "total": 0.0,
            "errors": 0,
        }

        # 1. Price calc
        start = time.perf_counter()
        for i in range(iterations):
            try:
                PriceEngine.calculate_price(
                    guild_id, base_price=100, demand=1.0, supply=1.0,
                    stock=100, money_supply=1_000_000,
                )
            except Exception:
                results["errors"] += 1
        results["price_calc"] = (time.perf_counter() - start) * 1000

        # 2. Inflation calc
        start = time.perf_counter()
        for i in range(min(iterations, 20)):   # inflação é mais pesada
            try:
                InflationEngine.calculate_ipc(guild_id)
            except Exception:
                results["errors"] += 1
        results["inflation_calc"] = (time.perf_counter() - start) * 1000

        results["total"] = results["price_calc"] + results["inflation_calc"]

        # Avaliação
        avg_price = results["price_calc"] / max(1, iterations)
        if avg_price < 1:
            results["verdict"] = "🚀 Excelente (<1ms/op)"
        elif avg_price < 5:
            results["verdict"] = "✅ Bom (<5ms/op)"
        elif avg_price < 20:
            results["verdict"] = "⚠️ Aceitável (<20ms/op)"
        else:
            results["verdict"] = "🚨 Lento (>20ms/op)"

        return results

    @classmethod
    def clear_cache(cls) -> None:
        _balance_cache.clear()


async def setup(bot):
    pass