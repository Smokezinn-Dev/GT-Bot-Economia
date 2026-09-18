# ============================================================
# DATABASE.PY - v7.0 (POOL + ÍNDICES + TTL - Fases 1 a 7)
# ============================================================

import time
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, OperationFailure

from config import MONGODB_URL, DB_NAME
from utils import safe_object_id

_MAX_ATTEMPTS = 4
_RETRY_DELAY = 4


def get_mongo_client() -> MongoClient:
    attempt = 0
    last_exc = None
    while attempt < _MAX_ATTEMPTS:
        try:
            client = MongoClient(
                MONGODB_URL,
                serverSelectionTimeoutMS=15000,
                connectTimeoutMS=15000,
                socketTimeoutMS=20000,
                maxPoolSize=5,
                minPoolSize=1,
                maxIdleTimeMS=45000,
                retryWrites=True,
                retryReads=True,
                w="majority",
                appname="GTBot-v7.0",
            )
            client.admin.command("ping")
            return client
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            attempt += 1
            last_exc = e
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_DELAY)
    raise ConnectionError(f"Falha ao conectar MongoDB: {last_exc}")


client = get_mongo_client()
db = client[DB_NAME]


def get_connection():
    return db


def _safe_idx(col, keys, **kwargs):
    try:
        db[col].create_index(keys, **kwargs)
    except Exception:
        pass


def _safe_ttl(col, key, seconds, name):
    try:
        db[col].create_index([(key, ASCENDING)], expireAfterSeconds=seconds,
                             background=True, name=name)
    except Exception:
        pass


