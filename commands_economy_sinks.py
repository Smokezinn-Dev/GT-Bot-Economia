# ============================================================
# COMMANDS_ECONOMY_SINKS.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from utils import safe_object_id, TTLCache, SlashCtxAdapter

SINK_CONFIG = {
    "tax_enabled": False,
    "tax_threshold": 100_000,
    "tax_percent": 2.0,
    "tax_hour_utc": 3,
    "lottery_price": 100,
    "lottery_duration_hours": 24,
    "auction_min_bid": 100,
    "auction_duration_seconds": 300,
}


class EconomySinks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._auction_tasks: Dict[str, asyncio.Task] = {}
        self.tax_loop.start()
        self.lottery_loop.start()

    def cog_unload(self):
        self.tax_loop.cancel()
        self.lottery_loop.cancel()
        for t in self._auction_tasks.values():
            t.cancel()

    def _cfg(self, guild_id: int) -> dict:
        db = get_connection()
        doc = db["sinks_config"].find_one({"guild_id": guild_id}) or {}
        return {**SINK_CONFIG, **doc}

    def _update(self, guild_id: int, key: str, value):
        db = get_connection()
        db["sinks_config"].update_one({"guild_id": guild_id},
                                      {"$set": {key: value}}, upsert=True)

    @tasks.loop(minutes=10)
    async def tax_loop(self):
        try:
            now = datetime.utcnow()
            db = get_connection()
            for doc in db["sinks_config"].find({"tax_enabled": True}):
                if now.hour != int(doc.get("tax_hour_utc", 3)):
                    continue
                gid = doc["guild_id"]
                last_run = doc.get("last_tax_run")
                if last_run and last_run.date() == now.date():
                    continue

                threshold = int(doc.get("tax_threshold", 100_000))
                pct = float(doc.get("tax_percent", 2.0))
                rich = db["economy_balances"].find({
                    "guild_id": gid, "balance": {"$gt": threshold}
                })
                for bal in rich:
                    excess = bal["balance"] - threshold
                    tax = int(excess * pct / 100)
                    if tax > 0:
                        EconomyManager.remove_balance(
                            gid, bal["user_id"], tax,
                            "Imposto de rico", "tax")

                db["sinks_config"].update_one(
                    {"guild_id": gid},
                    {"$set": {"last_tax_run": now}}
                )
        except Exception as e:
            print(f"⚠️ Erro tax_loop: {e}")

    @tax_loop.before_loop
    async def before_tax(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def lottery_loop(self):
        try:
            db = get_connection()
            now = datetime.utcnow()
            expired = list(db["lottery_rounds"].find({
                "active": True, "end_time": {"$lte": now}
            }))
            for rnd in expired:
                await self._draw_lottery(rnd)
        except Exception:
            pass

    @lottery_loop.before_loop
    async def before_lottery(self):
        await self.bot.wait_until_ready()

    async def _draw_lottery(self, rnd: dict):
        db = get_connection()
        gid = rnd["guild_id"]
        round_id = rnd["round_id"]
        tickets = list(db["lottery_tickets"].find({
            "guild_id": gid, "round_id": round_id
        }))
        if not tickets:
            db["lottery_rounds"].update_one(
                {"_id": rnd["_id"]}, {"$set": {"active": False}})
            return

        pool = []
        for t in tickets:
            pool.extend([t["user_id"]] * t["quantity"])
        winner = random.choice(pool)
        total = len(pool) * int(rnd.get("price", 100))
        prize = int(total * 0.8)
        EconomyManager.add_balance(gid, winner, prize, "Loteria", "lottery_win")

        db["lottery_rounds"].update_one(
            {"_id": rnd["_id"]},
            {"$set": {"active": False, "winner": winner, "prize": prize,
                      "drawn_at": datetime.utcnow()}})

        channel = self.bot.get_channel(rnd.get("channel_id", 0))
        if channel:
            try:
                await channel.send(embed=embed_success(
                    f"🎉 **LOTERIA** — Rodada #{round_id}!\n"
                    f"🏆 Vencedor: <@{winner}>\n"
                    f"💰 Prêmio: **{EconomyManager.format_currency(gid, prize)}**\n"
                    f"🎫 Tickets vendidos: {len(pool)}"))
            except Exception:
                pass

    @commands.command(name="taxconfig", aliases=["imposto"])
    @commands.has_permissions(administrator=True)
    async def tax_config(self, ctx, action: str = None, *, value: str = None):
        cfg = self._cfg(ctx.guild.id)
        if not action:
            embed = discord.Embed(title="💰 IMPOSTO DE RICO",
                                  color=discord.Color.blurple(),
                                  timestamp=datetime.utcnow())
            embed.add_field(name="Status",
                            value="✅ ON" if cfg["tax_enabled"] else "❌ OFF", inline=True)
            embed.add_field(name="Limite",
                            value=EconomyManager.format_currency(ctx.guild.id, cfg["tax_threshold"]),
                            inline=True)
            embed.add_field(name="Taxa", value=f"{cfg['tax_percent']}%", inline=True)
            embed.add_field(name="Hora (UTC)", value=f"{cfg['tax_hour_utc']}h", inline=True)
            embed.add_field(
                name="Como usar",
                value="`.taxconfig on/off`\n`.taxconfig limite 100000`\n"
                      "`.taxconfig taxa 2`\n`.taxconfig hora 3`",
                inline=False)
            return await ctx.send(embed=embed)

        if action in ("on", "off"):
            self._update(ctx.guild.id, "tax_enabled", action == "on")
            return await ctx.send(embed=embed_success(
                f"✅ Imposto {'ativado' if action == 'on' else 'desativado'}!"))

        if action == "limite" and value:
            try:
                self._update(ctx.guild.id, "tax_threshold", int(value))
                await ctx.send(embed=embed_success(f"✅ Limite: {value}"))
            except Exception:
                await ctx.send(embed=embed_error("❌ Valor inválido."))
            return

        if action == "taxa" and value:
            try:
                self._update(ctx.guild.id, "tax_percent", float(value))
                await ctx.send(embed=embed_success(f"✅ Taxa: {value}%"))
            except Exception:
                await ctx.send(embed=embed_error("❌ Valor inválido."))
            return

        if action == "hora" and value:
            try:
                self._update(ctx.guild.id, "tax_hour_utc", int(value) % 24)
                await ctx.send(embed=embed_success(f"✅ Hora: {value}h UTC"))
            except Exception:
                await ctx.send(embed=embed_error("❌ Valor inválido."))
            return

        await ctx.send(embed=embed_error("❌ Ação inválida."))

    @commands.command(name="lottery", aliases=["loteria"])
    async def lottery(self, ctx, action: str = None, quantity: int = 1):
        db = get_connection()
        guild_id = ctx.guild.id

        if action == "buy" or action is None:
            quantity = max(1, min(quantity, 100))
            cfg = self._cfg(guild_id)

            rnd = db["lottery_rounds"].find_one(
                {"guild_id": guild_id, "active": True,
                 "end_time": {"$gt": datetime.utcnow()}})
            if not rnd:
                last = db["lottery_rounds"].find_one(
                    {"guild_id": guild_id}, sort=[("round_id", -1)])
                round_id = (last["round_id"] + 1) if last else 1
                end_time = datetime.utcnow() + timedelta(hours=cfg["lottery_duration_hours"])
                result = db["lottery_rounds"].insert_one({
                    "guild_id": guild_id,
                    "round_id": round_id,
                    "price": cfg["lottery_price"],
                    "end_time": end_time,
                    "active": True,
                    "channel_id": ctx.channel.id,
                    "created_at": datetime.utcnow()
                })
                rnd = db["lottery_rounds"].find_one({"_id": result.inserted_id})

            price = int(rnd.get("price", 100))
            total = price * quantity
            bal = EconomyManager.get_balance(guild_id, ctx.author.id)
            if bal < total:
                return await ctx.send(embed=embed_error(
                    f"❌ Precisa de {EconomyManager.format_currency(guild_id, total)}.\n"
                    f"Você tem {EconomyManager.format_currency(guild_id, bal)}"))

            if not EconomyManager.remove_balance(guild_id, ctx.author.id, total,
                                                  f"Loteria {quantity}x", "lottery"):
                return await ctx.send(embed=embed_error("❌ Falha."))

            db["lottery_tickets"].update_one(
                {"guild_id": guild_id, "round_id": rnd["round_id"], "user_id": ctx.author.id},
                {"$inc": {"quantity": quantity}}, upsert=True)

            my_doc = db["lottery_tickets"].find_one(
                {"guild_id": guild_id, "round_id": rnd["round_id"], "user_id": ctx.author.id})
            my_tickets = my_doc.get("quantity", 0) if my_doc else 0

            total_agg = list(db["lottery_tickets"].aggregate([
                {"$match": {"guild_id": guild_id, "round_id": rnd["round_id"]}},
                {"$group": {"_id": None, "total": {"$sum": "$quantity"}}}
            ]))
            total_count = total_agg[0]["total"] if total_agg else 0

            embed = discord.Embed(
                title="🎰 LOTERIA",
                description=f"Você comprou **{quantity}** ticket(s)!",
                color=discord.Color.gold(), timestamp=datetime.utcnow())
            embed.add_field(name="🎫 Seus tickets", value=str(my_tickets), inline=True)
            embed.add_field(name="🎫 Total vendidos", value=str(total_count), inline=True)
            embed.add_field(name="💰 Custo",
                            value=EconomyManager.format_currency(guild_id, total),
                            inline=True)
            embed.add_field(name="⏰ Encerra",
                            value=f"<t:{int(rnd['end_time'].timestamp())}:R>",
                            inline=False)
            embed.add_field(name="🏆 Prêmio estimado",
                            value=EconomyManager.format_currency(
                                guild_id, int(total_count * price * 0.8)),
                            inline=False)
            return await ctx.send(embed=embed)

        if action == "info":
            rnd = db["lottery_rounds"].find_one(
                {"guild_id": guild_id, "active": True,
                 "end_time": {"$gt": datetime.utcnow()}})
            if not rnd:
                return await ctx.send(embed=embed_info("📋 Nenhuma loteria ativa."))
            total_agg = list(db["lottery_tickets"].aggregate([
                {"$match": {"guild_id": guild_id, "round_id": rnd["round_id"]}},
                {"$group": {"_id": None, "total": {"$sum": "$quantity"}}}
            ]))
            total_count = total_agg[0]["total"] if total_agg else 0
            prize = int(total_count * rnd.get("price", 100) * 0.8)
            embed = discord.Embed(title=f"🎰 LOTERIA #{rnd['round_id']}",
                                  color=discord.Color.gold(),
                                  timestamp=datetime.utcnow())
            embed.add_field(name="🎫 Tickets", value=str(total_count), inline=True)
            embed.add_field(name="💰 Preço",
                            value=EconomyManager.format_currency(guild_id, rnd["price"]),
                            inline=True)
            embed.add_field(name="🏆 Prêmio",
                            value=EconomyManager.format_currency(guild_id, prize),
                            inline=True)
            embed.add_field(name="⏰ Encerra",
                            value=f"<t:{int(rnd['end_time'].timestamp())}:R>",
                            inline=False)
            return await ctx.send(embed=embed)

        await ctx.send(embed=embed_error("❌ Use: `.lottery buy [qtd]` ou `.lottery info`"))

    @commands.command(name="auction", aliases=["leilao"])
    @commands.has_permissions(administrator=True)
    async def auction(self, ctx, action: str = None, *, args: str = None):
        db = get_connection()
        guild_id = ctx.guild.id

        if action == "start":
            if not args:
                return await ctx.send(embed=embed_error(
                    "❌ Use: `.auction start <item> | <preço mínimo>`"))
            parts = args.split("|")
            if len(parts) != 2:
                return await ctx.send(embed=embed_error(
                    "❌ Formato: `.auction start Nome do item | 1000`"))
            item_name = parts[0].strip()
            try:
                min_bid = int(parts[1].strip())
            except Exception:
                return await ctx.send(embed=embed_error("❌ Preço inválido."))

            cfg = self._cfg(guild_id)
            duration = cfg["auction_duration_seconds"]
            end_time = datetime.utcnow() + timedelta(seconds=duration)

            result = db["auctions"].insert_one({
                "guild_id": guild_id,
                "item": item_name,
                "min_bid": min_bid,
                "current_bid": 0,
                "current_bidder": None,
                "end_time": end_time,
                "active": True,
                "channel_id": ctx.channel.id,
                "created_at": datetime.utcnow()
            })
            auc_id = str(result.inserted_id)

            embed = discord.Embed(
                title="⚖️ LEILÃO INICIADO!",
                description=(
                    f"**{item_name}**\n\n"
                    f"💰 Preço mínimo: {EconomyManager.format_currency(guild_id, min_bid)}\n"
                    f"⏰ Termina em {duration//60}min\n\n"
                    f"Use: `.bid {auc_id[:8]} <valor>`"
                ),
                color=discord.Color.gold(), timestamp=datetime.utcnow())
            embed.set_footer(text=f"ID: {auc_id[:8]}")
            await ctx.send(embed=embed)

            task = asyncio.create_task(self._end_auction(guild_id, auc_id, duration))
            self._auction_tasks[auc_id] = task
            return

        if action == "cancel":
            auc = None
            if args:
                oid = safe_object_id(args) if len(args) == 24 else None
                if oid:
                    auc = db["auctions"].find_one({"_id": oid, "guild_id": guild_id})
                if not auc:
                    auc = next((a for a in db["auctions"].find(
                        {"guild_id": guild_id, "active": True})
                        if str(a["_id"]).startswith(args)), None)
            if not auc:
                return await ctx.send(embed=embed_error("❌ Leilão não encontrado."))
            db["auctions"].update_one({"_id": auc["_id"]}, {"$set": {"active": False}})
            t = self._auction_tasks.pop(str(auc["_id"]), None)
            if t:
                t.cancel()
            return await ctx.send(embed=embed_success("✅ Leilão cancelado."))

        auctions = list(db["auctions"].find(
            {"guild_id": guild_id, "active": True,
             "end_time": {"$gt": datetime.utcnow()}}))
        if not auctions:
            return await ctx.send(embed=embed_info("📋 Nenhum leilão ativo."))

        embed = discord.Embed(title="⚖️ LEILÕES ATIVOS",
                              color=discord.Color.gold(),
                              timestamp=datetime.utcnow())
        for a in auctions:
            cur = a.get("current_bid", 0)
            bidder = a.get("current_bidder")
            embed.add_field(
                name=f"{str(a['_id'])[:8]} — {a['item']}",
                value=(f"💰 Atual: "
                       f"{EconomyManager.format_currency(guild_id, cur) if cur else 'sem lances'}\n"
                       f"👤 {f'<@{bidder}>' if bidder else '—'}\n"
                       f"⏰ <t:{int(a['end_time'].timestamp())}:R>"),
                inline=False
            )
        embed.set_footer(text="Use .bid <id> <valor>")
        await ctx.send(embed=embed)

    @commands.command(name="bid", aliases=["lance"])
    async def bid(self, ctx, auction_id: str, amount: int):
        db = get_connection()
        guild_id = ctx.guild.id
        oid = safe_object_id(auction_id) if len(auction_id) == 24 else None
        auc = None
        if oid:
            auc = db["auctions"].find_one(
                {"_id": oid, "guild_id": guild_id, "active": True})
        if not auc:
            auc = next((a for a in db["auctions"].find(
                {"guild_id": guild_id, "active": True})
                if str(a["_id"]).startswith(auction_id)), None)

        if not auc:
            return await ctx.send(embed=embed_error("❌ Leilão não encontrado."))
        if datetime.utcnow() >= auc["end_time"]:
            return await ctx.send(embed=embed_error("❌ Leilão já encerrou."))

        min_required = max(int(auc.get("min_bid", 0)),
                           int(auc.get("current_bid", 0)) + 1)
        if amount < min_required:
            return await ctx.send(embed=embed_error(
                f"❌ Lance mínimo: {EconomyManager.format_currency(guild_id, min_required)}"))

        bal = EconomyManager.get_balance(guild_id, ctx.author.id)
        if bal < amount:
            return await ctx.send(embed=embed_error("❌ Saldo insuficiente."))

        prev_bidder = auc.get("current_bidder")
        prev_bid = int(auc.get("current_bid", 0))

        db["auctions"].update_one(
            {"_id": auc["_id"]},
            {"$set": {"current_bid": amount, "current_bidder": ctx.author.id}})

        if prev_bidder and prev_bid > 0:
            EconomyManager.add_balance(guild_id, prev_bidder, prev_bid,
                                        "Reembolso leilão", "auction_refund")

        EconomyManager.remove_balance(guild_id, ctx.author.id, amount,
                                       "Lance leilão", "auction_bid")

        await ctx.send(embed=embed_success(
            f"✅ Lance de {EconomyManager.format_currency(guild_id, amount)} "
            f"em **{auc['item']}**!"))

    async def _end_auction(self, guild_id: int, auc_id: str, duration: int):
        try:
            await asyncio.sleep(duration)
            db = get_connection()
            oid = safe_object_id(auc_id)
            auc = db["auctions"].find_one({"_id": oid})
            if not auc:
                return

            winner = auc.get("current_bidder")
            bid = int(auc.get("current_bid", 0))

            db["auctions"].update_one(
                {"_id": oid}, {"$set": {"active": False, "finished": True}})

            channel = self.bot.get_channel(auc.get("channel_id", 0))
            if channel:
                try:
                    if winner and bid > 0:
                        await channel.send(embed=embed_success(
                            f"🏆 **{auc['item']}** arrematado por <@{winner}> "
                            f"por {EconomyManager.format_currency(guild_id, bid)}!"))
                    else:
                        await channel.send(embed=embed_info(
                            f"😢 Leilão de **{auc['item']}** terminou sem lances."))
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            self._auction_tasks.pop(auc_id, None)


async def setup(bot):
    if bot.get_cog("EconomySinks") is None:
        await bot.add_cog(EconomySinks(bot))