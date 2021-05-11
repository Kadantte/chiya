import logging
import requests

from discord.ext import commands
from discord.ext.commands import Bot, Cog, Context

import config
from utils import embeds
from utils.record import record_usage

log = logging.getLogger(__name__)

class TrackerStatus(Cog):
    """ Tracker status Commands Cog """

    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.before_invoke(record_usage)
    @commands.bot_has_permissions(embed_links=True)
    @commands.command(name='status', aliases=["ts", "trackerstatus"])
    async def tracker_status(self, ctx: Context, tracker: str):
        """ Returns the status of a private tracker, currently accepts: AR, BTN, GGn, MTV, PTP, RED, and OPS. """
        
        # tracker name aliases, recognition is case-insensitive and exact spelling.
        tracker_name_aliases = {
            'AlphaRatio' : ['ar', 'alpharatio', 'alpharatio.cc'],
            'BroadcasTheNet' : ['btn', 'broadcasthenet', 'broadcasthe.net'],
            'GazelleGames' : ['ggn', 'gazellegames', 'gazellegames.net'],
            'MoreThanTV' : ['mtv', 'morethantv', 'morethantv.me'],
            'PassThePopcorn' : ['ptp', 'passthepopcorn', 'passthepopcorn.me'],
            'Redacted' : ['red', 'redacted', 'redacted.ch'],
            'Orpheus' : ['ops', 'orpheus', 'orpheus.network']
        }
        
        # lowercasing to avoid the issue of adding a LOT of aliases.
        tracker = tracker.lower()

        for key in tracker_name_aliases:
            if tracker == key.lower() or tracker in tracker_name_aliases[key]:
                tracker = key
                break

        # A list of the TrackerStatus.info APIs to query
        tracker_status_apis = {
            "AlphaRatio": "https://ar.trackerstatus.info/api/all/",
            "BroadcasTheNet": "https://btn.trackerstatus.info/api/all/",
            "GazelleGames": "https://ggn.trackerstatus.info/api/all/",
            "MoreThanTV": "https://mtv.trackerstatus.info/api/all/",
            "PassThePopcorn": "https://ptp.trackerstatus.info/api/all/",
            "Redacted": "https://red.trackerstatus.info/api/all/",
            "Orpheus": "https://ops.trackerstatus.info/api/all/",
        }

        # A list of tracker specific APIs to query
        tracker_specific_apis = {
            "AnimeBytes": "https://status.animebytes.tv/api/status"
        }

        # Query the relevant trackers API and return the JSON response
        try:
            r = requests.get(tracker_status_apis[tracker])
        except KeyError:
            await embeds.error_message(ctx, "The specified term isn't a recognized tracker name or alias.")
            return
        json = r.json()

        # Create the embed to send 
        embed = embeds.make_embed(ctx=ctx, title=tracker)

        # Loop over the JSON data returned in response
        for service in json.items():
            # name is a string containing the name of service
            # data is a dictionary containing the key: values of the data responses
            name, data = service

            # Skip over the tweets as we don't care about those
            if name == "tweet":
                continue
            
            # Loop over the keys in the data response
            for key in data:

                # Setup a map to replace service names with something more digestible
                name_renaming_map = {
                    "TrackerHTTP": "Tracker (HTTP):",
                    "TrackerHTTPS": "Tracker (HTTPS):",
                    "IRCPersona": "IRC Server:",
                    "IRCTorrentAnnouncer": "Torrent Announcer:",
                    "IRCUserIdentifier": "IRC Authentication:",
                    "Barney": "Torrent Announcer:", # BTN
                    "CableGuy": "IRC Authentication:", # BTN
                }

                # Replace any service names found in name_renaming_map
                if name in name_renaming_map:
                    name = name_renaming_map[name]

                # Replace the status response with something more digestible
                if key == "Status":
                    data[key] = data[key].replace("1", ":green_circle: Online")
                    data[key] = data[key].replace("2", ":yellow_circle: Unstable")
                    data[key] = data[key].replace("0", ":red_circle: Offline")
            
            # Add the key and the value into an embed field
            embed.add_field(name=name, value=f"{data.get('Status')}")

        # Send the embed
        await ctx.reply(embed=embed)


def setup(bot: Bot) -> None:
    """ Load the TrackerStatus cog. """
    bot.add_cog(TrackerStatus(bot))
    log.info("Commands loaded: trackerstatus")
