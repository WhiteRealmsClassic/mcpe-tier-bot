```python
import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import *
from database import Database


# ======================================================
# HELPERS
# ======================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def emoji(gm):
    _, name, eid, _ = GAMEMODES[gm]
    return f"<:{name}:{eid}>"


def bar(n):
    n = max(0, min(15, n))
    return "■" * n + "□" * (15 - n)


def add_server_logo(embed):

    if SERVER_LOGO_URL:
        embed.set_thumbnail(
            url=SERVER_LOGO_URL
        )

    return embed


# ======================================================
# BOT
# ======================================================

class TierBot(commands.Bot):

    def __init__(self):

        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents
        )

        self.db = Database(DB_PATH)

        self.refresh_lock = asyncio.Lock()

    # ==================================================
    # SETUP
    # ==================================================

    async def setup_hook(self):

        await self.load_extension(
            "moderation"
        )

        self.add_view(
            ApplyView(self)
        )

        self.add_view(
            TicketView(self)
        )

        self.add_view(
            ResultView(self)
        )

        self.add_view(
            QueueView(self)
        )

        self.add_view(
            LeaderboardView(self)
        )

        guild = discord.Object(
            id=GUILD_ID
        )

        self.tree.copy_global_to(
            guild=guild
        )

        await self.tree.sync(
            guild=guild
        )

    # ==================================================
    # READY
    # ==================================================

    async def on_ready(self):

        print(
            f"Logged in as {self.user} "
            f"({self.user.id})"
        )

        print(
            f"Database integrity: "
            f"{self.db.integrity_check()}"
        )

        await self.refresh_apply_message()
        await self.refresh_queue_message()
        await self.refresh_leaderboard()

    # ==================================================
    # STAFF
    # ==================================================

    def has_staff(self, member):

        if not isinstance(
            member,
            discord.Member
        ):
            return False

        return (
            member.guild_permissions.manage_guild
            or any(
                role.id in {
                    TESTER_ROLE_ID,
                    STAFF_ROLE_ID
                }
                for role in member.roles
            )
        )

    # ==================================================
    # SETTINGS
    # ==================================================

    def get_message_id(self, key):

        value = self.db.get_setting(
            key
        )

        if not value:
            return None

        try:

            return int(value)

        except (
            ValueError,
            TypeError
        ):

            return None

    def save_message_id(
        self,
        key,
        message_id
    ):

        self.db.save_setting(
            key,
            message_id
        )

    # ==================================================
    # REAL ACTIVE TICKET
    # ==================================================

    async def get_real_active_ticket(
        self,
        user_id
    ):

        ticket = self.db.ticket_for_user(
            user_id
        )

        if not ticket:
            return None

        guild = self.get_guild(
            GUILD_ID
        )

        if guild is None:
            return ticket

        try:

            channel = await guild.fetch_channel(
                ticket["channel_id"]
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):

            channel = None

        if channel is not None:
            return ticket

        self.db.close_ticket(
            ticket["channel_id"],
            now(),
            "channel_missing"
        )

        self.db.queue_remove(
            user_id
        )

        return None

    # ==================================================
    # APPLY EMBED
    # ==================================================

    def apply_embed(self):

        embed = discord.Embed(
            title="MCPE Tier Testing",
            description=(
                "Click the **Queue** button below "
                "to request an MCPE PvP tier test."
            ),
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="How it works",
            value=(
                "Select a gamemode, enter your "
                "Minecraft username and preferred "
                "server, then wait for a tester."
            ),
            inline=False
        )

        embed.set_footer(
            text="MCPE Tier Testing"
        )

        return add_server_logo(
            embed
        )

    # ==================================================
    # APPLY PANEL
    # ==================================================

    async def refresh_apply_message(self):

        channel = self.get_channel(
            APPLY_CHANNEL_ID
        )

        if not channel:
            return

        message_id = self.get_message_id(
            "apply_message_id"
        )

        message = None

        if message_id:

            try:

                message = await channel.fetch_message(
                    message_id
                )

            except discord.NotFound:

                message = None

            except (
                discord.Forbidden,
                discord.HTTPException
            ):

                return

        if not message:

            try:

                message = await channel.send(
                    embed=self.apply_embed(),
                    view=ApplyView(self)
                )

            except (
                discord.Forbidden,
                discord.HTTPException
            ):

                return

        else:

            try:

                await message.edit(
                    content=None,
                    embed=self.apply_embed(),
                    view=ApplyView(self)
                )

            except (
                discord.Forbidden,
                discord.HTTPException
            ):

                return

        self.save_message_id(
            "apply_message_id",
            message.id
        )

    # ==================================================
    # QUEUE EMBED
    # ==================================================

    def queue_embed(self):

        embed = discord.Embed(
            title="MCPE Tier Testing Queue",
            description=(
                "Live queue status for all "
                "MCPE testing gamemodes."
            ),
            color=discord.Color.blurple()
        )

        for gm, data in GAMEMODES.items():

            count = self.db.count(
                gm
            )

            embed.add_field(
                name=(
                    f"{emoji(gm)} "
                    f"{data[0]}"
                ),
                value=(
                    f"**{count}/15**\n"
                    f"`{bar(count)}`"
                ),
                inline=False
            )

        embed.set_footer(
            text="Use Leave Queue to leave your queue."
        )

        return add_server_logo(
            embed
        )

    # ==================================================
    # QUEUE REFRESH
    # ==================================================

    async def refresh_queue_message(self):

        async with self.refresh_lock:

            channel = self.get_channel(
                QUEUE_CHANNEL_ID
            )

            if not channel:
                return

            message_id = self.get_message_id(
                "queue_message_id"
            )

            message = None

            if message_id:

                try:

                    message = await channel.fetch_message(
                        message_id
                    )

                except discord.NotFound:

                    message = None

                except (
                    discord.Forbidden,
                    discord.HTTPException
                ):

                    return

            if not message:

                try:

                    message = await channel.send(
                        embed=self.queue_embed(),
                        view=QueueView(self)
                    )

                except (
                    discord.Forbidden,
                    discord.HTTPException
                ):

                    return

            else:

                try:

                    await message.edit(
                        content=None,
                        embed=self.queue_embed(),
                        view=QueueView(self)
                    )

                except (
                    discord.Forbidden,
                    discord.HTTPException
                ):

                    return

            self.save_message_id(
                "queue_message_id",
                message.id
            )

    # ==================================================
    # GLOBAL LEADERBOARD
    # ==================================================

    def global_leaderboard_embed(self):

        rows = self.db.global_leaderboard()

        embed = discord.Embed(
            title="🏆 MCPE Global Leaderboard",
            description=(
                "Combined points from **every gamemode**."
            ),
            color=discord.Color.gold()
        )

        if not rows:

            embed.add_field(
                name="Rankings",
                value="No tested players yet.",
                inline=False
            )

            embed.set_footer(
                text="Complete a tier test to appear here."
            )

            return add_server_logo(
                embed
            )

        lines = []

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉"
        }

        for index, row in enumerate(
            rows[:20],
            1
        ):

            medal = medals.get(
                index,
                f"`#{index}`"
            )

            lines.append(
                f"{medal} "
                f"`{row['minecraft_username']}` "
                f"| **{row['total_points']}pts** "
                f"| `{row['tests']} tests`"
            )

        embed.add_field(
            name="Global Rankings",
            value="\n".join(lines),
            inline=False
        )

        embed.set_footer(
            text=(
                "Points from all completed gamemode "
                "tests are combined."
            )
        )

        return add_server_logo(
            embed
        )

    # ==================================================
    # GAMEMODE LEADERBOARD
    # ==================================================

    def leaderboard_embed(
        self,
        selected_gm=None
    ):

        if selected_gm is None:

            selected_gm = next(
                iter(GAMEMODES)
            )

        rows = self.db.gamemode_leaderboard(
            selected_gm
        )

        embed = discord.Embed(
            title="MCPE Tier Leaderboard",
            color=discord.Color.gold()
        )

        embed.description = (
            f"{emoji(selected_gm)} "
            f"**{GAMEMODES[selected_gm][0]}**"
        )

        if not rows:

            embed.add_field(
                name="Rankings",
                value="No tested players yet.",
                inline=False
            )

        else:

            lines = []

            for index, row in enumerate(
                rows[:20],
                1
            ):

                lines.append(
                    f"`#{index}` "
                    f"`{row['minecraft_username']}` "
                    f"| **{row['total_points']}pts** "
                    f"| `{row['tests']} tests`"
                )

            embed.add_field(
                name="Rankings",
                value="\n".join(lines),
                inline=False
            )

        embed.set_footer(
            text="Select a gamemode below."
        )

        return add_server_logo(
            embed
        )

    # ==================================================
    # LEADERBOARD REFRESH
    # ==================================================

    async def refresh_leaderboard(
        self,
        selected_gm=None
    ):

        channel = self.get_channel(
            LEADERBOARD_CHANNEL_ID
        )

        if not channel:
            return

        message_id = self.get_message_id(
            "leaderboard_message_id"
        )

        message = None

        if message_id:

            try:

                message = await channel.fetch_message(
                    message_id
                )

            except discord.NotFound:

                message = None

            except (
                discord.Forbidden,
                discord.HTTPException
            ):

                return

        embed = (
            self.global_leaderboard_embed()
            if selected_gm == "global"
            else self.leaderboard_embed(
                selected_gm
            )
        )

        if not message:

            try:

                message = await channel.send(
                    embed=embed,
                    view=LeaderboardView(self)
                )

            except (
                discord.Forbidden,
                discord.HTTPException
            ):

                return

        else:

            try:

                await message.edit(
                    content=None,
                    embed=embed,
                    view=LeaderboardView(self)
                )

            except (
                discord.Forbidden,
                discord.HTTPException
            ):

                return

        self.save_message_id(
            "leaderboard_message_id",
            message.id
        )

    # ==================================================
    # AUDIT
    # ==================================================

    async def log(self, text):

        channel = self.get_channel(
            AUDIT_CHANNEL_ID
        )

        if channel:

            try:
                await channel.send(
                    text
                )

            except discord.HTTPException:
                pass


