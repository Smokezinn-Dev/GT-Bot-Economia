# ============================================================
# COMMANDS_ECONOMY_ACHIEVEMENTS.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional, List, Dict, Any

from database import get_connection
from embeds import embed_success, embed_error, embed_info
from commands_economy_core import EconomyManager
from utils import TTLCache, safe_object_id, SlashCtxAdapter


class AchievementManager:
    VALID_REQUIREMENTS = {
        "balance": "Ter X de saldo",
        "messages": "Enviar X mensagens (permanente)",
        "prestige": "Alcançar nível X de prestige",
        "wins": "Ter X vitórias (ranked)",
        "transfers": "Fazer X transferências",
        "investments": "Resgatar X investimentos",
        "purchases": "Comprar X itens na loja",
        "daily_streak": "Coletar daily X vezes",
    }
    VALID_REWARDS = {"money", "role"}

    _list_cache = TTLCache(max_size=200, ttl=45)

    @staticmethod
    def get_achievements(guild_id: int, active_only: bool = True) -> List[Dict]:
        key = f"{guild_id}:{int(active_only)}"
        cached = AchievementManager._list_cache.get(key)
        if cached is not None:
            return cached
        db = get_connection()
        query = {"guild_id": guild_id}
        if active_only:
            query["active"] = True
        result = list(db["achievements"].find(query).sort("created_at", -1))
        AchievementManager._list_cache.set(key, result)
        return result

    @staticmethod
    def get_achievement(guild_id: int, achievement_id) -> Optional[Dict]:
        db = get_connection()
        oid = safe_object_id(achievement_id)
        if oid:
            return db["achievements"].find_one({"_id": oid, "guild_id": guild_id})
        try:
            return db["achievements"].find_one(
                {"_id": int(achievement_id), "guild_id": guild_id})
        except Exception:
            return None

    @staticmethod
    def create_achievement(guild_id: int, data: dict) -> Any:
        db = get_connection()
        data["guild_id"] = guild_id
        data["active"] = True
        data["created_at"] = datetime.utcnow()
        result = db["achievements"].insert_one(data)
        AchievementManager._list_cache.invalidate_prefix(f"{guild_id}:")
        return result.inserted_id

    @staticmethod
    def delete_achievement(guild_id: int, achievement_id) -> bool:
        db = get_connection()
        oid = safe_object_id(achievement_id)
        query = ({"_id": oid, "guild_id": guild_id} if oid
                 else {"_id": int(achievement_id), "guild_id": guild_id})
        try:
            res = db["achievements"].delete_one(query)
            AchievementManager._list_cache.invalidate_prefix(f"{guild_id}:")
            return res.deleted_count > 0
        except Exception:
            return False

    @staticmethod
    def is_unlocked(guild_id: int, user_id: int, achievement_id) -> bool:
        db = get_connection()
        return db["user_achievements"].find_one({
            "guild_id": guild_id, "user_id": user_id,
            "achievement_id": str(achievement_id)
        }) is not None

    @staticmethod
    def unlock(guild_id: int, user_id: int, achievement_id,
               achievement_name: str = "") -> bool:
        if AchievementManager.is_unlocked(guild_id, user_id, achievement_id):
            return False
        db = get_connection()
        try:
            db["user_achievements"].insert_one({
                "guild_id": guild_id, "user_id": user_id,
                "achievement_id": str(achievement_id),
                "achievement_name": achievement_name,
                "unlocked_at": datetime.utcnow()
            })
            return True
        except Exception:
            return False

    @staticmethod
    def get_user_achievements(guild_id: int, user_id: int) -> List[Dict]:
        db = get_connection()
        return list(db["user_achievements"].find(
            {"guild_id": guild_id, "user_id": user_id}).sort("unlocked_at", -1))

    @staticmethod
    def get_progress_value(guild_id: int, user_id: int, req_type: str) -> int:
        db = get_connection()
        if req_type == "balance":
            return EconomyManager.get_balance(guild_id, user_id)
        if req_type == "prestige":
            doc = db["prestige"].find_one(
                {"guild_id": guild_id, "user_id": user_id}, {"prestige_level": 1})
            return int(doc.get("prestige_level", 0)) if doc else 0
        if req_type == "messages":
            return EconomyManager.get_counter(guild_id, user_id, "messages_sent")
        if req_type == "transfers":
            return EconomyManager.get_counter(guild_id, user_id, "transfers_sent")
        if req_type == "purchases":
            return EconomyManager.get_counter(guild_id, user_id, "purchases_made")
        if req_type == "investments":
            return EconomyManager.get_counter(guild_id, user_id, "investments_collected")
        if req_type == "daily_streak":
            return EconomyManager.get_counter(guild_id, user_id, "dailies_collected")
        if req_type == "wins":
            doc = db["players"].find_one(
                {"guild_id": str(guild_id), "user_id": str(user_id)},
                {"total_wins": 1})
            return int(doc.get("total_wins", 0)) if doc else 0
        return 0

    @staticmethod
    async def check_and_unlock(guild_id: int, user_id: int,
                               member: discord.Member = None,
                               bot=None, channel=None) -> List[Dict]:
        achievements = AchievementManager.get_achievements(guild_id)
        unlocked_now = []
        for ach in achievements:
            ach_id = ach["_id"]
            if AchievementManager.is_unlocked(guild_id, user_id, ach_id):
                continue
            req_type = ach.get("requirement_type", "")
            req_value = int(ach.get("requirement_value", 0))
            current = AchievementManager.get_progress_value(guild_id, user_id, req_type)
            if current < req_value:
                continue
            if not AchievementManager.unlock(guild_id, user_id, ach_id, ach.get("name", "")):
                continue
            reward_type = ach.get("reward_type", "money")
            reward_value = ach.get("reward_value", "0")
            if reward_type == "money":
                try:
                    amount = int(reward_value)
                    if amount > 0:
                        EconomyManager.add_balance(
                            guild_id, user_id, amount,
                            f"Conquista: {ach.get('name')}", "achievement")
                except Exception:
                    pass
            elif reward_type == "role" and member and bot:
                try:
                    role_id = int(reward_value)
                    role = member.guild.get_role(role_id)
                    if role:
                        await member.add_roles(role, reason=f"Conquista: {ach.get('name')}")
                except Exception:
                    pass
            unlocked_now.append(ach)
            if channel:
                try:
                    embed = discord.Embed(
                        title="🏆 CONQUISTA DESBLOQUEADA!",
                        description=(
                            f"{member.mention if member else f'<@{user_id}>'} "
                            f"desbloqueou **{ach.get('name')}**!"
                        ),
                        color=discord.Color.gold(),
                        timestamp=datetime.utcnow())
                    if ach.get("description"):
                        embed.add_field(name="📋", value=ach["description"], inline=False)
                    embed.add_field(name="🎁 Recompensa",
                                    value=f"{reward_type}: {reward_value}", inline=True)
                    await channel.send(embed=embed, delete_after=25)
                except Exception:
                    pass
        return unlocked_now


