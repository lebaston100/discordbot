import logging
import pathlib
from re import S
from discord.ext import commands, tasks
from utils.commandReplyProcessor import commandProc
from utils.jsonFile import fileHelper

logger = logging.getLogger("NinjaBot." + __name__)

class NinjaDynCmds(commands.Cog):
    def __init__(self, bot) -> None:
        logger.debug(f"Loading {self.__class__.__name__}")
        self.bot = bot
        self.isInternal = False
        self._fh = fileHelper(pathlib.Path(__file__).parent.resolve() / "../suggestions.json")
        self.commands = {}
        self.loadCommands.start()

    async def process_command(self, ctx) -> bool:
        return await commandProc(self, ctx)

    @commands.command(hidden=True, aliases=["addcom"])
    @commands.has_role("Moderator")
    async def add(self, ctx: commands.context, command: str, reply: str, *args) -> None:
        """Command to dynamically add a command to the bot. Should not be used (but works)."""
        args and await ctx.send("If you want to use spaces, please put the text in quotes")
        await ctx.send("This is only for temp use. Please consider creating a PR/Commit to the bot repo.")

        command = command.lower()

        if command in self.commands:
            await ctx.send("Command already exists as a temp command. please use !delete <command> or !delcom <command> first")
        else:
            self.commands[command] = reply
            await self._saveToFile()
            await self._loadFromFile()
            await ctx.send(f"Command '{command}' with reply '{reply}' has been added")

    @commands.command(hidden=True, aliases=["delcom"])
    @commands.has_role("Moderator")
    async def delete(self, ctx: commands.context, command: str) -> None:
        if command in self.commands:
            del self.commands[command]
            await self._saveToFile()
            await self._loadFromFile()
            await ctx.send(f"Command '{command}' was successfully deleted from my memory")
        else:
            NinjaGithub = self.bot.get_cog("NinjaGithub")
            if command in NinjaGithub.commands:
                await ctx.send(f"'{command}' is a github command and can only edited on github")
            else:
                await ctx.send(f"Command '{command}' is not a dynamic command")

    
    async def cog_command_error(self, ctx, error):
        """Post error that happen inside this cog to channel"""
        await ctx.send(error)

    async def _loadFromFile(self) -> None:
        logger.debug("Loading dyn cmds from file")
        self.commands = await self._fh.read()

    async def _saveToFile(self) -> None:
        logger.debug("Saving dyn cmds to file")
        await self._fh.write(self.commands)

    # run only once
    @tasks.loop(count=1)
    async def loadCommands(self) -> None:
        await self._loadFromFile()

    async def getCommands(self) -> list:
        """Return the available commands as a list"""
        return list(self.commands.keys())

    async def cog_unload(self) -> None:
        logger.debug(f"Shutting down {self.__class__.__name__}")
        self.loadCommands.cancel()

async def setup(bot) -> None:
    await bot.add_cog(NinjaDynCmds(bot))