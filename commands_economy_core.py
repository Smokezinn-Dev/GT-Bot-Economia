# ============================================================
# COMMANDS_ECONOMY_CORE.PY - v7.0 (prefixo .)
# ============================================================
# Integra Fase 5: cobrança de imposto de transferência via TaxEngine.
# Se TaxEngine falhar (Fase 5 não instalada), o .pay continua funcionando
# sem a cobrança — proteção contra dependência circular.
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from utils import TTLCache, retry_mongo, SlashCtxAdapter


class EconomyManager:
    _config_cache = TTLCache(max_size=100, ttl=120)
    _balance_cache = TTLCache(max_size=600, ttl=15)

    DEFAULT_CONFIG = {
        "currency_name": "Moeda",
        "currency_emoji": "💰",
        "daily_bonus": 100,
        "staff_role": 0,
        "log_channel": 0,
        "tax_rate": 0,
        "min_transfer": 1,
        "max_transfer": 1_000_000,
        "bonus_multiplier": 1.0,
        "economy_frozen": False,
        "frozen_users": [],
    }

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = cls._config_cache.get(guild_id)
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["economy_config"].find_one({"guild_id": guild_id}, {"_id": 0})
        config = {**cls.DEFAULT_CONFIG, **(doc or {})}
        cls._config_cache.set(guild_id, config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["economy_config"].update_one(
            {"guild_id": guild_id}, {"$set": {key: value}}, upsert=True)
        cls._config_cache.invalidate(guild_id)

    @classmethod
    def get_balance(cls, guild_id: int, user_id: int) -> int:
        key = f"{guild_id}:{user_id}"
        cached = cls._balance_cache.get(key)
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["economy_balances"].find_one(
            {"guild_id": guild_id, "user_id": user_id}, {"balance": 1})
        balance = int(doc["balance"]) if doc and "balance" in doc else 0
        cls._balance_cache.set(key, balance)
        return balance

    @classmethod
    def _invalidate_balance(cls, guild_id: int, user_id: int) -> None:
        cls._balance_cache.invalidate(f"{guild_id}:{user_id}")

    @classmethod
    @retry_mongo(attempts=3)
    def set_balance(cls, guild_id: int, user_id: int, amount: int) -> int:
        amount = max(0, int(amount))
        db = get_connection()
        db["economy_balances"].update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$set": {"balance": amount, "updated_at": datetime.utcnow()}},
            upsert=True)
        cls._invalidate_balance(guild_id, user_id)
        return amount

    @classmethod
    @retry_mongo(attempts=3)
    def add_balance(cls, guild_id: int, user_id: int, amount: int,
                    description: str = "", source: str = "system") -> int:
        if amount == 0:
            return cls.get_balance(guild_id, user_id)
        if amount < 0:
            cls.remove_balance(guild_id, user_id, -amount, description, source)
            return cls.get_balance(guild_id, user_id)
        db = get_connection()
        result = db["economy_balances"].find_one_and_update(
            {"guild_id": guild_id, "user_id": user_id},
            {
                "$inc": {"balance": int(amount)},
                "$set": {"updated_at": datetime.utcnow()},
                "$setOnInsert": {"guild_id": guild_id, "user_id": user_id}
            },
            upsert=True, return_document=True)
        new_balance = int(result.get("balance", amount)) if result else amount
        cls._invalidate_balance(guild_id, user_id)
        try:
            db["economy_transactions"].insert_one({
                "guild_id": guild_id, "user_id": user_id,
                "type": "add", "amount": int(amount),
                "description": description[:200], "source": source,
                "balance_after": new_balance,
                "timestamp": datetime.utcnow()
            })
        except Exception:
            pass
        return new_balance

    @classmethod
    @retry_mongo(attempts=3)
    def remove_balance(cls, guild_id: int, user_id: int, amount: int,
                       description: str = "", source: str = "system") -> bool:
        amount = int(amount)
        if amount <= 0:
            return False
        db = get_connection()
        result = db["economy_balances"].find_one_and_update(
            {"guild_id": guild_id, "user_id": user_id, "balance": {"$gte": amount}},
            {"$inc": {"balance": -amount}, "$set": {"updated_at": datetime.utcnow()}},
            return_document=True)
        if result is None:
            cls.get_balance(guild_id, user_id)
            return False
        new_balance = int(result.get("balance", 0))
        cls._invalidate_balance(guild_id, user_id)
        try:
            db["economy_transactions"].insert_one({
                "guild_id": guild_id, "user_id": user_id,
                "type": "remove", "amount": amount,
                "description": description[:200], "source": source,
                "balance_after": new_balance,
                "timestamp": datetime.utcnow()
            })
        except Exception:
            pass
        return True

    @classmethod
    def increment_counter(cls, guild_id: int, user_id: int, counter: str, amount: int = 1):
        if amount <= 0:
            return
        db = get_connection()
        db["economy_counters"].update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$inc": {counter: amount}, "$set": {"updated_at": datetime.utcnow()}},
            upsert=True
        )

    @classmethod
    def get_counter(cls, guild_id: int, user_id: int, counter: str) -> int:
        db = get_connection()
        doc = db["economy_counters"].find_one(
            {"guild_id": guild_id, "user_id": user_id}, {counter: 1})
        return int(doc.get(counter, 0)) if doc else 0

    @classmethod
    def transfer(cls, guild_id: int, from_user: int, to_user: int,
                 amount: int, description: str = "") -> bool:
        amount = int(amount)
        if amount <= 0 or from_user == to_user:
            return False
        config = cls.get_config(guild_id)
        min_t = config.get("min_transfer", 1)
        max_t = config.get("max_transfer", 1_000_000)
        if amount < min_t or amount > max_t:
            return False
        if cls.is_frozen(guild_id, from_user) or cls.is_frozen(guild_id, to_user):
            return False

        tax_rate = float(config.get("tax_rate", 0))
        tax = int(amount * tax_rate / 100)
        final = amount - tax

        if not cls.remove_balance(guild_id, from_user, amount,
                                  description or f"Transferência para {to_user}", "transfer"):
            return False

        try:
            cls.add_balance(guild_id, to_user, final,
                            description or f"Transferência de {from_user}", "transfer")
        except Exception:
            try:
                cls.add_balance(guild_id, from_user, amount,
                                "Rollback: falha na transferência", "transfer_rollback")
            except Exception:
                pass
            return False

        try:
            db = get_connection()
            db["economy_transactions"].insert_one({
                "guild_id": guild_id, "user_id": from_user, "target_user_id": to_user,
                "type": "transfer", "amount": amount, "tax": tax, "final_amount": final,
                "description": description[:200] if description else f"para {to_user}",
                "source": "transfer", "timestamp": datetime.utcnow()
            })
            cls.increment_counter(guild_id, from_user, "transfers_sent", 1)
            cls.increment_counter(guild_id, to_user, "transfers_received", 1)
        except Exception:
            pass
        return True

    @classmethod
    def is_frozen(cls, guild_id: int, user_id: int = None) -> bool:
        config = cls.get_config(guild_id)
        if config.get("economy_frozen", False):
            return True
        if user_id is not None:
            return user_id in config.get("frozen_users", [])
        return False

    @classmethod
    def freeze_user(cls, guild_id: int, user_id: int) -> None:
        config = cls.get_config(guild_id)
        frozen = list(config.get("frozen_users", []))
        if user_id not in frozen:
            frozen.append(user_id)
            cls.update_config(guild_id, "frozen_users", frozen)

    @classmethod
    def unfreeze_user(cls, guild_id: int, user_id: int) -> None:
        config = cls.get_config(guild_id)
        frozen = [u for u in config.get("frozen_users", []) if u != user_id]
        cls.update_config(guild_id, "frozen_users", frozen)

    @classmethod
    def freeze_guild(cls, guild_id: int, frozen: bool = True) -> None:
        cls.update_config(guild_id, "economy_frozen", frozen)

    @classmethod
    def get_ranking(cls, guild_id: int, limit: int = 20) -> List[Tuple[int, int]]:
        db = get_connection()
        docs = list(db["economy_balances"].find(
            {"guild_id": guild_id, "balance": {"$gt": 0}},
            {"user_id": 1, "balance": 1}
        ).sort("balance", -1).limit(limit))
        return [(d["user_id"], int(d["balance"])) for d in docs]

    @classmethod
    def get_total_balance(cls, guild_id: int) -> int:
        db = get_connection()
        result = list(db["economy_balances"].aggregate([
            {"$match": {"guild_id": guild_id}},
            {"$group": {"_id": None, "total": {"$sum": "$balance"}}}
        ]))
        return int(result[0]["total"]) if result else 0

    @classmethod
    def format_currency(cls, guild_id: int, amount: int) -> str:
        config = cls.get_config(guild_id)
        emoji = config.get("currency_emoji", "💰")
        name = config.get("currency_name", "Moeda")
        return f"{emoji} {amount:,} {name}".replace(",", ".")

    @classmethod
    def clear_caches(cls) -> None:
        cls._config_cache.clear()
        cls._balance_cache.clear()