class EconomyAchievements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="achcreate")
    @commands.has_permissions(administrator=True)
    async def ach_create(self, ctx: commands.Context, name: str, requirement_type: str,
                         requirement_value: int, reward_type: str, reward_value: str,
                         *, description: str = ""):
        req_type = requirement_type.lower()
        rew_type = reward_type.lower()
        if req_type not in AchievementManager.VALID_REQUIREMENTS:
            return await ctx.send(embed=embed_error(
                f"❌ Requisitos válidos:\n`{', '.join(AchievementManager.VALID_REQUIREMENTS.keys())}`"))
        if rew_type not in AchievementManager.VALID_REWARDS:
            return await ctx.send(embed=embed_error("❌ Recompensas: `money` ou `role`"))
        if requirement_value <= 0:
            return await ctx.send(embed=embed_error("❌ Valor do requisito deve ser positivo."))
        db = get_connection()
        if db["achievements"].find_one({"guild_id": ctx.guild.id, "name": name}):
            return await ctx.send(embed=embed_error(f"❌ Já existe conquista chamada `{name}`."))
        ach_id = AchievementManager.create_achievement(ctx.guild.id, {
            "name": name, "description": description, "icon": "🏆",
            "requirement_type": req_type, "requirement_value": requirement_value,
            "reward_type": rew_type, "reward_value": str(reward_value),
            "created_by": ctx.author.id
        })
        embed = discord.Embed(
            title="🏆 CONQUISTA CRIADA!",
            description=f"**{name}** criada!",
            color=discord.Color.gold(), timestamp=datetime.utcnow())
        embed.add_field(name="📋 Requisito",
                        value=f"`{req_type}` ≥ **{requirement_value}**\n"
                              f"({AchievementManager.VALID_REQUIREMENTS[req_type]})",
                        inline=False)
        embed.add_field(name="🎁 Recompensa", value=f"{rew_type}: `{reward_value}`", inline=True)
        embed.add_field(name="🆔 ID", value=f"`{str(ach_id)[:8]}`", inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="achcreate", description="🏆 Cria uma conquista")
    @app_commands.default_permissions(administrator=True)
    async def ach_create_slash(self, interaction: discord.Interaction, name: str,
                               requirement_type: str, requirement_value: int,
                               reward_type: str, reward_value: str,
                               description: str = ""):
        await self.ach_create(
            SlashCtxAdapter(interaction),
            name, requirement_type, requirement_value,
            reward_type, reward_value, description=description)

    @commands.command(name="achdelete")
    @commands.has_permissions(administrator=True)
    async def ach_delete(self, ctx: commands.Context, achievement_id: str):
        ach = AchievementManager.get_achievement(ctx.guild.id, achievement_id)
        if not ach:
            return await ctx.send(embed=embed_error(
                f"❌ Conquista `{achievement_id}` não encontrada."))
        AchievementManager.delete_achievement(ctx.guild.id, achievement_id)
        await ctx.send(embed=embed_success(f"✅ Conquista **{ach.get('name')}** deletada!"))

    @commands.command(name="achievements", aliases=["conquistas", "ach"])
    async def achievements(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        guild_id = ctx.guild.id
        user_id = member.id
        unlocked = AchievementManager.get_user_achievements(guild_id, user_id)
        all_achs = AchievementManager.get_achievements(guild_id)
        embed = discord.Embed(
            title=f"🏆 Conquistas de {member.display_name}",
            color=member.color or discord.Color.gold(),
            timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="📊 Progresso",
                        value=f"**{len(unlocked)}** / **{len(all_achs)}** desbloqueadas",
                        inline=False)
        if unlocked:
            lines = []
            for item in unlocked[:8]:
                name = item.get("achievement_name") or "Conquista"
                ts = item.get("unlocked_at", datetime.utcnow())
                ts_str = ts.strftime("%d/%m/%Y") if hasattr(ts, "strftime") else str(ts)[:10]
                lines.append(f"✅ **{name}** — `{ts_str}`")
            embed.add_field(name="Desbloqueadas", value="\n".join(lines), inline=False)
        unlocked_ids = {str(u.get("achievement_id")) for u in unlocked}
        missing = [a for a in all_achs if str(a["_id"]) not in unlocked_ids]
        if missing:
            prog_lines = []
            for ach in missing[:6]:
                req_type = ach.get("requirement_type", "")
                req_val = int(ach.get("requirement_value", 0))
                current = AchievementManager.get_progress_value(guild_id, user_id, req_type)
                pct = min(100, int((current / req_val) * 100)) if req_val > 0 else 0
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                prog_lines.append(
                    f"**{ach.get('name')}**\n`{bar}` {current}/{req_val} ({pct}%)")
            embed.add_field(name="🎯 Em progresso", value="\n".join(prog_lines), inline=False)
        if not unlocked and not missing:
            embed.description = "Nenhuma conquista configurada."
        await ctx.send(embed=embed)

    @commands.command(name="achlist", aliases=["achievementsall"])
    async def ach_list(self, ctx: commands.Context):
        achs = AchievementManager.get_achievements(ctx.guild.id)
        if not achs:
            return await ctx.send(embed=embed_info("📋 Nenhuma conquista criada ainda."))
        embed = discord.Embed(title="🏆 Conquistas do Servidor",
                              color=discord.Color.gold(),
                              timestamp=datetime.utcnow())
        for ach in achs[:15]:
            req = f"{ach.get('requirement_type')} ≥ {ach.get('requirement_value')}"
            rew = f"{ach.get('reward_type')}: {ach.get('reward_value')}"
            embed.add_field(name=f"{ach.get('icon', '🏆')} {ach.get('name')}",
                            value=f"📋 {req}\n🎁 {rew}\n`ID: {str(ach['_id'])[:8]}`",
                            inline=False)
        embed.set_footer(text=f"Total: {len(achs)} | .achcreate para criar")
        await ctx.send(embed=embed)

    @commands.command(name="achcheck")
    async def ach_check(self, ctx: commands.Context):
        unlocked = await AchievementManager.check_and_unlock(
            ctx.guild.id, ctx.author.id, ctx.author, self.bot, ctx.channel)
        if not unlocked:
            await ctx.send(embed=embed_info("📋 Nenhuma conquista nova desbloqueada."))
        else:
            names = ", ".join(f"**{a.get('name')}**" for a in unlocked)
            await ctx.send(embed=embed_success(f"🏆 Você desbloqueou: {names}"))

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        if not ctx.guild or ctx.author.bot:
            return
        relevant = {"daily", "pay", "balance", "buy", "collect", "prestige",
                    "invest", "ecogive", "gameplay", "flip", "roulette"}
        if ctx.command and ctx.command.name in relevant:
            import random
            if random.random() < 0.30:
                try:
                    await AchievementManager.check_and_unlock(
                        ctx.guild.id, ctx.author.id, ctx.author, self.bot, None)
                except Exception:
                    pass


async def setup(bot):
    if bot.get_cog("EconomyAchievements") is None:
        await bot.add_cog(EconomyAchievements(bot))