# ======================================================
# APPLY VIEW
# ======================================================

class ApplyView(discord.ui.View):

    def __init__(self, bot):

        super().__init__(
            timeout=None
        )

        self.bot = bot

    @discord.ui.button(
        label="Queue",
        style=discord.ButtonStyle.primary,
        custom_id="tierbot:queue"
    )
    async def queue(
        self,
        interaction,
        button
    ):

        active = await self.bot.get_real_active_ticket(
            interaction.user.id
        )

        if active:

            return await interaction.response.send_message(
                "You already have an active test ticket.",
                ephemeral=True
            )

        queued = self.bot.db.queue_for_user(
            interaction.user.id
        )

        if queued:

            return await interaction.response.send_message(
                "You are already in a queue.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "Select your gamemode:",
            view=GamemodeView(self.bot),
            ephemeral=True
        )


# ======================================================
# GAMEMODE VIEW
# ======================================================

class GamemodeView(discord.ui.View):

    def __init__(self, bot):

        super().__init__(
            timeout=120
        )

        self.bot = bot

        options = []

        for key, value in GAMEMODES.items():

            options.append(
                discord.SelectOption(
                    label=value[0],
                    value=key,
                    emoji=discord.PartialEmoji(
                        name=value[1],
                        id=value[2]
                    )
                )
            )

        self.select = discord.ui.Select(
            placeholder="Select Gamemode",
            options=options
        )

        self.select.callback = self.selected

        self.add_item(
            self.select
        )

    async def selected(
        self,
        interaction
    ):

        active = await self.bot.get_real_active_ticket(
            interaction.user.id
        )

        if active:

            return await interaction.response.send_message(
                "You already have an active test ticket.",
                ephemeral=True
            )

        if self.bot.db.queue_for_user(
            interaction.user.id
        ):

            return await interaction.response.send_message(
                "You are already in a queue.",
                ephemeral=True
            )

        gm = self.select.values[0]

        if self.bot.db.count(gm) >= 15:

            return await interaction.response.send_message(
                "That queue is full (15/15).",
                ephemeral=True
            )

        await interaction.response.send_modal(
            QueueModal(
                self.bot,
                gm
            )
        )


