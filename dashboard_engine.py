# ============================================================
# DASHBOARD_ENGINE.PY - v7.0 Fase 8 (Dashboard Visual)
# ============================================================
# Responsável por:
#   • Snapshot consolidado da economia
#   • Gráficos ASCII de tendência
#   • Comparativo de períodos
#   • Relatórios automáticos
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database import get_connection
from utils import TTLCache


_dashboard_cache = TTLCache(max_size=100, ttl=30)


# ============================================================
# HELPERS DE GRÁFICO ASCII
# ============================================================

def _sparkline(values: List[float], width: int = 20) -> str:
    """
    Gera uma sparkline ASCII de uma série de valores.
    Ex: ▁▂▃▅▆▇█
    """
    if not values:
        return "─" * width

    chars = "▁▂▃▄▅▆▇█"
    min_v = min(values)
    max_v = max(values)
    span = max_v - min_v

    # Amostra pra caber no width
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = list(values) + [values[-1]] * (width - len(values))

    if span == 0:
        return chars[3] * width

    line = ""
    for v in sampled:
        norm = (v - min_v) / span
        idx = int(norm * (len(chars) - 1))
        line += chars[idx]

    return line


def _bar(value: float, max_value: float, width: int = 15) -> str:
    """Barra horizontal."""
    if max_value <= 0:
        return "░" * width
    filled = int((value / max_value) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _trend_arrow(values: List[float]) -> str:
    """Seta de tendência baseada nos últimos valores."""
    if len(values) < 2:
        return "→"
    first = values[0]
    last = values[-1]
    if last > first * 1.02:
        return "📈"
    if last < first * 0.98:
        return "📉"
    return "➡️"


class DashboardEngine:

    # ============================================================
    # SNAPSHOT GERAL
    # ============================================================

    @classmethod
    def snapshot(cls, guild_id: int) -> dict:
        """Retorna um snapshot consolidado da economia."""
        cached = _dashboard_cache.get(f"snap:{guild_id}")
        if cached is not None:
            return cached

        from commands_economy_core import EconomyManager
        from inflation_engine import InflationEngine
        from currency_engine import CurrencyEngine

        db = get_connection()

        # Moeda
        total_money = EconomyManager.get_total_balance(guild_id)

        # IPC
        try:
            ipc = InflationEngine.calculate_ipc(guild_id)
        except Exception:
            ipc = {"ipc": 0, "index": 100, "status": "unknown"}

        # Câmbio
        try:
            currency = CurrencyEngine.get_currency(guild_id)
        except Exception:
            currency = {"name": "?", "symbol": "?", "rate": 1.0, "confidence": 1.0}

        # PIB
        try:
            gdp = CurrencyEngine.estimate_gdp(guild_id)
        except Exception:
            gdp = total_money

        # Empresas
        total_companies = db["companies"].count_documents({
            "guild_id": guild_id, "active": True
        })

        # Empregos
        total_jobs = db["job_contracts"].count_documents({
            "guild_id": guild_id, "active": True
        })

        # Imóveis
        total_properties = db["realestate_properties"].count_documents({
            "guild_id": guild_id, "active": True
        })

        # Crédito
        total_loans = db["loans"].count_documents({
            "guild_id": guild_id,
            "status": {"$in": ["active", "late"]},
        })
        pipeline = [
            {"$match": {
                "guild_id": guild_id,
                "status": {"$in": ["active", "late"]},
            }},
            {"$group": {
                "_id": None,
                "total": {"$sum": {"$subtract": ["$total_due", "$paid_amount"]}},
            }},
        ]
        loans_agg = list(db["loans"].aggregate(pipeline))
        total_debt = int(loans_agg[0]["total"]) if loans_agg else 0

        # Tesouro
        try:
            from treasury_engine import TreasuryEngine
            treasury = TreasuryEngine.get_balance(guild_id)
        except Exception:
            treasury = 0

        # População (jogadores com saldo > 0)
        population = db["economy_balances"].count_documents({
            "guild_id": guild_id, "balance": {"$gt": 0}
        })

        # Preços (índice)
        price_index = float(ipc.get("index", 100))

        snap = {
            "guild_id": guild_id,
            "total_money": total_money,
            "gdp": gdp,
            "ipc": float(ipc.get("ipc", 0)),
            "ipc_status": ipc.get("status", "unknown"),
            "price_index": price_index,
            "currency": currency,
            "companies": total_companies,
            "jobs": total_jobs,
            "properties": total_properties,
            "loans": total_loans,
            "total_debt": total_debt,
            "treasury": treasury,
            "population": population,
            "timestamp": datetime.utcnow(),
        }
        _dashboard_cache.set(f"snap:{guild_id}", snap)
        return snap

    # ============================================================
    # HISTÓRICO
    # ============================================================

    @classmethod
    def get_money_history(cls, guild_id: int, days: int = 7) -> List[float]:
        """Série histórica de moeda em circulação."""
        db = get_connection()
        cutoff = datetime.utcnow() - timedelta(days=days)
        docs = list(db["economy_ticks"].aggregate([
            {"$match": {
                "guild_id": guild_id,
                "timestamp": {"$gte": cutoff},
            }},
            {"$lookup": {
                "from": "economy_state",
                "localField": "guild_id",
                "foreignField": "guild_id",
                "as": "state",
            }},
            {"$sort": {"timestamp": 1}},
            {"$project": {"_id": 0, "timestamp": 1}},
        ]))
        # Fallback: pega do economy_state
        state = db["economy_state"].find_one({"guild_id": guild_id})
        if not state:
            return []
        # Como economy_state não guarda histórico, fazemos snapshot agora
        return [int(state.get("last_money_snapshot", 0))]

    @classmethod
    def get_inflation_history(cls, guild_id: int, days: int = 7) -> List[float]:
        """Série histórica de inflação."""
        db = get_connection()
        cutoff = datetime.utcnow() - timedelta(days=days)
        docs = list(db["inflation_index"].find({
            "guild_id": guild_id,
            "timestamp": {"$gte": cutoff},
        }).sort("timestamp", 1))
        return [float(d.get("ipc", 0)) * 100 for d in docs]

    @classmethod
    def get_gdp_history(cls, guild_id: int, days: int = 7) -> List[float]:
        """Série histórica de PIB (via snapshot de moeda)."""
        # Não temos histórico direto — usamos economia_state + tick
        # Fallback: usa a inflação histórica pra calcular tendência
        return []

    # ============================================================
    # RELATÓRIOS
    # ============================================================

    @classmethod
    def report(cls, guild_id: int) -> str:
        """Gera relatório textual consolidado."""
        snap = cls.snapshot(guild_id)
        lines = []

        lines.append("=" * 50)
        lines.append("📊 RELATÓRIO ECONÔMICO")
        lines.append("=" * 50)
        lines.append("")

        lines.append(f"💰 Moeda em circulação: {snap['total_money']:,}".replace(",", "."))
        lines.append(f"📈 PIB estimado:       {snap['gdp']:,}".replace(",", "."))
        lines.append(f"📉 IPC atual:          {snap['ipc']*100:+.2f}%")
        lines.append(f"🎯 Status:             {snap['ipc_status'].upper()}")
        lines.append(f"🪙 Moeda:              {snap['currency'].get('name', '?')} "
                     f"({snap['currency'].get('symbol', '?')})")
        lines.append(f"💱 Taxa base:          {snap['currency'].get('rate', 1.0):.4f}")
        lines.append(f"🎯 Confiança:          {snap['currency'].get('confidence', 1.0):.2f}")
        lines.append("")

        lines.append("─" * 50)
        lines.append("SETOR REAL")
        lines.append("─" * 50)
        lines.append(f"🏢 Empresas ativas:    {snap['companies']}")
        lines.append(f"💼 Contratos de trab.: {snap['jobs']}")
        lines.append(f"🏠 Imóveis:            {snap['properties']}")
        lines.append(f"👥 População ativa:    {snap['population']}")
        lines.append("")

        lines.append("─" * 50)
        lines.append("SETOR FINANCEIRO")
        lines.append("─" * 50)
        lines.append(f"💳 Empréstimos:        {snap['loans']}")
        lines.append(f"📊 Dívida total:       {snap['total_debt']:,}".replace(",", "."))
        lines.append(f"💰 Tesouro:            {snap['treasury']:,}".replace(",", "."))
        lines.append("")

        lines.append("=" * 50)
        return "\n".join(lines)

    @classmethod
    def sparklines(cls, guild_id: int) -> dict:
        """Gera sparklines das principais métricas."""
        infl = cls.get_inflation_history(guild_id, days=7)
        money = cls.get_money_history(guild_id, days=7)

        return {
            "inflation": _sparkline(infl) if infl else "─" * 20,
            "inflation_trend": _trend_arrow(infl),
            "money": _sparkline(money) if money else "─" * 20,
            "money_trend": _trend_arrow(money),
        }

    # ============================================================
    # DIAGNÓSTICO
    # ============================================================

    @classmethod
    def diagnose(cls, guild_id: int) -> dict:
        """
        Diagnóstico automático:
        • Saúde econômica
        • Alertas
        • Sugestões
        """
        snap = cls.snapshot(guild_id)
        alerts = []
        suggestions = []
        health = 100

        # Inflação
        ipc_pct = snap["ipc"] * 100
        if ipc_pct > 10:
            alerts.append(f"🚨 Inflação muito alta ({ipc_pct:.1f}%)")
            suggestions.append("Aumente Selic via `.centralbank selic <taxa>`")
            health -= 30
        elif ipc_pct > 5:
            alerts.append(f"⚠️ Inflação alta ({ipc_pct:.1f}%)")
            suggestions.append("Considere aumentar Selic")
            health -= 15
        elif ipc_pct < -5:
            alerts.append(f"⚠️ Deflação ({ipc_pct:.1f}%)")
            suggestions.append("Reduza Selic para estimular economia")
            health -= 10

        # Concentração de moeda
        if snap["total_money"] > 0 and snap["population"] > 0:
            avg = snap["total_money"] / snap["population"]
            if avg > 1_000_000:
                alerts.append(f"⚠️ Muita moeda per capita ({avg:,.0f})".replace(",", "."))
                health -= 5

        # Tesouro
        if snap["treasury"] < 0:
            alerts.append("🚨 Tesouro no negativo")
            suggestions.append("Reduza gastos ou aumente impostos")
            health -= 20

        # Crédito
        if snap["total_debt"] > snap["total_money"] * 2:
            alerts.append("⚠️ Alavancagem alta na economia")
            suggestions.append("Considere aumentar reserva dos bancos")
            health -= 10

        # População
        if snap["population"] < 3:
            alerts.append("⚠️ Poucos jogadores ativos")
            health -= 5

        health = max(0, min(100, health))

        # Classificação
        if health >= 80:
            status = "🌟 Saudável"
            color = "green"
        elif health >= 60:
            status = "👍 Estável"
            color = "blue"
        elif health >= 40:
            status = "😐 Atenção"
            color = "yellow"
        else:
            status = "🚨 Crítica"
            color = "red"

        return {
            "health": health,
            "status": status,
            "color": color,
            "alerts": alerts,
            "suggestions": suggestions,
            "snapshot": snap,
        }

    # ============================================================
    # COMPARATIVO
    # ============================================================

    @classmethod
    def compare_periods(cls, guild_id: int, hours: int = 24) -> dict:
        """
        Compara métricas entre "agora" e "N horas atrás".
        """
        db = get_connection()
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Ticks do período
        ticks = db["economy_ticks"].count_documents({
            "guild_id": guild_id,
            "timestamp": {"$gte": cutoff},
        })

        # Transações
        tx_count = db["economy_transactions"].count_documents({
            "guild_id": guild_id,
            "timestamp": {"$gte": cutoff},
        })

        # Empréstimos novos
        new_loans = db["loans"].count_documents({
            "guild_id": guild_id,
            "created_at": {"$gte": cutoff},
        })

        # Imóveis vendidos
        sold_props = db["realestate_properties"].count_documents({
            "guild_id": guild_id,
            "sold_at": {"$gte": cutoff},
        })

        return {
            "ticks": ticks,
            "transactions": tx_count,
            "new_loans": new_loans,
            "sold_properties": sold_props,
            "period_hours": hours,
        }

    @classmethod
    def clear_cache(cls) -> None:
        _dashboard_cache.clear()


async def setup(bot):
    pass