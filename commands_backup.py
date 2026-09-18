# ============================================================
# COMMANDS_BACKUP.PY - v6.2 (prefixo .)
# ============================================================

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from config import BACKUP_ENABLED, BACKUP_AUTO_HOUR, BACKUP_MAX_PER_GUILD
from database import get_connection
from embeds import embed_success, embed_error, embed_warning, embed_info
from utils import safe_object_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BackupCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if BACKUP_ENABLED:
            self.auto_backup.start()

    def cog_unload(self):
        try:
            self.auto_backup.cancel()
        except Exception:
            pass

    # ============================================================
    # AUTO BACKUP DIÁRIO
    # ============================================================

    @tasks.loop(hours=24)
    async def auto_backup(self):
        try:
            now = _now()
            if now.hour != BACKUP_AUTO_HOUR:
                return
            for guild in self.bot.guilds:
                try:
                    await self._create_backup(guild, author=None,
                                              name=f"auto-{now.strftime('%Y%m%d')}")
                except Exception:
                    pass
        except Exception:
            pass

    @auto_backup.before_loop
    async def before_auto(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # HELPERS
    # ============================================================

    async def _create_backup(self, guild: discord.Guild, author, name: str = None) -> str:
        db = get_connection()
        now = _now()
        name = name or f"backup-{now.strftime('%Y%m%d-%H%M%S')}"

        channels_data = []
        for ch in guild.channels:
            ch_entry = {
                "id": ch.id,
                "name": ch.name,
                "type": str(ch.type),
                "position": ch.position,
                "category_id": ch.category.id if ch.category else None,
                "topic": getattr(ch, "topic", None),
                "nsfw": getattr(ch, "nsfw", False),
                "slowmode": getattr(ch, "slowmode_delay", 0),
                "overwrites": [],
            }
            for target, ow in ch.overwrites.items():
                allow, deny = ow.pair()
                ch_entry["overwrites"].append({
                    "target_id": target.id,
                    "target_type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            channels_data.append(ch_entry)

        roles_data = []
        for role in guild.roles:
            if role.is_default():
                continue
            roles_data.append({
                "id": role.id,
                "name": role.name,
                "color": role.color.value,
                "permissions": role.permissions.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "position": role.position,
            })

        members_data = []
        for m in guild.members:
            if m.bot:
                continue
            member_roles = [r.id for r in m.roles if not r.is_default()]
            if member_roles:
                members_data.append({
                    "user_id": m.id,
                    "username": str(m),
                    "roles": member_roles,
                })

        configs = {}
        for col in ["economy_config", "earn_config", "guild_config", "staff_config",
                    "automod_config", "branding_config", "control_config"]:
            doc = db[col].find_one({"guild_id": guild.id})
            if doc:
                doc.pop("_id", None)
                configs[col] = doc

        backup_cfg = db["backup_config"].find_one({"guild_id": guild.id}) or {}
        text_channels_ids = backup_cfg.get("text_channels", [])
        text_channel_limit = int(backup_cfg.get("text_channel_limit", 50))

        meta = {
            "guild_id": guild.id,
            "guild_name": guild.name,
            "name": name,
            "created_at": now,
            "created_by": author.id if author else None,
            "created_by_name": str(author) if author else "AUTO",
            "channels": channels_data,
            "roles": roles_data,
            "members": members_data,
            "configs": configs,
            "text_channels_ids": text_channels_ids,
        }

        result = db["backups"].insert_one(meta)
        backup_id = result.inserted_id

        for ch_id in text_channels_ids:
            ch = guild.get_channel(ch_id)
            if not ch or not isinstance(ch, discord.TextChannel):
                continue
            messages = []
            try:
                async for msg in ch.history(limit=text_channel_limit, oldest_first=False):
                    if msg.author.bot:
                        continue
                    messages.append({
                        "author": str(msg.author),
                        "content": msg.content[:2000],
                        "timestamp": msg.created_at.isoformat(),
                        "pinned": msg.pinned,
                    })
                messages.reverse()
            except Exception:
                pass
            if messages:
                db["backup_texts"].insert_one({
                    "backup_id": str(backup_id),
                    "guild_id": guild.id,
                    "channel_id": ch_id,
                    "channel_name": ch.name,
                    "messages": messages,
                })

        total = db["backups"].count_documents({"guild_id": guild.id})
        if total > BACKUP_MAX_PER_GUILD:
            old = list(db["backups"].find({"guild_id": guild.id})
                       .sort("created_at", 1)
                       .limit(total - BACKUP_MAX_PER_GUILD))
            for doc in old:
                db["backups"].delete_one({"_id": doc["_id"]})
                db["backup_texts"].delete_many({"backup_id": str(doc["_id"])})

        return str(backup_id)

    # ============================================================
    # COMANDOS
    # ============================================================

    @commands.command(name="backup", aliases=["bkp"])
    @commands.has_permissions(administrator=True)
    async def backup(self, ctx):
        """Painel do backup."""
        embed = discord.Embed(
            title="💾 SISTEMA DE BACKUP",
            description=(
                "**Comandos disponíveis:**\n\n"
                "• `.backup create [nome]` — Cria um backup\n"
                "• `.backup list` — Lista backups\n"
                "• `.backup info <id>` — Detalhes\n"
                "• `.backup restore <id>` — Restaura completo\n"
                "• `.backup restore <id> canais` — Só canais\n"
                "• `.backup restore <id> cargos` — Só cargos\n"
                "• `.backup restore <id> membros` — Só reatribui cargos\n"
                "• `.backup restore <id> config` — Só configs\n"
                "• `.backup delete <id>` — Apaga backup\n"
                "• `.backup textchannel #canal` — Marca canal para salvar texto\n"
                "• `.backup textchannel #canal remove` — Desmarca\n"
                "• `.backup textlimit <n>` — Limite de msgs por canal\n"
            ),
            color=discord.Color.blurple(),
            timestamp=_now()
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    @commands.command(name="backupcreate")
    @commands.has_permissions(administrator=True)
    async def backup_create(self, ctx, *, name: str = None):
        msg = await ctx.send(embed=embed_info("⏳ Criando backup..."))
        try:
            bkp_id = await self._create_backup(ctx.guild, ctx.author, name)
        except Exception as e:
            return await msg.edit(embed=embed_error(f"❌ Falha: {e}"))

        db = get_connection()
        doc = db["backups"].find_one({"_id": safe_object_id(bkp_id)})
        embed = discord.Embed(
            title="✅ BACKUP CRIADO!",
            description=f"**{doc.get('name', name or 'sem nome')}**",
            color=discord.Color.green(),
            timestamp=_now()
        )
        embed.add_field(name="🆔 ID", value=f"`{bkp_id}`", inline=False)
        embed.add_field(name="📁 Canais", value=str(len(doc.get("channels", []))), inline=True)
        embed.add_field(name="👑 Cargos", value=str(len(doc.get("roles", []))), inline=True)
        embed.add_field(name="👥 Membros", value=str(len(doc.get("members", []))), inline=True)
        texts = db["backup_texts"].count_documents({"backup_id": bkp_id})
        embed.add_field(name="📝 Textos salvos", value=str(texts), inline=True)
        await msg.edit(embed=embed)

    @commands.command(name="backuplist")
    @commands.has_permissions(administrator=True)
    async def backup_list(self, ctx):
        db = get_connection()
        docs = list(db["backups"].find({"guild_id": ctx.guild.id})
                    .sort("created_at", -1).limit(20))
        if not docs:
            return await ctx.send(embed=embed_info("📋 Nenhum backup."))

        embed = discord.Embed(title="💾 BACKUPS DISPONÍVEIS",
                              color=discord.Color.blurple(), timestamp=_now())
        for d in docs:
            bkp_id = str(d["_id"])
            ts = d.get("created_at", _now())
            ts_str = ts.strftime("%d/%m/%Y %H:%M") if hasattr(ts, "strftime") else str(ts)
            texts = db["backup_texts"].count_documents({"backup_id": bkp_id})
            embed.add_field(
                name=f"`{bkp_id[:8]}` — {d.get('name', 'sem nome')}",
                value=f"📅 {ts_str}\n👤 {d.get('created_by_name', '?')}\n📝 {texts} canal(is) com texto",
                inline=False
            )
        embed.set_footer(text=f"Total: {len(docs)} | .backupinfo <id>")
        await ctx.send(embed=embed)

    @commands.command(name="backupinfo")
    @commands.has_permissions(administrator=True)
    async def backup_info(self, ctx, backup_id: str):
        oid = safe_object_id(backup_id)
        if not oid:
            return await ctx.send(embed=embed_error("❌ ID inválido."))
        db = get_connection()
        doc = db["backups"].find_one({"_id": oid, "guild_id": ctx.guild.id})
        if not doc:
            return await ctx.send(embed=embed_error("❌ Backup não encontrado."))

        texts = list(db["backup_texts"].find({"backup_id": backup_id}))
        embed = discord.Embed(
            title=f"💾 {doc.get('name', 'sem nome')}",
            color=discord.Color.blurple(), timestamp=_now()
        )
        embed.add_field(name="🆔", value=f"`{backup_id}`", inline=False)
        embed.add_field(name="📅 Criado", value=str(doc.get("created_at")), inline=True)
        embed.add_field(name="👤 Por", value=doc.get("created_by_name", "?"), inline=True)
        embed.add_field(name="📁 Canais", value=str(len(doc.get("channels", []))), inline=True)
        embed.add_field(name="👑 Cargos", value=str(len(doc.get("roles", []))), inline=True)
        embed.add_field(name="👥 Membros", value=str(len(doc.get("members", []))), inline=True)
        if texts:
            lines = [f"• `{t['channel_name']}` — {len(t['messages'])} msgs" for t in texts]
            embed.add_field(name="📝 Textos salvos", value="\n".join(lines)[:1000], inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="backupdelete")
    @commands.has_permissions(administrator=True)
    async def backup_delete(self, ctx, backup_id: str):
        oid = safe_object_id(backup_id)
        if not oid:
            return await ctx.send(embed=embed_error("❌ ID inválido."))
        db = get_connection()
        result = db["backups"].delete_one({"_id": oid, "guild_id": ctx.guild.id})
        db["backup_texts"].delete_many({"backup_id": backup_id})
        if result.deleted_count > 0:
            await ctx.send(embed=embed_success("✅ Backup removido."))
        else:
            await ctx.send(embed=embed_error("❌ Backup não encontrado."))

    # ============================================================
    # CONFIG DE TEXTO
    # ============================================================

    @commands.command(name="backuptext")
    @commands.has_permissions(administrator=True)
    async def backup_text_channel(self, ctx, channel: discord.TextChannel = None,
                                  action: str = "add"):
        if channel is None:
            return await ctx.send(embed=embed_error("❌ Use: `.backuptext #canal`"))

        db = get_connection()
        cfg = db["backup_config"].find_one({"guild_id": ctx.guild.id}) or {}
        ids = set(cfg.get("text_channels", []))

        if action.lower() in ("remove", "remover", "del"):
            ids.discard(channel.id)
            db["backup_config"].update_one(
                {"guild_id": ctx.guild.id},
                {"$set": {"text_channels": list(ids)}}, upsert=True
            )
            return await ctx.send(embed=embed_success(
                f"✅ {channel.mention} não salva mais texto."))

        ids.add(channel.id)
        db["backup_config"].update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"text_channels": list(ids)}}, upsert=True
        )
        await ctx.send(embed=embed_success(
            f"✅ {channel.mention} agora salva texto nos backups.\n"
            f"**Total:** {len(ids)} canal(is) marcados."))

    @commands.command(name="backuptextlimit")
    @commands.has_permissions(administrator=True)
    async def backup_text_limit(self, ctx, limit: int):
        if limit < 10 or limit > 500:
            return await ctx.send(embed=embed_error("❌ Limite: 10 a 500 mensagens."))
        db = get_connection()
        db["backup_config"].update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"text_channel_limit": limit}}, upsert=True
        )
        await ctx.send(embed=embed_success(f"✅ Limite: **{limit}** mensagens por canal."))

    @commands.command(name="backuptextlist")
    @commands.has_permissions(administrator=True)
    async def backup_text_list(self, ctx):
        db = get_connection()
        cfg = db["backup_config"].find_one({"guild_id": ctx.guild.id}) or {}
        ids = cfg.get("text_channels", [])
        limit = cfg.get("text_channel_limit", 50)
        if not ids:
            return await ctx.send(embed=embed_info(
                "📋 Nenhum canal marcado. Use `.backuptext #canal`"))
        embed = discord.Embed(title="📝 Canais que salvam texto",
                              color=discord.Color.blue(), timestamp=_now())
        embed.add_field(
            name="Canais",
            value="\n".join(f"• <#{c}>" for c in ids),
            inline=False
        )
        embed.set_footer(text=f"Limite por canal: {limit} msgs")
        await ctx.send(embed=embed)

    # ============================================================
    # RESTORE
    # ============================================================

    @commands.command(name="backuprestore")
    @commands.has_permissions(administrator=True)
    async def backup_restore(self, ctx, backup_id: str = None, *, mode: str = "all"):
        if not backup_id:
            return await ctx.send(embed=embed_error(
                "❌ Use: `.backuprestore <id> [all/canais/cargos/membros/config/textos]`"))

        oid = safe_object_id(backup_id)
        if not oid:
            return await ctx.send(embed=embed_error("❌ ID inválido."))
        db = get_connection()
        doc = db["backups"].find_one({"_id": oid, "guild_id": ctx.guild.id})
        if not doc:
            return await ctx.send(embed=embed_error("❌ Backup não encontrado."))

        mode = mode.lower().strip() or "all"
        valid_modes = ("all", "tudo", "canais", "channels", "cargos", "roles",
                       "membros", "members", "config", "textos", "texts")
        if mode not in valid_modes:
            return await ctx.send(embed=embed_error(
                f"❌ Modo inválido. Use: all, canais, cargos, membros, config, textos"))

        await ctx.send(embed=embed_warning(
            f"⚠️ **RESTORE INICIADO** — modo `{mode}`\nDigite `CONFIRMAR` em 20 segundos."
        ))

        def check(m):
            return (m.author.id == ctx.author.id and
                    m.channel.id == ctx.channel.id and
                    m.content.upper() == "CONFIRMAR")

        try:
            await self.bot.wait_for("message", check=check, timeout=20)
        except asyncio.TimeoutError:
            return await ctx.send(embed=embed_info("Cancelado."))

        stats = {"roles": 0, "channels": 0, "categories": 0,
                 "members": 0, "texts": 0, "configs": 0}

        # ----- CARGOS -----
        if mode in ("all", "tudo", "cargos", "roles"):
            existing = {r.name.lower(): r for r in ctx.guild.roles}
            for r in doc.get("roles", []):
                if r["name"].lower() in existing:
                    continue
                try:
                    perms = discord.Permissions(r["permissions"])
                    new_role = await ctx.guild.create_role(
                        name=r["name"],
                        color=discord.Color(r["color"]),
                        permissions=perms,
                        hoist=r.get("hoist", False),
                        mentionable=r.get("mentionable", False),
                        reason="Backup restore"
                    )
                    stats["roles"] += 1
                except Exception:
                    pass
            try:
                sorted_roles = sorted(doc.get("roles", []), key=lambda x: x.get("position", 0))
                positions = {}
                for r in sorted_roles:
                    role = discord.utils.get(ctx.guild.roles, name=r["name"])
                    if role:
                        positions[role] = r.get("position", role.position)
                if positions:
                    await ctx.guild.edit_role_positions(positions=positions)
            except Exception:
                pass

        # ----- CANAIS -----
        if mode in ("all", "tudo", "canais", "channels"):
            cat_map = {}
            existing_cats = {c.name.lower(): c for c in ctx.guild.categories}
            for ch in doc.get("channels", []):
                if "category" not in str(ch.get("type", "")).lower():
                    continue
                if ch["name"].lower() in existing_cats:
                    cat_map[ch["id"]] = existing_cats[ch["name"].lower()]
                    continue
                try:
                    new_cat = await ctx.guild.create_category(
                        ch["name"], reason="Backup restore")
                    cat_map[ch["id"]] = new_cat
                    stats["categories"] += 1
                except Exception:
                    pass

            existing_channels = {c.name.lower(): c for c in ctx.guild.channels}
            created_map = {}
            for ch in doc.get("channels", []):
                if "category" in str(ch.get("type", "")).lower():
                    continue
                if ch["name"].lower() in existing_channels:
                    continue
                try:
                    if "voice" in str(ch.get("type", "")).lower():
                        new_ch = await ctx.guild.create_voice_channel(
                            ch["name"], reason="Backup restore")
                    else:
                        new_ch = await ctx.guild.create_text_channel(
                            ch["name"],
                            topic=ch.get("topic"),
                            nsfw=ch.get("nsfw", False),
                            slowmode_delay=ch.get("slowmode", 0),
                            reason="Backup restore")
                    created_map[ch["id"]] = new_ch
                    stats["channels"] += 1
                except Exception:
                    pass

            for ch_data in doc.get("channels", []):
                new_ch = created_map.get(ch_data["id"])
                if not new_ch:
                    continue
                for ow in ch_data.get("overwrites", []):
                    try:
                        target = None
                        if ow["target_type"] == "role":
                            role = ctx.guild.get_role(ow["target_id"])
                            if not role:
                                role = discord.utils.get(ctx.guild.roles,
                                                         name=ow.get("target_name", ""))
                            target = role
                        else:
                            target = ctx.guild.get_member(ow["target_id"])
                        if not target:
                            continue
                        allow = discord.Permissions(ow["allow"])
                        deny = discord.Permissions(ow["deny"])
                        await new_ch.set_permissions(
                            target,
                            overwrite=discord.PermissionOverwrite.from_pair(allow, deny))
                    except Exception:
                        pass

            try:
                positions = {}
                for ch in doc.get("channels", []):
                    new_ch = created_map.get(ch["id"])
                    cat = cat_map.get(ch.get("category_id"))
                    if new_ch:
                        positions[new_ch] = (ch.get("position", 0), cat)
                for channel, (pos, cat) in positions.items():
                    try:
                        await channel.edit(category=cat, position=pos)
                    except Exception:
                        pass
            except Exception:
                pass

        # ----- MEMBROS -----
        if mode in ("all", "tudo", "membros", "members"):
            for m_data in doc.get("members", []):
                member = ctx.guild.get_member(m_data["user_id"])
                if not member:
                    continue
                added = False
                for role_id in m_data.get("roles", []):
                    role = ctx.guild.get_role(role_id)
                    if not role:
                        role = discord.utils.get(
                            ctx.guild.roles,
                            name=next((r["name"] for r in doc.get("roles", [])
                                       if r["id"] == role_id), ""))
                    if role and role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Backup restore")
                            added = True
                        except Exception:
                            pass
                if added:
                    stats["members"] += 1

        # ----- CONFIG -----
        if mode in ("all", "tudo", "config"):
            for col, data in (doc.get("configs") or {}).items():
                try:
                    data["guild_id"] = ctx.guild.id
                    db[col].update_one(
                        {"guild_id": ctx.guild.id},
                        {"$set": data}, upsert=True
                    )
                    stats["configs"] += 1
                except Exception:
                    pass

        # ----- TEXTOS -----
        if mode in ("all", "tudo", "textos", "texts"):
            texts = list(db["backup_texts"].find({"backup_id": backup_id}))
            for t in texts:
                ch = ctx.guild.get_channel(t["channel_id"])
                if not ch or not isinstance(ch, discord.TextChannel):
                    ch = discord.utils.get(ctx.guild.text_channels, name=t["channel_name"])
                if not ch:
                    continue
                for m in t.get("messages", []):
                    try:
                        embed_msg = discord.Embed(
                            description=m["content"],
                            color=discord.Color.greyple(),
                            timestamp=datetime.fromisoformat(m["timestamp"]) if m.get("timestamp") else _now()
                        )
                        embed_msg.set_author(name=m.get("author", "Desconhecido"))
                        if m.get("pinned"):
                            embed_msg.set_footer(text="📌 Fixada")
                        await ch.send(embed=embed_msg)
                        stats["texts"] += 1
                        await asyncio.sleep(0.6)
                    except Exception:
                        pass

        embed = discord.Embed(
            title="✅ RESTORE CONCLUÍDO",
            description=f"Modo: `{mode}`",
            color=discord.Color.green(),
            timestamp=_now()
        )
        embed.add_field(name="👑 Cargos", value=str(stats["roles"]), inline=True)
        embed.add_field(name="📁 Categorias", value=str(stats["categories"]), inline=True)
        embed.add_field(name="📁 Canais", value=str(stats["channels"]), inline=True)
        embed.add_field(name="👥 Membros", value=str(stats["members"]), inline=True)
        embed.add_field(name="⚙️ Configs", value=str(stats["configs"]), inline=True)
        embed.add_field(name="📝 Textos", value=str(stats["texts"]), inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    if bot.get_cog("BackupCommands") is None:
        await bot.add_cog(BackupCommands(bot))