# ======================================================
# QUEUE MODAL
# ======================================================

class QueueModal(
    discord.ui.Modal,
    title="MCPE Test Request"
):

    username = discord.ui.TextInput(
        label="Minecraft username",
        placeholder="Your Bedrock username",
        max_length=32
    )

    server = discord.ui.TextInput(
        label="Preferred server",
        placeholder="Server name/IP",
        max_length=100
    )

    def __init__(
        self,
        bot,
        gm
    ):

        super().__init__()

        self.bot = bot
        self.gm = gm

    async def on_submit(
        self,
        interaction
    ):

        minecraft_username = (
            self.username.value.strip()
        )

        preferred_server = (
            self.server.value.strip()
        )

        if not minecraft_username:

            return await interaction.response.send_message(
                "Minecraft username cannot be empty.",
                ephemeral=True
            )

        if not preferred_server:

            return await interaction.response.send_message(
                "Preferred server cannot be empty.",
                ephemeral=True
            )

        active = await self.bot.get_real_active_ticket(
            interaction.user.id
        )

        if active:

            return await interaction.response.send_message(
                "You already have an active test ticket.",
                ephemeral=True
            )

        if self.bot.db.queue_for_user(
            interaction.user.id
        ):

            return await interaction.response.send_message(
                "You are already in a queue.",
                ephemeral=True
            )

        guild = interaction.guild

        if guild is None:

            return await interaction.response.send_message(
                "This request must be made inside the Discord server.",
                ephemeral=True
            )

        category = guild.get_channel(
            TICKET_CATEGORY_ID
        )

        if category is None:

            return await interaction.response.send_message(
                "The ticket category could not be found.",
                ephemeral=True
            )

        ok, reason = self.bot.db.queue_join(
            interaction.user.id,
            self.gm,
            minecraft_username,
            preferred_server,
            now(),
            15
        )

        if not ok:

            messages = {
                "already_queued":
                    "You are already in a queue.",

                "full":
                    "That queue is full (15/15).",

                "invalid_username":
                    "Invalid Minecraft username.",

                "invalid_server":
                    "Invalid preferred server."
            }

            return await interaction.response.send_message(
                messages.get(
                    reason,
                    "Unable to join the queue."
                ),
                ephemeral=True
            )

        overwrites = {

            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            interaction.user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
        }

        tester = guild.get_role(
            TESTER_ROLE_ID
        )

        staff = guild.get_role(
            STAFF_ROLE_ID
        )

        if tester:

            overwrites[tester] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            )

        if staff:

            overwrites[staff] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            )

        channel = None

        try:

            channel = await guild.create_text_channel(
                f"test-{interaction.user.name}"[:95],
                category=category,
                overwrites=overwrites,
                reason="MCPE tier test ticket"
            )

            created = self.bot.db.create_ticket(
                channel.id,
                interaction.user.id,
                self.gm,
                minecraft_username,
                preferred_server,
                now()
            )

            if not created:

                await channel.delete(
                    reason="Duplicate ticket prevention"
                )

                self.bot.db.queue_remove(
                    interaction.user.id
                )

                return await interaction.response.send_message(
                    "You already have an active test ticket.",
                    ephemeral=True
                )

        except Exception:

            self.bot.db.queue_remove(
                interaction.user.id
            )

            if channel:

                try:
                    await channel.delete(
                        reason="Ticket creation failed"
                    )
                except discord.HTTPException:
                    pass

            raise

        embed = discord.Embed(
            title="MCPE Tier Test",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="Player",
            value=interaction.user.mention,
            inline=False
        )

        embed.add_field(
            name="Minecraft",
            value=minecraft_username,
            inline=True
        )

        embed.add_field(
            name="Gamemode",
            value=(
                f"{emoji(self.gm)} "
                f"{GAMEMODES[self.gm][0]}"
            ),
            inline=True
        )

        embed.add_field(
            name="Preferred Server",
            value=preferred_server,
            inline=False
        )

        embed.add_field(
            name="Status",
            value=(
                "Waiting for a tester "
                "to claim this test."
            ),
            inline=False
        )

        add_server_logo(
            embed
        )

        await channel.send(
            embed=embed,
            view=TicketView(self.bot)
        )

        await interaction.response.send_message(
            f"Your private test ticket is {channel.mention}.",
            ephemeral=True
        )

        await self.bot.refresh_queue_message()


