# ============================================================
# COMMANDS_ECONOMY_GAMBLING.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from utils import safe_object_id, SlashCtxAdapter

try:
    from commands_economy_events import EventManager
    HAS_EVENTS = True
except Exception:
    HAS_EVENTS = False


class EconomyGambling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cd: Dict[str, float] = {}
        self._cd_cleanup = 0.0
        self._giveaway_tasks: Dict[str, asyncio.Task] = {}
        self.cleanup_loop.start()

    def cog_unload(self):
        self.cleanup_loop.cancel()
        for t in self._giveaway_tasks.values():
            t.cancel()

    def _format(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    def _check_cd(self, guild_id: int, user_id: int, cmd: str, seconds: float = 2.0) -> bool:
        key = f"{guild_id}:{user_id}:{cmd}"
        now = time.time()
        last = self._cd.get(key, 0)
        if now - last < seconds:
            return True
        self._cd[key] = now
        if now - self._cd_cleanup > 120:
            self._cd_cleanup = now
            expired = [k for k, ts in self._cd.items() if now - ts > 300]
            for k in expired:
                del self._cd[k]
        return False

    @tasks.loop(minutes=10)
    async def cleanup_loop(self):
        try:
            db = get_connection()
            db["economy_giveaways"].update_many(
                {"active": True, "end_time": {"$lt": datetime.utcnow()}},
                {"$set": {"active": False}}
            )
            done = [k for k, t in self._giveaway_tasks.items() if t.done()]
            for k in done:
                del self._giveaway_tasks[k]
        except Exception:
            pass

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # FLIP
    # ============================================================

    @commands.command(name="flip", aliases=["coinflip", "cf"])
    async def flip(self, ctx: commands.Context, amount: int):
        if amount < 1:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))
        if amount > 500_000:
            return await ctx.send(embed=embed_error("❌ Aposta máxima: 500.000"))

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        if self._check_cd(guild_id, user_id, "flip", 1.5):
            return await ctx.send(embed=embed_warning("⏳ Aguarde um momento..."), delete_after=3)

        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < amount:
            return await ctx.send(embed=embed_error(
                f"❌ Saldo insuficiente! Você tem {self._format(guild_id, balance)}"
            ))

        win = random.random() < 0.49
        side = "Cara" if random.random() < 0.5 else "Coroa"

        if not EconomyManager.remove_balance(guild_id, user_id, amount,
                                              f"Flip {side}", "flip"):
            return await ctx.send(embed=embed_error("❌ Falha ao processar aposta."))

        if win:
            winnings = int(amount * 1.96)
            EconomyManager.add_balance(guild_id, user_id, winnings,
                                        f"Ganho no flip ({side})", "flip_win")
            embed = discord.Embed(
                title="🪙 CARA OU COROA",
                description=f"Resultado: **{side}**\n🎉 Você ganhou **{self._format(guild_id, winnings)}**!",
                color=discord.Color.green(), timestamp=datetime.utcnow())
        else:
            embed = discord.Embed(
                title="🪙 CARA OU COROA",
                description=f"Resultado: **{side}**\n😢 Você perdeu **{self._format(guild_id, amount)}**!",
                color=discord.Color.red(), timestamp=datetime.utcnow())

        new_bal = EconomyManager.get_balance(guild_id, user_id)
        embed.add_field(name="💰 Saldo", value=self._format(guild_id, new_bal), inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="flip", description="🪙 Aposta em cara ou coroa")
    @app_commands.describe(amount="Valor da aposta")
    async def flip_slash(self, interaction: discord.Interaction, amount: int):
        await self.flip(SlashCtxAdapter(interaction), amount)

    # ============================================================
    # DADOS
    # ============================================================

    @commands.command(name="rollgamble", aliases=["dice", "dados"])
    async def roll_gamble(self, ctx: commands.Context, amount: int):
        if amount < 1:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))
        if amount > 500_000:
            return await ctx.send(embed=embed_error("❌ Aposta máxima: 500.000"))

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        if self._check_cd(guild_id, user_id, "dice", 1.5):
            return await ctx.send(embed=embed_warning("⏳ Aguarde..."), delete_after=3)

        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < amount:
            return await ctx.send(embed=embed_error(f"❌ Saldo insuficiente!"))

        if not EconomyManager.remove_balance(guild_id, user_id, amount,
                                              "Aposta nos dados", "dice"):
            return await ctx.send(embed=embed_error("❌ Falha ao processar."))

        roll = random.randint(1, 6)
        multipliers = {1: 0.0, 2: 0.0, 3: 0.5, 4: 0.8, 5: 1.5, 6: 2.8}
        mult = multipliers.get(roll, 0.0)

        if mult > 0:
            winnings = int(amount * mult)
            EconomyManager.add_balance(guild_id, user_id, winnings,
                                        f"Dados: {roll}", "dice_win")
            embed = discord.Embed(
                title="🎲 DADOS",
                description=(f"Resultado: **{roll}**\nMultiplicador **x{mult}**\n"
                             f"🎉 Você ganhou **{self._format(guild_id, winnings)}**!"),
                color=discord.Color.green(), timestamp=datetime.utcnow())
        else:
            embed = discord.Embed(
                title="🎲 DADOS",
                description=(f"Resultado: **{roll}**\n"
                             f"😢 Você perdeu **{self._format(guild_id, amount)}**!"),
                color=discord.Color.red(), timestamp=datetime.utcnow())

        embed.add_field(name="💰 Saldo",
                        value=self._format(guild_id, EconomyManager.get_balance(guild_id, user_id)))
        await ctx.send(embed=embed)

    @app_commands.command(name="rollgamble", description="🎲 Aposta nos dados")
    @app_commands.describe(amount="Valor da aposta")
    async def roll_gamble_slash(self, interaction: discord.Interaction, amount: int):
        await self.roll_gamble(SlashCtxAdapter(interaction), amount)

    # ============================================================
    # ROLETA
    # ============================================================

    @commands.command(name="roulette", aliases=["roleta", "rr"])
    async def roulette(self, ctx: commands.Context, amount: int):
        if amount < 1:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))
        if amount > 250_000:
            return await ctx.send(embed=embed_error("❌ Aposta máxima na roleta: 250.000"))

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        if self._check_cd(guild_id, user_id, "roulette", 2.0):
            return await ctx.send(embed=embed_warning("⏳ Aguarde..."), delete_after=3)

        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente!"))

        if not EconomyManager.remove_balance(guild_id, user_id, amount,
                                              "Roleta Russa", "roulette"):
            return await ctx.send(embed=embed_error("❌ Falha ao processar."))

        chamber = random.randint(1, 6)
        if chamber == 1:
            embed = discord.Embed(
                title="🔫 ROLETA RUSSA",
                description=f"💀 **BOOM!** Você perdeu **{self._format(guild_id, amount)}**!",
                color=discord.Color.dark_red(), timestamp=datetime.utcnow())
        else:
            winnings = int(amount * 1.90)
            EconomyManager.add_balance(guild_id, user_id, winnings,
                                        "Sobreviveu à roleta", "roulette_win")
            embed = discord.Embed(
                title="🔫 ROLETA RUSSA",
                description=(f"🎉 *click* ... Sobreviveu!\n"
                             f"Você ganhou **{self._format(guild_id, winnings)}**!"),
                color=discord.Color.green(), timestamp=datetime.utcnow())

        embed.add_field(name="💰 Saldo",
                        value=self._format(guild_id, EconomyManager.get_balance(guild_id, user_id)))
        await ctx.send(embed=embed)

    @app_commands.command(name="roulette", description="🔫 Roleta Russa")
    @app_commands.describe(amount="Valor da aposta")
    async def roulette_slash(self, interaction: discord.Interaction, amount: int):
        await self.roulette(SlashCtxAdapter(interaction), amount)

    # ============================================================
    # SLOTS
    # ============================================================

    @commands.command(name="slots", aliases=["slot", "caça"])
    async def slots(self, ctx: commands.Context, amount: int):
        if amount < 1:
            return await ctx.send(embed=embed_error("❌ Valor deve ser positivo!"))
        if amount > 100_000:
            return await ctx.send(embed=embed_error("❌ Aposta máxima nos slots: 100.000"))

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))
        if self._check_cd(guild_id, user_id, "slots", 2.0):
            return await ctx.send(embed=embed_warning("⏳ Aguarde..."), delete_after=3)

        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente!"))

        if not EconomyManager.remove_balance(guild_id, user_id, amount, "Slots", "slots"):
            return await ctx.send(embed=embed_error("❌ Falha ao processar."))

        symbols = ["🍒", "🍋", "🔔", "⭐", "💎", "7️⃣"]
        weights = [30, 25, 20, 12, 8, 5]
        reels = random.choices(symbols, weights=weights, k=3)

        if reels[0] == reels[1] == reels[2]:
            pay = {"🍒": 3, "🍋": 4, "🔔": 6, "⭐": 10, "💎": 20, "7️⃣": 40}
            mult = pay.get(reels[0], 3)
            winnings = int(amount * mult)
            result_txt = (f"**JACKPOT!** {' '.join(reels)}\n"
                          f"🎉 x{mult} → **{self._format(guild_id, winnings)}**")
            color = discord.Color.gold()
            EconomyManager.add_balance(guild_id, user_id, winnings,
                                        "Slots jackpot", "slots_win")
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            winnings = int(amount * 1.4)
            result_txt = (f"{' '.join(reels)}\n"
                          f"✨ Par! Você ganhou **{self._format(guild_id, winnings)}**")
            color = discord.Color.green()
            EconomyManager.add_balance(guild_id, user_id, winnings,
                                        "Slots par", "slots_win")
        else:
            result_txt = f"{' '.join(reels)}\n😢 Sem combinação..."
            color = discord.Color.red()

        embed = discord.Embed(
            title="🎰 SLOTS",
            description=result_txt,
            color=color, timestamp=datetime.utcnow())
        embed.add_field(name="💰 Saldo",
                        value=self._format(guild_id, EconomyManager.get_balance(guild_id, user_id)))
        await ctx.send(embed=embed)

    # ============================================================
    # GIVEAWAY
    # ============================================================

    @commands.command(name="giveaway")
    @commands.has_permissions(administrator=True)
    async def giveaway(self, ctx: commands.Context, prize: str,
                       winners: int = 1, duration: str = "1h"):
        duration_map = {"m": 60, "h": 3600, "d": 86400}
        unit = duration[-1].lower()
        if unit not in duration_map or not duration[:-1].isdigit():
            return await ctx.send(embed=embed_error("❌ Use duração como: `10m`, `1h`, `2d`"))

        seconds = int(duration[:-1]) * duration_map[unit]
        if seconds < 60 or seconds > 86400 * 7:
            return await ctx.send(embed=embed_error("❌ Duração entre 1 minuto e 7 dias."))

        end_time = datetime.utcnow() + timedelta(seconds=seconds)

        embed = discord.Embed(
            title="🎉 SORTEIO!",
            description=f"**Prêmio:** {prize}\n**Vencedores:** {winners}",
            color=discord.Color.gold(), timestamp=datetime.utcnow())
        embed.add_field(name="⏳ Termina",
                        value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
        embed.add_field(name="📌 Participar",
                        value="Reaja com 🎉 **ou** compre tickets com `.ticket`", inline=False)
        embed.set_footer(text=f"Criado por {ctx.author.display_name}")

        msg = await ctx.send(embed=embed)
        try:
            await msg.add_reaction("🎉")
        except Exception:
            pass

        db = get_connection()
        result = db["economy_giveaways"].insert_one({
            "guild_id": ctx.guild.id,
            "channel_id": ctx.channel.id,
            "message_id": msg.id,
            "prize": prize,
            "winners": max(1, min(winners, 20)),
            "tickets_price": 25,
            "end_time": end_time,
            "created_by": ctx.author.id,
            "entrants": [],
            "winners_list": [],
            "active": True,
            "created_at": datetime.utcnow()
        })
        giveaway_id = str(result.inserted_id)

        task = asyncio.create_task(self._finish_giveaway(
            ctx.guild.id, ctx.channel.id, msg.id, end_time, giveaway_id))
        self._giveaway_tasks[giveaway_id] = task

        await ctx.send(embed=embed_info(
            f"🎫 ID do sorteio: `{giveaway_id[:8]}` (use com `.ticket`)"), delete_after=15)

    async def _finish_giveaway(self, guild_id: int, channel_id: int, message_id: int,
                               end_time: datetime, giveaway_id: str):
        try:
            wait = (end_time - datetime.utcnow()).total_seconds()
            if wait > 0:
                await asyncio.sleep(wait)

            db = get_connection()
            giveaway = None
            oid = safe_object_id(giveaway_id)
            if oid:
                giveaway = db["economy_giveaways"].find_one(
                    {"_id": oid, "guild_id": guild_id})
            if not giveaway:
                giveaway = db["economy_giveaways"].find_one(
                    {"message_id": message_id, "guild_id": guild_id})

            if not giveaway or not giveaway.get("active"):
                return

            entrants = giveaway.get("entrants", []) or []
            channel = self.bot.get_channel(channel_id)
            reaction_users = []
            if channel:
                try:
                    msg = await channel.fetch_message(message_id)
                    for reaction in msg.reactions:
                        if str(reaction.emoji) == "🎉":
                            async for user in reaction.users():
                                if not user.bot:
                                    reaction_users.append(user.id)
                except Exception:
                    pass

            all_entrants = list(set(entrants + reaction_users))
            winners_count = min(giveaway.get("winners", 1), len(all_entrants))
            selected = random.sample(all_entrants, winners_count) if winners_count > 0 else []

            db["economy_giveaways"].update_one(
                {"_id": giveaway["_id"]},
                {"$set": {"active": False, "winners_list": selected,
                          "finished_at": datetime.utcnow()}}
            )

            prize = giveaway.get("prize", "Prêmio")
            if channel:
                if selected:
                    mentions = " ".join(f"<@{uid}>" for uid in selected)
                    await channel.send(embed=embed_success(
                        f"🏆 Sorteio **{prize}** finalizado!\nVencedor(es): {mentions}"
                    ))
                else:
                    await channel.send(embed=embed_info(
                        f"😢 Sorteio **{prize}** sem participantes."))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ Erro em _finish_giveaway: {e}")
        finally:
            self._giveaway_tasks.pop(giveaway_id, None)

    @commands.command(name="ticket")
    async def ticket(self, ctx: commands.Context, giveaway_id: str, quantity: int = 1):
        if quantity < 1 or quantity > 50:
            return await ctx.send(embed=embed_error("❌ Quantidade: 1 a 50."))

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))

        db = get_connection()
        giveaway = None
        oid = safe_object_id(giveaway_id)
        if oid:
            giveaway = db["economy_giveaways"].find_one(
                {"_id": oid, "guild_id": guild_id, "active": True})
        if not giveaway:
            actives = list(db["economy_giveaways"].find(
                {"guild_id": guild_id, "active": True}))
            giveaway = next(
                (g for g in actives if str(g["_id"]).startswith(giveaway_id)), None)

        if not giveaway:
            return await ctx.send(embed=embed_error("❌ Sorteio não encontrado ou já encerrado."))

        price = int(giveaway.get("tickets_price", 25))
        total = price * quantity
        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < total:
            return await ctx.send(embed=embed_error(
                f"❌ Precisa de {self._format(guild_id, total)} "
                f"(você tem {self._format(guild_id, balance)})"
            ))

        if not EconomyManager.remove_balance(guild_id, user_id, total,
                                              f"Tickets sorteio {str(giveaway['_id'])[:6]}",
                                              "ticket"):
            return await ctx.send(embed=embed_error("❌ Falha ao comprar tickets."))

        entrants = giveaway.get("entrants", [])
        entrants.extend([user_id] * quantity)
        db["economy_giveaways"].update_one(
            {"_id": giveaway["_id"]}, {"$set": {"entrants": entrants}})

        await ctx.send(embed=embed_success(
            f"🎫 Você comprou **{quantity}** ticket(s) para **{giveaway['prize']}**!\n"
            f"Custo: {self._format(guild_id, total)}"
        ))

    @commands.command(name="giveaways", aliases=["sorteios"])
    async def list_giveaways(self, ctx: commands.Context):
        db = get_connection()
        giveaways = list(db["economy_giveaways"].find({
            "guild_id": ctx.guild.id,
            "active": True,
            "end_time": {"$gt": datetime.utcnow()}
        }).sort("end_time", 1).limit(10))

        if not giveaways:
            return await ctx.send(embed=embed_info("📋 Nenhum sorteio ativo."))

        embed = discord.Embed(
            title="🎉 SORTEIOS ATIVOS",
            color=discord.Color.gold(), timestamp=datetime.utcnow())

        for g in giveaways:
            entrants = len(g.get("entrants", []))
            embed.add_field(
                name=f"#{str(g['_id'])[:6]} — {g['prize']}",
                value=(
                    f"🏆 {g.get('winners', 1)} vencedor(es)\n"
                    f"👥 {entrants} tickets\n"
                    f"⏳ <t:{int(g['end_time'].timestamp())}:R>\n"
                    f"🎫 {g.get('tickets_price', 25)} por ticket"
                ),
                inline=False
            )

        embed.set_footer(text="Use .ticket <id> <qtd>")
        await ctx.send(embed=embed)

    @app_commands.command(name="giveaways", description="🎉 Lista sorteios ativos")
    async def giveaways_slash(self, interaction: discord.Interaction):
        await self.list_giveaways(SlashCtxAdapter(interaction))


async def setup(bot):
    if bot.get_cog("EconomyGambling") is None:
        await bot.add_cog(EconomyGambling(bot))