# ============================================================
# COMMANDS_ECONOMY_EVENTS.PY - v6.1 (SlashCtxAdapter)
# ============================================================

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from database import get_connection
from embeds import embed_success, embed_error, embed_info
from utils import TTLCache, safe_object_id, SlashCtxAdapter


class EventManager:
    VALID_TYPES = {
        "multiplier": "Multiplica todos os ganhos",
        "bonus": "Adiciona valor fixo extra em cada ganho",
        "double": "Dobra ganhos (atalho de multiplier 2x)",
        "earn_only": "Só afeta ganhos por mensagem",
        "shop_discount": "Desconto percentual na loja",
    }
    _cache = TTLCache(max_size=200, ttl=25)

    @classmethod
    def get_active_events(cls, guild_id: int) -> List[Dict]:
        cached = cls._cache.get(guild_id)
        if cached is not None:
            return cached
        db = get_connection()
        events = list(db["events"].find({
            "guild_id": guild_id, "active": True,
            "end_time": {"$gt": datetime.utcnow()}
        }))
        cls._cache.set(guild_id, events)
        return events

    @classmethod
    def invalidate_cache(cls, guild_id: int):
        cls._cache.invalidate(guild_id)

    @staticmethod
    def get_event(guild_id: int, event_id) -> Optional[Dict]:
        db = get_connection()
        oid = safe_object_id(event_id)
        if oid:
            return db["events"].find_one({"_id": oid, "guild_id": guild_id})
        try:
            return db["events"].find_one({"_id": int(event_id), "guild_id": guild_id})
        except Exception:
            return None

    @staticmethod
    def create_event(guild_id: int, data: dict) -> Any:
        db = get_connection()
        now = datetime.utcnow()
        duration = int(data.get("duration", 3600))
        doc = {
            "guild_id": guild_id,
            "name": data["name"],
            "description": data.get("description", ""),
            "event_type": data["event_type"],
            "multiplier": float(data.get("multiplier", 1.0)),
            "bonus_amount": int(data.get("bonus_amount", 0)),
            "discount_percent": float(data.get("discount_percent", 0)),
            "duration": duration,
            "start_time": now,
            "end_time": now + timedelta(seconds=duration),
            "active": True,
            "created_by": data.get("created_by"),
            "created_at": now
        }
        result = db["events"].insert_one(doc)
        EventManager.invalidate_cache(guild_id)
        return result.inserted_id

    @staticmethod
    def deactivate_event(guild_id: int, event_id) -> bool:
        db = get_connection()
        oid = safe_object_id(event_id)
        query = ({"_id": oid, "guild_id": guild_id} if oid
                 else {"_id": int(event_id), "guild_id": guild_id})
        try:
            res = db["events"].update_one(query, {"$set": {"active": False}})
            EventManager.invalidate_cache(guild_id)
            return res.modified_count > 0
        except Exception:
            return False

    @classmethod
    def get_earn_multiplier(cls, guild_id: int) -> float:
        events = cls.get_active_events(guild_id)
        mult = 1.0
        for ev in events:
            etype = ev.get("event_type")
            if etype in ("multiplier", "double", "earn_only"):
                m = float(ev.get("multiplier", 1.0))
                if etype == "double":
                    m = 2.0
                mult *= m
        return round(mult, 4)

    @classmethod
    def get_earn_bonus(cls, guild_id: int) -> int:
        events = cls.get_active_events(guild_id)
        return sum(int(ev.get("bonus_amount", 0))
                   for ev in events if ev.get("event_type") == "bonus")

    @classmethod
    def get_shop_discount(cls, guild_id: int) -> float:
        events = cls.get_active_events(guild_id)
        discount = 0.0
        for ev in events:
            if ev.get("event_type") == "shop_discount":
                discount = max(discount, float(ev.get("discount_percent", 0)))
        return min(discount, 90.0)


class EconomyEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._end_tasks = {}
        self.cleanup_loop.start()

    def cog_unload(self):
        self.cleanup_loop.cancel()
        for task in self._end_tasks.values():
            task.cancel()

    @tasks.loop(minutes=3)
    async def cleanup_loop(self):
        try:
            db = get_connection()
            result = db["events"].update_many(
                {"active": True, "end_time": {"$lte": datetime.utcnow()}},
                {"$set": {"active": False}})
            if result.modified_count > 0:
                EventManager._cache.clear()
        except Exception:
            pass

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @commands.command(name="eventcreate")
    @commands.has_permissions(administrator=True)
    async def event_create(self, ctx: commands.Context, name: str, event_type: str,
                           multiplier: float = 1.0, bonus_amount: int = 0,
                           duration: int = 3600, *, description: str = ""):
        etype = event_type.lower()
        if etype not in EventManager.VALID_TYPES:
            return await ctx.send(embed=embed_error(
                f"❌ Tipos: `{', '.join(EventManager.VALID_TYPES.keys())}`"))
        if duration < 60 or duration > 86400 * 3:
            return await ctx.send(embed=embed_error("❌ Duração: 60s até 3 dias."))

        discount = 0.0
        if etype == "shop_discount":
            discount = max(0.0, min(float(multiplier), 90.0))
            multiplier = 1.0
        if etype == "double":
            multiplier = 2.0

        event_id = EventManager.create_event(ctx.guild.id, {
            "name": name, "description": description, "event_type": etype,
            "multiplier": multiplier, "bonus_amount": bonus_amount,
            "discount_percent": discount, "duration": duration,
            "created_by": ctx.author.id
        })

        embed = discord.Embed(
            title="🎉 EVENTO CRIADO!",
            description=f"**{name}** está ativo!",
            color=discord.Color.gold(), timestamp=datetime.utcnow())
        embed.add_field(name="🎯 Tipo",
                        value=f"{etype}\n*{EventManager.VALID_TYPES[etype]}*",
                        inline=False)
        if etype in ("multiplier", "double", "earn_only"):
            embed.add_field(name="📈 Multiplicador", value=f"x{multiplier}", inline=True)
        if etype == "bonus":
            embed.add_field(name="🎁 Bônus", value=f"+{bonus_amount}", inline=True)
        if etype == "shop_discount":
            embed.add_field(name="🏷️ Desconto", value=f"{discount}%", inline=True)
        embed.add_field(name="⏳ Duração", value=f"{duration // 60} min", inline=True)
        embed.add_field(name="🆔 ID", value=f"`{str(event_id)[:8]}`", inline=True)
        await ctx.send(embed=embed)

        task = asyncio.create_task(self._end_event_later(
            ctx.guild.id, event_id, duration, name, ctx.channel))
        self._end_tasks[str(event_id)] = task

    @app_commands.command(name="eventcreate", description="🎉 Cria um evento econômico")
    @app_commands.default_permissions(administrator=True)
    async def event_create_slash(self, interaction: discord.Interaction, name: str,
                                 event_type: str, multiplier: float = 1.0,
                                 bonus_amount: int = 0, duration: int = 3600,
                                 description: str = ""):
        await self.event_create(
            SlashCtxAdapter(interaction), name, event_type,
            multiplier, bonus_amount, duration, description=description)

    async def _end_event_later(self, guild_id: int, event_id, duration: int,
                               name: str, channel):
        try:
            await asyncio.sleep(duration)
            EventManager.deactivate_event(guild_id, event_id)
            if channel:
                try:
                    await channel.send(embed=embed_info(f"⏰ Evento **{name}** terminou!"))
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            self._end_tasks.pop(str(event_id), None)

    @commands.command(name="eventdelete")
    @commands.has_permissions(administrator=True)
    async def event_delete(self, ctx: commands.Context, event_id: str):
        event = EventManager.get_event(ctx.guild.id, event_id)
        if not event:
            return await ctx.send(embed=embed_error(
                f"❌ Evento `{event_id}` não encontrado."))
        EventManager.deactivate_event(ctx.guild.id, event_id)
        task = self._end_tasks.pop(str(event.get("_id")), None)
        if task:
            task.cancel()
        await ctx.send(embed=embed_success(f"✅ Evento **{event.get('name')}** encerrado!"))

    @commands.command(name="events", aliases=["eventos"])
    async def events(self, ctx: commands.Context):
        events = EventManager.get_active_events(ctx.guild.id)
        embed = discord.Embed(title="🎉 EVENTOS ATIVOS",
                              color=discord.Color.gold(),
                              timestamp=datetime.utcnow())
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        if not events:
            embed.description = "Nenhum evento ativo."
        else:
            for ev in events:
                remaining = max(0, int((ev["end_time"] - datetime.utcnow()).total_seconds()))
                mins = remaining // 60
                etype = ev.get("event_type", "?")
                lines = [f"🎯 `{etype}`"]
                if etype in ("multiplier", "double", "earn_only"):
                    lines.append(f"📈 x{ev.get('multiplier', 1)}")
                if etype == "bonus":
                    lines.append(f"🎁 +{ev.get('bonus_amount', 0)}")
                if etype == "shop_discount":
                    lines.append(f"🏷️ {ev.get('discount_percent', 0)}% off")
                lines.append(f"⏳ {mins} min restantes")
                embed.add_field(name=f"#{str(ev['_id'])[:6]} — {ev.get('name')}",
                                value="\n".join(lines), inline=False)

        mult = EventManager.get_earn_multiplier(ctx.guild.id)
        bonus = EventManager.get_earn_bonus(ctx.guild.id)
        discount = EventManager.get_shop_discount(ctx.guild.id)
        summary = []
        if mult != 1.0:
            summary.append(f"Ganhos x**{mult}**")
        if bonus > 0:
            summary.append(f"+**{bonus}** por ganho")
        if discount > 0:
            summary.append(f"Loja **{discount}%** off")
        if summary:
            embed.add_field(name="⚡ Efeito Atual",
                            value=" | ".join(summary), inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("EconomyEvents") is None:
        await bot.add_cog(EconomyEvents(bot))