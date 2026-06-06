import os
import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_BOT_API_KEY = os.getenv("DISCORD_BOT_API_KEY")
WEBSITE_API_URL = os.getenv("WEBSITE_API_URL", "http://127.0.0.1:5000").rstrip("/")


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
            headers={"X-Discord-Bot-Key": DISCORD_BOT_API_KEY or ""}
        )

    async def close(self):
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
