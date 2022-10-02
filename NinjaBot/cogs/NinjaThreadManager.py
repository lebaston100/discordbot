import logging
import re
import discord
import embedBuilder
from discord.ext import commands
from discord import app_commands

logger = logging.getLogger("NinjaBot." + __name__)

# The popup modal to rename a thread
class ThreadTitleChangeModal(discord.ui.Modal, title="Rename Thread"):
    newTitle = discord.ui.TextInput(label="New Title", required=True)
    
    def __init__(self, NinjaThreadManager, default="") -> None:
        super().__init__(timeout=None)
        self.ntm = NinjaThreadManager
        self.newTitle.default = default

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.ntm._title(interaction, self.newTitle)

# The buttons shown below the welcome message
class ThreadManagementButtons(discord.ui.View):
    def __init__(self, NinjaThreadManager) -> None:
        super().__init__(timeout=None)
        self.ntm = NinjaThreadManager

    @discord.ui.button(label="Close Thread", style=discord.ButtonStyle.success)
    async def closeButton(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.ntm._close(interaction)
    
    @discord.ui.button(label="Change title", style=discord.ButtonStyle.primary)
    async def titleButton(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ThreadTitleChangeModal(self.ntm, interaction.channel.name))

    # Check if user is Moderator before calling callbacks
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if hasattr(interaction, "message") and hasattr(interaction.user, "roles") and discord.utils.get(interaction.user.roles, name="Moderator"):
            return True
        await interaction.response.send_message("You don't have permission to use this button", ephemeral=True)
        return False

class NinjaThreadManager(commands.Cog):
    def __init__(self, bot) -> None:
        logger.debug(f"Loading {self.__class__.__name__}")
        self.bot = bot
        self.isInternal = True
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        ctx = await self.bot.get_context(message)
        # Check if config options are there and are the expected values
        if (not ctx.author == self.bot.user and not ctx.author.bot \
            and not isinstance(ctx.message.channel, discord.DMChannel) \
            and self.bot.config.has("autoThreadEnabledChannels") \
            and self.bot.config.has("autoThreadWelcomeText") \
            and str(ctx.channel.id) in self.bot.config.get("autoThreadEnabledChannels")):
            # we might want more checks here?
            # Create thread
            createdThread = await ctx.message.create_thread(name=self._getThreadTitle(ctx.message.content), auto_archive_duration=1440, reason=__name__)
            # create embed from welcome message
            welcomeText = self.bot.config.get("autoThreadWelcomeText")
            welcomeText = welcomeText.replace("<USERMENTION>", ctx.message.author.mention)
            embed = embedBuilder.ninjaEmbed(description=welcomeText)
            # Post welcome message to thread
            await createdThread.send(embed=embed, view=ThreadManagementButtons(self))

    @app_commands.command(description="Change the thread title")
    @app_commands.describe(new_title="The new thread title")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def title(self, interaction: discord.Interaction, new_title: str = None) -> None:
        if new_title:
            await self._title(interaction, new_title)
        else:
            await interaction.response.send_modal(ThreadTitleChangeModal(self, interaction.channel.name))
    
    async def _title(self, interaction, new_title) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("You can't change the title here since it's not a thread", ephemeral=True)
            return
        await interaction.response.send_message(f"Changing title to '{new_title}'", ephemeral=True)
        await interaction.channel.edit(name=new_title)
    
    @app_commands.command(description="Closes the thread")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def close(self, interaction: discord.Interaction) -> None:
        await self._close(interaction)
    
    async def _close(self, interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("You can't close this since it's not a thread", ephemeral=True)
            return
        await interaction.response.send_message(f"Archiving thread", ephemeral=True)
        if not interaction.channel.archived: await interaction.channel.edit(archived=True, reason="NinjaBot")

    @commands.command(hidden=True)
    @commands.has_role("Moderator")
    @commands.guild_only()
    async def login(self, ctx) -> None:
        """Login to automatic pings for support thread creations"""
        pass

    @commands.command(hidden=True)
    @commands.has_role("Moderator")
    @commands.guild_only()
    async def logout(self, ctx) -> None:
        """Logout from automatic pings for support thread creations"""
        pass

    async def cog_command_error(self, ctx, error) -> None:
        """Post error that happen inside this cog to channel"""
        await ctx.send(error)
    
    # get the first 14 words of a message or 40 chars
    def _getThreadTitle(self, message) -> None:
        match = re.match(r"^(?:\w+\s){1,14}", message)
        if match:
            return match.group(0)
        return message[:40]

    async def getCommands(self) -> list:
        """Return the available commands as a list"""
        return []

    async def cog_unload(self) -> None:
        logger.debug(f"Shutting down {self.__class__.__name__}")

async def setup(bot) -> None:
    await bot.add_cog(NinjaThreadManager(bot))

"""
TODO:
- (OK) add configuration option for enabled channels
- (OK) add configuration option for welcome text
- (OK) add configuration option for logged in staff
- (optional) set slowmode for channels?
- (OK) if new message in channel create new thread
- (OK)respond with configurable text block + close button
- staff login/logout system
- ping users that are logged in on thread creation
- (OK) /close to close/archive the thread
- (OK) /title to change title
"""