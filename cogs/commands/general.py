import logging
from typing import Union
from utils.image_sauce import paginate_image_sauce

import discord
from discord.ext import commands
from discord.ext.commands import Bot, Cog
from discord_slash import cog_ext, SlashContext
from discord_slash.model import SlashCommandPermissionType
from discord_slash.utils.manage_commands import create_option, create_permission

from cogs.commands import settings
from utils import embeds
from utils.record import record_usage

log = logging.getLogger(__name__)


class General(Cog):
    """ General Commands Cog """

    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.before_invoke(record_usage)
    @commands.bot_has_permissions(embed_links=True)
    @cog_ext.cog_slash(
        name="pfp",
        description="Gets the members profile picture",
        guild_ids=[settings.get_value("guild_id")]
    )
    async def pfp(self, ctx: SlashContext, user: discord.User = None):
        """ Returns the profile picture of the invoker or the mentioned user. """
        await ctx.defer()

        user = user or ctx.author

        # If we received an int instead of a discord.Member, the user is not in the server.
        if isinstance(user, int):
            user = await self.bot.fetch_user(user)

        if ctx.author:
            embed = embeds.make_embed(ctx=ctx)

        if user:
            embed = embeds.make_embed()
            embed.set_author(icon_url=user.avatar_url, name=str(user))

        embed.set_image(url=user.avatar_url)
        await ctx.send(embed=embed)

    @cog_ext.cog_slash(
        name="population",
        description="Gets the current server population count",
        guild_ids=[settings.get_value("guild_id")],
        default_permission=False,
        permissions={
            settings.get_value("guild_id"): [
                create_permission(settings.get_value("role_staff"), SlashCommandPermissionType.ROLE, True),
                create_permission(settings.get_value("role_trial_mod"), SlashCommandPermissionType.ROLE, True)
            ]
        }
    )
    async def count(self, ctx: SlashContext):
        """Returns the current guild member count."""
        await ctx.defer()
        await ctx.send(ctx.guild.member_count)

    @commands.before_invoke(record_usage)
    @cog_ext.cog_slash(
        name="vote",
        description="Adds the vote reactions to a message",
        guild_ids=[settings.get_value("guild_id")],
        options=[
            create_option(
                name="message",
                description="The ID for the target message",
                option_type=3,
                required=False
            ),
        ],
        default_permission=False,
        permissions={
            settings.get_value("guild_id"): [
                create_permission(settings.get_value("role_staff"), SlashCommandPermissionType.ROLE, True),
                create_permission(settings.get_value("role_trial_mod"), SlashCommandPermissionType.ROLE, True)
            ]
        }
    )
    async def vote(self, ctx, message: discord.Message = None):
        """ Add vote reactions to a message. """
        await ctx.defer()

        if message:
            message = await ctx.channel.fetch_message(message)

        if not message:
            messages = await ctx.channel.history(limit=1).flatten()
            message = messages[0]

        await message.add_reaction(":yes:778724405333196851")
        await message.add_reaction(":no:778724416230129705")

        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
                await ctx.message.delete()
            except discord.errors.HTTPException:
                pass
    
    @commands.before_invoke(record_usage)
    @cog_ext.cog_slash(
        name="sauce",
        description="Looks for sauce of an image.",
        guild_ids=[settings.get_value("guild_id")],
        options=[
            create_option(
                name="image_url",
                description="The image url.",
                option_type=3,
                required=True
            ),
        ],
    )
    async def sauce(self, ctx: SlashContext, image_url: str):
        await ctx.defer()
        await paginate_image_sauce(ctx, image_url)


def setup(bot: Bot) -> None:
    """ Load the General cog. """
    bot.add_cog(General(bot))
    log.info("Commands loaded: general")
