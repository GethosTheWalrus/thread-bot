import asyncio

from temporalio.client import Client as TemporalClient

from app.config import get_discord_config


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

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    def _message_link(message: discord.Message) -> str:
        guild_id = message.guild.id if message.guild else "@me"
        return f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"

    def _mention_prompt(message: discord.Message) -> str:
        content = message.content or ""
        if bot.user:
            content = content.replace(f"<@{bot.user.id}>", "")
            content = content.replace(f"<@!{bot.user.id}>", "")
        return content.strip()

    @bot.tree.command(name="threadbot", description="Start a new ThreadBot thread from Discord")
    @app_commands.describe(prompt="The first message to send to ThreadBot")
    async def threadbot_command(interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        from app.discord_integration import start_thread_from_discord_prompt

        try:
            channel_id = str(interaction.channel_id) if interaction.channel_id else config.get("channel_id")
            guild_id = str(interaction.guild_id) if interaction.guild_id else config.get("guild_id")
            sender_name = interaction.user.global_name or interaction.user.name or "Discord user"
            await start_thread_from_discord_prompt(
                temporal_client,
                prompt,
                sender_name,
                channel_id=channel_id,
                guild_id=guild_id,
            )
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
        except Exception as exc:
            print(f"[discord] slash command failed: {exc}", flush=True)
            await interaction.followup.send(f"Failed to start ThreadBot thread: {exc}", ephemeral=True)

    @bot.event
    async def on_ready():
        print(f"[discord] slash command bot connected as {bot.user}", flush=True)
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
        if message.author.bot or not bot.user or not bot.user.mentioned_in(message):
            await bot.process_commands(message)
            return

        prompt = _mention_prompt(message)
        if not prompt:
            await message.reply("Mention me with a prompt to start a ThreadBot thread.")
            await bot.process_commands(message)
            return

        from app.discord_integration import start_thread_from_discord_prompt

        try:
            guild_id = str(message.guild.id) if message.guild else config.get("guild_id")
            sender_name = message.author.global_name or message.author.name or "Discord user"
            await start_thread_from_discord_prompt(
                temporal_client,
                prompt,
                sender_name,
                source_message_id=str(message.id),
                source_message_link=_message_link(message),
                channel_id=str(message.channel.id),
                guild_id=guild_id,
            )
        except Exception as exc:
            print(f"[discord] mention handling failed: {exc}", flush=True)
            await message.reply(f"Failed to start ThreadBot thread: {exc}")

        await bot.process_commands(message)

    try:
        await bot.start(config["bot_token"])
    except asyncio.CancelledError:
        await bot.close()
        raise
    except Exception as exc:
        print(f"[discord] slash command bot stopped: {exc}", flush=True)
