import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

import config
from autogidas.scrapeGidas import scrape as scrape_autogidas
from autogidas.autogidas import autogidas as AutoGidas
from autoplius.scrapePlius import scrape as scrape_autoplius
from autoplius.autoplius import autoplius as AutoPlius

LT_TZ = ZoneInfo("Europe/Vilnius")


def build_embeds(listing: dict, color: discord.Color, footer: str) -> list[discord.Embed]:
    images = listing.get('images') or []
    images = images[:4]
    if not images:
        embed = discord.Embed(title=listing['title'], url=listing['url'], description=listing['description'] or '', color=color)
        embed.set_footer(text=footer)
        return [embed]
    embeds = []
    for i, img in enumerate(images):
        embed = discord.Embed(url=listing['url'], color=color)
        if i == 0:
            embed.title = listing['title']
            embed.description = listing['description'] or ''
            embed.set_footer(text=footer)
        embed.set_image(url=img)
        embeds.append(embed)
    return embeds


def _seconds_until_active() -> float:
    start = config.SCRAPE_START_HOUR
    end = config.SCRAPE_END_HOUR
    if start == 0 and end >= 24:
        return 0  # 24/7 mode

    now = datetime.now(LT_TZ)
    frac = now.hour + now.minute / 60 + now.second / 3600

    if start <= frac < end:
        return 0

    if frac < start:
        delta_hours = start - frac
    else:
        delta_hours = (24 - frac) + start
    return delta_hours * 3600


def _resume_time_str() -> str:
    now = datetime.now(LT_TZ)
    frac = now.hour + now.minute / 60 + now.second / 3600
    start = config.SCRAPE_START_HOUR

    if frac >= start:
        resume = (now + timedelta(days=1)).replace(hour=start, minute=0, second=0, microsecond=0)
    else:
        resume = now.replace(hour=start, minute=0, second=0, microsecond=0)
    return resume.strftime("%H:%M LT, %d %b")


intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
GUILD = discord.Object(id=config.DISCORD_GUILD_ID)

# { id: { "source": str, "url": str, "task": asyncio.Task, "channel_id": int } }
active_searches: dict[int, dict] = {}
next_id = 1


async def autogidas_loop(search_id: int, url: str, channel: discord.TextChannel):
    client = AutoGidas(proxy=config.PROXY)
    sleeping = False

    async def on_new_listing(href: str):
        listing = await client.get_listing(href)
        if listing and listing['title']:
            await channel.send(embeds=build_embeds(listing, discord.Color.green(), f"AutoGidas #{search_id}"))
        else:
            await channel.send(href)

    while True:
        wait = _seconds_until_active()
        if wait > 0:
            if not sleeping:
                await channel.send(
                    f"**[AutoGidas #{search_id}]** Outside active hours "
                    f"({config.SCRAPE_START_HOUR:02d}:00–{config.SCRAPE_END_HOUR:02d}:00 LT). "
                    f"Resuming at {_resume_time_str()}."
                )
                sleeping = True
            await asyncio.sleep(60)
            continue

        if sleeping:
            await channel.send(f"**[AutoGidas #{search_id}]** Active hours started — resuming.")
            sleeping = False

        try:
            await scrape_autogidas(url, client=client, on_new_listing=on_new_listing)
        except Exception as e:
            await channel.send(f"**[AutoGidas #{search_id}]** Error: {e}")
        await asyncio.sleep(config.SCRAPE_FETCH_DELAY)


