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
    n = max(0, min(10, n))
    return "■" * n + "□" * (10 - n)


def add_server_logo(embed):
    """
    Adds the configured server logo to the top-right
    of the Discord embed as a thumbnail.
    """
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

    async def setup_hook(self):

        await self.load_extension("moderation")

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

    async def on_ready(self):

        print(
            f"Logged in as {self.user} "
            f"({self.user.id})"
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

        row = self.db.conn.execute(
            """
            SELECT value
            FROM settings
            WHERE key=?
            """,
            (key,)
        ).fetchone()

        if not row:
            return None

        try:

            return int(
                row["value"]
            )

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

        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO settings(
                key,
                value
            )
            VALUES(?, ?)
            """,
            (
                key,
                str(message_id)
            )
        )

        self.db.conn.commit()

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

        channel = None

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

        # Discord channel no longer exists.
        # Remove stale database state.
        self.db.close_ticket(
            ticket["channel_id"],
            now()
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

            except (
                discord.NotFound,
                discord.HTTPException
            ):

                message = None

        if not message:

            message = await channel.send(
                embed=self.apply_embed(),
                view=ApplyView(self)
            )

        else:

            await message.edit(
                content=None,
                embed=self.apply_embed(),
                view=ApplyView(self)
            )

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
                    f"**{count}/10**\n"
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

                except (
                    discord.NotFound,
                    discord.HTTPException
                ):

                    message = None

            if not message:

                message = await channel.send(
                    embed=self.queue_embed(),
                    view=QueueView(self)
                )

            else:

                await message.edit(
                    content=None,
                    embed=self.queue_embed(),
                    view=QueueView(self)
                )

            self.save_message_id(
                "queue_message_id",
                message.id
            )

    # ==================================================
    # LEADERBOARD EMBED
    # ==================================================

    def leaderboard_embed(
        self,
        selected_gm=None
    ):

        if selected_gm is None:

            selected_gm = next(
                iter(GAMEMODES)
            )

        rows = self.db.latest_results()

        # Keep only the best score for each player
        # in this gamemode.
        players = {}

        for row in rows:

            if row["gamemode"] != selected_gm:
                continue

            user_id = row["user_id"]

            if user_id not in players:

                players[user_id] = row
                continue

            old = players[user_id]

            if (
                row["points"] > old["points"]
                or (
                    row["points"] == old["points"]
                    and row["id"] > old["id"]
                )
            ):

                players[user_id] = row

        entries = list(
            players.values()
        )

        entries.sort(
            key=lambda row: (
                -row["points"],
                row["id"]
            )
        )

        embed = discord.Embed(
            title="MCPE Tier Leaderboard",
            color=discord.Color.gold()
        )

        embed.description = (
            f"{emoji(selected_gm)} "
            f"**{GAMEMODES[selected_gm][0]}**"
        )

        if not entries:

            embed.add_field(
                name="Rankings",
                value="No tested players yet.",
                inline=False
            )

        else:

            lines = []

            for index, row in enumerate(
                entries[:20],
                1
            ):

                lines.append(
                    f"`#{index}` "
                    f"`{row['minecraft_username']}` "
                    f"| **No Region** "
                    f"| **{row['points']}pts**"
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

    async def refresh_leaderboard(self):

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

            except (
                discord.NotFound,
                discord.HTTPException
            ):

                message = None

        if not message:

            message = await channel.send(
                embed=self.leaderboard_embed(),
                view=LeaderboardView(self)
            )

        else:

            await message.edit(
                content=None,
                embed=self.leaderboard_embed(),
                view=LeaderboardView(self)
            )

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

        queued = self.bot.db.conn.execute(
            """
            SELECT 1
            FROM queues
            WHERE user_id=?
            """,
            (interaction.user.id,)
        ).fetchone()

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

        gm = self.select.values[0]

        if self.bot.db.count(gm) >= 10:

            return await interaction.response.send_message(
                "That queue is full (10/10).",
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

        active = await self.bot.get_real_active_ticket(
            interaction.user.id
        )

        if active:

            return await interaction.response.send_message(
                "You already have an active test ticket.",
                ephemeral=True
            )

        ok, reason = self.bot.db.queue_join(
            interaction.user.id,
            self.gm,
            minecraft_username,
            preferred_server,
            now(),
            10
        )

        if not ok:

            if reason == "already_queued":

                return await interaction.response.send_message(
                    "You are already in a queue.",
                    ephemeral=True
                )

            if reason == "full":

                return await interaction.response.send_message(
                    "That queue is full (10/10).",
                    ephemeral=True
                )

            return await interaction.response.send_message(
                "Unable to join the queue.",
                ephemeral=True
            )

        guild = interaction.guild

        if guild is None:

            self.bot.db.queue_remove(
                interaction.user.id
            )

            return await interaction.response.send_message(
                "This request must be made inside the Discord server.",
                ephemeral=True
            )

        category = guild.get_channel(
            TICKET_CATEGORY_ID
        )

        if category is None:

            self.bot.db.queue_remove(
                interaction.user.id
            )

            return await interaction.response.send_message(
                "The ticket category could not be found.",
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

        try:

            channel = await guild.create_text_channel(
                f"test-{interaction.user.name}"[:95],
                category=category,
                overwrites=overwrites,
                reason="MCPE tier test ticket"
            )

            self.bot.db.create_ticket(
                channel.id,
                interaction.user.id,
                self.gm,
                minecraft_username,
                preferred_server,
                now()
            )

        except Exception:

            self.bot.db.queue_remove(
                interaction.user.id
            )

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

        # Send the result button instead of immediately
        # asking for a rank.
        embed = discord.Embed(
            title="Test In Progress",
            description=(
                "When the match is finished, click "
                "**Submit Test Result** to submit the "
                "player's final rank, match score, points "
                "and custom verdict."
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

        # Only the tester who claimed the ticket can submit it.
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

    points = discord.ui.TextInput(
        label="Points",
        placeholder="Example: 4000",
        max_length=10
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

        # ----------------------------------------------
        # Validate rank
        # ----------------------------------------------

        if tier not in TIERS:

            return await interaction.response.send_message(
                "Invalid rank. Use a rank such as HT1, MT2, LT3, etc.",
                ephemeral=True
            )

        # ----------------------------------------------
        # Validate points
        # ----------------------------------------------

        try:

            points = int(
                self.points.value.strip()
            )

        except ValueError:

            return await interaction.response.send_message(
                "Points must be a whole number.",
                ephemeral=True
            )

        if points < 0:

            return await interaction.response.send_message(
                "Points cannot be negative.",
                ephemeral=True
            )

        # ----------------------------------------------
        # Re-check ticket before finalizing
        # ----------------------------------------------

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

        # ----------------------------------------------
        # ATOMIC RESULT SUBMISSION
        # ----------------------------------------------

        saved = self.bot.db.finalize_test(
            channel_id=interaction.channel.id,
            user_id=ticket["user_id"],
            minecraft_username=ticket["minecraft_username"],
            gamemode=ticket["gamemode"],
            tier=tier,
            tester_id=interaction.user.id,
            points=points,
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

        # Queue is no longer active.
        self.bot.db.queue_remove(
            ticket["user_id"]
        )

        # ----------------------------------------------
        # RESULTS CHANNEL
        # ----------------------------------------------

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

        # ----------------------------------------------
        # TIER ROLE
        # ----------------------------------------------

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
                    f"Verdict: {verdict}"
                )

            except discord.HTTPException:
                pass

        # ----------------------------------------------
        # CURRENT TICKET
        # ----------------------------------------------

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

        queued = self.bot.db.conn.execute(
            """
            SELECT *
            FROM queues
            WHERE user_id=?
            """,
            (interaction.user.id,)
        ).fetchone()

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
                now()
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

        options = []

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
            placeholder="Select Gamemode",
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

        gm = self.select.values[0]

        await interaction.response.edit_message(
            embed=self.bot.leaderboard_embed(gm),
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
            now()
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
            f"{row['verdict']}\n"
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
        now()
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