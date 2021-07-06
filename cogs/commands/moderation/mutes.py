import datetime
import logging
import re
import time

import dataset
import discord
import privatebinapi
from discord.ext import commands
from discord.ext.commands import Cog, Bot
from discord_slash import cog_ext, SlashContext
from discord_slash.utils.manage_commands import create_option, create_permission
from discord_slash.model import SlashCommandPermissionType

import config
from utils import database
from utils import embeds
from utils.record import record_usage
from utils.moderation import can_action_member

# Enabling logs
log = logging.getLogger(__name__)

class MuteCog(Cog):
    """ Mute Cog """

    def __init__(self, bot):
        self.bot = bot

    async def mute_member(self, ctx: SlashContext, member: discord.Member, reason: str, temporary: bool = False, end_time: float = None) -> None:
        role = discord.utils.get(ctx.guild.roles, id=config.role_muted)
        await member.add_roles(role, reason=reason)

        # Add the mute to the mod_log database.
        with dataset.connect(database.get_db()) as db:
            db["mod_logs"].insert(dict(
                user_id=member.id, mod_id=ctx.author.id, timestamp=int(time.time()), reason=reason, type="mute"
            ))

            # Occurs when the mute function is invoked as /tempmute instead of /mute.
            if temporary:
                db["timed_mod_actions"].insert(dict(
                user_id=member.id,
                mod_id=ctx.author.id,
                action_type="mute",
                reason=reason,
                start_time=datetime.datetime.now(tz=datetime.timezone.utc).timestamp(),
                end_time=end_time.timestamp(),
                is_done=False
            ))

    async def unmute_member(self, member: discord.Member, reason: str, ctx: SlashContext = None, guild: discord.Guild = None) -> None:
        guild = guild or ctx.guild
        moderator = ctx.author if ctx else self.bot.user

        # Removes "Muted" role from member.
        role = discord.utils.get(guild.roles, id=config.role_muted)
        await member.remove_roles(role, reason=reason)
        
        # Add the unmute to the mod_log database.
        with dataset.connect(database.get_db()) as db:
            db["mod_logs"].insert(dict(
                user_id=member.id, mod_id=moderator.id, timestamp=int(time.time()), reason=reason, type="unmute"
            ))

    async def is_user_muted(self, ctx: SlashContext, member: discord.Member) -> bool:
        if discord.utils.get(ctx.guild.roles, id=config.role_muted) in member.roles:
            return True
        return False

    async def send_muted_dm_embed(self, ctx: SlashContext, member: discord.Member, channel: discord.TextChannel, reason: str = None, duration: str = None) -> bool:
        if not duration:
            duration = "Indefinite"

        try: # Incase user has DM's Blocked.
            dm_channel = await member.create_dm()
            embed = embeds.make_embed(author=False, color=0x8083b0)
            embed.title = f"Uh-oh, you've been muted!"
            embed.description = "If you believe this was a mistake, contact staff."
            embed.add_field(name="Server:", value=ctx.guild, inline=True)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=True)
            embed.add_field(name="Length:", value=duration, inline=True)
            embed.add_field(name="Mute Channel:", value=channel.mention, inline=True)
            embed.add_field(name="Reason:", value=reason, inline=False)
            embed.set_image(url="https://i.imgur.com/KE1jNl3.gif")
            await dm_channel.send(embed=embed)
            return True
        except discord.errors.Forbidden:
            return False

    async def send_unmuted_dm_embed(self, member: discord.Member, reason: str, ctx: SlashContext = None, guild: discord.Guild = None) -> bool:
        guild = guild or ctx.guild
        moderator = ctx.author if ctx else self.bot.user

        # Send member message telling them that they were banned and why.
        try: # Incase user has DM's Blocked.
            channel = await member.create_dm()
            embed = embeds.make_embed(author=False, color=0x8a3ac5)
            embed.title = f"Yay, you've been unmuted!"
            embed.description = "Review our server rules to avoid being actioned again in the future."
            embed.add_field(name="Server:", value=guild, inline=True)
            embed.add_field(name="Moderator:", value=moderator.mention, inline=True)
            embed.add_field(name="Reason:", value=reason, inline=False)
            embed.set_image(url="https://i.imgur.com/U5Fvr2Y.gif")
            await channel.send(embed=embed)
            return True
        except discord.errors.Forbidden:
            return False

    async def create_mute_channel(self, ctx: SlashContext, member: discord.Member, reason=str, duration: str = None) -> int:
        if not duration:
            duration = "Indefinite"

        # Create a channel in the category specified in the config.     
        category = discord.utils.get(ctx.guild.categories, id=config.ticket_category_id)
        channel = await ctx.guild.create_text_channel(f"mute-{member.id}", category=category)

        # Give both the staff and the user perms to access the channel. 
        await channel.set_permissions(discord.utils.get(ctx.guild.roles, id=config.role_trial_mod), read_messages=True)
        await channel.set_permissions(discord.utils.get(ctx.guild.roles, id=config.role_staff), read_messages=True)
        await channel.set_permissions(member, read_messages=True)

        # Create embed at the start of the channel letting the user know how long they're muted for and why.
        embed = embeds.make_embed(title="🤐 You were muted", description="If you have any questions or concerns about your mute, you may voice them here.")
        embed.add_field(name="User:", value=member.mention, inline=True)
        embed.add_field(name="Moderator:", value=ctx.author.mention, inline=True)
        embed.add_field(name="Length:", value=duration, inline=True)
        embed.add_field(name="Reason:", value=reason, inline=False)
        await channel.send(embed=embed)

        # Embed mentions don't count as a ping so this is a workaround to that.
        ping = await channel.send(member.mention)
        await ping.delete()

        return channel

    async def archive_mute_channel(self, user_id: int, reason: str, ctx: SlashContext = None, guild: int = None):
        guild = guild or ctx.guild
        moderator = ctx.author_id if ctx else self.bot.user.id
        category = discord.utils.get(guild.categories, id=config.ticket_category_id)
        mute_channel = discord.utils.get(category.channels, name=f"mute-{user_id}")

        # TODO: Get the mute reason by looking up the latest mute for the user and getting the reason column data.
        with dataset.connect(database.get_db()) as db:
            table = db["mod_logs"]
            # Gets the most recent mute for the user, sorted by descending (-) ID.
            data = table.find_one(user_id=user_id, type="mute", order_by="-id")
            mute_reason = data["reason"]
            moderator = await self.bot.fetch_user(data["mod_id"])

        # Get the member object of the ticket creator.
        member = await self.bot.fetch_user(user_id)

        # Initialize the PrivateBin message log string.
        message_log = (
            f"Muted User: {member} ({member.id})\n"
            f"Muted By: {moderator} ({moderator.id})\n"
            f"Mute Reason: {mute_reason}\n"
        )

        # Initialize a list of moderator IDs as a set for no duplicates.
        mod_list = set()

        # Add the original muting moderator to avoid a blank embed field if no one interacts.
        mod_list.add(moderator)

        # Fetch the staff and trial mod role.
        role_staff = discord.utils.get(guild.roles, id=config.role_staff)
        role_trial_mod = discord.utils.get(guild.roles, id=config.role_trial_mod)

        # TODO: Implement so it gets the channel when the moderator is the bot
        # Loop through all messages in the ticket from old to new.
        async for message in mute_channel.history(oldest_first=True):
            # Ignore the bot replies.
            if not message.author.bot:
                # Time format is unnecessarily lengthy so trimming it down and keep the log go easier on the eyes.
                formatted_time = str(message.created_at).split(".")[-2]
                # Append the new messages to the current log as we loop.
                message_log += f"[{formatted_time}] {message.author}: {message.content}\n"
                # If the messenger has either staff role or trial mod role, add their ID to the mod_list set.
                if role_staff in message.author.roles or role_trial_mod in message.author.roles:
                    mod_list.add(message.author)

        # Dump message log to PrivateBin. This returns a dictionary, but only the url is needed for the embed.
        url = privatebinapi.send("https://bin.piracy.moe", text=message_log, expiration="never")["full_url"]

        # Create the embed in #mute-log.
        embed = embeds.make_embed(
            title = f"{mute_channel.name} archived",
            thumbnail_url=config.pencil, 
            color="blurple"
        )

        embed.add_field(name="Muted User:", value=member.mention, inline=True)
        embed.add_field(name="Muted By:", value=moderator.mention, inline=True)
        embed.add_field(name="Mute Reason:", value=mute_reason, inline=False)
        embed.add_field(name="Participating Moderators:", value=" ".join(mod.mention for mod in mod_list), inline=False)
        embed.add_field(name="Mute Log: ", value=url, inline=False)

        # Send the embed to #mute-log.
        mute_log = discord.utils.get(guild.channels, id=config.mute_log)
        await mute_log.send(embed=embed)

        # Add the unmute to the mod_logs database.
        with dataset.connect(database.get_db()) as db:
            db["mod_logs"].insert(dict(
                user_id=user_id, mod_id=moderator.id, timestamp=int(time.time()), reason=reason, type="unmute"
            ))
        
        # Delete the mute channel.
        await mute_channel.delete()

    @commands.bot_has_permissions(manage_roles=True, send_messages=True)
    @commands.before_invoke(record_usage)
    @cog_ext.cog_slash(
        name="mute", 
        description="Mutes the member indefinitely",
        guild_ids=[config.guild_id],
        options=[
            create_option(
                name="member",
                description="The member that will be muted",
                option_type=6,
                required=True
            ),
            create_option(
                name="reason",
                description="The reason why the member is being muted",
                option_type=3,
                required=False
            ),
        ],
        default_permission=False,
        permissions={
            config.guild_id: [
                create_permission(config.role_staff, SlashCommandPermissionType.ROLE, True),
                create_permission(config.role_trial_mod, SlashCommandPermissionType.ROLE, True)
            ]
        }
    )
    async def mute(self, ctx: SlashContext, member: discord.User, reason: str = None):
        """ Mutes member in guild. """
        await ctx.defer()

        # If we received an int instead of a discord.Member, the user is not in the server.
        if isinstance(member, int):
            await embeds.error_message(ctx=ctx, description=f"That user is not in the server.")
            return
        
        # Checks if invoker can action that member (self, bot, etc.)
        if not await can_action_member(bot=self.bot, ctx=ctx, member=member):
            await embeds.error_message(ctx=ctx, description=f"You cannot action {member.mention}.")
            return
        
        # Check if the user is muted already.
        if await self.is_user_muted(ctx=ctx, member=member):
            await embeds.error_message(ctx=ctx, description=f"{member.mention} is already muted.")
            return
        
        # Automatically default the reason string to N/A when the moderator does not provide a reason.
        if not reason:
            reason = "No reason provided."

        # Discord caps embed fields at a riduclously low character limit, avoids problems with future embeds.
        if len(reason) > 512:
            await embeds.error_message(ctx=ctx, description="Reason must be less than 512 characters.")
            return

        # Start creating the embed that will be used to alert the moderator that the user was successfully muted.
        embed = embeds.make_embed(ctx=ctx, title=f"Muting member: {member.name}", color="soft_red", thumbnail_url=config.user_mute)
        embed.description=f"{member.mention} was muted by {ctx.author.mention} for: {reason}"
        
        # Create the mute channel in the Staff category.
        channel = await self.create_mute_channel(ctx=ctx, member=member, reason=reason)

        # Attempt to DM the user to let them know they were muted.
        if not await self.send_muted_dm_embed(ctx=ctx, member=member, channel=channel, reason=reason):
            embed.add_field(name="Notice:", value=f"Unable to message {member.mention} about this action. This can be caused by the user not being in the server, having DMs disabled, or having the bot blocked.")

        # Mutes the user and returns the embed letting the moderator know they were successfully muted.
        await self.mute_member(ctx=ctx, member=member, reason=reason)
        await ctx.send(embed=embed)

    @commands.bot_has_permissions(manage_roles=True, send_messages=True)
    @commands.before_invoke(record_usage)
    @cog_ext.cog_slash(
        name="unmute", 
        description="Unmutes the member",
        guild_ids=[config.guild_id],
        options=[
            create_option(
                name="member",
                description="The member that will be unmuted",
                option_type=6,
                required=True
            ),
            create_option(
                name="reason",
                description="The reason why the member is being unmuted",
                option_type=3,
                required=False
            ),
        ],
        default_permission=False,
        permissions={
            config.guild_id: [
                create_permission(config.role_staff, SlashCommandPermissionType.ROLE, True),
                create_permission(config.role_trial_mod, SlashCommandPermissionType.ROLE, True)
            ]
        }
    )
    @commands.command(name="unmute")
    async def unmute(self, ctx: SlashContext, member: discord.User, reason: str = None):
        """ Unmutes member in guild. """
        await ctx.defer()

        # If we received an int instead of a discord.Member, the user is not in the server.
        if isinstance(member, int):
            await embeds.error_message(ctx=ctx, description=f"That user is not in the server.")
            return

        # Checks if invoker can action that member (self, bot, etc.)
        if not await can_action_member(bot=self.bot, ctx=ctx, member=member):
            await embeds.error_message(ctx=ctx, description=f"You cannot action {member.mention}.")
            return
        
        # Check if the user is not muted already.
        if not await self.is_user_muted(ctx=ctx, member=member):
            await embeds.error_message(ctx=ctx, description=f"{member.mention} is not muted.")
            return

        # Automatically default the reason string to N/A when the moderator does not provide a reason.
        if not reason:
            reason = "No reason provided."

        # Discord caps embed fields at a riduclously low character limit, avoids problems with future embeds.
        if len(reason) > 512:
            await embeds.error_message(ctx=ctx, description="Reason must be less than 512 characters.")
            return

        # Start creating the embed that will be used to alert the moderator that the user was successfully muted.
        embed = embeds.make_embed(ctx=ctx, title=f"Unmuting member: {member.name}", color="soft_green", thumbnail_url=config.user_unmute)
        embed.description=f"{member.mention} was unmuted by {ctx.author.mention} for: {reason}"
        
        # Unmutes the user and and archives the channel.
        await self.archive_mute_channel(ctx=ctx, user_id=member.id, reason=reason)
        await self.unmute_member(ctx=ctx, member=member, reason=reason)

        # Attempt to DM the user to let them know they were muted and let's the moderator know they were unmuted.
        if not await self.send_unmuted_dm_embed(ctx=ctx, member=member, reason=reason):
            embed.add_field(name="Notice:", value=f"Unable to message {member.mention} about this action. This can be caused by the user not being in the server, having DMs disabled, or having the bot blocked.")

        # If the mod sent the /unmute in the mute channel, this will cause a errors.NotFound 404.
        # We cannot send the embed and then archive the channel because that will cause a error.AlreadyResponded.
        try:
            await ctx.send(embed=embed)
        except discord.errors.NotFound:
            pass

    @commands.bot_has_permissions(manage_roles=True, send_messages=True)
    @commands.before_invoke(record_usage)
    @cog_ext.cog_slash(
        name="tempmute", 
        description="Mutes the member for the specified length of time",
        guild_ids=[config.guild_id],
        options=[
            create_option(
                name="member",
                description="The member that will be muted",
                option_type=6,
                required=True
            ),
            create_option(
                name="duration",
                description="The length of time the user will be muted for",
                option_type=3,
                required=True
            ),
            create_option(
                name="reason",
                description="The reason why the member is being unmuted",
                option_type=3,
                required=False
            ),
        ],
        default_permission=False,
        permissions={
            config.guild_id: [
                create_permission(config.role_staff, SlashCommandPermissionType.ROLE, True),
                create_permission(config.role_trial_mod, SlashCommandPermissionType.ROLE, True)
            ]
        }
    )
    async def tempmute(self, ctx: SlashContext, member: discord.User, duration: str, reason: str = None):
        """ Temporarily Mutes member in guild. """
        await ctx.defer()

        # If we received an int instead of a discord.Member, the user is not in the server.
        if isinstance(member, int):
            await embeds.error_message(ctx=ctx, description=f"That user is not in the server.")
            return

        # Checks if invoker can action that member (self, bot, etc.)
        if not await can_action_member(bot=self.bot, ctx=ctx, member=member):
            await embeds.error_message(ctx=ctx, description=f"You cannot action {member.mention}.")
            return

        # Check if the user is muted already.
        if await self.is_user_muted(ctx=ctx, member=member):
            await embeds.error_message(ctx=ctx, description=f"{member.mention} is already muted.")
            return
        
        # RegEx stolen from Setsudo and modified
        regex = r"((?:(\d+)\s*d(?:ays)?)?\s*(?:(\d+)\s*h(?:ours|rs|r)?)?\s*(?:(\d+)\s*m(?:inutes|in)?)?\s*(?:(\d+)\s*s(?:econds|ec)?)?)"

        # Get all of the matches from the RegEx.
        try:
            match_list = re.findall(regex, duration)[0]
        except:
            await embeds.error_message(ctx=ctx, description="Duration syntax: `#d#h#m#s` (day, hour, min, sec)\nYou can specify up to all four but you only need one.")
            return

        # Check if all the matches are blank and return preemptively if so.
        if not any(x.isalnum() for x in match_list):
            await embeds.error_message(ctx=ctx, description="Duration syntax: `#d#h#m#s` (day, hour, min, sec)\nYou can specify up to all four but you only need one.")
            return

        # Automatically default the reason string to N/A when the moderator does not provide a reason.
        if not reason:
            reason = "No reason provided."

        # Discord caps embed fields at a riduclously low character limit, avoids problems with future embeds.
        if len(reason) > 512:
            await embeds.error_message(ctx=ctx, description="Reason must be less than 512 characters.")
            return
        
        duration = dict(
            days = match_list[1],
            hours = match_list[2],
            minutes = match_list[3],
            seconds = match_list[4]
        )
        
        # String that will store the duration in a more digestible format.
        duration_string = ""
        
        for time_unit in duration:
            if len(duration[time_unit]):
                duration_string += f"{duration[time_unit]} {time_unit} "
                # updating the values for ease of conversion to timedelta object later.
                duration[time_unit] = float(duration[time_unit])
            else:
                # value defaults to 0 in case nothing was mentioned
                duration[time_unit] = 0

        mute_end_time = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(
            days = duration["days"],
            hours = duration["hours"],
            minutes = duration["minutes"],
            seconds = duration["seconds"]
        ) 

        # Start creating the embed that will be used to alert the moderator that the user was successfully muted.
        embed = embeds.make_embed(ctx=ctx, title=f"Muting member: {member}", thumbnail_url=config.user_mute, color="soft_red")
        embed.description=f"{member.mention} was muted by {ctx.author.mention} for:\n{reason}\n **Duration:** {duration_string}"
        
        # Create the mute channel in the Staff category.
        channel = await self.create_mute_channel(ctx=ctx, member=member, reason=reason, duration=duration_string)
        
        # Attempt to DM the user to let them know they were muted.
        if not await self.send_muted_dm_embed(ctx=ctx, member=member, channel=channel, reason=reason, duration=duration_string):
            embed.add_field(name="Notice:", value=f"Unable to message {member.mention} about this action. This can be caused by the user not being in the server, having DMs disabled, or having the bot blocked.")

        # Mutes the user and stores the unmute time in the database for the background task.
        await self.mute_member(ctx=ctx, member=member, reason=reason, temporary=True, end_time=mute_end_time)
        await ctx.send(embed=embed)

def setup(bot: Bot) -> None:
    """ Load the Mute cog. """
    bot.add_cog(MuteCog(bot))
    log.info("Commands loaded: mutes")