async def autoplius_loop(search_id: int, url: str, channel: discord.TextChannel):
    client = AutoPlius(proxy=config.PROXY)
    sleeping = False

    async def on_new_listing(href: str):
        listing = await client.get_listing(href)
        if listing and listing['title']:
            await channel.send(embeds=build_embeds(listing, discord.Color.blue(), f"Autoplius #{search_id}"))
        else:
            await channel.send(href)

    while True:
        wait = _seconds_until_active()
        if wait > 0:
            if not sleeping:
                await channel.send(
                    f"**[Autoplius #{search_id}]** Outside active hours "
                    f"({config.SCRAPE_START_HOUR:02d}:00–{config.SCRAPE_END_HOUR:02d}:00 LT). "
                    f"Resuming at {_resume_time_str()}."
                )
                sleeping = True
            await asyncio.sleep(60)
            continue

        if sleeping:
            await channel.send(f"**[Autoplius #{search_id}]** Active hours started — resuming.")
            sleeping = False

        try:
            await scrape_autoplius(url, client=client, on_new_listing=on_new_listing)
        except Exception as e:
            await channel.send(f"**[Autoplius #{search_id}]** Error: {e}")
        await asyncio.sleep(config.SCRAPE_FETCH_DELAY)


@bot.event
async def on_ready():
    bot.tree.clear_commands(guild=None) # remove stale global commands
    await bot.tree.sync() # push empty global command list
    guild = discord.Object(id=config.DISCORD_GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"Logged in as {bot.user}")
    print(f"  AutoGidas  -> channel {config.AUTOGIDAS_DISCORD_CHANNEL_ID}")
    print(f"  Autoplius  -> channel {config.AUTOPLIUS_DISCORD_CHANNEL_ID}")
    print(f"  Active hours: {config.SCRAPE_START_HOUR:02d}:00 – {config.SCRAPE_END_HOUR:02d}:00 LT")


@bot.tree.command(name="autogidas", description="Start watching an autogidas.lt URL for new listings", guild=GUILD)
@app_commands.describe(url="The autogidas.lt search URL to monitor")
async def autogidas_cmd(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    global next_id
    search_id = next_id
    next_id += 1

    channel = bot.get_channel(config.AUTOGIDAS_DISCORD_CHANNEL_ID) or interaction.channel
    task = asyncio.create_task(autogidas_loop(search_id, url, channel))

    active_searches[search_id] = {
        "source": "autogidas",
        "url": url,
        "task": task,
        "channel_id": channel.id,
    }

    await interaction.followup.send(
        f"Started AutoGidas monitoring **#{search_id}**: <{url}>\n"
        f"Fetch interval: {config.SCRAPE_FETCH_DELAY}s | "
        f"Active hours: {config.SCRAPE_START_HOUR:02d}:00–{config.SCRAPE_END_HOUR:02d}:00 LT"
    )


@bot.tree.command(name="autoplius", description="Start watching an autoplius.lt URL for new listings", guild=GUILD)
@app_commands.describe(url="The autoplius.lt search URL to monitor")
async def autoplius_cmd(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    global next_id
    search_id = next_id
    next_id += 1

    channel = bot.get_channel(config.AUTOPLIUS_DISCORD_CHANNEL_ID) or interaction.channel
    task = asyncio.create_task(autoplius_loop(search_id, url, channel))

    active_searches[search_id] = {
        "source": "autoplius",
        "url": url,
        "task": task,
        "channel_id": channel.id,
    }

    await interaction.followup.send(
        f"Started Autoplius monitoring **#{search_id}**: <{url}>\n"
        f"Fetch interval: {config.SCRAPE_FETCH_DELAY}s | "
        f"Active hours: {config.SCRAPE_START_HOUR:02d}:00–{config.SCRAPE_END_HOUR:02d}:00 LT"
    )


@bot.tree.command(name="list", description="List all active listing searches", guild=GUILD)
async def list_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    if not active_searches:
        await interaction.followup.send("No active searches.")
        return

    lines = [f"**#{sid}** [{s['source']}] — <{s['url']}>" for sid, s in active_searches.items()]
    await interaction.followup.send("\n".join(lines))


@bot.tree.command(name="stop", description="Stop a listing search by ID", guild=GUILD)
@app_commands.describe(id="The search ID to stop")
async def stop_cmd(interaction: discord.Interaction, id: int):
    await interaction.response.defer()
    if id not in active_searches:
        await interaction.followup.send(f"No active search with ID #{id}.")
        return

    active_searches[id]["task"].cancel()
    del active_searches[id]
    await interaction.followup.send(f"Stopped search **#{id}**.")