# ======================================================
# TICKET VIEW
# ======================================================

class TicketView(discord.ui.View):

    def __init__(self, bot):

        super().__init__(
            timeout=None
        )

        self.bot = bot

    @discord.ui.button(
        label="Claim Test",
        style=discord.ButtonStyle.success,
        custom_id="tierbot:claim"
    )
    async def claim(
        self,
        interaction,
        button
    ):

        if not self.bot.has_staff(
            interaction.user
        ):

            return await interaction.response.send_message(
                "Only testers/staff can claim tests.",
                ephemeral=True
            )

        ticket = self.bot.db.ticket(
            interaction.channel.id
        )

        if not ticket:

            return await interaction.response.send_message(
                "Ticket data was not found.",
                ephemeral=True
            )

        if ticket["status"] != "waiting":

            return await interaction.response.send_message(
                "This ticket has already been claimed.",
                ephemeral=True
            )

        claimed = self.bot.db.claim_ticket(
            interaction.channel.id,
            interaction.user.id,
            now()
        )

        if not claimed:

            return await interaction.response.send_message(
                "Another tester claimed it first.",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"Test claimed by {interaction.user.mention}."
        )

        embed = discord.Embed(
            title="Test In Progress",
            description=(
                "When the match is finished, click "
                "**Submit Test Result** to submit the "
                "player's final rank, match score "
                "and custom verdict.\n\n"
                "Points are assigned automatically "
                "from the final tier."
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="Only the assigned tester can submit the result."
        )

        add_server_logo(
            embed
        )

        await interaction.channel.send(
            embed=embed,
            view=ResultView(self.bot)
        )


# ======================================================
# RESULT VIEW
# ======================================================

class ResultView(discord.ui.View):

    def __init__(self, bot):

        super().__init__(
            timeout=None
        )

        self.bot = bot

    @discord.ui.button(
        label="Submit Test Result",
        style=discord.ButtonStyle.success,
        custom_id="tierbot:submit_result"
    )
    async def submit_result(
        self,
        interaction,
        button
    ):

        if not self.bot.has_staff(
            interaction.user
        ):

            return await interaction.response.send_message(
                "Only testers/staff can submit results.",
                ephemeral=True
            )

        ticket = self.bot.db.ticket(
            interaction.channel.id
        )

        if not ticket:

            return await interaction.response.send_message(
                "Ticket data was not found.",
                ephemeral=True
            )

        if ticket["status"] != "testing":

            return await interaction.response.send_message(
                "This test is no longer active.",
                ephemeral=True
            )

        if ticket["tester_id"] != interaction.user.id:

            return await interaction.response.send_message(
                "Only the tester who claimed this ticket can submit the result.",
                ephemeral=True
            )

        await interaction.response.send_modal(
            ResultModal(
                self.bot,
                ticket
            )
        )


# ======================================================
# RESULT MODAL
# ======================================================

class ResultModal(
    discord.ui.Modal,
    title="MCPE Test Result"
):

    rank = discord.ui.TextInput(
        label="Final Rank",
        placeholder="Example: HT2",
        max_length=10
    )

    match_score = discord.ui.TextInput(
        label="Match Score",
        placeholder="Example: 5-0",
        max_length=20
    )

    verdict = discord.ui.TextInput(
        label="Custom Verdict",
        placeholder="Write your verdict for the player...",
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    def __init__(
        self,
        bot,
        ticket
    ):

        super().__init__()

        self.bot = bot
        self.ticket_data = ticket

    async def on_submit(
        self,
        interaction
    ):

        tier = self.rank.value.strip().upper()

        match_score = (
            self.match_score.value.strip()
        )

        verdict = (
            self.verdict.value.strip()
        )

        if tier not in TIERS:

            return await interaction.response.send_message(
                "Invalid rank. Use a rank such as HT1, MT2, LT3, etc.",
                ephemeral=True
            )

        ticket = self.bot.db.ticket(
            interaction.channel.id
        )

        if not ticket:

            return await interaction.response.send_message(
                "This ticket no longer exists.",
                ephemeral=True
            )

        if ticket["status"] != "testing":

            return await interaction.response.send_message(
                "This result has already been submitted.",
                ephemeral=True
            )

        if ticket["tester_id"] != interaction.user.id:

            return await interaction.response.send_message(
                "Only the tester who claimed this ticket can submit the result.",
                ephemeral=True
            )

        saved = self.bot.db.finalize_test(
            channel_id=interaction.channel.id,
            user_id=ticket["user_id"],
            minecraft_username=ticket["minecraft_username"],
            gamemode=ticket["gamemode"],
            tier=tier,
            tester_id=interaction.user.id,
            points=0,
            match_score=match_score,
            verdict=verdict,
            created_at=now(),
            closed_at=now()
        )

        if not saved:

            return await interaction.response.send_message(
                "This result was already submitted.",
                ephemeral=True
            )

        points = self.bot.db.points_for_tier(
            tier
        )

        self.bot.db.queue_remove(
            ticket["user_id"]
        )

        results = self.bot.get_channel(
            RESULTS_CHANNEL_ID
        )

        if results:

            embed = discord.Embed(
                title="MCPE Tier Result",
                description=(
                    f"**{ticket['minecraft_username']}** "
                    f"has completed their test."
                ),
                color=discord.Color.green()
            )

            embed.add_field(
                name="Rank",
                value=f"**{tier}**",
                inline=True
            )

            embed.add_field(
                name="Points",
                value=f"**{points}pts**",
                inline=True
            )

            embed.add_field(
                name="Match Score",
                value=f"**{match_score}**",
                inline=True
            )

            embed.add_field(
                name="Gamemode",
                value=(
                    f"{emoji(ticket['gamemode'])} "
                    f"{GAMEMODES[ticket['gamemode']][0]}"
                ),
                inline=False
            )

            embed.add_field(
                name="Tester",
                value=interaction.user.mention,
                inline=True
            )

            embed.add_field(
                name="Player",
                value=ticket["minecraft_username"],
                inline=True
            )

            embed.add_field(
                name="Verdict",
                value=(
                    verdict
                    if verdict
                    else "No verdict provided."
                ),
                inline=False
            )

            add_server_logo(
                embed
            )

            await results.send(
                embed=embed
            )

        member = interaction.guild.get_member(
            ticket["user_id"]
        )

        if member:

            await assign_tier_role(
                member,
                tier
            )

            try:

                await member.send(
                    "Your MCPE tier test is complete!\n\n"
                    f"Gamemode: **{GAMEMODES[ticket['gamemode']][0]}**\n"
                    f"Rank: **{tier}**\n"
                    f"Score: **{match_score}**\n"
                    f"Points: **{points}pts**\n"
                    f"Verdict: {verdict or 'No verdict provided.'}"
                )

            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            f"Result submitted successfully: **{tier}** • **{points}pts**.\n"
            "This ticket will close shortly."
        )

        await self.bot.refresh_queue_message()
        await self.bot.refresh_leaderboard()

        await self.bot.log(
            f"Result: "
            f"{ticket['minecraft_username']} | "
            f"{GAMEMODES[ticket['gamemode']][0]} | "
            f"{tier} | "
            f"{points}pts | "
            f"{match_score} | "
            f"tester {interaction.user} "
            f"({interaction.user.id})"
        )

        await asyncio.sleep(
            TICKET_CLOSE_DELAY
        )

        try:

            await interaction.channel.delete(
                reason="Test completed"
            )

        except discord.HTTPException:
            pass


# ======================================================
# QUEUE VIEW
# ======================================================

class QueueView(discord.ui.View):

    def __init__(self, bot):

        super().__init__(
            timeout=None
        )

        self.bot = bot

    @discord.ui.button(
        label="Leave Queue",
        style=discord.ButtonStyle.danger,
        custom_id="tierbot:leave"
    )
    async def leave(
        self,
        interaction,
        button
    ):

        ticket = await self.bot.get_real_active_ticket(
            interaction.user.id
        )

        if (
            ticket
            and ticket["status"] == "testing"
        ):

            return await interaction.response.send_message(
                "Your test has already been claimed by a tester. "
                "You cannot leave the queue now.",
                ephemeral=True
            )

        queued = self.bot.db.queue_for_user(
            interaction.user.id
        )

        if not queued:

            return await interaction.response.send_message(
                "You are not in a queue.",
                ephemeral=True
            )

        self.bot.db.queue_remove(
            interaction.user.id
        )

        if (
            ticket
            and ticket["status"] == "waiting"
        ):

            ticket_channel = None

            try:

                ticket_channel = await interaction.guild.fetch_channel(
                    ticket["channel_id"]
                )

            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException
            ):

                ticket_channel = None

            self.bot.db.close_ticket(
                ticket["channel_id"],
                now(),
                "player_left_queue"
            )

            if ticket_channel:

                try:

                    await ticket_channel.delete(
                        reason="Player left MCPE queue"
                    )

                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            "You left the queue.",
            ephemeral=True
        )

        await self.bot.refresh_queue_message()


