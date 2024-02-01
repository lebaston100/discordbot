import logging
import embedBuilder
import re
import asyncio
import json
import aiohttp
import discord
import time
from discord import app_commands
from discord.ext import commands
from typing import Union

logger = logging.getLogger("NinjaBot." + __name__)

class NinjaDocs(commands.Cog):
    def __init__(self, bot) -> None:
        logger.debug(f"Loading {self.__class__.__name__}")
        self.bot = bot
        self.isInternal = False
        self.http = aiohttp.ClientSession()
        self.ninjaDocsBaseUrl = "https://docs.vdo.ninja/"
        self.gbBaseUrl = "https://api.gitbook.com/v1/"
        self.gbHeaders = {
                "Authorization": f"Bearer {self.bot.config.get('gitbookApiKey')}"
            }
        self.urlCache: dict[str, tuple[int, str]] = {}

    def _checkIfInATEC(interaction: discord.Interaction) -> bool:
        return str(interaction.channel_id) not in interaction.client.config.get("autoThreadEnabledChannels")

    # app command for manually asking questions to gitbook lens
    @app_commands.command()
    @app_commands.describe(question="The question you want to ask")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.check(_checkIfInATEC)
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        """Ask ninjabot a question"""
        await interaction.response.defer()
        la = await self.getLensAnswer(question)
        if la:
            embed = embedBuilder.ninjaEmbed(description=self.createEmbedTextFromLensResult(la))
            await interaction.followup.send(embed=embed)
            return
        await interaction.followup.send("Could not generate an answer ●︿●\nTry making your question more specific.")

    # app command for a normal docs search
    @app_commands.command()
    @app_commands.describe(query="The search query")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.check(_checkIfInATEC)
    async def searchdocs(self, interaction: discord.Interaction, query: str) -> None:
        """Search the documentation"""
        await interaction.response.defer()
        sr = await self.searchRequest(query)
        if sr:
            embed = embedBuilder.ninjaEmbed(description=self.createEmbedTextFromSearchResult(sr))
            await interaction.followup.send(embed=embed)
            return
        await interaction.followup.send("Could not find a result to your query, try /ask ●︿●")

    # formats the lens result into a discord embed
    def createEmbedTextFromLensResult(self, result: dict) -> str:
        t = f"{result['text'][:3800]}\n\nReferences:\n"
        for url in result["urls"]:
            t += f"{url}\n"
        t += "\nThe above response was generated by a Large Language Model, so take it with a grain of salt!"
        return t

    # formats a docs search result into a discord embed
    def createEmbedTextFromSearchResult(self, results: dict) -> str:
        t = "Documentation search results:\n"
        for result in results["items"][:5]:
            t += f"{result['title']}: {self.ninjaDocsBaseUrl}{result['path']}\n"
        return t

    # request answer from lens and process it
    async def getLensAnswer(self, message: str=None) -> Union[dict, None]:
        # don't proceed if we don't have a message
        if not message: return None

        # remove common phrases not needed for lens
        regex = r"((hello)|(hey)|(hi)|(everyone)|(thanks))\b,?!?\s?"
        message = re.sub(regex, "", message, 0, re.IGNORECASE)

        # questions need to be at least 15 characters long
        if not len(message) > 15: return None
        logger.debug(f"Question: {message}")

        # query lens
        answer = {}
        answer["urls"] = []
        lensData = await self.lensRequest(message)
        if lensData:
            # logger.debug(json.dumps(lensData["text"], indent=2))
            answer["text"] = lensData["text"] # get text
            if len(lensData["pages"]):
                # resolve top 3 pages to urls
                coros = [self.getGbUrlFromPage(page) for page in lensData["pages"][:3]]
                answer["urls"] = await asyncio.gather(*coros)
            return answer
        return None

    # ask lens the provided question
    async def lensRequest(self, query: str) -> Union[dict, None]:
        try:
            response = await self.doGbPostApiRequest(f"spaces/{self.bot.config.get('gitbookSpaceId')}/search/ask", {"query": query})
            if response and "answer" in response: return response["answer"]
        except Exception as E:
            logger.exception(E)
            return None
    
    # normal docs search
    async def searchRequest(self, query: str) -> Union[dict, None]:
        try:
            response = await self.doGbGetApiRequest(f"spaces/{self.bot.config.get('gitbookSpaceId')}/search", {"query": query})
            if response and "items" in response: return response
        except Exception as E:
            logger.exception(E)
            return None

    # extract the anchor text from the section id
    def resolveSectionIdToAnchor(self, page: dict, sectionId: str)  -> str:
        if "initial" in sectionId:
            return ""
        sections = page["document"]["nodes"]
        node = [sect for sect in sections if sect.get("key") == sectionId]
        if node:
            return "#" + node[0]["meta"]["id"]
        return ""

    # resolve page object to url, using cached values if possible
    async def getGbUrlFromPage(self, page: dict) -> Union[str, None]:
        pageId = page["page"]
        pageSelection = page["sections"][0] if len(page["sections"]) == 1 else ""
        pageKey = f"{pageId}|{pageSelection}"
        logger.debug(pageKey)
        logger.debug(self.urlCache)

        # if page is in cache
        if pageKey in self.urlCache:
            # and cache is no older then 7 days
            if time.time() - self.urlCache[pageKey][0] > 7*86400:
                # remove from cache
                logger.debug(f"removed {str(self.urlCache[pageKey])} from cache because of age")
                self.urlCache.pop(pageKey)
            else:
                logger.debug(f"returning from cache {pageKey} -> {str(self.urlCache[pageKey])}")
                return self.urlCache[pageKey][1]

        # it's not in cache, run request
        pageResponse = await self.resolveGbPageIdToUrl(pageId)
        if pageResponse:
            pageUrl = self.ninjaDocsBaseUrl + pageResponse["path"] + self.resolveSectionIdToAnchor(pageResponse, pageSelection)
            # save to cache
            self.urlCache.update({pageKey: (int(time.time()), pageUrl)})
            logger.debug(f"returning from api {pageKey} -> {pageUrl}")
            return pageUrl
        return None

    # resolve a gitbook page id to a usable url
    async def resolveGbPageIdToUrl(self, pageId: str) -> Union[str, None]:
        try:
            response = await self.doGbGetApiRequest(f"spaces/{self.bot.config.get('gitbookSpaceId')}/content/page/{pageId}", None)
            return response
        except Exception as E:
            logger.exception(E)
            return None

    # perform a get request to the gitbook api
    async def doGbGetApiRequest(self, endpoint: str, params: dict) -> Union[dict, None]:
        try:
            async with self.http.get(self.gbBaseUrl + endpoint, params=params, headers=self.gbHeaders) as resp:
                apiResponse = await resp.json(content_type="application/json")
                if resp.status == 200: return apiResponse
                return None
        except Exception as E:
            logger.exception(E)
            return None

    # perform a post request to the gitbook api
    async def doGbPostApiRequest(self, endpoint: str, data: dict) -> Union[dict, None]:
        try:
            async with self.http.post(self.gbBaseUrl + endpoint, json=data, headers=self.gbHeaders) as resp:
                apiResponse = await resp.json(content_type=None)
                logger.debug(await resp.text())
                logger.info(f"'status code': '{resp.status}', "\
                            f"'content_type': '{resp.content_type}', "\
                            f"'X-Ratelimit-Limit': '{resp.headers.get('X-Ratelimit-Limit')}', "\
                            f"'X-Ratelimit-Remaining': '{resp.headers.get('X-Ratelimit-Remaining')}', "\
                            f"'X-Ratelimit-Reset': '{resp.headers.get('X-Ratelimit-Reset')}'")
                # logger.debug(json.dumps(apiResponse, indent=2))
                if resp.status == 200: return apiResponse
                return None
        except Exception as E:
            logger.exception(E)
            return None

    async def cog_command_error(self, ctx, error) -> None:
        """Post error that happen inside this cog to channel"""
        await ctx.send(error)

    async def getCommands(self) -> list:
        """Return the available commands as a list"""
        return []

    async def cog_unload(self) -> None:
        logger.debug(f"Shutting down {self.__class__.__name__}")

async def setup(bot) -> None:
    await bot.add_cog(NinjaDocs(bot))