import discord
from discord import app_commands
from discord.ext import commands

from config import (
    STAFF_ROLE_ID,
    AUDIT_CHANNEL_ID,
)


class Moderation(commands.Cog):
    """Standalone moderation and utility system."""

    def __init__(self, bot):
        self.bot = bot

        # In-memory warnings.
        # Kept separate from the tier-testing database.
        self.warnings = {}

    # ==================================================
    # HELPERS
    # ==================================================

    def is_staff(self, member: discord.Member) -> bool:
        """Check whether a member can use staff commands."""

        if not isinstance(member, discord.Member):
            return False

        return (
            member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
            or any(
                role.id == STAFF_ROLE_ID
                for role in member.roles
            )
        )

    def can_moderate(
        self,
        moderator: discord.Member,
        target: discord.Member
    ) -> tuple[bool, str]:

        if moderator.id == target.id:
            return False, "You cannot moderate yourself."

        if target.id == moderator.guild.owner_id:
            return False, "You cannot moderate the server owner."

        if target.id == self.bot.user.id:
            return False, "I cannot moderate myself."

        if (
            moderator != moderator.guild.owner
            and target.top_role >= moderator.top_role
        ):
            return (
                False,
                "You cannot moderate a member with an equal or higher role."
            )

        bot_member = moderator.guild.me

        if bot_member is None:
            return False, "I could not determine my server role."

        if target.top_role >= bot_member.top_role:
            return (
                False,
                "My highest role must be above the target's highest role."
            )

        return True, ""

    async def audit(
        self,
        action: str,
        moderator: discord.Member,
        target_text: str,
        reason: str,
        extra: str | None = None
    ):

        channel = self.bot.get_channel(
            AUDIT_CHANNEL_ID
        )

        if channel is None:
            return

        embed = discord.Embed(
            title=f"Moderation • {action}",
            color=discord.Color.red()
        )

        embed.add_field(
            name="Moderator",
            value=(
                f"{moderator.mention}\n"
                f"`{moderator.id}`"
            ),
            inline=True
        )

        embed.add_field(
            name="Target",
            value=target_text,
            inline=True
        )

        embed.add_field(
            name="Reason",
            value=reason or "No reason provided.",
            inline=False
        )

        if extra:
            embed.add_field(
                name="Details",
                value=extra,
                inline=False
            )

        try:
            await channel.send(
                embed=embed
            )
        except discord.HTTPException:
            pass

    # ==================================================
    # KICK
    # ==================================================

    @app_commands.command(
        name="kick",
        description="Kick a member from the server"
    )
    @app_commands.describe(
        user="Member to kick",
        reason="Reason for the kick"
    )
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "No reason provided."
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        allowed, error = self.can_moderate(
            moderator,
            user
        )

        if not allowed:
            return await interaction.response.send_message(
                error,
                ephemeral=True
            )

        try:
            await user.kick(
                reason=f"{reason} | Moderator: {moderator}"
            )

        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to kick that member.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord rejected the kick.",
                ephemeral=True
            )

        await self.audit(
            "KICK",
            moderator,
            f"{user.mention}\n`{user}`",
            reason
        )

        await interaction.response.send_message(
            f"Successfully kicked **{user}**.",
            ephemeral=True
        )

    # ==================================================
    # BAN
    # ==================================================

    @app_commands.command(
        name="ban",
        description="Ban a member from the server"
    )
    @app_commands.describe(
        user="Member to ban",
        reason="Reason for the ban"
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "No reason provided."
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        allowed, error = self.can_moderate(
            moderator,
            user
        )

        if not allowed:
            return await interaction.response.send_message(
                error,
                ephemeral=True
            )

        try:
            await user.ban(
                reason=f"{reason} | Moderator: {moderator}"
            )

        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to ban that member.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord rejected the ban.",
                ephemeral=True
            )

        await self.audit(
            "BAN",
            moderator,
            f"{user.mention}\n`{user}`",
            reason
        )

        await interaction.response.send_message(
            f"Successfully banned **{user}**.",
            ephemeral=True
        )

    # ==================================================
    # UNBAN
    # ==================================================

    @app_commands.command(
        name="unban",
        description="Unban a user by their Discord ID"
    )
    @app_commands.describe(
        user_id="Discord ID of the banned user",
        reason="Reason for the unban"
    )
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: str = "No reason provided."
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        try:
            user_id_int = int(user_id)

        except ValueError:
            return await interaction.response.send_message(
                "That is not a valid Discord user ID.",
                ephemeral=True
            )

        try:
            user = await self.bot.fetch_user(
                user_id_int
            )

        except discord.NotFound:
            return await interaction.response.send_message(
                "That Discord user could not be found.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.response.send_message(
                "I could not fetch that user.",
                ephemeral=True
            )

        try:
            await interaction.guild.unban(
                user,
                reason=f"{reason} | Moderator: {moderator}"
            )

        except discord.NotFound:
            return await interaction.response.send_message(
                "That user is not currently banned.",
                ephemeral=True
            )

        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to unban users.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord rejected the unban.",
                ephemeral=True
            )

        await self.audit(
            "UNBAN",
            moderator,
            f"`{user}`\n`{user.id}`",
            reason
        )

        await interaction.response.send_message(
            f"Successfully unbanned **{user}**.",
            ephemeral=True
        )

    # ==================================================
    # MUTE
    # ==================================================

    @app_commands.command(
        name="mute",
        description="Timeout a member"
    )
    @app_commands.describe(
        user="Member to timeout",
        duration="Duration in minutes",
        reason="Reason for the timeout"
    )
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: app_commands.Range[int, 1, 40320],
        reason: str = "No reason provided."
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        allowed, error = self.can_moderate(
            moderator,
            user
        )

        if not allowed:
            return await interaction.response.send_message(
                error,
                ephemeral=True
            )

        if user.is_timed_out():
            return await interaction.response.send_message(
                "That member is already muted.",
                ephemeral=True
            )

        try:
            await user.timeout(
                discord.utils.utcnow()
                + discord.timedelta(minutes=duration),
                reason=f"{reason} | Moderator: {moderator}"
            )

        except AttributeError:
            try:
                from datetime import timedelta

                await user.timeout(
                    timedelta(minutes=duration),
                    reason=f"{reason} | Moderator: {moderator}"
                )

            except discord.Forbidden:
                return await interaction.response.send_message(
                    "I don't have permission to timeout that member.",
                    ephemeral=True
                )

            except discord.HTTPException:
                return await interaction.response.send_message(
                    "Discord rejected the timeout.",
                    ephemeral=True
                )

        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to timeout that member.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord rejected the timeout.",
                ephemeral=True
            )

        await self.audit(
            "MUTE",
            moderator,
            f"{user.mention}\n`{user}`",
            reason,
            f"Duration: `{duration}` minutes"
        )

        await interaction.response.send_message(
            f"Successfully muted **{user}** for **{duration} minutes**.",
            ephemeral=True
        )

    # ==================================================
    # UNMUTE
    # ==================================================

    @app_commands.command(
        name="unmute",
        description="Remove a member's timeout"
    )
    @app_commands.describe(
        user="Member to unmute",
        reason="Reason for removing the timeout"
    )
    async def unmute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "No reason provided."
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        allowed, error = self.can_moderate(
            moderator,
            user
        )

        if not allowed:
            return await interaction.response.send_message(
                error,
                ephemeral=True
            )

        if not user.is_timed_out():
            return await interaction.response.send_message(
                "That member is not currently muted.",
                ephemeral=True
            )

        try:
            await user.timeout(
                None,
                reason=f"{reason} | Moderator: {moderator}"
            )

        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to remove that timeout.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord rejected the unmute.",
                ephemeral=True
            )

        await self.audit(
            "UNMUTE",
            moderator,
            f"{user.mention}\n`{user}`",
            reason
        )

        await interaction.response.send_message(
            f"Successfully unmuted **{user}**.",
            ephemeral=True
        )

    # ==================================================
    # WARN
    # ==================================================

    @app_commands.command(
        name="warn",
        description="Warn a member"
    )
    @app_commands.describe(
        user="Member to warn",
        reason="Reason for the warning"
    )
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        allowed, error = self.can_moderate(
            moderator,
            user
        )

        if not allowed:
            return await interaction.response.send_message(
                error,
                ephemeral=True
            )

        warning = {
            "moderator_id": moderator.id,
            "reason": reason,
            "timestamp": discord.utils.utcnow()
        }

        self.warnings.setdefault(
            user.id,
            []
        ).append(warning)

        count = len(
            self.warnings[user.id]
        )

        await self.audit(
            "WARN",
            moderator,
            f"{user.mention}\n`{user}`",
            reason,
            f"Warning count: `{count}`"
        )

        await interaction.response.send_message(
            f"Warning issued to **{user}**.\n"
            f"Total warnings this session: **{count}**.",
            ephemeral=True
        )

    # ==================================================
    # WARNINGS
    # ==================================================

    @app_commands.command(
        name="warnings",
        description="View a member's warnings"
    )
    @app_commands.describe(
        user="Member whose warnings you want to view"
    )
    async def warnings(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):

        if not self.is_staff(interaction.user):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        warnings = self.warnings.get(
            user.id,
            []
        )

        if not warnings:
            return await interaction.response.send_message(
                f"**{user}** has no warnings recorded.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"Warnings • {user}",
            color=discord.Color.orange()
        )

        lines = []

        for index, warning in enumerate(
            warnings[-10:],
            1
        ):

            moderator = interaction.guild.get_member(
                warning["moderator_id"]
            )

            moderator_text = (
                moderator.mention
                if moderator
                else f"`{warning['moderator_id']}`"
            )

            timestamp = int(
                warning["timestamp"].timestamp()
            )

            lines.append(
                f"**#{index}** • {moderator_text}\n"
                f"{warning['reason']}\n"
                f"<t:{timestamp}:R>"
            )

        embed.description = "\n\n".join(
            lines
        )

        embed.set_footer(
            text=f"Total warnings: {len(warnings)}"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    # ==================================================
    # PURGE
    # ==================================================

    @app_commands.command(
        name="purge",
        description="Delete recent messages"
    )
    @app_commands.describe(
        amount="Number of messages to delete"
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100]
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return await interaction.response.send_message(
                "This command can only be used in a text channel.",
                ephemeral=True
            )

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            deleted = await channel.purge(
                limit=amount
            )

        except discord.Forbidden:
            return await interaction.followup.send(
                "I don't have permission to delete messages here.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.followup.send(
                "Discord rejected the message deletion.",
                ephemeral=True
            )

        await self.audit(
            "PURGE",
            moderator,
            f"#{channel.name}",
            "Messages purged",
            f"Deleted: `{len(deleted)}` messages"
        )

        await interaction.followup.send(
            f"Successfully purged **{len(deleted)} messages**.",
            ephemeral=True
        )

    # ==================================================
    # SLOWMODE
    # ==================================================

    @app_commands.command(
        name="slowmode",
        description="Set channel slowmode"
    )
    @app_commands.describe(
        seconds="Slowmode delay in seconds, 0 to disable"
    )
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600]
    ):

        moderator = interaction.user

        if not self.is_staff(moderator):
            return await interaction.response.send_message(
                "You do not have permission to use moderation commands.",
                ephemeral=True
            )

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return await interaction.response.send_message(
                "This command can only be used in a text channel.",
                ephemeral=True
            )

        try:
            await channel.edit(
                slowmode_delay=seconds,
                reason=f"Slowmode changed by {moderator}"
            )

        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to change slowmode.",
                ephemeral=True
            )

        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord rejected the slowmode change.",
                ephemeral=True
            )

        status = (
            "disabled"
            if seconds == 0
            else f"set to **{seconds} seconds**"
        )

        await self.audit(
            "SLOWMODE",
            moderator,
            f"#{channel.name}",
            "Channel slowmode changed",
            f"Slowmode {status}"
        )

        await interaction.response.send_message(
            f"Slowmode {status}.",
            ephemeral=True
        )

    # ==================================================
    # POLL
    # ==================================================

    @app_commands.command(
        name="poll",
        description="Create a poll"
    )
    @app_commands.describe(
        question="The poll question",
        option1="First option",
        option2="Second option",
        option3="Third option",
        option4="Fourth option",
        option5="Fifth option"
    )
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str | None = None,
        option4: str | None = None,
        option5: str | None = None
    ):

        options = [
            option1,
            option2,
        ]

        if option3:
            options.append(option3)

        if option4:
            options.append(option4)

        if option5:
            options.append(option5)

        numbers = [
            "1️⃣",
            "2️⃣",
            "3️⃣",
            "4️⃣",
            "5️⃣"
        ]

        lines = []

        for index, option in enumerate(options):
            lines.append(
                f"{numbers[index]} **{option}**"
            )

        embed = discord.Embed(
            title="Poll",
            description=(
                f"**{question}**\n\n"
                + "\n".join(lines)
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text=f"Poll created by {interaction.user.display_name}"
        )

        await interaction.response.send_message(
            embed=embed
        )

        message = await interaction.original_response()

        for index in range(len(options)):
            try:
                await message.add_reaction(
                    numbers[index]
                )
            except discord.HTTPException:
                pass

    # ==================================================
    # ABOUT
    # ==================================================

    @app_commands.command(
        name="about",
        description="Show information about the bot"
    )
    async def about(
        self,
        interaction: discord.Interaction
    ):

        embed = discord.Embed(
            title="MCPE Tier Testing Bot",
            description=(
                "A dedicated Minecraft Bedrock PvP tier-testing "
                "and Discord management bot."
            ),
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="⚔️ Tier Testing",
            value=(
                "MCPE-only tier testing with queues, "
                "private test tickets, tester claims, "
                "results and leaderboards."
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Moderation",
            value=(
                "Kick, ban, timeout, warnings, "
                "purging and channel management."
            ),
            inline=False
        )

        embed.add_field(
            name="👑 Creator",
            value=(
                "**Lord Whiteify (likewhiteforever on discord)**\n\n"
                "The person responsible for building the "
                "system, designing the workflow and apparently "
                "deciding that a Minecraft PvP bot needed its "
                "own moderation department.\n\n"
                "Without the creator, this bot would be nothing "
                "more than a collection of Python files sitting "
                "quietly on a Mac, contemplating its purpose."
            ),
            inline=False
        )

        embed.add_field(
            name="Technology",
            value=(
                "Python • discord.py • SQLite"
            ),
            inline=True
        )

        embed.add_field(
            name="Platform",
            value="Minecraft Bedrock Edition",
            inline=True
        )

        embed.set_footer(
            text="Built for MCPE PvP tier testing."
        )

        await interaction.response.send_message(
            embed=embed
        )


async def setup(bot):
    await bot.add_cog(
        Moderation(bot)
    )