# ======================================================
# LEADERBOARD VIEW
# ======================================================

class LeaderboardView(discord.ui.View):

    def __init__(self, bot):

        super().__init__(
            timeout=None
        )

        self.bot = bot

        options = [
            discord.SelectOption(
                label="Global Leaderboard",
                value="global",
                emoji="🏆",
                description="Combined points from every gamemode"
            )
        ]

        for key, data in GAMEMODES.items():

            options.append(
                discord.SelectOption(
                    label=data[0],
                    value=key,
                    emoji=discord.PartialEmoji(
                        name=data[1],
                        id=data[2]
                    )
                )
            )

        self.select = discord.ui.Select(
            placeholder="Select Leaderboard",
            options=options,
            custom_id="tierbot:leaderboard_gamemode"
        )

        self.select.callback = self.selected

        self.add_item(
            self.select
        )

    async def selected(
        self,
        interaction
    ):

        selection = self.select.values[0]

        if selection == "global":

            embed = self.bot.global_leaderboard_embed()

        else:

            embed = self.bot.leaderboard_embed(
                selection
            )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


# ======================================================
# TIER ROLES
# ======================================================

async def assign_tier_role(
    member,
    tier
):

    roles = {
        role.name: role
        for role in member.guild.roles
        if role.name in TIERS
    }

    for name, role in roles.items():

        if (
            name != tier
            and role in member.roles
        ):

            try:

                await member.remove_roles(
                    role,
                    reason="MCPE tier replaced"
                )

            except discord.HTTPException:
                pass

    role = roles.get(
        tier
    )

    if (
        role
        and role not in member.roles
    ):

        try:

            await member.add_roles(
                role,
                reason="MCPE tier result"
            )

        except discord.HTTPException:
            pass


