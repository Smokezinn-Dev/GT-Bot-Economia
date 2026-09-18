# ============================================================
# COMMANDS_ECONOMY_EARN.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import random
import asyncio
import re
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from utils import TTLCache, memory_guard, SlashCtxAdapter

_message_times: Dict[int, Dict[int, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=3)))
_daily_count: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
_activity_streak: Dict[int, Dict[int, dict]] = defaultdict(dict)
_treasure_active: Dict[int, dict] = {}
_challenge_progress: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

_last_cleanup = 0.0
_CLEANUP_INTERVAL = 240


def _cleanup_memory(force: bool = False):
    global _last_cleanup
    now = time.time()
    if not force and now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now

    for gid in list(_message_times.keys()):
        bucket = _message_times[gid]
        for uid in list(bucket.keys()):
            dq = bucket[uid]
            while dq and now - dq[0] > 60:
                dq.popleft()
            if not dq:
                del bucket[uid]
        if not bucket:
            del _message_times[gid]

    expired = [mid for mid, data in _treasure_active.items() if now > data.get("expires", 0)]
    for mid in expired:
        del _treasure_active[mid]

    cutoff_day = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    for gid in list(_activity_streak.keys()):
        bucket = _activity_streak[gid]
        for uid in list(bucket.keys()):
            if bucket[uid].get("last_day", "") < cutoff_day:
                del bucket[uid]
        if not bucket:
            del _activity_streak[gid]

    today = datetime.utcnow().strftime("%Y-%m-%d")
    if getattr(_cleanup_memory, "_last_day", None) != today:
        _cleanup_memory._last_day = today
        _daily_count.clear()
        _challenge_progress.clear()

    memory_guard(380.0)


class EarnManager:
    DEFAULT_CONFIG = {
        "per_message_amount": 1,
        "message_delay": 8,
        "max_messages_per_day": 150,
        "excluded_channels": [],
        "multiplier_roles": {},
        "bonus_hours": [],
        "peak_hour_multiplier": 1.4,
        "chat_activity_threshold": 15,
        "chat_activity_bonus": 3,
        "daily_challenge_enabled": True,
        "daily_challenge_target": 40,
        "daily_challenge_prize": 80,
        "treasure_hunt_enabled": True,
        "treasure_hunt_chance": 0.035,
        "treasure_min": 15,
        "treasure_max": 60,
        "prestige_enabled": True,
        "prestige_cost": 10000,
        "prestige_multiplier": 1.12,
        "streak_bonus_per_day": 0.05,
        "streak_max_days": 7,
    }

    _config_cache = TTLCache(max_size=200, ttl=90)

    @classmethod
    def get_config(cls, guild_id: int) -> dict:
        cached = cls._config_cache.get(guild_id)
        if cached is not None:
            return cached
        db = get_connection()
        doc = db["earn_config"].find_one({"guild_id": guild_id}, {"_id": 0})
        config = {**cls.DEFAULT_CONFIG, **(doc or {})}
        cls._config_cache.set(guild_id, config)
        return config

    @classmethod
    def update_config(cls, guild_id: int, key: str, value) -> None:
        db = get_connection()
        db["earn_config"].update_one(
            {"guild_id": guild_id}, {"$set": {key: value}}, upsert=True)
        cls._config_cache.invalidate(guild_id)

    @classmethod
    def get_prestige(cls, guild_id: int, user_id: int) -> dict:
        db = get_connection()
        doc = db["prestige"].find_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"prestige_level": 1, "multiplier": 1, "total_prestiged": 1})
        if not doc:
            return {"level": 0, "multiplier": 1.0, "total": 0}
        return {
            "level": doc.get("prestige_level", 0),
            "multiplier": float(doc.get("multiplier", 1.0)),
            "total": doc.get("total_prestiged", 0)
        }

    @classmethod
    def do_prestige(cls, guild_id: int, user_id: int, cost: int, mult_factor: float):
        if not EconomyManager.remove_balance(guild_id, user_id, cost, "Prestige", "prestige"):
            return None
        db = get_connection()
        doc = db["prestige"].find_one({"guild_id": guild_id, "user_id": user_id})
        if doc:
            level = doc.get("prestige_level", 0) + 1
            multiplier = round(float(doc.get("multiplier", 1.0)) * mult_factor, 4)
            db["prestige"].update_one(
                {"guild_id": guild_id, "user_id": user_id},
                {"$set": {"prestige_level": level, "multiplier": multiplier},
                 "$inc": {"total_prestiged": 1}})
        else:
            level = 1
            multiplier = round(mult_factor, 4)
            db["prestige"].insert_one({
                "guild_id": guild_id, "user_id": user_id,
                "prestige_level": level, "multiplier": multiplier,
                "total_prestiged": 1, "created_at": datetime.utcnow()
            })
        EconomyManager.set_balance(guild_id, user_id, 0)
        return {"level": level, "multiplier": multiplier}

    @classmethod
    def get_multiplier(cls, guild_id: int, member: discord.Member) -> float:
        config = cls.get_config(guild_id)
        mult = 1.0
        role_mults = config.get("multiplier_roles", {})
        if role_mults:
            for role_id, role_mult in role_mults.items():
                try:
                    if member.get_role(int(role_id)):
                        mult *= float(role_mult)
                except Exception:
                    continue
        mult *= cls.get_prestige(guild_id, member.id).get("multiplier", 1.0)
        if datetime.utcnow().hour in config.get("bonus_hours", []):
            mult *= float(config.get("peak_hour_multiplier", 1.4))
        streak_data = _activity_streak.get(guild_id, {}).get(member.id)
        if streak_data:
            days = min(streak_data.get("streak", 0), config.get("streak_max_days", 7))
            mult *= (1.0 + days * float(config.get("streak_bonus_per_day", 0.05)))
        return round(mult, 4)

    @classmethod
    def update_streak(cls, guild_id: int, user_id: int):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        data = _activity_streak[guild_id].get(user_id)
        if not data:
            _activity_streak[guild_id][user_id] = {"streak": 1, "last_day": today}
            return
        last = data.get("last_day")
        if last == today:
            return
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        data["streak"] = data.get("streak", 0) + 1 if last == yesterday else 1
        data["last_day"] = today