class EconomyCore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _format(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # BALANCE
    # ============================================================

    @commands.command(name="balance", aliases=["bal", "money", "saldo"])
    async def balance(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        balance = EconomyManager.get_balance(ctx.guild.id, member.id)
        embed = discord.Embed(
            title=f"💰 Saldo de {member.display_name}",
            description=f"**{self._format(ctx.guild.id, balance)}**",
            color=member.color or discord.Color.gold(),
            timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        if EconomyManager.is_frozen(ctx.guild.id, member.id):
            embed.set_footer(text="⚠️ Economia congelada")
        await ctx.send(embed=embed)

    @app_commands.command(name="balance", description="Mostra o saldo de um usuário")
    @app_commands.describe(member="Usuário (opcional)")
    async def balance_slash(self, interaction: discord.Interaction,
                            member: Optional[discord.Member] = None):
        member = member or interaction.user
        balance = EconomyManager.get_balance(interaction.guild.id, member.id)
        embed = discord.Embed(
            title=f"💰 Saldo de {member.display_name}",
            description=f"**{self._format(interaction.guild.id, balance)}**",
            color=member.color or discord.Color.gold(),
            timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ============================================================
    # DAILY
    # ============================================================

    @commands.command(name="daily")
    async def daily(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        config = EconomyManager.get_config(guild_id)
        db = get_connection()

        doc = db["economy_daily"].find_one(
            {"guild_id": guild_id, "user_id": user_id}, {"last_daily": 1})

        now = datetime.utcnow()
        if doc and doc.get("last_daily"):
            last = doc["last_daily"]
            if isinstance(last, str):
                try:
                    last = datetime.fromisoformat(last.replace("Z", "+00:00"))
                except Exception:
                    last = None
            if last and last.date() == now.date():
                next_d = (last + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0)
                remaining = next_d - now
                h, r = divmod(max(0, int(remaining.total_seconds())), 3600)
                m = r // 60
                return await ctx.send(embed=embed_warning(
                    f"⏳ Já coletou hoje.\nVolte em **{h}h {m}min**."))

        bonus = int(config.get("daily_bonus", 100) * float(config.get("bonus_multiplier", 1.0)))
        new_balance = EconomyManager.add_balance(
            guild_id, user_id, bonus, "Bônus diário", "daily")

        db["economy_daily"].update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$set": {"last_daily": now}, "$inc": {"total_dailies": 1}},
            upsert=True)
        EconomyManager._invalidate_balance(guild_id, user_id)
        EconomyManager.increment_counter(guild_id, user_id, "dailies_collected", 1)

        embed = discord.Embed(
            title="🎉 Bônus Diário!",
            description=f"Você recebeu **{self._format(guild_id, bonus)}**!",
            color=discord.Color.green(), timestamp=now)
        embed.add_field(name="💰 Saldo atual", value=self._format(guild_id, new_balance))
        await ctx.send(embed=embed)

    @app_commands.command(name="daily", description="Coleta o bônus diário")
    async def daily_slash(self, interaction: discord.Interaction):
        await self.daily(SlashCtxAdapter(interaction))

    # ============================================================
    # PAY (com imposto de transferência da Fase 5)
    # ============================================================

    @commands.command(name="pay", aliases=["transferir", "enviar"])
    async def pay(self, ctx: commands.Context, member: discord.Member, amount: int):
        if member.id == ctx.author.id:
            return await ctx.send(embed=embed_error("❌ Não pode transferir para si mesmo!"))
        if amount <= 0:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))
        if member.bot:
            return await ctx.send(embed=embed_error("❌ Não pode transferir para bots."))

        guild_id = ctx.guild.id
        if EconomyManager.is_frozen(guild_id, ctx.author.id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        if EconomyManager.is_frozen(guild_id, member.id):
            return await ctx.send(embed=embed_error("❌ Economia do destinatário congelada."))

        config = EconomyManager.get_config(guild_id)
        min_t = config.get("min_transfer", 1)
        max_t = config.get("max_transfer", 1_000_000)
        if amount < min_t:
            return await ctx.send(embed=embed_error(f"❌ Mínimo: {self._format(guild_id, min_t)}"))
        if amount > max_t:
            return await ctx.send(embed=embed_error(f"❌ Máximo: {self._format(guild_id, max_t)}"))

        current = EconomyManager.get_balance(guild_id, ctx.author.id)
        if current < amount:
            return await ctx.send(embed=embed_error(
                f"❌ Saldo insuficiente! Você tem {self._format(guild_id, current)}"))

        success = EconomyManager.transfer(
            guild_id, ctx.author.id, member.id, amount,
            f"Transferência de {ctx.author} para {member}")
        if not success:
            return await ctx.send(embed=embed_error("❌ Falha na transferência."))

        # -------- Fase 5: Imposto de transferência --------
        # Só roda se TaxEngine existir (compatibilidade com instalação antiga)
        extra_tax = 0
        try:
            from tax_engine import TaxEngine
            # TaxEngine.collect_tax cobra do autor e envia ao tesouro.
            # Aqui só precisamos debitar — o collect_tax já registra.
            tax_info = TaxEngine.collect_tax(
                guild_id, ctx.author.id, amount, "transfer",
                f"Transferência para {member.id}"
            )
            extra_tax = int(tax_info.get("collected", 0))
            if extra_tax > 0:
                # Debita efetivamente do saldo do autor
                ok = EconomyManager.remove_balance(
                    guild_id, ctx.author.id, extra_tax,
                    "Imposto de transferência", "transfer_tax"
                )
                if not ok:
                    # Não tinha saldo pro imposto; ignora silenciosamente
                    # (operação principal já foi feita; só loga)
                    pass
        except ImportError:
            # Fase 5 não instalada — segue sem cobrança
            pass
        except Exception:
            # Nunca quebra o .pay por causa do imposto
            pass

        # -------- Feedback --------
        embed = discord.Embed(
            title="✅ Transferência Realizada!",
            description=(
                f"**{ctx.author.mention}** → "
                f"**{self._format(guild_id, amount)}** → "
                f"**{member.mention}**"
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow())

        base_tax_rate = float(config.get("tax_rate", 0))
        base_tax = int(amount * base_tax_rate / 100)
        total_tax = base_tax + extra_tax
        received = amount - base_tax

        if base_tax > 0:
            embed.add_field(
                name="📉 Taxa base (economy_config)",
                value=self._format(guild_id, base_tax),
                inline=True)
        if extra_tax > 0:
            embed.add_field(
                name="💸 Imposto de transferência",
                value=self._format(guild_id, extra_tax),
                inline=True)
        if total_tax > 0:
            embed.add_field(
                name="💰 Recebido",
                value=self._format(guild_id, received),
                inline=True)

        await ctx.send(embed=embed)

    @app_commands.command(name="pay", description="Transfere dinheiro")
    @app_commands.describe(member="Recebedor", amount="Valor")
    async def pay_slash(self, interaction: discord.Interaction,
                        member: discord.Member, amount: int):
        await self.pay(SlashCtxAdapter(interaction), member, amount)

    # ============================================================
    # RANKING
    # ============================================================

    @commands.command(name="ranking", aliases=["top", "leaderboard"])
    async def ranking(self, ctx: commands.Context):
        ranking = EconomyManager.get_ranking(ctx.guild.id, 15)
        if not ranking:
            return await ctx.send(embed=embed_info("📊 Ninguém possui saldo ainda."))
        embed = discord.Embed(title="🏆 Ranking dos Mais Ricos",
                              color=discord.Color.gold(),
                              timestamp=datetime.utcnow())
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, (uid, balance) in enumerate(ranking):
            user = ctx.guild.get_member(uid)
            name = user.display_name if user else f"ID: {uid}"
            medal = medals[i] if i < 10 else f"`{i+1}.`"
            embed.add_field(name=f"{medal} {name}",
                            value=self._format(ctx.guild.id, balance), inline=False)
        total = EconomyManager.get_total_balance(ctx.guild.id)
        embed.set_footer(text=f"💰 Em circulação: {self._format(ctx.guild.id, total)}")
        await ctx.send(embed=embed)

    @app_commands.command(name="ranking", description="Ranking dos mais ricos")
    async def ranking_slash(self, interaction: discord.Interaction):
        await self.ranking(SlashCtxAdapter(interaction))


async def setup(bot):
    if bot.get_cog("EconomyCore") is None:
        await bot.add_cog(EconomyCore(bot))