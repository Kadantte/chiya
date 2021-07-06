from discord.ext import commands
from discord.ext.commands import Cog, Bot

import config
from utils import embeds
from utils.record import record_usage
from discord_slash import cog_ext, SlashContext
from discord_slash.utils.manage_commands import create_permission
from discord_slash.model import SlashCommandPermissionType

class BoostersCog(Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.bot_has_permissions(send_messages=True)
    @commands.before_invoke(record_usage)
    @cog_ext.cog_slash(
        name="boosters", 
        description="List all the current server boosters",
        guild_ids=[config.guild_id],
        default_permission=False,
        permissions={
            config.guild_id: [
                create_permission(config.role_staff, SlashCommandPermissionType.ROLE, True),
                create_permission(config.role_trial_mod, SlashCommandPermissionType.ROLE, True)
            ]
        }
    )
    async def boosters(self, ctx: SlashContext):
        """ Sends a list of users boosting the server. """
        await ctx.defer()
        
        embed = embeds.make_embed(
            ctx=ctx, 
            title=f"Total boosts: {ctx.guild.premium_subscription_count}", 
            thumbnail_url=config.nitro, 
            color="nitro_pink", 
            author=False
        )
        embed.description = "\n".join(user.mention for user in ctx.guild.premium_subscribers)
        embed.set_footer(text=f"Total boosters: {len(ctx.guild.premium_subscribers)}")
        await ctx.send(embed=embed)

def setup(bot: Bot) -> None:
    """ Load the BoosterCog cog. """
    bot.add_cog(BoostersCog(bot))