class EconomyEarn(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    @tasks.loop(minutes=4)
    async def cleanup_task(self):
        try:
            _cleanup_memory(force=True)
        except Exception:
            pass

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        guild = message.guild
        if guild is None:
            return
        content = message.content
        if not content or len(content) < 2:
            return
        # ✅ Ignora comandos com prefixo . e slash
        if content[0] in (".", "/"):
            return
        guild_id = guild.id
        user_id = message.author.id
        if EconomyManager.is_frozen(guild_id, user_id):
            return
        config = EarnManager.get_config(guild_id)
        if message.channel.id in config.get("excluded_channels", []):
            return
        now = time.time()
        delay = float(config.get("message_delay", 8))
        times = _message_times[guild_id][user_id]
        while times and now - times[0] > delay:
            times.popleft()
        if times:
            return
        times.append(now)
        max_day = int(config.get("max_messages_per_day", 150))
        if _daily_count[guild_id][user_id] >= max_day:
            return
        _daily_count[guild_id][user_id] += 1
        EarnManager.update_streak(guild_id, user_id)

        base = int(config.get("per_message_amount", 1))
        mult = EarnManager.get_multiplier(guild_id, message.author)
        amount = max(1, int(base * mult))
        total_chat = sum(_daily_count[guild_id].values())
        if total_chat >= int(config.get("chat_activity_threshold", 15)):
            amount += int(config.get("chat_activity_bonus", 3))

        EconomyManager.add_balance(guild_id, user_id, amount,
                                   f"Chat #{message.channel.name}", "earn")
        EconomyManager.increment_counter(guild_id, user_id, "messages_sent", 1)

        if config.get("daily_challenge_enabled", True):
            _challenge_progress[guild_id][user_id] += 1
            target = int(config.get("daily_challenge_target", 40))
            if _challenge_progress[guild_id][user_id] == target:
                prize = int(config.get("daily_challenge_prize", 80))
                EconomyManager.add_balance(guild_id, user_id, prize,
                                           "Daily Challenge completo", "daily_challenge")
                try:
                    await message.channel.send(
                        embed=embed_success(
                            f"🎯 {message.author.mention} completou o **Daily Challenge** "
                            f"({target} mensagens) e ganhou "
                            f"**{EconomyManager.format_currency(guild_id, prize)}**!"
                        ),
                        delete_after=15)
                except Exception:
                    pass

        if config.get("treasure_hunt_enabled", True):
            if random.random() < float(config.get("treasure_hunt_chance", 0.035)):
                await self._spawn_treasure(message, config)

        if random.random() < 0.01:
            _cleanup_memory()

    async def _spawn_treasure(self, message: discord.Message, config: dict):
        min_p = int(config.get("treasure_min", 15))
        max_p = int(config.get("treasure_max", 60))
        base = int(config.get("per_message_amount", 1))
        prize = random.randint(min_p, max_p) * max(1, base)
        embed = discord.Embed(
            title="🎁 TESOURO ESCONDIDO!",
            description="Reaja com 🎁 em **30 segundos**!",
            color=discord.Color.gold(), timestamp=datetime.utcnow())
        embed.add_field(name="💰 Prêmio",
                        value=EconomyManager.format_currency(message.guild.id, prize))
        embed.set_footer(text="Primeiro leva!")
        try:
            msg = await message.channel.send(embed=embed)
            await msg.add_reaction("🎁")
        except Exception:
            return
        _treasure_active[msg.id] = {
            "prize": prize, "claimed": False,
            "expires": time.time() + 30,
            "guild_id": message.guild.id
        }
        await asyncio.sleep(30)
        data = _treasure_active.get(msg.id)
        if data and not data["claimed"]:
            try:
                await msg.edit(embed=embed_error("⏰ Tesouro expirou!"))
            except Exception:
                pass
            _treasure_active.pop(msg.id, None)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != "🎁":
            return
        data = _treasure_active.get(payload.message_id)
        if not data or data["claimed"]:
            return
        data["claimed"] = True
        prize = data["prize"]
        guild_id = data.get("guild_id") or payload.guild_id
        EconomyManager.add_balance(guild_id, payload.user_id, prize,
                                   "Tesouro encontrado", "treasure")
        channel = self.bot.get_channel(payload.channel_id)
        if channel:
            try:
                msg = await channel.fetch_message(payload.message_id)
                await msg.edit(embed=embed_success(
                    f"🎉 <@{payload.user_id}> encontrou o tesouro e ganhou "
                    f"**{EconomyManager.format_currency(guild_id, prize)}**!"))
            except Exception:
                pass
        _treasure_active.pop(payload.message_id, None)

    @commands.command(name="prestige")
    async def prestige(self, ctx: commands.Context):
        config = EarnManager.get_config(ctx.guild.id)
        if not config.get("prestige_enabled", True):
            return await ctx.send(embed=embed_error("❌ Sistema de Prestígio desativado."))
        if EconomyManager.is_frozen(ctx.guild.id, ctx.author.id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        cost = int(config.get("prestige_cost", 10000))
        balance = EconomyManager.get_balance(ctx.guild.id, ctx.author.id)
        if balance < cost:
            return await ctx.send(embed=embed_error(
                f"❌ Precisa de **{EconomyManager.format_currency(ctx.guild.id, cost)}**.\n"
                f"Seu saldo: {EconomyManager.format_currency(ctx.guild.id, balance)}"))
        mult_factor = float(config.get("prestige_multiplier", 1.12))
        result = EarnManager.do_prestige(ctx.guild.id, ctx.author.id, cost, mult_factor)
        if not result:
            return await ctx.send(embed=embed_error("❌ Falha no Prestígio."))
        embed = discord.Embed(
            title="🌟 PRESTÍGIO ALCANÇADO!",
            description=f"{ctx.author.mention} alcançou o **Nível {result['level']}**!",
            color=discord.Color.gold(), timestamp=datetime.utcnow())
        embed.add_field(name="🔥 Novo Multiplicador",
                        value=f"**x{result['multiplier']:.2f}**", inline=True)
        embed.add_field(name="💰 Custo",
                        value=EconomyManager.format_currency(ctx.guild.id, cost), inline=True)
        embed.set_footer(text="Saldo resetado. Ganhos futuros aumentados.")
        await ctx.send(embed=embed)

    @commands.command(name="prestigestatus", aliases=["prestigeinfo"])
    async def prestige_status(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        prestige = EarnManager.get_prestige(ctx.guild.id, member.id)
        streak = _activity_streak.get(ctx.guild.id, {}).get(member.id, {}).get("streak", 0)
        embed = discord.Embed(
            title=f"🌟 Prestígio de {member.display_name}",
            color=discord.Color.gold(), timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="📊 Nível", value=str(prestige.get("level", 0)), inline=True)
        embed.add_field(name="🔥 Multiplicador",
                        value=f"x{prestige.get('multiplier', 1.0):.2f}", inline=True)
        embed.add_field(name="💫 Total", value=str(prestige.get("total", 0)), inline=True)
        embed.add_field(name="🔥 Streak", value=f"{streak} dia(s)", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="invest")
    async def invest(self, ctx: commands.Context, amount: int, days: int):
        if amount <= 0:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))
        if days < 1 or days > 30:
            return await ctx.send(embed=embed_error("❌ Dias: 1 a 30!"))
        if EconomyManager.is_frozen(ctx.guild.id, ctx.author.id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        balance = EconomyManager.get_balance(ctx.guild.id, ctx.author.id)
        if balance < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))
        rate = 0.04 + (days * 0.004)
        total_return = int(amount * (1 + rate))
        if not EconomyManager.remove_balance(ctx.guild.id, ctx.author.id, amount,
                                              f"Investimento {days}d", "invest"):
            return await ctx.send(embed=embed_error("❌ Falha ao investir."))
        db = get_connection()
        db["investments"].insert_one({
            "guild_id": ctx.guild.id, "user_id": ctx.author.id,
            "amount": amount, "interest_rate": rate,
            "start_time": datetime.utcnow(),
            "end_time": datetime.utcnow() + timedelta(days=days),
            "collected": False
        })
        embed = discord.Embed(
            title="📈 INVESTIMENTO REALIZADO!",
            description=(
                f"{ctx.author.mention} investiu "
                f"**{EconomyManager.format_currency(ctx.guild.id, amount)}** "
                f"por **{days} dias**."
            ),
            color=discord.Color.blue(), timestamp=datetime.utcnow())
        embed.add_field(name="📊 Taxa", value=f"{rate*100:.1f}%", inline=True)
        embed.add_field(name="💰 Retorno Estimado",
                        value=EconomyManager.format_currency(ctx.guild.id, total_return),
                        inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="collect")
    async def collect(self, ctx: commands.Context):
        db = get_connection()
        docs = list(db["investments"].find({
            "guild_id": ctx.guild.id, "user_id": ctx.author.id,
            "collected": False, "end_time": {"$lte": datetime.utcnow()}
        }))
        if not docs:
            return await ctx.send(embed=embed_info("📊 Você não tem investimentos para resgatar."))
        total = 0
        ids = []
        for doc in docs:
            total += int(doc["amount"] * (1 + float(doc["interest_rate"])))
            ids.append(doc["_id"])
        db["investments"].update_many({"_id": {"$in": ids}}, {"$set": {"collected": True}})
        EconomyManager.add_balance(ctx.guild.id, ctx.author.id, total,
                                   "Resgate de investimentos", "invest_collect")
        EconomyManager.increment_counter(
            ctx.guild.id, ctx.author.id, "investments_collected", len(docs))

        embed = discord.Embed(
            title="💰 INVESTIMENTOS RESGATADOS!",
            description=f"Você resgatou **{EconomyManager.format_currency(ctx.guild.id, total)}**!",
            color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="📈 Quantidade",
                        value=f"{len(docs)} investimento(s)", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="earnconfig")
    @commands.has_permissions(administrator=True)
    async def earn_config(self, ctx: commands.Context, key: str = None, *, value: str = None):
        config = EarnManager.get_config(ctx.guild.id)
        if not key:
            embed = discord.Embed(
                title="⚙️ Configuração de Ganhos",
                color=discord.Color.blue(), timestamp=datetime.utcnow())
            embed.add_field(name="💬 Por Mensagem",
                            value=str(config["per_message_amount"]), inline=True)
            embed.add_field(name="⏳ Delay",
                            value=f"{config['message_delay']}s", inline=True)
            embed.add_field(name="📊 Limite Diário",
                            value=str(config["max_messages_per_day"]), inline=True)
            embed.add_field(name="🎯 Daily Challenge",
                            value=f"{config['daily_challenge_target']} msgs → {config['daily_challenge_prize']}",
                            inline=True)
            embed.add_field(name="🎁 Tesouro",
                            value="Ativo" if config["treasure_hunt_enabled"] else "Off",
                            inline=True)
            embed.add_field(name="🌟 Prestígio",
                            value="Ativo" if config["prestige_enabled"] else "Off",
                            inline=True)
            embed.add_field(name="🔥 Streak Bônus",
                            value=f"+{config['streak_bonus_per_day']*100:.0f}%/dia",
                            inline=True)
            return await ctx.send(embed=embed)
        valid = ["per_message_amount", "message_delay", "max_messages_per_day",
                 "excluded_channels", "multiplier_roles", "bonus_hours",
                 "peak_hour_multiplier", "chat_activity_threshold", "chat_activity_bonus",
                 "daily_challenge_enabled", "daily_challenge_target", "daily_challenge_prize",
                 "treasure_hunt_enabled", "treasure_hunt_chance", "treasure_min", "treasure_max",
                 "prestige_enabled", "prestige_cost", "prestige_multiplier",
                 "streak_bonus_per_day", "streak_max_days"]
        if key not in valid:
            return await ctx.send(embed=embed_error(
                f"❌ Chave inválida. Use uma de:\n`{', '.join(valid[:8])}...`"))
        if value is None:
            return await ctx.send(embed=embed_error("❌ Forneça um valor."))
        try:
            if key in ("per_message_amount", "message_delay", "max_messages_per_day",
                       "chat_activity_threshold", "chat_activity_bonus",
                       "daily_challenge_target", "daily_challenge_prize",
                       "prestige_cost", "treasure_min", "treasure_max", "streak_max_days"):
                parsed = int(value)
            elif key in ("peak_hour_multiplier", "treasure_hunt_chance",
                         "prestige_multiplier", "streak_bonus_per_day"):
                parsed = float(value)
            elif key in ("daily_challenge_enabled", "treasure_hunt_enabled", "prestige_enabled"):
                parsed = value.lower() in ("true", "1", "sim", "on", "yes", "ativar")
            elif key == "excluded_channels":
                parsed = [int(i) for i in re.findall(r"<#(\d+)>", value)]
            elif key == "multiplier_roles":
                result = {}
                for part in value.split(","):
                    m = re.search(r"<@&(\d+)>\s*[:=]\s*([\d.]+)", part.strip())
                    if m:
                        result[str(int(m.group(1)))] = float(m.group(2))
                parsed = result
            elif key == "bonus_hours":
                parsed = [int(h.strip()) for h in value.split(",") if h.strip().isdigit()]
            else:
                parsed = value
        except Exception:
            return await ctx.send(embed=embed_error("❌ Valor inválido."))
        EarnManager.update_config(ctx.guild.id, key, parsed)
        await ctx.send(embed=embed_success(f"✅ `{key}` atualizado!"))


async def setup(bot):
    if bot.get_cog("EconomyEarn") is None:
        await bot.add_cog(EconomyEarn(bot))