import asyncio
import json

from temporalio.client import Client as TemporalClient

from app.config import get_discord_config


def escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def run_discord_bot(temporal_client: TemporalClient) -> None:
    """Run the Discord gateway client for private application commands."""
    from app.config import load_settings_from_db

    while True:
        await load_settings_from_db()
        config = get_discord_config()
        if config.get("enabled") and config.get("bot_token"):
            break
        await asyncio.sleep(10)

    try:
        import discord
        from discord import app_commands
        from discord.ext import commands
    except ImportError as exc:
        print(f"[discord] slash commands disabled; discord.py is not installed: {exc}", flush=True)
        return

    from app.database import AsyncSessionLocal
    from app.security import LOCAL_WORKSPACE_ID
    from app.models.osrs_models import OsrsLoadout
    from app.services import osrs_loadouts as loadout_service
    from app import discord_loadouts as loadouts
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(
        command_prefix="!",
        intents=intents,
        allowed_mentions=discord.AllowedMentions.none(),
    )

    def _message_link(message: discord.Message) -> str:
        guild_id = message.guild.id if message.guild else "@me"
        return f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"

    def _mention_prompt(message: discord.Message) -> str:
        content = message.content or ""
        if bot.user:
            content = content.replace(f"<@{bot.user.id}>", "")
            content = content.replace(f"<@!{bot.user.id}>", "")
        from app.discord_mentions import normalize_discord_user_mentions
        return normalize_discord_user_mentions(content, list(message.mentions)).strip()

    async def _image_attachments(message: discord.Message) -> list[dict]:
        images = []
        for attachment in message.attachments:
            content_type = attachment.content_type or ""
            filename = attachment.filename or "image"
            is_image = content_type.startswith("image/") or filename.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            )
            if is_image:
                content = None
                try:
                    content = await attachment.read(use_cached=True)
                except Exception as exc:
                    print(f"[discord] failed to read attachment bytes for {filename}: {exc}", flush=True)
                images.append({
                    "url": attachment.url,
                    "source_url": attachment.url,
                    "proxy_url": attachment.proxy_url,
                    "filename": filename,
                    "content_type": content_type or "image/*",
                    "width": attachment.width,
                    "height": attachment.height,
                    "content": content,
                })
        return images

    @bot.tree.command(name="threadbot", description="Start a new ThreadBot thread from Discord")
    @app_commands.describe(prompt="The first message to send to ThreadBot")
    async def threadbot_command(interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        from app.discord_integration import (
            reply_to_existing_discord_thread,
            start_thread_from_discord_prompt,
        )

        try:
            channel_id = str(interaction.channel_id) if interaction.channel_id else config.get("channel_id")
            guild_id = str(interaction.guild_id) if interaction.guild_id else config.get("guild_id")
            guild_name = interaction.guild.name if interaction.guild else None
            sender_name = interaction.user.global_name or interaction.user.name or "Discord user"
            from app.discord_mentions import normalize_discord_user_mentions
            prompt = normalize_discord_user_mentions(prompt)
            invoked_channel = interaction.channel
            if isinstance(invoked_channel, discord.Thread):
                # Slash command invoked inside an existing thread — reply there.
                await reply_to_existing_discord_thread(
                    temporal_client,
                    discord_thread_id=str(invoked_channel.id),
                    guild_id=guild_id,
                    channel_id=str(getattr(invoked_channel, "parent_id", None) or channel_id),
                    guild_name=guild_name,
                    discord_thread_name=invoked_channel.name,
                    sender_name=sender_name,
                    sender_id=str(interaction.user.id),
                    prompt=prompt,
                    source_message_id=None,
                    source_message_link=None,
                    source_event_id=str(interaction.id),
                )
            else:
                await start_thread_from_discord_prompt(
                    temporal_client,
                    prompt,
                    sender_name,
                    sender_id=str(interaction.user.id),
                    source_event_id=str(interaction.id),
                    channel_id=channel_id,
                    guild_id=guild_id,
                    guild_name=guild_name,
                )
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
        except Exception as exc:
            print(f"[discord] slash command failed: {exc}", flush=True)
            await interaction.followup.send(f"Failed to start ThreadBot thread: {exc}", ephemeral=True)

    loadout_group = app_commands.Group(name="loadout", description="Manage OSRS DPS loadouts")
    bot.tree.add_command(loadout_group)

    async def _name_autocomplete(interaction, current: str):
        async with AsyncSessionLocal() as db:
            rows = (await db.scalars(select(OsrsLoadout.name).where(
                OsrsLoadout.workspace_id == LOCAL_WORKSPACE_ID,
                OsrsLoadout.name.ilike(
                    f"%{escape_like_pattern(current)}%", escape="\\"
                )).order_by(OsrsLoadout.name).limit(25))).all()
        return [app_commands.Choice(name=name[:100], value=name) for name in rows]

    def _thread_id(interaction):
        return str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None

    @loadout_group.command(name="list", description="List your loadouts")
    async def loadout_list(interaction):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as db:
            rows = await loadout_service.list_loadouts(db, LOCAL_WORKSPACE_ID)
        text = "\n".join(f"• **{row['name']}** (revision {row['revision']})" for row in rows) or "No loadouts yet."
        await interaction.followup.send(text, ephemeral=True)

    @loadout_group.command(name="create", description="Create a safe empty starter loadout")
    @app_commands.describe(name="Unique loadout name")
    async def loadout_create(interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        try:
            async with AsyncSessionLocal() as db:
                row = await loadouts.create(db, LOCAL_WORKSPACE_ID, name.strip(), interaction.user.id)
                await db.commit()
            await interaction.followup.send(f"Created **{row['name']}**.", ephemeral=True)
        except IntegrityError:
            await interaction.followup.send("A loadout with that name already exists.", ephemeral=True)

    @loadout_group.command(name="import", description="Import loadouts from an OSRS Wiki DPS link")
    @app_commands.describe(link="OSRS Wiki DPS calculator link")
    async def loadout_import(interaction, link: str):
        await interaction.response.defer(ephemeral=True)
        try:
            async with AsyncSessionLocal() as db:
                rows = await loadouts.import_link(db, LOCAL_WORKSPACE_ID, link.strip(), interaction.user.id)
                await db.commit()
            await interaction.followup.send("Imported: " + (", ".join(f"**{x['name']}**" for x in rows) if rows else "no loadouts found."), ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Import failed: {exc}", ephemeral=True)

    @loadout_group.command(name="show", description="Show a loadout")
    @app_commands.describe(name="Loadout name")
    @app_commands.autocomplete(name=_name_autocomplete)
    async def loadout_show(interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as db:
            row = await loadouts.resolve_name(db, LOCAL_WORKSPACE_ID, name)
        if not row:
            await interaction.followup.send("Loadout not found.", ephemeral=True); return
        await interaction.followup.send(f"**{row.name}** · revision {row.revision}\nSource: `{row.source_type}`\n```json\n{json.dumps(row.payload, default=str)[:1800]}\n```", ephemeral=True)

    @loadout_group.command(name="use", description="Bind a loadout to this Discord thread")
    @app_commands.describe(name="Loadout name")
    @app_commands.autocomplete(name=_name_autocomplete)
    async def loadout_use(interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        thread_id = _thread_id(interaction)
        if not thread_id:
            await interaction.followup.send("Use `/loadout use` inside a linked ThreadBot Discord thread.", ephemeral=True); return
        async with AsyncSessionLocal() as db:
            local_thread = await loadouts.workspace_thread(db, LOCAL_WORKSPACE_ID, thread_id)
            row = await loadouts.resolve_name(db, LOCAL_WORKSPACE_ID, name)
            if not local_thread:
                await interaction.followup.send("This Discord thread is not linked to a ThreadBot thread.", ephemeral=True); return
            if not row:
                await interaction.followup.send("Loadout not found.", ephemeral=True); return
            await loadout_service.bind_thread(db, LOCAL_WORKSPACE_ID, local_thread, row.id)
            await db.commit()
        await interaction.followup.send(f"Using **{row.name}** in this thread.", ephemeral=True)

    @loadout_group.command(name="clone", description="Clone a loadout")
    @app_commands.describe(source="Existing loadout", new_name="Name for the clone")
    @app_commands.autocomplete(source=_name_autocomplete)
    async def loadout_clone(interaction, source: str, new_name: str):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as db:
            row = await loadouts.resolve_name(db, LOCAL_WORKSPACE_ID, source)
            if not row:
                await interaction.followup.send("Source loadout not found.", ephemeral=True); return
            try:
                result = await loadout_service.clone_loadout(db, LOCAL_WORKSPACE_ID, row.id, new_name.strip(), loadouts.discord_actor(str(interaction.user.id)))
                await db.commit()
            except IntegrityError:
                await interaction.followup.send("A loadout with that name already exists.", ephemeral=True); return
        await interaction.followup.send(f"Cloned **{result['name']}**.", ephemeral=True)

    @loadout_group.command(name="delete", description="Delete a loadout")
    @app_commands.describe(name="Loadout name")
    @app_commands.autocomplete(name=_name_autocomplete)
    async def loadout_delete(interaction, name: str):
        async with AsyncSessionLocal() as db:
            row = await loadouts.resolve_name(db, LOCAL_WORKSPACE_ID, name)
        if not row:
            await interaction.response.send_message("Loadout not found.", ephemeral=True); return
        view = discord.ui.View(timeout=60)
        async def confirm(i):
            if i.user.id != interaction.user.id:
                await i.response.send_message("Only the invoking user can confirm this deletion.", ephemeral=True); return
            async with AsyncSessionLocal() as db:
                deleted = await loadout_service.delete_loadout(db, LOCAL_WORKSPACE_ID, row.id); await db.commit()
            await i.response.edit_message(content="Deleted." if deleted else "Loadout was already deleted.", view=None)
        async def cancel(i):
            if i.user.id != interaction.user.id:
                await i.response.send_message("Only the invoking user can cancel this request.", ephemeral=True); return
            await i.response.edit_message(content="Cancelled.", view=None)
        yes = discord.ui.Button(label="Delete", style=discord.ButtonStyle.danger); no = discord.ui.Button(label="Cancel")
        yes.callback = confirm; no.callback = cancel; view.add_item(yes); view.add_item(no)
        await interaction.response.send_message(f"Delete **{row.name}**?", view=view, ephemeral=True)

    def _equipment_autocomplete(slot):
        async def callback(interaction, current: str):
            try:
                items = await loadouts.equipment_catalog()
                choices = loadouts.equipment_choices(items, slot, current)
                result = []
                for item in choices:
                    token = loadouts.encode_equipment_choice(item)
                    if len(token) > 100:
                        continue
                    version = f" [{item['version']}]" if item.get("version") else ""
                    result.append(app_commands.Choice(
                        name=f"{item['name']}{version} (id {item['id']})"[:100], value=token
                    ))
                return result + [
                    app_commands.Choice(name=f"Clear {slot}", value=loadouts.CLEAR_TOKEN)]
            except Exception:
                return []
        return callback

    @loadout_group.command(name="equip", description="Equip or clear one or more items")
    @app_commands.describe(name="Loadout name", head="Head item", cape="Cape item", neck="Neck item",
                           ammo="Ammunition", weapon="Weapon", body="Body item", shield="Shield item",
                           legs="Legs item", hands="Gloves item", feet="Boots item", ring="Ring item")
    @app_commands.autocomplete(name=_name_autocomplete)
    @app_commands.autocomplete(**{slot: _equipment_autocomplete(slot) for slot in loadouts.SLOTS})
    async def loadout_equip(interaction, name: str, head: str | None = None, cape: str | None = None,
                            neck: str | None = None, ammo: str | None = None, weapon: str | None = None,
                            body: str | None = None, shield: str | None = None, legs: str | None = None,
                            hands: str | None = None, feet: str | None = None, ring: str | None = None):
        await interaction.response.defer(ephemeral=True)
        supplied = {slot: value for slot, value in zip(loadouts.SLOTS,
                    (head, cape, neck, ammo, weapon, body, shield, legs, hands, feet, ring)) if value is not None}
        if not supplied:
            await interaction.followup.send("Provide at least one equipment slot to equip or clear.", ephemeral=True)
            return
        async with AsyncSessionLocal() as db:
            row = await loadouts.resolve_name(db, LOCAL_WORKSPACE_ID, name)
        if not row:
            await interaction.followup.send("Loadout not found.", ephemeral=True); return
        try:
            items = await loadouts.equipment_catalog()
        except Exception:
            await interaction.followup.send("Equipment catalog is temporarily unavailable; try again shortly.", ephemeral=True)
            return
        updates = {}
        labels = []
        for slot, token in supplied.items():
            item = loadouts.resolve_equipment_choice(token, slot, items)
            if item is False:
                await interaction.followup.send(f"Invalid {slot} item selection. Use autocomplete and try again.", ephemeral=True)
                return
            updates[slot] = item
            labels.append(f"{slot}: {'cleared' if item is None else item['name']}")
        async with AsyncSessionLocal() as db:
            updated, error = await loadouts.equip_many(db, LOCAL_WORKSPACE_ID, row.id, row.revision, updates)
            if error:
                await interaction.followup.send("Loadout changed; run the command again.", ephemeral=True)
                return
            await db.commit()
        await interaction.followup.send(f"Updated **{row.name}** ({'; '.join(labels)}), revision {updated['revision']}.", ephemeral=True)

    @loadout_group.command(name="stat", description="Set one player skill level")
    @app_commands.describe(name="Loadout name", stat="Skill", value="Level (1-126)")
    @app_commands.autocomplete(name=_name_autocomplete)
    @app_commands.choices(stat=[app_commands.Choice(name=key, value=key) for key in loadouts.STAT_KEYS])
    async def loadout_stat(interaction, name: str, stat: str, value: int):
        await interaction.response.defer(ephemeral=True)
        if not 1 <= value <= 126:
            await interaction.followup.send("Skill levels must be between 1 and 126.", ephemeral=True); return
        async with AsyncSessionLocal() as db:
            row = await loadouts.resolve_name(db, LOCAL_WORKSPACE_ID, name)
            if not row:
                await interaction.followup.send("Loadout not found.", ephemeral=True); return
            updated, error = await loadouts.update_stats(
                db, LOCAL_WORKSPACE_ID, row.id, row.revision, {stat: value})
            if error:
                await interaction.followup.send("Loadout changed; run the command again.", ephemeral=True); return
            await db.commit()
        await interaction.followup.send(f"Set **{stat}** to `{value}` in **{name}** (revision {updated['revision']}).", ephemeral=True)

    @loadout_group.command(name="preset", description="Set combat style and common OSRS buffs")
    @app_commands.describe(name="Loadout name", stance="Combat stance", attack_type="Attack type",
                           spell="Spell name", on_slayer_task="On a Slayer task", in_wilderness="In the Wilderness")
    @app_commands.autocomplete(name=_name_autocomplete)
    @app_commands.choices(
        stance=[app_commands.Choice(name=value, value=value) for value in
                ("Accurate", "Aggressive", "Autocast", "Controlled", "Defensive", "Defensive Autocast", "Longrange", "Rapid", "Manual Cast")],
        attack_type=[app_commands.Choice(name=value, value=value) for value in ("stab", "slash", "crush", "magic", "ranged")],
    )
    async def loadout_preset(interaction, name: str, stance: str | None = None,
                             attack_type: str | None = None, spell: str | None = None,
                             on_slayer_task: bool | None = None, in_wilderness: bool | None = None):
        await interaction.response.defer(ephemeral=True)
        combat = {key: value for key, value in {"stance": stance, "attack_type": attack_type, "spell": spell}.items() if value is not None}
        buffs = {key: value for key, value in {"on_slayer_task": on_slayer_task, "in_wilderness": in_wilderness}.items() if value is not None}
        if not combat and not buffs:
            await interaction.followup.send("Provide at least one combat or buff setting.", ephemeral=True); return
        async with AsyncSessionLocal() as db:
            row = await loadouts.resolve_name(db, LOCAL_WORKSPACE_ID, name)
            if not row:
                await interaction.followup.send("Loadout not found.", ephemeral=True); return
            updated, error = await loadouts.update_preset(
                db, LOCAL_WORKSPACE_ID, row.id, row.revision, combat=combat, buffs=buffs)
            if error:
                await interaction.followup.send("Loadout changed; run the command again.", ephemeral=True); return
            await db.commit()
        await interaction.followup.send(f"Updated **{name}** (revision {updated['revision']}).", ephemeral=True)

    @bot.event
    async def on_ready():
        print(f"[discord] slash command bot connected as {bot.user}", flush=True)
        async def warm_equipment_catalog():
            try:
                await loadouts.equipment_catalog()
            except Exception as exc:
                print(f"[discord] equipment catalog warmup failed: {exc}", flush=True)
        asyncio.create_task(warm_equipment_catalog())
        try:
            if config.get("guild_id"):
                guild = discord.Object(id=int(config["guild_id"]))
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"[discord] synced {len(synced)} guild slash command(s)", flush=True)
            else:
                synced = await bot.tree.sync()
                print(f"[discord] synced {len(synced)} global slash command(s)", flush=True)
        except Exception as exc:
            print(f"[discord] failed to sync slash commands: {exc}", flush=True)

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot or not bot.user:
            await bot.process_commands(message)
            return

        reply_to_message_id = str(message.reference.message_id) if message.reference and message.reference.message_id else None
        if reply_to_message_id and isinstance(message.channel, discord.Thread):
            from app.discord_integration import handle_discord_approval_reply

            handled = await handle_discord_approval_reply(
                temporal_client,
                guild_id=str(message.guild.id) if message.guild else str(config.get("guild_id") or "discord"),
                discord_thread_id=str(message.channel.id),
                sender_id=str(message.author.id),
                content=message.content or "",
                reply_to_message_id=reply_to_message_id,
                source_message_id=str(message.id),
            )
            if handled:
                await bot.process_commands(message)
                return

        if not bot.user.mentioned_in(message):
            await bot.process_commands(message)
            return

        prompt = _mention_prompt(message)
        if not prompt:
            await message.reply("Mention me with a prompt to start a ThreadBot thread.")
            await bot.process_commands(message)
            return

        guild_id = str(message.guild.id) if message.guild else config.get("guild_id")
        guild_name = message.guild.name if message.guild else None
        sender_name = message.author.global_name or message.author.name or "Discord user"

        from app.discord_integration import (
            reply_to_existing_discord_thread,
            start_thread_from_discord_prompt,
        )

        try:
            # If the mention happened inside an existing Discord thread, post
            # the user message there instead of creating a new thread.
            if isinstance(message.channel, discord.Thread):
                await reply_to_existing_discord_thread(
                    temporal_client,
                    discord_thread_id=str(message.channel.id),
                    guild_id=guild_id,
                    channel_id=str(getattr(message.channel, "parent_id", None) or config.get("channel_id")),
                    guild_name=guild_name,
                    discord_thread_name=message.channel.name,
                    sender_name=sender_name,
                    sender_id=str(message.author.id),
                    prompt=prompt,
                    source_message_id=str(message.id),
                    source_message_link=_message_link(message),
                    source_event_id=str(message.id),
                    source_image_attachments=await _image_attachments(message),
                )
            else:
                await start_thread_from_discord_prompt(
                    temporal_client,
                    prompt,
                    sender_name,
                    sender_id=str(message.author.id),
                    source_message_id=str(message.id),
                    source_message_link=_message_link(message),
                    source_event_id=str(message.id),
                    channel_id=str(message.channel.id),
                    guild_id=guild_id,
                    guild_name=guild_name,
                    source_image_attachments=await _image_attachments(message),
                )
        except Exception as exc:
            print(f"[discord] mention handling failed: {exc}", flush=True)
            await message.reply(f"Failed to handle mention: {exc}")

        await bot.process_commands(message)

    try:
        await bot.start(config["bot_token"])
    except asyncio.CancelledError:
        await bot.close()
        raise
    except Exception as exc:
        print(f"[discord] slash command bot stopped: {exc}", flush=True)
