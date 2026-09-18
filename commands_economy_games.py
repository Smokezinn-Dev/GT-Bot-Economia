# ============================================================
# COMMANDS_ECONOMY_GAMES.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
import random
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from collections import defaultdict

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from utils import SlashCtxAdapter

try:
    from commands_economy_events import EventManager
    HAS_EVENTS = True
except Exception:
    HAS_EVENTS = False


class GameManager:
    @staticmethod
    def get_games(guild_id: int, active_only: bool = True) -> List[Dict]:
        db = get_connection()
        query = {"guild_id": guild_id}
        if active_only:
            query["active"] = True
        return list(db["custom_games"].find(query).sort("created_at", -1))

    @staticmethod
    def get_game(guild_id: int, game_id) -> Optional[Dict]:
        db = get_connection()
        try:
            from bson import ObjectId
            if isinstance(game_id, str) and len(game_id) == 24:
                return db["custom_games"].find_one(
                    {"_id": ObjectId(game_id), "guild_id": guild_id})
            return db["custom_games"].find_one(
                {"_id": int(game_id), "guild_id": guild_id})
        except Exception:
            return None

    @staticmethod
    def create_game(guild_id: int, data: dict) -> Any:
        db = get_connection()
        data["guild_id"] = guild_id
        data["active"] = True
        data["created_at"] = datetime.utcnow()
        data["plays"] = 0
        data["total_wagered"] = 0
        data["total_paid"] = 0
        result = db["custom_games"].insert_one(data)
        return result.inserted_id

    @staticmethod
    def update_game(guild_id: int, game_id, **kwargs) -> bool:
        db = get_connection()
        try:
            from bson import ObjectId
            oid = (ObjectId(game_id)
                   if isinstance(game_id, str) and len(game_id) == 24
                   else int(game_id))
            res = db["custom_games"].update_one(
                {"_id": oid, "guild_id": guild_id},
                {"$set": kwargs})
            return res.modified_count > 0
        except Exception:
            return False

    @staticmethod
    def delete_game(guild_id: int, game_id) -> bool:
        db = get_connection()
        try:
            from bson import ObjectId
            oid = (ObjectId(game_id)
                   if isinstance(game_id, str) and len(game_id) == 24
                   else int(game_id))
            res = db["custom_games"].delete_one(
                {"_id": oid, "guild_id": guild_id})
            return res.deleted_count > 0
        except Exception:
            return False

    @staticmethod
    def add_participation(guild_id: int, game_id, user_id: int,
                          bet: int, won: bool, won_amount: int):
        db = get_connection()
        db["game_participations"].insert_one({
            "guild_id": guild_id,
            "game_id": str(game_id),
            "user_id": user_id,
            "bet_amount": bet,
            "won": won,
            "won_amount": won_amount,
            "played_at": datetime.utcnow()
        })
        inc = {"plays": 1, "total_wagered": bet}
        if won:
            inc["total_paid"] = won_amount
        try:
            from bson import ObjectId
            oid = (ObjectId(game_id)
                   if isinstance(game_id, str) and len(str(game_id)) == 24
                   else game_id)
            db["custom_games"].update_one({"_id": oid}, {"$inc": inc})
        except Exception:
            pass

    @staticmethod
    def get_user_history(guild_id: int, user_id: int, limit: int = 10) -> List[Dict]:
        db = get_connection()
        return list(
            db["game_participations"]
            .find({"guild_id": guild_id, "user_id": user_id})
            .sort("played_at", -1)
            .limit(limit)
        )


class EconomyGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldowns: Dict[str, float] = {}
        self._cooldown_cleanup = 0.0

    def _format(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    def _cleanup_cooldowns(self):
        now = time.time()
        if now - self._cooldown_cleanup < 180:
            return
        self._cooldown_cleanup = now
        expired = [k for k, ts in self._cooldowns.items() if now - ts > 600]
        for k in expired:
            del self._cooldowns[k]

    def _check_cooldown(self, guild_id: int, user_id: int,
                        game_id, cooldown: int) -> int:
        key = f"{guild_id}:{user_id}:{game_id}"
        last = self._cooldowns.get(key, 0)
        remaining = int(cooldown - (time.time() - last))
        return max(0, remaining)

    def _set_cooldown(self, guild_id: int, user_id: int, game_id):
        key = f"{guild_id}:{user_id}:{game_id}"
        self._cooldowns[key] = time.time()
        self._cleanup_cooldowns()

    @commands.command(name="gamecreate")
    @commands.has_permissions(administrator=True)
    async def game_create(self, ctx: commands.Context, name: str, game_type: str,
                          cost: int, prize_multiplier: float, win_chance: float,
                          max_players: int = 1, cooldown: int = 30,
                          *, description: str = ""):
        gtype = game_type.lower()
        if gtype not in ("roulette", "dice", "custom", "slots"):
            return await ctx.send(embed=embed_error(
                "❌ Tipos: `roulette`, `dice`, `custom`, `slots`"))

        if cost <= 0 or prize_multiplier < 1.0 or not (0 < win_chance <= 1):
            return await ctx.send(embed=embed_error(
                "❌ Valores inválidos.\n"
                "cost > 0 | prize_multiplier ≥ 1 | win_chance entre 0 e 1"))

        db = get_connection()
        if db["custom_games"].find_one({"guild_id": ctx.guild.id, "name": name}):
            return await ctx.send(embed=embed_error(
                f"❌ Já existe um jogo chamado `{name}`."))

        game_id = GameManager.create_game(ctx.guild.id, {
            "name": name,
            "description": description,
            "game_type": gtype,
            "cost": cost,
            "prize_multiplier": prize_multiplier,
            "win_chance": win_chance,
            "max_players": max_players,
            "cooldown": cooldown,
            "created_by": ctx.author.id
        })

        embed = discord.Embed(
            title="🎮 JOGO CRIADO!",
            description=f"**{name}** está disponível!",
            color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="🆔 ID", value=f"`{str(game_id)[:8]}`", inline=True)
        embed.add_field(name="🎯 Tipo", value=gtype, inline=True)
        embed.add_field(name="💰 Custo",
                        value=self._format(ctx.guild.id, cost), inline=True)
        embed.add_field(name="📈 Multiplicador",
                        value=f"x{prize_multiplier}", inline=True)
        embed.add_field(name="🎲 Chance",
                        value=f"{win_chance*100:.0f}%", inline=True)
        embed.add_field(name="⏳ Cooldown", value=f"{cooldown}s", inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="gamecreate", description="🎮 Cria um jogo customizado")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        name="Nome do jogo",
        game_type="roulette/dice/custom/slots",
        cost="Custo para jogar",
        prize_multiplier="Multiplicador do prêmio",
        win_chance="Chance de vitória (0.0 a 1.0)",
        cooldown="Cooldown em segundos",
        description="Descrição"
    )
    async def game_create_slash(self, interaction: discord.Interaction, name: str,
                                game_type: str, cost: int, prize_multiplier: float,
                                win_chance: float, cooldown: int = 30,
                                description: str = ""):
        await self.game_create(
            SlashCtxAdapter(interaction), name, game_type, cost,
            prize_multiplier, win_chance, 1, cooldown, description=description)

    @commands.command(name="gameedit")
    @commands.has_permissions(administrator=True)
    async def game_edit(self, ctx: commands.Context, game_id: str, field: str,
                        *, value: str):
        game = GameManager.get_game(ctx.guild.id, game_id)
        if not game:
            return await ctx.send(embed=embed_error(
                f"❌ Jogo `{game_id}` não encontrado."))

        valid = ["name", "description", "cost", "prize_multiplier",
                 "win_chance", "max_players", "cooldown", "active"]
        if field not in valid:
            return await ctx.send(embed=embed_error(f"❌ Campos: {', '.join(valid)}"))

        try:
            if field in ("cost", "max_players", "cooldown"):
                parsed = int(value)
            elif field in ("prize_multiplier", "win_chance"):
                parsed = float(value)
            elif field == "active":
                parsed = value.lower() in ("true", "1", "sim", "on", "yes")
            else:
                parsed = value
        except Exception:
            return await ctx.send(embed=embed_error("❌ Valor inválido."))

        GameManager.update_game(ctx.guild.id, game_id, **{field: parsed})
        await ctx.send(embed=embed_success(f"✅ `{field}` atualizado para `{parsed}`"))

    @commands.command(name="gamedelete")
    @commands.has_permissions(administrator=True)
    async def game_delete(self, ctx: commands.Context, game_id: str):
        game = GameManager.get_game(ctx.guild.id, game_id)
        if not game:
            return await ctx.send(embed=embed_error(
                f"❌ Jogo `{game_id}` não encontrado."))
        GameManager.delete_game(ctx.guild.id, game_id)
        await ctx.send(embed=embed_success(f"✅ Jogo **{game.get('name')}** deletado!"))

    @commands.command(name="gamelist", aliases=["games", "jogos"])
    async def game_list(self, ctx: commands.Context):
        games = GameManager.get_games(ctx.guild.id)
        if not games:
            return await ctx.send(embed=embed_info(
                "📋 Nenhum jogo ativo. Admins: `.gamecreate`"))

        embed = discord.Embed(
            title="🎮 JOGOS DISPONÍVEIS",
            description="Use `.gameplay <id>` para jogar",
            color=discord.Color.blue(), timestamp=datetime.utcnow())
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        for game in games[:12]:
            gid = str(game["_id"])[:8]
            embed.add_field(
                name=f"#{gid} — {game['name']}",
                value=(
                    f"🎯 `{game.get('game_type')}`\n"
                    f"💰 {self._format(ctx.guild.id, game['cost'])}\n"
                    f"📈 x{game.get('prize_multiplier', 1)} | "
                    f"🎲 {game.get('win_chance', 0)*100:.0f}%\n"
                    f"⏳ {game.get('cooldown', 30)}s"
                ),
                inline=True)

        embed.set_footer(text=f"Total: {len(games)} jogos")
        await ctx.send(embed=embed)

    @app_commands.command(name="gamelist", description="🎮 Lista os jogos disponíveis")
    async def game_list_slash(self, interaction: discord.Interaction):
        await self.game_list(SlashCtxAdapter(interaction))

    @commands.command(name="gameplay", aliases=["jogar", "play"])
    async def game_play(self, ctx: commands.Context, game_id: str):
        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))

        game = GameManager.get_game(guild_id, game_id)
        if not game:
            return await ctx.send(embed=embed_error(
                f"❌ Jogo `{game_id}` não encontrado. Use `.gamelist`."))
        if not game.get("active", True):
            return await ctx.send(embed=embed_error("❌ Este jogo está desativado."))

        cooldown = int(game.get("cooldown", 30))
        remaining = self._check_cooldown(guild_id, user_id, game["_id"], cooldown)
        if remaining > 0:
            return await ctx.send(embed=embed_warning(
                f"⏳ Aguarde **{remaining}s** para jogar novamente."))

        cost = int(game["cost"])
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < cost:
            return await ctx.send(embed=embed_error(
                f"❌ Saldo insuficiente!\n"
                f"Precisa de {self._format(guild_id, cost)} | "
                f"Você tem {self._format(guild_id, balance)}"
            ))

        if not EconomyManager.remove_balance(guild_id, user_id, cost,
                                              f"Jogo: {game['name']}", "game"):
            return await ctx.send(embed=embed_error("❌ Falha ao processar aposta."))

        win_chance = float(game.get("win_chance", 0.3))
        prize_mult = float(game.get("prize_multiplier", 2.0))

        if HAS_EVENTS:
            event_mult = EventManager.get_earn_multiplier(guild_id)
            if event_mult > 1.0:
                prize_mult *= min(event_mult, 1.5)

        won = random.random() < win_chance
        winnings = int(cost * prize_mult) if won else 0

        if won and winnings > 0:
            EconomyManager.add_balance(guild_id, user_id, winnings,
                                        f"Vitória: {game['name']}", "game_win")

        GameManager.add_participation(guild_id, game["_id"], user_id, cost, won, winnings)
        self._set_cooldown(guild_id, user_id, game["_id"])

        new_balance = EconomyManager.get_balance(guild_id, user_id)

        if won:
            embed = discord.Embed(
                title="🎉 VOCÊ GANHOU!",
                description=f"**{game['name']}** — VITÓRIA",
                color=discord.Color.green(), timestamp=datetime.utcnow())
            embed.add_field(name="🏆 Prêmio",
                            value=self._format(guild_id, winnings), inline=True)
        else:
            embed = discord.Embed(
                title="😢 VOCÊ PERDEU!",
                description=f"**{game['name']}** — DERROTA",
                color=discord.Color.red(), timestamp=datetime.utcnow())

        embed.add_field(name="💰 Apostou",
                        value=self._format(guild_id, cost), inline=True)
        embed.add_field(name="💰 Saldo",
                        value=self._format(guild_id, new_balance), inline=True)
        embed.set_footer(text=f"Chance: {win_chance*100:.0f}% | x{prize_mult:.1f}")
        await ctx.send(embed=embed)

    @app_commands.command(name="gameplay", description="🎮 Joga um jogo")
    @app_commands.describe(game_id="ID do jogo")
    async def game_play_slash(self, interaction: discord.Interaction, game_id: str):
        await self.game_play(SlashCtxAdapter(interaction), game_id)

    @commands.command(name="gamehistory", aliases=["gh"])
    async def game_history(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        history = GameManager.get_user_history(ctx.guild.id, member.id, 10)

        embed = discord.Embed(
            title=f"📜 Histórico de Jogos — {member.display_name}",
            color=member.color or discord.Color.blue(),
            timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)

        if not history:
            embed.description = "Nenhuma partida registrada."
        else:
            wins = sum(1 for h in history if h.get("won"))
            total_bet = sum(h.get("bet_amount", 0) for h in history)
            total_won = sum(h.get("won_amount", 0) for h in history if h.get("won"))

            embed.add_field(
                name="📊 Resumo (últimas 10)",
                value=(f"Vitórias: **{wins}**/{len(history)}\n"
                       f"Apostado: {self._format(ctx.guild.id, total_bet)}\n"
                       f"Ganho: {self._format(ctx.guild.id, total_won)}"),
                inline=False)

            lines = []
            for h in history[:8]:
                icon = "✅" if h.get("won") else "❌"
                amount = h.get("won_amount") if h.get("won") else h.get("bet_amount", 0)
                ts = h.get("played_at", datetime.utcnow())
                ts_str = ts.strftime("%d/%m %H:%M") if hasattr(ts, "strftime") else ""
                lines.append(f"{icon} {self._format(ctx.guild.id, amount)} — `{ts_str}`")
            embed.add_field(name="Partidas", value="\n".join(lines), inline=False)

        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("EconomyGames") is None:
        await bot.add_cog(EconomyGames(bot))