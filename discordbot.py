import asyncio
import os
import shutil

import aiohttp
import discord
import yt_dlp
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_BOT_API_KEY = os.getenv("DISCORD_BOT_API_KEY")
WEBSITE_API_URL = os.getenv("WEBSITE_API_URL", "http://127.0.0.1:5000").rstrip("/")
MEME_SOURCE_URL = "https://meme-api.com/gimme"
FFMPEG_BIN = os.path.join(os.path.dirname(__file__), "ffmpeg", "bin", "ffmpeg.exe")
FFPROBE_BIN = os.path.join(os.path.dirname(__file__), "ffmpeg", "bin", "ffprobe.exe")
YTDLP_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "cachedir": False,
    "extract_flat": False,
}
FFMPEG_OPTIONS = {
    "before_options": "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


def resolve_ffmpeg_path(filename, fallback_name):
    if os.path.exists(filename):
        return filename
    return shutil.which(fallback_name)


def is_youtube_url(url):
    lowered = url.lower()
    return "youtube.com/" in lowered or "youtu.be/" in lowered


def option_label(prefix, text):
    label = f"{prefix}: {text}"
    return label if len(label) <= 80 else f"{label[:77]}..."


def question_embed(question):
    embed = discord.Embed(title="Would You Rather...", color=discord.Color.blurple())
    embed.add_field(name="A", value=question["option_a"], inline=False)
    embed.add_field(name="B", value=question["option_b"], inline=False)
    embed.set_footer(
        text=(
            f"A: {question['votes_a']} ({question['percent_a']}%)  |  "
            f"B: {question['votes_b']} ({question['percent_b']}%)"
        )
    )
    return embed


class WouldYouRatherBot(commands.Bot):
    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(
            headers={
                "X-Discord-Bot-Key": DISCORD_BOT_API_KEY or "",
                "User-Agent": "WouldYouRatherDiscordBot/1.0",
            }
        )
        self.music_queue = []
        self.music_playing = False
        self.music_lock = asyncio.Lock()
        self.music_voice_client = None
        self.current_music_track = None

    async def close(self):
        if getattr(self, "music_voice_client", None) and self.music_voice_client.is_connected():
            await self.music_voice_client.disconnect(force=True)
        if hasattr(self, "http_session"):
            await self.http_session.close()
        await super().close()

    async def website_request(self, method, path, **kwargs):
        url = f"{WEBSITE_API_URL}{path}"
        async with self.http_session.request(method, url, **kwargs) as response:
            data = await response.json()
            if response.status >= 400:
                raise RuntimeError(data.get("error", f"Website returned {response.status}"))
            return data

    async def fetch_random_meme(self):
        async with self.http_session.get(
            MEME_SOURCE_URL,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status >= 400:
                raise RuntimeError(f"Meme API returned {response.status}")

            payload = await response.json()

        image_url = payload.get("url")
        if not image_url:
            raise RuntimeError("No meme image was returned")

        return {
            "title": payload.get("title", "Random Meme"),
            "image_url": image_url,
            "post_url": payload.get("postLink") or payload.get("preview") or image_url,
            "subreddit": payload.get("subreddit", "memes"),
            "author": payload.get("author", "unknown"),
        }

    def extract_youtube_audio(self, url):
        if not is_youtube_url(url):
            raise RuntimeError("Only YouTube links are allowed for music playback.")

        with yt_dlp.YoutubeDL(YTDLP_OPTIONS) as ydl:
            # Stream-only: never download media to disk.
            info = ydl.extract_info(url, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return {
                "title": info.get("title", "Unknown title"),
                "webpage_url": info.get("webpage_url", url),
                "youtube_url": url,
            }

    def ffmpeg_executable(self):
        return resolve_ffmpeg_path(FFMPEG_BIN, "ffmpeg")

    def create_music_source(self, track):
        # Refresh the expiring direct media URL right before playback starts.
        with yt_dlp.YoutubeDL(YTDLP_OPTIONS) as ydl:
            info = ydl.extract_info(track["youtube_url"], download=False)
            if "entries" in info:
                info = info["entries"][0]

        track["title"] = info.get("title", track["title"])
        track["webpage_url"] = info.get("webpage_url", track["youtube_url"])

        return discord.FFmpegPCMAudio(
            info["url"],
            executable=self.ffmpeg_executable(),
            **FFMPEG_OPTIONS,
        )

    async def _start_track(self, ctx, track):
        try:
            source = await asyncio.to_thread(self.create_music_source, track)
        except Exception as exc:
            async with self.music_lock:
                self.music_playing = False
                self.current_music_track = None
            await ctx.send(f"Skipping **{track['title']}** because playback could not start: {exc}")
            await self._continue_music(ctx)
            return

        async with self.music_lock:
            self.current_music_track = track

        def after_playback(error):
            if error:
                print(f"Music playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._continue_music(ctx), self.loop)

        self.music_voice_client.play(source, after=after_playback)
        await ctx.send(f"Now playing: **{track['title']}**")

    async def play_next_track(self, ctx):
        async with self.music_lock:
            if self.music_playing or not self.music_queue:
                return
            self.music_playing = True
            track = self.music_queue.pop(0)
        await self._start_track(ctx, track)

    async def _continue_music(self, ctx):
        async with self.music_lock:
            self.music_playing = False
            self.current_music_track = None
            if self.music_queue and self.music_voice_client and self.music_voice_client.is_connected():
                track = self.music_queue.pop(0)
                self.music_playing = True
            else:
                track = None

        if track is None:
            return
        await self._start_track(ctx, track)


class VoteButton(discord.ui.Button):
    def __init__(self, choice, option_text):
        style = discord.ButtonStyle.primary if choice == "a" else discord.ButtonStyle.success
        super().__init__(label=option_label(choice.upper(), option_text), style=style)
        self.choice = choice

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        view = self.view

        try:
            result = await interaction.client.website_request(
                "POST",
                "/api/discord/vote",
                json={
                    "question_id": view.question["id"],
                    "choice": self.choice,
                    "user_id": str(interaction.user.id),
                    "username": interaction.user.name,
                    "display_name": interaction.user.display_name,
                },
            )
        except (aiohttp.ClientError, RuntimeError) as exc:
            await interaction.followup.send(f"Could not record your vote: {exc}", ephemeral=True)
            return

        view.question.update(result)
        await interaction.message.edit(embed=question_embed(view.question), view=view)

        if result["already_voted"]:
            message = "You already voted on this question."
        else:
            message = f"Your vote for **{view.question[f'option_{self.choice}']}** was recorded."
        await interaction.followup.send(message, ephemeral=True)


class VoteView(discord.ui.View):
    def __init__(self, question):
        super().__init__(timeout=600)
        self.question = question
        self.add_item(VoteButton("a", question["option_a"]))
        self.add_item(VoteButton("b", question["option_b"]))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = WouldYouRatherBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Discord bot logged in as {bot.user}")


@bot.command()
async def wouldyourather(ctx):
    """Post a random approved website question with voting buttons."""
    try:
        question = await bot.website_request("GET", "/api/discord/question")
    except (aiohttp.ClientError, RuntimeError) as exc:
        await ctx.send(f"Could not get a question from the website: {exc}")
        return

    await ctx.send(embed=question_embed(question), view=VoteView(question))


@bot.command()
async def commands(ctx):
    """Show all available bot commands."""
    embed = discord.Embed(
        title="Available Commands",
        description="Here are the commands you can use with this bot:",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="!wouldyourather",
        value="Post a random Would You Rather question.",
        inline=False,
    )
    embed.add_field(
        name="!resetvotes",
        value="Clear Discord vote history for the bot owner.",
        inline=False,
    )
    embed.add_field(
        name="!meme",
        value="Pull a random meme from the internet.",
        inline=False,
    )
    embed.add_field(
        name="!play",
        value="Queue a YouTube link to play in `Bot-Music`.",
        inline=False,
    )
    embed.add_field(
        name="!stopmusic",
        value="Stop music and clear the queue. Owner only.",
        inline=False,
    )
    embed.add_field(
        name="!showmusic",
        value="Show the current song and the queued songs.",
        inline=False,
    )
    embed.add_field(
        name="!commands",
        value="Show this command list.",
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command()
async def meme(ctx):
    """Pull a random meme from a public meme API."""
    try:
        meme = await bot.fetch_random_meme()
    except (aiohttp.ClientError, RuntimeError, KeyError, IndexError, TypeError) as exc:
        await ctx.send(f"Could not fetch a meme right now: {exc}")
        return

    embed = discord.Embed(
        title=meme["title"][:256],
        url=meme["post_url"],
        color=discord.Color.orange(),
    )
    embed.set_image(url=meme["image_url"])
    embed.set_footer(text=f"r/{meme['subreddit']} - by u/{meme['author']}")
    await ctx.send(embed=embed)


@bot.command()
async def play(ctx, *, youtube_url: str):
    """Queue and play audio from a YouTube URL in the Bot-Music voice channel."""
    voice_channel = discord.utils.get(ctx.guild.voice_channels, name="Bot-Music")
    if voice_channel is None:
        await ctx.send("I could not find a voice channel named `Bot-Music`.")
        return

    if not ctx.author.voice or ctx.author.voice.channel != voice_channel:
        await ctx.send("You need to be in the `Bot-Music` voice channel to use this command.")
        return

    if not is_youtube_url(youtube_url):
        await ctx.send("Only YouTube links are allowed. I will not download or play files from other sites.")
        return

    ffmpeg_path = bot.ffmpeg_executable()
    if not ffmpeg_path:
        await ctx.send(
            "I could not find `ffmpeg.exe`. It should be in `ffmpeg\\bin` or available on PATH."
        )
        return

    try:
        track = await asyncio.to_thread(bot.extract_youtube_audio, youtube_url)
    except Exception as exc:
        await ctx.send(f"Could not load that YouTube link: {exc}")
        return

    async with bot.music_lock:
        bot.music_queue.append(track)
        should_start = not bot.music_playing

    if bot.music_voice_client is None or not bot.music_voice_client.is_connected():
        try:
            bot.music_voice_client = await voice_channel.connect(reconnect=True)
        except (discord.ClientException, discord.Forbidden, discord.HTTPException, OSError) as exc:
            await ctx.send(f"I could not join `Bot-Music`: {exc}")
            return
        if bot.music_voice_client is None or not bot.music_voice_client.is_connected():
            bot.music_voice_client = discord.utils.get(bot.voice_clients, channel=voice_channel)
            if bot.music_voice_client is None or not bot.music_voice_client.is_connected():
                await ctx.send("I could not connect to the `Bot-Music` voice channel.")
                return

    await ctx.send(f"Queued: **{track['title']}**")

    if should_start:
        await bot.play_next_track(ctx)


@bot.command()
async def stopmusic(ctx):
    """Stop music and clear the queue. Owner only."""
    if ctx.author.name != "hackerpro13":
        await ctx.send("Only hackerpro13 can use this command.")
        return

    async with bot.music_lock:
        bot.music_queue.clear()
        bot.music_playing = False

    if bot.music_voice_client and bot.music_voice_client.is_connected():
        bot.music_voice_client.stop()
        await bot.music_voice_client.disconnect(force=True)
        bot.music_voice_client = None

    await ctx.send("Music stopped and the queue was cleared.")


@bot.command()
async def showmusic(ctx):
    """Show the currently playing song and the queued songs."""
    async with bot.music_lock:
        current_track = bot.current_music_track
        queued_tracks = list(bot.music_queue)

    if current_track is None and not queued_tracks:
        await ctx.send("There are no songs in the queue right now.")
        return

    embed = discord.Embed(
        title="Music Queue",
        color=discord.Color.blurple(),
    )

    if current_track is not None:
        embed.add_field(
            name="Now Playing",
            value=f"1. {current_track['title']}",
            inline=False,
        )

    if queued_tracks:
        queued_lines = [f"{index}. {track['title']}" for index, track in enumerate(queued_tracks, start=1)]
        embed.add_field(
            name="Up Next",
            value="\n".join(queued_lines[:25]),
            inline=False,
        )
        if len(queued_tracks) > 25:
            embed.set_footer(text=f"And {len(queued_tracks) - 25} more queued song(s).")

    await ctx.send(embed=embed)


@bot.command()
async def resetvotes(ctx):
    """Clear Discord vote history for the bot owner."""
    if ctx.author.name != "hackerpro13":
        await ctx.send("Only hackerpro13 can use this command.")
        return

    try:
        await bot.website_request(
            "POST",
            "/api/discord/reset-votes",
            json={"username": ctx.author.name},
        )
    except (aiohttp.ClientError, RuntimeError) as exc:
        await ctx.send(f"Could not reset Discord votes: {exc}")
        return

    await ctx.send("Discord vote history has been cleared.")


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("Add DISCORD_BOT_TOKEN to .env before starting the bot.")
    if not DISCORD_BOT_API_KEY:
        raise RuntimeError("Add DISCORD_BOT_API_KEY to .env before starting the bot.")
    bot.run(DISCORD_BOT_TOKEN)