def ensure_indexes() -> None:
    try:
        # ============================================================
        # CONTROLE / BRANDING
        # ============================================================
        _safe_idx("control_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_ctrl")
        _safe_idx("branding_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_brand")

        # ============================================================
        # ECONOMIA CORE
        # ============================================================
        _safe_idx("economy_balances", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_bal")
        _safe_idx("economy_balances", [("guild_id", ASCENDING), ("balance", DESCENDING)],
                  background=True, name="idx_bal_rank")
        _safe_idx("economy_transactions",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_tx")
        _safe_idx("economy_transactions", [("guild_id", ASCENDING), ("source", ASCENDING)],
                  background=True, name="idx_tx_src")
        _safe_ttl("economy_transactions", "timestamp", 60 * 60 * 24 * 30, "ttl_tx")
        _safe_idx("economy_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_ecfg")
        _safe_idx("economy_counters", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_counters")
        _safe_idx("economy_daily", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_daily")

        # ============================================================
        # LOJA / INVENTÁRIO
        # ============================================================
        _safe_idx("economy_shop", [("guild_id", ASCENDING), ("name", ASCENDING)],
                  background=True, name="idx_shop")
        _safe_idx("economy_inventory",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("item_id", ASCENDING)],
                  unique=True, background=True, name="idx_inv")
        _safe_idx("economy_purchases",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("purchased_at", DESCENDING)],
                  background=True, name="idx_purch")
        _safe_ttl("economy_purchases", "purchased_at", 60 * 60 * 24 * 90, "ttl_purch")
        _safe_idx("economy_boosts",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("effect", ASCENDING)],
                  unique=True, background=True, name="idx_boost")

        # ============================================================
        # GANHOS / PRESTÍGIO
        # ============================================================
        _safe_idx("earn_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_earn")
        _safe_idx("prestige", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_prest")
        _safe_idx("investments",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("collected", ASCENDING)],
                  background=True, name="idx_invst")

        # ============================================================
        # CONQUISTAS / EVENTOS
        # ============================================================
        _safe_idx("achievements", [("guild_id", ASCENDING), ("active", ASCENDING)],
                  background=True, name="idx_ach")
        _safe_idx("user_achievements",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("achievement_id", ASCENDING)],
                  unique=True, background=True, name="idx_uach")
        _safe_idx("events",
                  [("guild_id", ASCENDING), ("active", ASCENDING), ("end_time", ASCENDING)],
                  background=True, name="idx_evt")

        # ============================================================
        # GAMES / GIVEAWAYS
        # ============================================================
        _safe_idx("custom_games", [("guild_id", ASCENDING), ("active", ASCENDING)],
                  background=True, name="idx_games")
        _safe_idx("game_participations",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("played_at", DESCENDING)],
                  background=True, name="idx_gp")
        _safe_ttl("game_participations", "played_at", 60 * 60 * 24 * 60, "ttl_gp")
        _safe_idx("economy_giveaways",
                  [("guild_id", ASCENDING), ("active", ASCENDING), ("end_time", ASCENDING)],
                  background=True, name="idx_gw")

        # ============================================================
        # STAFF / MODERAÇÃO
        # ============================================================
        _safe_idx("staff_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_stfg")
        _safe_idx("staff_points", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_stpts")
        _safe_idx("staff_actions",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_stact")
        _safe_idx("staff_auto_roles", [("guild_id", ASCENDING), ("points_required", ASCENDING)],
                  background=True, name="idx_star")
        _safe_idx("warns", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  background=True, name="idx_warns")
        _safe_idx("punishments",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_pun")
        _safe_idx("blocked_words", [("guild_id", ASCENDING), ("word", ASCENDING)],
                  unique=True, background=True, name="idx_bwords")
        _safe_idx("whitelist", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_wl")
        _safe_idx("guild_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_gcfg")

        # ============================================================
        # AUTOMOD / ANTINUKE
        # ============================================================
        _safe_idx("automod_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_amcfg")
        _safe_idx("automod_infractions",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_aminf")
        _safe_ttl("automod_infractions", "timestamp", 60 * 60 * 24 * 7, "ttl_aminf")
        _safe_idx("antinuke_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_ancfg")
        _safe_idx("antinuke_logs", [("guild_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_anlog")
        _safe_ttl("antinuke_logs", "timestamp", 60 * 60 * 24 * 14, "ttl_anlog")

        # ============================================================
        # MODERAÇÃO / CASES
        # ============================================================
        _safe_idx("mod_cases", [("guild_id", ASCENDING), ("case_id", ASCENDING)],
                  unique=True, background=True, name="idx_case")
        _safe_idx("mod_cases",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_case_usr")
        _safe_idx("user_notes", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  background=True, name="idx_notes")
        _safe_idx("appeals", [("guild_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_appeals")

        # ============================================================
        # BACKUP
        # ============================================================
        _safe_idx("backups", [("guild_id", ASCENDING), ("created_at", DESCENDING)],
                  background=True, name="idx_bkup")
        _safe_idx("backup_texts", [("backup_id", ASCENDING)],
                  background=True, name="idx_bkup_txt")
        _safe_idx("backup_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_bkup_cfg")

        # ============================================================
        # SINKS (leilão, loteria)
        # ============================================================
        _safe_idx("sinks_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_sinks")
        _safe_idx("auctions",
                  [("guild_id", ASCENDING), ("active", ASCENDING), ("end_time", ASCENDING)],
                  background=True, name="idx_auc")
        _safe_idx("lottery_rounds",
                  [("guild_id", ASCENDING), ("active", ASCENDING), ("end_time", ASCENDING)],
                  background=True, name="idx_lot_r")
        _safe_idx("lottery_tickets",
                  [("guild_id", ASCENDING), ("round_id", ASCENDING), ("user_id", ASCENDING)],
                  background=True, name="idx_lot")

        # ============================================================
        # MARKET v6 (legado)
        # ============================================================
        _safe_idx("market_stocks", [("guild_id", ASCENDING), ("symbol", ASCENDING)],
                  unique=True, background=True, name="idx_stock")

        # ============================================================
        # SOCIAL
        # ============================================================
        _safe_idx("guilds_social", [("guild_id", ASCENDING), ("name", ASCENDING)],
                  background=True, name="idx_gsoc")
        _safe_idx("guilds_members", [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_gmem")
        _safe_idx("marriages", [("guild_id", ASCENDING), ("user_a", ASCENDING)],
                  background=True, name="idx_marr_a")
        _safe_idx("marriages", [("guild_id", ASCENDING), ("user_b", ASCENDING)],
                  background=True, name="idx_marr_b")
        _safe_idx("pvp_bets", [("guild_id", ASCENDING), ("created_at", DESCENDING)],
                  background=True, name="idx_pvp")

        # ============================================================
        # MISSÕES
        # ============================================================
        _safe_idx("missions_daily",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("date", ASCENDING)],
                  unique=True, background=True, name="idx_miss")
        _safe_ttl("missions_daily", "expires_at", 60 * 60 * 48, "ttl_miss")

        # ============================================================
        # v7.0 — FASE 1 (Preços, Inflação, Tick)
        # ============================================================
        _safe_idx("price_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_v7_pcfg")
        _safe_idx("price_history",
                  [("guild_id", ASCENDING), ("item_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_phist")
        _safe_ttl("price_history", "timestamp", 60 * 60 * 24 * 30, "ttl_v7_phist")
        _safe_idx("inflation_index",
                  [("guild_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_ipc")
        _safe_ttl("inflation_index", "timestamp", 60 * 60 * 24 * 90, "ttl_v7_ipc")
        _safe_idx("economy_state", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_v7_state")
        _safe_idx("economy_ticks",
                  [("guild_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_ticks")
        _safe_ttl("economy_ticks", "timestamp", 60 * 60 * 24 * 7, "ttl_v7_ticks")
        _safe_idx("president_config",
                  [("guild_id", ASCENDING), ("section", ASCENDING)],
                  unique=True, background=True, name="idx_v7_pres")

        # ============================================================
        # v7.0 — FASE 2 (Empresas, Empregos, Recursos)
        # ============================================================
        _safe_idx("companies", [("guild_id", ASCENDING), ("owner_id", ASCENDING)],
                  background=True, name="idx_v7_comp")
        _safe_idx("companies", [("guild_id", ASCENDING), ("sector", ASCENDING)],
                  background=True, name="idx_v7_comp_sector")
        _safe_idx("company_shares",
                  [("guild_id", ASCENDING), ("company_id", ASCENDING), ("holder_id", ASCENDING)],
                  background=True, name="idx_v7_shares")
        _safe_idx("company_employees",
                  [("guild_id", ASCENDING), ("company_id", ASCENDING), ("user_id", ASCENDING)],
                  background=True, name="idx_v7_emp")
        _safe_idx("company_production",
                  [("guild_id", ASCENDING), ("company_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_prod")
        _safe_ttl("company_production", "timestamp", 60 * 60 * 24 * 30, "ttl_v7_prod")
        _safe_idx("company_financials",
                  [("guild_id", ASCENDING), ("company_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_fin")
        _safe_idx("jobs", [("guild_id", ASCENDING), ("active", ASCENDING)],
                  background=True, name="idx_v7_jobs")
        _safe_idx("job_contracts",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("active", ASCENDING)],
                  background=True, name="idx_v7_jobs_c")
        _safe_idx("resources", [("guild_id", ASCENDING), ("symbol", ASCENDING)],
                  unique=True, background=True, name="idx_v7_res")
        _safe_idx("resource_prices",
                  [("guild_id", ASCENDING), ("symbol", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_res_p")
        _safe_ttl("resource_prices", "timestamp", 60 * 60 * 24 * 30, "ttl_v7_res_p")

        # ============================================================
        # v7.0 — FASE 3 (Crédito, Bancos, BC)
        # ============================================================
        _safe_idx("loans",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_loans")
        _safe_idx("loan_payments",
                  [("guild_id", ASCENDING), ("loan_id", ASCENDING), ("paid_at", DESCENDING)],
                  background=True, name="idx_v7_pay")
        _safe_ttl("loan_payments", "paid_at", 60 * 60 * 24 * 180, "ttl_v7_pay")
        _safe_idx("credit_scores",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  unique=True, background=True, name="idx_v7_score")
        _safe_idx("bank_accounts",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                  background=True, name="idx_v7_bank")
        _safe_idx("central_bank_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_v7_cb")
        _safe_idx("central_bank_ops",
                  [("guild_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_cb_ops")
        _safe_ttl("central_bank_ops", "timestamp", 60 * 60 * 24 * 90, "ttl_v7_cb_ops")

        # ============================================================
        # v7.0 — FASE 4 (Mercado real, Futuros, Commodities)
        # ============================================================
        _safe_idx("market_orders",
                  [("guild_id", ASCENDING), ("symbol", ASCENDING),
                   ("side", ASCENDING), ("price", ASCENDING)],
                  background=True, name="idx_v7_orders")
        _safe_idx("market_orders",
                  [("guild_id", ASCENDING), ("symbol", ASCENDING),
                   ("status", ASCENDING)],
                  background=True, name="idx_v7_orders_status")
        _safe_idx("market_trades",
                  [("guild_id", ASCENDING), ("symbol", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_trades")
        _safe_ttl("market_trades", "timestamp", 60 * 60 * 24 * 90, "ttl_v7_trades")
        _safe_idx("market_portfolio",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("symbol", ASCENDING)],
                  unique=True, background=True, name="idx_v7_port")
        _safe_idx("commodities",
                  [("guild_id", ASCENDING), ("symbol", ASCENDING)],
                  unique=True, background=True, name="idx_v7_comm")
        _safe_idx("commodity_prices",
                  [("guild_id", ASCENDING), ("symbol", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_comm_p")
        _safe_ttl("commodity_prices", "timestamp", 60 * 60 * 24 * 90, "ttl_v7_comm_p")
        _safe_idx("futures_contracts",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_fut")

        # ============================================================
        # v7.0 — FASE 5 (Governo, Políticas, Tesouro)
        # ============================================================
        _safe_idx("government_config", [("guild_id", ASCENDING)], unique=True,
                  background=True, name="idx_v7_gov")
        _safe_idx("government_officials",
                  [("guild_id", ASCENDING), ("role", ASCENDING), ("active", ASCENDING)],
                  background=True, name="idx_v7_gov_off")
        _safe_idx("tax_records",
                  [("guild_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_tax")
        _safe_ttl("tax_records", "timestamp", 60 * 60 * 24 * 90, "ttl_v7_tax")
        _safe_idx("public_spending",
                  [("guild_id", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_spend")
        _safe_ttl("public_spending", "timestamp", 60 * 60 * 24 * 90, "ttl_v7_spend")
        _safe_idx("policies",
                  [("guild_id", ASCENDING), ("active", ASCENDING)],
                  background=True, name="idx_v7_pol")
        _safe_idx("policies",
                  [("guild_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_pol_status")
        _safe_idx("elections",
                  [("guild_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_elec")

        # ============================================================
        # v7.0 — FASE 6 (Inter-Guild)
        # ============================================================
        _safe_idx("currencies",
                  [("guild_id", ASCENDING)],
                  unique=True, background=True, name="idx_v7_cur")
        _safe_idx("exchange_rates",
                  [("from_guild", ASCENDING), ("to_guild", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_fx")
        _safe_ttl("exchange_rates", "timestamp", 60 * 60 * 24 * 30, "ttl_v7_fx")
        _safe_idx("trade_agreements",
                  [("guild_a", ASCENDING), ("guild_b", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_trade")
        _safe_idx("international_transfers",
                  [("from_guild", ASCENDING), ("to_guild", ASCENDING), ("timestamp", DESCENDING)],
                  background=True, name="idx_v7_intl")
        _safe_ttl("international_transfers", "timestamp", 60 * 60 * 24 * 90, "ttl_v7_intl")

        # ============================================================
        # v7.0 — FASE 7 (Imobiliário)
        # ============================================================
        _safe_idx("realestate_regions",
                  [("guild_id", ASCENDING), ("category_id", ASCENDING)],
                  unique=True, background=True, name="idx_v7_region")
        _safe_idx("realestate_lands",
                  [("guild_id", ASCENDING), ("owner_id", ASCENDING)],
                  background=True, name="idx_v7_lands")
        _safe_idx("realestate_lands",
                  [("guild_id", ASCENDING), ("category_id", ASCENDING)],
                  background=True, name="idx_v7_lands_region")
        _safe_idx("realestate_properties",
                  [("guild_id", ASCENDING), ("owner_id", ASCENDING), ("active", ASCENDING)],
                  background=True, name="idx_v7_props")
        _safe_idx("realestate_properties",
                  [("guild_id", ASCENDING), ("rented_to", ASCENDING)],
                  background=True, name="idx_v7_props_rented")
        _safe_idx("realestate_rentals",
                  [("guild_id", ASCENDING), ("status", ASCENDING),
                   ("next_due_at", ASCENDING)],
                  background=True, name="idx_v7_rent")
        _safe_idx("realestate_rentals",
                  [("guild_id", ASCENDING), ("tenant_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_rent_tenant")
        _safe_idx("realestate_rentals",
                  [("guild_id", ASCENDING), ("landlord_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_rent_landlord")
        _safe_idx("realestate_mortgages",
                  [("guild_id", ASCENDING), ("user_id", ASCENDING), ("status", ASCENDING)],
                  background=True, name="idx_v7_mort")
        _safe_idx("realestate_mortgages",
                  [("guild_id", ASCENDING), ("status", ASCENDING),
                   ("next_due_at", ASCENDING)],
                  background=True, name="idx_v7_mort_due")
        _safe_idx("realestate_auctions",
                  [("guild_id", ASCENDING), ("active", ASCENDING), ("ends_at", ASCENDING)],
                  background=True, name="idx_v7_auction")

        print("✅ Índices garantidos (v7.0 Fases 1-7).")
    except Exception as e:
        print(f"⚠️ Erro índices: {e}")


def init_db():
    ensure_indexes()
    return db


def warmup() -> bool:
    try:
        db.command("ping")
        return True
    except Exception:
        return False