# ======================================================
# BOT INSTANCE
# ======================================================

bot = TierBot()


# ======================================================
# SETUP
# ======================================================

@bot.tree.command(
    name="setup",
    description="Create the MCPE tier bot panels"
)
async def setup(
    interaction: discord.Interaction
):

    if not bot.has_staff(
        interaction.user
    ):

        return await interaction.response.send_message(
            "Staff only.",
            ephemeral=True
        )

    await interaction.response.defer(
        ephemeral=True
    )

    await bot.refresh_apply_message()
    await bot.refresh_queue_message()
    await bot.refresh_leaderboard()

    await interaction.followup.send(
        "Panels created/refreshed.",
        ephemeral=True
    )


# ======================================================
# STATS
# ======================================================

@bot.tree.command(
    name="stats",
    description="Show a player's MCPE profile"
)
@app_commands.describe(
    username="Discord member whose MCPE profile you want to view"
)
async def stats(
    interaction: discord.Interaction,
    username: discord.Member
):

    player = bot.db.stats_player(
        username.id
    )

    if not player:

        return await interaction.response.send_message(
            "This player has no MCPE tier profile yet.",
            ephemeral=True
        )

    gamemode_results = bot.db.stats_gamemodes(
        username.id
    )

    total_points = int(
        player["total_points"] or 0
    )

    rank = bot.db.global_rank(
        username.id
    )

    if rank is None:
        rank_text = "Unranked"
    else:
        rank_text = f"#{rank}"

    embed = discord.Embed(
        title=f"{player['minecraft_username']}'s Profile",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="IGN",
        value=player["minecraft_username"],
        inline=True
    )

    embed.add_field(
        name="Region",
        value=player["region"] or "No Region",
        inline=True
    )

    embed.add_field(
        name="Total Points",
        value=f"{total_points}",
        inline=True
    )

    embed.add_field(
        name="Global Rank",
        value=rank_text,
        inline=True
    )

    # ==================================================
    # GAMEMODES
    # ==================================================

    gamemode_lines = []

    main_gamemode = None
    main_points = -1

    for gm, data in GAMEMODES.items():

        result = gamemode_results.get(
            gm
        )

        if result:

            tier = result["tier"]
            points = int(
                result["points"] or 0
            )

            line = (
                f"{emoji(gm)} "
                f"**{data[0]}** - "
                f"[{tier}] ({points}pts)"
            )

            if points > main_points:

                main_points = points
                main_gamemode = gm

        else:

            line = (
                f"{emoji(gm)} "
                f"**{data[0]}** - "
                f"Unranked (0pts)"
            )

        gamemode_lines.append(
            line
        )

    embed.add_field(
        name="Gamemodes",
        value="\n".join(
            gamemode_lines
        ),
        inline=False
    )

    if main_gamemode:

        main_name = GAMEMODES[
            main_gamemode
        ][0]

    else:

        main_name = "None"

    embed.add_field(
        name="Main Gamemode",
        value=main_name,
        inline=False
    )

    # ==================================================
    # AVATAR
    # ==================================================

    avatar = username.display_avatar.url

    embed.set_image(
        url=avatar
    )

    embed.set_footer(
        text=(
            f"{rank_text} on Global Leaderboard"
        )
    )

    add_server_logo(
        embed
    )

    await interaction.response.send_message(
        embed=embed
    )


