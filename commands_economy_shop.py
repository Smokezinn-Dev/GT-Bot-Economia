# ============================================================
# COMMANDS_ECONOMY_SHOP.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import time

from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from commands_economy_core import EconomyManager
from utils import SlashCtxAdapter


class ShopManager:
    @staticmethod
    def get_item(guild_id: int, item_id) -> Optional[Dict]:
        db = get_connection()
        try:
            from bson import ObjectId
            if isinstance(item_id, str) and len(item_id) == 24:
                return db["economy_shop"].find_one(
                    {"_id": ObjectId(item_id), "guild_id": guild_id})
        except Exception:
            pass
        if isinstance(item_id, int) or (isinstance(item_id, str) and item_id.isdigit()):
            return db["economy_shop"].find_one(
                {"_id": int(item_id), "guild_id": guild_id})
        return db["economy_shop"].find_one(
            {"guild_id": guild_id, "name": str(item_id)})

    @staticmethod
    def get_items(guild_id: int, category: str = None) -> list:
        db = get_connection()
        query = {"guild_id": guild_id, "active": {"$ne": False}}
        if category:
            query["category"] = category
        return list(db["economy_shop"].find(query).sort([("category", 1), ("price", 1)]))

    @staticmethod
    def add_item(guild_id: int, data: dict) -> Any:
        db = get_connection()
        data["guild_id"] = guild_id
        data["created_at"] = datetime.utcnow()
        data["active"] = True
        result = db["economy_shop"].insert_one(data)
        return result.inserted_id

    @staticmethod
    def remove_item(guild_id: int, item_id) -> bool:
        db = get_connection()
        try:
            from bson import ObjectId
            if isinstance(item_id, str) and len(item_id) == 24:
                res = db["economy_shop"].delete_one(
                    {"_id": ObjectId(item_id), "guild_id": guild_id})
            else:
                res = db["economy_shop"].delete_one(
                    {"_id": int(item_id), "guild_id": guild_id})
            return res.deleted_count > 0
        except Exception:
            return False

    @staticmethod
    def get_inventory(guild_id: int, user_id: int) -> list:
        db = get_connection()
        return list(db["economy_inventory"].find(
            {"guild_id": guild_id, "user_id": user_id, "quantity": {"$gt": 0}}
        ))

    @staticmethod
    def add_to_inventory(guild_id: int, user_id: int, item_id, item_name: str,
                         quantity: int = 1, meta: dict = None):
        db = get_connection()
        db["economy_inventory"].update_one(
            {"guild_id": guild_id, "user_id": user_id, "item_id": str(item_id)},
            {
                "$inc": {"quantity": quantity},
                "$set": {"item_name": item_name, "updated_at": datetime.utcnow()},
                "$setOnInsert": {
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "item_id": str(item_id),
                    "meta": meta or {},
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    @staticmethod
    def remove_from_inventory(guild_id: int, user_id: int, item_id, quantity: int = 1) -> bool:
        db = get_connection()
        result = db["economy_inventory"].find_one_and_update(
            {
                "guild_id": guild_id,
                "user_id": user_id,
                "item_id": str(item_id),
                "quantity": {"$gte": quantity}
            },
            {"$inc": {"quantity": -quantity}, "$set": {"updated_at": datetime.utcnow()}},
            return_document=True
        )
        return result is not None

    @staticmethod
    def log_purchase(guild_id: int, user_id: int, item: dict, price: int):
        db = get_connection()
        db["economy_purchases"].insert_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "item_id": str(item.get("_id")),
            "item_name": item.get("name"),
            "price": price,
            "purchased_at": datetime.utcnow()
        })


class EconomyShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._buy_cooldown = {}

    def _format(self, guild_id: int, amount: int) -> str:
        return EconomyManager.format_currency(guild_id, amount)

    # ============================================================
    # ADMIN
    # ============================================================

    @commands.command(name="shopadd")
    @commands.has_permissions(administrator=True)
    async def shop_add(self, ctx: commands.Context, name: str, price: int,
                       category: str = "Geral", *, description: str = ""):
        if price < 0:
            return await ctx.send(embed=embed_error("❌ Preço inválido."))
        db = get_connection()
        if db["economy_shop"].find_one({"guild_id": ctx.guild.id, "name": name}):
            return await ctx.send(embed=embed_error("❌ Já existe um item com esse nome."))
        item_id = ShopManager.add_item(ctx.guild.id, {
            "name": name,
            "description": description,
            "price": price,
            "category": category,
            "item_type": "normal",
            "role_id": 0,
            "stock": -1,
            "cooldown_seconds": 0,
            "required_prestige": 0,
            "required_role": 0,
            "created_by": ctx.author.id
        })
        embed = discord.Embed(
            title="✅ Item Adicionado!",
            description=f"**{name}** por **{self._format(ctx.guild.id, price)}**",
            color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="📂 Categoria", value=category, inline=True)
        embed.add_field(name="🆔 ID", value=f"`{str(item_id)[:8]}`", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="shoprole")
    @commands.has_permissions(administrator=True)
    async def shop_role(self, ctx: commands.Context, role: discord.Role, price: int,
                        stock: int = -1, cooldown: int = 0):
        if price < 0:
            return await ctx.send(embed=embed_error("❌ Preço inválido."))
        db = get_connection()
        if db["economy_shop"].find_one({"guild_id": ctx.guild.id, "role_id": role.id}):
            return await ctx.send(embed=embed_error("❌ Esse cargo já está na loja."))
        item_id = ShopManager.add_item(ctx.guild.id, {
            "name": role.name,
            "description": f"Cargo: {role.mention}",
            "price": price,
            "category": "Cargos",
            "item_type": "role",
            "role_id": role.id,
            "stock": stock,
            "cooldown_seconds": cooldown,
            "required_prestige": 0,
            "required_role": 0,
            "created_by": ctx.author.id
        })
        embed = discord.Embed(
            title="✅ Cargo Adicionado à Loja!",
            description=f"**{role.mention}** por **{self._format(ctx.guild.id, price)}**",
            color=role.color or discord.Color.green(), timestamp=datetime.utcnow())
        if stock >= 0:
            embed.add_field(name="📦 Stock", value=str(stock), inline=True)
        if cooldown > 0:
            embed.add_field(name="⏳ Cooldown", value=f"{cooldown}s", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="shopconsumable")
    @commands.has_permissions(administrator=True)
    async def shop_consumable(self, ctx: commands.Context, name: str, price: int,
                              effect: str, duration_minutes: int = 60,
                              category: str = "Boosters", *, description: str = ""):
        valid_effects = ["earn_boost", "daily_boost", "gamble_protect"]
        if effect not in valid_effects:
            return await ctx.send(embed=embed_error(
                f"❌ Efeitos válidos: {', '.join(valid_effects)}"))
        if price < 0 or duration_minutes < 1:
            return await ctx.send(embed=embed_error("❌ Valores inválidos."))
        item_id = ShopManager.add_item(ctx.guild.id, {
            "name": name,
            "description": description or f"Booster: {effect}",
            "price": price,
            "category": category,
            "item_type": "consumable",
            "role_id": 0,
            "stock": -1,
            "cooldown_seconds": 0,
            "effect": effect,
            "duration_minutes": duration_minutes,
            "required_prestige": 0,
            "required_role": 0,
            "created_by": ctx.author.id
        })
        await ctx.send(embed=embed_success(
            f"✅ Consumível **{name}** criado!\n"
            f"Efeito: `{effect}` por **{duration_minutes} min**\n"
            f"Preço: {self._format(ctx.guild.id, price)}"
        ))

    @commands.command(name="shopremove")
    @commands.has_permissions(administrator=True)
    async def shop_remove(self, ctx: commands.Context, item_id: str):
        if ShopManager.remove_item(ctx.guild.id, item_id):
            await ctx.send(embed=embed_success(f"✅ Item `{item_id}` removido!"))
        else:
            await ctx.send(embed=embed_error(f"❌ Item `{item_id}` não encontrado."))

    # ============================================================
    # LOJA
    # ============================================================

    @commands.command(name="shop", aliases=["loja"])
    async def shop(self, ctx: commands.Context, category: str = None):
        items = ShopManager.get_items(ctx.guild.id, category)
        if not items:
            return await ctx.send(embed=embed_info(
                "🛒 Loja vazia!\nAdmins: use `.shopadd`, `.shoprole` ou `.shopconsumable`."
            ))
        embed = discord.Embed(
            title="🛒 LOJA DO SERVIDOR",
            description="Use `.buy <id>` para comprar\nUse `.inventory` para ver seus itens",
            color=discord.Color.blue(), timestamp=datetime.utcnow())
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        categories: Dict[str, list] = {}
        for item in items:
            cat = item.get("category", "Geral")
            categories.setdefault(cat, []).append(item)
        for cat, cat_items in categories.items():
            lines = []
            for item in cat_items[:12]:
                iid = str(item["_id"])[:8]
                name = item["name"]
                price = item["price"]
                stock = item.get("stock", -1)
                itype = item.get("item_type", "normal")
                extra = ""
                if itype == "role":
                    extra = " 👑"
                elif itype == "consumable":
                    extra = " ⚡"
                if stock >= 0:
                    extra += f" (📦{stock})"
                lines.append(f"`{iid}` **{name}**{extra} — {self._format(ctx.guild.id, price)}")
            value = "\n".join(lines) if lines else "—"
            embed.add_field(name=f"📂 {cat}", value=value[:1024], inline=False)
        embed.set_footer(text=f"Total: {len(items)} itens | .buy <id>")
        await ctx.send(embed=embed)

    @app_commands.command(name="shop", description="🛒 Mostra a loja do servidor")
    async def shop_slash(self, interaction: discord.Interaction):
        await self.shop(SlashCtxAdapter(interaction))

    # ============================================================
    # COMPRAR
    # ============================================================

    @commands.command(name="buy", aliases=["comprar"])
    async def buy(self, ctx: commands.Context, item_id: str):
        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if EconomyManager.is_frozen(guild_id, user_id):
            return await ctx.send(embed=embed_error("❌ Sua economia está congelada."))

        key = f"{guild_id}:{user_id}"
        now = time.time()
        if key in self._buy_cooldown and now - self._buy_cooldown[key] < 2:
            return await ctx.send(embed=embed_warning("⏳ Aguarde um momento..."), delete_after=5)
        self._buy_cooldown[key] = now

        item = ShopManager.get_item(guild_id, item_id)
        if not item:
            return await ctx.send(embed=embed_error(
                "❌ Item não encontrado. Use `.shop` para ver os IDs."))
        if item.get("active") is False:
            return await ctx.send(embed=embed_error("❌ Este item está desativado."))

        price = int(item.get("price", 0))
        stock = item.get("stock", -1)
        if stock == 0:
            return await ctx.send(embed=embed_error("❌ Item esgotado."))

        req_prestige = int(item.get("required_prestige", 0))
        if req_prestige > 0:
            from commands_economy_earn import EarnManager
            prestige = EarnManager.get_prestige(guild_id, user_id)
            if prestige.get("level", 0) < req_prestige:
                return await ctx.send(embed=embed_error(
                    f"❌ Requer Prestígio nível **{req_prestige}**."))

        req_role = int(item.get("required_role", 0))
        if req_role:
            if not ctx.author.get_role(req_role):
                role = ctx.guild.get_role(req_role)
                return await ctx.send(embed=embed_error(
                    f"❌ Requer o cargo {role.mention if role else req_role}."))

        cooldown = int(item.get("cooldown_seconds", 0))
        if cooldown > 0:
            db = get_connection()
            last = db["economy_purchases"].find_one(
                {"guild_id": guild_id, "user_id": user_id, "item_id": str(item["_id"])},
                sort=[("purchased_at", -1)]
            )
            if last:
                elapsed = (datetime.utcnow() - last["purchased_at"]).total_seconds()
                if elapsed < cooldown:
                    remaining = int(cooldown - elapsed)
                    return await ctx.send(embed=embed_warning(
                        f"⏳ Você poderá comprar este item novamente em **{remaining}s**."))

        balance = EconomyManager.get_balance(guild_id, user_id)
        if balance < price:
            return await ctx.send(embed=embed_error(
                f"❌ Saldo insuficiente!\n"
                f"Precisa de {self._format(guild_id, price)} | "
                f"Você tem {self._format(guild_id, balance)}"
            ))

        if not EconomyManager.remove_balance(guild_id, user_id, price,
                                              f"Compra: {item['name']}", "shop"):
            return await ctx.send(embed=embed_error("❌ Falha ao processar pagamento."))

        item_type = item.get("item_type", "normal")
        message = ""

        if item_type == "role":
            role_id = item.get("role_id", 0)
            role = ctx.guild.get_role(role_id)
            if role:
                try:
                    await ctx.author.add_roles(role, reason=f"Comprado na loja por {ctx.author}")
                    message = f"🎉 Você adquiriu o cargo **{role.name}**!"
                except Exception:
                    EconomyManager.add_balance(guild_id, user_id, price,
                                                "Reembolso: erro ao dar cargo", "shop_refund")
                    return await ctx.send(embed=embed_error(
                        "❌ Erro ao adicionar cargo. Valor reembolsado."))
            else:
                EconomyManager.add_balance(guild_id, user_id, price,
                                            "Reembolso: cargo inexistente", "shop_refund")
                return await ctx.send(embed=embed_error(
                    "❌ Cargo não existe mais. Valor reembolsado."))

        elif item_type == "consumable":
            ShopManager.add_to_inventory(
                guild_id, user_id, item["_id"], item["name"], 1,
                meta={
                    "effect": item.get("effect"),
                    "duration_minutes": item.get("duration_minutes", 60)
                }
            )
            message = (
                f"🎉 Você comprou **{item['name']}**!\n"
                f"Ele foi para seu inventário. Use `.use {str(item['_id'])[:8]}` para ativar."
            )
        else:
            ShopManager.add_to_inventory(guild_id, user_id, item["_id"], item["name"], 1)
            message = f"🎉 Você comprou **{item['name']}**! (adicionado ao inventário)"

        if stock > 0:
            db = get_connection()
            db["economy_shop"].update_one(
                {"_id": item["_id"]},
                {"$inc": {"stock": -1}}
            )

        ShopManager.log_purchase(guild_id, user_id, item, price)
        EconomyManager.increment_counter(guild_id, user_id, "purchases_made", 1)

        new_balance = EconomyManager.get_balance(guild_id, user_id)
        embed = discord.Embed(
            title="🛒 Compra Realizada!",
            description=message,
            color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="💰 Preço", value=self._format(guild_id, price), inline=True)
        embed.add_field(name="💰 Saldo atual",
                        value=self._format(guild_id, new_balance), inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="buy", description="🛒 Compra um item da loja")
    @app_commands.describe(item_id="ID do item (veja em /shop)")
    async def buy_slash(self, interaction: discord.Interaction, item_id: str):
        await self.buy(SlashCtxAdapter(interaction), item_id)

    # ============================================================
    # INVENTÁRIO
    # ============================================================

    @commands.command(name="inventory", aliases=["inv", "inventario"])
    async def inventory(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        items = ShopManager.get_inventory(ctx.guild.id, member.id)
        embed = discord.Embed(
            title=f"🎒 Inventário de {member.display_name}",
            color=member.color or discord.Color.blue(),
            timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        if not items:
            embed.description = "Inventário vazio."
        else:
            lines = []
            for inv in items[:20]:
                name = inv.get("item_name", "Item")
                qty = inv.get("quantity", 0)
                iid = str(inv.get("item_id", ""))[:8]
                meta = inv.get("meta", {})
                effect = meta.get("effect")
                extra = f" ⚡`{effect}`" if effect else ""
                lines.append(f"`{iid}` **{name}** x{qty}{extra}")
            embed.description = "\n".join(lines)
            embed.set_footer(text="Use .use <id> para consumir boosters")
        await ctx.send(embed=embed)

    @commands.command(name="use", aliases=["usar"])
    async def use_item(self, ctx: commands.Context, item_id: str):
        guild_id = ctx.guild.id
        user_id = ctx.author.id

        db = get_connection()
        items = list(db["economy_inventory"].find({
            "guild_id": guild_id,
            "user_id": user_id,
            "quantity": {"$gt": 0}
        }))

        inv = None
        for it in items:
            if str(it.get("item_id", "")).startswith(item_id):
                inv = it
                break

        if not inv or inv.get("quantity", 0) < 1:
            return await ctx.send(embed=embed_error("❌ Você não possui esse item."))

        meta = inv.get("meta", {})
        effect = meta.get("effect")
        duration = int(meta.get("duration_minutes", 60))

        if not effect:
            return await ctx.send(embed=embed_error("❌ Este item não é consumível."))

        if not ShopManager.remove_from_inventory(guild_id, user_id, inv["item_id"], 1):
            return await ctx.send(embed=embed_error("❌ Falha ao consumir o item."))

        expires = datetime.utcnow() + timedelta(minutes=duration)
        db["economy_boosts"].update_one(
            {"guild_id": guild_id, "user_id": user_id, "effect": effect},
            {"$set": {
                "expires_at": expires,
                "multiplier": 2.0 if "boost" in effect else 1.0,
                "activated_at": datetime.utcnow()
            }},
            upsert=True
        )

        effect_names = {
            "earn_boost": "Ganhos por mensagem x2",
            "daily_boost": "Daily em dobro",
            "gamble_protect": "Proteção contra perda em apostas"
        }
        nice = effect_names.get(effect, effect)

        await ctx.send(embed=embed_success(
            f"⚡ **{inv.get('item_name')}** ativado!\n"
            f"Efeito: **{nice}**\n"
            f"Duração: **{duration} minutos**"
        ))


async def setup(bot):
    if bot.get_cog("EconomyShop") is None:
        await bot.add_cog(EconomyShop(bot))