# ======================================================
# FORCE REMOVE
# ======================================================

@bot.tree.command(
    name="force-remove",
    description="Remove a player from the active queue"
)
@app_commands.describe(
    user="Player to remove"
)
async def force_remove(
    interaction: discord.Interaction,
    user: discord.Member
):

    if not bot.has_staff(
        interaction.user
    ):

        return await interaction.response.send_message(
            "Staff only.",
            ephemeral=True
        )

    ticket = await bot.get_real_active_ticket(
        user.id
    )

    bot.db.queue_remove(
        user.id
    )

    if ticket:

        bot.db.close_ticket(
            ticket["channel_id"],
            now(),
            "staff_force_removed"
        )

        channel = None

        try:

            channel = await interaction.guild.fetch_channel(
                ticket["channel_id"]
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):

            channel = None

        if channel:

            try:

                await channel.delete(
                    reason="Player force-removed"
                )

            except discord.HTTPException:
                pass

    await bot.refresh_queue_message()

    await interaction.response.send_message(
        f"Removed {user.mention} from the queue.",
        ephemeral=True
    )


# ======================================================
# PLAYER RESULTS
# ======================================================

@bot.tree.command(
    name="player-results",
    description="Show a player's test history"
)
@app_commands.describe(
    user="Player"
)
async def player_results(
    interaction: discord.Interaction,
    user: discord.Member
):

    rows = bot.db.results_for_user(
        user.id
    )

    if not rows:

        return await interaction.response.send_message(
            "No results found.",
            ephemeral=True
        )

    embed = discord.Embed(
        title=(
            f"{user.display_name}'s "
            "MCPE Results"
        ),
        color=discord.Color.blurple()
    )

    lines = []

    for row in rows[:20]:

        try:

            timestamp = int(
                datetime.fromisoformat(
                    row["created_at"]
                ).timestamp()
            )

            time_text = f"<t:{timestamp}:R>"

        except Exception:

            time_text = row["created_at"]

        lines.append(
            f"{emoji(row['gamemode'])} "
            f"**{GAMEMODES[row['gamemode']][0]}**\n"
            f"Rank: **{row['tier']}** | "
            f"Score: **{row['match_score']}** | "
            f"Points: **{row['points']}pts**\n"
            f"{row['verdict'] or 'No verdict provided.'}\n"
            f"{time_text}"
        )

    embed.description = "\n\n".join(
        lines
    )

    add_server_logo(
        embed
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ======================================================
# CLOSE TICKET
# ======================================================

@bot.tree.command(
    name="close-ticket",
    description="Close the current test ticket"
)
async def close_ticket(
    interaction: discord.Interaction
):

    if not bot.has_staff(
        interaction.user
    ):

        return await interaction.response.send_message(
            "Staff only.",
            ephemeral=True
        )

    ticket = bot.db.ticket(
        interaction.channel.id
    )

    if not ticket:

        return await interaction.response.send_message(
            "This is not a tier test ticket.",
            ephemeral=True
        )

    bot.db.queue_remove(
        ticket["user_id"]
    )

    bot.db.close_ticket(
        interaction.channel.id,
        now(),
        "staff_closed"
    )

    await bot.refresh_queue_message()

    await interaction.response.send_message(
        "Ticket closed."
    )

    await asyncio.sleep(
        3
    )

    try:

        await interaction.channel.delete(
            reason="Staff closed ticket"
        )

    except discord.HTTPException:
        pass


# ======================================================
# START
# ======================================================

if __name__ == "__main__":

    bot.run(
        TOKEN
    )
```
